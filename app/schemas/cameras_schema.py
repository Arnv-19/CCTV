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


class CameraUpdate(BaseModel):
    name: Optional[str] = None
    stream_url: Optional[str] = None
    location: Optional[str] = None
    is_active: Optional[bool] = None
    ingestion_fps: Optional[int] = None
    detection_width: Optional[int] = None
    detection_height: Optional[int] = None