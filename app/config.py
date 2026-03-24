"""
app/config.py
-------------
Helpers for reading and writing config.yaml.

config.yaml is the single source of truth for all runtime settings.
get_config() always re-reads from disk so changes saved via the API
(/api/config PATCH) are immediately visible to the next call without
restarting the server.
"""

import yaml
from pathlib import Path

# Absolute path to config.yaml in the project root
CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


def load_config() -> dict:
    """Read config.yaml and return the raw dict (no defaults applied)."""
    with open(CONFIG_PATH, "r") as f:
        return yaml.safe_load(f) or {}


def save_config(data: dict) -> None:
    """Write the given dict back to config.yaml."""
    with open(CONFIG_PATH, "w") as f:
        yaml.dump(data, f, default_flow_style=False)


def get_config() -> dict:
    """
    Read config.yaml and fill in defaults for any missing keys.

    Always returns a complete config dict safe to pass directly to
    camera_manager or alarm functions.
    """
    cfg = load_config()

    # --- Camera streams ---
    cfg.setdefault("camera_feeds", [])
    cfg.setdefault("camera_titles", [])

    # --- YOLOv8 model ---
    cfg.setdefault("model_path", "weights/helmet_model.pt")
    cfg.setdefault("person_model_path", "weights/person_model.pt")
    cfg.setdefault("class_file", "data/class_names.yaml")
    cfg.setdefault("confidence_threshold", 0.25)

    # --- Alarm cooldown ---
    # Minimum seconds between alarms per camera. 0 = no rate limiting.
    cfg.setdefault("alarm_cooldown_sec", 10)

    # --- Local test sound ---
    # If True, play a local machine sound when burglar alarm triggers.
    # Intended for testing only.
    cfg.setdefault("burglar_test_sound", False)

    # --- Alarm transport (legacy backward-compat keys) ---
    cfg.setdefault("esp_ip", "")
    cfg.setdefault("use_wifi", False)

    # --- Alarm transport (preferred, overrides use_wifi fallback) ---
    # Values: "usb" | "http" | "mqtt" | None
    # None means: infer from use_wifi (True → http, False → usb)
    cfg.setdefault("alarm_transport", None)

    # --- HTTP (ESP32) transport options ---
    cfg.setdefault("alarm_http_token", "")   # optional ?token= query param

    # --- MQTT transport options ---
    cfg.setdefault("mqtt_broker", "")
    cfg.setdefault("mqtt_port", 1883)
    cfg.setdefault("mqtt_username", "")
    cfg.setdefault("mqtt_password", "")
    cfg.setdefault("mqtt_topic", "skycctv/alarm")
    cfg.setdefault("mqtt_client_id", "skycctv-ai")
    cfg.setdefault("mqtt_qos", 1)
    cfg.setdefault("mqtt_retain", False)

    return cfg
