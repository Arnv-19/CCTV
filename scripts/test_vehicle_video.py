"""
scripts/test_vehicle_video.py
------------------------------
Test the vehicle detection + OCR pipeline on real video files.

Usage (from project root):
    python scripts/test_vehicle_video.py                         # all videos in testdataset/videos/
    python scripts/test_vehicle_video.py testdataset/videos/test.mp4
    python scripts/test_vehicle_video.py testdataset/videos/test.mp4 --interval 2.0
    python scripts/test_vehicle_video.py testdataset/videos/test.mp4 --save-db
    python scripts/test_vehicle_video.py testdataset/videos/test.mp4 --save-frames

Options:
    --interval N   Sample one frame every N seconds (default: 1.0)
    --save-db      Write detected events to the database
    --save-frames  Save annotated frames with detections to snapshots/video_test/
    --conf N       YOLO confidence threshold (default: 0.25)
"""

import sys
import os
import argparse
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np

VEHICLE_WEIGHTS = Path(__file__).parent.parent / "weights" / "Vehicle.pt"
VIDEO_DIR       = Path("testdataset/videos")
OUTPUT_DIR      = Path("snapshots/video_test")


# ── YOLO model (loaded once, reused across all frames) ────────────────────────

_yolo_model = None

def get_yolo_model():
    global _yolo_model
    if _yolo_model is not None:
        return _yolo_model
    if not VEHICLE_WEIGHTS.exists():
        print(f"[WARN] Vehicle.pt not found at {VEHICLE_WEIGHTS} — skipping YOLO")
        return None
    from ultralytics import YOLO
    print(f"[INFO] Loading YOLO model from {VEHICLE_WEIGHTS} ...")
    _yolo_model = YOLO(str(VEHICLE_WEIGHTS))
    print("[INFO] YOLO model loaded.")
    return _yolo_model


def run_yolo(frame: np.ndarray, conf_thresh: float = 0.25) -> list[dict]:
    model = get_yolo_model()
    if model is None:
        h, w = frame.shape[:2]
        return [{"box": [0, 0, w, h], "class": "vehicle", "conf": 0.0, "id": 0}]

    results = model.predict(source=frame, conf=conf_thresh, verbose=False)[0]
    detections = []
    for i, box in enumerate(results.boxes.data):
        x1, y1, x2, y2, conf, cls = box.tolist()
        detections.append({
            "box":   [x1, y1, x2, y2],
            "class": results.names[int(cls)],
            "conf":  float(conf),
            "id":    i,
        })
    return detections


# ── Per-frame processing ──────────────────────────────────────────────────────

def process_frame(frame: np.ndarray, frame_idx: int, timestamp: float,
                  conf_thresh: float, save_db: bool, snapshot_dir: str) -> list[dict]:
    from app.controllers.vehicle_detection_controller import process_vehicle_detection

    detections = run_yolo(frame, conf_thresh)
    if not detections:
        return []

    events = []
    for det in detections:
        event = process_vehicle_detection(frame, det, cam_id=0, snapshot_dir=snapshot_dir)
        event["_frame_idx"]  = frame_idx
        event["_timestamp"]  = timestamp
        event["_box"]        = det.get("box", [])
        events.append(event)

    if save_db:
        _write_to_db(events)

    return events


def _write_to_db(events: list[dict]) -> None:
    from datetime import datetime, timezone
    try:
        from app.db.database import SessionLocal, ensure_database_connected
        from app.db.models.vehicle_detection_event import VehicleDetectionEvent
        ensure_database_connected()
        with SessionLocal() as db:
            for ev in events:
                row = VehicleDetectionEvent(
                    camera_id           = None,
                    vehicle_class       = ev["vehicle_class"],
                    confidence_score    = ev["confidence_score"],
                    plate_number        = ev["plate_number"],
                    plate_confidence    = ev["plate_confidence"],
                    snapshot_path       = ev["snapshot_path"],
                    plate_snapshot_path = ev["plate_snapshot_path"],
                    triggered_at        = datetime.now(timezone.utc).replace(tzinfo=None),
                )
                db.add(row)
            db.commit()
    except Exception as exc:
        print(f"  [DB ERROR] {exc}")


# ── Annotated frame save ──────────────────────────────────────────────────────

def save_annotated_frame(frame: np.ndarray, events: list[dict],
                          video_name: str, frame_idx: int, out_dir: Path) -> None:
    annotated = frame.copy()
    for ev in events:
        box = ev.get("_box", [])
        if len(box) == 4:
            x1, y1, x2, y2 = map(int, box)
            plate = ev["plate_number"] or "?"
            label = f"{ev['vehicle_class']} {ev['confidence_score']:.2f} | {plate}"
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 165, 255), 2)
            cv2.putText(annotated, label, (x1, max(y1 - 8, 12)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)
    out_path = out_dir / f"{video_name}_frame{frame_idx:06d}.jpg"
    cv2.imwrite(str(out_path), annotated)


# ── Main video loop ───────────────────────────────────────────────────────────

def process_video(video_path: Path, interval: float, conf_thresh: float,
                  save_db: bool, save_frames: bool) -> None:
    print(f"\n{'='*60}")
    print(f"  Video: {video_path.name}")
    print(f"{'='*60}")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        print(f"  [ERROR] Cannot open {video_path}")
        return

    fps        = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_f    = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration   = total_f / fps
    step       = max(1, int(fps * interval))
    snap_dir   = str(OUTPUT_DIR / video_path.stem)
    out_dir    = OUTPUT_DIR / video_path.stem / "annotated"

    Path(snap_dir).mkdir(parents=True, exist_ok=True)
    if save_frames:
        out_dir.mkdir(parents=True, exist_ok=True)

    print(f"  Resolution : {int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))}x{int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))}")
    print(f"  Duration   : {duration:.1f}s  ({total_f} frames @ {fps:.1f} fps)")
    print(f"  Sampling   : every {interval}s (every {step} frames)")
    print(f"  Save DB    : {save_db}")
    print()

    frame_idx     = 0
    sampled       = 0
    total_dets    = 0
    t_start       = time.time()
    class_counts: dict[str, int] = {}
    plate_hits    = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx % step == 0:
            timestamp = frame_idx / fps
            events = process_frame(frame, frame_idx, timestamp,
                                   conf_thresh, save_db, snap_dir)

            if events:
                total_dets += len(events)
                for ev in events:
                    vc = ev["vehicle_class"]
                    class_counts[vc] = class_counts.get(vc, 0) + 1
                    if ev["plate_number"]:
                        plate_hits += 1

                for ev in events:
                    ts_str = f"{int(timestamp//60):02d}:{timestamp%60:05.2f}"
                    plate  = ev["plate_number"] or "—"
                    pconf  = f"{ev['plate_confidence']:.2f}" if ev["plate_confidence"] else "—"
                    print(f"  [{ts_str}] frame={frame_idx:5d}  "
                          f"class={ev['vehicle_class']:10s}  conf={ev['confidence_score']:.2f}  "
                          f"plate={plate}  ocr_conf={pconf}")

                if save_frames:
                    save_annotated_frame(frame, events, video_path.stem, frame_idx, out_dir)

            sampled += 1

        frame_idx += 1

    cap.release()
    elapsed = time.time() - t_start

    print(f"\n  ── Summary ─────────────────────────────────────")
    print(f"  Frames sampled : {sampled}")
    print(f"  Detections     : {total_dets}")
    print(f"  With plate OCR : {plate_hits}")
    print(f"  Vehicle types  : {dict(sorted(class_counts.items(), key=lambda x: -x[1]))}")
    print(f"  Time taken     : {elapsed:.1f}s")
    if save_frames and total_dets:
        print(f"  Annotated frames → {out_dir}/")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Vehicle detection + OCR on video files")
    parser.add_argument("videos", nargs="*", help="Video file(s) — defaults to all in testdataset/videos/")
    parser.add_argument("--interval",     type=float, default=1.0,  help="Sample every N seconds (default: 1.0)")
    parser.add_argument("--conf",         type=float, default=0.25, help="YOLO confidence threshold (default: 0.25)")
    parser.add_argument("--save-db",      action="store_true",       help="Write events to database")
    parser.add_argument("--save-frames",  action="store_true",       help="Save annotated frames as JPGs")
    args = parser.parse_args()

    from dotenv import load_dotenv
    load_dotenv()

    video_paths: list[Path] = []
    if args.videos:
        for v in args.videos:
            p = Path(v)
            if not p.exists():
                print(f"[ERROR] File not found: {v}")
                sys.exit(1)
            video_paths.append(p)
    else:
        video_paths = sorted(VIDEO_DIR.glob("*.mp4"))
        if not video_paths:
            print(f"[ERROR] No .mp4 files found in {VIDEO_DIR}")
            sys.exit(1)
        print(f"Found {len(video_paths)} video(s) in {VIDEO_DIR}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    for vp in video_paths:
        process_video(vp, args.interval, args.conf, args.save_db, args.save_frames)

    print(f"\n{'='*60}")
    print("  Done.")
    print(f"{'='*60}")
