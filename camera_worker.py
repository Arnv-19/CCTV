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


def result_handler_worker(
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

    # MediaPipe hand landmarker (CPU — stays in handler thread)
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

    # ── State ──────────────────────────────────────────────────────────────
    frame_count = 0
    violations  = 0
    last_alarm_times: dict = {}
    last_snapshot_times: dict = {}
    last_burglar_alarm_time = 0.0
    _last_stats_ts = 0.0

    feature_config = feature_config or {}
    missing_person_cfg = feature_config.get("missing_person_alert") or {}
    crowd_alert_cfg = feature_config.get("crowd_alert") or {}
    missing_person_frames = 0
    crowd_threshold_started_at = None

    ba_tracker           = None
    ba_tracking          = False
    ba_track_fail_count  = 0
    BA_MAX_FAILS         = 5
    BA_REDETECT_INTERVAL = 30
    ba_frames_since_check = 0
    ba_tracked_conf      = 0.0
    ba_last_saved_bbox   = None
    BA_IoU_THRESHOLD     = 0.3

    # ── Per-person PPE violation trackers ─────────────────────────────────
    # One KCF per violating person in frame. Each tracker covers ALL violation
    # classes for that person — prevents re-alerting the same person while
    # they remain visible. Each entry:
    #   {"tracker": cv2.TrackerKCF, "bbox": [x1,y1,x2,y2],
    #    "alerted": set of violation_keys already fired, "fails": int}
    # One orange box is drawn per tracker — original red NH/NV boxes come
    # from the "Draw detections" section unchanged.
    _viol_trackers: list  = []
    VIOL_MAX_FAILS        = 8
    VIOL_MAX_MISSED_DETECTIONS = 3
    VIOL_IOU_THRESHOLD    = 0.10
    VIOL_ORANGE           = (0, 165, 255)

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

    # ── Bbox-based tracker cache ──────────────────────────────────────────
    # Saves tracker params when KCF drops so a returning person at the
    # same location restores their session_id + alerted set.
    _tracker_cache: list = []          # list of saved tracker param dicts
    TRACKER_CACHE_TTL    = 30.0        # seconds to keep after tracker drops
    TRACKER_CACHE_IOU    = 0.30        # min IoU to consider "same person"

    def _cache_violation_tracker(vt):
        _tracker_cache.append({
            "bbox":       vt["bbox"],
            "alerted":    set(vt["alerted"]),
            "session_id": vt["session_id"],
            "saved_at":   time.time(),
        })

    set_stats("running", 0, 0, 0)

    while True:
        if stop_event is not None and stop_event.is_set():
            break

        # ── Read next result from inference server ─────────────────────────
        try:
            item = result_queue.get(timeout=0.1)
        except _Empty:
            continue

        if item is None:   # stop sentinel
            break

        # Unpack — extra_dets is a dict {model_name: [detections] | None}
        # None means "same as main" (inference server reused main model for that key)
        _cam_id_in, frame_payload, ts, detections, extra_dets = item

        # Decode JPEG bytes sent by inference server (reduces IPC data 18x).
        if isinstance(frame_payload, (bytes, bytearray)) and frame_payload:
            _dec = cv2.imdecode(np.frombuffer(frame_payload, np.uint8), cv2.IMREAD_COLOR)
            resized = _dec if _dec is not None else np.zeros(
                (RESIZE_DIM[1], RESIZE_DIM[0], 3), dtype=np.uint8
            )
        else:
            resized = frame_payload  # raw numpy fallback (legacy path)

        # Resolve None sentinels (same-model shortcut from inference server)
        gloves_dets = extra_dets.get("gloves")
        burglar_dets = extra_dets.get("burglar")
        gloves_detections = detections if gloves_dets is None else gloves_dets
        burglar_candidates_raw = detections if burglar_dets is None else burglar_dets
        # Resolve any remaining None sentinels in extra_dets
        extra_dets = {
            k: (detections if v is None else v)
            for k, v in extra_dets.items()
        }

        frame_count += 1
        start = time.time()

        # ── Filter: disabled classes + enabled_models ──────────────────────
        filtered_detections = []
        all_detections = (
            detections
            if gloves_detections is detections
            else detections + gloves_detections
        )
        for det in all_detections:
            if _class_key(det.get("class")) in _disabled_class_keys:
                continue
            model_name = _model_for_class(det["class"])
            if _enabled_set is not None and model_name and model_name not in _enabled_set:
                continue
            filtered_detections.append(det)

        # ── ROI filtering ──────────────────────────────────────────────────
        _rois = _get_rois_for_camera(str(cam_id))
        if _rois:
            for _d in filtered_detections:
                _d["x1"], _d["y1"], _d["x2"], _d["y2"] = _d["box"]
            frame_h_px, frame_w_px = resized.shape[:2]
            filtered_detections, _ = filter_detections(
                filtered_detections, str(cam_id), frame_w_px, frame_h_px, rois=_rois
            )

        # ── Violation recording helper ─────────────────────────────────────
        def record_violation(det, violation_type=None, allow_snapshot=True, session_tracker_id=None, skip_cooldown=False):
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
            *,
            model_name,
            violation_type,
            confidence_score=0.0,
            send_whatsapp=False,
            fire_alarm=False,
        ):
            nonlocal violations
            violations += 1
            snap_path = save_snapshot(resized, cam_id, snapshot_dir)
            buzzer_fired = fire_buzzers(assigned_buzzers, cam_id) if fire_alarm and assigned_buzzers else False
            if send_whatsapp:
                send_snapshot_best_effort(
                    snap_path,
                    f"AXIS CCTV {violation_type} | Camera {cam_id}",
                )
            if alert_queue is not None:
                alert_queue.put({
                    "camera_id":         cam_id,
                    "model_name":        model_name,
                    "violation_type":    violation_type,
                    "confidence_score":  float(confidence_score or 0.0),
                    "snapshot_path":     snap_path,
                    "buzzer_activated":  buzzer_fired,
                })
            log_violation_file(cam_id, frame_count, (violations / frame_count) * 100, violation_type)
            return True

        # ── Step 1: update all active violation trackers ──────────────────
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

        # Prune expired tracker cache entries
        _now_tc = time.time()
        _tracker_cache[:] = [
            c for c in _tracker_cache
            if _now_tc - c["saved_at"] < TRACKER_CACHE_TTL
        ]

        # ── Step 2: check each violation — per person AND per class ───────
        # Build a list of Person bboxes from YOLO detections so that each
        # violation can be associated with the full-body bbox of the person
        # it belongs to.  This ensures no-gloves (small hand bbox) and
        # no-hardhat (head bbox) both link to the same KCF tracker.
        _person_bboxes = [
            det["box"] for det in filtered_detections
            if det.get("class", "").strip().lower() in {"person", "persona", "human"}
            and det.get("box")
        ]
        person_count = len(_person_bboxes)

        # ── Missing person alert ──────────────────────────────────────────
        if missing_person_cfg.get("enabled"):
            if person_count == 0:
                missing_person_frames += 1
            else:
                missing_person_frames = 0

            missing_threshold = int(missing_person_cfg.get("missing_frames", 3600))
            if missing_person_frames >= missing_threshold:
                record_system_alert(
                    model_name="missing_person",
                    violation_type="missing_person",
                    confidence_score=missing_person_frames,
                    send_whatsapp=bool(missing_person_cfg.get("send_whatsapp")),
                    fire_alarm=False,
                )
                missing_person_frames = 0

        # ── Crowd alert: threshold must remain exceeded for N seconds ─────
        if crowd_alert_cfg.get("enabled"):
            crowd_threshold = int(crowd_alert_cfg.get("person_threshold", 5))
            sustained_sec = max(0.0, float(crowd_alert_cfg.get("sustained_seconds", 5)))
            now_alert = time.time()
            if person_count >= crowd_threshold:
                if crowd_threshold_started_at is None:
                    crowd_threshold_started_at = now_alert
                if now_alert - crowd_threshold_started_at >= sustained_sec:
                    record_system_alert(
                        model_name="crowd_alert",
                        violation_type="crowd_threshold_exceeded",
                        confidence_score=person_count,
                        send_whatsapp=bool(crowd_alert_cfg.get("send_whatsapp")),
                        fire_alarm=True,
                    )
                    crowd_threshold_started_at = None
            else:
                crowd_threshold_started_at = None

        # ── Re-anchor active trackers using Person class detections ───────
        # YOLO Person detections are more reliable than violation detections
        # (higher confidence, bigger target). Re-anchor KCF every frame when
        # a Person bbox overlaps the tracker — prevents drift accumulating
        # even when violation confidence temporarily drops below threshold.
        for vt in _viol_trackers:
            best_pb, best_iou = None, 0.15   # min IoU to consider a match
            vcx = (vt["bbox"][0] + vt["bbox"][2]) / 2
            vcy = (vt["bbox"][1] + vt["bbox"][3]) / 2
            for pb in _person_bboxes:
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

        # All violation bboxes this frame — used to build a synthetic person
        # bbox when the model doesn't output a Person class detection.
        _all_viol_bboxes_this_frame = [
            det["box"] for det in filtered_detections
            if _is_violation_class(det.get("class")) and det.get("box")
        ]

        def _find_person_bbox_for(viol_bbox):
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
            for pb in _person_bboxes:
                if pb[0] <= cx <= pb[2] and pb[1] <= cy <= pb[3]:
                    return pb

            # 2. Best IoU with Person detections
            best_bbox, best_iou = None, 0.0
            for pb in _person_bboxes:
                iou = _viol_iou(viol_bbox, pb)
                if iou > best_iou:
                    best_iou, best_bbox = iou, pb
            if best_iou > 0.05:
                return best_bbox

            # 3. No Person class detected — build synthetic person bbox by
            #    unioning all violation bboxes that share the same horizontal
            #    column (x-ranges overlap → same person, different body parts).
            union = list(viol_bbox)
            for vb in _all_viol_bboxes_this_frame:
                if viol_bbox[0] < vb[2] and vb[0] < viol_bbox[2]:  # x-ranges overlap
                    union[0] = min(union[0], vb[0])
                    union[1] = min(union[1], vb[1])
                    union[2] = max(union[2], vb[2])
                    union[3] = max(union[3], vb[3])
            return union

        # ── Inject MediaPipe no-gloves detections into filtered_detections ─
        # Run MediaPipe BEFORE the KCF violation loop so that bare-hand
        # detections go through the same tracker path as NH/NV and get
        # merged into the ONE orange box per person.
        if _run_gloves_mp and _mp_hands is not None:
            try:
                _mp_rgb    = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
                _mp_image  = mp.Image(image_format=mp.ImageFormat.SRGB, data=_mp_rgb)
                _mp_result = _mp_hands.detect(_mp_image)
                if _mp_result.hand_landmarks:
                    _h_mp, _w_mp = resized.shape[:2]
                    _glove_candidates = [
                        d for d in gloves_detections
                        if any(k in _class_key(d.get("class"))
                               for k in ("glove", "bare-hand", "bare-hands"))
                    ]
                    _glove_top  = max(_glove_candidates, key=lambda d: d.get("conf", 0.0)) if _glove_candidates else None
                    _gloves_ok  = _glove_top is not None and _is_safe_class(_glove_top.get("class"))
                    if not _gloves_ok:
                        # Compute ONE union bbox covering ALL detected hands.
                        # Injecting one entry per hand causes duplicate trackers
                        # and duplicate DB alerts when two hands are detected.
                        _all_hx1, _all_hy1, _all_hx2, _all_hy2 = [], [], [], []
                        for _hand_lm in _mp_result.hand_landmarks:
                            _xs = [lm.x for lm in _hand_lm]
                            _ys = [lm.y for lm in _hand_lm]
                            _all_hx1.append(max(0,      int(min(_xs) * _w_mp) - 20))
                            _all_hy1.append(max(0,      int(min(_ys) * _h_mp) - 20))
                            _all_hx2.append(min(_w_mp,  int(max(_xs) * _w_mp) + 20))
                            _all_hy2.append(min(_h_mp,  int(max(_ys) * _h_mp) + 20))
                        _union_box = [
                            min(_all_hx1), min(_all_hy1),
                            max(_all_hx2), max(_all_hy2),
                        ]
                        filtered_detections.append({
                            "id":    -1,
                            "box":   _union_box,
                            "conf":  _glove_top.get("conf", 0.5) if _glove_top else 0.5,
                            "class": "NO-Gloves",
                            "_from_mediapipe": True,
                        })
                        _all_viol_bboxes_this_frame.append(_union_box)
            except Exception as _mp_ex:
                print(f"[Camera {cam_id}] MediaPipe inject error: {_mp_ex}")

        logged_this_frame: set = set()
        for det in filtered_detections:
            vk = _class_key(det.get("class"))
            if not _is_violation_class(det.get("class")):
                continue
            if vk in logged_this_frame:
                continue

            bbox = det.get("box")

            # Resolve full-body person bbox FIRST — used for both tracker
            # lookup and KCF init so all violations on the same person
            # share a single orange box regardless of which body part YOLO
            # detected the violation on (head, torso, hands, etc.)
            tracker_bbox = _find_person_bbox_for(bbox) if bbox else bbox

            # Search existing trackers using the person bbox, not the small
            # violation bbox — ensures no-gloves / no-vest / no-hardhat all
            # resolve to the same tracker entry.
            existing = _find_tracker(tracker_bbox) if tracker_bbox else None

            if existing is not None and vk in existing["alerted"]:
                existing["matched"] = True
                existing["missed"] = 0
                # Violation already alerted for this tracker — but use the fresh
                # YOLO bbox to re-anchor KCF so it doesn't drift.  Re-init only
                # when KCF is starting to struggle (fails > 0) OR the bbox has
                # drifted significantly from the YOLO detection.
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
                _now_tc = time.time()
                best_cached = None
                best_iou    = TRACKER_CACHE_IOU
                for ce in _tracker_cache:
                    if _now_tc - ce["saved_at"] >= TRACKER_CACHE_TTL:
                        continue
                    iou = _viol_iou(tracker_bbox, ce["bbox"])
                    if iou > best_iou:
                        best_iou   = iou
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

            if record_violation(det, allow_snapshot=is_truly_new, session_tracker_id=session_id, skip_cooldown=True):
                logged_this_frame.add(vk)
                if tracker_bbox:
                    if existing is not None:
                        # Same person, new violation class (e.g. NH tracked, now NV)
                        # Also re-anchor KCF with fresh YOLO bbox.
                        existing["matched"] = True
                        existing["missed"] = 0
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

        # ── Deduplicate trackers — merge any two entries for the same person ─
        # Duplicate trackers can form when KCF drifts and _find_tracker misses
        # the existing entry on a subsequent frame. Merge overlapping entries.
        if len(_viol_trackers) > 1:
            _dedup: list = []
            _used:  set  = set()
            for _i, _vta in enumerate(_viol_trackers):
                if _i in _used:
                    continue
                for _j, _vtb in enumerate(_viol_trackers):
                    if _j <= _i or _j in _used:
                        continue
                    if _viol_iou(_vta["bbox"], _vtb["bbox"]) > VIOL_IOU_THRESHOLD:
                        # Same person — merge vtb into vta
                        _vta["alerted"].update(_vtb["alerted"])
                        _vta["matched"] = bool(_vta.get("matched") or _vtb.get("matched"))
                        _vta["missed"] = min(_vta.get("missed", 0), _vtb.get("missed", 0))
                        _used.add(_j)
                _dedup.append(_vta)
                _used.add(_i)
            _viol_trackers.clear()
            _viol_trackers.extend(_dedup)

        # ── Drop stale KCF boxes not confirmed by current YOLO detections ─
        # KCF can keep returning ok=True after locking onto background texture.
        # Keep it only as a short bridge across missed detections; a tracker
        # must be confirmed again by a Person/violation detection to survive.
        _confirmed_trackers = []
        for vt in _viol_trackers:
            if vt.get("matched"):
                vt["missed"] = 0
                _confirmed_trackers.append(vt)
                continue

            vt["missed"] = vt.get("missed", 0) + 1
            if vt["missed"] <= VIOL_MAX_MISSED_DETECTIONS:
                _confirmed_trackers.append(vt)
            else:
                _cache_violation_tracker(vt)
        _viol_trackers.clear()
        _viol_trackers.extend(_confirmed_trackers)

        # ── Draw ONE orange box per confirmed/trailing tracked person ──────
        # Original red NH/NV boxes are drawn by "Draw detections" below.
        for vt in _viol_trackers:
            draw_bbox = _bbox_to_int(vt.get("bbox"), resized)
            if draw_bbox is None:
                continue
            vt["bbox"] = draw_bbox
            x1, y1, x2, y2 = draw_bbox
            cv2.rectangle(resized, (x1, y1), (x2, y2), VIOL_ORANGE, 1)

        # ── Burglar alarm (KCF tracking) ───────────────────────────────────
        if burglar_alarm_config and burglar_alarm_config.get("alarm_enabled"):
            ba_cooldown  = float(burglar_alarm_config.get("cooldown_sec", 30))
            start_t      = burglar_alarm_config.get("alarm_start_time", "20:00")
            end_t        = burglar_alarm_config.get("alarm_end_time",   "06:00")
            window_active = is_in_alarm_window(start_t, end_t)

            if not window_active and ba_tracking:
                ba_tracker = None; ba_tracking = False
                ba_track_fail_count = 0; ba_frames_since_check = 0; ba_last_saved_bbox = None
                print(f"[Camera {cam_id}] KCF tracker reset — alarm window closed")

            if window_active:
                frame_h_px, frame_w_px = resized.shape[:2]
                zone_pts = burglar_alarm_config.get("monitored_zone_points")

                def _is_burglar_person(c):
                    return c and c.strip().lower() in {"person", "persona", "human"}

                def _compute_iou(box1, box2):
                    if box1 is None or box2 is None: return 0.0
                    x1_1, y1_1, x2_1, y2_1 = box1
                    x1_2, y1_2, x2_2, y2_2 = box2
                    xi1, yi1 = max(x1_1, x1_2), max(y1_1, y1_2)
                    xi2, yi2 = min(x2_1, x2_2), min(y2_1, y2_2)
                    if xi2 < xi1 or yi2 < yi1: inter_area = 0.0
                    else: inter_area = (xi2 - xi1) * (yi2 - yi1)
                    area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
                    area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
                    union_area = area1 + area2 - inter_area
                    return inter_area / union_area if union_area > 0 else 0.0

                if ba_tracking and ba_tracker is not None:
                    kcf_ok, kcf_rect = ba_tracker.update(resized)
                    if not kcf_ok:
                        ba_track_fail_count += 1
                        if ba_track_fail_count >= BA_MAX_FAILS:
                            ba_tracker = None; ba_tracking = False
                            ba_track_fail_count = 0; ba_frames_since_check = 0; ba_last_saved_bbox = None
                            print(f"[Camera {cam_id}] KCF lost intruder — IDLE")
                    else:
                        ba_track_fail_count = 0
                        kx, ky, kw, kh = [int(v) for v in kcf_rect]
                        kx2, ky2 = kx + kw, ky + kh
                        ba_frames_since_check += 1
                        if ba_frames_since_check >= BA_REDETECT_INTERVAL:
                            ba_frames_since_check = 0
                            still_in = (zone_pts is None or
                                        is_person_in_zone({"box": [kx, ky, kx2, ky2]},
                                                          zone_pts, frame_w_px, frame_h_px))
                            if not still_in:
                                ba_tracker = None; ba_tracking = False
                                ba_track_fail_count = 0; ba_last_saved_bbox = None
                                print(f"[Camera {cam_id}] KCF — intruder left zone, IDLE")
                        if ba_tracking:
                            import cv2 as _cv2b
                            _cv2b.rectangle(resized, (kx, ky), (kx2, ky2), (0, 165, 255), 2)
                            _cv2b.putText(resized, f"INTRUDER TRACKING {ba_tracked_conf:.2f}",
                                          (kx, ky - 10), _cv2b.FONT_HERSHEY_SIMPLEX, 0.6,
                                          (0, 165, 255), 2)
                else:
                    if (time.time() - last_burglar_alarm_time) > ba_cooldown:
                        for det in burglar_candidates_raw:
                            if not _is_burglar_person(det.get("class")):
                                continue
                            in_zone = (zone_pts is None or
                                       is_person_in_zone(det, zone_pts, frame_w_px, frame_h_px))
                            if not in_zone:
                                continue
                            det_bbox = det["box"]
                            if _compute_iou(det_bbox, ba_last_saved_bbox) > BA_IoU_THRESHOLD:
                                continue
                            new_tracker = init_kcf_tracker(resized, det_bbox)
                            if new_tracker is not None:
                                ba_tracker = new_tracker; ba_tracking = True
                                ba_track_fail_count = 0; ba_frames_since_check = 0
                                ba_tracked_conf = det["conf"]
                            last_burglar_alarm_time = time.time()
                            snap_path    = save_snapshot(resized, cam_id, snapshot_dir)
                            buzzer_fired = fire_buzzers(assigned_buzzers, cam_id) if assigned_buzzers else False
                            if burglar_test_sound:
                                play_test_sound(cam_id)
                            if alert_queue is not None:
                                _box = det_bbox
                                alert_queue.put({
                                    "camera_id": cam_id, "model_name": "burglar_alarm",
                                    "violation_type": "burglar_alarm",
                                    "confidence_score": det["conf"], "snapshot_path": snap_path,
                                    "buzzer_activated": buzzer_fired,
                                    "zone_id": burglar_alarm_config.get("monitored_zone_id"),
                                    "tracker_initialized": ba_tracking,
                                    "bbox_x1": int(_box[0]), "bbox_y1": int(_box[1]),
                                    "bbox_x2": int(_box[2]), "bbox_y2": int(_box[3]),
                                    "frame_width": frame_w_px, "frame_height": frame_h_px,
                                })
                                ba_last_saved_bbox = list(_box)
                            print(f"[Camera {cam_id}] BURGLAR ALARM — intruder detected "
                                  f"({start_t}–{end_t}), KCF started (conf={det['conf']:.2f})")
                            break

        # ── Draw detections ────────────────────────────────────────────────
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

        # MediaPipe gloves are now injected into filtered_detections before
        # the KCF loop (see "Inject MediaPipe" block above) so the hand
        # bbox is tracked by the same orange KCF box as NH/NV.
        # The "Draw detections" loop above already drew the red NGO label
        # on the hand bbox from the injected detection, so nothing extra needed here.

        fps = 1.0 / (time.time() - start + 1e-5)
        cv2.putText(resized, f"Cam {cam_id} | FPS: {fps:.1f} | Violations: {violations}",
                    (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

        # ── MJPEG encode ───────────────────────────────────────────────────
        _, jpeg = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 80])
        jpeg_bytes = jpeg.tobytes()
        # Manager dict is already serialised internally; explicit lock is redundant
        # and adds 2 extra IPC round-trips per frame.
        frame_dict[cam_id] = jpeg_bytes

        # Throttle stats updates to once/second — each set_stats is 4 IPC ops.
        _now_stats = time.time()
        if _now_stats - _last_stats_ts >= 1.0:
            set_stats("running", round(fps, 1), violations, frame_count,
                      extra={"frame_buffer_bytes": len(jpeg_bytes)})
            _last_stats_ts = _now_stats

    # ── Cleanup ────────────────────────────────────────────────────────────
    if _mp_hands is not None:
        try:
            _mp_hands.close()
        except Exception:
            pass
    set_stats("stopped", 0, 0, 0, extra={"frame_buffer_bytes": 0})



# """
# camera_worker.py
# ----------------
# Per-camera capture and detection loop, designed to run in a dedicated thread.

# Each camera gets one thread running camera_loop(). The loop:
#   1. Opens the RTSP stream with OpenCV
#   2. Reads frames continuously
#   3. Resizes each frame and runs YOLOv8 inference
#   4. If a violation is detected:
#        - Saves a snapshot JPEG to snapshots/cam_{id}/
#        - Logs the alert to PostgreSQL (via alert_queue — non-blocking)
#        - Fires the assigned buzzers for this camera
#   5. Draws bounding boxes and stats overlay
#   6. Encodes the annotated frame as JPEG and writes it to frame_dict
#      for the MJPEG streaming endpoint

# alert_queue is a thread-safe Queue processed by AlertWriter (background thread
# in camera_manager) so DB writes never slow down frame processing.
# """

# import cv2
# import time
# import os
# import sys
# import subprocess
# import threading
# import numpy as np
# from datetime import datetime
# from pathlib import Path
# from queue import Queue

# import mediapipe as mp
# from mediapipe.tasks.python import vision as _mp_vision
# from mediapipe.tasks.python import BaseOptions as _MpBaseOptions

# _HAND_LANDMARKER_PATH = str(
#     __import__("pathlib").Path(__file__).parent / "weights" / "hand_landmarker.task"
# )

# from alarm import send_buzzer_command
# from detector import run_detection, load_model
# from roi_module.filter import filter_detections
# from roi_module.cache import get_roi_cache
# from app.services.burglar_alarm_service import (
#     is_in_alarm_window,
#     is_person_in_zone,
#     init_kcf_tracker,
# )

# def start_ffmpeg(rtsp_url: str, width: int = 960, height: int = 720) -> subprocess.Popen:
#     """
#     Launch an FFmpeg subprocess that reads the given RTSP (or local) stream
#     and writes raw BGR24 frames to stdout.

#     width / height must match the -vf scale= filter so that the caller can
#     slice the stdout byte-stream into exact frame_size chunks.
#     """
#     # For a numeric source (webcam index) fall back to OpenCV; FFmpeg needs a
#     # proper URL or device path, not a plain integer.
#     if isinstance(rtsp_url, int) or (isinstance(rtsp_url, str) and rtsp_url.isdigit()):
#         return None  # caller will use legacy cv2.VideoCapture for webcams

#     # fps is now configurable; default to 4 if not provided
#     fps = start_ffmpeg.ingestion_fps if hasattr(start_ffmpeg, "ingestion_fps") else 4
#     cmd = [
#         "ffmpeg",
#         "-loglevel", "warning",
#         "-rtsp_transport", "tcp",
#         "-stimeout", "10000000",   # 10s connection timeout (microseconds)
#         "-i", rtsp_url,
#         "-vf", f"scale={width}:{height},fps={fps},format=bgr24",
#         "-f", "rawvideo",
#         "-"
#     ]
#     return subprocess.Popen(
#         cmd,
#         stdout=subprocess.PIPE,
#         stderr=subprocess.PIPE,   # capture so we can log errors
#         bufsize=10 ** 8,
#     )


# def ensure_dir(path: str):
#     """Create a directory (and parents) if it does not already exist."""
#     Path(path).mkdir(parents=True, exist_ok=True)


# def save_snapshot(frame, cam_id: int, snapshot_dir: str) -> str | None:
#     """
#     Save the current frame as a JPEG snapshot.
#     Returns the relative path string, or None on failure.
#     """
#     try:
#         cam_dir = Path(snapshot_dir) / f"cam_{cam_id}"
#         ensure_dir(str(cam_dir))
#         ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
#         filename = f"violation_{ts}.jpg"
#         filepath = cam_dir / filename
#         cv2.imwrite(str(filepath), frame)
#         return str(filepath)
#     except Exception as e:
#         print(f"[Camera {cam_id}] Snapshot save failed: {e}")
#         return None


# def log_violation_file(
#     cam_id: int,
#     frame_index: int,
#     violation_rate: float,
#     violation_type: str = "violation",
# ):
#     """Append a violation line to the flat-file log (kept for backward compat)."""
#     ensure_dir("logs")
#     now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
#     with open("logs/alerts.log", "a") as f:
#         f.write(
#             f"[{now}] Camera {cam_id} | Frame {frame_index} | {violation_type} | Rate: {violation_rate:.2f}%\n"
#         )


# def fire_buzzers(buzzers: list, cam_id: int) -> bool:
#     """
#     Trigger all active buzzers assigned to this camera.
#     Returns True if at least one buzzer was fired.
#     `buzzers` is a list of Buzzer ORM-like dicts captured at thread-start.
#     """
#     fired = False
#     for b in buzzers:
#         if not b.get("is_active"):
#             continue
#         try:
#             protocol = b.get("protocol", "usb")
#             send_buzzer_command(
#                 state=True,
#                 use_wifi=(protocol == "http"),
#                 esp_ip=b.get("ip_address"),
#                 transport=protocol,
#                 mqtt_broker=b.get("ip_address", "") if protocol == "mqtt" else "",
#                 mqtt_port=b.get("port") or 1883,
#                 camera_id=cam_id,
#             )
#             fired = True
#         except Exception as e:
#             print(f"[Camera {cam_id}] Buzzer fire error (buzzer {b.get('id')}): {e}")
#     return fired



# def play_test_sound(cam_id: int):
#     """
#     Play a short non-blocking local machine sound for burglar alarm testing.
#     Best-effort only: failures are logged and ignored.
#     """
#     try:
#         if sys.platform == "darwin":
#             sound_path = "/System/Library/Sounds/Ping.aiff"
#             subprocess.Popen(
#                 ["afplay", sound_path],
#                 stdout=subprocess.DEVNULL,
#                 stderr=subprocess.DEVNULL,
#             )
#             return

#         # Fallback for other platforms: terminal bell (may be muted by terminal settings)
#         print("\a", end="", flush=True)
#     except Exception as e:
#         print(f"[Camera {cam_id}] Test sound failed: {e}")

# def _get_rois_for_camera(cam_id_str: str) -> list:
#     """Return active ROIs from cache; fall back to DB on cache miss."""
#     rois = get_roi_cache().get(cam_id_str)
#     if rois is not None:
#         return rois
#     try:
#         from app.db.database import SessionLocal
#         from roi_module.service import get_camera_rois_cached
#         if SessionLocal is not None:
#             with SessionLocal() as db:
#                 return get_camera_rois_cached(db, cam_id_str)
#     except Exception as e:
#         print(f"[ROI] Could not fetch ROIs for camera {cam_id_str}: {e}")
#     return []


# # # ─────────────────────────────────────────────────────────────────────────────
# # # InferenceWorker
# # # Runs in a dedicated daemon thread per camera (started by camera_loop).
# # # Reads the latest frame from frame_buffer at a controlled rate and executes
# # # all YOLO inference, violation detection, burglar alarm, and MJPEG encoding.
# # # All existing logic is preserved unchanged — only the execution model differs.
# # # ─────────────────────────────────────────────────────────────────────────────
# # def inference_worker(
# #     cam_id: int,
# #     frame_buffer: dict,              # {"frame": ndarray|None, "ts": float, "lock": Lock}
# #     model,
# #     threshold: float,
# #     helmet_class: str,
# #     no_helmet_class: str,
# #     cooldown: float,
# #     use_wifi: bool,
# #     esp_ip: str | None,
# #     frame_dict: dict,
# #     lock: threading.Lock,
# #     stop_event: threading.Event = None,
# #     stats_dict: dict = None,
# #     alarm_transport: str | None = None,
# #     alarm_http_token: str = "",
# #     mqtt_broker: str = "",
# #     mqtt_port: int = 1883,
# #     mqtt_username: str = "",
# #     mqtt_password: str = "",
# #     mqtt_topic: str = "skycctv/alarm",
# #     mqtt_client_id: str = "skycctv-ai",
# #     mqtt_qos: int = 1,
# #     mqtt_retain: bool = False,
# #     assigned_buzzers: list = None,
# #     alert_queue: Queue = None,
# #     snapshot_dir: str = "snapshots",
# #     snapshot_cooldown: float = 120,
# #     detection_width: int = 960,
# #     detection_height: int = 720,
# #     yolo_imgsz: int = 960,
# #     enabled_models: list = None,
# #     violation_classes: list = None,
# #     safe_classes: list = None,
# #     gloves_model = None,
# #     burglar_person_model = None,
# #     burglar_alarm_config: dict = None,
# #     burglar_test_sound: bool = False,
# #     inference_fps: float = 4.0,
# # ):
# #     """
# #     Inference worker thread.  Reads latest_frame from frame_buffer at a
# #     controlled rate (~inference_fps), runs YOLO, handles violations/alerts/
# #     burglar-alarm/MJPEG.  All existing logic is unchanged.
# #     """
# #     _inference_interval = 1.0 / max(1.0, float(inference_fps))
# #     _last_inference_ts  = 0.0   # frame_buffer["ts"] of the last processed frame
# #     _last_run_wall      = 0.0   # wall-clock time of the last inference pass

# #     thread_native_id = threading.get_native_id()

# #     def set_stats(
# #         status: str,
# #         fps: float = 0,
# #         violations: int = 0,
# #         frames: int = 0,
# #         extra: dict | None = None,
# #     ):
# #         if stats_dict is not None:
# #             with lock:
# #                 stats = dict(stats_dict.get(cam_id, {}))
# #                 stats.update({
# #                     "status": status, "fps": fps,
# #                     "violations": violations, "frames": frames,
# #                     "thread_native_id": thread_native_id,
# #                 })
# #                 if extra:
# #                     stats.update(extra)
# #                 stats_dict[cam_id] = stats

# #     def _class_key(class_name: str) -> str:
# #         return str(class_name or "").strip().lower().replace("_", "-").replace(" ", "-")

# #     _violation_set: set = set(violation_classes) if violation_classes else (
# #         {no_helmet_class} if no_helmet_class else set()
# #     )
# #     _safe_set: set = set(safe_classes) if safe_classes else (
# #         {helmet_class} if helmet_class else set()
# #     )
# #     _violation_keys: set = {_class_key(c) for c in _violation_set}
# #     _violation_keys.update({
# #         "no-hardhat", "no-hat", "no-helmet",
# #         "no-boot", "no-boots", "no-shoe", "no-shoes",
# #         "no-gloves", "bare-hand", "bare-hands",
# #         "no-safety-vest", "no-vest", "no-goggles", "no-glasses",
# #         # "no-mask",
# #         "fire",
# #     })
# #     _safe_keys: set = {_class_key(c) for c in _safe_set}
# #     _safe_keys.update({
# #         "hardhat", "hat", "helmet",
# #         "boot", "boots", "shoe", "shoes",
# #         "gloves", "safety-vest", "vest", "goggles", "glasses",
# #         # "mask",
# #     })
# #     _disabled_class_keys = {"mask", "no-mask"}

# #     def _is_violation_class(class_name: str) -> bool:
# #         return _class_key(class_name) in _violation_keys

# #     def _is_safe_class(class_name: str) -> bool:
# #         return _class_key(class_name) in _safe_keys

# #     _enabled_set: set | None = set(enabled_models) if enabled_models is not None else None

# #     _DISPLAY_NAMES: dict = {
# #         "NO-Hardhat": "NH", "NO-Hat": "NH", "Hardhat": "", "Hat": "",
# #         "no_helmet": "NH", "helmet": "",
# #         "NO-Safety Vest": "NV", "Safety Vest": "", "no_vest": "NV", "vest": "",
# #         "NO-Goggles": "NGL", "Goggles": "",
# #         "Gloves": "", "NO-Gloves": "NGO", "no-gloves": "NGO",
# #         "bare_hand": "NGO", "bare_hands": "NGO",
# #     }

# #     _CLASS_TO_MODEL: dict = {
# #         "no_helmet": "helmet_detection", "helmet": "helmet_detection",
# #         "no-hardhat": "helmet_detection", "no_hardhat": "helmet_detection",
# #         "hardhat": "helmet_detection", "no-hat": "helmet_detection",
# #         "no_hat": "helmet_detection", "hat": "helmet_detection",
# #         "no_vest": "vest_detection", "vest": "vest_detection",
# #         "no-safety vest": "vest_detection", "no_safety_vest": "vest_detection",
# #         "safety vest": "vest_detection", "safety_vest": "vest_detection",
# #         "no_glasses": "glasses_detection", "glasses": "glasses_detection",
# #         "no-goggles": "glasses_detection", "no_goggles": "glasses_detection",
# #         "goggles": "glasses_detection",
# #         "no-gloves": "gloves_detection", "no_gloves": "gloves_detection",
# #         "gloves": "gloves_detection", "bare-hand": "gloves_detection",
# #         "bare_hand": "gloves_detection", "bare_hands": "gloves_detection",
# #         # "no-mask": "mask_detection", "no_mask": "mask_detection", "mask": "mask_detection",
# #         "fire": "fire_detection",
# #     }

# #     def _model_for_class(class_name: str) -> str | None:
# #         if not class_name:
# #             return None
# #         key = class_name.strip().lower()
# #         if key in _CLASS_TO_MODEL:
# #             return _CLASS_TO_MODEL[key]
# #         key_norm = key.replace("-", "_").replace(" ", "_")
# #         return _CLASS_TO_MODEL.get(key_norm)

# #     _run_gloves = (
# #         gloves_model is not None
# #         and (_enabled_set is None or "gloves_detection" in _enabled_set)
# #     )

# #     _mp_hands = None
# #     if _run_gloves:
# #         _opts = _mp_vision.HandLandmarkerOptions(
# #             base_options=_MpBaseOptions(model_asset_path=_HAND_LANDMARKER_PATH),
# #             num_hands=4,
# #             min_hand_detection_confidence=0.5,
# #         )
# #         _mp_hands = _mp_vision.HandLandmarker.create_from_options(_opts)

# #     RESIZE_DIM = (
# #         max(320, int(detection_width or 960)),
# #         max(240, int(detection_height or 720)),
# #     )

# #     # ── Inference state ───────────────────────────────────────────────────
# #     frame_count = 0
# #     violations  = 0
# #     last_alarm_times: dict[str, float] = {}
# #     last_snapshot_times: dict[str, float] = {}
# #     last_burglar_alarm_time = 0.0

# #     # ── KCF tracker state for burglar alarm ───────────────────────────────
# #     ba_tracker           = None
# #     ba_tracking          = False
# #     ba_track_fail_count  = 0
# #     BA_MAX_FAILS         = 5
# #     BA_REDETECT_INTERVAL = 30
# #     ba_frames_since_check = 0
# #     ba_tracked_conf      = 0.0
# #     ba_last_saved_bbox   = None
# #     BA_IoU_THRESHOLD     = 0.3

# #     # ── Inference loop ────────────────────────────────────────────────────
# #     while True:
# #         if stop_event is not None and stop_event.is_set():
# #             break

# #         # ── Rate limiting: run inference at ~inference_fps ────────────────
# #         now = time.time()
# #         if now - _last_run_wall < _inference_interval:
# #             time.sleep(0.005)
# #             continue

# #         # ── Grab latest frame from buffer ─────────────────────────────────
# #         with frame_buffer["lock"]:
# #             frame_ts  = frame_buffer["ts"]
# #             raw_frame = frame_buffer["frame"]
# #             raw_frame = raw_frame.copy() if raw_frame is not None else None

# #         if raw_frame is None:
# #             time.sleep(0.02)
# #             continue

# #         # Skip if we already ran inference on this exact frame
# #         if frame_ts <= _last_inference_ts:
# #             time.sleep(0.005)
# #             continue

# #         _last_inference_ts = frame_ts
# #         _last_run_wall     = time.time()

# #         frame_count += 1
# #         start = time.time()
# #         resized = cv2.resize(raw_frame, RESIZE_DIM)

# #         # ── All existing inference / violation / burglar / MJPEG code ─────
# #         # (unchanged from original camera_loop — only moved here)

# #         def _is_burglar_person_class(class_name: str) -> bool:
# #             if not class_name:
# #                 return False
# #             return class_name.strip().lower() in {"person", "persona", "human"}

# #         def _compute_iou(box1, box2):
# #             if box1 is None or box2 is None:
# #                 return 0.0
# #             x1_1, y1_1, x2_1, y2_1 = box1
# #             x1_2, y1_2, x2_2, y2_2 = box2
# #             xi1, yi1 = max(x1_1, x1_2), max(y1_1, y1_2)
# #             xi2, yi2 = min(x2_1, x2_2), min(y2_1, y2_2)
# #             if xi2 < xi1 or yi2 < yi1:
# #                 inter_area = 0.0
# #             else:
# #                 inter_area = (xi2 - xi1) * (yi2 - yi1)
# #             area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
# #             area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
# #             union_area = area1 + area2 - inter_area
# #             if union_area <= 0:
# #                 return 0.0
# #             return inter_area / union_area

# #         detections = run_detection(model, resized, threshold, imgsz=yolo_imgsz)
# #         if _run_gloves:
# #             gloves_detections = detections if gloves_model is model else run_detection(
# #                 gloves_model, resized, threshold, imgsz=yolo_imgsz
# #             )
# #         else:
# #             gloves_detections = []

# #         filtered_detections = []
# #         all_detections = detections if gloves_detections is detections else detections + gloves_detections
# #         for det in all_detections:
# #             if _class_key(det.get("class")) in _disabled_class_keys:
# #                 continue
# #             model_name = _model_for_class(det["class"])
# #             if _enabled_set is not None and model_name and model_name not in _enabled_set:
# #                 continue
# #             filtered_detections.append(det)

# #         _rois = _get_rois_for_camera(str(cam_id))
# #         if _rois:
# #             for _d in filtered_detections:
# #                 _d["x1"], _d["y1"], _d["x2"], _d["y2"] = _d["box"]
# #             frame_h_px, frame_w_px = resized.shape[:2]
# #             filtered_detections, _ = filter_detections(
# #                 filtered_detections, str(cam_id), frame_w_px, frame_h_px, rois=_rois
# #             )

# #         def record_violation(det: dict, violation_type: str | None = None) -> bool:
# #             nonlocal violations

# #             violation_name = violation_type or det.get("class", "violation")
# #             violation_key = _class_key(violation_name)
# #             now = time.time()
# #             effective_cooldown = max(0.0, float(cooldown or 0))
# #             if now - last_alarm_times.get(violation_key, 0) <= effective_cooldown:
# #                 return False

# #             last_alarm_times[violation_key] = now
# #             violations += 1

# #             snapshot_key = violation_key
# #             snapshot_interval = max(0.0, float(snapshot_cooldown or 0))
# #             if now - last_snapshot_times.get(snapshot_key, 0) > snapshot_interval:
# #                 snap_path = save_snapshot(resized, cam_id, snapshot_dir)
# #                 last_snapshot_times[snapshot_key] = now
# #             else:
# #                 snap_path = None

# #             buzzer_fired = False
# #             if assigned_buzzers:
# #                 buzzer_fired = fire_buzzers(assigned_buzzers, cam_id)
# #             else:
# #                 from alarm import trigger_alarm
# #                 trigger_alarm(
# #                     cam_id, cooldown,
# #                     use_wifi=use_wifi, esp_ip=esp_ip,
# #                     transport=alarm_transport, token=alarm_http_token,
# #                     mqtt_broker=mqtt_broker, mqtt_port=mqtt_port,
# #                     mqtt_username=mqtt_username, mqtt_password=mqtt_password,
# #                     mqtt_topic=mqtt_topic, mqtt_client_id=mqtt_client_id,
# #                     mqtt_qos=mqtt_qos, mqtt_retain=mqtt_retain,
# #                 )
# #                 buzzer_fired = True

# #             if alert_queue is not None:
# #                 alert_queue.put({
# #                     "camera_id":        cam_id,
# #                     "model_name":       "ppe_detection",
# #                     "violation_type":   violation_name,
# #                     "confidence_score": det.get("conf", 0.0),
# #                     "snapshot_path":    snap_path,
# #                     "buzzer_activated": buzzer_fired,
# #                 })

# #             log_violation_file(cam_id, frame_count, (violations / frame_count) * 100, violation_name)
# #             return True

# #         logged_this_frame: set[str] = set()
# #         for det in filtered_detections:
# #             violation_key = _class_key(det.get("class"))
# #             if _is_violation_class(det.get("class")) and violation_key not in logged_this_frame:
# #                 if record_violation(det):
# #                     logged_this_frame.add(violation_key)

# #         # ── burglar alarm (KCF tracking) — unchanged ──────────────────────
# #         if burglar_alarm_config and burglar_alarm_config.get("alarm_enabled"):
# #             ba_cooldown = float(burglar_alarm_config.get("cooldown_sec", 30))
# #             start_t = burglar_alarm_config.get("alarm_start_time", "20:00")
# #             end_t   = burglar_alarm_config.get("alarm_end_time",   "06:00")
# #             window_active = is_in_alarm_window(start_t, end_t)

# #             if not window_active and ba_tracking:
# #                 ba_tracker   = None
# #                 ba_tracking  = False
# #                 ba_track_fail_count  = 0
# #                 ba_frames_since_check = 0
# #                 ba_last_saved_bbox = None
# #                 print(f"[Camera {cam_id}] KCF tracker reset — alarm window closed")

# #             if window_active:
# #                 frame_h_px, frame_w_px = resized.shape[:2]
# #                 zone_pts = burglar_alarm_config.get("monitored_zone_points")

# #                 if ba_tracking and ba_tracker is not None:
# #                     kcf_ok, kcf_rect = ba_tracker.update(resized)

# #                     if not kcf_ok:
# #                         ba_track_fail_count += 1
# #                         if ba_track_fail_count >= BA_MAX_FAILS:
# #                             ba_tracker  = None
# #                             ba_tracking = False
# #                             ba_track_fail_count  = 0
# #                             ba_frames_since_check = 0
# #                             ba_last_saved_bbox = None
# #                             print(
# #                                 f"[Camera {cam_id}] KCF lost intruder after "
# #                                 f"{BA_MAX_FAILS} failures — returning to IDLE"
# #                             )
# #                     else:
# #                         ba_track_fail_count = 0
# #                         kx, ky, kw, kh = [int(v) for v in kcf_rect]
# #                         kx2, ky2 = kx + kw, ky + kh

# #                         ba_frames_since_check += 1
# #                         if ba_frames_since_check >= BA_REDETECT_INTERVAL:
# #                             ba_frames_since_check = 0
# #                             tracked_det = {"box": [kx, ky, kx2, ky2]}
# #                             still_in_zone = (
# #                                 zone_pts is None
# #                                 or is_person_in_zone(tracked_det, zone_pts, frame_w_px, frame_h_px)
# #                             )
# #                             if not still_in_zone:
# #                                 ba_tracker  = None
# #                                 ba_tracking = False
# #                                 ba_track_fail_count  = 0
# #                                 ba_last_saved_bbox = None
# #                                 print(f"[Camera {cam_id}] KCF — intruder left zone, tracker reset to IDLE")

# #                         if ba_tracking:
# #                             cv2.rectangle(resized, (kx, ky), (kx2, ky2), (0, 165, 255), 2)
# #                             cv2.putText(
# #                                 resized,
# #                                 f"INTRUDER TRACKING {ba_tracked_conf:.2f}",
# #                                 (kx, ky - 10),
# #                                 cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2,
# #                             )

# #                 else:
# #                     if (time.time() - last_burglar_alarm_time) > ba_cooldown:
# #                         burglar_candidates = filtered_detections
# #                         if burglar_person_model is not None:
# #                             burglar_candidates = run_detection(
# #                                 burglar_person_model, resized, threshold, imgsz=yolo_imgsz
# #                             )

# #                         for det in burglar_candidates:
# #                             if not _is_burglar_person_class(det.get("class")):
# #                                 continue

# #                             in_zone = (
# #                                 zone_pts is None
# #                                 or is_person_in_zone(det, zone_pts, frame_w_px, frame_h_px)
# #                             )
# #                             if not in_zone:
# #                                 continue

# #                             det_bbox = det["box"]
# #                             iou_with_last = _compute_iou(det_bbox, ba_last_saved_bbox)
# #                             if iou_with_last > BA_IoU_THRESHOLD:
# #                                 continue

# #                             new_tracker = init_kcf_tracker(resized, det_bbox)
# #                             if new_tracker is not None:
# #                                 ba_tracker            = new_tracker
# #                                 ba_tracking           = True
# #                                 ba_track_fail_count   = 0
# #                                 ba_frames_since_check = 0
# #                                 ba_tracked_conf       = det["conf"]

# #                             last_burglar_alarm_time = time.time()
# #                             snap_path = save_snapshot(resized, cam_id, snapshot_dir)

# #                             buzzer_fired = False
# #                             if assigned_buzzers:
# #                                 buzzer_fired = fire_buzzers(assigned_buzzers, cam_id)
# #                             else:
# #                                 from alarm import trigger_alarm
# #                                 trigger_alarm(
# #                                     cam_id, ba_cooldown,
# #                                     use_wifi=use_wifi, esp_ip=esp_ip,
# #                                     transport=alarm_transport, token=alarm_http_token,
# #                                     mqtt_broker=mqtt_broker, mqtt_port=mqtt_port,
# #                                     mqtt_username=mqtt_username, mqtt_password=mqtt_password,
# #                                     mqtt_topic=mqtt_topic, mqtt_client_id=mqtt_client_id,
# #                                     mqtt_qos=mqtt_qos, mqtt_retain=mqtt_retain,
# #                                 )
# #                                 buzzer_fired = True

# #                             if burglar_test_sound:
# #                                 play_test_sound(cam_id)

# #                             if alert_queue is not None:
# #                                 _box = det_bbox
# #                                 alert_queue.put({
# #                                     "camera_id":           cam_id,
# #                                     "model_name":          "burglar_alarm",
# #                                     "violation_type":      "burglar_alarm",
# #                                     "confidence_score":    det["conf"],
# #                                     "snapshot_path":       snap_path,
# #                                     "buzzer_activated":    buzzer_fired,
# #                                     "zone_id":             burglar_alarm_config.get("monitored_zone_id"),
# #                                     "tracker_initialized": ba_tracking,
# #                                     "bbox_x1":     int(_box[0]),
# #                                     "bbox_y1":     int(_box[1]),
# #                                     "bbox_x2":     int(_box[2]),
# #                                     "bbox_y2":     int(_box[3]),
# #                                     "frame_width":  frame_w_px,
# #                                     "frame_height": frame_h_px,
# #                                 })
# #                                 ba_last_saved_bbox = list(_box)

# #                             print(
# #                                 f"[Camera {cam_id}] BURGLAR ALARM — intruder detected "
# #                                 f"in zone ({start_t}–{end_t}), KCF tracker started "
# #                                 f"(conf={det['conf']:.2f}, IoU={iou_with_last:.2f})"
# #                             )
# #                             break

# #         # ── draw detections ───────────────────────────────────────────────
# #         for det in filtered_detections:
# #             x1, y1, x2, y2 = map(int, det["box"])
# #             class_name = det["class"]
# #             display_name = _DISPLAY_NAMES.get(class_name, class_name)

# #             cls_key = str(class_name).strip().lower().replace("_", "-").replace(" ", "-")
# #             if any(k in cls_key for k in ("helmet", "hardhat", "-hat", "hat")):
# #                 if cls_key.startswith("no-") or "-no-" in cls_key or cls_key.startswith("without-"):
# #                     display_name = "NH"
# #                 else:
# #                     continue

# #             if any(k in cls_key for k in ("vest",)):
# #                 if cls_key.startswith("no-") or "-no-" in cls_key or cls_key.startswith("without-"):
# #                     display_name = "NV"
# #                 else:
# #                     continue

# #             if any(k in cls_key for k in ("goggle", "glasses", "goggle")):
# #                 if cls_key.startswith("no-") or "-no-" in cls_key or cls_key.startswith("without-"):
# #                     display_name = "NGL"
# #                 else:
# #                     continue

# #             if any(k in cls_key for k in ("glove",)):
# #                 if cls_key.startswith("no-") or "-no-" in cls_key or cls_key.startswith("without-"):
# #                     display_name = "NGO"
# #                 else:
# #                     continue

# #             if not display_name:
# #                 label = ""
# #             elif display_name.upper() in ("NH", "NV", "NGO", "NGL"):
# #                 label = display_name.upper()
# #             else:
# #                 label = f"{display_name.upper()} {det['conf']:.2f}"
# #             color = (0, 255, 0) if _is_safe_class(class_name) else (0, 0, 255)

# #             if label in ("NH", "NV", "NGO", "NGL"):
# #                 shrink_x = max(1, int((x2 - x1) * 0.12))
# #                 shrink_y = max(1, int((y2 - y1) * 0.12))
# #                 x1_draw = min(x2 - 1, x1 + shrink_x)
# #                 y1_draw = min(y2 - 1, y1 + shrink_y)
# #                 x2_draw = max(x1_draw + 1, x2 - shrink_x)
# #                 y2_draw = max(y1_draw + 1, y2 - shrink_y)
# #                 box_thickness = 1
# #                 label_scale = 0.35
# #                 label_thickness = 1
# #             else:
# #                 x1_draw, y1_draw, x2_draw, y2_draw = x1, y1, x2, y2
# #                 box_thickness = 2
# #                 label_scale = 0.6
# #                 label_thickness = 2

# #             cv2.rectangle(resized, (x1_draw, y1_draw), (x2_draw, y2_draw), color, box_thickness)
# #             if label:
# #                 cv2.putText(resized, label, (x1_draw, y1_draw - 10),
# #                             cv2.FONT_HERSHEY_SIMPLEX, label_scale, color, label_thickness)

# #         # ── hand / gloves overlay (MediaPipe) ─────────────────────────────
# #         if _run_gloves and _mp_hands is not None:
# #             rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
# #             mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
# #             hand_results = _mp_hands.detect(mp_image)
# #             if hand_results.hand_landmarks:
# #                 h, w = resized.shape[:2]
# #                 glove_candidates = [
# #                     d for d in gloves_detections
# #                     if any(k in _class_key(d.get("class")) for k in ("glove", "bare-hand", "bare-hands"))
# #                 ]
# #                 glove_top = max(glove_candidates, key=lambda d: d.get("conf", 0.0)) if glove_candidates else None
# #                 gloves_worn = glove_top is not None and _is_safe_class(glove_top.get("class"))
# #                 gloves_missing = not gloves_worn

# #                 if gloves_missing:
# #                     glove_violation_name = "no-gloves"
# #                     glove_violation_key = _class_key(glove_violation_name)
# #                     if glove_violation_key not in logged_this_frame:
# #                         record_violation({
# #                             "class": glove_violation_name,
# #                             "conf": glove_top.get("conf", 0.0) if glove_top is not None else 0.5,
# #                             "box": [0, 0, w, h],
# #                         }, glove_violation_name)
# #                         logged_this_frame.add(glove_violation_key)

# #                     g_color = (0, 0, 255)
# #                     for hand_lm in hand_results.hand_landmarks:
# #                         xs = [lm.x for lm in hand_lm]
# #                         ys = [lm.y for lm in hand_lm]
# #                         x1 = max(0, int(min(xs) * w) - 20)
# #                         y1 = max(0, int(min(ys) * h) - 20)
# #                         x2 = min(w, int(max(xs) * w) + 20)
# #                         y2 = min(h, int(max(ys) * h) + 20)
# #                         shrink_x = max(1, int((x2 - x1) * 0.12))
# #                         shrink_y = max(1, int((y2 - y1) * 0.12))
# #                         x1d = min(x2 - 1, x1 + shrink_x)
# #                         y1d = min(y2 - 1, y1 + shrink_y)
# #                         x2d = max(x1d + 1, x2 - shrink_x)
# #                         y2d = max(y1d + 1, y2 - shrink_y)
# #                         cv2.rectangle(resized, (x1d, y1d), (x2d, y2d), g_color, 1)
# #                         cv2.putText(resized, "NGO", (x1d, y1d - 10),
# #                                     cv2.FONT_HERSHEY_SIMPLEX, 0.35, g_color, 1)

# #         fps = 1 / (time.time() - start + 1e-5)
# #         stat_text = f"Cam {cam_id} | FPS: {fps:.1f} | Violations: {violations}"
# #         cv2.putText(resized, stat_text, (10, 30),
# #                     cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

# #         # ── encode JPEG for MJPEG stream ───────────────────────────────────
# #         _, jpeg = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 80])
# #         jpeg_bytes = jpeg.tobytes()
# #         with lock:
# #             frame_dict[cam_id] = jpeg_bytes

# #         set_stats(
# #             "running",
# #             round(fps, 1),
# #             violations,
# #             frame_count,
# #             extra={"frame_buffer_bytes": len(jpeg_bytes)},
# #         )

# #     # ── Cleanup ───────────────────────────────────────────────────────────
# #     if _mp_hands is not None:
# #         try:
# #             _mp_hands.close()
# #         except Exception:
# #             pass


# # def camera_loop(
# #     # ── required positional args ───────────────────────────────────────────
# #     cam_id: int,
# #     stream_url: str,
# #     model_path: str,                # path to YOLO .pt file — model is loaded inside the process
# #     threshold: float,
# #     helmet_class: str,
# #     no_helmet_class: str,
# #     cooldown: float,
# #     use_wifi: bool,                 # legacy fallback
# #     esp_ip: str | None,            # legacy fallback
# #     frame_dict: dict,               # {cam_id: jpeg_bytes} for MJPEG endpoint
# #     lock: threading.Lock,
# #     # ── optional keyword args ─────────────────────────────────────────────
# #     stop_event: threading.Event = None,
# #     stats_dict: dict = None,
# #     alarm_transport: str | None = None,
# #     alarm_http_token: str = "",
# #     mqtt_broker: str = "",
# #     mqtt_port: int = 1883,
# #     mqtt_username: str = "",
# #     mqtt_password: str = "",
# #     mqtt_topic: str = "skycctv/alarm",
# #     mqtt_client_id: str = "skycctv-ai",
# #     mqtt_qos: int = 1,
# #     mqtt_retain: bool = False,
# #     # ── new: DB-backed features ───────────────────────────────────────────
# #     assigned_buzzers: list = None,  # list of buzzer dicts fetched from DB at start
# #     alert_queue: Queue = None,      # queue to AlertWriter for non-blocking DB logging
# #     snapshot_dir: str = "snapshots",
# #     snapshot_cooldown: float = 120,
# #     detection_width: int = 960,
# #     detection_height: int = 720,
# #     yolo_imgsz: int = 960,
# #     enabled_models: list = None,    # list of model_name strings enabled for this camera
# #     violation_classes: list = None, # PPE classes that trigger an alarm
# #     safe_classes: list = None,      # PPE classes shown with green bounding box
# #     gloves_model_path: str | None = None,        # path to gloves model — loaded inside the process
# #     burglar_person_model_path: str | None = None,  # path to burglar person model — loaded inside
# #     burglar_alarm_config: dict = None,  # pre-fetched burglar alarm config dict (or None)
# #     burglar_test_sound: bool = False,
# #     ingestion_fps: float = 4.0,
# #     inference_fps: float = 4.0,
# # ):
# #     """
# #     Per-camera ingestion loop (FFmpeg/webcam only).

# #     Opens the stream, maintains frame_buffer for inference_worker, and
# #     handles reconnections.  All YOLO inference, violation detection,
# #     burglar alarm, and MJPEG encoding are handled by inference_worker
# #     running in a dedicated daemon thread started here.

# #     Function signature and all external behaviour are unchanged.
# #     """

# #     # Patch start_ffmpeg to use the configured ingestion FPS for this camera
# #     start_ffmpeg.ingestion_fps = ingestion_fps

# #     # ── Load models inside this process (no pickle, full CPU/GPU isolation) ──
# #     model = load_model(model_path)
# #     gloves_model = load_model(gloves_model_path) if gloves_model_path else None
# #     burglar_person_model = (
# #         load_model(burglar_person_model_path) if burglar_person_model_path else None
# #     )

# #     # ── Shared frame buffer: ingestion writes, inference_worker reads ─────
# #     frame_buffer: dict = {
# #         "frame": None,          # latest BGR numpy array
# #         "ts":    0.0,           # wall-clock time the frame was stored
# #         "lock":  threading.Lock(),
# #     }

# #     thread_native_id = threading.get_native_id()

# #     def set_stats(
# #         status: str,
# #         fps: float = 0,
# #         violations: int = 0,
# #         frames: int = 0,
# #         extra: dict | None = None,
# #     ):
# #         if stats_dict is not None:
# #             with lock:
# #                 stats = dict(stats_dict.get(cam_id, {}))
# #                 stats.update({
# #                     "status": status, "fps": fps,
# #                     "violations": violations, "frames": frames,
# #                     "thread_native_id": thread_native_id,
# #                 })
# #                 if extra:
# #                     stats.update(extra)
# #                 stats_dict[cam_id] = stats

# #     # OLD OpenCV ingestion (commented out — replaced by FFmpeg subprocess):
# #     # source = int(stream_url) if isinstance(stream_url, str) and stream_url.isdigit() else stream_url
# #     # cap = cv2.VideoCapture(source)
# #     # if not cap.isOpened():
# #     #     print(f"[Camera {cam_id}] Failed to open stream: {stream_url}")
# #     #     set_stats("error")
# #     #     return

# #     _ff_width   = max(320, int(detection_width or 960))
# #     _ff_height  = max(240, int(detection_height or 720))
# #     _frame_size = _ff_width * _ff_height * 3   # bytes per raw BGR24 frame

# #     _is_webcam = isinstance(stream_url, int) or (
# #         isinstance(stream_url, str) and stream_url.isdigit()
# #     )

# #     ffmpeg_proc: subprocess.Popen | None = None
# #     _legacy_cap = None

# #     def _ffmpeg_reader(proc: subprocess.Popen):
# #         """Background thread: reads raw BGR24 frames from FFmpeg stdout → frame_buffer."""
# #         while True:
# #             try:
# #                 raw = proc.stdout.read(_frame_size)
# #             except Exception:
# #                 break
# #             if not raw or len(raw) != _frame_size:
# #                 break
# #             frame_arr = np.frombuffer(raw, dtype=np.uint8).reshape(
# #                 (_ff_height, _ff_width, 3)
# #             )
# #             with frame_buffer["lock"]:
# #                 frame_buffer["frame"] = frame_arr.copy()
# #                 frame_buffer["ts"]    = time.time()

# #     def _start_reader():
# #         """(Re-)launch FFmpeg subprocess and its reader thread."""
# #         nonlocal ffmpeg_proc
# #         if ffmpeg_proc is not None:
# #             try:
# #                 ffmpeg_proc.terminate()
# #                 ffmpeg_proc.wait(timeout=3)
# #             except subprocess.TimeoutExpired:
# #                 ffmpeg_proc.kill()
# #                 ffmpeg_proc.wait()
# #             except Exception:
# #                 pass
# #         ffmpeg_proc = start_ffmpeg(stream_url, _ff_width, _ff_height)
# #         if ffmpeg_proc is None:
# #             return
# #         t = threading.Thread(
# #             target=_ffmpeg_reader, args=(ffmpeg_proc,), daemon=True
# #         )
# #         t.start()

# #     reconnect_attempts     = 0
# #     max_reconnect_attempts = 10

# #     set_stats("connecting", 0, 0, 0)

# #     if _is_webcam:
# #         _legacy_cap = cv2.VideoCapture(
# #             int(stream_url) if isinstance(stream_url, str) else stream_url
# #         )
# #         if not _legacy_cap.isOpened():
# #             print(f"[Camera {cam_id}] Failed to open webcam: {stream_url}")
# #             set_stats("error")
# #             return
# #     else:
# #         _start_reader()
# #         time.sleep(1.5)   # give FFmpeg a moment before first frame check

# #     # ── Start inference_worker in a dedicated thread ───────────────────────
# #     _iw_thread = threading.Thread(
# #         target=inference_worker,
# #         kwargs=dict(
# #             cam_id=cam_id,
# #             frame_buffer=frame_buffer,
# #             model=model,
# #             threshold=threshold,
# #             helmet_class=helmet_class,
# #             no_helmet_class=no_helmet_class,
# #             cooldown=cooldown,
# #             use_wifi=use_wifi,
# #             esp_ip=esp_ip,
# #             frame_dict=frame_dict,
# #             lock=lock,
# #             stop_event=stop_event,
# #             stats_dict=stats_dict,
# #             alarm_transport=alarm_transport,
# #             alarm_http_token=alarm_http_token,
# #             mqtt_broker=mqtt_broker,
# #             mqtt_port=mqtt_port,
# #             mqtt_username=mqtt_username,
# #             mqtt_password=mqtt_password,
# #             mqtt_topic=mqtt_topic,
# #             mqtt_client_id=mqtt_client_id,
# #             mqtt_qos=mqtt_qos,
# #             mqtt_retain=mqtt_retain,
# #             assigned_buzzers=assigned_buzzers,
# #             alert_queue=alert_queue,
# #             snapshot_dir=snapshot_dir,
# #             snapshot_cooldown=snapshot_cooldown,
# #             detection_width=detection_width,
# #             detection_height=detection_height,
# #             yolo_imgsz=yolo_imgsz,
# #             enabled_models=enabled_models,
# #             violation_classes=violation_classes,
# #             safe_classes=safe_classes,
# #             gloves_model=gloves_model,         # already-loaded model object (local to this process)
# #             burglar_person_model=burglar_person_model,
# #             burglar_alarm_config=burglar_alarm_config,
# #             burglar_test_sound=burglar_test_sound,
# #             inference_fps=inference_fps,
# #         ),
# #         daemon=True,
# #     )
# #     _iw_thread.start()

# #     # ── Ingestion loop: feed frames into frame_buffer, manage reconnects ───
# #     while True:
# #         if stop_event is not None and stop_event.is_set():
# #             break

# #         if _is_webcam:
# #             # Legacy OpenCV read for local webcam devices
# #             ret, frame = _legacy_cap.read()
# #             if not ret:
# #                 reconnect_attempts += 1
# #                 print(
# #                     f"[Camera {cam_id}] Webcam read failed "
# #                     f"(attempt {reconnect_attempts}/{max_reconnect_attempts})"
# #                 )
# #                 set_stats("reconnecting", 0, 0, 0)
# #                 for _ in range(7):
# #                     if stop_event is not None and stop_event.is_set():
# #                         break
# #                     time.sleep(0.1)
# #                 if stop_event is not None and stop_event.is_set():
# #                     break
# #                 if reconnect_attempts >= max_reconnect_attempts:
# #                     print(f"[Camera {cam_id}] Webcam unavailable after retries")
# #                     set_stats("error", 0, 0, 0)
# #                     break
# #                 continue
# #             # Write fresh webcam frame into buffer
# #             with frame_buffer["lock"]:
# #                 frame_buffer["frame"] = frame.copy()
# #                 frame_buffer["ts"]    = time.time()
# #         else:
# #             # FFmpeg path: _ffmpeg_reader populates frame_buffer automatically.
# #             # This loop only monitors for stalls and triggers restarts.
# #             with frame_buffer["lock"]:
# #                 _age = time.time() - frame_buffer["ts"] if frame_buffer["ts"] > 0 else 99.0

# #             if _age > 5.0:
# #                 reconnect_attempts += 1
# #                 print(
# #                     f"[Camera {cam_id}] FFmpeg stall detected "
# #                     f"(age={_age:.1f}s, attempt {reconnect_attempts}/{max_reconnect_attempts})"
# #                 )
# #                 set_stats("reconnecting", 0, 0, 0)
# #                 _start_reader()
# #                 for _ in range(15):
# #                     if stop_event is not None and stop_event.is_set():
# #                         break
# #                     time.sleep(0.1)
# #                 if stop_event is not None and stop_event.is_set():
# #                     break
# #                 if reconnect_attempts >= max_reconnect_attempts:
# #                     print(f"[Camera {cam_id}] Stream unavailable after retries")
# #                     set_stats("error", 0, 0, 0)
# #                     break
# #                 continue

# #         reconnect_attempts = 0
# #         # Yield CPU to inference_worker and other threads
# #         time.sleep(0.01)

# #     # ── Cleanup ────────────────────────────────────────────────────────────
# #     if _is_webcam and _legacy_cap is not None:
# #         try:
# #             _legacy_cap.release()
# #         except Exception:
# #             pass
# #     elif ffmpeg_proc is not None:
# #         try:
# #             ffmpeg_proc.terminate()
# #             ffmpeg_proc.wait(timeout=5)
# #         except subprocess.TimeoutExpired:
# #             ffmpeg_proc.kill()
# #             ffmpeg_proc.wait()
# #         except Exception:
# #             pass
# #     # inference_worker is daemon=True; it exits when this thread exits.
# #     _iw_thread.join(timeout=5)
# #     set_stats("stopped", 0, 0, 0, extra={"frame_buffer_bytes": 0})


# # ═════════════════════════════════════════════════════════════════════════════
# # NEW SHARED-INFERENCE ARCHITECTURE
# # ─────────────────────────────────────────────────────────────────────────────
# # ingestion_worker   — one lightweight mp.Process per camera
# #                      reads FFmpeg/webcam frames, pushes to shared frame_queue
# # result_handler_worker — one threading.Thread per camera (in main process)
# #                         reads (cam_id, frame, ts, detections, gloves_dets,
# #                         burglar_dets) from its result_queue and handles all
# #                         alarm logic, MJPEG encoding and stats updates
# #
# # The inference server (inference_server.py) sits between them:
# #   frame_queue ──► InferenceServer (1 process, 1 model, batch GPU predict)
# #                            └──► per-camera result_queues ──► result_handler_worker
# # ═════════════════════════════════════════════════════════════════════════════

# import multiprocessing as _mp   # keep local alias to avoid clash at module level


# def ingestion_worker(
#     cam_id: int,
#     stream_url,
#     frame_queue,          # mp.Queue shared with inference_server_loop
#     stop_event,           # mp.Event
#     stats_dict: dict,
#     lock,
#     detection_width: int = 960,
#     detection_height: int = 720,
#     ingestion_fps: float = 4.0,
# ):
#     """
#     Lightweight per-camera ingestion process.

#     Reads BGR frames from FFmpeg (RTSP) or OpenCV (webcam), resizes them to
#     (detection_width × detection_height), rate-limits to ingestion_fps, and
#     pushes (cam_id, frame, timestamp) to the shared frame_queue for the
#     inference server to process.

#     No model loading, no inference — just frame delivery.
#     """
#     import cv2 as _cv2
#     import numpy as _np

#     _ff_width   = max(320, int(detection_width  or 960))
#     _ff_height  = max(240, int(detection_height or 720))
#     _frame_size = _ff_width * _ff_height * 3
#     _interval   = 1.0 / max(1.0, float(ingestion_fps))

#     _is_webcam = isinstance(stream_url, int) or (
#         isinstance(stream_url, str) and str(stream_url).isdigit()
#     )

#     ffmpeg_proc_ing = None
#     _buf: dict = {"frame": None, "ts": 0.0, "lock": threading.Lock()}

#     def _ffmpeg_reader_ing(proc):
#         while True:
#             try:
#                 raw = proc.stdout.read(_frame_size)
#             except Exception:
#                 break
#             if not raw or len(raw) != _frame_size:
#                 break
#             arr = _np.frombuffer(raw, dtype=_np.uint8).reshape(
#                 (_ff_height, _ff_width, 3)
#             )
#             with _buf["lock"]:
#                 _buf["frame"] = arr.copy()
#                 _buf["ts"]    = time.time()

#     def _ffmpeg_stderr_logger(proc):
#         """Print FFmpeg stderr lines so connection errors appear in server logs."""
#         try:
#             for line in proc.stderr:
#                 msg = line.decode(errors="replace").rstrip()
#                 if msg:
#                     print(f"[FFmpeg cam{cam_id}] {msg}", flush=True)
#         except Exception:
#             pass

#     def _start_ffmpeg_ing():
#         nonlocal ffmpeg_proc_ing
#         if ffmpeg_proc_ing is not None:
#             try:
#                 ffmpeg_proc_ing.terminate()
#                 ffmpeg_proc_ing.wait(timeout=3)
#             except Exception:
#                 pass
#         ffmpeg_proc_ing = start_ffmpeg(stream_url, _ff_width, _ff_height)
#         if ffmpeg_proc_ing:
#             threading.Thread(
#                 target=_ffmpeg_reader_ing,
#                 args=(ffmpeg_proc_ing,),
#                 daemon=True,
#             ).start()
#             threading.Thread(
#                 target=_ffmpeg_stderr_logger,
#                 args=(ffmpeg_proc_ing,),
#                 daemon=True,
#             ).start()

#     legacy_cap = None
#     if _is_webcam:
#         legacy_cap = _cv2.VideoCapture(
#             int(stream_url) if isinstance(stream_url, str) else stream_url
#         )
#         if not legacy_cap.isOpened():
#             print(f"[Ingestion {cam_id}] Failed to open webcam: {stream_url}")
#             if stats_dict is not None:
#                 with lock:
#                     stats_dict[cam_id] = {"status": "error", "fps": 0,
#                                           "violations": 0, "frames": 0}
#             return
#     else:
#         _start_ffmpeg_ing()
#         time.sleep(1.5)

#     reconnect_attempts = 0
#     max_reconnect      = 10
#     _last_push         = 0.0

#     if stats_dict is not None:
#         with lock:
#             stats_dict[cam_id] = {"status": "ingesting", "fps": 0,
#                                    "violations": 0, "frames": 0}

#     while True:
#         if stop_event is not None and stop_event.is_set():
#             break

#         if _is_webcam:
#             # Sleep BEFORE reading so cap.read() is only called at ingestion_fps,
#             # not at the webcam's native ~30 FPS. Avoids 7-8 wasted reads per push.
#             sleep_time = _interval - (time.time() - _last_push)
#             if sleep_time > 0.01:
#                 time.sleep(sleep_time - 0.005)  # wake slightly early to hit target

#             ret, frame = legacy_cap.read()
#             if not ret:
#                 reconnect_attempts += 1
#                 time.sleep(0.5)
#                 if reconnect_attempts >= max_reconnect:
#                     break
#                 continue
#             resized = _cv2.resize(frame, (_ff_width, _ff_height))
#         else:
#             with _buf["lock"]:
#                 buf_ts = _buf["ts"]
#                 frame  = _buf["frame"]

#             # No frame yet — FFmpeg is still connecting; wait without counting as a stall
#             if buf_ts == 0:
#                 time.sleep(0.1)
#                 continue

#             age = time.time() - buf_ts
#             if age > 12.0:
#                 reconnect_attempts += 1
#                 print(f"[Ingestion {cam_id}] FFmpeg stall (age={age:.1f}s) — reconnect {reconnect_attempts}/{max_reconnect}", flush=True)
#                 _start_ffmpeg_ing()
#                 time.sleep(2.0)
#                 if reconnect_attempts >= max_reconnect:
#                     print(f"[Ingestion {cam_id}] Giving up after {max_reconnect} reconnects — check FFmpeg/RTSP above", flush=True)
#                     break
#                 continue

#             if frame is None:
#                 time.sleep(0.02)
#                 continue

#             resized = frame

#             # RTSP path: honour rate limit
#             now = time.time()
#             if now - _last_push < _interval:
#                 time.sleep(0.005)
#                 continue

#         reconnect_attempts = 0
#         _last_push = time.time()

#         try:
#             frame_queue.put_nowait((cam_id, resized, _last_push))
#         except Exception:
#             pass   # queue full — drop frame (backpressure)

#     # ── Cleanup ────────────────────────────────────────────────────────────
#     if legacy_cap is not None:
#         legacy_cap.release()
#     elif ffmpeg_proc_ing is not None:
#         try:
#             ffmpeg_proc_ing.terminate()
#             ffmpeg_proc_ing.wait(timeout=5)
#         except subprocess.TimeoutExpired:
#             ffmpeg_proc_ing.kill()
#             ffmpeg_proc_ing.wait()
#         except Exception:
#             pass


# def result_handler_worker(
#     cam_id: int,
#     result_queue,                   # mp.Queue from inference_server_loop
#     frame_dict: dict,               # shared {cam_id: jpeg_bytes}
#     lock,                           # shared lock
#     threshold: float,
#     helmet_class: str,
#     no_helmet_class: str,
#     cooldown: float,
#     stop_event: threading.Event = None,
#     stats_dict: dict = None,
#     assigned_buzzers: list = None,
#     alert_queue: Queue = None,
#     snapshot_dir: str = "snapshots",
#     snapshot_cooldown: float = 120,
#     detection_width: int = 960,
#     detection_height: int = 720,
#     yolo_imgsz: int = 960,
#     enabled_models: list = None,
#     violation_classes: list = None,
#     safe_classes: list = None,
#     burglar_alarm_config: dict = None,
#     burglar_test_sound: bool = False,
# ):
#     """
#     Per-camera result handler thread (runs in main process).

#     Reads (cam_id, frame_bgr, ts, detections, gloves_dets, burglar_dets) from
#     result_queue and handles:
#       • ROI filtering
#       • Violation detection & alarm triggering
#       • Burglar alarm KCF tracking
#       • MediaPipe gloves overlay
#       • MJPEG encoding → frame_dict
#       • Stats updates

#     No YOLO inference here — detections arrive pre-computed from the shared
#     inference server process.

#     gloves_dets == None  → treat as equal to main detections (same model)
#     burglar_dets == None → treat as equal to main detections (same model)
#     """
#     from queue import Empty as _Empty

#     thread_native_id = threading.get_native_id()

#     def set_stats(status, fps=0, violations=0, frames=0, extra=None):
#         if stats_dict is not None:
#             with lock:
#                 s = dict(stats_dict.get(cam_id, {}))
#                 s.update({"status": status, "fps": fps,
#                            "violations": violations, "frames": frames,
#                            "thread_native_id": thread_native_id})
#                 if extra:
#                     s.update(extra)
#                 stats_dict[cam_id] = s

#     def _class_key(class_name):
#         return str(class_name or "").strip().lower().replace("_", "-").replace(" ", "-")

#     _violation_set = set(violation_classes) if violation_classes else (
#         {no_helmet_class} if no_helmet_class else set()
#     )
#     _safe_set = set(safe_classes) if safe_classes else (
#         {helmet_class} if helmet_class else set()
#     )
#     _violation_keys = {_class_key(c) for c in _violation_set}
#     _violation_keys.update({
#         "no-hardhat", "no-hat", "no-helmet",
#         "no-boot", "no-boots", "no-shoe", "no-shoes",
#         "no-gloves", "bare-hand", "bare-hands",
#         "no-safety-vest", "no-vest", "no-goggles", "no-glasses",
#         "fire",
#     })
#     _safe_keys = {_class_key(c) for c in _safe_set}
#     _safe_keys.update({
#         "hardhat", "hat", "helmet",
#         "boot", "boots", "shoe", "shoes",
#         "gloves", "safety-vest", "vest", "goggles", "glasses",
#     })
#     _disabled_class_keys = {"mask", "no-mask"}

#     def _is_violation_class(c):  return _class_key(c) in _violation_keys
#     def _is_safe_class(c):       return _class_key(c) in _safe_keys

#     _enabled_set = set(enabled_models) if enabled_models is not None else None

#     _DISPLAY_NAMES = {
#         "NO-Hardhat": "NH", "NO-Hat": "NH", "Hardhat": "", "Hat": "",
#         "no_helmet": "NH", "helmet": "",
#         "NO-Safety Vest": "NV", "Safety Vest": "", "no_vest": "NV", "vest": "",
#         "NO-Goggles": "NGL", "Goggles": "",
#         "Gloves": "", "NO-Gloves": "NGO", "no-gloves": "NGO",
#         "bare_hand": "NGO", "bare_hands": "NGO",
#     }
#     _CLASS_TO_MODEL = {
#         "no_helmet": "helmet_detection", "helmet": "helmet_detection",
#         "no-hardhat": "helmet_detection", "no_hardhat": "helmet_detection",
#         "hardhat": "helmet_detection", "no-hat": "helmet_detection",
#         "no_hat": "helmet_detection", "hat": "helmet_detection",
#         "no_vest": "vest_detection", "vest": "vest_detection",
#         "no-safety vest": "vest_detection", "no_safety_vest": "vest_detection",
#         "safety vest": "vest_detection", "safety_vest": "vest_detection",
#         "no_glasses": "glasses_detection", "glasses": "glasses_detection",
#         "no-goggles": "glasses_detection", "no_goggles": "glasses_detection",
#         "goggles": "glasses_detection",
#         "no-gloves": "gloves_detection", "no_gloves": "gloves_detection",
#         "gloves": "gloves_detection", "bare-hand": "gloves_detection",
#         "bare_hand": "gloves_detection", "bare_hands": "gloves_detection",
#         "fire": "fire_detection",
#     }

#     def _model_for_class(c):
#         if not c:
#             return None
#         k = c.strip().lower()
#         if k in _CLASS_TO_MODEL:
#             return _CLASS_TO_MODEL[k]
#         return _CLASS_TO_MODEL.get(k.replace("-", "_").replace(" ", "_"))

#     # MediaPipe hand landmarker (CPU — stays in handler thread)
#     _run_gloves_mp = _enabled_set is None or "gloves_detection" in _enabled_set
#     _mp_hands = None
#     if _run_gloves_mp:
#         try:
#             _opts = _mp_vision.HandLandmarkerOptions(
#                 base_options=_MpBaseOptions(model_asset_path=_HAND_LANDMARKER_PATH),
#                 num_hands=4,
#                 min_hand_detection_confidence=0.5,
#             )
#             _mp_hands = _mp_vision.HandLandmarker.create_from_options(_opts)
#         except Exception as e:
#             print(f"[ResultHandler {cam_id}] MediaPipe init failed: {e}")
#             _mp_hands = None

#     RESIZE_DIM = (max(320, int(detection_width or 960)),
#                   max(240, int(detection_height or 720)))

#     # ── State ──────────────────────────────────────────────────────────────
#     frame_count = 0
#     violations  = 0
#     last_alarm_times: dict = {}
#     last_snapshot_times: dict = {}
#     last_burglar_alarm_time = 0.0
#     _last_stats_ts = 0.0

#     ba_tracker           = None
#     ba_tracking          = False
#     ba_track_fail_count  = 0
#     BA_MAX_FAILS         = 5
#     BA_REDETECT_INTERVAL = 30
#     ba_frames_since_check = 0
#     ba_tracked_conf      = 0.0
#     ba_last_saved_bbox   = None
#     BA_IoU_THRESHOLD     = 0.3

#     set_stats("running", 0, 0, 0)

#     while True:
#         if stop_event is not None and stop_event.is_set():
#             break

#         # ── Read next result from inference server ─────────────────────────
#         try:
#             item = result_queue.get(timeout=0.1)
#         except _Empty:
#             continue

#         if item is None:   # stop sentinel
#             break

#         # Unpack — extra_dets is a dict {model_name: [detections] | None}
#         # None means "same as main" (inference server reused main model for that key)
#         _cam_id_in, frame_payload, ts, detections, extra_dets = item

#         # Decode JPEG bytes sent by inference server (reduces IPC data 18x).
#         if isinstance(frame_payload, (bytes, bytearray)) and frame_payload:
#             _dec = cv2.imdecode(np.frombuffer(frame_payload, np.uint8), cv2.IMREAD_COLOR)
#             resized = _dec if _dec is not None else np.zeros(
#                 (RESIZE_DIM[1], RESIZE_DIM[0], 3), dtype=np.uint8
#             )
#         else:
#             resized = frame_payload  # raw numpy fallback (legacy path)

#         # Resolve None sentinels (same-model shortcut from inference server)
#         gloves_dets = extra_dets.get("gloves")
#         burglar_dets = extra_dets.get("burglar")
#         gloves_detections = detections if gloves_dets is None else gloves_dets
#         burglar_candidates_raw = detections if burglar_dets is None else burglar_dets
#         # Resolve any remaining None sentinels in extra_dets
#         extra_dets = {
#             k: (detections if v is None else v)
#             for k, v in extra_dets.items()
#         }

#         frame_count += 1
#         start = time.time()

#         # ── Filter: disabled classes + enabled_models ──────────────────────
#         filtered_detections = []
#         all_detections = (
#             detections
#             if gloves_detections is detections
#             else detections + gloves_detections
#         )
#         for det in all_detections:
#             if _class_key(det.get("class")) in _disabled_class_keys:
#                 continue
#             model_name = _model_for_class(det["class"])
#             if _enabled_set is not None and model_name and model_name not in _enabled_set:
#                 continue
#             filtered_detections.append(det)

#         # ── ROI filtering ──────────────────────────────────────────────────
#         _rois = _get_rois_for_camera(str(cam_id))
#         if _rois:
#             for _d in filtered_detections:
#                 _d["x1"], _d["y1"], _d["x2"], _d["y2"] = _d["box"]
#             frame_h_px, frame_w_px = resized.shape[:2]
#             filtered_detections, _ = filter_detections(
#                 filtered_detections, str(cam_id), frame_w_px, frame_h_px, rois=_rois
#             )

#         # ── Violation recording helper ─────────────────────────────────────
#         def record_violation(det, violation_type=None):
#             nonlocal violations
#             violation_name = violation_type or det.get("class", "violation")
#             violation_key  = _class_key(violation_name)
#             now = time.time()
#             effective_cooldown = max(0.0, float(cooldown or 0))
#             if now - last_alarm_times.get(violation_key, 0) <= effective_cooldown:
#                 return False
#             last_alarm_times[violation_key] = now
#             violations += 1

#             snap_path = None
#             if now - last_snapshot_times.get(violation_key, 0) > max(0.0, float(snapshot_cooldown or 0)):
#                 snap_path = save_snapshot(resized, cam_id, snapshot_dir)
#                 last_snapshot_times[violation_key] = now

#             buzzer_fired = False
#             if assigned_buzzers:
#                 buzzer_fired = fire_buzzers(assigned_buzzers, cam_id)
#             else:
#                 print(f"[Camera {cam_id}] No buzzers configured for violation '{violation_name}'")

#             if alert_queue is not None:
#                 alert_queue.put({
#                     "camera_id":        cam_id,
#                     "model_name":       "ppe_detection",
#                     "violation_type":   violation_name,
#                     "confidence_score": det.get("conf", 0.0),
#                     "snapshot_path":    snap_path,
#                     "buzzer_activated": buzzer_fired,
#                 })
#             log_violation_file(cam_id, frame_count, (violations / frame_count) * 100, violation_name)
#             return True

#         logged_this_frame: set = set()
#         for det in filtered_detections:
#             vk = _class_key(det.get("class"))
#             if _is_violation_class(det.get("class")) and vk not in logged_this_frame:
#                 if record_violation(det):
#                     logged_this_frame.add(vk)

#         # ── Burglar alarm (KCF tracking) ───────────────────────────────────
#         if burglar_alarm_config and burglar_alarm_config.get("alarm_enabled"):
#             ba_cooldown  = float(burglar_alarm_config.get("cooldown_sec", 30))
#             start_t      = burglar_alarm_config.get("alarm_start_time", "20:00")
#             end_t        = burglar_alarm_config.get("alarm_end_time",   "06:00")
#             window_active = is_in_alarm_window(start_t, end_t)

#             if not window_active and ba_tracking:
#                 ba_tracker = None; ba_tracking = False
#                 ba_track_fail_count = 0; ba_frames_since_check = 0; ba_last_saved_bbox = None
#                 print(f"[Camera {cam_id}] KCF tracker reset — alarm window closed")

#             if window_active:
#                 frame_h_px, frame_w_px = resized.shape[:2]
#                 zone_pts = burglar_alarm_config.get("monitored_zone_points")

#                 def _is_burglar_person(c):
#                     return c and c.strip().lower() in {"person", "persona", "human"}

#                 def _compute_iou(box1, box2):
#                     if box1 is None or box2 is None: return 0.0
#                     x1_1, y1_1, x2_1, y2_1 = box1
#                     x1_2, y1_2, x2_2, y2_2 = box2
#                     xi1, yi1 = max(x1_1, x1_2), max(y1_1, y1_2)
#                     xi2, yi2 = min(x2_1, x2_2), min(y2_1, y2_2)
#                     if xi2 < xi1 or yi2 < yi1: inter_area = 0.0
#                     else: inter_area = (xi2 - xi1) * (yi2 - yi1)
#                     area1 = (x2_1 - x1_1) * (y2_1 - y1_1)
#                     area2 = (x2_2 - x1_2) * (y2_2 - y1_2)
#                     union_area = area1 + area2 - inter_area
#                     return inter_area / union_area if union_area > 0 else 0.0

#                 if ba_tracking and ba_tracker is not None:
#                     kcf_ok, kcf_rect = ba_tracker.update(resized)
#                     if not kcf_ok:
#                         ba_track_fail_count += 1
#                         if ba_track_fail_count >= BA_MAX_FAILS:
#                             ba_tracker = None; ba_tracking = False
#                             ba_track_fail_count = 0; ba_frames_since_check = 0; ba_last_saved_bbox = None
#                             print(f"[Camera {cam_id}] KCF lost intruder — IDLE")
#                     else:
#                         ba_track_fail_count = 0
#                         kx, ky, kw, kh = [int(v) for v in kcf_rect]
#                         kx2, ky2 = kx + kw, ky + kh
#                         ba_frames_since_check += 1
#                         if ba_frames_since_check >= BA_REDETECT_INTERVAL:
#                             ba_frames_since_check = 0
#                             still_in = (zone_pts is None or
#                                         is_person_in_zone({"box": [kx, ky, kx2, ky2]},
#                                                           zone_pts, frame_w_px, frame_h_px))
#                             if not still_in:
#                                 ba_tracker = None; ba_tracking = False
#                                 ba_track_fail_count = 0; ba_last_saved_bbox = None
#                                 print(f"[Camera {cam_id}] KCF — intruder left zone, IDLE")
#                         if ba_tracking:
#                             import cv2 as _cv2b
#                             _cv2b.rectangle(resized, (kx, ky), (kx2, ky2), (0, 165, 255), 2)
#                             _cv2b.putText(resized, f"INTRUDER TRACKING {ba_tracked_conf:.2f}",
#                                           (kx, ky - 10), _cv2b.FONT_HERSHEY_SIMPLEX, 0.6,
#                                           (0, 165, 255), 2)
#                 else:
#                     if (time.time() - last_burglar_alarm_time) > ba_cooldown:
#                         for det in burglar_candidates_raw:
#                             if not _is_burglar_person(det.get("class")):
#                                 continue
#                             in_zone = (zone_pts is None or
#                                        is_person_in_zone(det, zone_pts, frame_w_px, frame_h_px))
#                             if not in_zone:
#                                 continue
#                             det_bbox = det["box"]
#                             if _compute_iou(det_bbox, ba_last_saved_bbox) > BA_IoU_THRESHOLD:
#                                 continue
#                             new_tracker = init_kcf_tracker(resized, det_bbox)
#                             if new_tracker is not None:
#                                 ba_tracker = new_tracker; ba_tracking = True
#                                 ba_track_fail_count = 0; ba_frames_since_check = 0
#                                 ba_tracked_conf = det["conf"]
#                             last_burglar_alarm_time = time.time()
#                             snap_path    = save_snapshot(resized, cam_id, snapshot_dir)
#                             buzzer_fired = fire_buzzers(assigned_buzzers, cam_id) if assigned_buzzers else False
#                             if burglar_test_sound:
#                                 play_test_sound(cam_id)
#                             if alert_queue is not None:
#                                 _box = det_bbox
#                                 alert_queue.put({
#                                     "camera_id": cam_id, "model_name": "burglar_alarm",
#                                     "violation_type": "burglar_alarm",
#                                     "confidence_score": det["conf"], "snapshot_path": snap_path,
#                                     "buzzer_activated": buzzer_fired,
#                                     "zone_id": burglar_alarm_config.get("monitored_zone_id"),
#                                     "tracker_initialized": ba_tracking,
#                                     "bbox_x1": int(_box[0]), "bbox_y1": int(_box[1]),
#                                     "bbox_x2": int(_box[2]), "bbox_y2": int(_box[3]),
#                                     "frame_width": frame_w_px, "frame_height": frame_h_px,
#                                 })
#                                 ba_last_saved_bbox = list(_box)
#                             print(f"[Camera {cam_id}] BURGLAR ALARM — intruder detected "
#                                   f"({start_t}–{end_t}), KCF started (conf={det['conf']:.2f})")
#                             break

#         # ── Draw detections ────────────────────────────────────────────────
#         for det in filtered_detections:
#             x1, y1, x2, y2 = map(int, det["box"])
#             class_name   = det["class"]
#             display_name = _DISPLAY_NAMES.get(class_name, class_name)
#             cls_key = str(class_name).strip().lower().replace("_", "-").replace(" ", "-")

#             if any(k in cls_key for k in ("helmet", "hardhat", "-hat", "hat")):
#                 display_name = "NH" if (cls_key.startswith("no-") or "-no-" in cls_key
#                                         or cls_key.startswith("without-")) else ""
#                 if not display_name: continue
#             if any(k in cls_key for k in ("vest",)):
#                 display_name = "NV" if (cls_key.startswith("no-") or "-no-" in cls_key
#                                         or cls_key.startswith("without-")) else ""
#                 if not display_name: continue
#             if any(k in cls_key for k in ("goggle", "glasses")):
#                 display_name = "NGL" if (cls_key.startswith("no-") or "-no-" in cls_key
#                                          or cls_key.startswith("without-")) else ""
#                 if not display_name: continue
#             if any(k in cls_key for k in ("glove",)):
#                 display_name = "NGO" if (cls_key.startswith("no-") or "-no-" in cls_key
#                                          or cls_key.startswith("without-")) else ""
#                 if not display_name: continue

#             if not display_name:
#                 label = ""
#             elif display_name.upper() in ("NH", "NV", "NGO", "NGL"):
#                 label = display_name.upper()
#             else:
#                 label = f"{display_name.upper()} {det['conf']:.2f}"
#             color = (0, 255, 0) if _is_safe_class(class_name) else (0, 0, 255)

#             if label in ("NH", "NV", "NGO", "NGL"):
#                 shrink_x = max(1, int((x2 - x1) * 0.12))
#                 shrink_y = max(1, int((y2 - y1) * 0.12))
#                 x1d = min(x2 - 1, x1 + shrink_x); y1d = min(y2 - 1, y1 + shrink_y)
#                 x2d = max(x1d + 1, x2 - shrink_x); y2d = max(y1d + 1, y2 - shrink_y)
#                 bt, ls, lt = 1, 0.35, 1
#             else:
#                 x1d, y1d, x2d, y2d = x1, y1, x2, y2
#                 bt, ls, lt = 2, 0.6, 2
#             cv2.rectangle(resized, (x1d, y1d), (x2d, y2d), color, bt)
#             if label:
#                 cv2.putText(resized, label, (x1d, y1d - 10),
#                             cv2.FONT_HERSHEY_SIMPLEX, ls, color, lt)

#         # ── MediaPipe gloves overlay (CPU) ─────────────────────────────────
#         if _run_gloves_mp and _mp_hands is not None:
#             rgb = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
#             mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
#             hand_results = _mp_hands.detect(mp_image)
#             if hand_results.hand_landmarks:
#                 h, w = resized.shape[:2]
#                 glove_candidates = [
#                     d for d in gloves_detections
#                     if any(k in _class_key(d.get("class"))
#                            for k in ("glove", "bare-hand", "bare-hands"))
#                 ]
#                 glove_top   = max(glove_candidates, key=lambda d: d.get("conf", 0.0)) if glove_candidates else None
#                 gloves_worn = glove_top is not None and _is_safe_class(glove_top.get("class"))
#                 if not gloves_worn:
#                     gvk = _class_key("no-gloves")
#                     if gvk not in logged_this_frame:
#                         record_violation({"class": "no-gloves",
#                                           "conf": glove_top.get("conf", 0.0) if glove_top else 0.5,
#                                           "box": [0, 0, w, h]}, "no-gloves")
#                         logged_this_frame.add(gvk)
#                     g_color = (0, 0, 255)
#                     for hand_lm in hand_results.hand_landmarks:
#                         xs = [lm.x for lm in hand_lm]; ys = [lm.y for lm in hand_lm]
#                         gx1 = max(0, int(min(xs) * w) - 20); gy1 = max(0, int(min(ys) * h) - 20)
#                         gx2 = min(w, int(max(xs) * w) + 20); gy2 = min(h, int(max(ys) * h) + 20)
#                         sx = max(1, int((gx2 - gx1) * 0.12)); sy = max(1, int((gy2 - gy1) * 0.12))
#                         gx1d = min(gx2 - 1, gx1 + sx); gy1d = min(gy2 - 1, gy1 + sy)
#                         gx2d = max(gx1d + 1, gx2 - sx); gy2d = max(gy1d + 1, gy2 - sy)
#                         cv2.rectangle(resized, (gx1d, gy1d), (gx2d, gy2d), g_color, 1)
#                         cv2.putText(resized, "NGO", (gx1d, gy1d - 10),
#                                     cv2.FONT_HERSHEY_SIMPLEX, 0.35, g_color, 1)

#         fps = 1.0 / (time.time() - start + 1e-5)
#         cv2.putText(resized, f"Cam {cam_id} | FPS: {fps:.1f} | Violations: {violations}",
#                     (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

#         # ── MJPEG encode ───────────────────────────────────────────────────
#         _, jpeg = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 80])
#         jpeg_bytes = jpeg.tobytes()
#         # Manager dict is already serialised internally; explicit lock is redundant
#         # and adds 2 extra IPC round-trips per frame.
#         frame_dict[cam_id] = jpeg_bytes

#         # Throttle stats updates to once/second — each set_stats is 4 IPC ops.
#         _now_stats = time.time()
#         if _now_stats - _last_stats_ts >= 1.0:
#             set_stats("running", round(fps, 1), violations, frame_count,
#                       extra={"frame_buffer_bytes": len(jpeg_bytes)})
#             _last_stats_ts = _now_stats

#     # ── Cleanup ────────────────────────────────────────────────────────────
#     if _mp_hands is not None:
#         try:
#             _mp_hands.close()
#         except Exception:
#             pass
#     set_stats("stopped", 0, 0, 0, extra={"frame_buffer_bytes": 0})
