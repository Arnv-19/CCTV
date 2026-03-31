"""
app/api/routes/burglar_alarm.py
---------------------------------
Per-camera burglar alarm configuration endpoints.

GET    /api/burglar-alarm/                        List all configs
GET    /api/burglar-alarm/{camera_id}             Get config for one camera
PUT    /api/burglar-alarm/{camera_id}             Create or fully update a camera config
DELETE /api/burglar-alarm/{camera_id}             Remove config for a camera
GET    /api/burglar-alarm/{camera_id}/status      Live status (is window active right now?)

Event log endpoints:
GET    /api/burglar-alarm/events                  All events (paginated, newest first)
GET    /api/burglar-alarm/{camera_id}/events      Events for one camera (paginated)
POST   /api/burglar-alarm/events/{event_id}/ack   Acknowledge an event
"""

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import BurglarAlarmConfig, BurglarAlarmEvent, ROI, User
from app.dependencies import get_current_user, require_admin
from app.services.burglar_alarm_service import is_in_alarm_window

router = APIRouter()
_IST_TZ = ZoneInfo("Asia/Kolkata")


def _now_ist_naive() -> datetime:
    """Return current IST time as a naive datetime for DB DateTime columns."""
    return datetime.now(_IST_TZ).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class BurglarAlarmBody(BaseModel):
    alarm_enabled:    bool   = True
    alarm_start_time: str    = "20:00"   # "HH:MM"
    alarm_end_time:   str    = "06:00"   # "HH:MM"
    monitored_zone_id: Optional[str] = None
    cooldown_sec:     int    = 30

    @field_validator("alarm_start_time", "alarm_end_time")
    @classmethod
    def validate_time_format(cls, v: str) -> str:
        try:
            parts = v.split(":")
            assert len(parts) == 2
            h, m = int(parts[0]), int(parts[1])
            assert 0 <= h <= 23 and 0 <= m <= 59
        except Exception:
            raise ValueError("Time must be in HH:MM format (24-hour)")
        return v

    @field_validator("cooldown_sec")
    @classmethod
    def validate_cooldown(cls, v: int) -> int:
        if v < 0:
            raise ValueError("cooldown_sec must be >= 0")
        return v


def _cfg_dict(c: BurglarAlarmConfig) -> dict:
    return {
        "id":                 c.id,
        "camera_id":          c.camera_id,
        "alarm_enabled":      c.alarm_enabled,
        "alarm_start_time":   c.alarm_start_time,
        "alarm_end_time":     c.alarm_end_time,
        "monitored_zone_id":  c.monitored_zone_id,
        "cooldown_sec":       c.cooldown_sec,
        "created_at":         c.created_at,
        "updated_at":         c.updated_at,
    }


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/")
def list_configs(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return burglar alarm configurations for all cameras."""
    rows = db.query(BurglarAlarmConfig).order_by(BurglarAlarmConfig.camera_id).all()
    return [_cfg_dict(r) for r in rows]


@router.get("/{camera_id:int}/status")
def get_status(
    camera_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Return the current live status for a camera's burglar alarm:
      - whether a config exists
      - whether the alarm is currently within its active time window
    """
    cfg = db.query(BurglarAlarmConfig).filter(
        BurglarAlarmConfig.camera_id == camera_id
    ).first()

    if cfg is None:
        return {"configured": False, "active_now": False}

    window_active = is_in_alarm_window(cfg.alarm_start_time, cfg.alarm_end_time)
    return {
        "configured":   True,
        "alarm_enabled": cfg.alarm_enabled,
        "active_now":   cfg.alarm_enabled and window_active,
        "window_active": window_active,
        "current_time": datetime.now().strftime("%H:%M"),
    }


@router.get("/{camera_id:int}")
def get_config(
    camera_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    cfg = db.query(BurglarAlarmConfig).filter(
        BurglarAlarmConfig.camera_id == camera_id
    ).first()
    if cfg is None:
        raise HTTPException(404, f"No burglar alarm config for camera {camera_id}")
    return _cfg_dict(cfg)


@router.put("/{camera_id:int}")
def upsert_config(
    camera_id: int,
    body: BurglarAlarmBody,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Create or fully replace the burglar alarm config for a camera."""
    # Validate zone ID if provided
    if body.monitored_zone_id:
        roi = db.get(ROI, body.monitored_zone_id)
        if roi is None:
            raise HTTPException(404, f"ROI zone '{body.monitored_zone_id}' not found")

    cfg = db.query(BurglarAlarmConfig).filter(
        BurglarAlarmConfig.camera_id == camera_id
    ).first()

    if cfg is None:
        cfg = BurglarAlarmConfig(camera_id=camera_id)
        db.add(cfg)

    cfg.alarm_enabled    = body.alarm_enabled
    cfg.alarm_start_time = body.alarm_start_time
    cfg.alarm_end_time   = body.alarm_end_time
    cfg.monitored_zone_id = body.monitored_zone_id
    cfg.cooldown_sec     = body.cooldown_sec
    cfg.updated_at       = datetime.utcnow()
    db.commit()
    db.refresh(cfg)
    return _cfg_dict(cfg)


@router.delete("/{camera_id:int}")
def delete_config(
    camera_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    cfg = db.query(BurglarAlarmConfig).filter(
        BurglarAlarmConfig.camera_id == camera_id
    ).first()
    if cfg is None:
        raise HTTPException(404, f"No burglar alarm config for camera {camera_id}")
    db.delete(cfg)
    db.commit()
    return {"message": f"Burglar alarm config for camera {camera_id} deleted"}


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------

def _event_dict(e: BurglarAlarmEvent) -> dict:
    return {
        "id":                   e.id,
        "camera_id":            e.camera_id,
        "zone_id":              e.zone_id,
        "confidence_score":     e.confidence_score,
        "snapshot_path":        e.snapshot_path,
        "buzzer_activated":     e.buzzer_activated,
        "tracker_initialized":  e.tracker_initialized,
        "triggered_at":         e.triggered_at,
        # Person location at moment of detection
        "person_location": {
            "bbox_x1":      e.bbox_x1,
            "bbox_y1":      e.bbox_y1,
            "bbox_x2":      e.bbox_x2,
            "bbox_y2":      e.bbox_y2,
            "frame_width":  e.frame_width,
            "frame_height": e.frame_height,
        },
        "acknowledged":         e.acknowledged,
        "acknowledged_by":      e.acknowledged_by,
        "acknowledged_at":      e.acknowledged_at,
    }


@router.get("/events")
def list_all_events(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    unacked_only: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """
    Return burglar alarm events across all cameras, newest first.

    Query params:
      limit        — max rows to return (1–500, default 50)
      offset       — skip N rows (for pagination)
      unacked_only — if true, only return unacknowledged events
    """
    q = db.query(BurglarAlarmEvent)
    if unacked_only:
        q = q.filter(BurglarAlarmEvent.acknowledged.is_(False))
    total = q.count()
    rows = (
        q.order_by(BurglarAlarmEvent.triggered_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"total": total, "offset": offset, "limit": limit, "events": [_event_dict(r) for r in rows]}


@router.get("/{camera_id:int}/events")
def list_camera_events(
    camera_id: int,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    unacked_only: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return burglar alarm events for a specific camera, newest first."""
    q = db.query(BurglarAlarmEvent).filter(
        BurglarAlarmEvent.camera_id == camera_id
    )
    if unacked_only:
        q = q.filter(BurglarAlarmEvent.acknowledged.is_(False))
    total = q.count()
    rows = (
        q.order_by(BurglarAlarmEvent.triggered_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {"total": total, "offset": offset, "limit": limit, "events": [_event_dict(r) for r in rows]}


@router.post("/events/{event_id}/ack")
def acknowledge_event(
    event_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark a burglar alarm event as acknowledged by the current user."""
    event = db.get(BurglarAlarmEvent, event_id)
    if event is None:
        raise HTTPException(404, f"Burglar alarm event {event_id} not found")
    if event.acknowledged:
        return _event_dict(event)   # idempotent — already acked
    event.acknowledged    = True
    event.acknowledged_by = current_user.id
    event.acknowledged_at = _now_ist_naive()
    db.commit()
    db.refresh(event)
    return _event_dict(event)
