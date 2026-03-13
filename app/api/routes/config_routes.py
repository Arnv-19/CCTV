"""
app/api/routes/config_routes.py
--------------------------------
Endpoints for reading and updating the application configuration.

config.yaml is the persistent store. Changes take effect for the next
camera start — running cameras use the config snapshot captured when they
were started and must be restarted to pick up new settings.

GET   /api/config/    Return the complete current config (with defaults filled)
PATCH /api/config/    Merge the supplied fields into config.yaml and save

Only fields included in the request body are updated (exclude_none=True).
"""

from fastapi import APIRouter
from pydantic import BaseModel
from typing import List, Optional, Union

from app.config import get_config, save_config

router = APIRouter()


class ConfigUpdate(BaseModel):
    """
    Partial config update model. All fields are optional — only provided
    fields are written to config.yaml. Omitted fields are left unchanged.
    """
    # Camera streams
    # Accept both RTSP/file URLs (str) and webcam indices (int, e.g. 0)
    camera_feeds: Optional[List[Union[str, int]]] = None
    camera_titles: Optional[List[str]] = None

    # YOLOv8 model
    model_path: Optional[str] = None
    confidence_threshold: Optional[float] = None

    # Alarm rate limiting
    alarm_cooldown_sec: Optional[int] = None

    # Legacy backward-compat keys (still supported)
    esp_ip: Optional[str] = None
    use_wifi: Optional[bool] = None

    # Preferred alarm transport: "usb" | "http" | "mqtt"
    alarm_transport: Optional[str] = None
    alarm_http_token: Optional[str] = None   # optional ?token= for HTTP transport

    # MQTT transport settings
    mqtt_broker: Optional[str] = None
    mqtt_port: Optional[int] = None
    mqtt_username: Optional[str] = None
    mqtt_password: Optional[str] = None
    mqtt_topic: Optional[str] = None
    mqtt_client_id: Optional[str] = None
    mqtt_qos: Optional[int] = None
    mqtt_retain: Optional[bool] = None


@router.get("/")
def get_full_config():
    """Return the full config with all defaults applied."""
    return get_config()


@router.patch("/")
def update_config(body: ConfigUpdate):
    """
    Merge partial config into config.yaml.
    Only fields present in the request body are written; others are untouched.
    Returns the updated full config.
    """
    cfg = get_config()
    # exclude_none ensures fields not provided in the request are not overwritten
    data = body.model_dump(exclude_none=True)
    cfg.update(data)
    save_config(cfg)
    return {"message": "Config updated", "config": cfg}
