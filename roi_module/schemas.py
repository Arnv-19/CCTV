"""Pydantic v2 request / response schemas for the ROI module."""

from __future__ import annotations

import re
from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Shared primitives
# ---------------------------------------------------------------------------

class PointNorm(BaseModel):
    """A single polygon vertex in normalized [0, 1] space."""
    x: float = Field(..., ge=0.0, le=1.0, description="Normalized x coordinate [0, 1]")
    y: float = Field(..., ge=0.0, le=1.0, description="Normalized y coordinate [0, 1]")


# ---------------------------------------------------------------------------
# Create / Update
# ---------------------------------------------------------------------------

class ROICreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    points_normalized: List[PointNorm] = Field(..., min_length=3, max_length=200)
    is_active: bool = True
    color: str = Field("#FF5733", pattern=r"^#[0-9A-Fa-f]{6}$")
    priority: int = Field(0, ge=0, le=100)
    camera_width: Optional[int] = Field(None, gt=0)
    camera_height: Optional[int] = Field(None, gt=0)

    @field_validator("name")
    @classmethod
    def name_safe(cls, v: str) -> str:
        if not re.match(r"^[\w\s\-()\[\]]+$", v):
            raise ValueError("Name contains invalid characters")
        return v.strip()


class ROIUpdate(BaseModel):
    """All fields optional — supports partial PATCH semantics."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    points_normalized: Optional[List[PointNorm]] = Field(None, min_length=3, max_length=200)
    is_active: Optional[bool] = None
    color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    priority: Optional[int] = Field(None, ge=0, le=100)
    camera_width: Optional[int] = Field(None, gt=0)
    camera_height: Optional[int] = Field(None, gt=0)

    @field_validator("name")
    @classmethod
    def name_safe(cls, v: Optional[str]) -> Optional[str]:
        if v is not None:
            if not re.match(r"^[\w\s\-()\[\]]+$", v):
                raise ValueError("Name contains invalid characters")
            return v.strip()
        return v


# ---------------------------------------------------------------------------
# Response
# ---------------------------------------------------------------------------

class ROIOut(BaseModel):
    roi_id: str
    camera_id: str
    name: str
    points_normalized: List[PointNorm]
    is_active: bool
    color: str
    priority: int
    camera_width: Optional[int]
    camera_height: Optional[int]
    created_at: datetime
    updated_at: datetime
    created_by: Optional[str]

    model_config = {"from_attributes": True}


class ROIListOut(BaseModel):
    camera_id: str
    rois: List[ROIOut]
    total: int


# ---------------------------------------------------------------------------
# Bulk operation
# ---------------------------------------------------------------------------

class BulkReplaceRequest(BaseModel):
    """Replace ALL ROIs for a camera atomically."""
    rois: List[ROICreate] = Field(..., max_length=50)
