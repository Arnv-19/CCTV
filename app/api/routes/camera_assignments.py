"""
app/api/routes/camera_assignments.py
--------------------------------------
Manage which AI models run on which cameras, and which detection classes are active.

Endpoints:
  GET    /api/camera-assignments/?camera_id=1              All assignments for a camera
  POST   /api/camera-assignments/                          Assign a model to a camera
  PATCH  /api/camera-assignments/{id}                      Enable/disable or override threshold
  DELETE /api/camera-assignments/{id}                      Remove assignment
  GET    /api/camera-assignments/{id}/classes              Class configs for one assignment
  PATCH  /api/camera-assignments/{id}/classes/{class_id}   Toggle is_active for one class
  POST   /api/camera-assignments/{id}/classes/bulk         Bulk-set is_active for many classes
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing import Optional

from app.db.database import get_db
from app.db.models import (
    Camera, AIModel,
    CameraModelAssignment, CameraClassConfig, ModelClass, User,
)
from app.dependencies import get_current_user, require_admin

router = APIRouter()


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class AssignmentCreate(BaseModel):
    camera_id: int
    model_id: int
    is_enabled: bool = True
    confidence_threshold: Optional[float] = None


class AssignmentPatch(BaseModel):
    is_enabled: Optional[bool] = None
    confidence_threshold: Optional[float] = None


class ClassConfigPatch(BaseModel):
    is_active: bool


class BulkClassConfigItem(BaseModel):
    class_id: int
    is_active: bool


# ── Serialisers ───────────────────────────────────────────────────────────────

def _config_dict(cc: CameraClassConfig) -> dict:
    mc = cc.model_class
    return {
        "id":          cc.id,
        "class_id":    cc.class_id,
        "class_name":  mc.class_name if mc else None,
        "class_role":  mc.class_role if mc else None,
        "class_index": mc.class_index if mc else None,
        "is_active":   cc.is_active,
        "updated_at":  cc.updated_at,
    }


def _assignment_dict(a: CameraModelAssignment, include_classes: bool = False) -> dict:
    d = {
        "id":                   a.id,
        "camera_id":            a.camera_id,
        "model_id":             a.model_id,
        "model_name":           a.model.name if a.model else None,
        "model_display_name":   a.model.display_name if a.model else None,
        "weight_path":          a.model.weight_path if a.model else None,
        "is_enabled":           a.is_enabled,
        "confidence_threshold": a.confidence_threshold,
        "assigned_at":          a.assigned_at,
    }
    if include_classes:
        d["class_configs"] = [_config_dict(cc) for cc in a.class_configs]
    return d


# ── Assignment endpoints ──────────────────────────────────────────────────────

@router.get("/")
def list_assignments(
    camera_id: Optional[int] = Query(None, description="Filter by camera DB id"),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """List all model assignments, optionally filtered to one camera."""
    q = db.query(CameraModelAssignment)
    if camera_id is not None:
        q = q.filter(CameraModelAssignment.camera_id == camera_id)
    return [_assignment_dict(a, include_classes=True) for a in q.order_by(CameraModelAssignment.id).all()]


@router.post("/")
def create_assignment(
    body: AssignmentCreate,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    Assign a model to a camera.

    Automatically creates a CameraClassConfig row for every class the model has
    (all active by default), giving immediate per-class control via the
    PATCH /classes/{class_id} endpoint.
    """
    if not db.query(Camera).filter(Camera.id == body.camera_id).first():
        raise HTTPException(404, f"Camera {body.camera_id} not found")
    model = db.query(AIModel).filter(AIModel.id == body.model_id).first()
    if not model:
        raise HTTPException(404, f"Model {body.model_id} not found")
    if db.query(CameraModelAssignment).filter(
        CameraModelAssignment.camera_id == body.camera_id,
        CameraModelAssignment.model_id  == body.model_id,
    ).first():
        raise HTTPException(409, "This model is already assigned to this camera")

    asgn = CameraModelAssignment(
        camera_id=body.camera_id,
        model_id=body.model_id,
        is_enabled=body.is_enabled,
        confidence_threshold=body.confidence_threshold,
    )
    db.add(asgn)
    db.flush()   # populate asgn.id before creating class configs

    for mc in model.classes:
        db.add(CameraClassConfig(
            assignment_id=asgn.id,
            class_id=mc.id,
            is_active=True,
        ))

    db.commit()
    db.refresh(asgn)
    return _assignment_dict(asgn, include_classes=True)


@router.patch("/{assignment_id}")
def update_assignment(
    assignment_id: int,
    body: AssignmentPatch,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Enable/disable a model on a camera, or override the confidence threshold."""
    asgn = db.query(CameraModelAssignment).filter(
        CameraModelAssignment.id == assignment_id
    ).first()
    if not asgn:
        raise HTTPException(404, "Assignment not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(asgn, field, value)
    db.commit()
    return _assignment_dict(asgn, include_classes=True)


@router.delete("/{assignment_id}")
def delete_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    Remove a model from a camera.
    CASCADE deletes all CameraClassConfig rows for this assignment.
    """
    asgn = db.query(CameraModelAssignment).filter(
        CameraModelAssignment.id == assignment_id
    ).first()
    if not asgn:
        raise HTTPException(404, "Assignment not found")
    db.delete(asgn)
    db.commit()
    return {"message": "Assignment deleted"}


# ── Class-config endpoints ────────────────────────────────────────────────────

@router.get("/{assignment_id}/classes")
def list_class_configs(
    assignment_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """List all class configs (active/inactive) for one camera-model assignment."""
    asgn = db.query(CameraModelAssignment).filter(
        CameraModelAssignment.id == assignment_id
    ).first()
    if not asgn:
        raise HTTPException(404, "Assignment not found")
    return [_config_dict(cc) for cc in asgn.class_configs]


@router.patch("/{assignment_id}/classes/{class_id}")
def toggle_class_config(
    assignment_id: int,
    class_id: int,
    body: ClassConfigPatch,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Set is_active for a single class on one camera-model assignment."""
    cc = db.query(CameraClassConfig).filter(
        CameraClassConfig.assignment_id == assignment_id,
        CameraClassConfig.class_id == class_id,
    ).first()
    if not cc:
        raise HTTPException(404, "Class config not found")
    cc.is_active = body.is_active
    db.commit()
    return _config_dict(cc)


@router.post("/{assignment_id}/classes/bulk")
def bulk_update_class_configs(
    assignment_id: int,
    body: list[BulkClassConfigItem],
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    Set is_active for multiple classes in one call.
    Creates the config row if it doesn't exist yet
    (handles classes added to a model after the assignment was created).
    """
    if not db.query(CameraModelAssignment).filter(
        CameraModelAssignment.id == assignment_id
    ).first():
        raise HTTPException(404, "Assignment not found")

    result = []
    for item in body:
        cc = db.query(CameraClassConfig).filter(
            CameraClassConfig.assignment_id == assignment_id,
            CameraClassConfig.class_id == item.class_id,
        ).first()
        if cc:
            cc.is_active = item.is_active
        else:
            cc = CameraClassConfig(
                assignment_id=assignment_id,
                class_id=item.class_id,
                is_active=item.is_active,
            )
            db.add(cc)
        db.flush()
        result.append(_config_dict(cc))

    db.commit()
    return result
