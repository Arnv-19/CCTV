import threading
from queue import Queue
from unittest.mock import patch

import numpy as np

import camera_worker


class FakeCap:
    def __init__(self, source):
        self.source = source

    def isOpened(self):
        return True

    def read(self):
        return True, np.zeros((480, 640, 3), dtype=np.uint8)

    def release(self):
        pass


def run_case(enabled_models):
    stop_event = threading.Event()
    frame_dict = {}
    stats = {}
    alerts = Queue()

    def fake_run_detection(model, frame, threshold):
        stop_event.set()
        return [{"class": "no_helmet", "conf": 0.9, "box": [0, 0, 10, 10]}]

    with patch.object(camera_worker.cv2, "VideoCapture", FakeCap), \
         patch.object(camera_worker.cv2, "resize", lambda f, d: f), \
         patch.object(camera_worker.cv2, "imencode", lambda ext, frm, opts=None: (True, np.array([1, 2, 3], dtype=np.uint8))), \
         patch.object(camera_worker.cv2, "rectangle", lambda *a, **k: None), \
         patch.object(camera_worker.cv2, "putText", lambda *a, **k: None), \
         patch.object(camera_worker, "run_detection", fake_run_detection), \
         patch.object(camera_worker, "save_snapshot", lambda *a, **k: None), \
         patch.object(camera_worker, "log_violation_file", lambda *a, **k: None), \
         patch.object(camera_worker, "fire_buzzers", lambda *a, **k: False):

        camera_worker.camera_loop(
            cam_id=0,
            stream_url="0",
            model=object(),
            threshold=0.25,
            helmet_class="helmet",
            no_helmet_class="no_helmet",
            cooldown=0,
            use_wifi=False,
            esp_ip=None,
            frame_dict=frame_dict,
            lock=threading.Lock(),
            stop_event=stop_event,
            stats_dict=stats,
            assigned_buzzers=[{"id": 1, "is_active": False}],
            alert_queue=alerts,
            enabled_models=enabled_models,
            violation_classes=["no_helmet"],
            safe_classes=["helmet"],
            gloves_model=None,
        )

    return alerts.qsize(), stats.get(0, {}).get("status"), stats.get(0, {}).get("frames", 0)


if __name__ == "__main__":
    size_default, status_default, frames_default = run_case(None)
    assert size_default == 1, f"Expected 1 alert for enabled default, got {size_default}"

    size_filtered, status_filtered, frames_filtered = run_case(["vest_detection"])
    assert size_filtered == 0, f"Expected 0 alerts when helmet model disabled, got {size_filtered}"

    print({
        "result": "ok",
        "default_all_enabled_alerts": size_default,
        "helmet_disabled_alerts": size_filtered,
        "status_default": status_default,
        "status_filtered": status_filtered,
        "frames_default": frames_default,
        "frames_filtered": frames_filtered,
    })
