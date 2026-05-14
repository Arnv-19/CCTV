"""
app/controllers/vehicle_detection_controller.py
------------------------------------------------
Vehicle detection + number plate OCR pipeline.

Public API (called from camera_worker.py result_handler_worker):

    process_vehicle_detection(frame, det, cam_id, snapshot_dir)
        → Full pipeline for one YOLO detection dict.
          Crops the vehicle, finds the plate region, runs OCR,
          saves snapshots, and returns an event dict ready for alert_queue.

Internal helpers (each does exactly one thing):

    get_ocr_reader()          — lazy EasyOCR singleton (loaded once per process)
    _get_plate_cascade()      — lazy Haar cascade for plate region detection
    detect_plate_region()     — find the license plate inside a vehicle crop
    run_plate_ocr()           — extract text + confidence from a plate image
    save_vehicle_snapshot()   — save annotated full-frame JPEG
    save_plate_snapshot()     — save cropped plate JPEG
    make_position_key()       — produce a grid-bucket dedup key from a bbox
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


# ── EasyOCR reader ────────────────────────────────────────────────────────────
# Loaded once per process the first time get_ocr_reader() is called.
# Thread-safe: the global assignment is protected by the GIL for simple objects.

_ocr_reader = None


def get_ocr_reader():
    """Return the EasyOCR Reader, initialising it on first call (English only)."""
    global _ocr_reader
    if _ocr_reader is None:
        try:
            import easyocr
            # gpu=False keeps it compatible with CPU-only deployments;
            # set gpu=True if a CUDA device is available and you want faster OCR.
            _ocr_reader = easyocr.Reader(["en"], gpu=False, verbose=False)
            print("[VehicleOCR] EasyOCR reader initialised.")
        except ImportError:
            print("[VehicleOCR] easyocr not installed — plate OCR disabled. Run: pip install easyocr")
        except Exception as exc:
            print(f"[VehicleOCR] EasyOCR init failed: {exc}")
    return _ocr_reader


# ── Haar cascade for plate detection ─────────────────────────────────────────
# OpenCV ships haarcascade_russian_plate_number.xml inside the cv2 data folder.
# It works reasonably well on both Russian and Indian plates.

_plate_cascade: Optional[cv2.CascadeClassifier] = None


def _get_plate_cascade() -> Optional[cv2.CascadeClassifier]:
    """Return a loaded Haar cascade classifier, or None if unavailable."""
    global _plate_cascade
    if _plate_cascade is None:
        cascade_path = Path(cv2.__file__).parent / "data" / "haarcascade_russian_plate_number.xml"
        try:
            cc = cv2.CascadeClassifier(str(cascade_path))
            _plate_cascade = cc if not cc.empty() else None
        except Exception:
            _plate_cascade = None
    return _plate_cascade


# ── Core helper functions ─────────────────────────────────────────────────────

def detect_plate_region(vehicle_crop: np.ndarray) -> Optional[np.ndarray]:
    """
    Locate the license plate inside a vehicle crop image.

    Strategy:
      1. Try Haar cascade (relaxed params to catch more plates).
      2. Fallback: bottom 45 % of the crop (plates sit at bumper height).

    Returns a BGR numpy array (plate region), or None if the crop is too small.
    """
    if vehicle_crop is None or vehicle_crop.size == 0:
        return None

    h, w = vehicle_crop.shape[:2]
    if w < 20 or h < 20:
        return None

    cascade = _get_plate_cascade()
    if cascade is not None:
        gray = cv2.cvtColor(vehicle_crop, cv2.COLOR_BGR2GRAY)
        # Try progressively more relaxed settings to find the plate
        for neighbors, scale in ((3, 1.1), (2, 1.05), (1, 1.05)):
            plates = cascade.detectMultiScale(
                gray, scaleFactor=scale, minNeighbors=neighbors, minSize=(15, 5)
            )
            if len(plates):
                px, py, pw, ph = max(plates, key=lambda p: p[2] * p[3])
                plate_crop = vehicle_crop[py: py + ph, px: px + pw]
                if plate_crop.size > 0:
                    return plate_crop

    # Fallback: bottom 45 % of the vehicle bbox, full width
    y_start = int(h * 0.55)
    fallback = vehicle_crop[y_start:, :]
    return fallback if fallback.size > 0 else None


def run_plate_ocr(plate_img: np.ndarray) -> tuple[Optional[str], float]:
    """
    Run EasyOCR on a plate image and return (text, confidence).

    - text       : cleaned, upper-cased plate string; None if nothing readable.
    - confidence : highest per-word OCR confidence seen (0.0 if no result).

    Plates smaller than 200 px wide are upscaled before OCR for better accuracy.
    Only OCR results with confidence ≥ 0.3 are kept.
    """
    reader = get_ocr_reader()
    if reader is None or plate_img is None or plate_img.size == 0:
        return None, 0.0

    try:
        h, w = plate_img.shape[:2]

        # Upscale small plates — target at least 300 px wide for better OCR
        if w < 300:
            scale = max(2, 300 // max(w, 1))
            plate_img = cv2.resize(
                plate_img, (w * scale, h * scale), interpolation=cv2.INTER_LANCZOS4
            )

        # Build a set of preprocessed variants to try.
        # Indian plates come in white (black text), yellow (white text), and green.
        # Each variant uses a different channel/space to maximise text contrast.
        h2, w2 = plate_img.shape[:2]
        variants: list[np.ndarray] = []

        # 1. CLAHE on gray (works for white plates with black text)
        gray  = cv2.cvtColor(plate_img, cv2.COLOR_BGR2GRAY)
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4))
        variants.append(cv2.cvtColor(clahe.apply(gray), cv2.COLOR_GRAY2BGR))

        # 2. Inverted HSV-saturation (works for yellow plates with white text):
        #    yellow has high saturation, white text has near-zero saturation,
        #    so inverting S gives dark text on bright background.
        hsv        = cv2.cvtColor(plate_img, cv2.COLOR_BGR2HSV)
        sat_inv    = cv2.bitwise_not(hsv[:, :, 1])
        sat_clahe  = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(2, 2)).apply(sat_inv)
        variants.append(cv2.cvtColor(sat_clahe, cv2.COLOR_GRAY2BGR))

        # 3. High-contrast BGR (boosts dark text on any background)
        boosted = cv2.convertScaleAbs(plate_img, alpha=2.0, beta=-60)
        variants.append(boosted)

        best_text = None
        best_conf = 0.0

        for variant in variants:
            results = reader.readtext(variant, detail=1, paragraph=False,
                                      text_threshold=0.3, low_text=0.2,
                                      contrast_ths=0.1, adjust_contrast=0.5)
            parts = []
            conf_sum = 0.0
            for (_bbox, text, conf) in results:
                cleaned = "".join(c for c in text.upper() if c.isalnum() or c == " ").strip()
                if cleaned and conf >= 0.25 and len(cleaned) >= 2:
                    parts.append(cleaned)
                    conf_sum = max(conf_sum, conf)

            if parts and conf_sum > best_conf:
                best_text = " ".join(parts)
                best_conf = conf_sum

        return best_text, best_conf

    except Exception as exc:
        print(f"[VehicleOCR] OCR error: {exc}")
        return None, 0.0


def save_vehicle_snapshot(
    frame: np.ndarray,
    bbox: list,
    cam_id: int,
    snapshot_dir: str,
    plate_number: Optional[str] = None,
) -> Optional[str]:
    """
    Save an annotated copy of *frame* with the vehicle bounding box and
    plate number (if found) drawn on it.

    Returns the file path string, or None on failure.
    Saved under:  <snapshot_dir>/cam_<id>/vehicles/vehicle_<timestamp>.jpg
    """
    try:
        save_dir = Path(snapshot_dir) / f"cam_{cam_id}" / "vehicles"
        save_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filepath = save_dir / f"vehicle_{ts}.jpg"

        annotated = frame.copy()
        if len(bbox) == 4:
            x1, y1, x2, y2 = [int(v) for v in bbox]
            cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 165, 255), 2)   # orange box
            label = plate_number if plate_number else "Vehicle"
            cv2.putText(
                annotated, label, (x1, max(0, y1 - 10)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 165, 255), 2,
            )
        cv2.imwrite(str(filepath), annotated)
        return str(filepath)
    except Exception as exc:
        print(f"[VehicleOCR] Snapshot save failed (cam {cam_id}): {exc}")
        return None


def save_plate_snapshot(
    plate_img: np.ndarray,
    cam_id: int,
    snapshot_dir: str,
) -> Optional[str]:
    """
    Save the cropped plate image.

    Returns the file path string, or None on failure.
    Saved under:  <snapshot_dir>/cam_<id>/plates/plate_<timestamp>.jpg
    """
    try:
        save_dir = Path(snapshot_dir) / f"cam_{cam_id}" / "plates"
        save_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        filepath = save_dir / f"plate_{ts}.jpg"
        cv2.imwrite(str(filepath), plate_img)
        return str(filepath)
    except Exception as exc:
        print(f"[VehicleOCR] Plate snapshot save failed (cam {cam_id}): {exc}")
        return None


def make_position_key(bbox: list, bucket_size: int = 100) -> str:
    """
    Quantise a bounding box centre to a grid bucket (bucket_size × bucket_size pixels).

    Used as a fallback dedup key when no plate number is available, so we don't
    re-log the same parked vehicle on every detection frame.
    """
    if not bbox or len(bbox) < 4:
        return "unknown"
    cx = int((bbox[0] + bbox[2]) / 2 / bucket_size)
    cy = int((bbox[1] + bbox[3]) / 2 / bucket_size)
    return f"pos_{cx}_{cy}"


# ── Main pipeline function ────────────────────────────────────────────────────

def process_vehicle_detection(
    frame: np.ndarray,
    det: dict,
    cam_id: int,
    snapshot_dir: str,
) -> dict:
    """
    Full pipeline for a single YOLO vehicle detection dict.

    Steps:
      1. Crop the vehicle region from *frame* using the detection bbox.
      2. Detect the plate region within the crop (Haar cascade → fallback).
      3. Run EasyOCR on the plate region.
      4. Save annotated vehicle snapshot + plate crop.
      5. Return a plain dict ready to be pushed to the shared alert_queue.

    The returned dict uses model_name="vehicle_detection" so alert_writer.py
    knows to write a VehicleDetectionEvent row instead of an Alert row.
    """
    bbox          = det.get("box", [])
    vehicle_class = det.get("class", "vehicle")
    confidence    = float(det.get("conf", 0.0))

    plate_number     = None
    plate_confidence = None
    plate_snap_path  = None

    # ── Step 1-3: crop → plate region → OCR ──────────────────────────────
    if len(bbox) == 4:
        h, w = frame.shape[:2]
        x1 = max(0, int(bbox[0]))
        y1 = max(0, int(bbox[1]))
        x2 = min(w, int(bbox[2]))
        y2 = min(h, int(bbox[3]))
        vehicle_crop = frame[y1:y2, x1:x2]

        if vehicle_crop.size > 0:
            # If YOLO already detected a plate directly, use that crop as-is.
            # Otherwise run Haar cascade / bottom-third fallback.
            if "plate" in vehicle_class.lower():
                plate_img = vehicle_crop
            else:
                plate_img = detect_plate_region(vehicle_crop)

            if plate_img is not None and plate_img.size > 0:
                plate_number, ocr_conf = run_plate_ocr(plate_img)
                plate_confidence = float(ocr_conf) if plate_number else None
                plate_snap_path  = save_plate_snapshot(plate_img, cam_id, snapshot_dir)

    # ── Step 4: save annotated frame ─────────────────────────────────────
    snap_path = save_vehicle_snapshot(
        frame, bbox, cam_id, snapshot_dir, plate_number=plate_number
    )

    # ── Step 5: build event dict ──────────────────────────────────────────
    return {
        "camera_id":           cam_id,
        "model_name":          "vehicle_detection",
        "vehicle_class":       vehicle_class,
        "confidence_score":    confidence,
        "plate_number":        plate_number,
        "plate_confidence":    plate_confidence,
        "snapshot_path":       snap_path,
        "plate_snapshot_path": plate_snap_path,
    }
