"""
app/services/alert_writer.py
------------------------------
Background thread that drains the shared alert_queue and writes rows to PostgreSQL.

Camera workers never touch the DB directly — they put() a plain dict to the queue
so that DB I/O never stalls frame processing.

Usage:
    from app.services.alert_writer import alert_writer_loop, STOP_SENTINEL

    thread = threading.Thread(target=alert_writer_loop, args=(queue,), daemon=True)
    thread.start()

    # to stop:
    queue.put(STOP_SENTINEL)
    thread.join(timeout=5)
"""

import time
from datetime import datetime
from queue import Queue, Empty
from zoneinfo import ZoneInfo

_IST_TZ = ZoneInfo("Asia/Kolkata")

STOP_SENTINEL = None   # sentinel value pushed to queue to signal shutdown


def _now_ist() -> datetime:
    return datetime.now(_IST_TZ).replace(tzinfo=None)


def alert_writer_loop(queue: Queue):
    """
    Drain *queue* and persist each item as a DB row.

    Each item is a plain dict.  Two shapes are supported:
      • model_name == "burglar_alarm"  → BurglarAlarmEvent row
      • anything else                  → Alert row

    Retries up to 5 times with a 2-second back-off before dropping.
    """
    try:
        from app.db.database import SessionLocal, ensure_database_connected
        from app.db.models import Alert, BurglarAlarmEvent
        from app.db.models.vehicle_detection_event import VehicleDetectionEvent
    except Exception as e:
        print(f"[AlertWriter] Import error — DB writes disabled: {e}")
        return

    while True:
        try:
            item = queue.get(timeout=1)
        except Empty:
            continue

        if item is STOP_SENTINEL:
            break

        try:
            ensure_database_connected()
            with SessionLocal() as db:
                if item.get("model_name") == "burglar_alarm":
                    db.add(BurglarAlarmEvent(
                        camera_id           = item["camera_id"],
                        zone_id             = item.get("zone_id"),
                        confidence_score    = item.get("confidence_score", 0.0),
                        snapshot_path       = item.get("snapshot_path"),
                        buzzer_activated    = item.get("buzzer_activated", False),
                        tracker_initialized = item.get("tracker_initialized", False),
                        triggered_at        = _now_ist(),
                        bbox_x1             = item.get("bbox_x1"),
                        bbox_y1             = item.get("bbox_y1"),
                        bbox_x2             = item.get("bbox_x2"),
                        bbox_y2             = item.get("bbox_y2"),
                        frame_width         = item.get("frame_width"),
                        frame_height        = item.get("frame_height"),
                    ))
                elif item.get("model_name") == "vehicle_detection":
                    db.add(VehicleDetectionEvent(
                        camera_id           = item["camera_id"],
                        vehicle_class       = item.get("vehicle_class", "vehicle"),
                        confidence_score    = item.get("confidence_score", 0.0),
                        plate_number        = item.get("plate_number"),
                        plate_confidence    = item.get("plate_confidence"),
                        snapshot_path       = item.get("snapshot_path"),
                        plate_snapshot_path = item.get("plate_snapshot_path"),
                        triggered_at        = _now_ist(),
                    ))
                else:
                    db.add(Alert(
                        camera_id          = item["camera_id"],
                        model_name         = item.get("model_name", "ppe_detection"),
                        violation_type     = item.get("violation_type", "violation"),
                        confidence_score   = item.get("confidence_score", 0.0),
                        snapshot_path      = item.get("snapshot_path"),
                        triggered_at       = _now_ist(),
                        buzzer_activated   = item.get("buzzer_activated", False),
                        session_tracker_id = item.get("session_tracker_id"),
                    ))
                db.commit()

        except Exception as e:
            attempts = int(item.get("_db_write_attempts", 0)) + 1
            item["_db_write_attempts"] = attempts
            print(
                f"[AlertWriter] DB write failed "
                f"(attempt {attempts}/5, cam={item.get('camera_id')}, "
                f"type={item.get('violation_type')}): {e}"
            )
            if attempts < 5:
                time.sleep(2)
                queue.put(item)
            else:
                print(f"[AlertWriter] Dropping alert after 5 failures: {item}")
