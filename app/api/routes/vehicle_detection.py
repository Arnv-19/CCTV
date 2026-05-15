"""
app/api/routes/vehicle_detection.py
-------------------------------------
Vehicle detection event endpoints.

GET  /api/vehicle-detections/summary   Dashboard stats
GET  /api/vehicle-detections/          List events (paginated + filters)
GET  /api/vehicle-detections/export    Download filtered events as CSV
"""

import csv
import io
from datetime import date, datetime, time, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import User
from app.db.models.vehicle_detection_event import VehicleDetectionEvent
from app.dependencies import get_current_user
from app.schemas.vehicle_schemas import _event_dict

router = APIRouter()

_IST_TZ = ZoneInfo("Asia/Kolkata")


def _now_ist_naive() -> datetime:
    return datetime.now(_IST_TZ).replace(tzinfo=None)


def _to_start_dt(d: Optional[date]) -> Optional[datetime]:
    return datetime.combine(d, time.min) if d else None


def _to_end_dt(d: Optional[date]) -> Optional[datetime]:
    return datetime.combine(d, time.max) if d else None


def _apply_filters(query, camera_id, plate_number, vehicle_class, date_from, date_to):
    if camera_id     is not None:
        query = query.filter(VehicleDetectionEvent.camera_id == camera_id)
    if plate_number  is not None:
        query = query.filter(VehicleDetectionEvent.plate_number.ilike(f"%{plate_number}%"))
    if vehicle_class is not None:
        query = query.filter(VehicleDetectionEvent.vehicle_class.ilike(f"%{vehicle_class}%"))
    if date_from     is not None:
        query = query.filter(VehicleDetectionEvent.triggered_at >= date_from)
    if date_to       is not None:
        query = query.filter(VehicleDetectionEvent.triggered_at <= date_to)
    return query


# ── Routes ────────────────────────────────────────────────────────────────────

@router.get("/summary")
def get_summary(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    today_start = _now_ist_naive().replace(hour=0, minute=0, second=0, microsecond=0)

    total_today = db.query(func.count(VehicleDetectionEvent.id)).filter(
        VehicleDetectionEvent.triggered_at >= today_start
    ).scalar()

    top_cam = (
        db.query(
            VehicleDetectionEvent.camera_id,
            func.count(VehicleDetectionEvent.id).label("cnt"),
        )
        .filter(VehicleDetectionEvent.triggered_at >= today_start)
        .group_by(VehicleDetectionEvent.camera_id)
        .order_by(func.count(VehicleDetectionEvent.id).desc())
        .first()
    )

    top_class = (
        db.query(
            VehicleDetectionEvent.vehicle_class,
            func.count(VehicleDetectionEvent.id).label("cnt"),
        )
        .filter(VehicleDetectionEvent.triggered_at >= today_start)
        .group_by(VehicleDetectionEvent.vehicle_class)
        .order_by(func.count(VehicleDetectionEvent.id).desc())
        .first()
    )

    return {
        "today_count":       total_today or 0,
        "top_camera_id":     top_cam.camera_id if top_cam else None,
        "top_camera_count":  top_cam.cnt if top_cam else 0,
        "top_vehicle_class": top_class.vehicle_class if top_class else None,
        "top_class_count":   top_class.cnt if top_class else 0,
    }


@router.get("/")
def list_events(
    camera_id:     Optional[int]  = Query(None),
    plate_number:  Optional[str]  = Query(None),
    vehicle_class: Optional[str]  = Query(None),
    date_from:     Optional[date] = Query(None),
    date_to:       Optional[date] = Query(None),
    page:  int = Query(default=1, ge=1),
    limit: int = Query(default=50, ge=1, le=500),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = _apply_filters(
        db.query(VehicleDetectionEvent),
        camera_id, plate_number, vehicle_class,
        _to_start_dt(date_from), _to_end_dt(date_to),
    )
    total = query.count()
    rows  = (
        query
        .order_by(VehicleDetectionEvent.triggered_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
        .all()
    )
    return {
        "total": total,
        "page":  page,
        "limit": limit,
        "items": [_event_dict(e) for e in rows],
    }


@router.get("/export")
def export_csv(
    camera_id:     Optional[int]  = Query(None),
    plate_number:  Optional[str]  = Query(None),
    vehicle_class: Optional[str]  = Query(None),
    date_from:     Optional[date] = Query(None),
    date_to:       Optional[date] = Query(None),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    query = _apply_filters(
        db.query(VehicleDetectionEvent),
        camera_id, plate_number, vehicle_class,
        _to_start_dt(date_from), _to_end_dt(date_to),
    )
    rows = query.order_by(VehicleDetectionEvent.triggered_at.desc()).all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "id", "camera_id", "vehicle_class", "confidence_score",
        "plate_number", "plate_confidence", "triggered_at",
        "snapshot_path", "plate_snapshot_path",
    ])
    for e in rows:
        writer.writerow([
            e.id, e.camera_id, e.vehicle_class, round(e.confidence_score, 4),
            e.plate_number or "",
            round(e.plate_confidence, 4) if e.plate_confidence else "",
            e.triggered_at,
            e.snapshot_path or "",
            e.plate_snapshot_path or "",
        ])

    output.seek(0)
    filename = f"vehicle_detections_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.csv"
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
