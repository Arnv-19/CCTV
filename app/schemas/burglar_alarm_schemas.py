from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter
from pydantic import BaseModel, field_validator

from app.db.models.burglar_alarm_config import BurglarAlarmConfig
from app.db.models.burglar_alarm_event import BurglarAlarmEvent


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
