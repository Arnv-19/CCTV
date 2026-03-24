import uuid
from datetime import datetime as real_datetime

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.routes import burglar_alarm as ba
from app.db.database import Base
from app.db.models import ROI, User


@pytest.fixture()
def app_and_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    app = FastAPI()
    app.include_router(ba.router, prefix="/api/burglar-alarm")

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    admin = User(
        id=1,
        username="admin",
        email="admin@example.com",
        password_hash="x",
        role="admin",
        is_active=True,
    )
    operator = User(
        id=2,
        username="operator",
        email="operator@example.com",
        password_hash="x",
        role="operator",
        is_active=True,
    )

    def override_current_user_admin():
        return admin

    def override_current_user_operator():
        return operator

    def override_require_admin_ok():
        return admin

    def override_require_admin_forbidden():
        raise HTTPException(status_code=403, detail="Admin access required")

    app.dependency_overrides[ba.get_db] = override_get_db
    app.dependency_overrides[ba.get_current_user] = override_current_user_admin
    app.dependency_overrides[ba.require_admin] = override_require_admin_ok

    client = TestClient(app)

    return {
        "app": app,
        "client": client,
        "Session": TestingSessionLocal,
        "admin_user": admin,
        "operator_user": operator,
        "override_current_user_admin": override_current_user_admin,
        "override_current_user_operator": override_current_user_operator,
        "override_require_admin_ok": override_require_admin_ok,
        "override_require_admin_forbidden": override_require_admin_forbidden,
    }


def _upsert_cam1(client, **kwargs):
    body = {
        "alarm_enabled": True,
        "alarm_start_time": "20:00",
        "alarm_end_time": "06:00",
        "cooldown_sec": 30,
    }
    body.update(kwargs)
    return client.put("/api/burglar-alarm/1", json=body)


def _hhmm(total_minutes):
    h = (total_minutes // 60) % 24
    m = total_minutes % 60
    return f"{h:02d}:{m:02d}"


def test_01_create_config_put_returns_200_and_object(app_and_db):
    client = app_and_db["client"]
    r = _upsert_cam1(client)
    assert r.status_code == 200
    j = r.json()
    assert j["camera_id"] == 1
    assert j["alarm_enabled"] is True
    assert j["alarm_start_time"] == "20:00"
    assert j["alarm_end_time"] == "06:00"
    assert j["cooldown_sec"] == 30


def test_02_get_config(app_and_db):
    client = app_and_db["client"]
    _upsert_cam1(client)

    r = client.get("/api/burglar-alarm/1")
    assert r.status_code == 200
    j = r.json()
    assert j["alarm_enabled"] is True
    assert j["alarm_start_time"] == "20:00"


def test_03_list_all_configs(app_and_db):
    client = app_and_db["client"]
    _upsert_cam1(client)

    r = client.get("/api/burglar-alarm/")
    assert r.status_code == 200
    arr = r.json()
    assert isinstance(arr, list)
    assert any(c["camera_id"] == 1 for c in arr)


def test_04_status_inside_window(app_and_db):
    client = app_and_db["client"]

    now = real_datetime.now()
    now_min = now.hour * 60 + now.minute
    start = _hhmm((now_min - 30) % (24 * 60))
    end = _hhmm((now_min + 30) % (24 * 60))

    # Keep this test deterministic: force a non-overnight active window.
    if start > end:
        start = _hhmm(max(now_min - 30, 0))
        end = _hhmm(min(now_min + 30, 23 * 60 + 59))

    _upsert_cam1(client, alarm_enabled=True, alarm_start_time=start, alarm_end_time=end)

    r = client.get("/api/burglar-alarm/1/status")
    assert r.status_code == 200
    j = r.json()
    assert j["configured"] is True
    assert j["alarm_enabled"] is True
    assert j["window_active"] is True
    assert j["active_now"] is True


def test_05_status_outside_window(app_and_db):
    client = app_and_db["client"]

    now = real_datetime.now()
    now_min = now.hour * 60 + now.minute
    start = _hhmm((now_min + 120) % (24 * 60))
    end = _hhmm((now_min + 180) % (24 * 60))

    # Avoid accidental overnight ranges for this specific assertion.
    if start > end:
        start = "01:00"
        end = "02:00"

    _upsert_cam1(client, alarm_enabled=True, alarm_start_time=start, alarm_end_time=end)

    r = client.get("/api/burglar-alarm/1/status")
    assert r.status_code == 200
    j = r.json()
    assert j["window_active"] is False
    assert j["active_now"] is False


def test_06_disable_alarm_forces_active_now_false(app_and_db):
    client = app_and_db["client"]

    # Full-day window means window_active=True by implementation.
    _upsert_cam1(
        client,
        alarm_enabled=False,
        alarm_start_time="20:00",
        alarm_end_time="20:00",
        cooldown_sec=30,
    )

    r = client.get("/api/burglar-alarm/1/status")
    assert r.status_code == 200
    j = r.json()
    assert j["window_active"] is True
    assert j["active_now"] is False


def test_07_status_unconfigured_camera(app_and_db):
    client = app_and_db["client"]

    r = client.get("/api/burglar-alarm/999/status")
    assert r.status_code == 200
    assert r.json() == {"configured": False, "active_now": False}


def test_08_get_unconfigured_camera_404(app_and_db):
    client = app_and_db["client"]

    r = client.get("/api/burglar-alarm/999")
    assert r.status_code == 404


def test_09_invalid_time_format_422(app_and_db):
    client = app_and_db["client"]

    r = client.put(
        "/api/burglar-alarm/1",
        json={"alarm_start_time": "8pm", "alarm_end_time": "6am"},
    )
    assert r.status_code == 422


def test_10_negative_cooldown_422(app_and_db):
    client = app_and_db["client"]

    r = client.put("/api/burglar-alarm/1", json={"cooldown_sec": -5})
    assert r.status_code == 422


def test_11_invalid_roi_zone_id_404(app_and_db):
    client = app_and_db["client"]

    r = _upsert_cam1(client, monitored_zone_id="nonexistent-zone-uuid")
    assert r.status_code == 404
    assert "ROI zone" in r.json()["detail"]


def test_12_delete_config_then_get_404(app_and_db):
    client = app_and_db["client"]
    _upsert_cam1(client)

    r_del = client.delete("/api/burglar-alarm/1")
    assert r_del.status_code == 200
    assert r_del.json() == {"message": "Burglar alarm config for camera 1 deleted"}

    r_get = client.get("/api/burglar-alarm/1")
    assert r_get.status_code == 404


def test_13_non_admin_cannot_create_delete_but_can_read(app_and_db):
    app = app_and_db["app"]
    client = app_and_db["client"]

    # First create as admin so a read target exists.
    _upsert_cam1(client)

    # Switch to operator context.
    app.dependency_overrides[ba.get_current_user] = app_and_db["override_current_user_operator"]
    app.dependency_overrides[ba.require_admin] = app_and_db["override_require_admin_forbidden"]

    r_put = _upsert_cam1(client, alarm_enabled=True)
    assert r_put.status_code == 403

    r_del = client.delete("/api/burglar-alarm/1")
    assert r_del.status_code == 403

    # Read is guarded by get_current_user only, so still allowed.
    r_get = client.get("/api/burglar-alarm/1")
    assert r_get.status_code == 200


def test_14_overnight_window_logic(app_and_db, monkeypatch):
    client = app_and_db["client"]
    _upsert_cam1(client, alarm_enabled=True, alarm_start_time="23:00", alarm_end_time="01:00")

    # Monkeypatch route helper so status uses deterministic times.
    from app.services import burglar_alarm_service as bas

    class FakeDateTimeMidnight:
        @classmethod
        def now(cls):
            return real_datetime(2026, 3, 17, 0, 0, 0)

    class FakeDateTimeNoon:
        @classmethod
        def now(cls):
            return real_datetime(2026, 3, 17, 12, 0, 0)

    monkeypatch.setattr(bas, "datetime", FakeDateTimeMidnight)
    monkeypatch.setattr(ba, "is_in_alarm_window", bas.is_in_alarm_window)
    r_midnight = client.get("/api/burglar-alarm/1/status")
    assert r_midnight.status_code == 200
    assert r_midnight.json()["active_now"] is True

    monkeypatch.setattr(bas, "datetime", FakeDateTimeNoon)
    monkeypatch.setattr(ba, "is_in_alarm_window", bas.is_in_alarm_window)
    r_noon = client.get("/api/burglar-alarm/1/status")
    assert r_noon.status_code == 200
    assert r_noon.json()["active_now"] is False


def test_11b_valid_roi_zone_id_accepts_config(app_and_db):
    client = app_and_db["client"]
    Session = app_and_db["Session"]

    zone_id = str(uuid.uuid4())
    with Session() as db:
        db.add(
            ROI(
                roi_id=zone_id,
                camera_id="1",
                name="Zone 1",
                points_normalized=[
                    {"x": 0.1, "y": 0.1},
                    {"x": 0.9, "y": 0.1},
                    {"x": 0.9, "y": 0.9},
                    {"x": 0.1, "y": 0.9},
                ],
                is_active=True,
                color="#FF0000",
                priority=0,
            )
        )
        db.commit()

    r = _upsert_cam1(client, monitored_zone_id=zone_id)
    assert r.status_code == 200
    assert r.json()["monitored_zone_id"] == zone_id
