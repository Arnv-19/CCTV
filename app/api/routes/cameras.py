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
from sqlalchemy.orm import Session
from typing import Optional

from app.db.database import get_db
from app.db.models import Camera
from app.services.camera_manager import camera_manager

router = APIRouter()


class CameraCreate(BaseModel):
    name: str
    stream_url: str
    location: Optional[str] = None
    is_active: bool = True
    ingestion_fps: int = 4
    detection_width: int = 960
    detection_height: int = 720


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    stream_url: Optional[str] = None
    location: Optional[str] = None
    is_active: Optional[bool] = None
    ingestion_fps: Optional[int] = None
    detection_width: Optional[int] = None
    detection_height: Optional[int] = None


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
    db.commit()
    db.refresh(cam)
    return {"message": "Camera added", "id": cam.id}


@router.put("/{cam_id}")
def update_camera(cam_id: int, body: CameraUpdate, db: Session = Depends(get_db)):
    """Update any fields of an existing camera."""
    cam = db.query(Camera).filter(Camera.id == cam_id).first()
    if not cam:
        raise HTTPException(404, "Camera not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(cam, field, value)
    db.commit()
    return {"message": "Camera updated"}


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
    db.delete(cam)
    db.commit()
    return {"message": "Camera deleted"}


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
