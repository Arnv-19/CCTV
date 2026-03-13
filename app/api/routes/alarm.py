import sys
from pathlib import Path
from fastapi import APIRouter

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
import alarm  # import module, not names, so runtime state (ser) is always current
from app.config import get_config

router = APIRouter()


@router.post("/test")
def test_alarm():
    cfg = get_config()
    alarm.send_buzzer_command(
        True,
        cfg.get("use_wifi", False),
        esp_ip=cfg.get("esp_ip", None),
        token=cfg.get("alarm_http_token", ""),
        transport=cfg.get("alarm_transport", None),
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
def alarm_status():
    cfg = get_config()
    # Reference alarm.ser at call time (not import time) so we see the live value
    serial_connected = alarm.ser is not None and alarm.ser.is_open
    transport = cfg.get("alarm_transport") or ("http" if cfg.get("use_wifi") else "usb")
    return {
        "transport": transport,
        "serial_port": alarm.SERIAL_PORT,
        "serial_connected": serial_connected,
        "use_wifi": cfg.get("use_wifi", False),
        "esp_ip": cfg.get("esp_ip", ""),
        "mqtt_broker": cfg.get("mqtt_broker", ""),
        "mqtt_topic": cfg.get("mqtt_topic", "skycctv/alarm"),
    }
