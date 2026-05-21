"""
app/services/camera_db_helpers.py
-----------------------------------
DB query helpers used by CameraManager at startup and on single-camera restarts.

All functions do their own DB session management so they can be called from
any thread without a pre-existing session.  Each returns plain dicts/lists so
the values are picklable (passed to mp.Process workers).

Every function silently returns a safe empty value on failure so the caller
can fall back to config.yaml without crashing.
"""

from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_local_path(path_like: str) -> Path:
    p = Path(path_like)
    return p if p.is_absolute() else _PROJECT_ROOT / p


def load_cameras_from_db() -> list[dict]:
    """
    Return all active cameras from the `cameras` table as plain dicts:
        {id, name, stream_url, ingestion_fps, detection_width, detection_height}

    Returns [] when the table is empty or DB is unavailable.
    Caller falls back to config.yaml in that case.
    """
    try:
        from app.db.database import SessionLocal, ensure_database_connected
        from app.db.models import Camera

        ensure_database_connected()
        with SessionLocal() as db:
            rows = (
                db.query(Camera)
                .filter(Camera.is_active == True)
                .order_by(Camera.id)
                .all()
            )
            cameras = [
                {
                    "id":               cam.id,
                    "name":             cam.name,
                    "stream_url":       cam.stream_url,
                    "ingestion_fps":    cam.ingestion_fps,
                    "detection_width":  cam.detection_width,
                    "detection_height": cam.detection_height,
                }
                for cam in rows
            ]
            if cameras:
                print(f"[CameraManager] Loaded {len(cameras)} camera(s) from DB.")
            return cameras
    except Exception as e:
        print(f"[CameraManager] Warning: could not load cameras from DB: {e}")
        return []


def load_model_config_for_camera(cam_id: int) -> dict | None:
    """
    Return the model configuration for one camera from camera_model_assignments.

    Return dict:
        {main_model_path, gloves_model_path, person_model_path,
         confidence_threshold, violation_classes, safe_classes}

    Returns None when no assignment exists — caller falls back to config.yaml.

    Model role is derived from ai_models.name:
        "gloves" in name  → gloves model
        "person"/"burglar" in name → burglar person model
        anything else → main / PPE model
    """
    try:
        from app.db.database import SessionLocal, ensure_database_connected
        from app.db.models import CameraModelAssignment, CameraClassConfig

        ensure_database_connected()
        with SessionLocal() as db:
            assignments = (
                db.query(CameraModelAssignment)
                .filter(
                    CameraModelAssignment.camera_id == cam_id,
                    CameraModelAssignment.is_enabled == True,
                )
                .all()
            )
            if not assignments:
                return None

            main_path         = None
            gloves_path       = None
            person_path       = None
            vehicle_path      = None
            main_conf         = 0.25
            violation_classes: list[str] = []
            safe_classes:      list[str] = []

            for asgn in assignments:
                model = asgn.model
                if model is None or not model.is_active:
                    continue

                weight = str(_resolve_local_path(model.weight_path))
                conf   = asgn.confidence_threshold or model.confidence_threshold
                mname  = (model.name or "").lower()

                if "gloves" in mname:
                    gloves_path = weight
                elif "person" in mname or "burglar" in mname:
                    person_path = weight
                elif "vehicle" in mname:
                    vehicle_path = weight
                else:
                    main_path = weight
                    main_conf = conf
                    for cc in (
                        db.query(CameraClassConfig)
                        .filter(
                            CameraClassConfig.assignment_id == asgn.id,
                            CameraClassConfig.is_active == True,
                        )
                        .all()
                    ):
                        mc = cc.model_class
                        if mc is None:
                            continue
                        if mc.class_role == "violation":
                            violation_classes.append(mc.class_name)
                        elif mc.class_role == "safe":
                            safe_classes.append(mc.class_name)

            if not main_path:
                return None

            print(
                f"[CameraManager] Camera {cam_id}: model={Path(main_path).name}, "
                f"vehicle={Path(vehicle_path).name if vehicle_path else None}, "
                f"violations={violation_classes}, safe={safe_classes}"
            )
            return {
                "main_model_path":      main_path,
                "gloves_model_path":    gloves_path,
                "person_model_path":    person_path,
                "vehicle_model_path":   vehicle_path,
                "confidence_threshold": main_conf,
                "violation_classes":    violation_classes,
                "safe_classes":         safe_classes,
            }
    except Exception as e:
        print(f"[CameraManager] Warning: could not load model config for cam {cam_id}: {e}")
        return None


def fetch_buzzers_for_camera(cam_id: int) -> list[dict]:
    """
    Return all buzzers assigned to *cam_id* as plain dicts.
    Each dict is compatible with camera_worker.fire_buzzers().
    Returns [] if DB is unavailable or no buzzers are assigned.
    """
    try:
        from app.db.database import SessionLocal, ensure_database_connected
        from app.db.models import CameraBuzzer

        ensure_database_connected()
        with SessionLocal() as db:
            rows = (
                db.query(CameraBuzzer)
                .filter(CameraBuzzer.camera_id == cam_id)
                .all()
            )
            return [
                {
                    "id":         cb.buzzer.id,
                    "protocol":   cb.buzzer.protocol,
                    "device_id":  cb.buzzer.device_id,
                    "ip_address": cb.buzzer.ip_address,
                    "port":       cb.buzzer.port,
                    "gpio_pin":   cb.buzzer.gpio_pin,
                    "is_active":  cb.buzzer.is_active,
                }
                for cb in rows
                if cb.buzzer is not None
            ]
    except Exception as e:
        print(f"[CameraManager] Warning: could not fetch buzzers for cam {cam_id}: {e}")
        return []


def fetch_enabled_models_for_camera(cam_id: int) -> list[str] | None:
    """
    Return the list of enabled legacy model names for a camera (camera_models table).

    Returns None when no rows exist → caller treats all models as enabled.
    Used by result_handler_worker to filter detections by model toggle.
    """
    try:
        from app.db.database import SessionLocal, ensure_database_connected
        from app.db.models import CameraModel

        ensure_database_connected()
        with SessionLocal() as db:
            rows = db.query(CameraModel).filter(CameraModel.camera_id == cam_id).all()
            if not rows:
                return None

            result = sorted(r.model_name for r in rows if r.is_enabled)
            print(f"[CameraManager] Camera {cam_id} enabled models: {result}")
            return result
    except Exception as e:
        print(f"[CameraManager] Warning: could not fetch enabled models for cam {cam_id}: {e}")
        return None
