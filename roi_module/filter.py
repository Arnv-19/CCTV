"""
Detection Filtering Hook
========================
Drop this into any detection pipeline to apply ROI-based spatial filtering.

Quick-start
-----------
    from roi_module.filter import filter_detections

    # Inside your camera loop, after running the YOLO model:
    detections = [{"x1": 100, "y1": 50, "x2": 200, "y2": 150, "class": "no_helmet"}]
    kept, dropped = filter_detections(
        detections=detections,
        camera_id="cam_1",
        frame_w=1280,
        frame_h=720,
        db=db_session,
    )
    # Use `kept` for alert generation

Detection dict formats supported
---------------------------------
  {x1, y1, x2, y2}            # pixel coords
  {xmin, ymin, xmax, ymax}    # pixel coords
  {bbox: [x1, y1, x2, y2]}    # pixel coords
  {x1, y1, x2, y2}            # already normalized (max value ≤ 1.0)
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from .config import roi_config
from .geometry import (
    compute_iou_with_polygon,
    detection_bbox_normalized,
    detection_center,
    point_in_polygon,
    points_to_tuples,
)
from .service import get_camera_rois_cached

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-detection / per-ROI check
# ---------------------------------------------------------------------------

def is_detection_in_roi(
    detection: dict,
    roi: dict,
    frame_w: int,
    frame_h: int,
) -> bool:
    """
    Return True if *detection* falls inside (or overlaps sufficiently with)
    the given *roi*, according to the configured filter_mode.
    """
    points = roi["points_normalized"]

    if roi_config.filter_mode == "center":
        cx, cy = detection_center(detection)
        # Auto-normalize if coords look like pixels
        if frame_w > 1 and (cx > 1.0 or cy > 1.0):
            cx, cy = cx / frame_w, cy / frame_h
        return point_in_polygon((cx, cy), points_to_tuples(points))

    elif roi_config.filter_mode == "iou":
        bbox_norm = detection_bbox_normalized(detection, frame_w, frame_h)
        iou = compute_iou_with_polygon(bbox_norm, points)
        return iou >= roi_config.iou_threshold

    return False


# ---------------------------------------------------------------------------
# Main filter function
# ---------------------------------------------------------------------------

def filter_detections(
    detections: List[dict],
    camera_id: str,
    frame_w: int,
    frame_h: int,
    db: Optional[Session] = None,
    rois: Optional[List[dict]] = None,
) -> Tuple[List[dict], List[dict]]:
    """
    Split *detections* into (kept, dropped) based on active ROI polygons.

    Args:
        detections:  List of detection dicts from your model.
        camera_id:   Camera identifier; used to look up ROIs when *rois* is None.
        frame_w:     Frame width in pixels (used for coordinate normalization).
        frame_h:     Frame height in pixels.
        db:          SQLAlchemy session. Required if *rois* is not pre-supplied.
        rois:        Pre-fetched list of ROI dicts (bypasses DB + cache lookup).
                     Pass this in tight loops to avoid any I/O overhead.

    Returns:
        ``(kept_detections, dropped_detections)``

    Fallback rules:
    - No active ROIs + allow_outside_fallback=True  → all detections kept.
    - No active ROIs + allow_outside_fallback=False → all detections dropped.
    """
    if not detections:
        return [], []

    if rois is None:
        if db is None:
            raise ValueError("Provide either 'db' or pre-fetched 'rois'.")
        rois = get_camera_rois_cached(db, camera_id)

    active_rois = [r for r in rois if r.get("is_active", True)]

    if not active_rois:
        if roi_config.allow_outside_fallback:
            if roi_config.debug_mode:
                logger.debug(
                    "camera=%s no active ROIs → pass-through all %d detections",
                    camera_id, len(detections),
                )
            return detections, []
        else:
            if roi_config.debug_mode:
                logger.debug(
                    "camera=%s no active ROIs + strict mode → drop all %d detections",
                    camera_id, len(detections),
                )
            return [], detections

    kept: List[dict] = []
    dropped: List[dict] = []

    for det in detections:
        in_any_roi = any(
            is_detection_in_roi(det, roi, frame_w, frame_h)
            for roi in active_rois
        )
        (kept if in_any_roi else dropped).append(det)

    if roi_config.debug_mode:
        logger.debug(
            "camera=%s kept=%d dropped=%d rois=%d mode=%s",
            camera_id, len(kept), len(dropped), len(active_rois), roi_config.filter_mode,
        )

    return kept, dropped


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def make_roi_filter(camera_id: str, frame_w: int, frame_h: int, db: Session):
    """
    Return a callable ``(detections) -> (kept, dropped)`` bound to a specific camera.
    Useful to avoid repeating arguments on every call.

    Example::

        roi_filter = make_roi_filter("cam_1", 1280, 720, db)
        while True:
            frame = cap.read()
            dets = model.detect(frame)
            kept, _ = roi_filter(dets)
            trigger_alerts(kept)
    """
    def _filter(detections: List[dict]) -> Tuple[List[dict], List[dict]]:
        return filter_detections(detections, camera_id, frame_w, frame_h, db=db)
    return _filter
