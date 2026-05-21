from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.controllers.feature_config_controller import get_feature_section, update_feature_section
from app.db.models import User
from app.dependencies import get_current_user, require_admin

router = APIRouter()


class CrowdAlertConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    person_threshold: Optional[int] = Field(None, ge=1)
    sustained_seconds: Optional[float] = Field(None, ge=0)
    send_whatsapp: Optional[bool] = None
    per_camera: Optional[dict[str, dict]] = None


class CrowdAlertConfigResponse(BaseModel):
    enabled: bool
    person_threshold: int
    sustained_seconds: float
    send_whatsapp: bool
    per_camera: dict


@router.get("/config", response_model=CrowdAlertConfigResponse)
def get_crowd_alert_config(_: User = Depends(get_current_user)):
    return get_feature_section("crowd_alert")


@router.put("/config", response_model=CrowdAlertConfigResponse)
def update_crowd_alert_config(
    body: CrowdAlertConfigRequest,
    _: User = Depends(require_admin),
):
    return update_feature_section("crowd_alert", body.model_dump(exclude_unset=True))

