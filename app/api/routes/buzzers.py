"""
app/api/routes/buzzers.py
--------------------------
Buzzer device CRUD — admin only for write operations, all authenticated for reads.

GET    /api/buzzers/         List all buzzers
POST   /api/buzzers/         Create a buzzer
PUT    /api/buzzers/{id}     Update a buzzer
DELETE /api/buzzers/{id}     Delete a buzzer
PATCH  /api/buzzers/{id}/toggle  Enable / disable a buzzer
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from typing import Optional
from sqlalchemy.orm import Session

from app.db.database import get_db
from app.db.models import Buzzer, User
from app.dependencies import get_current_user, require_admin

router = APIRouter()

VALID_PROTOCOLS = ("usb", "http", "mqtt", "gpio")


class BuzzerBody(BaseModel):
    name:       str
    protocol:   str = "usb"
    device_id:  Optional[str] = None   # serial port e.g. /dev/ttyACM0
    ip_address: Optional[str] = None   # for http / mqtt
    port:       Optional[int] = None   # http port or mqtt port
    gpio_pin:   Optional[int] = None   # for gpio
    is_active:  bool = True


def _validate(body: BuzzerBody):
    if body.protocol not in VALID_PROTOCOLS:
        raise HTTPException(400, f"protocol must be one of {VALID_PROTOCOLS}")
    if body.protocol == "usb"  and not body.device_id:
        raise HTTPException(400, "device_id (serial port) required for USB protocol")
    if body.protocol == "http" and not body.ip_address:
        raise HTTPException(400, "ip_address required for HTTP protocol")
    if body.protocol == "mqtt" and not body.ip_address:
        raise HTTPException(400, "ip_address (broker host) required for MQTT protocol")
    if body.protocol == "gpio" and body.gpio_pin is None:
        raise HTTPException(400, "gpio_pin required for GPIO protocol")


def _buzzer_dict(b: Buzzer) -> dict:
    return {
        "id":         b.id,
        "name":       b.name,
        "protocol":   b.protocol,
        "device_id":  b.device_id,
        "ip_address": b.ip_address,
        "port":       b.port,
        "gpio_pin":   b.gpio_pin,
        "is_active":  b.is_active,
        "created_at": b.created_at,
    }


@router.get("/")
def list_buzzers(
    db: Session = Depends(get_db),
    _: User = Depends(get_current_user),
):
    return [_buzzer_dict(b) for b in db.query(Buzzer).order_by(Buzzer.id).all()]


@router.post("/", status_code=status.HTTP_201_CREATED)
def create_buzzer(
    body: BuzzerBody,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    _validate(body)
    b = Buzzer(**body.model_dump())
    db.add(b)
    db.commit()
    db.refresh(b)
    return _buzzer_dict(b)


@router.put("/{buzzer_id}")
def update_buzzer(
    buzzer_id: int,
    body: BuzzerBody,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    _validate(body)
    b = db.get(Buzzer, buzzer_id)
    if not b:
        raise HTTPException(404, "Buzzer not found")
    for k, v in body.model_dump().items():
        setattr(b, k, v)
    db.commit()
    db.refresh(b)
    return _buzzer_dict(b)


@router.delete("/{buzzer_id}")
def delete_buzzer(
    buzzer_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    b = db.get(Buzzer, buzzer_id)
    if not b:
        raise HTTPException(404, "Buzzer not found")
    db.delete(b)
    db.commit()
    return {"message": f"Buzzer '{b.name}' deleted"}


@router.patch("/{buzzer_id}/toggle")
def toggle_buzzer(
    buzzer_id: int,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    b = db.get(Buzzer, buzzer_id)
    if not b:
        raise HTTPException(404, "Buzzer not found")
    b.is_active = not b.is_active
    db.commit()
    return {"id": b.id, "is_active": b.is_active}
