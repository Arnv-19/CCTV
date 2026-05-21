"""
inference_server.py
-------------------
Shared GPU inference server — loads YOLO model(s) ONCE and serves all cameras
via batched inference.

Architecture vs. old per-process model loading:

  Feature          | Before (per-process)  | After (shared server)
  -----------------|-----------------------|----------------------
  GPU memory       | high  (N model copies)| low  (1 model copy)
  GPU utilisation  | low   (1 frame/pass)  | high (N frames/pass)
  cameras per GPU  | 4–8                   | 15–25
  scalability      | limited               | strong

Flow:
  ingestion_worker (1 per camera, mp.Process)
      └─► frame_queue (shared mp.Queue)
              └─► inference_server_loop (1 process, shared model, batch predict)
                      └─► per-camera result_queues (mp.Queue)
                              └─► result_handler_worker (1 thread per camera)
                                      └─► frame_dict / stats_dict / alarm / MJPEG
"""

import time
from queue import Empty
import multiprocessing as mp
import cv2 as _cv2

from detector import load_model


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _parse_result(result) -> list:
    """Convert one ultralytics Result object to a list of detection dicts."""
    detections = []
    if result is None:
        return detections
    try:
        for i, box in enumerate(result.boxes.data):
            x1, y1, x2, y2, conf, cls = box.tolist()
            class_name = result.names[int(cls)]
            if class_name == "ignore":
                continue
            detections.append({
                "id":    i,
                "box":   [x1, y1, x2, y2],
                "conf":  float(conf),
                "class": class_name,
            })
    except Exception as e:
        print(f"[InferenceServer] Parse error: {e}")
    return detections


# ─────────────────────────────────────────────────────────────────────────────
# Main entry point (runs as a dedicated mp.Process)
# ─────────────────────────────────────────────────────────────────────────────

def inference_server_loop(
    models: dict,             # {"main": path, "gloves": path, "burglar": path, "vehicle": path, ...}
    frame_queue: mp.Queue,    # In:  (cam_id, frame_bgr_ndarray, ts_float)
    result_queues,            # Out: Manager dict {cam_id: mp.Queue} — supports hot camera add
    stop_event: mp.Event,
    batch_size: int = 8,
    batch_timeout: float = 0.05,  # seconds to wait for a full batch
    threshold: float = 0.25,
    yolo_imgsz: int = 640,
):
    """
    Run as a single shared inference process.

    `models` dict keys:
        "main"    — required. primary detection model (PPE, helmet, etc.)
        "gloves"  — optional. gloves/bare-hand model
        "burglar" — optional. person/intruder model for burglar alarm
        any other key (e.g. "vehicle", "fire") — loaded and run as an extra model

    Adding a new model in the future = one new key in the dict. No code changes needed.

    Result tuple written to each camera's result_queue:
        (cam_id, frame_jpeg, ts, main_dets, extra_dets)

        main_dets  — list of detection dicts from the "main" model
        extra_dets — {model_name: [detections] | None}
                     None means "same as main" (path was identical — no extra GPU call)
    """
    main_path = models.get("main")
    if not main_path:
        raise ValueError("[InferenceServer] 'main' key is required in models dict")

    print(f"[InferenceServer] Loading main model: {main_path}")
    main_model = load_model(main_path)

    # ── Load all secondary models ─────────────────────────────────────────
    # _secondary: {name: (model_obj, same_as_main)}
    # same_as_main=True → skip separate GPU call; caller reuses main results downstream
    _secondary: dict = {}
    for name, path in models.items():
        if name == "main" or not path:
            continue
        if path == main_path:
            _secondary[name] = (main_model, True)
            print(f"[InferenceServer] Model '{name}' reuses main model (same path).")
        else:
            try:
                m = load_model(path)
                _secondary[name] = (m, False)
                print(f"[InferenceServer] Model '{name}' loaded: {path}")
            except Exception as e:
                print(f"[InferenceServer] Model '{name}' unavailable ({e}); falling back to main model.")
                _secondary[name] = (main_model, True)

    print(
        f"[InferenceServer] Ready — "
        f"batch_size={batch_size}, timeout={batch_timeout}s, imgsz={yolo_imgsz}, "
        f"models={list(models.keys())}"
    )

    # Local queue cache: avoid an IPC round-trip to the Manager on every frame.
    # Populated on first access per cam_id; safe because mp.Queue objects are stable.
    _rq_cache: dict = {}

    def _get_result_queue(cam_id):
        if cam_id not in _rq_cache:
            q = result_queues.get(cam_id)
            if q is not None:
                _rq_cache[cam_id] = q
        return _rq_cache.get(cam_id)

    while not stop_event.is_set():
        # ── Wait for the first frame, then drain the queue ────────────────
        # On CPU the inference cycle is slower than ingestion, so the queue
        # accumulates stale frames. We always process the LATEST frame per
        # camera — never a backlog — so the stream stays current.
        try:
            first = frame_queue.get(timeout=0.05)
        except Empty:
            continue

        if first is None:   # stop sentinel
            stop_event.set()
            print("[InferenceServer] Received stop sentinel.")
            return

        # Drain all queued frames; keep only the newest per camera.
        latest: dict = {first[0]: first}
        try:
            while True:
                item = frame_queue.get_nowait()
                if item is None:
                    stop_event.set()
                    print("[InferenceServer] Received stop sentinel.")
                    return
                latest[item[0]] = item   # newer frame overwrites older
        except Empty:
            pass

        batch = list(latest.values())

        cam_ids = [it[0] for it in batch]
        frames  = [it[1] for it in batch]
        tss     = [it[2] for it in batch]

        # ── Batch YOLO inference — main model ─────────────────────────────
        try:
            main_results = main_model.predict(
                source=frames,
                conf=threshold,
                imgsz=yolo_imgsz,
                stream=False,
                verbose=False,
            )
        except Exception as e:
            print(f"[InferenceServer] Main batch inference error: {e}")
            main_results = [None] * len(batch)

        # ── Batch YOLO inference — secondary models (one GPU call each) ───
        # _sec_results: {name: [Result, ...] | None}
        # None = same_as_main sentinel; caller resolves to main_dets downstream.
        _sec_results: dict = {}
        for name, (m, same_as_main) in _secondary.items():
            if same_as_main:
                _sec_results[name] = None
            else:
                try:
                    _sec_results[name] = m.predict(
                        source=frames,
                        conf=threshold,
                        imgsz=yolo_imgsz,
                        stream=False,
                        verbose=False,
                    )
                except Exception as e:
                    print(f"[InferenceServer] Model '{name}' batch error: {e}")
                    _sec_results[name] = [None] * len(batch)

        # ── Route results to per-camera queues ────────────────────────────
        # Frames are JPEG-encoded before entering the Manager Queue to reduce
        # IPC data volume from ~900 KB (raw BGR numpy) to ~50 KB per frame.
        for i, (cam_id, frame, ts) in enumerate(zip(cam_ids, frames, tss)):
            main_dets = _parse_result(main_results[i] if i < len(main_results) else None)

            extra_dets: dict = {}
            for name, results in _sec_results.items():
                extra_dets[name] = (
                    None   # sentinel: caller uses main_dets
                    if results is None
                    else _parse_result(results[i] if i < len(results) else None)
                )

            ret, jpeg = _cv2.imencode(".jpg", frame, [_cv2.IMWRITE_JPEG_QUALITY, 80])
            frame_payload = jpeg.tobytes() if ret else None
            if frame_payload is None:
                continue

            q = _get_result_queue(cam_id)
            if q is None:
                continue
            payload = (cam_id, frame_payload, ts, main_dets, extra_dets)
            try:
                q.put_nowait(payload)
            except Exception:
                # Queue full — evict oldest then retry once
                try:
                    q.get_nowait()
                    q.put_nowait(payload)
                except Exception:
                    pass   # drop silently

    print("[InferenceServer] Stopped.")
