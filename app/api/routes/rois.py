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

logger = logging.getLogger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Request / Response schemas (inline, matching existing buzzer style)
# ---------------------------------------------------------------------------

class PointNorm(BaseModel):
    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)


class ROIBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    points_normalized: List[PointNorm] = Field(..., min_length=3, max_length=200)
    is_active: bool = True
    color: str = Field("#FF5733", pattern=r"^#[0-9A-Fa-f]{6}$")
    priority: int = Field(0, ge=0, le=100)
    camera_width: Optional[int] = None
    camera_height: Optional[int] = None

    @field_validator("name")
    @classmethod
    def name_safe(cls, v: str) -> str:
        if not re.match(r"^[\w\s\-()\[\]]+$", v):
            raise ValueError("Name contains invalid characters")
        return v.strip()


class ROIUpdateBody(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    points_normalized: Optional[List[PointNorm]] = Field(None, min_length=3, max_length=200)
    is_active: Optional[bool] = None
    color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    priority: Optional[int] = Field(None, ge=0, le=100)
    camera_width: Optional[int] = None
    camera_height: Optional[int] = None


class BulkBody(BaseModel):
    rois: List[ROIBody] = Field(..., max_length=50)


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


def _check_limit(db: Session, camera_id: str) -> None:
    count = db.query(ROI).filter(ROI.camera_id == camera_id).count()
    if count >= roi_config.max_rois_per_camera:
        raise HTTPException(
            409,
            f"Camera '{camera_id}' already has {roi_config.max_rois_per_camera} ROIs (limit reached)"
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/camera/{camera_id}")
def list_camera_rois(
    camera_id: str,
    active_only: bool = Query(False),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """List all ROIs for a camera."""
    q = db.query(ROI).filter(ROI.camera_id == camera_id)
    if active_only:
        q = q.filter(ROI.is_active.is_(True))
    rois = q.order_by(ROI.priority.desc(), ROI.created_at).all()
    return {"camera_id": camera_id, "rois": [r.to_dict() for r in rois], "total": len(rois)}


@router.post("/camera/{camera_id}", status_code=status.HTTP_201_CREATED)
def create_roi(
    camera_id: str,
    body: ROIBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new ROI for a camera."""
    _check_limit(db, camera_id)
    _validate_points(body.points_normalized)

    roi = ROI(
        roi_id=str(uuid.uuid4()),
        camera_id=camera_id,
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
    get_roi_cache().invalidate(camera_id)
    logger.info("ROI created roi_id=%s camera_id=%s by=%s", roi.roi_id, camera_id, current_user.username)
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
    get_roi_cache().invalidate(roi.camera_id)
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
    get_roi_cache().invalidate(camera_id)
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
    get_roi_cache().invalidate(roi.camera_id)
    logger.info("ROI toggled roi_id=%s is_active=%s", roi_id, roi.is_active)
    return roi.to_dict()


@router.put("/camera/{camera_id}/bulk")
def bulk_replace_rois(
    camera_id: str,
    body: BulkBody,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Atomically replace ALL ROIs for a camera."""
    if len(body.rois) > roi_config.max_rois_per_camera:
        raise HTTPException(
            409,
            f"Exceeds max_rois_per_camera={roi_config.max_rois_per_camera}"
        )
    for i, r in enumerate(body.rois):
        ok, reason = validate_polygon([{"x": p.x, "y": p.y} for p in r.points_normalized])
        if not ok:
            raise HTTPException(422, f"ROI #{i} '{r.name}': {reason}")

    db.query(ROI).filter(ROI.camera_id == camera_id).delete()
    now = datetime.utcnow()
    new_rois = []
    for r in body.rois:
        roi = ROI(
            roi_id=str(uuid.uuid4()),
            camera_id=camera_id,
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

    get_roi_cache().invalidate(camera_id)
    logger.info("Bulk replaced %d ROIs for camera_id=%s", len(new_rois), camera_id)
    return {"camera_id": camera_id, "rois": [r.to_dict() for r in new_rois], "total": len(new_rois)}
