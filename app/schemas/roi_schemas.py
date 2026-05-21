
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator
import re


class PointNorm(BaseModel):
    x: float = Field(..., ge=0.0, le=1.0)
    y: float = Field(..., ge=0.0, le=1.0)


class ROIBody(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    points_normalized: List[PointNorm] = Field(..., min_length=3, max_length=200)
    is_active: bool = True
    color: str = Field("#FF5733", pattern=r"^#[0-9A-Fa-f]{6}$")
    priority: int = Field(0, ge=0, le=100)
    camera_width: Optional[int] = None
    camera_height: Optional[int] = None

    @field_validator("name")
    @classmethod
    def name_safe(cls, v: str) -> str:
        if not re.match(r"^[\w\s\-()\[\]]+$", v):
            raise ValueError("Name contains invalid characters")
        return v.strip()


class ROIUpdateBody(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    points_normalized: Optional[List[PointNorm]] = Field(None, min_length=3, max_length=200)
    is_active: Optional[bool] = None
    color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    priority: Optional[int] = Field(None, ge=0, le=100)
    camera_width: Optional[int] = None
    camera_height: Optional[int] = None


class BulkBody(BaseModel):
    rois: List[ROIBody] = Field(..., max_length=50)
