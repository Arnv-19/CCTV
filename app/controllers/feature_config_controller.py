from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.db.database import SessionLocal
from app.db.models.app_config import AppConfig


FEATURE_DEFAULTS: dict[str, dict] = {
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


def _get_or_create_app_config(db) -> AppConfig:
    row = db.query(AppConfig).filter(AppConfig.id == 1).first()
    if row is None:
        row = AppConfig(id=1)
        db.add(row)
        db.flush()
    return row


def get_feature_section(section: str) -> dict:
    if section not in FEATURE_DEFAULTS:
        raise KeyError(f"Unknown feature section: {section}")
    db = SessionLocal()
    try:
        row = _get_or_create_app_config(db)
        stored = getattr(row, section, None)
        return _deep_merge(FEATURE_DEFAULTS[section], stored)
    finally:
        db.close()


def update_feature_section(section: str, data: dict[str, Any]) -> dict:
    if section not in FEATURE_DEFAULTS:
        raise KeyError(f"Unknown feature section: {section}")
    db = SessionLocal()
    try:
        row = _get_or_create_app_config(db)
        current = _deep_merge(FEATURE_DEFAULTS[section], getattr(row, section, None))
        merged = _deep_merge(current, data)
        setattr(row, section, merged)
        db.commit()
        db.refresh(row)
        return _deep_merge(FEATURE_DEFAULTS[section], getattr(row, section, None))
    finally:
        db.close()


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
