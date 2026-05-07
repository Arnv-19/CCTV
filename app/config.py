"""
app/config.py
-------------
Helpers for reading and writing config.yaml.

config.yaml is the single source of truth for all runtime settings.
get_config() always re-reads from disk so changes saved via the API
(/api/config PATCH) are immediately visible to the next call without
restarting the server.
"""

import yaml
from pathlib import Path

# Absolute path to config.yaml in the project root
CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def load_config() -> dict:
    """Read config.yaml and return the raw dict (no defaults applied)."""
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f) or {}


def save_config(data: dict) -> None:
    """Write the given dict back to config.yaml."""
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False)


def get_config() -> dict:
    """
    Read config.yaml and fill in defaults for any missing keys.

    Always returns a complete config dict safe to pass directly to
    camera_manager or alarm functions.
    """
    cfg = load_config()

    # --- Camera streams ---
    cfg.setdefault("camera_feeds", [])
    cfg.setdefault("camera_titles", [])

    # --- YOLOv8 model ---
    cfg.setdefault("model_path", "weights/helmet_model.pt")
    cfg.setdefault("person_model_path", "weights/person_model.pt")
    cfg.setdefault("gloves_model_path", "weights/best 1.pt")
    cfg.setdefault("ppe_model_path", "weights/ppe_model.pt")
    cfg.setdefault("class_file", "data/class_names.yaml")
    cfg.setdefault("confidence_threshold", 0.25)
    # Higher values preserve distant people/PPE details but cost more CPU/GPU.
    cfg.setdefault("detection_frame_width", 640)
    cfg.setdefault("detection_frame_height", 480)
    cfg.setdefault("yolo_imgsz", 640)

    # --- Alarm cooldown ---
    # Minimum seconds between alarms per camera. 0 = no rate limiting.
    cfg.setdefault("alarm_cooldown_sec", 10)
    # Minimum seconds between saved violation images per camera/violation type.
    # Alerts can still be logged while snapshot_path is null during this window.
    cfg.setdefault("snapshot_cooldown_sec", 120)

    # --- Local test sound ---
    # If True, play a local machine sound when burglar alarm triggers.
    # Intended for testing only.
    cfg.setdefault("burglar_test_sound", False)

    # --- Alarm transport (legacy backward-compat keys) ---
    cfg.setdefault("esp_ip", "")
    cfg.setdefault("use_wifi", False)

    # --- Alarm transport (preferred, overrides use_wifi fallback) ---
    # Values: "usb" | "http" | "mqtt" | None
    # None means: infer from use_wifi (True → http, False → usb)
    cfg.setdefault("alarm_transport", None)

    # --- HTTP (ESP32) transport options ---
    cfg.setdefault("alarm_http_token", "")   # optional ?token= query param

    # --- MQTT transport options ---
    # cfg.setdefault("mqtt_broker", "")
    # cfg.setdefault("mqtt_port", 1883)
    # cfg.setdefault("mqtt_username", "")
    # cfg.setdefault("mqtt_password", "")
    # cfg.setdefault("mqtt_topic", "skycctv/alarm")
    # cfg.setdefault("mqtt_client_id", "skycctv-ai")
    # cfg.setdefault("mqtt_qos", 1)
    # cfg.setdefault("mqtt_retain", False)

    # --- FPS and batch inference ---
    cfg.setdefault("ingestion_fps", 4)
    cfg.setdefault("inference_fps", 4)
    # Frames batched per GPU forward pass — higher = better GPU utilisation
    cfg.setdefault("inference_batch_size", 8)
    # Extra models loaded alongside main model — add new models here without code changes
    # e.g. {"vehicle": "weights/vehicle_model.pt", "fire": "weights/fire_model.pt"}
    cfg.setdefault("extra_models", {})

    # Overlay DB-backed configuration when PostgreSQL is available.
    try:
        from app.db.database import SessionLocal, ensure_database_connected
        from app.db.models import AIModel, AppConfig, Camera

        ensure_database_connected()
        with SessionLocal() as db:
            cameras = db.query(Camera).order_by(Camera.id).all()
            if cameras:
                cfg["camera_feeds"] = [cam.stream_url for cam in cameras]
                cfg["camera_titles"] = [cam.name for cam in cameras]

            app_cfg = db.query(AppConfig).filter(AppConfig.id == 1).first()
            if app_cfg is not None:
                cfg["confidence_threshold"] = app_cfg.confidence_threshold
                cfg["alarm_cooldown_sec"] = app_cfg.alarm_cooldown_sec
                cfg["burglar_test_sound"] = app_cfg.burglar_test_sound
                cfg["esp_ip"] = app_cfg.esp_ip
                cfg["use_wifi"] = app_cfg.use_wifi
                cfg["alarm_transport"] = app_cfg.alarm_transport
                cfg["alarm_http_token"] = app_cfg.alarm_http_token

            slot_names = {
                "model_path": "main_model",
                "person_model_path": "person_model",
                "gloves_model_path": "gloves_model",
                "ppe_model_path": "ppe_model",
            }
            for cfg_key, model_name in slot_names.items():
                row = (
                    db.query(AIModel)
                    .filter(AIModel.name == model_name)
                    .order_by(AIModel.id)
                    .first()
                )
                if row is not None and row.weight_path:
                    cfg[cfg_key] = row.weight_path
    except Exception:
        pass

    return cfg
