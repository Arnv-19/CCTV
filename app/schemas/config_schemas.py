from pydantic import BaseModel
from typing import List, Optional, Union


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
    person_model_path: Optional[str] = None
    gloves_model_path: Optional[str] = None
    ppe_model_path: Optional[str] = None
    confidence_threshold: Optional[float] = None

    # Alarm rate limiting
    alarm_cooldown_sec: Optional[int] = None
    burglar_test_sound: Optional[bool] = None


    # Legacy backward-compat keys (still supported)
    esp_ip: Optional[str] = None
    use_wifi: Optional[bool] = None

    # Preferred alarm transport: "usb" | "http" | "mqtt"
    alarm_transport: Optional[str] = None
    alarm_http_token: Optional[str] = None   # optional ?token= for HTTP transport
