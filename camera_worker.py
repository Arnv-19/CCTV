"""
camera_worker.py
----------------
Per-camera capture and detection loop, designed to run in a dedicated thread.

Each camera gets one thread running camera_loop(). The loop:
  1. Opens the RTSP stream with OpenCV
  2. Reads frames continuously
  3. Resizes each frame and runs YOLOv8 inference
  4. If a violation is detected:
       - Saves a snapshot JPEG to snapshots/cam_{id}/
       - Logs the alert to PostgreSQL (via alert_queue — non-blocking)
       - Fires the assigned buzzers for this camera
  5. Draws bounding boxes and stats overlay
  6. Encodes the annotated frame as JPEG and writes it to frame_dict
     for the MJPEG streaming endpoint

alert_queue is a thread-safe Queue processed by AlertWriter (background thread
in camera_manager) so DB writes never slow down frame processing.
"""

import cv2
import time
import os
import threading
from datetime import datetime
from pathlib import Path
from queue import Queue

import mediapipe as mp
from mediapipe.tasks.python import vision as _mp_vision
from mediapipe.tasks.python import BaseOptions as _MpBaseOptions

_HAND_LANDMARKER_PATH = str(
    __import__("pathlib").Path(__file__).parent / "weights" / "hand_landmarker.task"
)

from alarm import send_buzzer_command
from detector import run_detection


def ensure_dir(path: str):
    """Create a directory (and parents) if it does not already exist."""
    Path(path).mkdir(parents=True, exist_ok=True)


def save_snapshot(frame, cam_id: int, snapshot_dir: str) -> str | None:
    """
    Save the current frame as a JPEG snapshot.
    Returns the relative path string, or None on failure.
    """
    try:
        cam_dir = Path(snapshot_dir) / f"cam_{cam_id}"
        ensure_dir(str(cam_dir))
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filename = f"violation_{ts}.jpg"
        filepath = cam_dir / filename
        cv2.imwrite(str(filepath), frame)
        return str(filepath)
    except Exception as e:
        print(f"[Camera {cam_id}] Snapshot save failed: {e}")
        return None


def log_violation_file(cam_id: int, frame_index: int, violation_rate: float):
    """Append a violation line to the flat-file log (kept for backward compat)."""
    ensure_dir("logs")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("logs/alerts.log", "a") as f:
        f.write(
            f"[{now}] Camera {cam_id} | Frame {frame_index} | No helmet | Rate: {violation_rate:.2f}%\n"
        )


def fire_buzzers(buzzers: list, cam_id: int) -> bool:
    """
    Trigger all active buzzers assigned to this camera.
    Returns True if at least one buzzer was fired.
    `buzzers` is a list of Buzzer ORM-like dicts captured at thread-start.
    """
    fired = False
    for b in buzzers:
        if not b.get("is_active"):
            continue
        try:
            protocol = b.get("protocol", "usb")
            send_buzzer_command(
                state=True,
                use_wifi=(protocol == "http"),
                esp_ip=b.get("ip_address"),
                transport=protocol,
                mqtt_broker=b.get("ip_address", "") if protocol == "mqtt" else "",
                mqtt_port=b.get("port") or 1883,
                camera_id=cam_id,
            )
            fired = True
        except Exception as e:
            print(f"[Camera {cam_id}] Buzzer fire error (buzzer {b.get('id')}): {e}")
    return fired


def camera_loop(
    # ── required positional args ───────────────────────────────────────────
    cam_id: int,
    stream_url: str,
    model,                          # shared YOLO model instance
    threshold: float,
    helmet_class: str,
    no_helmet_class: str,
    cooldown: float,
    use_wifi: bool,                 # legacy fallback
    esp_ip: str | None,            # legacy fallback
    frame_dict: dict,               # {cam_id: jpeg_bytes} for MJPEG endpoint
    lock: threading.Lock,
    # ── optional keyword args ─────────────────────────────────────────────
    stop_event: threading.Event = None,
    stats_dict: dict = None,
    alarm_transport: str | None = None,
    alarm_http_token: str = "",
    mqtt_broker: str = "",
    mqtt_port: int = 1883,
    mqtt_username: str = "",
    mqtt_password: str = "",
    mqtt_topic: str = "skycctv/alarm",
    mqtt_client_id: str = "skycctv-ai",
    mqtt_qos: int = 1,
    mqtt_retain: bool = False,
    # ── new: DB-backed features ───────────────────────────────────────────
    assigned_buzzers: list = None,  # list of buzzer dicts fetched from DB at start
    alert_queue: Queue = None,      # queue to AlertWriter for non-blocking DB logging
    snapshot_dir: str = "snapshots",
    enabled_models: list = None,    # list of model_name strings enabled for this camera
    violation_classes: list = None, # PPE classes that trigger an alarm
    safe_classes: list = None,      # PPE classes shown with green bounding box
    gloves_model = None,            # optional second model for gloves/bare-hands detection
):
    """
    Main per-camera loop. Blocks until the stream ends or stop_event is set.

    New behaviour vs original:
      - Uses assigned_buzzers (from DB) instead of global alarm config
      - Saves snapshot images and queues alert records for DB logging
      - Falls back to legacy alarm.py transport if no DB buzzers are assigned
    """

    # Build sets for O(1) look-ups; fall back to legacy single-class args
    _violation_set: set = set(violation_classes) if violation_classes else (
        {no_helmet_class} if no_helmet_class else set()
    )
    _safe_set: set = set(safe_classes) if safe_classes else (
        {helmet_class} if helmet_class else set()
    )

    # Per-camera enabled model filtering.
    # None = no DB config → all models run (backward-compat default).
    # Empty list = every model explicitly disabled → nothing triggers alarms.
    _enabled_set: set | None = set(enabled_models) if enabled_models is not None else None

    # Human-readable label overrides for the live stream overlay.
    # Keys are the raw class names the model emits; values are what is shown on screen.
    _DISPLAY_NAMES: dict = {
        # Helmet / hardhat
        "NO-Hardhat":       "No Helmet",
        "NO-Hat":           "No Helmet",
        "Hardhat":          "Helmet",
        "Hat":              "Helmet",
        "no_helmet":        "No Helmet",
        "helmet":           "Helmet",
        # Vest
        "NO-Safety Vest":   "No Vest",
        "Safety Vest":      "Vest",
        "no_vest":          "No Vest",
        "vest":             "Vest",
        # Goggles / glasses
        "NO-Goggles":       "No Goggles",
        "Goggles":          "Goggles",
        # Gloves
        "Gloves":           "Gloves",
        "NO-Gloves":        "No Gloves",
        "bare_hand":        "Bare Hand",
        "bare_hands":       "Bare Hands",
        # Mask
        "Mask":             "Mask",
        "NO-Mask":          "No Mask",
    }

    # Map each detection class name to its logical model name.
    # Extend aliases whenever a new class label variant appears in model outputs.
    _CLASS_TO_MODEL: dict = {
        # Helmet / hardhat
        "no_helmet":        "helmet_detection",
        "helmet":           "helmet_detection",
        "no-hardhat":       "helmet_detection",
        "no_hardhat":       "helmet_detection",
        "hardhat":          "helmet_detection",
        "no-hat":           "helmet_detection",
        "no_hat":           "helmet_detection",
        "hat":              "helmet_detection",

        # Vest
        "no_vest":          "vest_detection",
        "vest":             "vest_detection",
        "no-safety vest":   "vest_detection",
        "no_safety_vest":   "vest_detection",
        "safety vest":      "vest_detection",
        "safety_vest":      "vest_detection",

        # Goggles / glasses
        "no_glasses":       "glasses_detection",
        "glasses":          "glasses_detection",
        "no-goggles":       "glasses_detection",
        "no_goggles":       "glasses_detection",
        "goggles":          "glasses_detection",

        # Gloves
        "no_gloves":        "gloves_detection",
        "gloves":           "gloves_detection",
        "bare_hand":        "gloves_detection",
        "bare_hands":       "gloves_detection",

        # Mask
        "no-mask":          "mask_detection",
        "no_mask":          "mask_detection",
        "mask":             "mask_detection",

        # Fire
        "fire":             "fire_detection",
    }

    def _model_for_class(class_name: str) -> str | None:
        if not class_name:
            return None
        key = class_name.strip().lower()
        if key in _CLASS_TO_MODEL:
            return _CLASS_TO_MODEL[key]

        # Normalize separators for variants like "NO-Hardhat" vs "NO_Hardhat".
        key_norm = key.replace("-", "_").replace(" ", "_")
        return _CLASS_TO_MODEL.get(key_norm)

    # Only initialise the gloves model if gloves_detection is enabled for this camera
    _run_gloves = (
        gloves_model is not None
        and (_enabled_set is None or "gloves_detection" in _enabled_set)
    )

    # MediaPipe hands detector — used to get real hand bounding boxes
    _mp_hands = None
    if _run_gloves:
        _opts = _mp_vision.HandLandmarkerOptions(
            base_options=_MpBaseOptions(model_asset_path=_HAND_LANDMARKER_PATH),
            num_hands=4,
            min_hand_detection_confidence=0.5,
        )
        _mp_hands = _mp_vision.HandLandmarker.create_from_options(_opts)

    def set_stats(status: str, fps: float = 0, violations: int = 0, frames: int = 0):
        if stats_dict is not None:
            with lock:
                stats_dict[cam_id] = {
                    "status": status, "fps": fps,
                    "violations": violations, "frames": frames,
                }

    # Convert numeric string to int so cv2 treats it as a device index (e.g. "0" → webcam)
    source = int(stream_url) if isinstance(stream_url, str) and stream_url.isdigit() else stream_url
    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"[Camera {cam_id}] Failed to open stream: {stream_url}")
        set_stats("error")
        return

    frame_count = 0
    violations  = 0
    last_alarm_time = 0
    reconnect_attempts = 0
    max_reconnect_attempts = 10
    RESIZE_DIM = (640, 480)

    set_stats("connecting", 0, violations, frame_count)

    while True:
        if stop_event is not None and stop_event.is_set():
            break

        ret, frame = cap.read()
        if not ret:
            reconnect_attempts += 1
            print(
                f"[Camera {cam_id}] Frame read failed "
                f"(attempt {reconnect_attempts}/{max_reconnect_attempts})"
            )
            set_stats("reconnecting", 0, violations, frame_count)

            try:
                cap.release()
            except Exception:
                pass

            # Interruptible sleep — respond to stop_event within 100 ms
            for _ in range(7):
                if stop_event is not None and stop_event.is_set():
                    break
                time.sleep(0.1)
            if stop_event is not None and stop_event.is_set():
                break

            cap = cv2.VideoCapture(source)
            if cap.isOpened():
                # Don't reset reconnect_attempts here — only reset on a
                # successful frame read. If the source reopens but keeps
                # dropping frames we still need to hit the retry limit.
                continue

            if reconnect_attempts >= max_reconnect_attempts:
                print(f"[Camera {cam_id}] Stream unavailable after retries")
                set_stats("error", 0, violations, frame_count)
                break
            continue

        reconnect_attempts = 0

        frame_count += 1
        start = time.time()
        resized = cv2.resize(frame, RESIZE_DIM)

        detections = run_detection(model, resized, threshold)
        # Gloves model — only run if gloves_detection is enabled for this camera
        gloves_detections = run_detection(gloves_model, resized, threshold) if _run_gloves else []

        # Apply per-camera model filtering once so disabled models are neither
        # considered for alarms nor rendered in the live stream overlay.
        filtered_detections = []
        for det in detections + gloves_detections:
            model_name = _model_for_class(det["class"])
            if _enabled_set is not None and model_name and model_name not in _enabled_set:
                continue
            filtered_detections.append(det)

        # ── violation handling ─────────────────────────────────────────────
        violation_found = False
        for det in filtered_detections:
            if det["class"] in _violation_set:
                now = time.time()

                # Cooldown check — only count + act once per cooldown window
                effective_cooldown = max(0.0, float(cooldown or 0))
                if now - last_alarm_time > effective_cooldown:
                    last_alarm_time = now
                    violations += 1
                    violation_found = True

                    # Save snapshot
                    snap_path = save_snapshot(resized, cam_id, snapshot_dir)

                    # Fire buzzers (DB-assigned or legacy fallback)
                    buzzer_fired = False
                    if assigned_buzzers:
                        buzzer_fired = fire_buzzers(assigned_buzzers, cam_id)
                    else:
                        # Legacy path — use alarm.py global config
                        from alarm import trigger_alarm
                        trigger_alarm(
                            cam_id, cooldown,
                            use_wifi=use_wifi, esp_ip=esp_ip,
                            transport=alarm_transport, token=alarm_http_token,
                            mqtt_broker=mqtt_broker, mqtt_port=mqtt_port,
                            mqtt_username=mqtt_username, mqtt_password=mqtt_password,
                            mqtt_topic=mqtt_topic, mqtt_client_id=mqtt_client_id,
                            mqtt_qos=mqtt_qos, mqtt_retain=mqtt_retain,
                        )
                        buzzer_fired = True

                    # Queue DB alert (non-blocking)
                    if alert_queue is not None:
                        alert_queue.put({
                            "camera_id":        cam_id,
                            "model_name":       "ppe_detection",
                            "violation_type":   det["class"],
                            "confidence_score": det["conf"],
                            "snapshot_path":    snap_path,
                            "buzzer_activated": buzzer_fired,
                        })

                    log_violation_file(cam_id, frame_count, (violations / frame_count) * 100)
                break   # one violation event per frame

        # ── draw detections (filtered by enabled per-camera models) ────────
        for det in filtered_detections:
            x1, y1, x2, y2 = map(int, det["box"])
            class_name = det["class"]
            display_name = _DISPLAY_NAMES.get(class_name, class_name)
            label = f"{display_name.upper()} {det['conf']:.2f}"
            color = (0, 255, 0) if class_name in _safe_set else (0, 0, 255)
            cv2.rectangle(resized, (x1, y1), (x2, y2), color, 2)
            cv2.putText(resized, label, (x1, y1 - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        # ── hand bounding boxes via MediaPipe + gloves classification ────────
        if _run_gloves and _mp_hands is not None:
            rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            hand_results = _mp_hands.detect(mp_image)
            if hand_results.hand_landmarks:
                h, w = resized.shape[:2]
                # Determine gloves status from best.pt for this frame
                gloves_status = "Gloves"  # default: assume safe until model says otherwise
                if gloves_detections:
                    top = max(gloves_detections, key=lambda d: d["conf"])
                    gloves_status = top["class"]
                g_color = (0, 255, 0) if gloves_status in _safe_set else (0, 0, 255)
                g_label = gloves_status.upper()
                for hand_lm in hand_results.hand_landmarks:
                    xs = [lm.x for lm in hand_lm]
                    ys = [lm.y for lm in hand_lm]
                    x1 = max(0, int(min(xs) * w) - 20)
                    y1 = max(0, int(min(ys) * h) - 20)
                    x2 = min(w, int(max(xs) * w) + 20)
                    y2 = min(h, int(max(ys) * h) + 20)
                    cv2.rectangle(resized, (x1, y1), (x2, y2), g_color, 2)
                    cv2.putText(resized, g_label, (x1, y1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, g_color, 2)

        fps = 1 / (time.time() - start + 1e-5)
        stat_text = f"Cam {cam_id} | FPS: {fps:.1f} | Violations: {violations}"
        cv2.putText(resized, stat_text, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        # ── encode JPEG for MJPEG stream ───────────────────────────────────
        _, jpeg = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 80])
        with lock:
            frame_dict[cam_id] = jpeg.tobytes()

        set_stats("running", round(fps, 1), violations, frame_count)

    cap.release()
    if _mp_hands is not None:
        try:
            _mp_hands.close()
        except Exception:
            pass
    set_stats("stopped", 0, violations, frame_count)
