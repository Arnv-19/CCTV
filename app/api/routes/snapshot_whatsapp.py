from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.controllers.whatsapp_snapshot_controller import send_snapshot_image
from app.db.models import User
from app.dependencies import get_current_user
from app.services.whatsapp_service import WhatsAppConfigError

router = APIRouter()


class SnapshotWhatsAppRequest(BaseModel):
    snapshot_path: str
    to: Optional[str] = None
    caption: Optional[str] = "AXIS CCTV SNAPSHOT"


class SnapshotWhatsAppResponse(BaseModel):
    file: str
    media_id: str
    response: dict


@router.post("/send", response_model=SnapshotWhatsAppResponse)
def send_snapshot_on_whatsapp(
    body: SnapshotWhatsAppRequest,
    _: User = Depends(get_current_user),
):
    try:
        return send_snapshot_image(
            body.snapshot_path,
            recipient_number=body.to,
            caption=body.caption,
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except WhatsAppConfigError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc

