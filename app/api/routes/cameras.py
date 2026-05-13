"""
app/api/routes/cameras.py
--------------------------
Camera management endpoints — backed by the `cameras` DB table.

CRUD operations persist to the database. Start/stop operations control live
camera processes via CameraManager without restarting the server.

Endpoints:
  GET    /api/cameras/           List all cameras with live status
  POST   /api/cameras/           Add a new camera
  PUT    /api/cameras/{id}       Update a camera
  DELETE /api/cameras/{id}       Remove a camera (stops process if running)
  POST   /api/cameras/start      Start detection on all cameras
  POST   /api/cameras/stop       Stop all camera processes
  POST   /api/cameras/{id}/start Start a single camera
  POST   /api/cameras/{id}/stop  Stop a single camera
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from typing import Optional

from app.db.database import get_db
from app.db.models import Camera, AIModel, CameraModelAssignment, CameraClassConfig
from app.db.models.camera_model import CameraModel
from app.services.camera_manager import camera_manager
from app.schemas.cameras_schema import CameraCreate, CameraUpdate

router = APIRouter()

_KNOWN_MODEL_TYPES = [
    "helmet_detection", "gloves_detection", "vest_detection",
    "fire_detection", "glasses_detection", "mask_detection",
    "vehicle_detection",
]


def _assign_all_active_models(db: Session, cam_id: int) -> None:
    """
    For a newly created camera:
      1. Create CameraModelAssignment + CameraClassConfig rows for every active AI model
         (controls which weights are loaded and which classes are active).
      2. Create CameraModel rows for every known model type, all enabled by default
         (controls the result-handler filter and is visible/toggleable in the UI).
    """
    # 1 — model weight assignments
    active_models = db.query(AIModel).filter(AIModel.is_active == True).all()
    for model in active_models:
        already = db.query(CameraModelAssignment).filter(
            CameraModelAssignment.camera_id == cam_id,
            CameraModelAssignment.model_id == model.id,
        ).first()
        if already:
            continue
        asgn = CameraModelAssignment(camera_id=cam_id, model_id=model.id, is_enabled=True)
        db.add(asgn)
        db.flush()
        for mc in model.classes:
            db.add(CameraClassConfig(assignment_id=asgn.id, class_id=mc.id, is_active=True))

    # 2 — explicit per-model-type toggles (so UI shows them and they can be toggled)
    for model_type in _KNOWN_MODEL_TYPES:
        already = db.query(CameraModel).filter(
            CameraModel.camera_id == cam_id,
            CameraModel.model_name == model_type,
        ).first()
        if not already:
            db.add(CameraModel(camera_id=cam_id, model_name=model_type, is_enabled=True))




@router.get("/")
def list_cameras():
    """Return all cameras with live stats (fps, violations, active status)."""
    return camera_manager.get_camera_statuses()


@router.get("/metrics")
def camera_metrics():
    """Return server totals plus per-camera runtime resource metrics."""
    return camera_manager.get_resource_metrics()


@router.post("/")
def add_camera(body: CameraCreate, db: Session = Depends(get_db)):
    """Insert a new camera row into the database."""
    try:
        # Clear any aborted transaction state inherited from the connection pool.
        db.rollback()
        cam = Camera(
            name=body.name,
            stream_url=body.stream_url,
            location=body.location,
            is_active=body.is_active,
            ingestion_fps=body.ingestion_fps,
            detection_width=body.detection_width,
            detection_height=body.detection_height,
        )
        db.add(cam)
        db.flush()
        _assign_all_active_models(db, cam.id)
        db.commit()
        db.refresh(cam)
        return {"message": "Camera added", "id": cam.id}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(500, f"Could not add camera: {exc.orig or exc}") from exc


@router.put("/{cam_id}")
def update_camera(cam_id: int, body: CameraUpdate, db: Session = Depends(get_db)):
    """Update any fields of an existing camera."""
    try:
        cam = db.query(Camera).filter(Camera.id == cam_id).first()
        if not cam:
            raise HTTPException(404, "Camera not found")
        for field, value in body.model_dump(exclude_unset=True).items():
            setattr(cam, field, value)
        db.commit()
        return {"message": "Camera updated"}
    except HTTPException:
        raise
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(500, f"Could not update camera: {exc.orig or exc}") from exc


@router.delete("/{cam_id}")
def delete_camera(cam_id: int, db: Session = Depends(get_db)):
    """
    Delete a camera from the database.
    Stops the live process first if it is running.
    Related rows (assignments, buzzers, ROIs, alarm config) are CASCADE deleted.
    Alerts and burglar events retain the row with camera_id SET NULL.
    """
    cam = db.query(Camera).filter(Camera.id == cam_id).first()
    if not cam:
        raise HTTPException(404, "Camera not found")
    if camera_manager.is_running():
        try:
            camera_manager.stop_camera(cam_id)
        except Exception:
            pass
    try:
        db.delete(cam)
        db.commit()
        return {"message": "Camera deleted"}
    except SQLAlchemyError as exc:
        db.rollback()
        raise HTTPException(500, f"Could not delete camera: {exc.orig or exc}") from exc


@router.post("/start")
def start_all():
    """Load cameras and models from DB, then start all detection processes."""
    try:
        camera_manager.start_all()
        return {"message": "Detection started"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/stop")
def stop_all():
    """Signal all camera processes to stop and wait for them to exit."""
    camera_manager.stop_all()
    return {"message": "Detection stopped"}


@router.post("/{cam_id}/start")
def start_camera(cam_id: int):
    """Start detection on a single camera by its DB id."""
    try:
        camera_manager.start_camera(cam_id)
        return {"message": f"Camera {cam_id} started"}
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/{cam_id}/stop")
def stop_camera(cam_id: int):
    """Stop the detection process for a single camera."""
    camera_manager.stop_camera(cam_id)
    return {"message": f"Camera {cam_id} stopped"}
