from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.config import get_config, load_config, save_config


FEATURE_DEFAULTS = {
    "missing_person_alert": {
        "enabled": False,
        "missing_frames": 3600,
        "cooldown_sec": 300,
        "send_whatsapp": False,
        "per_camera": {},
    },
    "crowd_alert": {
        "enabled": False,
        "person_threshold": 5,
        "sustained_seconds": 5,
        "cooldown_sec": 300,
        "send_whatsapp": False,
        "per_camera": {},
    },
    "dynamic_fps": {
        "enabled": False,
        "min_fps": 2,
        "max_fps": 12,
        "default_fps": 4,
        "target_cpu_percent": 70,
        "per_camera": {},
    },
}


def _deep_merge(base: dict, override: dict | None) -> dict:
    result = deepcopy(base)
    if not isinstance(override, dict):
        return result
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def get_feature_section(section: str) -> dict:
    if section not in FEATURE_DEFAULTS:
        raise KeyError(f"Unknown feature section: {section}")
    cfg = get_config()
    return _deep_merge(FEATURE_DEFAULTS[section], cfg.get(section))


def update_feature_section(section: str, data: dict[str, Any]) -> dict:
    if section not in FEATURE_DEFAULTS:
        raise KeyError(f"Unknown feature section: {section}")
    cfg = load_config()
    current = _deep_merge(FEATURE_DEFAULTS[section], cfg.get(section))
    cfg[section] = _deep_merge(current, data)
    save_config(cfg)
    return get_feature_section(section)


def get_camera_feature_config(cam_id: int) -> dict:
    result = {}
    for section in FEATURE_DEFAULTS:
        section_cfg = get_feature_section(section)
        per_camera = section_cfg.get("per_camera") or {}
        override = per_camera.get(str(cam_id)) or per_camera.get(cam_id) or {}
        merged = _deep_merge(section_cfg, override)
        merged.pop("per_camera", None)
        result[section] = merged
    return result

