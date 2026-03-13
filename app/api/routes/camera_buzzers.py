"""
app/api/routes/camera_buzzers.py
---------------------------------
Camera ↔ Buzzer assignment endpoints.

GET    /api/camera-buzzers/{camera_id}            List buzzers assigned to a camera
POST   /api/camera-buzzers/{camera_id}/{buzzer_id} Assign a buzzer to a camera
DELETE /api/camera-buzzers/{camera_id}/{buzzer_id} Unassign a buzzer from a camera
PUT    /api/camera-buzzers/{camera_id}            Replace the full buzzer set for a camera
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Buzzer, CameraBuzzer, User
from app.dependencies import get_current_user, require_admin

router = APIRouter()


def _assignment_dict(cb: CameraBuzzer) -> dict:
    return {
        "id":          cb.id,
        "camera_id":   cb.camera_id,
        "buzzer_id":   cb.buzzer_id,
        "buzzer_name": cb.buzzer.name if cb.buzzer else None,
        "assigned_at": cb.assigned_at,
    }


@router.get("/{camera_id}")
def list_camera_buzzers(
    camera_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    rows = (
        db.query(CameraBuzzer)
        .filter(CameraBuzzer.camera_id == camera_id)
        .all()
    )
    return [_assignment_dict(r) for r in rows]


@router.post("/{camera_id}/{buzzer_id}", status_code=201)
def assign_buzzer(
    camera_id: int,
    buzzer_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    if not db.get(Buzzer, buzzer_id):
        raise HTTPException(404, "Buzzer not found")
    existing = (
        db.query(CameraBuzzer)
        .filter(CameraBuzzer.camera_id == camera_id, CameraBuzzer.buzzer_id == buzzer_id)
        .first()
    )
    if existing:
        return _assignment_dict(existing)  # idempotent
    cb = CameraBuzzer(camera_id=camera_id, buzzer_id=buzzer_id)
    db.add(cb)
    db.commit()
    db.refresh(cb)
    return _assignment_dict(cb)


@router.delete("/{camera_id}/{buzzer_id}")
def unassign_buzzer(
    camera_id: int,
    buzzer_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    cb = (
        db.query(CameraBuzzer)
        .filter(CameraBuzzer.camera_id == camera_id, CameraBuzzer.buzzer_id == buzzer_id)
        .first()
    )
    if not cb:
        raise HTTPException(404, "Assignment not found")
    db.delete(cb)
    db.commit()
    return {"message": "Buzzer unassigned"}


class BulkAssign(BaseModel):
    buzzer_ids: List[int]


@router.put("/{camera_id}")
def set_camera_buzzers(
    camera_id: int,
    body: BulkAssign,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Replace the full buzzer assignment for a camera in one call."""
    # Validate all buzzer IDs exist
    for bid in body.buzzer_ids:
        if not db.get(Buzzer, bid):
            raise HTTPException(404, f"Buzzer {bid} not found")

    # Remove current assignments
    db.query(CameraBuzzer).filter(CameraBuzzer.camera_id == camera_id).delete()

    # Insert new ones
    for bid in body.buzzer_ids:
        db.add(CameraBuzzer(camera_id=camera_id, buzzer_id=bid))

    db.commit()
    rows = db.query(CameraBuzzer).filter(CameraBuzzer.camera_id == camera_id).all()
    return [_assignment_dict(r) for r in rows]
