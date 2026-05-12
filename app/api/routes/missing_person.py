from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.controllers.feature_config_controller import get_feature_section, update_feature_section
from app.db.models import User
from app.dependencies import get_current_user, require_admin

router = APIRouter()


class MissingPersonConfigRequest(BaseModel):
    enabled: Optional[bool] = None
    missing_frames: Optional[int] = Field(None, ge=1)
    cooldown_sec: Optional[int] = Field(None, ge=0)
    send_whatsapp: Optional[bool] = None
    per_camera: Optional[dict[str, dict]] = None


class MissingPersonConfigResponse(BaseModel):
    enabled: bool
    missing_frames: int
    cooldown_sec: int
    send_whatsapp: bool
    per_camera: dict


@router.get("/config", response_model=MissingPersonConfigResponse)
def get_missing_person_config(_: User = Depends(get_current_user)):
    return get_feature_section("missing_person_alert")


@router.put("/config", response_model=MissingPersonConfigResponse)
def update_missing_person_config(
    body: MissingPersonConfigRequest,
    _: User = Depends(require_admin),
):
    return update_feature_section(
        "missing_person_alert",
        body.model_dump(exclude_unset=True),
    )

