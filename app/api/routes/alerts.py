"""
app/api/routes/alerts.py
-------------------------
Alert log endpoints — violation events logged by camera workers.

GET    /api/alerts/           Query alerts with filters + pagination
GET    /api/alerts/summary    Dashboard summary stats (today / unacked / top camera / model)
POST   /api/alerts/           Create an alert (called internally by camera worker)
PATCH  /api/alerts/{id}/acknowledge   Operator marks an alert as reviewed
GET    /api/alerts/export     Export filtered alerts as CSV download
"""

import csv
import io
from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Alert, User
from app.dependencies import get_current_user
from app.services.reporting_service import (
    build_daily_report_filename,
    build_daily_report_rows,
    get_daily_alerts_query,
    render_daily_report_pdf,
    render_daily_report_xlsx,
    save_report_artifacts,
)
from app.services.whatsapp_service import WhatsAppConfigError, send_documents

router = APIRouter()
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _apply_filters(query, camera_id, model_name, date_from, date_to, acknowledged):
    if camera_id   is not None: query = query.filter(Alert.camera_id == camera_id)
    if model_name  is not None: query = query.filter(Alert.model_name == model_name)
    if date_from   is not None: query = query.filter(Alert.triggered_at >= date_from)
    if date_to     is not None: query = query.filter(Alert.triggered_at <= date_to)
    if acknowledged is not None: query = query.filter(Alert.acknowledged == acknowledged)
    return query


def _resolve_report_date(report_date: Optional[date]) -> date:
    return report_date or _now_ist_naive().date()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/summary")
def get_summary(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Dashboard summary cards."""
    today_start = _now_ist_naive().replace(hour=0, minute=0, second=0, microsecond=0)

    total_today = db.query(func.count(Alert.id)).filter(
        Alert.triggered_at >= today_start
    ).scalar()

    unacknowledged = db.query(func.count(Alert.id)).filter(
        Alert.acknowledged == False
    ).scalar()

    # Most active camera today
    top_cam = (
        db.query(Alert.camera_id, func.count(Alert.id).label("cnt"))
        .filter(Alert.triggered_at >= today_start)
        .group_by(Alert.camera_id)
        .order_by(func.count(Alert.id).desc())
        .first()
    )

    # Most triggered model today
    top_model = (
        db.query(Alert.model_name, func.count(Alert.id).label("cnt"))
        .filter(Alert.triggered_at >= today_start)
        .group_by(Alert.model_name)
        .order_by(func.count(Alert.id).desc())
        .first()
    )

    return {
        "today_count":      total_today or 0,
        "total_today":      total_today or 0,
        "unacknowledged":   unacknowledged or 0,
        "top_camera":       top_cam.camera_id if top_cam else None,
        "top_camera_id":    top_cam.camera_id if top_cam else None,
        "top_camera_count": top_cam.cnt if top_cam else 0,
        "top_model":        top_model.model_name if top_model else None,
        "top_model_count":  top_model.cnt if top_model else 0,
    }


@router.get("/")
def list_alerts(
    camera_id:    Optional[int]  = Query(None),
    model_name:   Optional[str]  = Query(None),
    date_from:    Optional[datetime] = Query(None),
    date_to:      Optional[datetime] = Query(None),
    acknowledged: Optional[bool] = Query(None),
    page:  int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = db.query(Alert)
    query = _apply_filters(query, camera_id, model_name, date_from, date_to, acknowledged)
    total = query.count()
    rows  = query.order_by(Alert.triggered_at.desc()).offset((page - 1) * limit).limit(limit).all()
    return {
        "total": total,
        "page":  page,
        "limit": limit,
        "items": [_alert_dict(a) for a in rows],
    }


@router.post("/", status_code=201)
def create_alert(
    body: AlertCreate,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Internal endpoint — called by the camera worker to log a violation."""
    alert = Alert(**body.model_dump())
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return _alert_dict(alert)


@router.patch("/{alert_id}/acknowledge")
def acknowledge_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    alert = db.get(Alert, alert_id)
    if not alert:
        raise HTTPException(404, "Alert not found")
    if alert.acknowledged:
        return _alert_dict(alert)  # idempotent
    alert.acknowledged    = True
    alert.acknowledged_by = current_user.id
    alert.acknowledged_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(alert)
    return _alert_dict(alert)


@router.get("/export")
def export_alerts_csv(
    camera_id:    Optional[int]  = Query(None),
    model_name:   Optional[str]  = Query(None),
    date_from:    Optional[datetime] = Query(None),
    date_to:      Optional[datetime] = Query(None),
    acknowledged: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Stream filtered alerts as a CSV file download."""
    query = db.query(Alert)
    query = _apply_filters(query, camera_id, model_name, date_from, date_to, acknowledged)
    rows  = query.order_by(Alert.triggered_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "camera_id", "model_name", "violation_type",
        "confidence_score", "triggered_at", "buzzer_activated",
        "acknowledged", "acknowledged_by", "acknowledged_at", "snapshot_path",
    ])
    for a in rows:
        writer.writerow([
            a.id, a.camera_id, a.model_name, a.violation_type,
            round(a.confidence_score, 4), a.triggered_at, a.buzzer_activated,
            a.acknowledged,
            a.acknowledger.username if a.acknowledger else "",
            a.acknowledged_at or "",
            a.snapshot_path or "",
        ])

    output.seek(0)
    filename = f"alerts_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/daily-report.xlsx")
def export_daily_report_xlsx(
    report_date: Optional[date] = Query(None),
    use_dummy_data: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    resolved_date = _resolve_report_date(report_date)
    alerts = get_daily_alerts_query(db, resolved_date).all()
    rows = build_daily_report_rows(
        alerts,
        resolved_date,
        include_dummy_data=use_dummy_data,
    )
    payload = render_daily_report_xlsx(rows, resolved_date)
    filename = build_daily_report_filename(resolved_date, "xlsx")
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.get("/daily-report.pdf")
def export_daily_report_pdf(
    report_date: Optional[date] = Query(None),
    use_dummy_data: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    resolved_date = _resolve_report_date(report_date)
    alerts = get_daily_alerts_query(db, resolved_date).all()
    rows = build_daily_report_rows(
        alerts,
        resolved_date,
        include_dummy_data=use_dummy_data,
    )
    payload = render_daily_report_pdf(rows, resolved_date)
    filename = build_daily_report_filename(resolved_date, "pdf")
    return StreamingResponse(
        io.BytesIO(payload),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/daily-report/whatsapp")
def send_daily_report_whatsapp(
    body: DailyReportWhatsAppRequest = Body(default=DailyReportWhatsAppRequest()),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    resolved_date = _resolve_report_date(body.report_date)
    alerts = get_daily_alerts_query(db, resolved_date).all()
    if not alerts and not body.use_dummy_data:
        raise HTTPException(400, f"No alert data found in DB for {resolved_date.isoformat()}.")
    rows = build_daily_report_rows(
        alerts,
        resolved_date,
        include_dummy_data=body.use_dummy_data,
    )
    if not body.include_pdf and not body.include_excel:
        raise HTTPException(400, "Select at least one file type to send.")

    artifacts = save_report_artifacts(rows, resolved_date, "violations/reports")
    files_to_send = []
    if body.include_pdf:
        files_to_send.append(artifacts["pdf"])
    if body.include_excel:
        files_to_send.append(artifacts["xlsx"])

    try:
        responses = send_documents(
            files_to_send,
            recipient_number=body.to,
            caption_text="AXIS CCTV REPORT",
            filename_stem="AXIS CCTV REPORT",
        )
    except WhatsAppConfigError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc

    return {
        "report_date": resolved_date.isoformat(),
        "row_count": len(rows),
        "files": {key: str(path) for key, path in artifacts.items()},
        "sent": responses,
        "used_dummy_data": body.use_dummy_data,
    }
