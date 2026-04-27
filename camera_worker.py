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
import sys
import subprocess
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
from roi_module.filter import filter_detections
from roi_module.cache import get_roi_cache
from app.services.burglar_alarm_service import (
    is_in_alarm_window,
    is_person_in_zone,
    init_kcf_tracker,
)

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



def play_test_sound(cam_id: int):
    """
    Play a short non-blocking local machine sound for burglar alarm testing.
    Best-effort only: failures are logged and ignored.
    """
    try:
        if sys.platform == "darwin":
            sound_path = "/System/Library/Sounds/Ping.aiff"
            subprocess.Popen(
                ["afplay", sound_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return

        # Fallback for other platforms: terminal bell (may be muted by terminal settings)
        print("\a", end="", flush=True)
    except Exception as e:
        print(f"[Camera {cam_id}] Test sound failed: {e}")

def _get_rois_for_camera(cam_id_str: str) -> list:
    """Return active ROIs from cache; fall back to DB on cache miss."""
    rois = get_roi_cache().get(cam_id_str)
    if rois is not None:
        return rois
    try:
        from app.db.database import SessionLocal
        from roi_module.service import get_camera_rois_cached
        if SessionLocal is not None:
            with SessionLocal() as db:
                return get_camera_rois_cached(db, cam_id_str)
    except Exception as e:
        print(f"[ROI] Could not fetch ROIs for camera {cam_id_str}: {e}")
    return []


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
    burglar_person_model = None,    # optional dedicated person detector for burglar alarm
    burglar_alarm_config: dict = None,  # pre-fetched burglar alarm config dict (or None)
    burglar_test_sound: bool = False, 
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
        "NO-Hardhat":       "NH",
        "NO-Hat":           "NH",
        "Hardhat":          "",
        "Hat":              "",
        "no_helmet":        "NH",
        "helmet":           "",
        # Vest
        "NO-Safety Vest":   "NV",
        "Safety Vest":      "",
        "no_vest":          "NV",
        "vest":             "",
        # Goggles / glasses
        "NO-Goggles":       "NGL",
        "Goggles":          "",
        # Gloves
        "Gloves":           "",
        "NO-Gloves":        "NGO",
        "bare_hand":        "NGO",
        "bare_hands":       "NGO",
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

    thread_native_id = threading.get_native_id()

    def set_stats(
        status: str,
        fps: float = 0,
        violations: int = 0,
        frames: int = 0,
        extra: dict | None = None,
    ):
        if stats_dict is not None:
            with lock:
                stats = dict(stats_dict.get(cam_id, {}))
                stats.update({
                    "status": status, "fps": fps,
                    "violations": violations, "frames": frames,
                    "thread_native_id": thread_native_id,
                })
                if extra:
                    stats.update(extra)
                stats_dict[cam_id] = stats

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
    last_burglar_alarm_time = 0   # separate cooldown for burglar alarm events

    RESIZE_DIM = (640, 480)

     # ── KCF tracker state for burglar alarm ───────────────────────────────
    ba_tracker           = None   # cv2.TrackerKCF instance, or None when idle
    ba_tracking          = False  # True while KCF is actively tracking an intruder
    ba_track_fail_count  = 0      # consecutive KCF update failures
    BA_MAX_FAILS         = 5      # failures before dropping back to IDLE
    BA_REDETECT_INTERVAL = 30     # frames between zone re-checks while tracking
    ba_frames_since_check = 0     # counter for the re-check interval
    ba_tracked_conf      = 0.0   # confidence of the initial YOLO detection
    ba_last_saved_bbox   = None   # [x1, y1, x2, y2] of last DB event for IoU dedup
    BA_IoU_THRESHOLD     = 0.3    # if IoU > this, same person — skip event


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

        def _is_burglar_person_class(class_name: str) -> bool:
            if not class_name:
                return False
            return class_name.strip().lower() in {"person", "persona", "human"}

        def _compute_iou(box1, box2):
            """
            Compute Intersection over Union for two bboxes [x1, y1, x2, y2].
            Returns float in [0, 1]. Returns 0.0 if either box is None.
            """
            if box1 is None or box2 is None:
                return 0.0
            x1_1, y1_1, x2_1, y2_1 = box1
            x1_2, y1_2, x2_2, y2_2 = box2
            # Intersection
            xi1, yi1 = max(x1_1, x1_2), max(y1_1, y1_2)
            xi2, yi2 = min(x2_1, x2_2), min(y2_1, y2_2)
            if xi2 < xi1 or yi2 < yi1:
                inter_area = 0.0
            else:
                inter_area = (xi2 - xi1) * (yi2 - yi1)
            # Union
            area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
            area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
            union_area = area1 + area2 - inter_area
            if union_area <= 0:
                return 0.0
            return inter_area / union_area


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

        # ── ROI spatial filter ────────────────────────────────────────────
        # Detections outside all active ROI polygons are dropped.
        # If no active ROIs exist, all detections pass through (allow_outside_fallback=True).
        _rois = _get_rois_for_camera(str(cam_id))
        if _rois:
            # filter_detections expects x1/y1/x2/y2 keys; adapt from our "box" list
            for _d in filtered_detections:
                _d["x1"], _d["y1"], _d["x2"], _d["y2"] = _d["box"]
            frame_h_px, frame_w_px = resized.shape[:2]
            filtered_detections, _ = filter_detections(
                filtered_detections, str(cam_id), frame_w_px, frame_h_px, rois=_rois
            )

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
        

        # ── burglar alarm check (with KCF tracking) ───────────────────────
        # State machine:
        #   IDLE     → YOLO detects person in zone+window → init KCF, fire alarm
        #   TRACKING → KCF follows intruder each frame, skipping heavy YOLO
        #   TRACKING → KCF fails BA_MAX_FAILS times → back to IDLE
        #   TRACKING → zone re-check every BA_REDETECT_INTERVAL frames;
        #              person left zone → back to IDLE
        #   Any state → window closes → reset to IDLE immediately
        if burglar_alarm_config and burglar_alarm_config.get("alarm_enabled"):
            ba_cooldown = float(burglar_alarm_config.get("cooldown_sec", 30))
            start_t = burglar_alarm_config.get("alarm_start_time", "20:00")
            end_t   = burglar_alarm_config.get("alarm_end_time",   "06:00")
            window_active = is_in_alarm_window(start_t, end_t)

            # Reset tracker immediately when the time window closes
            if not window_active and ba_tracking:
                ba_tracker   = None
                ba_tracking  = False
                ba_track_fail_count  = 0
                ba_frames_since_check = 0
                ba_last_saved_bbox = None  # clear session on window close
                print(f"[Camera {cam_id}] KCF tracker reset — alarm window closed")

            if window_active:
                frame_h_px, frame_w_px = resized.shape[:2]
                zone_pts = burglar_alarm_config.get("monitored_zone_points")

                if ba_tracking and ba_tracker is not None:
                    # ── TRACKING STATE: update KCF ─────────────────────────
                    kcf_ok, kcf_rect = ba_tracker.update(resized)

                    if not kcf_ok:
                        ba_track_fail_count += 1
                        if ba_track_fail_count >= BA_MAX_FAILS:
                            ba_tracker  = None
                            ba_tracking = False
                            ba_track_fail_count  = 0
                            ba_frames_since_check = 0
                            ba_last_saved_bbox = None  # reset session on tracker loss
                            print(
                                f"[Camera {cam_id}] KCF lost intruder after "
                                f"{BA_MAX_FAILS} failures — returning to IDLE"
                            )
                    else:
                        ba_track_fail_count = 0
                        kx, ky, kw, kh = [int(v) for v in kcf_rect]
                        kx2, ky2 = kx + kw, ky + kh

                        # Periodic zone re-check — drop tracker if person left zone
                        ba_frames_since_check += 1
                        if ba_frames_since_check >= BA_REDETECT_INTERVAL:
                            ba_frames_since_check = 0
                            tracked_det = {"box": [kx, ky, kx2, ky2]}
                            still_in_zone = (
                                zone_pts is None
                                or is_person_in_zone(
                                    tracked_det, zone_pts, frame_w_px, frame_h_px
                                )
                            )
                            if not still_in_zone:
                                ba_tracker  = None
                                ba_tracking = False
                                ba_track_fail_count  = 0
                                ba_last_saved_bbox = None  # reset session on zone exit
                                print(
                                    f"[Camera {cam_id}] KCF — intruder left zone, "
                                    "tracker reset to IDLE"
                                )

                        # Draw orange tracking box while KCF is active
                        if ba_tracking:
                            cv2.rectangle(
                                resized, (kx, ky), (kx2, ky2), (0, 165, 255), 2
                            )
                            cv2.putText(
                                resized,
                                f"INTRUDER TRACKING {ba_tracked_conf:.2f}",
                                (kx, ky - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2,
                            )

                else:
                    # ── IDLE STATE: run YOLO person detection ──────────────
                    if (time.time() - last_burglar_alarm_time) > ba_cooldown:
                        burglar_candidates = filtered_detections
                        if burglar_person_model is not None:
                            burglar_candidates = run_detection(
                                burglar_person_model, resized, threshold
                            )

                        for det in burglar_candidates:
                            if not _is_burglar_person_class(det.get("class")):
                                continue

                            in_zone = (
                                zone_pts is None
                                or is_person_in_zone(
                                    det, zone_pts, frame_w_px, frame_h_px
                                )
                            )
                            if not in_zone:
                                continue

                            # ── IoU deduplication: check if same person as last event ─
                            det_bbox = det["box"]
                            iou_with_last = _compute_iou(det_bbox, ba_last_saved_bbox)
                            if iou_with_last > BA_IoU_THRESHOLD:
                                # Same person still in frame, skip event
                                continue

                            # Intruder confirmed — initialize KCF tracker
                            new_tracker = init_kcf_tracker(resized, det_bbox)
                            if new_tracker is not None:
                                ba_tracker            = new_tracker
                                ba_tracking           = True
                                ba_track_fail_count   = 0
                                ba_frames_since_check = 0
                                ba_tracked_conf       = det["conf"]

                            # Fire alarm + save snapshot + queue alert
                            last_burglar_alarm_time = time.time()
                            snap_path = save_snapshot(resized, cam_id, snapshot_dir)

                            buzzer_fired = False
                            if assigned_buzzers:
                                buzzer_fired = fire_buzzers(assigned_buzzers, cam_id)
                            else:
                                from alarm import trigger_alarm
                                trigger_alarm(
                                    cam_id, ba_cooldown,
                                    use_wifi=use_wifi, esp_ip=esp_ip,
                                    transport=alarm_transport, token=alarm_http_token,
                                    mqtt_broker=mqtt_broker, mqtt_port=mqtt_port,
                                    mqtt_username=mqtt_username, mqtt_password=mqtt_password,
                                    mqtt_topic=mqtt_topic, mqtt_client_id=mqtt_client_id,
                                    mqtt_qos=mqtt_qos, mqtt_retain=mqtt_retain,
                                )
                                buzzer_fired = True

                            if burglar_test_sound:
                                play_test_sound(cam_id)

                            if alert_queue is not None:
                                _box = det_bbox
                                alert_queue.put({
                                    "camera_id":           cam_id,
                                    "model_name":          "burglar_alarm",
                                    "violation_type":      "burglar_alarm",
                                    "confidence_score":    det["conf"],
                                    "snapshot_path":       snap_path,
                                    "buzzer_activated":    buzzer_fired,
                                    "zone_id":             burglar_alarm_config.get("monitored_zone_id"),
                                    "tracker_initialized": ba_tracking,
                                    # Person location in frame
                                    "bbox_x1":     int(_box[0]),
                                    "bbox_y1":     int(_box[1]),
                                    "bbox_x2":     int(_box[2]),
                                    "bbox_y2":     int(_box[3]),
                                    "frame_width":  frame_w_px,
                                    "frame_height": frame_h_px,
                                })
                                # Update last saved bbox for next iteration's IoU check
                                ba_last_saved_bbox = list(_box)

                            print(
                                f"[Camera {cam_id}] BURGLAR ALARM — intruder detected "
                                f"in zone ({start_t}–{end_t}), KCF tracker started "
                                f"(conf={det['conf']:.2f}, IoU={iou_with_last:.2f})"
                            )
                            break   # one burglar event per frame


        # ── draw detections (filtered by enabled per-camera models) ────────
        for det in filtered_detections:
            x1, y1, x2, y2 = map(int, det["box"])
            class_name = det["class"]
            display_name = _DISPLAY_NAMES.get(class_name, class_name)

            # Normalize helmet label variants so "No Hat/No Hardhat" is always NH,
            # and compliant helmet detections show no text.
            cls_key = str(class_name).strip().lower().replace("_", "-").replace(" ", "-")
            if any(k in cls_key for k in ("helmet", "hardhat", "-hat", "hat")):
                if cls_key.startswith("no-") or "-no-" in cls_key or cls_key.startswith("without-"):
                    display_name = "NH"
                else:
                    # Compliant helmet — skip box and label entirely
                    continue

            # Vest compliance suppression
            if any(k in cls_key for k in ("vest",)):
                if cls_key.startswith("no-") or "-no-" in cls_key or cls_key.startswith("without-"):
                    display_name = "NV"
                else:
                    continue

            # Glasses / goggles compliance suppression
            if any(k in cls_key for k in ("goggle", "glasses", "goggle")):
                if cls_key.startswith("no-") or "-no-" in cls_key or cls_key.startswith("without-"):
                    display_name = "NGL"
                else:
                    continue

            # Gloves compliance suppression
            if any(k in cls_key for k in ("glove",)):
                if cls_key.startswith("no-") or "-no-" in cls_key or cls_key.startswith("without-"):
                    display_name = "NGO"
                else:
                    continue

            if not display_name:
                label = ""
            elif display_name.upper() in ("NH", "NV", "NGO", "NGL"):
                label = display_name.upper()
            else:
                label = f"{display_name.upper()} {det['conf']:.2f}"
            color = (0, 255, 0) if class_name in _safe_set else (0, 0, 255)

            # Draw NH/NV/NGO/NGL slightly smaller to reduce visual dominance on the stream.
            if label in ("NH", "NV", "NGO", "NGL"):
                shrink_x = max(1, int((x2 - x1) * 0.12))
                shrink_y = max(1, int((y2 - y1) * 0.12))
                x1_draw = min(x2 - 1, x1 + shrink_x)
                y1_draw = min(y2 - 1, y1 + shrink_y)
                x2_draw = max(x1_draw + 1, x2 - shrink_x)
                y2_draw = max(y1_draw + 1, y2 - shrink_y)
                box_thickness = 1
                label_scale = 0.35
                label_thickness = 1
            else:
                x1_draw, y1_draw, x2_draw, y2_draw = x1, y1, x2, y2
                box_thickness = 2
                label_scale = 0.6
                label_thickness = 2

            cv2.rectangle(resized, (x1_draw, y1_draw), (x2_draw, y2_draw), color, box_thickness)
            if label:
                cv2.putText(resized, label, (x1_draw, y1_draw - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, label_scale, color, label_thickness)

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
                gloves_worn = gloves_status in _safe_set
                if not gloves_worn:
                    g_color = (0, 0, 255)
                    for hand_lm in hand_results.hand_landmarks:
                        xs = [lm.x for lm in hand_lm]
                        ys = [lm.y for lm in hand_lm]
                        x1 = max(0, int(min(xs) * w) - 20)
                        y1 = max(0, int(min(ys) * h) - 20)
                        x2 = min(w, int(max(xs) * w) + 20)
                        y2 = min(h, int(max(ys) * h) + 20)
                        shrink_x = max(1, int((x2 - x1) * 0.12))
                        shrink_y = max(1, int((y2 - y1) * 0.12))
                        x1d = min(x2 - 1, x1 + shrink_x)
                        y1d = min(y2 - 1, y1 + shrink_y)
                        x2d = max(x1d + 1, x2 - shrink_x)
                        y2d = max(y1d + 1, y2 - shrink_y)
                        cv2.rectangle(resized, (x1d, y1d), (x2d, y2d), g_color, 1)
                        cv2.putText(resized, "NGO", (x1d, y1d - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.35, g_color, 1)

        fps = 1 / (time.time() - start + 1e-5)
        stat_text = f"Cam {cam_id} | FPS: {fps:.1f} | Violations: {violations}"
        cv2.putText(resized, stat_text, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        # ── encode JPEG for MJPEG stream ───────────────────────────────────
        _, jpeg = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 80])
        jpeg_bytes = jpeg.tobytes()
        with lock:
            frame_dict[cam_id] = jpeg_bytes

        set_stats(
            "running",
            round(fps, 1),
            violations,
            frame_count,
            extra={"frame_buffer_bytes": len(jpeg_bytes)},
        )

    cap.release()
    if _mp_hands is not None:
        try:
            _mp_hands.close()
        except Exception:
            pass
    set_stats("stopped", 0, violations, frame_count, extra={"frame_buffer_bytes": 0})
