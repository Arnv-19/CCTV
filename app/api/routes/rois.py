"""
app/api/routes/rois.py
----------------------
ROI (Region of Interest) CRUD endpoints.

GET    /api/rois/camera/{camera_id}           List ROIs for a camera
POST   /api/rois/camera/{camera_id}           Create ROI
GET    /api/rois/{roi_id}                     Get single ROI
PUT    /api/rois/{roi_id}                     Update ROI (partial)
DELETE /api/rois/{roi_id}                     Delete ROI
PATCH  /api/rois/{roi_id}/toggle              Toggle active state
PUT    /api/rois/camera/{camera_id}/bulk      Atomically replace all ROIs
"""

import uuid
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session
import re

from app.db.database import get_db
from app.db.models import ROI, User
from app.dependencies import get_current_user
from roi_module.geometry import validate_polygon
from roi_module.cache import get_roi_cache
from roi_module.config import roi_config
from app.schemas.roi_schemas import PointNorm, ROIBody, ROIUpdateBody, BulkBody
logger = logging.getLogger(__name__)
router = APIRouter()



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_or_404(db: Session, roi_id: str) -> ROI:
    roi = db.query(ROI).filter(ROI.roi_id == roi_id).first()
    if not roi:
        raise HTTPException(404, f"ROI '{roi_id}' not found")
    return roi


def _validate_points(points: List[PointNorm]) -> None:
    raw = [{"x": p.x, "y": p.y} for p in points]
    ok, reason = validate_polygon(raw)
    if not ok:
        raise HTTPException(422, f"Invalid polygon: {reason}")


def _camera_id_int(camera_id: int | str) -> int:
    try:
        return int(camera_id)
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "camera_id must be numeric") from exc


def _camera_cache_key(camera_id: int | str) -> str:
    return str(_camera_id_int(camera_id))


def _check_limit(db: Session, camera_id: int | str) -> None:
    cam_id = _camera_id_int(camera_id)
    count = db.query(ROI).filter(ROI.camera_id == cam_id).count()
    if count >= roi_config.max_rois_per_camera:
        raise HTTPException(
            409,
            f"Camera '{cam_id}' already has {roi_config.max_rois_per_camera} ROIs (limit reached)"
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/camera/{camera_id}")
def list_camera_rois(
    camera_id: int,
    active_only: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """List all ROIs for a camera."""
    cam_id = _camera_id_int(camera_id)
    q = db.query(ROI).filter(ROI.camera_id == cam_id)
    if active_only:
        q = q.filter(ROI.is_active.is_(True))
    rois = q.order_by(ROI.priority.desc(), ROI.created_at).all()
    return {"camera_id": cam_id, "rois": [r.to_dict() for r in rois], "total": len(rois)}


@router.post("/camera/{camera_id}", status_code=status.HTTP_201_CREATED)
def create_roi(
    camera_id: int,
    body: ROIBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new ROI for a camera."""
    cam_id = _camera_id_int(camera_id)
    _check_limit(db, camera_id)
    _validate_points(body.points_normalized)

    roi = ROI(
        roi_id=str(uuid.uuid4()),
        camera_id=cam_id,
        name=body.name,
        points_normalized=[{"x": p.x, "y": p.y} for p in body.points_normalized],
        is_active=body.is_active,
        color=body.color,
        priority=body.priority,
        camera_width=body.camera_width,
        camera_height=body.camera_height,
        created_by=current_user.username,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(roi)
    db.commit()
    db.refresh(roi)
    get_roi_cache().invalidate(str(cam_id))
    logger.info("ROI created roi_id=%s camera_id=%s by=%s", roi.roi_id, cam_id, current_user.username)
    return roi.to_dict()


@router.get("/{roi_id}")
def get_roi(
    roi_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Get a single ROI."""
    return _get_or_404(db, roi_id).to_dict()


@router.put("/{roi_id}")
def update_roi(
    roi_id: str,
    body: ROIUpdateBody,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Update an ROI (partial — only supplied fields are changed)."""
    roi = _get_or_404(db, roi_id)

    if body.points_normalized is not None:
        _validate_points(body.points_normalized)
        roi.points_normalized = [{"x": p.x, "y": p.y} for p in body.points_normalized]
    if body.name is not None:
        roi.name = body.name
    if body.is_active is not None:
        roi.is_active = body.is_active
    if body.color is not None:
        roi.color = body.color
    if body.priority is not None:
        roi.priority = body.priority
    if body.camera_width is not None:
        roi.camera_width = body.camera_width
    if body.camera_height is not None:
        roi.camera_height = body.camera_height

    roi.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(roi)
    get_roi_cache().invalidate(str(roi.camera_id))
    logger.info("ROI updated roi_id=%s", roi_id)
    return roi.to_dict()


@router.delete("/{roi_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_roi(
    roi_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Delete an ROI."""
    roi = _get_or_404(db, roi_id)
    camera_id = roi.camera_id
    db.delete(roi)
    db.commit()
    get_roi_cache().invalidate(str(camera_id))
    logger.info("ROI deleted roi_id=%s camera_id=%s", roi_id, camera_id)


@router.patch("/{roi_id}/toggle")
def toggle_roi(
    roi_id: str,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Toggle an ROI's active state."""
    roi = _get_or_404(db, roi_id)
    roi.is_active = not roi.is_active
    roi.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(roi)
    get_roi_cache().invalidate(str(roi.camera_id))
    logger.info("ROI toggled roi_id=%s is_active=%s", roi_id, roi.is_active)
    return roi.to_dict()


@router.put("/camera/{camera_id}/bulk")
def bulk_replace_rois(
    camera_id: int,
    body: BulkBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Atomically replace ALL ROIs for a camera."""
    cam_id = _camera_id_int(camera_id)
    if len(body.rois) > roi_config.max_rois_per_camera:
        raise HTTPException(
            409,
            f"Exceeds max_rois_per_camera={roi_config.max_rois_per_camera}"
        )
    for i, r in enumerate(body.rois):
        ok, reason = validate_polygon([{"x": p.x, "y": p.y} for p in r.points_normalized])
        if not ok:
            raise HTTPException(422, f"ROI #{i} '{r.name}': {reason}")

    db.query(ROI).filter(ROI.camera_id == cam_id).delete()
    now = datetime.utcnow()
    new_rois = []
    for r in body.rois:
        roi = ROI(
            roi_id=str(uuid.uuid4()),
            camera_id=cam_id,
            name=r.name,
            points_normalized=[{"x": p.x, "y": p.y} for p in r.points_normalized],
            is_active=r.is_active,
            color=r.color,
            priority=r.priority,
            camera_width=r.camera_width,
            camera_height=r.camera_height,
            created_by=current_user.username,
            created_at=now,
            updated_at=now,
        )
        db.add(roi)
        new_rois.append(roi)

    db.commit()
    for roi in new_rois:
        db.refresh(roi)

    get_roi_cache().invalidate(str(cam_id))
    logger.info("Bulk replaced %d ROIs for camera_id=%s", len(new_rois), cam_id)
    return {"camera_id": cam_id, "rois": [r.to_dict() for r in new_rois], "total": len(new_rois)}
