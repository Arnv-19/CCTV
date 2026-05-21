"""
ROI Service Layer
=================
Business logic for ROI CRUD operations. All DB I/O is funnelled through here.
The service layer owns cache invalidation so routes stay thin.
"""

from __future__ import annotations

import uuid
import logging
from datetime import datetime
from typing import List, Optional

from sqlalchemy.orm import Session

from .cache import get_roi_cache
from .config import roi_config
from .exceptions import ROILimitExceededError, ROINotFoundError, InvalidPolygonError
from .geometry import validate_polygon
from .models import ROI
from .schemas import ROICreate, ROIUpdate

logger = logging.getLogger(__name__)


def _camera_id_int(camera_id: int | str) -> int:
    try:
        return int(camera_id)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"camera_id must be numeric, got {camera_id!r}") from exc


def _camera_cache_key(camera_id: int | str) -> str:
    return str(_camera_id_int(camera_id))


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

def get_camera_rois(
    db: Session,
    camera_id: int | str,
    active_only: bool = False,
) -> List[ROI]:
    """Return ROIs for a camera, ordered by priority desc then created_at asc."""
    cam_id = _camera_id_int(camera_id)
    q = db.query(ROI).filter(ROI.camera_id == cam_id)
    if active_only:
        q = q.filter(ROI.is_active.is_(True))
    return q.order_by(ROI.priority.desc(), ROI.created_at).all()


def get_camera_rois_cached(db: Session, camera_id: int | str) -> List[dict]:
    """
    Return active ROIs as dicts, served from cache when possible.
    Used in the hot detection-filtering path.
    """
    cache = get_roi_cache()
    cache_key = _camera_cache_key(camera_id)
    hit = cache.get(cache_key)
    if hit is not None:
        return hit

    rois = get_camera_rois(db, camera_id, active_only=True)
    dicts = [r.to_dict() for r in rois]
    cache.set(cache_key, dicts)
    return dicts


def get_roi_by_id(db: Session, roi_id: str) -> ROI:
    roi = db.query(ROI).filter(ROI.roi_id == roi_id).first()
    if roi is None:
        raise ROINotFoundError(roi_id)
    return roi


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

def create_roi(
    db: Session,
    camera_id: int | str,
    data: ROICreate,
    created_by: Optional[str] = None,
) -> ROI:
    cam_id = _camera_id_int(camera_id)
    count = db.query(ROI).filter(ROI.camera_id == cam_id).count()
    if count >= roi_config.max_rois_per_camera:
        raise ROILimitExceededError(str(cam_id), roi_config.max_rois_per_camera)

    if len(data.points_normalized) > roi_config.max_points_per_roi:
        raise InvalidPolygonError(f"Exceeds max_points_per_roi={roi_config.max_points_per_roi}")

    valid, reason = validate_polygon([p.model_dump() for p in data.points_normalized])
    if not valid:
        raise InvalidPolygonError(reason)

    roi = ROI(
        roi_id=str(uuid.uuid4()),
        camera_id=cam_id,
        name=data.name,
        points_normalized=[{"x": p.x, "y": p.y} for p in data.points_normalized],
        is_active=data.is_active,
        color=data.color,
        priority=data.priority,
        camera_width=data.camera_width,
        camera_height=data.camera_height,
        created_by=created_by,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(roi)
    db.commit()
    db.refresh(roi)

    get_roi_cache().invalidate(str(cam_id))
    logger.info("ROI created roi_id=%s camera_id=%s by=%s", roi.roi_id, cam_id, created_by)
    return roi


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

def update_roi(db: Session, roi_id: str, data: ROIUpdate) -> ROI:
    roi = get_roi_by_id(db, roi_id)

    if data.points_normalized is not None:
        if len(data.points_normalized) > roi_config.max_points_per_roi:
            raise InvalidPolygonError(
                f"Exceeds max_points_per_roi={roi_config.max_points_per_roi}"
            )
        valid, reason = validate_polygon([p.model_dump() for p in data.points_normalized])
        if not valid:
            raise InvalidPolygonError(reason)
        roi.points_normalized = [{"x": p.x, "y": p.y} for p in data.points_normalized]

    if data.name is not None:
        roi.name = data.name
    if data.is_active is not None:
        roi.is_active = data.is_active
    if data.color is not None:
        roi.color = data.color
    if data.priority is not None:
        roi.priority = data.priority
    if data.camera_width is not None:
        roi.camera_width = data.camera_width
    if data.camera_height is not None:
        roi.camera_height = data.camera_height

    roi.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(roi)

    get_roi_cache().invalidate(str(roi.camera_id))
    logger.info("ROI updated roi_id=%s", roi_id)
    return roi


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

def delete_roi(db: Session, roi_id: str) -> None:
    roi = get_roi_by_id(db, roi_id)
    camera_id = roi.camera_id
    db.delete(roi)
    db.commit()
    get_roi_cache().invalidate(str(camera_id))
    logger.info("ROI deleted roi_id=%s camera_id=%s", roi_id, camera_id)


# ---------------------------------------------------------------------------
# Toggle
# ---------------------------------------------------------------------------

def toggle_roi(db: Session, roi_id: str) -> ROI:
    roi = get_roi_by_id(db, roi_id)
    roi.is_active = not roi.is_active
    roi.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(roi)
    get_roi_cache().invalidate(str(roi.camera_id))
    logger.info(
        "ROI toggled roi_id=%s -> is_active=%s", roi_id, roi.is_active
    )
    return roi


# ---------------------------------------------------------------------------
# Bulk replace
# ---------------------------------------------------------------------------

def bulk_replace_rois(
    db: Session,
    camera_id: int | str,
    rois_data: List[ROICreate],
    created_by: Optional[str] = None,
) -> List[ROI]:
    """
    Atomically replace all ROIs for *camera_id* with *rois_data*.
    Validates all polygons before touching the database.
    """
    cam_id = _camera_id_int(camera_id)
    if len(rois_data) > roi_config.max_rois_per_camera:
        raise ROILimitExceededError(str(cam_id), roi_config.max_rois_per_camera)

    for i, data in enumerate(rois_data):
        valid, reason = validate_polygon([p.model_dump() for p in data.points_normalized])
        if not valid:
            raise InvalidPolygonError(f"ROI #{i} '{data.name}': {reason}")

    db.query(ROI).filter(ROI.camera_id == cam_id).delete()

    new_rois: List[ROI] = []
    now = datetime.utcnow()
    for data in rois_data:
        roi = ROI(
            roi_id=str(uuid.uuid4()),
            camera_id=cam_id,
            name=data.name,
            points_normalized=[{"x": p.x, "y": p.y} for p in data.points_normalized],
            is_active=data.is_active,
            color=data.color,
            priority=data.priority,
            camera_width=data.camera_width,
            camera_height=data.camera_height,
            created_by=created_by,
            created_at=now,
            updated_at=now,
        )
        db.add(roi)
        new_rois.append(roi)

    db.commit()
    for roi in new_rois:
        db.refresh(roi)

    get_roi_cache().invalidate(str(cam_id))
    logger.info(
        "Bulk replaced %d ROIs for camera_id=%s by=%s",
        len(new_rois), cam_id, created_by,
    )
    return new_rois
