"""
app/api/routes/config_routes.py
--------------------------------
Existing configuration endpoints, now backed by PostgreSQL.

GET   /api/config/    Return the Configuration page payload from DB
PATCH /api/config/    Persist Configuration page changes to DB

This route keeps the old API path but stops using config.yaml as the primary
store. Legacy config.yaml values are only used once to bootstrap older
deployments into the database when needed.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import get_config
from app.db.database import get_db
from app.db.models import AIModel, AppConfig, Camera
from app.schemas.config_schemas import ConfigPageCamera, ConfigUpdate

router = APIRouter()


MODEL_SLOT_SPECS = {
    "model_path": {
        "name": "main_model",
        "display_name": "Main Detection Model",
        "description": "Primary detection model configured from the Configuration page.",
    },
    "person_model_path": {
        "name": "person_model",
        "display_name": "Person Model",
        "description": "Person/burglar model configured from the Configuration page.",
    },
    "gloves_model_path": {
        "name": "gloves_model",
        "display_name": "Gloves Model",
        "description": "Gloves detection model configured from the Configuration page.",
    },
    "ppe_model_path": {
        "name": "ppe_model",
        "display_name": "PPE Model",
        "description": "Legacy PPE model path configured from the Configuration page.",
    },
}


def _camera_dict(cam: Camera) -> dict:
    return {
        "id": cam.id,
        "name": cam.name,
        "stream_url": cam.stream_url,
        "location": cam.location,
        "is_active": cam.is_active,
        "ingestion_fps": cam.ingestion_fps,
        "detection_width": cam.detection_width,
        "detection_height": cam.detection_height,
    }


def _get_or_create_app_config(db: Session) -> AppConfig:
    row = db.query(AppConfig).filter(AppConfig.id == 1).first()
    if row is not None:
        return row

    # One-time bootstrap for old deployments so existing values are preserved.
    legacy = get_config()
    row = AppConfig(
        id=1,
        confidence_threshold=legacy.get("confidence_threshold", 0.25),
        alarm_cooldown_sec=legacy.get("alarm_cooldown_sec", 10),
        burglar_test_sound=legacy.get("burglar_test_sound", False),
        esp_ip=legacy.get("esp_ip", ""),
        use_wifi=legacy.get("use_wifi", False),
        alarm_transport=legacy.get("alarm_transport"),
        alarm_http_token=legacy.get("alarm_http_token", ""),
    )
    db.add(row)
    db.flush()
    return row


def _read_model_slot(db: Session, slot_key: str) -> str:
    spec = MODEL_SLOT_SPECS[slot_key]
    row = (
        db.query(AIModel)
        .filter(AIModel.name == spec["name"])
        .order_by(AIModel.id)
        .first()
    )
    return row.weight_path if row and row.weight_path else ""


def _upsert_model_slot(
    db: Session,
    slot_key: str,
    weight_path: str | None,
    confidence_threshold: float | None,
):
    if weight_path is None:
        return

    spec = MODEL_SLOT_SPECS[slot_key]
    path = weight_path.strip()
    if not path:
        return

    row = (
        db.query(AIModel)
        .filter(AIModel.name == spec["name"])
        .order_by(AIModel.id)
        .first()
    )
    if row is None:
        row = AIModel(
            name=spec["name"],
            display_name=spec["display_name"],
            weight_path=path,
            model_type="yolov8",
            confidence_threshold=confidence_threshold or 0.25,
            description=spec["description"],
            is_active=True,
        )
        db.add(row)
        return

    row.weight_path = path
    row.is_active = True
    if confidence_threshold is not None:
        row.confidence_threshold = confidence_threshold
    if not row.display_name:
        row.display_name = spec["display_name"]
    if not row.description:
        row.description = spec["description"]


def _bootstrap_cameras_from_legacy_if_needed(db: Session):
    if db.query(Camera).first() is not None:
        return

    legacy = get_config()
    feeds = legacy.get("camera_feeds") or []
    titles = legacy.get("camera_titles") or []
    if not feeds:
        return

    for index, feed in enumerate(feeds, start=1):
        if feed is None:
            continue
        if isinstance(feed, str) and not feed.strip():
            continue
        db.add(Camera(
            name=titles[index - 1] if index - 1 < len(titles) and titles[index - 1] else f"Camera {index}",
            stream_url=str(feed),
            location=None,
            is_active=True,
            ingestion_fps=legacy.get("ingestion_fps", 4),
            detection_width=legacy.get("detection_frame_width", 640),
            detection_height=legacy.get("detection_frame_height", 480),
        ))
    db.flush()


def _bootstrap_model_slots_from_legacy_if_needed(db: Session, app_cfg: AppConfig):
    legacy = get_config()
    for slot_key in MODEL_SLOT_SPECS:
        if _read_model_slot(db, slot_key):
            continue
        _upsert_model_slot(db, slot_key, legacy.get(slot_key), app_cfg.confidence_threshold)


def _serialize_config(db: Session) -> dict:
    app_cfg = _get_or_create_app_config(db)
    _bootstrap_cameras_from_legacy_if_needed(db)
    _bootstrap_model_slots_from_legacy_if_needed(db, app_cfg)
    db.commit()

    cameras = db.query(Camera).order_by(Camera.id).all()
    return {
        "cameras": [_camera_dict(cam) for cam in cameras],
        "camera_feeds": [cam.stream_url for cam in cameras],
        "camera_titles": [cam.name for cam in cameras],
        "model_path": _read_model_slot(db, "model_path"),
        "person_model_path": _read_model_slot(db, "person_model_path"),
        "gloves_model_path": _read_model_slot(db, "gloves_model_path"),
        "ppe_model_path": _read_model_slot(db, "ppe_model_path"),
        "confidence_threshold": app_cfg.confidence_threshold,
        "alarm_cooldown_sec": app_cfg.alarm_cooldown_sec,
        "burglar_test_sound": app_cfg.burglar_test_sound,
        "esp_ip": app_cfg.esp_ip,
        "use_wifi": app_cfg.use_wifi,
        "alarm_transport": app_cfg.alarm_transport,
        "alarm_http_token": app_cfg.alarm_http_token,
    }


def _normalize_cameras(body: ConfigUpdate) -> list[ConfigPageCamera]:
    if body.cameras is not None:
        return body.cameras

    feeds = body.camera_feeds or []
    titles = body.camera_titles or []
    cameras: list[ConfigPageCamera] = []
    for index, feed in enumerate(feeds, start=1):
        cameras.append(ConfigPageCamera(
            id=None,
            name=titles[index - 1] if index - 1 < len(titles) and titles[index - 1] else f"Camera {index}",
            stream_url=feed,
        ))
    return cameras


@router.get("/")
def get_full_config(db: Session = Depends(get_db)):
    """Return the full configuration payload from PostgreSQL."""
    return _serialize_config(db)


@router.patch("/")
def update_config(body: ConfigUpdate, db: Session = Depends(get_db)):
    """
    Persist the configuration payload into PostgreSQL using the existing API.
    """
    app_cfg = _get_or_create_app_config(db)
    existing_by_id = {cam.id: cam for cam in db.query(Camera).all()}
    seen_ids: set[int] = set()

    cameras = _normalize_cameras(body)
    if body.cameras is not None or body.camera_feeds is not None or body.camera_titles is not None:
        for index, cam_body in enumerate(cameras, start=1):
            raw_name = (cam_body.name or "").strip()
            raw_url = cam_body.stream_url
            url = raw_url.strip() if isinstance(raw_url, str) else raw_url

            is_blank_row = (not raw_name) and (
                (isinstance(url, str) and not url) or url is None
            )
            if is_blank_row:
                continue

            if isinstance(url, str) and not url:
                raise HTTPException(400, f"Camera row {index} is missing stream_url")

            name = raw_name or f"Camera {index}"

            if cam_body.id is not None:
                cam = existing_by_id.get(cam_body.id)
                if cam is None:
                    raise HTTPException(404, f"Camera {cam_body.id} not found")
            else:
                cam = Camera()
                db.add(cam)

            cam.name = name
            cam.stream_url = str(url)
            cam.location = cam_body.location
            cam.is_active = cam_body.is_active
            cam.ingestion_fps = cam_body.ingestion_fps
            cam.detection_width = cam_body.detection_width
            cam.detection_height = cam_body.detection_height
            db.flush()
            seen_ids.add(cam.id)

        for cam_id, cam in existing_by_id.items():
            if cam_id not in seen_ids:
                db.delete(cam)

    for slot_key in MODEL_SLOT_SPECS:
        _upsert_model_slot(db, slot_key, getattr(body, slot_key), body.confidence_threshold)

    if body.confidence_threshold is not None:
        app_cfg.confidence_threshold = body.confidence_threshold
    if body.alarm_cooldown_sec is not None:
        app_cfg.alarm_cooldown_sec = body.alarm_cooldown_sec
    if body.burglar_test_sound is not None:
        app_cfg.burglar_test_sound = body.burglar_test_sound
    if body.esp_ip is not None:
        app_cfg.esp_ip = body.esp_ip
    if body.use_wifi is not None:
        app_cfg.use_wifi = body.use_wifi
    if body.alarm_transport is not None:
        app_cfg.alarm_transport = body.alarm_transport
    if body.alarm_http_token is not None:
        app_cfg.alarm_http_token = body.alarm_http_token

    db.commit()
    return {"message": "Config updated", "config": _serialize_config(db)}
