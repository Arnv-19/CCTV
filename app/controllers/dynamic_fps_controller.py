from __future__ import annotations

from app.controllers.feature_config_controller import get_feature_section, update_feature_section
from app.db.models import Camera


def decide_camera_fps(
    *,
    camera_count: int,
    camera_id: int | None = None,
    requested_fps: int | None = None,
    cpu_percent: float | None = None,
    settings: dict | None = None,
) -> int:
    cfg = settings or get_feature_section("dynamic_fps")
    min_fps = max(1, int(cfg.get("min_fps", 2)))
    max_fps = max(min_fps, int(cfg.get("max_fps", 12)))
    default_fps = int(requested_fps or cfg.get("default_fps", 4))

    # More active cameras means each one gets a smaller share. CPU pressure can
    # reduce it further; this is intentionally simple and predictable.
    divisor = max(1, camera_count)
    decided = max_fps if divisor <= 1 else round(max_fps / min(divisor, 4))

    target_cpu = float(cfg.get("target_cpu_percent", 70))
    if cpu_percent is not None and cpu_percent > target_cpu:
        pressure = min(1.0, (cpu_percent - target_cpu) / max(1.0, 100 - target_cpu))
        decided = round(decided * (1.0 - 0.5 * pressure))

    return max(min_fps, min(max_fps, min(default_fps, int(decided))))


def recommend_fps_for_cameras(cameras: list[dict], cpu_percent: float | None = None) -> list[dict]:
    settings = get_feature_section("dynamic_fps")
    return [
        {
            "camera_id": cam["id"],
            "current_fps": cam.get("ingestion_fps"),
            "recommended_fps": decide_camera_fps(
                camera_count=len(cameras),
                camera_id=cam["id"],
                requested_fps=cam.get("ingestion_fps"),
                cpu_percent=cpu_percent,
                settings=settings,
            ),
        }
        for cam in cameras
    ]


def update_dynamic_fps_settings(data: dict) -> dict:
    return update_feature_section("dynamic_fps", data)


def apply_dynamic_fps_to_db(db, cpu_percent: float | None = None) -> list[dict]:
    cameras = db.query(Camera).filter(Camera.is_active == True).order_by(Camera.id).all()
    camera_dicts = [
        {"id": cam.id, "ingestion_fps": cam.ingestion_fps}
        for cam in cameras
    ]
    recommendations = recommend_fps_for_cameras(camera_dicts, cpu_percent)
    by_id = {row["camera_id"]: row["recommended_fps"] for row in recommendations}
    for cam in cameras:
        cam.ingestion_fps = by_id[cam.id]
    db.commit()
    return recommendations

