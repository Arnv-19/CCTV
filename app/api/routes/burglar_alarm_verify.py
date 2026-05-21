from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.controllers.burglar_alarm_verification_controller import verify_burglar_alarm_for_all_cameras
from app.db.database import get_db
from app.db.models import User
from app.dependencies import get_current_user

router = APIRouter()


class BurglarAlarmCameraVerification(BaseModel):
    camera_id: int
    camera_name: str
    configured: bool
    alarm_enabled: bool
    window_active: bool
    active_now: bool
    alarm_start_time: str | None = None
    alarm_end_time: str | None = None
    monitored_zone_id: str | None = None
    cooldown_sec: int | None = None


class BurglarAlarmVerificationResponse(BaseModel):
    camera_count: int
    configured_count: int
    missing_camera_ids: list[int]
    disabled_camera_ids: list[int]
    all_configured: bool
    all_enabled: bool
    items: list[BurglarAlarmCameraVerification]


@router.get("/all-cameras", response_model=BurglarAlarmVerificationResponse)
def verify_burglar_alarm_all_cameras(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return verify_burglar_alarm_for_all_cameras(db)

