from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel

_IST_TZ = ZoneInfo("Asia/Kolkata")


class VehicleEventOut(BaseModel):
    id:                  int
    camera_id:           Optional[int]
    vehicle_class:       str
    confidence_score:    float
    plate_number:        Optional[str]
    plate_confidence:    Optional[float]
    snapshot_path:       Optional[str]
    plate_snapshot_path: Optional[str]
    triggered_at:        datetime

    class Config:
        from_attributes = True


def _event_dict(e) -> dict:
    """Serialize a VehicleDetectionEvent ORM row to a plain dict."""
    return {
        "id":                  e.id,
        "camera_id":           e.camera_id,
        "vehicle_class":       e.vehicle_class,
        "confidence_score":    round(e.confidence_score, 4),
        "plate_number":        e.plate_number,
        "plate_confidence":    round(e.plate_confidence, 4) if e.plate_confidence else None,
        "snapshot_path":       e.snapshot_path,
        "plate_snapshot_path": e.plate_snapshot_path,
        "triggered_at":        e.triggered_at,
    }
