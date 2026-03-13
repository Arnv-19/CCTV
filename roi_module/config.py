"""
ROI Module Configuration
Provides safe defaults and a configure_roi() function for runtime overrides.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class ROIConfig:
    # Feature toggle
    default_enabled: bool = True

    # Limits
    max_rois_per_camera: int = 10
    max_points_per_roi: int = 50

    # Detection behaviour
    allow_outside_fallback: bool = True   # allow all detections when no ROI exists
    strict_roi_mode: bool = False          # per-module override (cameras can override individually)
    filter_mode: Literal["center", "iou"] = "center"
    iou_threshold: float = 0.3            # minimum IoU to consider detection "inside" ROI

    # Cache
    cache_ttl_seconds: int = 60

    # Observability
    debug_mode: bool = False


# Module-level singleton — override at application startup via configure_roi()
roi_config = ROIConfig()


def configure_roi(**kwargs) -> None:
    """
    Override ROI config settings at application startup.

    Example::

        from roi_module.config import configure_roi
        configure_roi(filter_mode="iou", iou_threshold=0.25, debug_mode=True)
    """
    for key, value in kwargs.items():
        if not hasattr(roi_config, key):
            raise ValueError(f"Unknown ROI config key: '{key}'")
        setattr(roi_config, key, value)
