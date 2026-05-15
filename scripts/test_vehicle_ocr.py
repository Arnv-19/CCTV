"""
scripts/test_vehicle_ocr.py
---------------------------
Standalone smoke-test for the vehicle detection + OCR + DB pipeline.
No camera or RTSP stream needed.

Usage (from project root):
    python scripts/test_vehicle_ocr.py                   # synthetic image
    python scripts/test_vehicle_ocr.py path/to/car.jpg   # your own image

What it tests:
    1. YOLO vehicle detection    — runs Vehicle.pt to detect vehicle type + bbox
    2. detect_plate_region()     — finds the plate region inside the vehicle crop
    3. run_plate_ocr()           — reads text from the plate region
    4. process_vehicle_detection() — full pipeline: crop → OCR → save snapshots
    5. VehicleDetectionEvent DB row — writes directly to DB and reads it back
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import cv2
import numpy as np
from pathlib import Path
from datetime import datetime, timezone

VEHICLE_WEIGHTS = Path(__file__).parent.parent / "weights" / "Vehicle.pt"
SNAPSHOT_DIR    = "snapshots/test"


# ── Step 0a: build a synthetic vehicle frame (no image needed) ────────────────

def make_synthetic_vehicle_frame() -> np.ndarray:
    """Draw a fake truck with a readable plate — no real image needed."""
    frame = np.ones((480, 640, 3), dtype=np.uint8) * 50

    cv2.rectangle(frame, (80, 80),   (560, 420), (120, 120, 120), -1)   # body
    cv2.rectangle(frame, (150, 110), (490, 230), (180, 200, 210), -1)   # windshield
    cv2.rectangle(frame, (90, 350),  (160, 390), (220, 220, 100), -1)   # headlight L
    cv2.rectangle(frame, (480, 350), (550, 390), (220, 220, 100), -1)   # headlight R
    cv2.rectangle(frame, (220, 385), (420, 415), (240, 240, 240), -1)   # plate bg
    cv2.putText(frame, "MH 12 AB 1234", (228, 410),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 2)

    return frame


# ── Step 0b: load a real image and run YOLO to detect vehicles ────────────────

def load_frame_from_file(path: str) -> np.ndarray:
    """Read an image file and return the BGR frame."""
    frame = cv2.imread(path)
    if frame is None:
        raise FileNotFoundError(f"Could not read image: {path}")
    return frame


def run_yolo_on_frame(frame: np.ndarray) -> list[dict]:
    """
    Run Vehicle.pt YOLO on *frame* and return a list of detection dicts.

    Each dict: {box, class, conf, id}
    Falls back to a full-frame bounding box if the model file is missing
    or no vehicle is detected.
    """
    print("\n── Step 1: YOLO vehicle detection ────────────────────────────────")

    if not VEHICLE_WEIGHTS.exists():
        print(f"  ! Vehicle.pt not found at {VEHICLE_WEIGHTS}")
        print("    Falling back — treating the whole image as one vehicle.")
        h, w = frame.shape[:2]
        return [{"box": [0, 0, w, h], "class": "vehicle", "conf": 0.0, "id": 0}]

    try:
        from ultralytics import YOLO
        model   = YOLO(str(VEHICLE_WEIGHTS))
        results = model.predict(source=frame, conf=0.25, verbose=False)[0]

        detections = []
        for i, box in enumerate(results.boxes.data):
            x1, y1, x2, y2, conf, cls = box.tolist()
            detections.append({
                "box":   [x1, y1, x2, y2],
                "class": results.names[int(cls)],
                "conf":  float(conf),
                "id":    i,
            })

        if detections:
            print(f"  ✓ {len(detections)} vehicle(s) detected:")
            for d in detections:
                x1, y1, x2, y2 = map(int, d["box"])
                print(f"      [{d['id']}] class={d['class']!r:12s}  "
                      f"conf={d['conf']:.3f}  bbox=({x1},{y1})→({x2},{y2})")
            return detections

        print("  ! No vehicles detected — treating full frame as one vehicle.")
        h, w = frame.shape[:2]
        return [{"box": [0, 0, w, h], "class": "vehicle", "conf": 0.0, "id": 0}]

    except Exception as exc:
        print(f"  ! YOLO inference failed: {exc}")
        print("    Falling back to full-frame detection.")
        h, w = frame.shape[:2]
        return [{"box": [0, 0, w, h], "class": "vehicle", "conf": 0.0, "id": 0}]


# ── Step 2-4: OCR pipeline for each detected vehicle ─────────────────────────

def test_controller(frame: np.ndarray, detections: list[dict]):
    """Run the full OCR pipeline for every detected vehicle."""
    from app.controllers.vehicle_detection_controller import (
        detect_plate_region,
        run_plate_ocr,
        process_vehicle_detection,
    )

    Path(SNAPSHOT_DIR).mkdir(parents=True, exist_ok=True)
    events = []

    for det in detections:
        print(f"\n── Vehicle [{det['id']}] — class={det['class']!r}  "
              f"conf={det['conf']:.3f} ──────────────")

        # ── Step 2: plate region ─────────────────────────────────────────────
        print("  Step 2: detect_plate_region()")
        bbox = det["box"]
        x1, y1, x2, y2 = [max(0, int(v)) for v in bbox]
        h, w = frame.shape[:2]
        vehicle_crop = frame[y1:min(h, y2), x1:min(w, x2)]
        plate_img    = detect_plate_region(vehicle_crop)

        if plate_img is not None and plate_img.size > 0:
            plate_save = f"{SNAPSHOT_DIR}/plate_crop_{det['id']}.jpg"
            cv2.imwrite(plate_save, plate_img)
            print(f"    ✓ plate region found  shape={plate_img.shape} → {plate_save}")
        else:
            print("    ! no plate region found (using lower-third fallback)")
            plate_img = vehicle_crop[int(vehicle_crop.shape[0] * 0.55):, :]

        # ── Step 3: OCR ──────────────────────────────────────────────────────
        print("  Step 3: run_plate_ocr()")
        plate_text, ocr_conf = run_plate_ocr(plate_img)
        print(f"    plate_number   = {plate_text!r}")
        print(f"    ocr_confidence = {ocr_conf:.3f}")

        # ── Step 4: full pipeline (saves annotated snapshot) ────────────────
        print("  Step 4: process_vehicle_detection()")
        event = process_vehicle_detection(frame, det, cam_id=0, snapshot_dir=SNAPSHOT_DIR)
        print(f"    vehicle_class      = {event['vehicle_class']}")
        print(f"    confidence_score   = {event['confidence_score']:.3f}")
        print(f"    plate_number       = {event['plate_number']!r}")
        print(f"    plate_confidence   = {event['plate_confidence']}")
        print(f"    snapshot_path      = {event['snapshot_path']}")
        print(f"    plate_snapshot_path= {event['plate_snapshot_path']}")

        events.append(event)

    return events


# ── Step 5: DB write + read-back ──────────────────────────────────────────────

def test_db_write(events: list[dict]):
    print("\n── Step 5: DB write + read-back ──────────────────────────────────")
    try:
        from dotenv import load_dotenv
        load_dotenv()
        from app.db.database import SessionLocal, ensure_database_connected
        from app.db.models.vehicle_detection_event import VehicleDetectionEvent

        ensure_database_connected()
        inserted_ids = []

        with SessionLocal() as db:
            for event in events:
                row = VehicleDetectionEvent(
                    camera_id           = None,
                    vehicle_class       = event["vehicle_class"],
                    confidence_score    = event["confidence_score"],
                    plate_number        = event["plate_number"],
                    plate_confidence    = event["plate_confidence"],
                    snapshot_path       = event["snapshot_path"],
                    plate_snapshot_path = event["plate_snapshot_path"],
                    bbox_x1             = event["bbox_x1"],
                    bbox_y1             = event["bbox_y1"],
                    bbox_x2             = event["bbox_x2"],
                    bbox_y2             = event["bbox_y2"],
                    triggered_at        = datetime.now(timezone.utc).replace(tzinfo=None),
                )
                db.add(row)
                db.flush()
                inserted_ids.append(row.id)
            db.commit()

        for eid in inserted_ids:
            with SessionLocal() as db:
                fetched = db.get(VehicleDetectionEvent, eid)
                assert fetched is not None
                print(f"  ✓ id={fetched.id}  "
                      f"vehicle_class={fetched.vehicle_class!r:12s}  "
                      f"plate_number={fetched.plate_number!r}")

    except Exception as exc:
        print(f"  ✗ DB test skipped / failed: {exc}")
        print("    (start the server + DB first, or check your .env)")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    image_path = sys.argv[1] if len(sys.argv) > 1 else None

    print("=" * 60)
    print("  Vehicle detection + OCR pipeline smoke-test")
    print("=" * 60)

    if image_path:
        print(f"\nLoading image: {image_path}")
        frame = load_frame_from_file(image_path)
    else:
        print("\nNo image supplied — using synthetic vehicle frame.")
        frame = make_synthetic_vehicle_frame()
        Path("snapshots").mkdir(exist_ok=True)
        cv2.imwrite("snapshots/test_synthetic_frame.jpg", frame)
        print("  saved → snapshots/test_synthetic_frame.jpg")

    print(f"  frame shape = {frame.shape}")

    # Step 1: run YOLO to detect vehicle type(s) + bboxes
    detections = run_yolo_on_frame(frame)

    # Steps 2-4: plate region + OCR + snapshots for each vehicle
    events = test_controller(frame, detections)

    # Step 5: save to DB
    test_db_write(events)

    print("\n" + "=" * 60)
    print("  Done.")
    print("=" * 60)
