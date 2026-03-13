"""Shared pytest fixtures for the ROI module test suite."""

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from roi_module.models import ROIBase, ROI
from roi_module.config import roi_config


# ---------------------------------------------------------------------------
# In-memory SQLite DB
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def engine():
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    ROIBase.metadata.create_all(eng)
    yield eng
    ROIBase.metadata.drop_all(eng)


@pytest.fixture(scope="function")
def db(engine):
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ---------------------------------------------------------------------------
# Sample data helpers
# ---------------------------------------------------------------------------

SQUARE_NORM = [
    {"x": 0.1, "y": 0.1},
    {"x": 0.9, "y": 0.1},
    {"x": 0.9, "y": 0.9},
    {"x": 0.1, "y": 0.9},
]

TRIANGLE_NORM = [
    {"x": 0.5, "y": 0.1},
    {"x": 0.9, "y": 0.9},
    {"x": 0.1, "y": 0.9},
]

L_SHAPE_NORM = [
    {"x": 0.1, "y": 0.1},
    {"x": 0.5, "y": 0.1},
    {"x": 0.5, "y": 0.5},
    {"x": 0.9, "y": 0.5},
    {"x": 0.9, "y": 0.9},
    {"x": 0.1, "y": 0.9},
]

SELF_INTERSECTING = [
    {"x": 0.1, "y": 0.1},
    {"x": 0.9, "y": 0.9},
    {"x": 0.9, "y": 0.1},
    {"x": 0.1, "y": 0.9},
]


def make_roi_row(db, camera_id="cam_test", name="Test ROI", points=None, is_active=True):
    from roi_module.schemas import ROICreate, PointNorm
    from roi_module.service import create_roi
    pts = points or SQUARE_NORM
    data = ROICreate(
        name=name,
        points_normalized=[PointNorm(**p) for p in pts],
        is_active=is_active,
        color="#FF0000",
        camera_width=1280,
        camera_height=720,
    )
    return create_roi(db, camera_id, data, created_by="test")
