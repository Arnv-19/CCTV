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
    model_path: str,
    gloves_model_path,            # str | None
    burglar_person_model_path,    # str | None
    frame_queue: mp.Queue,        # In:  (cam_id, frame_bgr_ndarray, ts_float)
    result_queues,                # Out: Manager dict {cam_id: mp.Queue} — supports hot camera add
    stop_event: mp.Event,
    batch_size: int = 8,
    batch_timeout: float = 0.05,  # seconds to wait for a full batch
    threshold: float = 0.25,
    yolo_imgsz: int = 640,
):
    """
    Run as a single shared inference process.

    Reads frames from frame_queue, batches up to batch_size frames (or waits
    batch_timeout seconds), runs YOLO batch predict for ALL models, then routes
    each result back to the camera's dedicated result_queue as a tuple:

        (cam_id, frame_bgr, ts, detections, gloves_dets, burglar_dets)

    gloves_dets = None  →  caller should treat it as equal to detections
                            (happens when gloves_model_path == model_path)
    """
    print(f"[InferenceServer] Loading model: {model_path}")
    model = load_model(model_path)

    # ── Gloves model (reuse main model when paths match) ──────────────────
    _gloves_same_as_main = False
    if gloves_model_path and gloves_model_path != model_path:
        try:
            gloves_model = load_model(gloves_model_path)
            print(f"[InferenceServer] Gloves model loaded: {gloves_model_path}")
        except Exception as e:
            print(f"[InferenceServer] Gloves model unavailable ({e}); using main model")
            gloves_model = model
            _gloves_same_as_main = True
    elif gloves_model_path:   # same path as model_path
        gloves_model = model
        _gloves_same_as_main = True
    else:
        gloves_model = None

    # ── Burglar / person model ────────────────────────────────────────────
    _burglar_same_as_main = False
    if burglar_person_model_path and burglar_person_model_path != model_path:
        try:
            burglar_model = load_model(burglar_person_model_path)
            print(f"[InferenceServer] Burglar model loaded: {burglar_person_model_path}")
        except Exception as e:
            print(f"[InferenceServer] Burglar model unavailable ({e}); using main model")
            burglar_model = model
            _burglar_same_as_main = True
    else:
        burglar_model = model   # fallback to main
        _burglar_same_as_main = True

    print(
        f"[InferenceServer] Ready — "
        f"batch_size={batch_size}, timeout={batch_timeout}s, imgsz={yolo_imgsz}"
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
        # ── Collect a batch of frames (up to batch_timeout seconds) ───────
        batch: list = []
        deadline = time.time() + batch_timeout

        while len(batch) < batch_size:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            try:
                item = frame_queue.get(timeout=min(remaining, 0.01))
            except Empty:
                if time.time() >= deadline:
                    break
                continue

            if item is None:   # stop sentinel
                stop_event.set()
                print("[InferenceServer] Received stop sentinel.")
                return
            batch.append(item)

        if not batch:
            continue

        cam_ids = [it[0] for it in batch]
        frames  = [it[1] for it in batch]
        tss     = [it[2] for it in batch]

        # ── Batch YOLO inference — main model ─────────────────────────────
        try:
            main_results = model.predict(
                source=frames,
                conf=threshold,
                imgsz=yolo_imgsz,
                stream=False,
                verbose=False,
            )
        except Exception as e:
            print(f"[InferenceServer] Batch inference error: {e}")
            main_results = [None] * len(batch)

        # ── Batch YOLO inference — gloves model ───────────────────────────
        # Run the full batch in one GPU call instead of one-frame-at-a-time.
        if _gloves_same_as_main or gloves_model is None:
            gloves_results = None   # sentinel: reuse main detections downstream
        else:
            try:
                gloves_results = gloves_model.predict(
                    source=frames,
                    conf=threshold,
                    imgsz=yolo_imgsz,
                    stream=False,
                    verbose=False,
                )
            except Exception as e:
                print(f"[InferenceServer] Gloves batch error: {e}")
                gloves_results = [None] * len(batch)

        # ── Batch YOLO inference — burglar / person model ─────────────────
        if _burglar_same_as_main:
            burglar_results = None  # sentinel: reuse main detections downstream
        else:
            try:
                burglar_results = burglar_model.predict(
                    source=frames,
                    conf=threshold,
                    imgsz=yolo_imgsz,
                    stream=False,
                    verbose=False,
                )
            except Exception as e:
                print(f"[InferenceServer] Burglar batch error: {e}")
                burglar_results = [None] * len(batch)

        # ── Route results to per-camera queues ────────────────────────────
        # Frames are JPEG-encoded before entering the Manager Queue to reduce
        # IPC data volume from ~900 KB (raw BGR numpy) to ~50 KB per frame.
        for i, (cam_id, frame, ts) in enumerate(zip(cam_ids, frames, tss)):
            detections = _parse_result(
                main_results[i] if i < len(main_results) else None
            )
            gloves_dets = (
                None if gloves_results is None
                else _parse_result(gloves_results[i] if i < len(gloves_results) else None)
            )
            burglar_dets = (
                None if burglar_results is None
                else _parse_result(burglar_results[i] if i < len(burglar_results) else None)
            )

            ret, jpeg = _cv2.imencode(".jpg", frame, [_cv2.IMWRITE_JPEG_QUALITY, 80])
            frame_payload = jpeg.tobytes() if ret else None
            if frame_payload is None:
                continue

            q = _get_result_queue(cam_id)
            if q is None:
                continue
            try:
                q.put_nowait(
                    (cam_id, frame_payload, ts, detections, gloves_dets, burglar_dets)
                )
            except Exception:
                # Queue full — evict oldest then retry once
                try:
                    q.get_nowait()
                    q.put_nowait(
                        (cam_id, frame_payload, ts, detections, gloves_dets, burglar_dets)
                    )
                except Exception:
                    pass   # drop silently

    print("[InferenceServer] Stopped.")
