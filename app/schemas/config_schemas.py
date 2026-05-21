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
    cameras: Optional[List["ConfigPageCamera"]] = None

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


class ConfigPageCamera(BaseModel):
    id: Optional[int] = None
    name: str
    stream_url: Union[str, int]
    location: Optional[str] = None
    is_active: bool = True
    ingestion_fps: int = 4
    detection_width: int = 960
    detection_height: int = 720


class ConfigPageUpdate(BaseModel):
    """
    Full-page configuration payload used by the Configuration screen.

    Cameras are sourced from PostgreSQL (`cameras` table). Detection model paths
    are mirrored into the AI model registry (`ai_models`) and also written back
    to config.yaml so the existing fallback path keeps working.
    """
    cameras: List[ConfigPageCamera]

    model_path: Optional[str] = None
    person_model_path: Optional[str] = None
    gloves_model_path: Optional[str] = None
    ppe_model_path: Optional[str] = None
    confidence_threshold: Optional[float] = None

    alarm_cooldown_sec: Optional[int] = None
    burglar_test_sound: Optional[bool] = None
    esp_ip: Optional[str] = None
    use_wifi: Optional[bool] = None
    alarm_transport: Optional[str] = None
    alarm_http_token: Optional[str] = None


ConfigUpdate.model_rebuild()
