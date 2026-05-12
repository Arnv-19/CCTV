from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.controllers.dynamic_fps_controller import (
    apply_dynamic_fps_to_db,
    recommend_fps_for_cameras,
    update_dynamic_fps_settings,
)
from app.controllers.feature_config_controller import get_feature_section
from app.db.database import get_db
from app.db.models import Camera, User
from app.dependencies import get_current_user, require_admin

router = APIRouter()


class DynamicFpsConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    min_fps: Optional[int] = Field(None, ge=1)
    max_fps: Optional[int] = Field(None, ge=1)
    default_fps: Optional[int] = Field(None, ge=1)
    target_cpu_percent: Optional[float] = Field(None, ge=1, le=100)
    per_camera: Optional[dict[str, dict]] = None


class DynamicFpsConfigResponse(BaseModel):
    enabled: bool
    min_fps: int
    max_fps: int
    default_fps: int
    target_cpu_percent: float
    per_camera: dict


class DynamicFpsRecommendation(BaseModel):
    camera_id: int
    current_fps: Optional[int]
    recommended_fps: int


@router.get("/config", response_model=DynamicFpsConfigResponse)
def get_dynamic_fps_config(_: User = Depends(get_current_user)):
    return get_feature_section("dynamic_fps")


@router.put("/config", response_model=DynamicFpsConfigResponse)
def update_dynamic_fps_config(
    body: DynamicFpsConfigRequest,
    _: User = Depends(require_admin),
):
    return update_dynamic_fps_settings(body.model_dump(exclude_unset=True))


@router.get("/recommendations", response_model=list[DynamicFpsRecommendation])
def get_dynamic_fps_recommendations(
    cpu_percent: Optional[float] = Query(None, ge=0, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    cameras = [
        {"id": cam.id, "ingestion_fps": cam.ingestion_fps}
        for cam in db.query(Camera).filter(Camera.is_active == True).order_by(Camera.id).all()
    ]
    return recommend_fps_for_cameras(cameras, cpu_percent)


@router.post("/apply", response_model=list[DynamicFpsRecommendation])
def apply_dynamic_fps(
    cpu_percent: Optional[float] = Query(None, ge=0, le=100),
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    return apply_dynamic_fps_to_db(db, cpu_percent)

