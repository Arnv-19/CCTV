"""
alarm.py
--------
Multi-transport alarm sender for SkyCCTVAI.

Supported transports:
  usb   — sends "buzz_on\\n" / "buzz_off\\n" over USB serial to an ESP32
  http  — HTTP GET to ESP32 web server endpoint  /buzz_on | /buzz_off
  mqtt  — publishes a JSON payload to an MQTT broker topic

Transport selection (in priority order):
  1. Explicit `transport` argument ("usb" | "http" | "mqtt")
  2. Backward-compat fallback: use_wifi=True → http, else usb

All alarm sends are fire-and-forget (spawned in a daemon thread) so they
never block the camera detection loop.

Cooldown is tracked per camera_id so a busy camera doesn't spam the buzzer.
"""

import time
import threading
from typing import Optional

# Per-camera timestamp of last alarm sent {camera_id: float (epoch seconds)}
last_sent_time = {}

# pyserial is optional — if not installed, USB transport is silently disabled
try:
    import serial  # type: ignore
except Exception:  # pragma: no cover
    serial = None

# --- Serial port configuration ---
SERIAL_PORT = "/dev/ttyACM0"   # update via set_serial_port() or the GUI config
BAUDRATE = 115200
serial_lock = threading.Lock()  # guards concurrent writes from multiple camera threads

# Active serial connection (set by init_serial, read by _send_usb)
ser = None


# ---------------------------------------------------------------------------
# Serial lifecycle
# ---------------------------------------------------------------------------

def init_serial():
    """Open the serial port on app startup. Silently skips if pyserial is absent."""
    global ser
    if serial is None:
        print("[USB] pyserial not installed; USB alarm disabled")
        return
    try:
        ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
        print(f"[USB] Serial connected on {SERIAL_PORT}")
    except Exception as e:
        ser = None
        print(f"[USB] Failed to open serial port {SERIAL_PORT}: {e}")


def set_serial_port(port: str):
    """Update the serial port path at runtime (before calling init_serial)."""
    global SERIAL_PORT
    SERIAL_PORT = port


def reconnect_serial():
    """Attempt to re-open the serial port after a write error."""
    global ser
    if serial is None:
        return
    try:
        if ser:
            ser.close()
            time.sleep(0.5)
        ser = serial.Serial(SERIAL_PORT, BAUDRATE, timeout=1)
        print("[USB] Serial reconnected.")
    except Exception as e:
        ser = None
        print(f"[USB] Reconnection failed: {e}")


def close_serial():
    """Close the serial connection cleanly on app shutdown."""
    global ser
    if ser and ser.is_open:
        print("[USB] Closing serial port...")
        ser.close()
        time.sleep(0.5)


# ---------------------------------------------------------------------------
# Private transport implementations
# ---------------------------------------------------------------------------

def _send_usb(state: bool):
    """Write buzz_on / buzz_off command over USB serial."""
    if serial is None:
        print("[USB] pyserial not installed; cannot send USB alarm")
        return
    if ser and ser.is_open:
        cmd = "buzz_on\n" if state else "buzz_off\n"
        try:
            with serial_lock:
                ser.write(cmd.encode())
            print(f"[USB] Sent: {cmd.strip()}")
        except Exception as e:
            print(f"[USB] Error sending serial command: {e}")
            reconnect_serial()  # try to recover for next alarm
    else:
        print("[USB] Serial port not open, can't send command")


def _send_http(state: bool, esp_ip: str, token: str = ""):
    """
    Send an HTTP GET request to the ESP32 web server.
    Endpoint: http://<esp_ip>/buzz_on  or  /buzz_off
    Optional token is passed as a query param: ?token=<token>
    """
    import requests
    try:
        path = f"/buzz_{'on' if state else 'off'}"
        url = f"http://{esp_ip}{path}"
        params = {"token": token} if token else None
        print(f"[WiFi] Sending request to {url}")
        requests.get(url, timeout=1, params=params)
    except Exception as e:
        print(f"[WiFi] Error sending buzzer request: {e}")


def _send_mqtt(
    state: bool,
    broker: str,
    port: int,
    topic: str,
    username: str = "",
    password: str = "",
    client_id: str = "skycctv-ai",
    qos: int = 1,
    retain: bool = False,
    camera_id: Optional[int] = None,
):
    """
    Publish an alarm event to an MQTT broker.

    Payload (JSON):
        {"state": "on"|"off", "camera_id": int|null, "ts": epoch_float}

    Uses a new connection per publish (connect → publish → disconnect).
    This is appropriate for infrequent alarm events. For high-frequency
    scenarios a persistent client would be more efficient.

    Requires paho-mqtt>=2.0.0 (CallbackAPIVersion.VERSION2).
    """
    try:
        import json
        import paho.mqtt.client as mqtt
    except Exception as e:
        print(f"[MQTT] MQTT dependency missing or import failed: {e}")
        return

    payload = {
        "state": "on" if state else "off",
        "camera_id": camera_id,
        "ts": time.time(),
    }

    try:
        # CallbackAPIVersion.VERSION2 is required for paho-mqtt >= 2.0.0
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id)
        if username:
            client.username_pw_set(username, password=password)
        client.connect(broker, port=port, keepalive=10)
        client.publish(topic, json.dumps(payload), qos=qos, retain=retain)
        client.disconnect()
        print(f"[MQTT] Published to {topic}: {payload}")
    except Exception as e:
        print(f"[MQTT] Publish failed: {e}")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def send_buzzer_command(
    state: bool,
    use_wifi: bool,
    esp_ip: str | None = None,
    token: str = "",
    transport: str | None = None,
    mqtt_broker: str = "",
    mqtt_port: int = 1883,
    mqtt_username: str = "",
    mqtt_password: str = "",
    mqtt_topic: str = "skycctv/alarm",
    mqtt_client_id: str = "skycctv-ai",
    mqtt_qos: int = 1,
    mqtt_retain: bool = False,
    camera_id: Optional[int] = None,
):
    """
    Route an alarm signal to the correct transport.

    transport resolution order:
      1. Explicit `transport` arg ("usb" | "http" | "mqtt")
      2. Backward-compat: use_wifi=True → http, else usb
    """
    resolved = (transport or "").lower().strip() or ("http" if use_wifi else "usb")

    if resolved == "http":
        if not esp_ip:
            print("[WiFi] esp_ip missing; cannot send HTTP alarm")
            return
        _send_http(state, esp_ip=esp_ip, token=token)
        return

    if resolved == "mqtt":
        if not mqtt_broker:
            print("[MQTT] mqtt_broker missing; cannot send MQTT alarm")
            return
        _send_mqtt(
            state,
            broker=mqtt_broker,
            port=mqtt_port,
            topic=mqtt_topic,
            username=mqtt_username,
            password=mqtt_password,
            client_id=mqtt_client_id,
            qos=mqtt_qos,
            retain=mqtt_retain,
            camera_id=camera_id,
        )
        return

    # Default transport: USB serial
    _send_usb(state)


def trigger_alarm(
    camera_id,
    cooldown,
    use_wifi: bool = False,
    esp_ip: str | None = None,
    transport: str | None = None,
    token: str = "",
    mqtt_broker: str = "",
    mqtt_port: int = 1883,
    mqtt_username: str = "",
    mqtt_password: str = "",
    mqtt_topic: str = "skycctv/alarm",
    mqtt_client_id: str = "skycctv-ai",
    mqtt_qos: int = 1,
    mqtt_retain: bool = False,
):
    """
    Rate-limited alarm trigger called by the camera loop on each violation.

    Enforces a per-camera cooldown so repeated detections in the same window
    don't flood the buzzer. The actual send runs in a daemon thread so this
    call returns immediately without blocking the detection loop.

    cooldown=0 means every detected frame fires an alarm with no rate limiting.
    """
    now = time.time()

    if camera_id not in last_sent_time:
        last_sent_time[camera_id] = 0

    # Guard against None or negative cooldown values
    effective_cooldown = max(0.0, float(cooldown or 0))

    if now - last_sent_time[camera_id] > effective_cooldown:
        print(f"[ALARM] No helmet detected on Camera {camera_id}")
        # Dispatch alarm in background so the camera loop is not delayed
        threading.Thread(
            target=send_buzzer_command,
            kwargs={
                "state": True,
                "use_wifi": use_wifi,
                "esp_ip": esp_ip,
                "token": token,
                "transport": transport,
                "mqtt_broker": mqtt_broker,
                "mqtt_port": mqtt_port,
                "mqtt_username": mqtt_username,
                "mqtt_password": mqtt_password,
                "mqtt_topic": mqtt_topic,
                "mqtt_client_id": mqtt_client_id,
                "mqtt_qos": mqtt_qos,
                "mqtt_retain": mqtt_retain,
                "camera_id": camera_id,
            },
            daemon=True,
        ).start()
        last_sent_time[camera_id] = now
