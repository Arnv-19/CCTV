"""
app/api/routes/camera_models.py
---------------------------------
Per-camera AI model enable/disable endpoints.

GET   /api/camera-models/{camera_id}                 List model configs for a camera
POST  /api/camera-models/{camera_id}                 Upsert a model entry
PATCH /api/camera-models/{camera_id}/{model_name}    Toggle is_enabled
GET   /api/camera-models/{camera_id}/enabled         Return only enabled model names
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi import Body
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import CameraModel, User
from app.dependencies import get_current_user, require_admin
from app.services.camera_manager import camera_manager
from app.schemas.camera_model_schemas import ModelToggle, ModelPatch, _row_dict
router = APIRouter()




@router.get("/{camera_id}")
def list_camera_models(
    camera_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = db.query(CameraModel).filter(CameraModel.camera_id == camera_id).all()
    return [_row_dict(r) for r in rows]


@router.get("/{camera_id}/enabled")
def enabled_models(
    camera_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """Return just the list of enabled model names for a camera."""
    rows = (
        db.query(CameraModel)
        .filter(CameraModel.camera_id == camera_id, CameraModel.is_enabled == True)
        .all()
    )
    return [r.model_name for r in rows]


@router.post("/{camera_id}")
def upsert_camera_model(
    camera_id: int,
    body: ModelToggle,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Create or update the is_enabled flag for a model on a camera."""
    row = (
        db.query(CameraModel)
        .filter(
            CameraModel.camera_id == camera_id,
            CameraModel.model_name == body.model_name,
        )
        .first()
    )
    if row:
        row.is_enabled = body.is_enabled
        row.updated_at = datetime.utcnow()
    else:
        row = CameraModel(
            camera_id=camera_id,
            model_name=body.model_name,
            is_enabled=body.is_enabled,
        )
        db.add(row)
    db.commit()
    db.refresh(row)

    # Apply model changes immediately for active camera workers.
    try:
        proc = camera_manager.processes.get(camera_id)
        if proc is not None and proc.is_alive():
            camera_manager.start_camera(camera_id)
    except Exception as e:
        print(f"[CameraModels] Warning: could not restart camera {camera_id}: {e}")

    return _row_dict(row)


@router.patch("/{camera_id}/{model_name}")
def toggle_model(
    camera_id: int,
    model_name: str,
    body: ModelPatch | None = Body(default=None),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    row = (
        db.query(CameraModel)
        .filter(
            CameraModel.camera_id == camera_id,
            CameraModel.model_name == model_name,
        )
        .first()
    )
    if not row:
        raise HTTPException(404, f"Model '{model_name}' not configured for camera {camera_id}")

    # Support both forms:
    # - PATCH with no body: toggle (used by frontend)
    # - PATCH with {"is_enabled": ...}: set exact state
    if body is not None and body.is_enabled is not None:
        row.is_enabled = body.is_enabled
    else:
        row.is_enabled = not row.is_enabled
    row.updated_at = datetime.utcnow()
    db.commit()

    # Apply model changes immediately for active camera workers.
    try:
        proc = camera_manager.processes.get(camera_id)
        if proc is not None and proc.is_alive():
            camera_manager.start_camera(camera_id)
    except Exception as e:
        print(f"[CameraModels] Warning: could not restart camera {camera_id}: {e}")

    return _row_dict(row)
