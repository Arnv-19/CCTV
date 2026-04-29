from __future__ import annotations

from datetime import date, datetime, time

from app.db.database import SessionLocal, engine
from app.db.models import Alert


def main() -> None:
    if engine is None:
        raise SystemExit("Database is not connected. Fix DB_* settings in .env first.")

    report_date = date.today()
    rows = [
        Alert(
            camera_id=1,
            model_name="ppe_monitor",
            violation_type="no_helmet",
            confidence_score=0.94,
            snapshot_path="snapshots/cam_0/violation_seed_01.jpg",
            triggered_at=datetime.combine(report_date, time(12, 3, 24)),
            buzzer_activated=False,
        ),
        Alert(
            camera_id=1,
            model_name="ppe_monitor",
            violation_type="no_helmet",
            confidence_score=0.96,
            snapshot_path="snapshots/cam_0/violation_seed_02.jpg",
            triggered_at=datetime.combine(report_date, time(14, 15, 26)),
            buzzer_activated=True,
        ),
        Alert(
            camera_id=1,
            model_name="ppe_monitor",
            violation_type="no_boot",
            confidence_score=0.88,
            snapshot_path="snapshots/cam_0/violation_seed_03.jpg",
            triggered_at=datetime.combine(report_date, time(14, 15, 26)),
            buzzer_activated=True,
        ),
        Alert(
            camera_id=1,
            model_name="ppe_monitor",
            violation_type="no_gloves",
            confidence_score=0.91,
            snapshot_path="snapshots/cam_0/violation_seed_04.jpg",
            triggered_at=datetime.combine(report_date, time(14, 15, 26)),
            buzzer_activated=True,
        ),
        Alert(
            camera_id=1,
            model_name="ppe_monitor",
            violation_type="no_vest",
            confidence_score=0.86,
            snapshot_path="snapshots/cam_0/violation_seed_05.jpg",
            triggered_at=datetime.combine(report_date, time(14, 15, 26)),
            buzzer_activated=True,
        ),
        Alert(
            camera_id=1,
            model_name="zone_monitor",
            violation_type="safe_zone",
            confidence_score=0.90,
            snapshot_path="snapshots/cam_0/violation_seed_06.jpg",
            triggered_at=datetime.combine(report_date, time(14, 15, 26)),
            buzzer_activated=False,
        ),
        Alert(
            camera_id=2,
            model_name="ppe_monitor",
            violation_type="no_helmet",
            confidence_score=0.95,
            snapshot_path="snapshots/cam_0/violation_seed_07.jpg",
            triggered_at=datetime.combine(report_date, time(14, 17, 9)),
            buzzer_activated=True,
        ),
        Alert(
            camera_id=2,
            model_name="ppe_monitor",
            violation_type="no_boot",
            confidence_score=0.87,
            snapshot_path="snapshots/cam_0/violation_seed_08.jpg",
            triggered_at=datetime.combine(report_date, time(14, 17, 9)),
            buzzer_activated=True,
        ),
        Alert(
            camera_id=2,
            model_name="ppe_monitor",
            violation_type="no_vest",
            confidence_score=0.89,
            snapshot_path="snapshots/cam_0/violation_seed_09.jpg",
            triggered_at=datetime.combine(report_date, time(14, 17, 9)),
            buzzer_activated=True,
        ),
        Alert(
            camera_id=2,
            model_name="off_hours_monitor",
            violation_type="off_hours",
            confidence_score=0.93,
            snapshot_path="snapshots/cam_0/violation_seed_10.jpg",
            triggered_at=datetime.combine(report_date, time(14, 17, 9)),
            buzzer_activated=False,
        ),
        Alert(
            camera_id=3,
            model_name="ppe_monitor",
            violation_type="no_gloves",
            confidence_score=0.92,
            snapshot_path="snapshots/cam_0/violation_seed_11.jpg",
            triggered_at=datetime.combine(report_date, time(14, 18, 45)),
            buzzer_activated=True,
        ),
        Alert(
            camera_id=3,
            model_name="ppe_monitor",
            violation_type="no_gloves",
            confidence_score=0.91,
            snapshot_path="snapshots/cam_0/violation_seed_12.jpg",
            triggered_at=datetime.combine(report_date, time(14, 18, 45)),
            buzzer_activated=True,
        ),
        Alert(
            camera_id=3,
            model_name="ppe_monitor",
            violation_type="no_gloves",
            confidence_score=0.90,
            snapshot_path="snapshots/cam_0/violation_seed_13.jpg",
            triggered_at=datetime.combine(report_date, time(14, 18, 45)),
            buzzer_activated=True,
        ),
        Alert(
            camera_id=3,
            model_name="ppe_monitor",
            violation_type="no_gloves",
            confidence_score=0.88,
            snapshot_path="snapshots/cam_0/violation_seed_14.jpg",
            triggered_at=datetime.combine(report_date, time(14, 18, 45)),
            buzzer_activated=True,
        ),
        Alert(
            camera_id=3,
            model_name="ppe_monitor",
            violation_type="no_vest",
            confidence_score=0.85,
            snapshot_path="snapshots/cam_0/violation_seed_15.jpg",
            triggered_at=datetime.combine(report_date, time(14, 18, 45)),
            buzzer_activated=True,
        ),
        Alert(
            camera_id=3,
            model_name="zone_monitor",
            violation_type="safe_zone",
            confidence_score=0.90,
            snapshot_path="snapshots/cam_0/violation_seed_16.jpg",
            triggered_at=datetime.combine(report_date, time(14, 18, 45)),
            buzzer_activated=False,
        ),
    ]

    session = SessionLocal()
    try:
        start_dt = datetime.combine(report_date, time.min)
        end_dt = datetime.combine(report_date, time.max)
        session.query(Alert).filter(
            Alert.triggered_at >= start_dt,
            Alert.triggered_at <= end_dt,
        ).delete(synchronize_session=False)
        session.add_all(rows)
        session.commit()
        print(f"Seeded {len(rows)} alert rows for {report_date.isoformat()}")
    finally:
        session.close()


if __name__ == "__main__":
    main()
