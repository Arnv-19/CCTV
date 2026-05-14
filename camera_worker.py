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
import uuid
import subprocess
import threading
import numpy as np
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
from detector import run_detection, load_model
from roi_module.filter import filter_detections
from roi_module.cache import get_roi_cache
from app.services.burglar_alarm_service import (
    is_in_alarm_window,
    is_person_in_zone,
    init_kcf_tracker,
)
from app.controllers.whatsapp_snapshot_controller import send_snapshot_best_effort
from app.controllers.vehicle_detection_controller import (
    process_vehicle_detection,
    make_position_key,
)

def start_ffmpeg(rtsp_url: str, width: int = 960, height: int = 720) -> subprocess.Popen:
    """
    Launch an FFmpeg subprocess that reads the given RTSP (or local) stream
    and writes raw BGR24 frames to stdout.

    width / height must match the -vf scale= filter so that the caller can
    slice the stdout byte-stream into exact frame_size chunks.
    """
    # For a numeric source (webcam index) fall back to OpenCV; FFmpeg needs a
    # proper URL or device path, not a plain integer.
    if isinstance(rtsp_url, int) or (isinstance(rtsp_url, str) and rtsp_url.isdigit()):
        return None  # caller will use legacy cv2.VideoCapture for webcams

    # fps is now configurable; default to 4 if not provided
    fps = start_ffmpeg.ingestion_fps if hasattr(start_ffmpeg, "ingestion_fps") else 4
    cmd = [
        "ffmpeg",
        "-loglevel", "warning",
        "-rtsp_transport", "tcp",
        "-stimeout", "10000000",   # 10s connection timeout (microseconds)
        "-i", rtsp_url,
        "-vf", f"scale={width}:{height},fps={fps},format=bgr24",
        "-f", "rawvideo",
        "-"
    ]
    return subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,   # capture so we can log errors
        bufsize=10 ** 8,
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


def log_violation_file(
    cam_id: int,
    frame_index: int,
    violation_rate: float,
    violation_type: str = "violation",
):
    """Append a violation line to the flat-file log (kept for backward compat)."""
    ensure_dir("logs")
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open("logs/alerts.log", "a") as f:
        f.write(
            f"[{now}] Camera {cam_id} | Frame {frame_index} | {violation_type} | Rate: {violation_rate:.2f}%\n"
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




# ═════════════════════════════════════════════════════════════════════════════
# NEW SHARED-INFERENCE ARCHITECTURE
# ─────────────────────────────────────────────────────────────────────────────
# ingestion_worker   — one lightweight mp.Process per camera
#                      reads FFmpeg/webcam frames, pushes to shared frame_queue
# result_handler_worker — one threading.Thread per camera (in main process)
#                         reads (cam_id, frame, ts, detections, gloves_dets,
#                         burglar_dets) from its result_queue and handles all
#                         alarm logic, MJPEG encoding and stats updates
#
# The inference server (inference_server.py) sits between them:
#   frame_queue ──► InferenceServer (1 process, 1 model, batch GPU predict)
#                            └──► per-camera result_queues ──► result_handler_worker
# ═════════════════════════════════════════════════════════════════════════════

import multiprocessing as _mp   # keep local alias to avoid clash at module level


def ingestion_worker(
    cam_id: int,
    stream_url,
    frame_queue,          # mp.Queue shared with inference_server_loop
    stop_event,           # mp.Event
    stats_dict: dict,
    lock,
    detection_width: int = 960,
    detection_height: int = 720,
    ingestion_fps: float = 4.0,
):
    """
    Lightweight per-camera ingestion process.

    Reads BGR frames from FFmpeg (RTSP) or OpenCV (webcam), resizes them to
    (detection_width × detection_height), rate-limits to ingestion_fps, and
    pushes (cam_id, frame, timestamp) to the shared frame_queue for the
    inference server to process.

    No model loading, no inference — just frame delivery.
    """
    import cv2 as _cv2
    import numpy as _np

    _ff_width   = max(320, int(detection_width  or 960))
    _ff_height  = max(240, int(detection_height or 720))
    _frame_size = _ff_width * _ff_height * 3
    _interval   = 1.0 / max(1.0, float(ingestion_fps))

    _is_webcam = isinstance(stream_url, int) or (
        isinstance(stream_url, str) and str(stream_url).isdigit()
    )

    ffmpeg_proc_ing = None
    _buf: dict = {"frame": None, "ts": 0.0, "lock": threading.Lock()}

    def _ffmpeg_reader_ing(proc):
        while True:
            try:
                raw = proc.stdout.read(_frame_size)
            except Exception:
                break
            if not raw or len(raw) != _frame_size:
                break
            arr = _np.frombuffer(raw, dtype=_np.uint8).reshape(
                (_ff_height, _ff_width, 3)
            )
            with _buf["lock"]:
                _buf["frame"] = arr.copy()
                _buf["ts"]    = time.time()

    def _ffmpeg_stderr_logger(proc):
        """Print FFmpeg stderr lines so connection errors appear in server logs."""
        try:
            for line in proc.stderr:
                msg = line.decode(errors="replace").rstrip()
                if msg:
                    print(f"[FFmpeg cam{cam_id}] {msg}", flush=True)
        except Exception:
            pass

    def _start_ffmpeg_ing():
        nonlocal ffmpeg_proc_ing
        if ffmpeg_proc_ing is not None:
            try:
                ffmpeg_proc_ing.terminate()
                ffmpeg_proc_ing.wait(timeout=3)
            except Exception:
                pass
        ffmpeg_proc_ing = start_ffmpeg(stream_url, _ff_width, _ff_height)
        if ffmpeg_proc_ing:
            threading.Thread(
                target=_ffmpeg_reader_ing,
                args=(ffmpeg_proc_ing,),
                daemon=True,
            ).start()
            threading.Thread(
                target=_ffmpeg_stderr_logger,
                args=(ffmpeg_proc_ing,),
                daemon=True,
            ).start()

    legacy_cap = None
    if _is_webcam:
        legacy_cap = _cv2.VideoCapture(
            int(stream_url) if isinstance(stream_url, str) else stream_url
        )
        if not legacy_cap.isOpened():
            print(f"[Ingestion {cam_id}] Failed to open webcam: {stream_url}")
            if stats_dict is not None:
                with lock:
                    stats_dict[cam_id] = {"status": "error", "fps": 0,
                                          "violations": 0, "frames": 0}
            return
    else:
        _start_ffmpeg_ing()
        time.sleep(1.5)

    reconnect_attempts = 0
    max_reconnect      = 10
    _last_push         = 0.0

    if stats_dict is not None:
        with lock:
            stats_dict[cam_id] = {"status": "ingesting", "fps": 0,
                                   "violations": 0, "frames": 0}

    while True:
        if stop_event is not None and stop_event.is_set():
            break

        if _is_webcam:
            # Sleep BEFORE reading so cap.read() is only called at ingestion_fps,
            # not at the webcam's native ~30 FPS. Avoids 7-8 wasted reads per push.
            sleep_time = _interval - (time.time() - _last_push)
            if sleep_time > 0.01:
                time.sleep(sleep_time - 0.005)  # wake slightly early to hit target

            ret, frame = legacy_cap.read()
            if not ret:
                reconnect_attempts += 1
                time.sleep(0.5)
                if reconnect_attempts >= max_reconnect:
                    break
                continue
            resized = _cv2.resize(frame, (_ff_width, _ff_height))
        else:
            with _buf["lock"]:
                buf_ts = _buf["ts"]
                frame  = _buf["frame"]

            # No frame yet — FFmpeg is still connecting; wait without counting as a stall
            if buf_ts == 0:
                time.sleep(0.1)
                continue

            age = time.time() - buf_ts
            if age > 12.0:
                reconnect_attempts += 1
                print(f"[Ingestion {cam_id}] FFmpeg stall (age={age:.1f}s) — reconnect {reconnect_attempts}/{max_reconnect}", flush=True)
                _start_ffmpeg_ing()
                time.sleep(2.0)
                if reconnect_attempts >= max_reconnect:
                    print(f"[Ingestion {cam_id}] Giving up after {max_reconnect} reconnects — check FFmpeg/RTSP above", flush=True)
                    break
                continue

            if frame is None:
                time.sleep(0.02)
                continue

            resized = frame

            # RTSP path: honour rate limit
            now = time.time()
            if now - _last_push < _interval:
                time.sleep(0.005)
                continue

        reconnect_attempts = 0
        _last_push = time.time()

        try:
            frame_queue.put_nowait((cam_id, resized, _last_push))
        except Exception:
            pass   # queue full — drop frame (backpressure)

    # ── Cleanup ────────────────────────────────────────────────────────────
    if legacy_cap is not None:
        legacy_cap.release()
    elif ffmpeg_proc_ing is not None:
        try:
            ffmpeg_proc_ing.terminate()
            ffmpeg_proc_ing.wait(timeout=5)
        except subprocess.TimeoutExpired:
            ffmpeg_proc_ing.kill()
            ffmpeg_proc_ing.wait()
        except Exception:
            pass


def result_handler_worker(  # noqa: C901  (refactored into sub-functions below)
    cam_id: int,
    result_queue,                   # mp.Queue from inference_server_loop
    frame_dict: dict,               # shared {cam_id: jpeg_bytes}
    lock,                           # shared lock
    threshold: float,
    helmet_class: str,
    no_helmet_class: str,
    cooldown: float,
    stop_event: threading.Event = None,
    stats_dict: dict = None,
    assigned_buzzers: list = None,
    alert_queue: Queue = None,
    snapshot_dir: str = "snapshots",
    snapshot_cooldown: float = 120,
    detection_width: int = 960,
    detection_height: int = 720,
    yolo_imgsz: int = 960,
    enabled_models: list = None,
    violation_classes: list = None,
    safe_classes: list = None,
    burglar_alarm_config: dict = None,
    burglar_test_sound: bool = False,
    feature_config: dict = None,
):
    """
    Per-camera result handler thread (runs in main process).

    Reads (cam_id, frame_bgr, ts, detections, gloves_dets, burglar_dets) from
    result_queue and handles:
      • ROI filtering
      • Violation detection & alarm triggering
      • Burglar alarm KCF tracking
      • MediaPipe gloves overlay
      • MJPEG encoding → frame_dict
      • Stats updates

    No YOLO inference here — detections arrive pre-computed from the shared
    inference server process.

    gloves_dets == None  → treat as equal to main detections (same model)
    burglar_dets == None → treat as equal to main detections (same model)
    """
    from queue import Empty as _Empty

    thread_native_id = threading.get_native_id()

    # ── Utility ────────────────────────────────────────────────────────────

    def set_stats(status, fps=0, violations=0, frames=0, extra=None):
        if stats_dict is not None:
            with lock:
                s = dict(stats_dict.get(cam_id, {}))
                s.update({"status": status, "fps": fps,
                           "violations": violations, "frames": frames,
                           "thread_native_id": thread_native_id})
                if extra:
                    s.update(extra)
                stats_dict[cam_id] = s

    def _class_key(class_name):
        return str(class_name or "").strip().lower().replace("_", "-").replace(" ", "-")

    # ── Class sets, display names, model mapping ───────────────────────────

    _violation_set = set(violation_classes) if violation_classes else (
        {no_helmet_class} if no_helmet_class else set()
    )
    _safe_set = set(safe_classes) if safe_classes else (
        {helmet_class} if helmet_class else set()
    )
    _violation_keys = {_class_key(c) for c in _violation_set}
    _violation_keys.update({
        "no-hardhat", "no-hat", "no-helmet",
        "no-boot", "no-boots", "no-shoe", "no-shoes",
        "no-gloves", "bare-hand", "bare-hands",
        "no-safety-vest", "no-vest", "no-goggles", "no-glasses",
        "fire",
    })
    _safe_keys = {_class_key(c) for c in _safe_set}
    _safe_keys.update({
        "hardhat", "hat", "helmet",
        "boot", "boots", "shoe", "shoes",
        "gloves", "safety-vest", "vest", "goggles", "glasses",
    })
    _disabled_class_keys = {"mask", "no-mask"}

    def _is_violation_class(c):  return _class_key(c) in _violation_keys
    def _is_safe_class(c):       return _class_key(c) in _safe_keys

    _enabled_set = set(enabled_models) if enabled_models is not None else None

    _DISPLAY_NAMES = {
        "NO-Hardhat": "NH", "NO-Hat": "NH", "Hardhat": "", "Hat": "",
        "no_helmet": "NH", "helmet": "",
        "NO-Safety Vest": "NV", "Safety Vest": "", "no_vest": "NV", "vest": "",
        "NO-Goggles": "NGL", "Goggles": "",
        "Gloves": "", "NO-Gloves": "NGO", "no-gloves": "NGO",
        "bare_hand": "NGO", "bare_hands": "NGO",
    }
    _CLASS_TO_MODEL = {
        "no_helmet": "helmet_detection", "helmet": "helmet_detection",
        "no-hardhat": "helmet_detection", "no_hardhat": "helmet_detection",
        "hardhat": "helmet_detection", "no-hat": "helmet_detection",
        "no_hat": "helmet_detection", "hat": "helmet_detection",
        "no_vest": "vest_detection", "vest": "vest_detection",
        "no-safety vest": "vest_detection", "no_safety_vest": "vest_detection",
        "safety vest": "vest_detection", "safety_vest": "vest_detection",
        "no_glasses": "glasses_detection", "glasses": "glasses_detection",
        "no-goggles": "glasses_detection", "no_goggles": "glasses_detection",
        "goggles": "glasses_detection",
        "no-gloves": "gloves_detection", "no_gloves": "gloves_detection",
        "gloves": "gloves_detection", "bare-hand": "gloves_detection",
        "bare_hand": "gloves_detection", "bare_hands": "gloves_detection",
        "fire": "fire_detection",
    }

    def _model_for_class(c):
        if not c:
            return None
        k = c.strip().lower()
        if k in _CLASS_TO_MODEL:
            return _CLASS_TO_MODEL[k]
        return _CLASS_TO_MODEL.get(k.replace("-", "_").replace(" ", "_"))

    # ── MediaPipe hand landmarker (CPU — stays in handler thread) ──────────

    _run_gloves_mp = _enabled_set is None or "gloves_detection" in _enabled_set
    _mp_hands = None
    if _run_gloves_mp:
        try:
            _opts = _mp_vision.HandLandmarkerOptions(
                base_options=_MpBaseOptions(model_asset_path=_HAND_LANDMARKER_PATH),
                num_hands=4,
                min_hand_detection_confidence=0.5,
            )
            _mp_hands = _mp_vision.HandLandmarker.create_from_options(_opts)
        except Exception as e:
            print(f"[ResultHandler {cam_id}] MediaPipe init failed: {e}")
            _mp_hands = None

    RESIZE_DIM = (max(320, int(detection_width or 960)),
                  max(240, int(detection_height or 720)))

    # ── Mutable state ──────────────────────────────────────────────────────

    frame_count = 0
    violations  = 0
    last_alarm_times: dict = {}
    last_snapshot_times: dict = {}
    _last_stats_ts = 0.0

    feature_config       = feature_config or {}
    missing_person_cfg   = feature_config.get("missing_person_alert") or {}
    crowd_alert_cfg      = feature_config.get("crowd_alert") or {}
    missing_person_frames       = 0
    crowd_threshold_started_at  = None

    # Burglar alarm state in a dict so _handle_burglar_alarm mutates in place
    _ba = {
        "tracker":            None,
        "tracking":           False,
        "fail_count":         0,
        "frames_since_check": 0,
        "tracked_conf":       0.0,
        "last_saved_bbox":    None,
        "last_alarm_time":    0.0,
    }
    BA_MAX_FAILS         = 5
    BA_REDETECT_INTERVAL = 30
    BA_IoU_THRESHOLD     = 0.3

    # Vehicle dedup: {plate_or_position_key: last_logged_timestamp}
    _vehicle_last_seen: dict = {}
    VEHICLE_COOLDOWN_SEC = 30

    # Per-person PPE violation trackers
    _viol_trackers: list       = []
    VIOL_MAX_FAILS             = 8
    VIOL_MAX_MISSED_DETECTIONS = 3
    VIOL_IOU_THRESHOLD         = 0.10
    VIOL_ORANGE                = (0, 165, 255)

    def _viol_iou(b1, b2):
        xi1, yi1 = max(b1[0], b2[0]), max(b1[1], b2[1])
        xi2, yi2 = min(b1[2], b2[2]), min(b1[3], b2[3])
        if xi2 <= xi1 or yi2 <= yi1:
            return 0.0
        inter = (xi2 - xi1) * (yi2 - yi1)
        area1 = max(1, (b1[2]-b1[0]) * (b1[3]-b1[1]))
        area2 = max(1, (b2[2]-b2[0]) * (b2[3]-b2[1]))
        return inter / (area1 + area2 - inter)

    def _bbox_to_int(bbox, frame=None):
        """Return a valid int [x1,y1,x2,y2] bbox, optionally clamped to frame."""
        try:
            if bbox is None or len(bbox) != 4:
                return None
            x1, y1, x2, y2 = [int(round(float(v))) for v in bbox]
            if frame is not None:
                h, w = frame.shape[:2]
                x1 = max(0, min(w - 1, x1))
                y1 = max(0, min(h - 1, y1))
                x2 = max(0, min(w, x2))
                y2 = max(0, min(h, y2))
            if x2 <= x1 or y2 <= y1:
                return None
            return [x1, y1, x2, y2]
        except Exception:
            return None

    def _find_tracker(bbox):
        """Return the tracker entry whose bbox overlaps or contains this detection."""
        cx = (bbox[0] + bbox[2]) / 2
        cy = (bbox[1] + bbox[3]) / 2
        for vt in _viol_trackers:
            if _viol_iou(bbox, vt["bbox"]) > VIOL_IOU_THRESHOLD:
                return vt
            # Center containment: violation center falls inside tracked person bbox
            tx1, ty1, tx2, ty2 = vt["bbox"]
            if tx1 <= cx <= tx2 and ty1 <= cy <= ty2:
                return vt
            # Center-distance fallback: handles KCF drift / partial occlusion.
            # When KCF is failing the tracker bbox freezes at last good position
            # while YOLO detects the person at their actual new position — IoU
            # drops to 0. Check if centres are within 80% of the tracker size.
            tcx = (tx1 + tx2) / 2
            tcy = (ty1 + ty2) / 2
            tw  = max(1, tx2 - tx1)
            th  = max(1, ty2 - ty1)
            if abs(cx - tcx) < tw * 0.8 and abs(cy - tcy) < th * 0.8:
                return vt
        return None

    # ── Appearance cache (histogram-based re-identification) — DISABLED ──
    # Commented out by management request. KCF tracker handles deduplication
    # while person is visible; no re-ID after person leaves frame.
    # _appearance_cache: list = []
    # HIST_CACHE_TTL     = 60.0
    # HIST_SIM_THRESHOLD = 0.80

    # def _compute_histogram(frame, bbox): ...
    # def _find_cached_person(hist): ...

    # ── Bbox-based tracker cache ───────────────────────────────────────────
    # Saves tracker params when KCF drops so a returning person at the
    # same location restores their session_id + alerted set.
    _tracker_cache: list = []       # list of saved tracker param dicts
    TRACKER_CACHE_TTL    = 30.0     # seconds to keep after tracker drops
    TRACKER_CACHE_IOU    = 0.30     # min IoU to consider "same person"

    def _cache_violation_tracker(vt):
        _tracker_cache.append({
            "bbox":       vt["bbox"],
            "alerted":    set(vt["alerted"]),
            "session_id": vt["session_id"],
            "saved_at":   time.time(),
        })

    # ── Alert helpers (defined once; resized passed per-call) ─────────────

    def record_violation(det, resized, violation_type=None, allow_snapshot=True,
                         session_tracker_id=None, skip_cooldown=False):
        nonlocal violations
        violation_name = violation_type or det.get("class", "violation")
        violation_key  = _class_key(violation_name)
        now = time.time()
        effective_cooldown = max(0.0, float(cooldown or 0))
        if not skip_cooldown:
            if now - last_alarm_times.get(violation_key, 0) <= effective_cooldown:
                return False
        last_alarm_times[violation_key] = now
        violations += 1

        snap_path = None
        if allow_snapshot and now - last_snapshot_times.get(violation_key, 0) > max(0.0, float(snapshot_cooldown or 0)):
            snap_path = save_snapshot(resized, cam_id, snapshot_dir)
            last_snapshot_times[violation_key] = now

        buzzer_fired = False
        if assigned_buzzers:
            buzzer_fired = fire_buzzers(assigned_buzzers, cam_id)
        else:
            print(f"[Camera {cam_id}] No buzzers configured for violation '{violation_name}'")

        if alert_queue is not None:
            alert_queue.put({
                "camera_id":           cam_id,
                "model_name":          "ppe_detection",
                "violation_type":      violation_name,
                "confidence_score":    det.get("conf", 0.0),
                "snapshot_path":       snap_path,
                "buzzer_activated":    buzzer_fired,
                "session_tracker_id":  session_tracker_id,
            })
        log_violation_file(cam_id, frame_count, (violations / frame_count) * 100, violation_name)
        return True

    def record_system_alert(
        resized,
        *,
        model_name,
        violation_type,
        confidence_score=0.0,
        send_whatsapp=False,
        fire_alarm=False,
    ):
        nonlocal violations
        violations += 1
        snap_path    = save_snapshot(resized, cam_id, snapshot_dir)
        buzzer_fired = fire_buzzers(assigned_buzzers, cam_id) if fire_alarm and assigned_buzzers else False
        if send_whatsapp:
            send_snapshot_best_effort(snap_path, f"AXIS CCTV {violation_type} | Camera {cam_id}")
        if alert_queue is not None:
            alert_queue.put({
                "camera_id":        cam_id,
                "model_name":       model_name,
                "violation_type":   violation_type,
                "confidence_score": float(confidence_score or 0.0),
                "snapshot_path":    snap_path,
                "buzzer_activated": buzzer_fired,
            })
        log_violation_file(cam_id, frame_count, (violations / frame_count) * 100, violation_type)
        return True

    # ── Per-frame processing functions ─────────────────────────────────────

    def _decode_frame(frame_payload):
        """Decode JPEG bytes from inference server to a BGR ndarray."""
        if isinstance(frame_payload, (bytes, bytearray)) and frame_payload:
            dec = cv2.imdecode(np.frombuffer(frame_payload, np.uint8), cv2.IMREAD_COLOR)
            return dec if dec is not None else np.zeros(
                (RESIZE_DIM[1], RESIZE_DIM[0], 3), dtype=np.uint8
            )
        return frame_payload  # raw numpy fallback (legacy path)

    def _resolve_detections(detections, extra_dets):
        """Unpack extra_dets into named detection lists, resolving None sentinels."""
        gloves_dets  = extra_dets.get("gloves")
        burglar_dets = extra_dets.get("burglar")
        gloves_detections      = detections if gloves_dets  is None else gloves_dets
        burglar_candidates_raw = detections if burglar_dets is None else burglar_dets
        vehicle_dets_raw       = extra_dets.get("vehicle")
        return gloves_detections, burglar_candidates_raw, vehicle_dets_raw

    def _filter_and_roi(detections, gloves_detections, resized):
        """Apply class-enable and ROI filters; return filtered detection list."""
        filtered = []
        all_dets = (
            detections
            if gloves_detections is detections
            else detections + gloves_detections
        )
        for det in all_dets:
            if _class_key(det.get("class")) in _disabled_class_keys:
                continue
            model_name = _model_for_class(det["class"])
            if _enabled_set is not None and model_name and model_name not in _enabled_set:
                continue
            filtered.append(det)
        _rois = _get_rois_for_camera(str(cam_id))
        if _rois:
            for d in filtered:
                d["x1"], d["y1"], d["x2"], d["y2"] = d["box"]
            frame_h, frame_w = resized.shape[:2]
            filtered, _ = filter_detections(filtered, str(cam_id), frame_w, frame_h, rois=_rois)
        return filtered

    def _handle_missing_person_alert(person_count, resized):
        """Fire a missing-person alert when no person is detected for N frames."""
        nonlocal missing_person_frames
        if not missing_person_cfg.get("enabled"):
            return
        if person_count == 0:
            missing_person_frames += 1
        else:
            missing_person_frames = 0
        missing_threshold = int(missing_person_cfg.get("missing_frames", 3600))
        if missing_person_frames >= missing_threshold:
            record_system_alert(
                resized,
                model_name="missing_person",
                violation_type="missing_person",
                confidence_score=missing_person_frames,
                send_whatsapp=bool(missing_person_cfg.get("send_whatsapp")),
                fire_alarm=False,
            )
            missing_person_frames = 0

    def _handle_crowd_alert(person_count, resized):
        """Fire a crowd alert when count exceeds threshold for N sustained seconds."""
        nonlocal crowd_threshold_started_at
        if not crowd_alert_cfg.get("enabled"):
            return
        crowd_threshold = int(crowd_alert_cfg.get("person_threshold", 5))
        sustained_sec   = max(0.0, float(crowd_alert_cfg.get("sustained_seconds", 5)))
        now_alert = time.time()
        if person_count >= crowd_threshold:
            if crowd_threshold_started_at is None:
                crowd_threshold_started_at = now_alert
            if now_alert - crowd_threshold_started_at >= sustained_sec:
                record_system_alert(
                    resized,
                    model_name="crowd_alert",
                    violation_type="crowd_threshold_exceeded",
                    confidence_score=person_count,
                    send_whatsapp=bool(crowd_alert_cfg.get("send_whatsapp")),
                    fire_alarm=True,
                )
                crowd_threshold_started_at = None
        else:
            crowd_threshold_started_at = None

    def _update_ppe_trackers(resized):
        """Advance all active KCF trackers by one frame; drop failures to cache."""
        still_active = []
        for vt in _viol_trackers:
            vt["matched"] = False
            ok, rect = vt["tracker"].update(resized)
            if ok:
                kx, ky, kw, kh = [int(v) for v in rect]
                vt["bbox"]  = [kx, ky, kx + kw, ky + kh]
                vt["fails"] = 0
                still_active.append(vt)
            else:
                vt["fails"] += 1
                if vt["fails"] < VIOL_MAX_FAILS:
                    still_active.append(vt)
                else:
                    # Tracker dropped — save params to bbox cache so person
                    # can be restored if they return within TRACKER_CACHE_TTL.
                    _cache_violation_tracker(vt)
        _viol_trackers.clear()
        _viol_trackers.extend(still_active)
        _now_tc = time.time()
        _tracker_cache[:] = [c for c in _tracker_cache if _now_tc - c["saved_at"] < TRACKER_CACHE_TTL]

    def _reanchor_person_trackers(resized, person_bboxes):
        """Re-anchor active KCF trackers using fresh YOLO Person detections."""
        # YOLO Person detections are more reliable than violation detections
        # (higher confidence, bigger target). Re-anchor every frame when a
        # Person bbox overlaps the tracker — prevents drift accumulating even
        # when violation confidence temporarily drops below threshold.
        for vt in _viol_trackers:
            best_pb, best_iou = None, 0.15   # min IoU to consider a match
            vcx = (vt["bbox"][0] + vt["bbox"][2]) / 2
            vcy = (vt["bbox"][1] + vt["bbox"][3]) / 2
            for pb in person_bboxes:
                iou = _viol_iou(vt["bbox"], pb)
                # Also accept if tracker centre is inside Person bbox
                if iou < best_iou:
                    if pb[0] <= vcx <= pb[2] and pb[1] <= vcy <= pb[3]:
                        iou = best_iou + 0.001   # force selection
                if iou > best_iou:
                    best_iou = iou
                    best_pb  = pb
            if best_pb is not None:
                new_t = init_kcf_tracker(resized, best_pb)
                best_pb_int = _bbox_to_int(best_pb, resized)
                if new_t is not None:
                    vt["tracker"] = new_t
                    vt["bbox"]    = best_pb_int or list(best_pb)
                    vt["fails"]   = 0
                    vt["missed"]  = 0
                    vt["matched"] = True

    def _find_person_bbox_for(viol_bbox, person_bboxes, all_viol_bboxes):
        """
        Return the best full-body bbox for the person who has *viol_bbox*.

        Priority:
        1. YOLO Person bbox whose area contains the violation centre.
        2. YOLO Person bbox with best IoU (>5%).
        3. Synthetic bbox = union of all violation bboxes that overlap
           *viol_bbox* horizontally (same person, different body parts).
           Used when the model doesn't output a Person class at all.
        """
        cx = (viol_bbox[0] + viol_bbox[2]) / 2
        cy = (viol_bbox[1] + viol_bbox[3]) / 2

        # 1. Center containment (most reliable for small head/hand bboxes)
        for pb in person_bboxes:
            if pb[0] <= cx <= pb[2] and pb[1] <= cy <= pb[3]:
                return pb

        # 2. Best IoU with Person detections
        best_bbox, best_iou = None, 0.0
        for pb in person_bboxes:
            iou = _viol_iou(viol_bbox, pb)
            if iou > best_iou:
                best_iou, best_bbox = iou, pb
        if best_iou > 0.05:
            return best_bbox

        # 3. No Person class detected — build synthetic person bbox by
        #    unioning all violation bboxes that share the same horizontal
        #    column (x-ranges overlap → same person, different body parts).
        union = list(viol_bbox)
        for vb in all_viol_bboxes:
            if viol_bbox[0] < vb[2] and vb[0] < viol_bbox[2]:  # x-ranges overlap
                union[0] = min(union[0], vb[0])
                union[1] = min(union[1], vb[1])
                union[2] = max(union[2], vb[2])
                union[3] = max(union[3], vb[3])
        return union

    def _inject_mediapipe_gloves(resized, gloves_detections, filtered_detections, all_viol_bboxes):
        """Inject a NO-Gloves detection from MediaPipe hand landmarks when gloves absent."""
        # Run MediaPipe BEFORE the KCF violation loop so that bare-hand
        # detections go through the same tracker path as NH/NV and get
        # merged into the ONE orange box per person.
        if not (_run_gloves_mp and _mp_hands is not None):
            return
        try:
            mp_rgb    = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
            mp_image  = mp.Image(image_format=mp.ImageFormat.SRGB, data=mp_rgb)
            mp_result = _mp_hands.detect(mp_image)
            if not mp_result.hand_landmarks:
                return
            h_mp, w_mp = resized.shape[:2]
            glove_candidates = [
                d for d in gloves_detections
                if any(k in _class_key(d.get("class")) for k in ("glove", "bare-hand", "bare-hands"))
            ]
            glove_top = max(glove_candidates, key=lambda d: d.get("conf", 0.0)) if glove_candidates else None
            gloves_ok = glove_top is not None and _is_safe_class(glove_top.get("class"))
            if gloves_ok:
                return
            # Compute ONE union bbox covering ALL detected hands.
            # Injecting one entry per hand causes duplicate trackers and
            # duplicate DB alerts when two hands are detected.
            all_hx1, all_hy1, all_hx2, all_hy2 = [], [], [], []
            for hand_lm in mp_result.hand_landmarks:
                xs = [lm.x for lm in hand_lm]
                ys = [lm.y for lm in hand_lm]
                all_hx1.append(max(0,     int(min(xs) * w_mp) - 20))
                all_hy1.append(max(0,     int(min(ys) * h_mp) - 20))
                all_hx2.append(min(w_mp,  int(max(xs) * w_mp) + 20))
                all_hy2.append(min(h_mp,  int(max(ys) * h_mp) + 20))
            union_box = [min(all_hx1), min(all_hy1), max(all_hx2), max(all_hy2)]
            filtered_detections.append({
                "id":              -1,
                "box":             union_box,
                "conf":            glove_top.get("conf", 0.5) if glove_top else 0.5,
                "class":           "NO-Gloves",
                "_from_mediapipe": True,
            })
            all_viol_bboxes.append(union_box)
        except Exception as mp_ex:
            print(f"[Camera {cam_id}] MediaPipe inject error: {mp_ex}")

    def _run_ppe_violation_loop(resized, filtered_detections, person_bboxes, all_viol_bboxes):
        """
        For each violation detection: find/create a KCF tracker for the person,
        fire the alert if this is a new violation, then deduplicate and prune trackers.
        """
        logged_this_frame: set = set()
        for det in filtered_detections:
            vk = _class_key(det.get("class"))
            if not _is_violation_class(det.get("class")):
                continue
            if vk in logged_this_frame:
                continue

            bbox = det.get("box")

            # Resolve full-body person bbox FIRST — used for both tracker lookup
            # and KCF init so all violations on the same person share a single
            # orange box regardless of which body part YOLO detected (head, torso, hands).
            tracker_bbox = _find_person_bbox_for(bbox, person_bboxes, all_viol_bboxes) if bbox else bbox

            # Search existing trackers using the person bbox, not the small
            # violation bbox — ensures no-gloves / no-vest / no-hardhat all
            # resolve to the same tracker entry.
            existing = _find_tracker(tracker_bbox) if tracker_bbox else None

            if existing is not None and vk in existing["alerted"]:
                existing["matched"] = True
                existing["missed"]  = 0
                # Violation already alerted for this tracker — re-anchor KCF so
                # it doesn't drift. Re-init only when KCF is struggling (fails > 0)
                # OR the bbox has drifted significantly from the YOLO detection.
                if tracker_bbox and (
                    existing["fails"] > 0
                    or _viol_iou(tracker_bbox, existing["bbox"]) < 0.5
                ):
                    new_t = init_kcf_tracker(resized, tracker_bbox)
                    tracker_bbox_int = _bbox_to_int(tracker_bbox, resized)
                    if new_t is not None:
                        existing["tracker"] = new_t
                        existing["bbox"]    = tracker_bbox_int or list(tracker_bbox)
                        existing["fails"]   = 0
                continue   # same person, same violation class — skip alert

            # Assign session_id: reuse from existing tracker or create new
            session_id   = existing["session_id"] if existing else str(uuid.uuid4())
            is_truly_new = existing is None

            # No active tracker — check bbox cache before treating as brand new
            if is_truly_new and tracker_bbox:
                _now_tc     = time.time()
                best_cached = None
                best_iou    = TRACKER_CACHE_IOU
                for ce in _tracker_cache:
                    if _now_tc - ce["saved_at"] >= TRACKER_CACHE_TTL:
                        continue
                    iou = _viol_iou(tracker_bbox, ce["bbox"])
                    if iou > best_iou:
                        best_iou    = iou
                        best_cached = ce
                if best_cached is not None:
                    # Same person returned to same area — restore their identity
                    session_id   = best_cached["session_id"]
                    is_truly_new = False
                    # If this violation was already alerted in their previous visit, skip
                    if vk in best_cached["alerted"]:
                        # Re-init KCF and restore full alerted set
                        new_t = init_kcf_tracker(resized, tracker_bbox)
                        tracker_bbox_int = _bbox_to_int(tracker_bbox, resized)
                        if new_t is not None:
                            _viol_trackers.append({
                                "tracker":    new_t,
                                "bbox":       tracker_bbox_int or list(tracker_bbox),
                                "alerted":    set(best_cached["alerted"]),
                                "fails":      0,
                                "missed":     0,
                                "matched":    True,
                                "session_id": session_id,
                            })
                        _tracker_cache.remove(best_cached)
                        logged_this_frame.add(vk)
                        continue   # skip alert — already fired for this person

            if record_violation(det, resized, allow_snapshot=is_truly_new,
                                session_tracker_id=session_id, skip_cooldown=True):
                logged_this_frame.add(vk)
                if tracker_bbox:
                    if existing is not None:
                        # Same person, new violation class (e.g. NH tracked, now NV)
                        # Also re-anchor KCF with fresh YOLO bbox.
                        existing["matched"] = True
                        existing["missed"]  = 0
                        existing["alerted"].add(vk)
                        new_t = init_kcf_tracker(resized, tracker_bbox)
                        tracker_bbox_int = _bbox_to_int(tracker_bbox, resized)
                        if new_t is not None:
                            existing["tracker"] = new_t
                            existing["bbox"]    = tracker_bbox_int or list(tracker_bbox)
                            existing["fails"]   = 0
                    else:
                        # New person (or returning with a new violation) — init KCF
                        # using full-body person bbox so all violations link to it
                        new_t = init_kcf_tracker(resized, tracker_bbox)
                        tracker_bbox_int = _bbox_to_int(tracker_bbox, resized)
                        if new_t is not None:
                            _viol_trackers.append({
                                "tracker":    new_t,
                                "bbox":       tracker_bbox_int or list(tracker_bbox),
                                "alerted":    {vk},
                                "fails":      0,
                                "missed":     0,
                                "matched":    True,
                                "session_id": session_id,
                            })

        # Deduplicate trackers — merge any two entries for the same person.
        # Duplicate trackers can form when KCF drifts and _find_tracker misses
        # the existing entry on a subsequent frame.
        if len(_viol_trackers) > 1:
            dedup: list = []
            used:  set  = set()
            for i, vta in enumerate(_viol_trackers):
                if i in used:
                    continue
                for j, vtb in enumerate(_viol_trackers):
                    if j <= i or j in used:
                        continue
                    if _viol_iou(vta["bbox"], vtb["bbox"]) > VIOL_IOU_THRESHOLD:
                        # Same person — merge vtb into vta
                        vta["alerted"].update(vtb["alerted"])
                        vta["matched"] = bool(vta.get("matched") or vtb.get("matched"))
                        vta["missed"]  = min(vta.get("missed", 0), vtb.get("missed", 0))
                        used.add(j)
                dedup.append(vta)
                used.add(i)
            _viol_trackers.clear()
            _viol_trackers.extend(dedup)

        # Drop stale KCF boxes not confirmed by current YOLO detections.
        # KCF can keep returning ok=True after locking onto background texture.
        # Keep it only as a short bridge across missed detections; a tracker
        # must be confirmed again by a Person/violation detection to survive.
        confirmed = []
        for vt in _viol_trackers:
            if vt.get("matched"):
                vt["missed"] = 0
                confirmed.append(vt)
                continue
            vt["missed"] = vt.get("missed", 0) + 1
            if vt["missed"] <= VIOL_MAX_MISSED_DETECTIONS:
                confirmed.append(vt)
            else:
                _cache_violation_tracker(vt)
        _viol_trackers.clear()
        _viol_trackers.extend(confirmed)

    def _draw_tracker_boxes(resized):
        """Draw one orange box per confirmed/trailing tracked violating person."""
        # Original red NH/NV boxes are drawn separately by _draw_ppe_detections.
        for vt in _viol_trackers:
            draw_bbox = _bbox_to_int(vt.get("bbox"), resized)
            if draw_bbox is None:
                continue
            vt["bbox"] = draw_bbox
            x1, y1, x2, y2 = draw_bbox
            cv2.rectangle(resized, (x1, y1), (x2, y2), VIOL_ORANGE, 1)

    def _is_burglar_person(c):
        return c and c.strip().lower() in {"person", "persona", "human"}

    def _handle_burglar_alarm(resized, burglar_candidates_raw):
        """KCF-tracked burglar alarm: detect intruder in zone and raise alert."""
        if not (burglar_alarm_config and burglar_alarm_config.get("alarm_enabled")):
            return
        ba_cooldown   = float(burglar_alarm_config.get("cooldown_sec", 30))
        start_t       = burglar_alarm_config.get("alarm_start_time", "20:00")
        end_t         = burglar_alarm_config.get("alarm_end_time",   "06:00")
        window_active = is_in_alarm_window(start_t, end_t)

        if not window_active and _ba["tracking"]:
            _ba["tracker"] = None; _ba["tracking"] = False
            _ba["fail_count"] = 0; _ba["frames_since_check"] = 0; _ba["last_saved_bbox"] = None
            print(f"[Camera {cam_id}] KCF tracker reset — alarm window closed")

        if not window_active:
            return

        frame_h, frame_w = resized.shape[:2]
        zone_pts = burglar_alarm_config.get("monitored_zone_points")

        if _ba["tracking"] and _ba["tracker"] is not None:
            kcf_ok, kcf_rect = _ba["tracker"].update(resized)
            if not kcf_ok:
                _ba["fail_count"] += 1
                if _ba["fail_count"] >= BA_MAX_FAILS:
                    _ba["tracker"] = None; _ba["tracking"] = False
                    _ba["fail_count"] = 0; _ba["frames_since_check"] = 0; _ba["last_saved_bbox"] = None
                    print(f"[Camera {cam_id}] KCF lost intruder — IDLE")
            else:
                _ba["fail_count"] = 0
                kx, ky, kw, kh = [int(v) for v in kcf_rect]
                kx2, ky2 = kx + kw, ky + kh
                _ba["frames_since_check"] += 1
                if _ba["frames_since_check"] >= BA_REDETECT_INTERVAL:
                    _ba["frames_since_check"] = 0
                    still_in = (zone_pts is None or
                                is_person_in_zone({"box": [kx, ky, kx2, ky2]},
                                                  zone_pts, frame_w, frame_h))
                    if not still_in:
                        _ba["tracker"] = None; _ba["tracking"] = False
                        _ba["fail_count"] = 0; _ba["last_saved_bbox"] = None
                        print(f"[Camera {cam_id}] KCF — intruder left zone, IDLE")
                if _ba["tracking"]:
                    cv2.rectangle(resized, (kx, ky), (kx2, ky2), (0, 165, 255), 2)
                    cv2.putText(resized, f"INTRUDER TRACKING {_ba['tracked_conf']:.2f}",
                                (kx, ky - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)
        else:
            if (time.time() - _ba["last_alarm_time"]) > ba_cooldown:
                for det in burglar_candidates_raw:
                    if not _is_burglar_person(det.get("class")):
                        continue
                    in_zone = (zone_pts is None or
                               is_person_in_zone(det, zone_pts, frame_w, frame_h))
                    if not in_zone:
                        continue
                    det_bbox = det["box"]
                    if (_ba["last_saved_bbox"] is not None and
                            _viol_iou(det_bbox, _ba["last_saved_bbox"]) > BA_IoU_THRESHOLD):
                        continue
                    new_tracker = init_kcf_tracker(resized, det_bbox)
                    if new_tracker is not None:
                        _ba["tracker"] = new_tracker; _ba["tracking"] = True
                        _ba["fail_count"] = 0; _ba["frames_since_check"] = 0
                        _ba["tracked_conf"] = det["conf"]
                    _ba["last_alarm_time"] = time.time()
                    snap_path    = save_snapshot(resized, cam_id, snapshot_dir)
                    buzzer_fired = fire_buzzers(assigned_buzzers, cam_id) if assigned_buzzers else False
                    if burglar_test_sound:
                        play_test_sound(cam_id)
                    if alert_queue is not None:
                        alert_queue.put({
                            "camera_id":          cam_id,
                            "model_name":         "burglar_alarm",
                            "violation_type":     "burglar_alarm",
                            "confidence_score":   det["conf"],
                            "snapshot_path":      snap_path,
                            "buzzer_activated":   buzzer_fired,
                            "zone_id":            burglar_alarm_config.get("monitored_zone_id"),
                            "tracker_initialized": _ba["tracking"],
                            "bbox_x1": int(det_bbox[0]), "bbox_y1": int(det_bbox[1]),
                            "bbox_x2": int(det_bbox[2]), "bbox_y2": int(det_bbox[3]),
                            "frame_width": frame_w, "frame_height": frame_h,
                        })
                        _ba["last_saved_bbox"] = list(det_bbox)
                    print(f"[Camera {cam_id}] BURGLAR ALARM — intruder detected "
                          f"({start_t}–{end_t}), KCF started (conf={det['conf']:.2f})")
                    break

    def _handle_vehicle_detection(resized, vehicle_dets_raw):
        """Run OCR pipeline for each new vehicle; queue events and draw boxes."""
        if vehicle_dets_raw is None:
            return
        if _enabled_set is not None and "vehicle_detection" not in _enabled_set:
            return
        now_v = time.time()
        for vdet in vehicle_dets_raw:
            vbox    = vdet.get("box") or []
            pos_key = make_position_key(vbox)
            if now_v - _vehicle_last_seen.get(pos_key, 0) <= VEHICLE_COOLDOWN_SEC:
                continue
            # Run OCR pipeline — crops, plate detection, EasyOCR, snapshots
            event    = process_vehicle_detection(resized, vdet, cam_id, snapshot_dir)
            # Use plate number as dedup key when available (same plate, slight drift)
            dedup_key = event.get("plate_number") or pos_key
            if now_v - _vehicle_last_seen.get(dedup_key, 0) <= VEHICLE_COOLDOWN_SEC:
                continue
            _vehicle_last_seen[pos_key]   = now_v
            _vehicle_last_seen[dedup_key] = now_v
            if alert_queue is not None:
                alert_queue.put(event)
        # Draw bounding boxes on every frame (lightweight, no cooldown)
        for vdet in vehicle_dets_raw:
            if not vdet.get("box"):
                continue
            vx1, vy1, vx2, vy2 = map(int, vdet["box"])
            cv2.rectangle(resized, (vx1, vy1), (vx2, vy2), (0, 165, 255), 2)
            cv2.putText(
                resized,
                f"{vdet['class']} {vdet['conf']:.2f}",
                (vx1, max(0, vy1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 165, 255), 2,
            )

    def _draw_ppe_detections(resized, filtered_detections):
        """Draw class-coloured bounding boxes for all PPE detections."""
        for det in filtered_detections:
            x1, y1, x2, y2 = map(int, det["box"])
            class_name   = det["class"]
            display_name = _DISPLAY_NAMES.get(class_name, class_name)
            cls_key = str(class_name).strip().lower().replace("_", "-").replace(" ", "-")

            if any(k in cls_key for k in ("helmet", "hardhat", "-hat", "hat")):
                display_name = "NH" if (cls_key.startswith("no-") or "-no-" in cls_key
                                        or cls_key.startswith("without-")) else ""
                if not display_name: continue
            if any(k in cls_key for k in ("vest",)):
                display_name = "NV" if (cls_key.startswith("no-") or "-no-" in cls_key
                                        or cls_key.startswith("without-")) else ""
                if not display_name: continue
            if any(k in cls_key for k in ("goggle", "glasses")):
                display_name = "NGL" if (cls_key.startswith("no-") or "-no-" in cls_key
                                         or cls_key.startswith("without-")) else ""
                if not display_name: continue
            if any(k in cls_key for k in ("glove",)):
                display_name = "NGO" if (cls_key.startswith("no-") or "-no-" in cls_key
                                         or cls_key.startswith("without-")) else ""
                if not display_name: continue

            if not display_name:
                label = ""
            elif display_name.upper() in ("NH", "NV", "NGO", "NGL"):
                label = display_name.upper()
            else:
                label = f"{display_name.upper()} {det['conf']:.2f}"
            color = (0, 255, 0) if _is_safe_class(class_name) else (0, 0, 255)

            if label in ("NH", "NV", "NGO", "NGL"):
                shrink_x = max(1, int((x2 - x1) * 0.12))
                shrink_y = max(1, int((y2 - y1) * 0.12))
                x1d = min(x2 - 1, x1 + shrink_x); y1d = min(y2 - 1, y1 + shrink_y)
                x2d = max(x1d + 1, x2 - shrink_x); y2d = max(y1d + 1, y2 - shrink_y)
                bt, ls, lt = 1, 0.35, 1
            else:
                x1d, y1d, x2d, y2d = x1, y1, x2, y2
                bt, ls, lt = 2, 0.6, 2
            cv2.rectangle(resized, (x1d, y1d), (x2d, y2d), color, bt)
            if label:
                cv2.putText(resized, label, (x1d, y1d - 10),
                            cv2.FONT_HERSHEY_SIMPLEX, ls, color, lt)

    def _update_stats_throttled(fps, jpeg_bytes):
        """Update shared stats dict at most once per second."""
        nonlocal _last_stats_ts
        now_s = time.time()
        if now_s - _last_stats_ts >= 1.0:
            set_stats("running", round(fps, 1), violations, frame_count,
                      extra={"frame_buffer_bytes": len(jpeg_bytes)})
            _last_stats_ts = now_s

    # ── Main loop ──────────────────────────────────────────────────────────

    set_stats("running", 0, 0, 0)

    while True:
        if stop_event is not None and stop_event.is_set():
            break

        try:
            item = result_queue.get(timeout=0.1)
        except _Empty:
            continue

        if item is None:   # stop sentinel
            break

        # Unpack — extra_dets is a dict {model_name: [detections] | None}
        # None means "same as main" (inference server reused main model for that key)
        _cam_id_in, frame_payload, ts, detections, extra_dets = item

        resized = _decode_frame(frame_payload)
        gloves_detections, burglar_candidates_raw, vehicle_dets_raw = (
            _resolve_detections(detections, extra_dets)
        )
        filtered_detections = _filter_and_roi(detections, gloves_detections, resized)

        frame_count += 1
        start = time.time()

        person_bboxes = [
            det["box"] for det in filtered_detections
            if det.get("class", "").strip().lower() in {"person", "persona", "human"}
            and det.get("box")
        ]
        person_count  = len(person_bboxes)
        all_viol_bboxes = [
            det["box"] for det in filtered_detections
            if _is_violation_class(det.get("class")) and det.get("box")
        ]

        _handle_missing_person_alert(person_count, resized)
        _handle_crowd_alert(person_count, resized)
        _update_ppe_trackers(resized)
        _reanchor_person_trackers(resized, person_bboxes)
        _inject_mediapipe_gloves(resized, gloves_detections, filtered_detections, all_viol_bboxes)
        _run_ppe_violation_loop(resized, filtered_detections, person_bboxes, all_viol_bboxes)
        _draw_tracker_boxes(resized)
        _handle_burglar_alarm(resized, burglar_candidates_raw)
        _handle_vehicle_detection(resized, vehicle_dets_raw)
        _draw_ppe_detections(resized, filtered_detections)

        fps = 1.0 / (time.time() - start + 1e-5)
        cv2.putText(resized, f"Cam {cam_id} | FPS: {fps:.1f} | Violations: {violations}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        # Manager dict is already serialised internally; explicit lock is redundant
        # and adds 2 extra IPC round-trips per frame.
        _, jpeg    = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 80])
        jpeg_bytes = jpeg.tobytes()
        frame_dict[cam_id] = jpeg_bytes
        _update_stats_throttled(fps, jpeg_bytes)

    # ── Cleanup ────────────────────────────────────────────────────────────
    if _mp_hands is not None:
        try:
            _mp_hands.close()
        except Exception:
            pass
    set_stats("stopped", 0, 0, 0, extra={"frame_buffer_bytes": 0})


