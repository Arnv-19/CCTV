
from datetime import date, datetime
from typing import Optional
from zoneinfo import ZoneInfo

from pydantic import BaseModel

from app.db.models import Alert


_IST_TZ = ZoneInfo("Asia/Kolkata")


def _now_ist_naive() -> datetime:
    return datetime.now(_IST_TZ).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class AlertCreate(BaseModel):
    camera_id:        int
    model_name:       str
    violation_type:   str
    confidence_score: float
    snapshot_path:    Optional[str] = None
    buzzer_activated: bool = False


class AlertOut(BaseModel):
    id:               int
    camera_id:        int
    model_name:       str
    violation_type:   str
    confidence_score: float
    snapshot_path:    Optional[str]
    triggered_at:     datetime
    buzzer_activated: bool
    acknowledged:     bool
    acknowledged_by:  Optional[int]
    acknowledged_at:  Optional[datetime]
    acknowledger_name: Optional[str] = None

    class Config:
        from_attributes = True


class DailyReportWhatsAppRequest(BaseModel):
    report_date: Optional[date] = None
    camera_id: Optional[int] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    to: Optional[str] = None
    include_pdf: bool = True
    include_excel: bool = True
    use_dummy_data: bool = False


def _alert_dict(a: Alert) -> dict:
    return {
        "id":               a.id,
        "camera_id":        a.camera_id,
        "model_name":       a.model_name,
        "violation_type":   a.violation_type,
        "confidence_score": round(a.confidence_score, 4),
        "snapshot_path":    a.snapshot_path,
        "triggered_at":     a.triggered_at,
        "buzzer_activated": a.buzzer_activated,
        "acknowledged":     a.acknowledged,
        "acknowledged_by":  a.acknowledged_by,
        "acknowledged_at":  a.acknowledged_at,
        "acknowledger_name": a.acknowledger.username if a.acknowledger else None,
    }
