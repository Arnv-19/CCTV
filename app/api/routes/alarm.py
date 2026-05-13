import sys
from pathlib import Path
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
import alarm  # import module, not names, so runtime state (ser) is always current

from app.db.database import get_db
from app.db.models.app_config import AppConfig
from app.config import get_config  # kept for MQTT settings not yet in DB

router = APIRouter()


def _get_app_config(db: Session) -> AppConfig | None:
    return db.query(AppConfig).filter(AppConfig.id == 1).first()


@router.post("/test")
def test_alarm(db: Session = Depends(get_db)):
    row = _get_app_config(db)

    # Core alarm settings from DB
    use_wifi       = row.use_wifi       if row else False
    esp_ip         = row.esp_ip         if row else ""
    alarm_http_token = row.alarm_http_token if row else ""
    transport      = row.alarm_transport if row else None

    # MQTT settings not yet in DB — fall back to config.yaml
    cfg = get_config()
    alarm.send_buzzer_command(
        True,
        use_wifi,
        esp_ip=esp_ip or None,
        token=alarm_http_token,
        transport=transport,
        mqtt_broker=cfg.get("mqtt_broker", ""),
        mqtt_port=cfg.get("mqtt_port", 1883),
        mqtt_username=cfg.get("mqtt_username", ""),
        mqtt_password=cfg.get("mqtt_password", ""),
        mqtt_topic=cfg.get("mqtt_topic", "skycctv/alarm"),
        mqtt_client_id=cfg.get("mqtt_client_id", "skycctv-ai"),
        mqtt_qos=cfg.get("mqtt_qos", 1),
        mqtt_retain=cfg.get("mqtt_retain", False),
        camera_id=None,
    )
    return {"message": "Alarm triggered"}


@router.get("/status")
def alarm_status(db: Session = Depends(get_db)):
    row = _get_app_config(db)

    use_wifi  = row.use_wifi        if row else False
    esp_ip    = row.esp_ip          if row else ""
    transport = row.alarm_transport if row else None

    # MQTT settings not yet in DB — fall back to config.yaml
    cfg = get_config()

    serial_connected = alarm.ser is not None and alarm.ser.is_open
    effective_transport = transport or ("http" if use_wifi else "usb")

    return {
        "transport":       effective_transport,
        "serial_port":     alarm.SERIAL_PORT,
        "serial_connected": serial_connected,
        "use_wifi":        use_wifi,
        "esp_ip":          esp_ip,
        "mqtt_broker":     cfg.get("mqtt_broker", ""),
        "mqtt_topic":      cfg.get("mqtt_topic", "skycctv/alarm"),
    }
