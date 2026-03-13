"""Unit tests for roi_module.geometry."""

import pytest
from roi_module.geometry import (
    compute_iou_with_polygon,
    denormalize_points,
    is_self_intersecting,
    normalize_points,
    point_in_polygon,
    points_to_tuples,
    polygon_area,
    polygon_bounding_box,
    sutherland_hodgman_clip,
    validate_polygon,
)


# ---------------------------------------------------------------------------
# point_in_polygon
# ---------------------------------------------------------------------------

class TestPointInPolygon:
    SQUARE = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]

    def test_center_inside(self):
        assert point_in_polygon((0.5, 0.5), self.SQUARE) is True

    def test_outside_right(self):
        assert point_in_polygon((1.5, 0.5), self.SQUARE) is False

    def test_outside_above(self):
        assert point_in_polygon((0.5, 1.5), self.SQUARE) is False

    def test_outside_bottom_left(self):
        assert point_in_polygon((-0.1, -0.1), self.SQUARE) is False

    def test_triangle_center(self):
        triangle = [(0.5, 0.0), (1.0, 1.0), (0.0, 1.0)]
        assert point_in_polygon((0.5, 0.5), triangle) is True

    def test_triangle_outside(self):
        triangle = [(0.5, 0.0), (1.0, 1.0), (0.0, 1.0)]
        assert point_in_polygon((0.1, 0.1), triangle) is False

    def test_concave_inside(self):
        # L-shape
        l_shape = [
            (0.0, 0.0), (0.5, 0.0), (0.5, 0.5),
            (1.0, 0.5), (1.0, 1.0), (0.0, 1.0),
        ]
        assert point_in_polygon((0.2, 0.2), l_shape) is True
        assert point_in_polygon((0.8, 0.2), l_shape) is False  # concave cutout

    def test_pentagon(self):
        import math
        n = 5
        r = 0.4
        cx, cy = 0.5, 0.5
        pentagon = [(cx + r * math.cos(2 * math.pi * i / n - math.pi / 2),
                     cy + r * math.sin(2 * math.pi * i / n - math.pi / 2)) for i in range(n)]
        assert point_in_polygon((cx, cy), pentagon) is True
        assert point_in_polygon((cx + r + 0.1, cy), pentagon) is False


# ---------------------------------------------------------------------------
# validate_polygon
# ---------------------------------------------------------------------------

class TestValidatePolygon:
    def test_valid_square(self):
        pts = [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1},
               {"x": 0.9, "y": 0.9}, {"x": 0.1, "y": 0.9}]
        ok, _ = validate_polygon(pts)
        assert ok

    def test_too_few_points(self):
        ok, msg = validate_polygon([{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}])
        assert not ok
        assert "3" in msg

    def test_out_of_range(self):
        ok, msg = validate_polygon([
            {"x": 0.1, "y": 0.1}, {"x": 1.5, "y": 0.1}, {"x": 0.5, "y": 0.9}
        ])
        assert not ok
        assert "range" in msg.lower()

    def test_self_intersecting(self):
        # Bowtie (figure-8)
        ok, msg = validate_polygon([
            {"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.9},
            {"x": 0.9, "y": 0.1}, {"x": 0.1, "y": 0.9},
        ])
        assert not ok
        assert "self-intersect" in msg.lower()

    def test_degenerate_collinear(self):
        ok, msg = validate_polygon([
            {"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1}, {"x": 0.9, "y": 0.1}
        ])
        assert not ok
        assert "area" in msg.lower()

    def test_malformed_point(self):
        ok, msg = validate_polygon([{"x": 0.1}, {"x": 0.5, "y": 0.5}, {"x": 0.1, "y": 0.9}])
        assert not ok

    def test_valid_triangle(self):
        pts = [{"x": 0.5, "y": 0.1}, {"x": 0.9, "y": 0.9}, {"x": 0.1, "y": 0.9}]
        ok, _ = validate_polygon(pts)
        assert ok

    def test_valid_l_shape(self):
        pts = [
            {"x": 0.1, "y": 0.1}, {"x": 0.5, "y": 0.1},
            {"x": 0.5, "y": 0.5}, {"x": 0.9, "y": 0.5},
            {"x": 0.9, "y": 0.9}, {"x": 0.1, "y": 0.9},
        ]
        ok, _ = validate_polygon(pts)
        assert ok


# ---------------------------------------------------------------------------
# normalize / denormalize
# ---------------------------------------------------------------------------

class TestNormalization:
    def test_normalize_round_trip(self):
        pts_px = [{"x": 128.0, "y": 72.0}, {"x": 640.0, "y": 360.0}]
        normalized = normalize_points(pts_px, 1280, 720)
        assert normalized[0] == {"x": 0.1, "y": 0.1}
        assert normalized[1] == {"x": 0.5, "y": 0.5}

        back = denormalize_points(normalized, 1280, 720)
        assert abs(back[0]["x"] - 128.0) < 1e-6
        assert abs(back[0]["y"] - 72.0) < 1e-6

    def test_normalize_corners(self):
        pts = [{"x": 0.0, "y": 0.0}, {"x": 1280.0, "y": 720.0}]
        norm = normalize_points(pts, 1280, 720)
        assert norm[0] == {"x": 0.0, "y": 0.0}
        assert norm[1] == {"x": 1.0, "y": 1.0}

    def test_denormalize_corners(self):
        pts = [{"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 1.0}]
        px = denormalize_points(pts, 1920, 1080)
        assert px[0] == {"x": 0.0, "y": 0.0}
        assert px[1] == {"x": 1920.0, "y": 1080.0}


# ---------------------------------------------------------------------------
# polygon_area
# ---------------------------------------------------------------------------

class TestPolygonArea:
    def test_unit_square(self):
        sq = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        assert abs(polygon_area(sq) - 1.0) < 1e-9

    def test_right_triangle(self):
        tri = [(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)]
        assert abs(polygon_area(tri) - 0.5) < 1e-9

    def test_cw_same_as_ccw(self):
        ccw = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
        cw = ccw[::-1]
        assert abs(polygon_area(ccw) - polygon_area(cw)) < 1e-9


# ---------------------------------------------------------------------------
# IoU
# ---------------------------------------------------------------------------

class TestIoU:
    UNIT_SQUARE = [
        {"x": 0.0, "y": 0.0}, {"x": 1.0, "y": 0.0},
        {"x": 1.0, "y": 1.0}, {"x": 0.0, "y": 1.0},
    ]

    def test_full_overlap(self):
        bbox = (0.0, 0.0, 1.0, 1.0)
        iou = compute_iou_with_polygon(bbox, self.UNIT_SQUARE)
        assert abs(iou - 1.0) < 1e-6

    def test_no_overlap(self):
        bbox = (1.5, 1.5, 2.0, 2.0)
        iou = compute_iou_with_polygon(bbox, self.UNIT_SQUARE)
        assert iou == 0.0

    def test_half_overlap(self):
        # bbox covers right half of the unit square
        bbox = (0.5, 0.0, 1.5, 1.0)
        iou = compute_iou_with_polygon(bbox, self.UNIT_SQUARE)
        # intersection=0.5, box_area=1.0, roi_area=1.0 → union=1.5 → IoU≈0.333
        assert abs(iou - 1 / 3) < 1e-5

    def test_bbox_inside_polygon(self):
        bbox = (0.2, 0.2, 0.8, 0.8)
        iou = compute_iou_with_polygon(bbox, self.UNIT_SQUARE)
        # intersection = 0.36, polygon = 1.0, box = 0.36, union = 1.0
        assert abs(iou - 0.36) < 1e-5

    def test_tiny_polygon(self):
        tiny = [
            {"x": 0.4, "y": 0.4}, {"x": 0.6, "y": 0.4},
            {"x": 0.6, "y": 0.6}, {"x": 0.4, "y": 0.6},
        ]
        # Detection that fully covers the tiny polygon
        bbox = (0.0, 0.0, 1.0, 1.0)
        iou = compute_iou_with_polygon(bbox, tiny)
        assert iou > 0.0
        assert iou < 0.05  # tiny polygon → small IoU

    def test_edge_touching(self):
        # Detection box shares only an edge with the polygon
        bbox = (1.0, 0.0, 2.0, 1.0)
        iou = compute_iou_with_polygon(bbox, self.UNIT_SQUARE)
        assert iou == 0.0  # edge touch = zero area intersection


# ---------------------------------------------------------------------------
# polygon_bounding_box
# ---------------------------------------------------------------------------

class TestBoundingBox:
    def test_square(self):
        pts = [{"x": 0.1, "y": 0.2}, {"x": 0.8, "y": 0.2},
               {"x": 0.8, "y": 0.7}, {"x": 0.1, "y": 0.7}]
        x1, y1, x2, y2 = polygon_bounding_box(pts)
        assert (x1, y1, x2, y2) == (0.1, 0.2, 0.8, 0.7)
