"""
app/api/routes/cameras.py
--------------------------
Camera management endpoints.

CRUD operates on config.yaml (persisted). Start/stop operations
control live camera threads via CameraManager without restarting the server.

Endpoints:
  GET    /api/cameras/           List all cameras with live status
  POST   /api/cameras/           Add a new camera
  PUT    /api/cameras/{id}       Update a camera's URL or title
  DELETE /api/cameras/{id}       Remove a camera (stops thread if running)
  POST   /api/cameras/start      Start detection on all cameras
  POST   /api/cameras/stop       Stop all camera threads
  POST   /api/cameras/{id}/start Start a single camera
  POST   /api/cameras/{id}/stop  Stop a single camera
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.config import get_config, save_config
from app.services.camera_manager import camera_manager

router = APIRouter()


class CameraUpdate(BaseModel):
    url: str
    title: Optional[str] = ""


@router.get("/")
def list_cameras():
    """Return all cameras with live stats (fps, violations, active status)."""
    return camera_manager.get_camera_statuses()


@router.get("/metrics")
def camera_metrics():
    """Return server totals plus per-camera runtime resource metrics."""
    return camera_manager.get_resource_metrics()


@router.post("/")
def add_camera(body: CameraUpdate):
    """Append a new camera to config.yaml. Does not start it automatically."""
    cfg = get_config()
    cfg["camera_feeds"].append(body.url)
    cfg["camera_titles"].append(body.title or f"Camera {len(cfg['camera_feeds']) - 1}")
    save_config(cfg)
    return {"message": "Camera added", "id": len(cfg["camera_feeds"]) - 1}


@router.put("/{cam_id}")
def update_camera(cam_id: int, body: CameraUpdate):
    """Update the URL and/or title of an existing camera in config.yaml."""
    cfg = get_config()
    feeds = cfg.get("camera_feeds", [])
    titles = cfg.get("camera_titles", [])
    if cam_id >= len(feeds):
        raise HTTPException(404, "Camera not found")
    feeds[cam_id] = body.url
    # Pad titles list if it is shorter than feeds
    while len(titles) <= cam_id:
        titles.append(f"Camera {len(titles)}")
    titles[cam_id] = body.title or titles[cam_id]
    cfg["camera_feeds"] = feeds
    cfg["camera_titles"] = titles
    save_config(cfg)
    return {"message": "Camera updated"}


@router.delete("/{cam_id}")
def delete_camera(cam_id: int):
    """
    Remove a camera from config.yaml.
    If the camera thread is running, it is stopped first.
    """
    cfg = get_config()
    feeds = cfg.get("camera_feeds", [])
    titles = cfg.get("camera_titles", [])
    if cam_id >= len(feeds):
        raise HTTPException(404, "Camera not found")
    # Stop the thread before removing so it doesn't hold a stale RTSP connection
    if camera_manager.is_running():
        try:
            camera_manager.stop_camera(cam_id)
        except Exception:
            pass
    feeds.pop(cam_id)
    if cam_id < len(titles):
        titles.pop(cam_id)
    cfg["camera_feeds"] = feeds
    cfg["camera_titles"] = titles
    save_config(cfg)
    return {"message": "Camera deleted"}


@router.post("/start")
def start_all():
    """
    Load config, load the YOLO model (if not already loaded), and start
    a detection thread for every configured camera.
    """
    try:
        camera_manager.start_all()
        return {"message": "Detection started"}
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/stop")
def stop_all():
    """Signal all camera threads to stop and wait for them to exit."""
    camera_manager.stop_all()
    return {"message": "Detection stopped"}


@router.post("/{cam_id}/start")
def start_camera(cam_id: int):
    """Start detection on a single camera by its config index."""
    try:
        camera_manager.start_camera(cam_id)
        return {"message": f"Camera {cam_id} started"}
    except ValueError as e:
        raise HTTPException(404, str(e))
    except Exception as e:
        raise HTTPException(500, str(e))


@router.post("/{cam_id}/stop")
def stop_camera(cam_id: int):
    """Stop the detection thread for a single camera."""
    camera_manager.stop_camera(cam_id)
    return {"message": f"Camera {cam_id} stopped"}
