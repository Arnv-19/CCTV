from __future__ import annotations

from app.db.models import BurglarAlarmConfig, Camera
from app.services.burglar_alarm_service import is_in_alarm_window


def verify_burglar_alarm_for_all_cameras(db) -> dict:
    cameras = db.query(Camera).filter(Camera.is_active == True).order_by(Camera.id).all()
    configs = {
        cfg.camera_id: cfg
        for cfg in db.query(BurglarAlarmConfig).all()
    }
    rows = []
    missing = []
    disabled = []
    for cam in cameras:
        cfg = configs.get(cam.id)
        if cfg is None:
            missing.append(cam.id)
            rows.append({
                "camera_id": cam.id,
                "camera_name": cam.name,
                "configured": False,
                "alarm_enabled": False,
                "window_active": False,
                "active_now": False,
            })
            continue
        window_active = is_in_alarm_window(cfg.alarm_start_time, cfg.alarm_end_time)
        if not cfg.alarm_enabled:
            disabled.append(cam.id)
        rows.append({
            "camera_id": cam.id,
            "camera_name": cam.name,
            "configured": True,
            "alarm_enabled": cfg.alarm_enabled,
            "window_active": window_active,
            "active_now": bool(cfg.alarm_enabled and window_active),
            "alarm_start_time": cfg.alarm_start_time,
            "alarm_end_time": cfg.alarm_end_time,
            "monitored_zone_id": cfg.monitored_zone_id,
            "cooldown_sec": cfg.cooldown_sec,
        })
    return {
        "camera_count": len(cameras),
        "configured_count": len(cameras) - len(missing),
        "missing_camera_ids": missing,
        "disabled_camera_ids": disabled,
        "all_configured": not missing,
        "all_enabled": not missing and not disabled,
        "items": rows,
    }

