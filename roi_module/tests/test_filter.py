"""Unit tests for roi_module.filter — detection pipeline filtering."""

import pytest
from unittest.mock import patch

from roi_module.config import roi_config, configure_roi
from roi_module.filter import filter_detections, is_detection_in_roi


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SQUARE_ROI = {
    "roi_id": "roi-square",
    "camera_id": "cam_1",
    "name": "Square",
    "points_normalized": [
        {"x": 0.2, "y": 0.2},
        {"x": 0.8, "y": 0.2},
        {"x": 0.8, "y": 0.8},
        {"x": 0.2, "y": 0.8},
    ],
    "is_active": True,
    "color": "#FF0000",
    "priority": 0,
}

CORNER_ROI = {
    "roi_id": "roi-corner",
    "camera_id": "cam_1",
    "name": "Corner",
    "points_normalized": [
        {"x": 0.7, "y": 0.7},
        {"x": 1.0, "y": 0.7},
        {"x": 1.0, "y": 1.0},
        {"x": 0.7, "y": 1.0},
    ],
    "is_active": True,
    "color": "#00FF00",
    "priority": 0,
}

# Detection whose center is at (0.5, 0.5) — inside SQUARE_ROI
DET_INSIDE = {"x1": 0.45, "y1": 0.45, "x2": 0.55, "y2": 0.55}
# Detection whose center is at (0.1, 0.1) — outside all ROIs
DET_OUTSIDE = {"x1": 0.05, "y1": 0.05, "x2": 0.15, "y2": 0.15}
# Detection in corner ROI only
DET_CORNER = {"x1": 0.75, "y1": 0.75, "x2": 0.85, "y2": 0.85}


def reset_config():
    """Reset config to safe defaults after each test."""
    configure_roi(
        filter_mode="center",
        allow_outside_fallback=True,
        iou_threshold=0.3,
        debug_mode=False,
    )


@pytest.fixture(autouse=True)
def restore_config():
    yield
    reset_config()


# ---------------------------------------------------------------------------
# is_detection_in_roi
# ---------------------------------------------------------------------------

class TestIsDetectionInROI:
    def test_center_inside(self):
        assert is_detection_in_roi(DET_INSIDE, SQUARE_ROI, 1, 1) is True

    def test_center_outside(self):
        assert is_detection_in_roi(DET_OUTSIDE, SQUARE_ROI, 1, 1) is False

    def test_iou_mode_overlap(self):
        # DET_INSIDE: 0.1×0.1 box, IoU with SQUARE (0.6×0.6) ≈ 0.027 — use low threshold
        configure_roi(filter_mode="iou", iou_threshold=0.02)
        assert is_detection_in_roi(DET_INSIDE, SQUARE_ROI, 1, 1) is True

    def test_iou_mode_no_overlap(self):
        configure_roi(filter_mode="iou", iou_threshold=0.1)
        assert is_detection_in_roi(DET_OUTSIDE, SQUARE_ROI, 1, 1) is False

    def test_pixel_coords_auto_normalized(self):
        det_px = {"x1": 576, "y1": 324, "x2": 704, "y2": 396}  # center ~(0.5, 0.5) in 1280×720
        assert is_detection_in_roi(det_px, SQUARE_ROI, 1280, 720) is True

    def test_bbox_format(self):
        det = {"bbox": [0.45, 0.45, 0.55, 0.55]}
        assert is_detection_in_roi(det, SQUARE_ROI, 1, 1) is True


# ---------------------------------------------------------------------------
# filter_detections
# ---------------------------------------------------------------------------

class TestFilterDetections:
    def test_empty_detections(self):
        kept, dropped = filter_detections([], "cam_1", 1, 1, rois=[SQUARE_ROI])
        assert kept == [] and dropped == []

    def test_all_kept_inside(self):
        kept, dropped = filter_detections(
            [DET_INSIDE], "cam_1", 1, 1, rois=[SQUARE_ROI]
        )
        assert len(kept) == 1 and len(dropped) == 0

    def test_all_dropped_outside(self):
        kept, dropped = filter_detections(
            [DET_OUTSIDE], "cam_1", 1, 1, rois=[SQUARE_ROI]
        )
        assert len(kept) == 0 and len(dropped) == 1

    def test_mixed(self):
        dets = [DET_INSIDE, DET_OUTSIDE, DET_CORNER]
        kept, dropped = filter_detections(dets, "cam_1", 1, 1, rois=[SQUARE_ROI])
        assert len(kept) == 1
        assert len(dropped) == 2

    def test_multiple_rois_union(self):
        """Detection in ANY active ROI should be kept."""
        dets = [DET_INSIDE, DET_OUTSIDE, DET_CORNER]
        kept, dropped = filter_detections(
            dets, "cam_1", 1, 1, rois=[SQUARE_ROI, CORNER_ROI]
        )
        # DET_INSIDE in SQUARE, DET_CORNER in CORNER_ROI, DET_OUTSIDE in neither
        assert len(kept) == 2
        assert len(dropped) == 1

    def test_no_rois_fallback_allow(self):
        configure_roi(allow_outside_fallback=True)
        kept, dropped = filter_detections(
            [DET_INSIDE, DET_OUTSIDE], "cam_1", 1, 1, rois=[]
        )
        assert len(kept) == 2 and len(dropped) == 0

    def test_no_rois_fallback_deny(self):
        configure_roi(allow_outside_fallback=False)
        kept, dropped = filter_detections(
            [DET_INSIDE, DET_OUTSIDE], "cam_1", 1, 1, rois=[]
        )
        assert len(kept) == 0 and len(dropped) == 2

    def test_disabled_roi_ignored(self):
        inactive_roi = {**SQUARE_ROI, "is_active": False}
        kept, dropped = filter_detections(
            [DET_INSIDE], "cam_1", 1, 1, rois=[inactive_roi]
        )
        # Only inactive ROI → fallback applies
        assert len(kept) == 1  # allow_outside_fallback=True by default

    def test_iou_mode_threshold(self):
        configure_roi(filter_mode="iou", iou_threshold=0.5)
        # DET_INSIDE is very small vs SQUARE_ROI (0.36 area) → IoU < 0.5
        kept, dropped = filter_detections(
            [DET_INSIDE], "cam_1", 1, 1, rois=[SQUARE_ROI]
        )
        # box area = 0.01, roi area = 0.36, intersection = 0.01
        # iou = 0.01 / (0.01 + 0.36 - 0.01) ≈ 0.027  → below threshold
        assert len(dropped) == 1

    def test_requires_db_or_rois(self):
        with pytest.raises(ValueError, match="db.*rois"):
            filter_detections([DET_INSIDE], "cam_1", 1, 1)

    def test_large_detection_set(self):
        """Performance: 1000 detections, 3 ROIs — should not raise."""
        import random
        dets = [
            {"x1": random.random() * 0.9, "y1": random.random() * 0.9,
             "x2": random.random() * 0.1 + 0.9, "y2": random.random() * 0.1 + 0.9}
            for _ in range(1000)
        ]
        kept, dropped = filter_detections(
            dets, "cam_1", 1, 1, rois=[SQUARE_ROI, CORNER_ROI]
        )
        assert len(kept) + len(dropped) == 1000


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_detection_on_polygon_boundary(self):
        """Boundary behaviour is implementation-defined; should not crash."""
        det_edge = {"x1": 0.19, "y1": 0.19, "x2": 0.21, "y2": 0.21}
        # Just verify it doesn't raise
        result = is_detection_in_roi(det_edge, SQUARE_ROI, 1, 1)
        assert isinstance(result, bool)

    def test_tiny_polygon(self):
        tiny_roi = {
            **SQUARE_ROI,
            "points_normalized": [
                {"x": 0.499, "y": 0.499},
                {"x": 0.501, "y": 0.499},
                {"x": 0.500, "y": 0.501},
            ],
        }
        # Detection centered at (0.5, 0.5) should be inside
        assert is_detection_in_roi(DET_INSIDE, tiny_roi, 1, 1) is True

    def test_malformed_detection_dict(self):
        """A detection missing bbox keys should not crash (treated as 0,0 box)."""
        det_empty = {}
        # Should return False (0,0 center is outside SQUARE_ROI)
        result = is_detection_in_roi(det_empty, SQUARE_ROI, 1, 1)
        assert isinstance(result, bool)
