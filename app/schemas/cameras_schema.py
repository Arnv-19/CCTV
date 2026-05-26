from pydantic import BaseModel
from typing import Optional



class CameraCreate(BaseModel):
    name: str
    stream_url: str
    location: Optional[str] = None
    is_active: bool = True
    ingestion_fps: int = 4
    detection_width: int = 960
    detection_height: int = 720
    face_detection_enabled: Optional[bool] = False
    face_detection_mode: Optional[str] = "standard"


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    stream_url: Optional[str] = None
    location: Optional[str] = None
    is_active: Optional[bool] = None
    ingestion_fps: Optional[int] = None
    detection_width: Optional[int] = None
    detection_height: Optional[int] = None
    face_detection_enabled: Optional[bool] = None
    face_detection_mode: Optional[str] = None