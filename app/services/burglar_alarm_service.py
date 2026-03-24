"""
app/services/burglar_alarm_service.py
--------------------------------------
Helper functions for the burglar alarm module.

Responsibilities:
  - is_in_alarm_window(start, end)  — time-window validation (handles overnight ranges)
  - point_in_polygon(px, py, pts)   — ray-casting check (no extra deps)
  - is_person_in_zone(det, zone, w, h) — check if a detection center is inside a zone
  - fetch_burglar_config(cam_id)    — load config + zone points from DB at thread start
  - init_kcf_tracker(frame, bbox)   — create and initialize a KCF tracker
"""

from __future__ import annotations
from datetime import datetime
import cv2


# ---------------------------------------------------------------------------
# Time-window check
# ---------------------------------------------------------------------------

def is_in_alarm_window(start_str: str, end_str: str) -> bool:
    """
    Return True if the current local time falls inside [start_str, end_str].

    Handles overnight windows, e.g. "20:00" → "05:00":
      start > end  →  active when  now >= start  OR  now <= end
      start <= end →  active when  start <= now <= end
    """
    now = datetime.now().time()
    try:
        sh, sm = map(int, start_str.split(":"))
        eh, em = map(int, end_str.split(":"))
    except (ValueError, AttributeError):
        return False   # bad config → fail safe (don't trigger)

    start_min = sh * 60 + sm
    end_min   = eh * 60 + em
    now_min   = now.hour * 60 + now.minute

    if start_min == end_min:
        return True  # window spans full 24 h

    if start_min < end_min:
        return start_min <= now_min <= end_min
    else:
        # Overnight: e.g. 20:00 – 05:00
        return now_min >= start_min or now_min <= end_min


# ---------------------------------------------------------------------------
# Point-in-polygon (ray casting)
# ---------------------------------------------------------------------------

def point_in_polygon(px: float, py: float, polygon: list[dict]) -> bool:
    """
    Return True if pixel point (px, py) is inside *polygon*.

    *polygon* is a list of dicts with keys 'x' and 'y' in **normalized**
    [0, 1] coordinates.  The caller is responsible for passing (px, py)
    also normalised, or for denormalising both consistently.
    """
    n = len(polygon)
    if n < 3:
        return False

    inside = False
    j = n - 1
    for i in range(n):
        xi, yi = polygon[i]["x"], polygon[i]["y"]
        xj, yj = polygon[j]["x"], polygon[j]["y"]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / (yj - yi + 1e-9) + xi):
            inside = not inside
        j = i
    return inside


def is_person_in_zone(
    det: dict,
    zone_points: list[dict],
    frame_w: int,
    frame_h: int,
) -> bool:
    """
    Return True if the detection centre is inside *zone_points*.

    *det*  must contain a "box" key: [x1, y1, x2, y2] in pixel coords.
    *zone_points* is the raw normalized list from the ROI model.
    """
    if not zone_points or frame_w <= 0 or frame_h <= 0:
        return True   # no zone configured → always trigger

    box = det.get("box") or [
        det.get("x1", 0), det.get("y1", 0),
        det.get("x2", 0), det.get("y2", 0),
    ]
    cx_norm = ((box[0] + box[2]) / 2) / frame_w
    cy_norm = ((box[1] + box[3]) / 2) / frame_h
    return point_in_polygon(cx_norm, cy_norm, zone_points)


# ---------------------------------------------------------------------------
# KCF tracker factory
# ---------------------------------------------------------------------------

def init_kcf_tracker(frame, bbox: list | tuple):
    """
    Create a KCF tracker and initialize it with *bbox* on *frame*.

    *bbox* is [x1, y1, x2, y2] in pixel coordinates (as returned by YOLO).
    Returns the initialized cv2.TrackerKCF instance, or None on failure.
    """
    try:
        x1, y1, x2, y2 = map(int, bbox)
        # OpenCV tracker expects (x, y, w, h)
        rect = (x1, y1, x2 - x1, y2 - y1)
        tracker = cv2.TrackerKCF_create()
        ok = tracker.init(frame, rect)
        # OpenCV ≥4.x returns None on success; only discard on explicit False
        if ok is False:
            return None
        return tracker
    except Exception as e:
        print(f"[KCF] Tracker init failed: {e}")
        return None


# ---------------------------------------------------------------------------
# DB helper — called once per camera at thread start
# ---------------------------------------------------------------------------

def fetch_burglar_config(cam_id: int) -> dict | None:
    """
    Load the BurglarAlarmConfig row for *cam_id* from the DB.

    Returns a plain dict for use inside the camera worker thread, or None if
    no config exists.

    The dict contains pre-fetched ROI points so the worker thread does not
    need DB access during the inference loop.

    Schema::
        {
            "alarm_enabled":    bool,
            "alarm_start_time": "HH:MM",
            "alarm_end_time":   "HH:MM",
            "monitored_zone_id":     str | None,
            "monitored_zone_points": list | None,   # normalised [{x,y},…]
            "cooldown_sec":     int,
        }
    """
    try:
        from app.db.database import SessionLocal
        from app.db.models import BurglarAlarmConfig, ROI

        if SessionLocal is None:
            return None

        with SessionLocal() as db:
            cfg = (
                db.query(BurglarAlarmConfig)
                .filter(BurglarAlarmConfig.camera_id == cam_id)
                .first()
            )
            if cfg is None:
                return None

            zone_points = None
            if cfg.monitored_zone_id:
                roi = db.get(ROI, cfg.monitored_zone_id)
                if roi and roi.is_active:
                    zone_points = roi.points_normalized

            return {
                "alarm_enabled":         cfg.alarm_enabled,
                "alarm_start_time":      cfg.alarm_start_time,
                "alarm_end_time":        cfg.alarm_end_time,
                "monitored_zone_id":     cfg.monitored_zone_id,
                "monitored_zone_points": zone_points,
                "cooldown_sec":          cfg.cooldown_sec,
            }
    except Exception as e:
        print(f"[BurglarAlarm] Could not fetch config for camera {cam_id}: {e}")
        return None
