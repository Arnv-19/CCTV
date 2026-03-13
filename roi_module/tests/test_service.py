"""Integration tests for roi_module.service — full CRUD lifecycle via SQLite."""

import pytest

from roi_module.exceptions import InvalidPolygonError, ROILimitExceededError, ROINotFoundError
from roi_module.schemas import ROICreate, ROIUpdate, PointNorm, BulkReplaceRequest
from roi_module.service import (
    bulk_replace_rois,
    create_roi,
    delete_roi,
    get_camera_rois,
    get_roi_by_id,
    toggle_roi,
    update_roi,
)
from roi_module.config import configure_roi

from .conftest import SQUARE_NORM, TRIANGLE_NORM, SELF_INTERSECTING, make_roi_row


def _make_payload(name="Zone A", points=None, is_active=True, color="#FF0000"):
    pts = points or SQUARE_NORM
    return ROICreate(
        name=name,
        points_normalized=[PointNorm(**p) for p in pts],
        is_active=is_active,
        color=color,
        camera_width=1280,
        camera_height=720,
    )


# ---------------------------------------------------------------------------
# Create
# ---------------------------------------------------------------------------

class TestCreate:
    def test_basic_create(self, db):
        roi = create_roi(db, "cam_1", _make_payload(), created_by="alice")
        assert roi.roi_id is not None
        assert roi.camera_id == "cam_1"
        assert roi.name == "Zone A"
        assert roi.created_by == "alice"
        assert roi.is_active is True
        assert len(roi.points_normalized) == 4

    def test_create_triangle(self, db):
        roi = create_roi(db, "cam_1", _make_payload(points=TRIANGLE_NORM))
        assert len(roi.points_normalized) == 3

    def test_create_self_intersecting_fails(self, db):
        with pytest.raises(InvalidPolygonError, match="self-intersect"):
            create_roi(db, "cam_1", _make_payload(points=SELF_INTERSECTING))

    def test_create_too_few_points_fails(self, db):
        # Pydantic validates min_length=3 before reaching create_roi → ValidationError
        from pydantic import ValidationError
        bad_pts = [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.1}]
        with pytest.raises((InvalidPolygonError, ValidationError)):
            create_roi(db, "cam_1", _make_payload(points=bad_pts))

    def test_create_exceeds_per_camera_limit(self, db):
        configure_roi(max_rois_per_camera=2)
        create_roi(db, "cam_limit", _make_payload("Z1"))
        create_roi(db, "cam_limit", _make_payload("Z2"))
        with pytest.raises(ROILimitExceededError):
            create_roi(db, "cam_limit", _make_payload("Z3"))
        configure_roi(max_rois_per_camera=10)  # restore

    def test_create_stores_normalized_coords(self, db):
        roi = create_roi(db, "cam_1", _make_payload())
        for pt in roi.points_normalized:
            assert 0.0 <= pt["x"] <= 1.0
            assert 0.0 <= pt["y"] <= 1.0


# ---------------------------------------------------------------------------
# Read
# ---------------------------------------------------------------------------

class TestRead:
    def test_get_existing(self, db):
        roi = make_roi_row(db)
        fetched = get_roi_by_id(db, roi.roi_id)
        assert fetched.roi_id == roi.roi_id

    def test_get_not_found(self, db):
        with pytest.raises(ROINotFoundError):
            get_roi_by_id(db, "nonexistent-id")

    def test_list_all(self, db):
        make_roi_row(db, name="R1")
        make_roi_row(db, name="R2")
        make_roi_row(db, camera_id="cam_other", name="Other")
        rois = get_camera_rois(db, "cam_test")
        assert len(rois) == 2

    def test_list_active_only(self, db):
        make_roi_row(db, name="Active", is_active=True)
        make_roi_row(db, name="Inactive", is_active=False)
        active = get_camera_rois(db, "cam_test", active_only=True)
        assert all(r.is_active for r in active)

    def test_empty_camera(self, db):
        rois = get_camera_rois(db, "cam_does_not_exist")
        assert rois == []


# ---------------------------------------------------------------------------
# Update
# ---------------------------------------------------------------------------

class TestUpdate:
    def test_rename(self, db):
        roi = make_roi_row(db, name="Old")
        updated = update_roi(db, roi.roi_id, ROIUpdate(name="New"))
        assert updated.name == "New"

    def test_update_points(self, db):
        roi = make_roi_row(db)
        new_pts = [PointNorm(**p) for p in TRIANGLE_NORM]
        updated = update_roi(db, roi.roi_id, ROIUpdate(points_normalized=new_pts))
        assert len(updated.points_normalized) == 3

    def test_update_invalid_points(self, db):
        roi = make_roi_row(db)
        bad_pts = [PointNorm(**p) for p in [
            {"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.9},
            {"x": 0.9, "y": 0.1}, {"x": 0.1, "y": 0.9},
        ]]
        with pytest.raises(InvalidPolygonError):
            update_roi(db, roi.roi_id, ROIUpdate(points_normalized=bad_pts))

    def test_update_color(self, db):
        roi = make_roi_row(db)
        updated = update_roi(db, roi.roi_id, ROIUpdate(color="#0000FF"))
        assert updated.color == "#0000FF"

    def test_update_not_found(self, db):
        with pytest.raises(ROINotFoundError):
            update_roi(db, "ghost-id", ROIUpdate(name="X"))

    def test_partial_update_preserves_other_fields(self, db):
        roi = make_roi_row(db, name="Preserve")
        update_roi(db, roi.roi_id, ROIUpdate(color="#ABCDEF"))
        fetched = get_roi_by_id(db, roi.roi_id)
        assert fetched.name == "Preserve"  # unchanged


# ---------------------------------------------------------------------------
# Delete
# ---------------------------------------------------------------------------

class TestDelete:
    def test_delete(self, db):
        roi = make_roi_row(db)
        roi_id = roi.roi_id
        delete_roi(db, roi_id)
        with pytest.raises(ROINotFoundError):
            get_roi_by_id(db, roi_id)

    def test_delete_not_found(self, db):
        with pytest.raises(ROINotFoundError):
            delete_roi(db, "ghost-id")

    def test_delete_only_affects_target(self, db):
        r1 = make_roi_row(db, name="R1")
        r2 = make_roi_row(db, name="R2")
        delete_roi(db, r1.roi_id)
        remaining = get_camera_rois(db, "cam_test")
        assert len(remaining) == 1
        assert remaining[0].roi_id == r2.roi_id


# ---------------------------------------------------------------------------
# Toggle
# ---------------------------------------------------------------------------

class TestToggle:
    def test_toggle_active_to_inactive(self, db):
        roi = make_roi_row(db, is_active=True)
        toggled = toggle_roi(db, roi.roi_id)
        assert toggled.is_active is False

    def test_toggle_inactive_to_active(self, db):
        roi = make_roi_row(db, is_active=False)
        toggled = toggle_roi(db, roi.roi_id)
        assert toggled.is_active is True

    def test_double_toggle_restores(self, db):
        roi = make_roi_row(db, is_active=True)
        toggle_roi(db, roi.roi_id)
        restored = toggle_roi(db, roi.roi_id)
        assert restored.is_active is True

    def test_toggle_not_found(self, db):
        with pytest.raises(ROINotFoundError):
            toggle_roi(db, "ghost-id")


# ---------------------------------------------------------------------------
# Bulk replace
# ---------------------------------------------------------------------------

class TestBulkReplace:
    def test_replaces_all(self, db):
        make_roi_row(db, name="Old 1")
        make_roi_row(db, name="Old 2")

        new_rois = [
            ROICreate(
                name="New 1",
                points_normalized=[PointNorm(**p) for p in SQUARE_NORM],
                color="#FF0000",
            ),
        ]
        result = bulk_replace_rois(db, "cam_test", new_rois)
        all_rois = get_camera_rois(db, "cam_test")
        assert len(all_rois) == 1
        assert all_rois[0].name == "New 1"

    def test_bulk_empty_clears(self, db):
        make_roi_row(db, name="Existing")
        bulk_replace_rois(db, "cam_test", [])
        assert get_camera_rois(db, "cam_test") == []

    def test_bulk_invalid_polygon_rolls_back(self, db):
        make_roi_row(db, name="Pre-existing")
        bad = ROICreate(
            name="Bad",
            points_normalized=[PointNorm(**p) for p in SELF_INTERSECTING],
            color="#FF0000",
        )
        with pytest.raises(InvalidPolygonError):
            bulk_replace_rois(db, "cam_test", [bad])
        # Original ROI should still exist (atomic)
        rois = get_camera_rois(db, "cam_test")
        assert len(rois) == 1

    def test_bulk_exceeds_limit(self, db):
        configure_roi(max_rois_per_camera=2)
        payloads = [
            ROICreate(
                name=f"Z{i}",
                points_normalized=[PointNorm(**p) for p in SQUARE_NORM],
                color="#FF0000",
            )
            for i in range(3)
        ]
        with pytest.raises(ROILimitExceededError):
            bulk_replace_rois(db, "cam_test", payloads)
        configure_roi(max_rois_per_camera=10)


# ---------------------------------------------------------------------------
# Detection pass-through when ROI disabled
# ---------------------------------------------------------------------------

class TestDetectionPassThrough:
    """Integration: disable ROI → filter_detections passes all through."""

    def test_inactive_roi_allows_all_detections(self, db):
        from roi_module.filter import filter_detections
        from roi_module.config import configure_roi

        make_roi_row(db, is_active=False)

        detections = [
            {"x1": 0.1, "y1": 0.1, "x2": 0.15, "y2": 0.15},
            {"x1": 0.5, "y1": 0.5, "x2": 0.6, "y2": 0.6},
        ]

        kept, dropped = filter_detections(
            detections, "cam_test", 1, 1, db=db
        )
        assert len(kept) == 2  # fallback = allow all
        assert len(dropped) == 0
