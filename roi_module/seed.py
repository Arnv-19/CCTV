"""
Sample seed data for development and testing.

Usage::

    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from roi_module.models import init_tables
    from roi_module.seed import seed_sample_rois

    engine = create_engine("postgresql://user:pass@localhost/db")
    init_tables(engine)
    Session = sessionmaker(bind=engine)

    with Session() as db:
        seed_sample_rois(db)
"""

from __future__ import annotations

import logging
from typing import List

from sqlalchemy.orm import Session

from .models import ROI
from .service import bulk_replace_rois
from .schemas import ROICreate, PointNorm

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Sample payload definitions
# ---------------------------------------------------------------------------

SAMPLE_ROIS: dict[str, List[dict]] = {
    "cam_1": [
        {
            "name": "Entrance Zone",
            "color": "#FF5733",
            "priority": 10,
            "is_active": True,
            "camera_width": 1280,
            "camera_height": 720,
            "points_normalized": [
                {"x": 0.05, "y": 0.05},
                {"x": 0.45, "y": 0.05},
                {"x": 0.45, "y": 0.55},
                {"x": 0.05, "y": 0.55},
            ],
        },
        {
            "name": "Machinery Area",
            "color": "#33FF57",
            "priority": 5,
            "is_active": True,
            "camera_width": 1280,
            "camera_height": 720,
            "points_normalized": [
                {"x": 0.55, "y": 0.10},
                {"x": 0.95, "y": 0.10},
                {"x": 0.90, "y": 0.60},
                {"x": 0.60, "y": 0.70},
                {"x": 0.55, "y": 0.40},
            ],
        },
    ],
    "cam_2": [
        {
            "name": "Hazard Zone",
            "color": "#FF3366",
            "priority": 10,
            "is_active": True,
            "camera_width": 1920,
            "camera_height": 1080,
            "points_normalized": [
                {"x": 0.20, "y": 0.20},
                {"x": 0.80, "y": 0.20},
                {"x": 0.80, "y": 0.80},
                {"x": 0.20, "y": 0.80},
            ],
        },
        {
            "name": "Disabled Zone (example)",
            "color": "#AAAAAA",
            "priority": 0,
            "is_active": False,
            "camera_width": 1920,
            "camera_height": 1080,
            "points_normalized": [
                {"x": 0.30, "y": 0.30},
                {"x": 0.70, "y": 0.30},
                {"x": 0.70, "y": 0.70},
                {"x": 0.30, "y": 0.70},
            ],
        },
    ],
}


# ---------------------------------------------------------------------------
# Seed function
# ---------------------------------------------------------------------------

def seed_sample_rois(db: Session, skip_if_exists: bool = True) -> int:
    """
    Insert sample ROIs for development cameras.

    Args:
        db:               SQLAlchemy session.
        skip_if_exists:   Skip cameras that already have ROIs defined.

    Returns:
        Number of ROIs inserted.
    """
    total = 0
    for camera_id, roi_list in SAMPLE_ROIS.items():
        if skip_if_exists:
            existing = db.query(ROI).filter(ROI.camera_id == camera_id).count()
            if existing > 0:
                logger.info("Skipping seed for camera %s (%d ROIs already exist)", camera_id, existing)
                continue

        create_payloads = [
            ROICreate(
                name=r["name"],
                color=r["color"],
                priority=r["priority"],
                is_active=r["is_active"],
                camera_width=r.get("camera_width"),
                camera_height=r.get("camera_height"),
                points_normalized=[PointNorm(**p) for p in r["points_normalized"]],
            )
            for r in roi_list
        ]

        inserted = bulk_replace_rois(db, camera_id, create_payloads, created_by="seed")
        total += len(inserted)
        logger.info("Seeded %d ROIs for camera %s", len(inserted), camera_id)

    return total


# ---------------------------------------------------------------------------
# Example payloads (for documentation / manual API testing)
# ---------------------------------------------------------------------------

EXAMPLE_CREATE_REQUEST = {
    "name": "Loading Bay",
    "color": "#0099FF",
    "priority": 8,
    "is_active": True,
    "camera_width": 1280,
    "camera_height": 720,
    "points_normalized": [
        {"x": 0.1, "y": 0.1},
        {"x": 0.6, "y": 0.1},
        {"x": 0.6, "y": 0.9},
        {"x": 0.1, "y": 0.9},
    ],
}

EXAMPLE_UPDATE_REQUEST = {
    "name": "Loading Bay (Updated)",
    "color": "#FF9900",
    "is_active": False,
}

EXAMPLE_BULK_REQUEST = {
    "rois": [
        {
            "name": "Zone A",
            "color": "#FF0000",
            "priority": 10,
            "is_active": True,
            "camera_width": 1280,
            "camera_height": 720,
            "points_normalized": [
                {"x": 0.0, "y": 0.0},
                {"x": 0.5, "y": 0.0},
                {"x": 0.5, "y": 0.5},
                {"x": 0.0, "y": 0.5},
            ],
        }
    ]
}
