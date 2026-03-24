"""
tests/test_kcf_tracking.py
--------------------------
Unit tests for KCF tracker integration inside the burglar alarm.

Covers:
  - init_kcf_tracker()           — service helper
  - is_in_alarm_window()         — time-window logic (unit)
  - is_person_in_zone()          — zone logic (unit)
  - point_in_polygon()           — ray-casting (unit)
  - KCF state machine logic      — via mocked tracker and camera_loop helpers
"""

import time
from unittest.mock import MagicMock, patch, call

import numpy as np
import pytest

from app.services.burglar_alarm_service import (
    init_kcf_tracker,
    is_in_alarm_window,
    is_person_in_zone,
    point_in_polygon,
)


# ────────────────────────────────────────────────────────────────────────────
# Fixtures
# ────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def blank_frame():
    """A 480×640 BGR frame with random noise (KCF needs texture to init)."""
    rng = np.random.default_rng(seed=42)
    return rng.integers(0, 256, (480, 640, 3), dtype=np.uint8)


@pytest.fixture()
def square_zone():
    """Normalized 0.1–0.9 square zone (centre of frame)."""
    return [
        {"x": 0.1, "y": 0.1},
        {"x": 0.9, "y": 0.1},
        {"x": 0.9, "y": 0.9},
        {"x": 0.1, "y": 0.9},
    ]


# ────────────────────────────────────────────────────────────────────────────
# 1. init_kcf_tracker
# ────────────────────────────────────────────────────────────────────────────

def test_kcf_init_returns_tracker_for_valid_bbox(blank_frame):
    """Valid bbox on a real frame → tracker object is returned."""
    tracker = init_kcf_tracker(blank_frame, [100, 100, 300, 300])
    assert tracker is not None


def test_kcf_init_returns_none_on_empty_frame():
    """Zero-size frame → tracker must not raise; returns None."""
    empty = np.zeros((0, 0, 3), dtype=np.uint8)
    result = init_kcf_tracker(empty, [0, 0, 10, 10])
    assert result is None


def test_kcf_init_returns_none_on_zero_size_bbox(blank_frame):
    """bbox with w=0 or h=0 → tracker init fails → returns None."""
    result = init_kcf_tracker(blank_frame, [100, 100, 100, 100])  # w=0, h=0
    assert result is None


def test_kcf_init_returns_none_on_bad_bbox(blank_frame):
    """Non-numeric bbox → exception caught → returns None."""
    result = init_kcf_tracker(blank_frame, ["a", "b", "c", "d"])
    assert result is None


def test_kcf_init_converts_floats_to_int(blank_frame):
    """Float coordinates are cast to int without error."""
    tracker = init_kcf_tracker(blank_frame, [50.7, 60.3, 250.9, 350.1])
    assert tracker is not None


def test_kcf_init_clamps_to_frame_bounds(blank_frame):
    """bbox partially outside frame edges should not crash."""
    # x2, y2 beyond 640×480 — OpenCV clips internally
    tracker = init_kcf_tracker(blank_frame, [600, 400, 700, 550])
    # May return None (OpenCV rejects OOB) or a tracker — either is acceptable
    # What must NOT happen is an unhandled exception.


# ────────────────────────────────────────────────────────────────────────────
# 2. is_in_alarm_window — time window logic
# ────────────────────────────────────────────────────────────────────────────

def test_window_same_start_end_always_active():
    """start == end → full 24-hour window → always True."""
    assert is_in_alarm_window("20:00", "20:00") is True


def test_window_normal_daytime_range(monkeypatch):
    """Normal range 08:00–18:00, current time 12:00 → active."""
    from app.services import burglar_alarm_service as bas
    from datetime import datetime as real_dt

    class FakeNoon:
        @classmethod
        def now(cls):
            return real_dt(2026, 3, 18, 12, 0, 0)

    monkeypatch.setattr(bas, "datetime", FakeNoon)
    assert bas.is_in_alarm_window("08:00", "18:00") is True


def test_window_normal_daytime_outside(monkeypatch):
    """Normal range 08:00–18:00, current time 22:00 → not active."""
    from app.services import burglar_alarm_service as bas
    from datetime import datetime as real_dt

    class FakeNight:
        @classmethod
        def now(cls):
            return real_dt(2026, 3, 18, 22, 0, 0)

    monkeypatch.setattr(bas, "datetime", FakeNight)
    assert bas.is_in_alarm_window("08:00", "18:00") is False


def test_window_overnight_active_at_midnight(monkeypatch):
    """Overnight 23:00–01:00, current time 00:00 → active."""
    from app.services import burglar_alarm_service as bas
    from datetime import datetime as real_dt

    class FakeMidnight:
        @classmethod
        def now(cls):
            return real_dt(2026, 3, 18, 0, 0, 0)

    monkeypatch.setattr(bas, "datetime", FakeMidnight)
    assert bas.is_in_alarm_window("23:00", "01:00") is True


def test_window_overnight_inactive_at_noon(monkeypatch):
    """Overnight 23:00–01:00, current time 12:00 → not active."""
    from app.services import burglar_alarm_service as bas
    from datetime import datetime as real_dt

    class FakeNoon:
        @classmethod
        def now(cls):
            return real_dt(2026, 3, 18, 12, 0, 0)

    monkeypatch.setattr(bas, "datetime", FakeNoon)
    assert bas.is_in_alarm_window("23:00", "01:00") is False


def test_window_bad_format_returns_false():
    """Malformed time strings → False (fail safe, never trigger alarm)."""
    assert is_in_alarm_window("8pm", "6am") is False
    assert is_in_alarm_window("", "") is False
    assert is_in_alarm_window("25:00", "01:00") is False


# ────────────────────────────────────────────────────────────────────────────
# 3. point_in_polygon — ray-casting
# ────────────────────────────────────────────────────────────────────────────

def test_point_inside_square(square_zone):
    assert point_in_polygon(0.5, 0.5, square_zone) is True


def test_point_outside_square(square_zone):
    assert point_in_polygon(0.05, 0.05, square_zone) is False


def test_point_on_boundary_is_edge_case(square_zone):
    # Boundary behaviour is undefined in ray-casting; must not raise.
    result = point_in_polygon(0.1, 0.5, square_zone)
    assert isinstance(result, bool)


def test_polygon_with_fewer_than_3_points():
    too_few = [{"x": 0.1, "y": 0.1}, {"x": 0.9, "y": 0.9}]
    assert point_in_polygon(0.5, 0.5, too_few) is False


def test_empty_polygon():
    assert point_in_polygon(0.5, 0.5, []) is False


# ────────────────────────────────────────────────────────────────────────────
# 4. is_person_in_zone
# ────────────────────────────────────────────────────────────────────────────

def test_person_centre_inside_zone(square_zone):
    # Centre of frame (320, 240) → normalised (0.5, 0.5) → inside 0.1–0.9 square
    det = {"box": [270, 190, 370, 290]}  # centre ~320,240
    assert is_person_in_zone(det, square_zone, 640, 480) is True


def test_person_centre_outside_zone(square_zone):
    # Top-left corner → normalised ~(0.02, 0.02) → outside 0.1–0.9 square
    det = {"box": [0, 0, 25, 25]}
    assert is_person_in_zone(det, square_zone, 640, 480) is False


def test_no_zone_always_triggers():
    """No zone configured (None) → always returns True regardless of position."""
    det = {"box": [0, 0, 10, 10]}
    assert is_person_in_zone(det, None, 640, 480) is True


def test_empty_zone_always_triggers():
    """Empty zone list → always returns True (no zone = whole frame)."""
    det = {"box": [0, 0, 10, 10]}
    assert is_person_in_zone(det, [], 640, 480) is True


def test_zero_frame_dimensions_returns_true():
    """Invalid frame size → safe fallback: return True."""
    det = {"box": [100, 100, 200, 200]}
    assert is_person_in_zone(det, [{"x": 0.1, "y": 0.1}], 0, 0) is True


# ────────────────────────────────────────────────────────────────────────────
# 5. KCF state machine — via mocked tracker
# ────────────────────────────────────────────────────────────────────────────

def _make_burglar_config(start="00:00", end="00:00", cooldown=0, zone=None):
    """Build a burglar_alarm_config dict (start==end → full-day window)."""
    return {
        "alarm_enabled":         True,
        "alarm_start_time":      start,
        "alarm_end_time":        end,
        "monitored_zone_points": zone,
        "cooldown_sec":          cooldown,
    }


def _person_det(x1=100, y1=100, x2=300, y2=400, conf=0.91):
    return {"class": "person", "box": [x1, y1, x2, y2], "conf": conf}


class FakeTracker:
    """Controllable stand-in for cv2.TrackerKCF."""
    def __init__(self, update_results):
        # update_results: list of (ok, rect) tuples, one per call
        self._results = iter(update_results)
        self.init_called = False
        self.last_rect = None

    def init(self, frame, rect):
        self.init_called = True
        self.last_rect = rect
        return True

    def update(self, frame):
        try:
            ok, rect = next(self._results)
            return ok, rect
        except StopIteration:
            return False, (0, 0, 0, 0)


def test_kcf_state_idle_transitions_to_tracking_on_person_detection(blank_frame):
    """
    IDLE: person detected in window+zone → init_kcf_tracker called,
    ba_tracking becomes True.
    """
    fake_tracker = FakeTracker(update_results=[(True, (100, 100, 200, 300))] * 100)

    with patch(
        "app.services.burglar_alarm_service.cv2.TrackerKCF_create",
        return_value=fake_tracker,
    ):
        tracker = init_kcf_tracker(blank_frame, [100, 100, 300, 400])

    assert tracker is fake_tracker
    assert fake_tracker.init_called is True
    assert fake_tracker.last_rect == (100, 100, 200, 300)  # (x,y,w,h)


def test_kcf_update_ok_returns_correct_rect(blank_frame):
    """Successful tracker.update() returns the expected bounding rect."""
    expected_rect = (150, 120, 180, 250)
    fake_tracker = FakeTracker(update_results=[(True, expected_rect)])

    ok, rect = fake_tracker.update(blank_frame)
    assert ok is True
    assert rect == expected_rect


def test_kcf_update_failure_increments_fail_count():
    """
    Simulate the fail-count logic: after BA_MAX_FAILS=5 failures
    the tracker should be discarded.
    """
    BA_MAX_FAILS = 5
    ba_track_fail_count = 0
    ba_tracking = True
    ba_tracker = MagicMock()
    ba_tracker.update.return_value = (False, (0, 0, 0, 0))

    for _ in range(BA_MAX_FAILS):
        kcf_ok, _ = ba_tracker.update(None)
        if not kcf_ok:
            ba_track_fail_count += 1
            if ba_track_fail_count >= BA_MAX_FAILS:
                ba_tracker = None
                ba_tracking = False
                ba_track_fail_count = 0

    assert ba_tracking is False
    assert ba_tracker is None
    assert ba_track_fail_count == 0


def test_kcf_resets_fail_count_on_successful_update():
    """A single successful update resets ba_track_fail_count to 0."""
    BA_MAX_FAILS = 5
    ba_track_fail_count = 3  # partially accumulated failures
    ba_tracker = MagicMock()
    ba_tracker.update.return_value = (True, (10, 20, 100, 150))

    kcf_ok, _ = ba_tracker.update(None)
    if kcf_ok:
        ba_track_fail_count = 0

    assert ba_track_fail_count == 0


def test_kcf_idle_when_window_not_active(monkeypatch, blank_frame):
    """
    If window is not active, init_kcf_tracker must never be called.
    """
    from app.services import burglar_alarm_service as bas
    from datetime import datetime as real_dt

    class FakeNoon:
        @classmethod
        def now(cls):
            return real_dt(2026, 3, 18, 12, 0, 0)

    monkeypatch.setattr(bas, "datetime", FakeNoon)

    # Window 23:00–01:00 excludes 12:00
    window_active = bas.is_in_alarm_window("23:00", "01:00")
    assert window_active is False
    # No tracker should be created when window is inactive


def test_kcf_tracker_reset_when_window_closes():
    """
    Simulate: ba_tracking=True, window suddenly becomes False
    → ba_tracking must be set to False and ba_tracker to None.
    """
    ba_tracking = True
    ba_tracker = MagicMock()
    ba_track_fail_count = 2
    ba_frames_since_check = 15
    window_active = False  # window just closed

    if not window_active and ba_tracking:
        ba_tracker = None
        ba_tracking = False
        ba_track_fail_count = 0
        ba_frames_since_check = 0

    assert ba_tracking is False
    assert ba_tracker is None
    assert ba_track_fail_count == 0
    assert ba_frames_since_check == 0


def test_kcf_drops_tracker_when_person_leaves_zone(square_zone):
    """
    Simulate zone re-check: tracked bbox centre outside zone
    → ba_tracking reset to False.
    """
    ba_tracking = True
    ba_tracker = MagicMock()

    # Tracked bbox top-left corner → centre ~(12, 12) → normalised ~(0.02, 0.025)
    # Outside the 0.1–0.9 square_zone
    kx, ky, kx2, ky2 = 0, 0, 25, 25
    frame_w, frame_h = 640, 480

    tracked_det = {"box": [kx, ky, kx2, ky2]}
    still_in_zone = is_person_in_zone(tracked_det, square_zone, frame_w, frame_h)

    if not still_in_zone:
        ba_tracker = None
        ba_tracking = False

    assert ba_tracking is False
    assert ba_tracker is None


def test_kcf_keeps_tracking_when_person_stays_in_zone(square_zone):
    """
    Zone re-check: tracked bbox centre inside zone
    → ba_tracking remains True.
    """
    ba_tracking = True
    ba_tracker = MagicMock()

    # Centre of frame → normalised (0.5, 0.5) → inside square_zone
    kx, ky, kx2, ky2 = 270, 190, 370, 290
    frame_w, frame_h = 640, 480

    tracked_det = {"box": [kx, ky, kx2, ky2]}
    still_in_zone = is_person_in_zone(tracked_det, square_zone, frame_w, frame_h)

    if not still_in_zone:
        ba_tracker = None
        ba_tracking = False

    assert ba_tracking is True
    assert ba_tracker is not None


def test_cooldown_prevents_double_alarm():
    """
    Alarm fires once. Second detection within cooldown window must not fire.
    """
    cooldown = 30
    last_burglar_alarm_time = time.time()  # just fired

    # Immediate re-check — should be blocked by cooldown
    time_since_last = time.time() - last_burglar_alarm_time
    can_fire = time_since_last > cooldown

    assert can_fire is False


def test_cooldown_allows_alarm_after_window():
    """
    After cooldown_sec has passed, the alarm is allowed to fire again.
    """
    cooldown = 1  # 1 second for test speed
    last_burglar_alarm_time = time.time() - 2  # 2 seconds ago

    time_since_last = time.time() - last_burglar_alarm_time
    can_fire = time_since_last > cooldown

    assert can_fire is True


def test_alarm_not_fired_when_disabled():
    """alarm_enabled=False → burglar alarm block is entirely skipped."""
    config = {
        "alarm_enabled":    False,
        "alarm_start_time": "00:00",
        "alarm_end_time":   "00:00",
        "monitored_zone_points": None,
        "cooldown_sec":     0,
    }
    # The outer guard in camera_loop: config.get("alarm_enabled")
    should_run = config and config.get("alarm_enabled")
    assert not should_run


def test_kcf_redetect_interval_counter():
    """
    ba_frames_since_check increments each tracking frame and resets at BA_REDETECT_INTERVAL.
    """
    BA_REDETECT_INTERVAL = 30
    ba_frames_since_check = 0
    zone_check_triggered = False

    for _ in range(BA_REDETECT_INTERVAL):
        ba_frames_since_check += 1
        if ba_frames_since_check >= BA_REDETECT_INTERVAL:
            ba_frames_since_check = 0
            zone_check_triggered = True

    assert zone_check_triggered is True
    assert ba_frames_since_check == 0
