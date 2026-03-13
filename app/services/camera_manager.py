"""
app/services/camera_manager.py
--------------------------------
Singleton service that owns all camera threads and shared frame data.

Lifecycle:
  initialize()  — called once at FastAPI startup (lifespan)
                  opens serial port, preloads YOLO model
  start_all()   — spawns one thread per configured camera + AlertWriter thread
  stop_all()    — sets stop_event on every thread, joins with 2s timeout
  shutdown()    — stop_all() + close serial (called on app shutdown)

Thread model:
  Each camera runs camera_worker.camera_loop() in a daemon thread.
  The thread writes JPEG bytes to frame_dict[cam_id] after every frame.
  The MJPEG streaming endpoint reads frame_dict[cam_id] asynchronously.
  A single threading.Lock protects both frame_dict and stats_dict.

AlertWriter:
  A single background thread reads violation dicts from alert_queue and
  writes Alert rows to PostgreSQL.  Camera threads never touch the DB
  directly — they only put() to the queue, keeping inference latency low.

The singleton instance `camera_manager` is imported directly by route modules.
"""

import threading
import sys
import os
from datetime import datetime
from pathlib import Path
from queue import Queue, Empty

# Make project root importable from this sub-package
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import get_config
from detector import load_model, load_class_names
from alarm import init_serial, close_serial
from camera_worker import camera_loop

# Sentinel value pushed to alert_queue to signal AlertWriter to stop
_STOP_SENTINEL = None
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _resolve_local_path(path_like: str) -> Path:
    p = Path(path_like)
    if p.is_absolute():
        return p
    return _PROJECT_ROOT / p


def _is_device_or_network_source(url) -> bool:
    """True for webcam indices or network stream URLs."""
    if isinstance(url, int):
        return True
    if not isinstance(url, str):
        return False
    s = url.strip()
    if s.isdigit():
        return True
    return s.startswith(("rtsp://", "rtmp://", "http://", "https://", "udp://", "tcp://"))


def _fetch_enabled_models_for_camera(cam_id: int) -> list | None:
    """
    Return the list of enabled model names for a camera from the DB.

        Returns None when no rows exist, which means "all models enabled" (backward-compat default).
        When rows exist, they are treated as per-model overrides:
            - known models default to enabled unless explicitly disabled
            - explicitly enabled custom models are included
    """
    try:
        from app.db.database import SessionLocal
        from app.db.models import CameraModel

        if SessionLocal is None:
            return None

        with SessionLocal() as db:
            rows = db.query(CameraModel).filter(CameraModel.camera_id == cam_id).all()
            if not rows:
                return None  # no config recorded → let all models run

            # Defaults for built-in model toggles shown in UI.
            known_defaults_enabled = {
                "helmet_detection",
                "gloves_detection",
                "vest_detection",
                "fire_detection",
                "glasses_detection",
                "mask_detection",
            }

            enabled = set(known_defaults_enabled)
            for r in rows:
                if r.is_enabled:
                    enabled.add(r.model_name)
                else:
                    enabled.discard(r.model_name)

            enabled = sorted(enabled)
            print(f"[CameraManager] Camera {cam_id} enabled models: {enabled}")
            return enabled
    except Exception as e:
        print(f"[CameraManager] Warning: could not fetch models for cam {cam_id}: {e}")
        return None


def _fetch_buzzers_for_camera(cam_id: int) -> list:
    """
    Query the DB for all active buzzers assigned to *cam_id*.

    Returns a list of plain dicts compatible with camera_worker.fire_buzzers().
    Returns [] if the DB is unavailable or no buzzers are assigned.
    """
    try:
        from app.db.database import SessionLocal
        from app.db.models import CameraBuzzer

        if SessionLocal is None:
            return []

        with SessionLocal() as db:
            rows = (
                db.query(CameraBuzzer)
                .filter(CameraBuzzer.camera_id == cam_id)
                .all()
            )
            buzzers = []
            for cb in rows:
                b = cb.buzzer
                if b:
                    buzzers.append({
                        "id":         b.id,
                        "protocol":   b.protocol,
                        "device_id":  b.device_id,
                        "ip_address": b.ip_address,
                        "port":       b.port,
                        "gpio_pin":   b.gpio_pin,
                        "is_active":  b.is_active,
                    })
            return buzzers
    except Exception as e:
        print(f"[CameraManager] Warning: could not fetch buzzers for cam {cam_id}: {e}")
        return []


def _alert_writer_loop(queue: Queue):
    """
    Background thread: drains alert_queue and persists each item as an Alert row.

    Each item is a dict with keys:
      camera_id, model_name, violation_type, confidence_score,
      snapshot_path, buzzer_activated

    Pushes _STOP_SENTINEL (None) to terminate.
    """
    try:
        from app.db.database import SessionLocal
        from app.db.models import Alert
    except Exception as e:
        print(f"[AlertWriter] Import error — DB writes disabled: {e}")
        return

    while True:
        try:
            item = queue.get(timeout=1)
        except Empty:
            continue

        if item is _STOP_SENTINEL:
            break

        try:
            if SessionLocal is None:
                continue
            with SessionLocal() as db:
                alert = Alert(
                    camera_id        = item["camera_id"],
                    model_name       = item.get("model_name", "helmet_detection"),
                    violation_type   = item.get("violation_type", "no_helmet"),
                    confidence_score = item.get("confidence_score", 0.0),
                    snapshot_path    = item.get("snapshot_path"),
                    triggered_at     = datetime.utcnow(),
                    buzzer_activated = item.get("buzzer_activated", False),
                )
                db.add(alert)
                db.commit()
        except Exception as e:
            print(f"[AlertWriter] Failed to write alert to DB: {e}")


class CameraManager:
    def __init__(self):
        # Latest JPEG frame bytes per camera: {cam_id: bytes}
        self.frame_dict: dict[int, bytes] = {}
        # Live stats per camera: {cam_id: {status, fps, violations, frames}}
        self.stats_dict: dict[int, dict] = {}
        # Shared lock protecting both frame_dict and stats_dict
        self.lock = threading.Lock()
        # Active camera threads: {cam_id: Thread}
        self.threads: dict[int, threading.Thread] = {}
        # Per-camera stop signals: {cam_id: Event}
        self.stop_events: dict[int, threading.Event] = {}
        # Shared YOLO model (loaded once, reused across all camera threads)
        self.model = None
        self.model_path_loaded: str | None = None
        # Optional second model for gloves/bare-hands detection
        self.gloves_model = None
        self.gloves_model_path_loaded: str | None = None
        self.helmet_class: str | None = None
        self.no_helmet_class: str | None = None
        self.violation_classes: list = []
        self.safe_classes: list = []
        self.runtime_fallbacks = {
            "model_fallback": False,
            "source_fallback": False,
            "active_model_path": None,
            "requested_model_path": None,
        }
        # True once start_all() has been called
        self._running = False

        # Queue shared by all camera threads → AlertWriter
        self.alert_queue: Queue = Queue()
        # AlertWriter background thread
        self._alert_writer_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self):
        """
        Called at FastAPI startup.
        Opens serial port and preloads the YOLO model so the first
        /cameras/start request responds immediately.
        """
        init_serial()
        preload = os.getenv("PRELOAD_MODEL_ON_STARTUP", "0").strip().lower() in {"1", "true", "yes", "on"}
        if not preload:
            print("[CameraManager] Skipping model preload at startup (lazy-load on /cameras/start).")
            return

        cfg = get_config()
        try:
            self.model = load_model(cfg["model_path"])
            self.model_path_loaded = cfg["model_path"]
            _, self.helmet_class, self.no_helmet_class, self.violation_classes, self.safe_classes = load_class_names(cfg["class_file"])
            print("[CameraManager] Model loaded successfully.")
        except Exception as e:
            # Non-fatal: model will be loaded lazily on start_all()
            print(f"[CameraManager] Warning: could not preload model: {e}")

    def shutdown(self):
        """Stop all cameras and close serial on app shutdown."""
        self.stop_all()
        close_serial()

    # ------------------------------------------------------------------
    # Start / stop
    # ------------------------------------------------------------------

    def start_all(self):
        """
        Start detection threads for all cameras listed in config.yaml,
        plus the AlertWriter background thread for non-blocking DB logging.
        Loads the YOLO model if it wasn't preloaded at startup.
        Raises RuntimeError if the model cannot be loaded.
        No-op if already running.
        """
        if self._running:
            # If threads are still alive, genuinely running — skip.
            if any(t.is_alive() for t in self.threads.values()):
                return
            # All threads died without an explicit stop() (e.g. webcam error).
            # Clean up orphaned state so we can restart cleanly.
            print("[CameraManager] Threads died without explicit stop — resetting state for restart.")
            self.threads.clear()
            self.stop_events.clear()
            with self.lock:
                self.frame_dict.clear()
                self.stats_dict.clear()
            self._running = False

        cfg = get_config()

        configured_model_path = cfg.get("model_path", "")
        selected_model_path = configured_model_path
        model_fallback = False
        configured_abs = _resolve_local_path(configured_model_path) if configured_model_path else None

        if configured_model_path and configured_abs and not configured_abs.exists():
            fallback_abs = _resolve_local_path("yolov8n.pt")
            if fallback_abs.exists():
                selected_model_path = "yolov8n.pt"
                model_fallback = True
                print(
                    f"[CameraManager] Warning: model '{configured_model_path}' not found. "
                    "Falling back to 'yolov8n.pt'."
                )

        self.runtime_fallbacks["model_fallback"] = model_fallback
        self.runtime_fallbacks["requested_model_path"] = configured_model_path
        self.runtime_fallbacks["active_model_path"] = selected_model_path

        # Load/reload main model if missing or config changed.
        if self.model is None or self.model_path_loaded != selected_model_path:
            try:
                self.model = load_model(selected_model_path)
                self.model_path_loaded = selected_model_path
                _, self.helmet_class, self.no_helmet_class, self.violation_classes, self.safe_classes = load_class_names(cfg["class_file"])
            except Exception as e:
                raise RuntimeError(f"Failed to load model: {e}")

        # Load optional gloves model if configured and present.
        gloves_model_path = cfg.get("gloves_model_path", "")
        if gloves_model_path:
            gloves_abs = _resolve_local_path(gloves_model_path)
            if gloves_abs.exists() and self.gloves_model_path_loaded != gloves_model_path:
                try:
                    self.gloves_model = load_model(gloves_model_path)
                    self.gloves_model_path_loaded = gloves_model_path
                    print(f"[CameraManager] Gloves model loaded: {gloves_model_path}")
                except Exception as e:
                    print(f"[CameraManager] Warning: could not load gloves model '{gloves_model_path}': {e}")
                    self.gloves_model = None
            elif not gloves_abs.exists():
                print(f"[CameraManager] Warning: gloves model not found: {gloves_model_path}")

        # Start the AlertWriter thread once for all cameras
        self._start_alert_writer()

        # Read all alarm/detection settings from config once
        feeds             = cfg.get("camera_feeds", [])
        use_wifi          = cfg.get("use_wifi", False)
        esp_ip            = cfg.get("esp_ip", None)
        alarm_transport   = cfg.get("alarm_transport", None)
        alarm_http_token  = cfg.get("alarm_http_token", "")
        mqtt_broker       = cfg.get("mqtt_broker", "")
        mqtt_port         = cfg.get("mqtt_port", 1883)
        mqtt_username     = cfg.get("mqtt_username", "")
        mqtt_password     = cfg.get("mqtt_password", "")
        mqtt_topic        = cfg.get("mqtt_topic", "skycctv/alarm")
        mqtt_client_id    = cfg.get("mqtt_client_id", "skycctv-ai")
        mqtt_qos          = cfg.get("mqtt_qos", 1)
        mqtt_retain       = cfg.get("mqtt_retain", False)
        cooldown          = cfg.get("alarm_cooldown_sec", 5)
        threshold         = cfg.get("confidence_threshold", 0.25)

        started_any = False
        for cam_id, url in enumerate(feeds):
            if url is None or (isinstance(url, str) and not url.strip()):
                continue

            # If a local media path is configured and missing, skip it.
            if not _is_device_or_network_source(url):
                source_abs = _resolve_local_path(str(url))
                if not source_abs.exists():
                    print(f"[CameraManager] Warning: source not found for camera {cam_id}: {url}")
                    with self.lock:
                        self.stats_dict[cam_id] = {
                            "status": "error",
                            "fps": 0,
                            "violations": 0,
                            "frames": 0,
                        }
                    continue

            self._start_camera(
                cam_id, url, threshold, cooldown, use_wifi, esp_ip,
                alarm_transport, alarm_http_token,
                mqtt_broker, mqtt_port, mqtt_username, mqtt_password,
                mqtt_topic, mqtt_client_id, mqtt_qos, mqtt_retain,
                violation_classes=self.violation_classes,
                safe_classes=self.safe_classes,
                gloves_model=self.gloves_model,
            )
            started_any = True

        # If no configured source can be started, fall back to local webcam 0.
        if not started_any:
            self.runtime_fallbacks["source_fallback"] = True
            print("[CameraManager] Warning: no valid camera sources found. Falling back to webcam 0.")
            self._start_camera(
                0, 0, threshold, cooldown, use_wifi, esp_ip,
                alarm_transport, alarm_http_token,
                mqtt_broker, mqtt_port, mqtt_username, mqtt_password,
                mqtt_topic, mqtt_client_id, mqtt_qos, mqtt_retain,
                violation_classes=self.violation_classes,
                safe_classes=self.safe_classes,
                gloves_model=self.gloves_model,
            )
        else:
            self.runtime_fallbacks["source_fallback"] = False

        self._running = True

    def stop_all(self):
        """Signal all camera threads to stop, then stop the AlertWriter."""
        for event in self.stop_events.values():
            event.set()
        for t in self.threads.values():
            t.join(timeout=2)
        self.threads.clear()
        self.stop_events.clear()
        with self.lock:
            self.frame_dict.clear()
            self.stats_dict.clear()
        self._running = False
        self._stop_alert_writer()

    def start_camera(self, cam_id: int):
        """
        Start (or restart) a single camera by its index in config.yaml.
        Reads fresh config so settings updated via the API are picked up.
        Ensures the AlertWriter is running (in case cameras were stopped).
        """
        cfg = get_config()
        feeds = cfg.get("camera_feeds", [])
        if cam_id >= len(feeds):
            raise ValueError(f"Camera {cam_id} not in config")
        url = feeds[cam_id]

        # Make sure alert writer is alive
        self._start_alert_writer()

        self._start_camera(
            cam_id, url,
            cfg.get("confidence_threshold", 0.25),
            cfg.get("alarm_cooldown_sec", 5),
            cfg.get("use_wifi", False),
            cfg.get("esp_ip", None),
            cfg.get("alarm_transport", None),
            cfg.get("alarm_http_token", ""),
            cfg.get("mqtt_broker", ""),
            cfg.get("mqtt_port", 1883),
            cfg.get("mqtt_username", ""),
            cfg.get("mqtt_password", ""),
            cfg.get("mqtt_topic", "skycctv/alarm"),
            cfg.get("mqtt_client_id", "skycctv-ai"),
            cfg.get("mqtt_qos", 1),
            cfg.get("mqtt_retain", False),
            violation_classes=self.violation_classes,
            safe_classes=self.safe_classes,
            gloves_model=self.gloves_model,
            enabled_models=_fetch_enabled_models_for_camera(cam_id),
        )

    def stop_camera(self, cam_id: int):
        """Signal a single camera thread to stop and wait for it to exit."""
        if cam_id in self.stop_events:
            self.stop_events[cam_id].set()
            self.threads[cam_id].join(timeout=2)
            del self.stop_events[cam_id]
            del self.threads[cam_id]

    def _start_alert_writer(self):
        """Start the AlertWriter background thread if it is not already running."""
        if (
            self._alert_writer_thread is not None
            and self._alert_writer_thread.is_alive()
        ):
            return
        self._alert_writer_thread = threading.Thread(
            target=_alert_writer_loop,
            args=(self.alert_queue,),
            daemon=True,
            name="AlertWriter",
        )
        self._alert_writer_thread.start()
        print("[CameraManager] AlertWriter thread started.")

    def _stop_alert_writer(self):
        """Send sentinel to AlertWriter and wait for it to drain and exit."""
        if (
            self._alert_writer_thread is not None
            and self._alert_writer_thread.is_alive()
        ):
            self.alert_queue.put(_STOP_SENTINEL)
            self._alert_writer_thread.join(timeout=5)
        self._alert_writer_thread = None

    def _start_camera(
        self,
        cam_id, url, threshold, cooldown, use_wifi, esp_ip,
        alarm_transport, alarm_http_token,
        mqtt_broker, mqtt_port, mqtt_username, mqtt_password,
        mqtt_topic, mqtt_client_id, mqtt_qos, mqtt_retain,
        violation_classes=None, safe_classes=None, gloves_model=None,
    ):
        """
        Internal: create and start a camera thread.
        If a thread for this cam_id is already running, it is stopped first.

        Fetches the camera's assigned buzzers from the DB so the worker thread
        has the full buzzer config without needing DB access during inference.
        MQTT and alarm params are passed as kwargs to avoid positional fragility.
        """
        # Stop any existing thread for this camera slot before replacing it
        if cam_id in self.stop_events:
            self.stop_events[cam_id].set()

        # Fetch DB-assigned buzzers and enabled model flags for this camera
        assigned_buzzers = _fetch_buzzers_for_camera(cam_id)
        enabled_models   = _fetch_enabled_models_for_camera(cam_id)

        stop_event = threading.Event()
        self.stop_events[cam_id] = stop_event

        t = threading.Thread(
            target=camera_loop,
            # Positional args match the required signature of camera_loop
            args=(
                cam_id, url, self.model, threshold,
                self.helmet_class, self.no_helmet_class,
                cooldown, use_wifi, esp_ip,
                self.frame_dict, self.lock,
            ),
            # Keyword args for optional params — safer against signature changes
            kwargs=dict(
                stop_event=stop_event,
                stats_dict=self.stats_dict,
                alarm_transport=alarm_transport,
                alarm_http_token=alarm_http_token,
                mqtt_broker=mqtt_broker,
                mqtt_port=mqtt_port,
                mqtt_username=mqtt_username,
                mqtt_password=mqtt_password,
                mqtt_topic=mqtt_topic,
                mqtt_client_id=mqtt_client_id,
                mqtt_qos=mqtt_qos,
                mqtt_retain=mqtt_retain,
                # DB-backed features
                assigned_buzzers=assigned_buzzers,
                alert_queue=self.alert_queue,
                enabled_models=enabled_models,
                violation_classes=violation_classes or self.violation_classes,
                safe_classes=safe_classes or self.safe_classes,
                gloves_model=gloves_model if gloves_model is not None else self.gloves_model,
            ),
            daemon=True,   # thread exits automatically when the main process does
        )
        self.threads[cam_id] = t
        t.start()
        print(
            f"[CameraManager] Camera {cam_id} started "
            f"({len(assigned_buzzers)} buzzer(s) assigned)."
        )

    # ------------------------------------------------------------------
    # Data accessors (called by route handlers)
    # ------------------------------------------------------------------

    def get_latest_frame(self, cam_id: int) -> bytes | None:
        """Return the most recent JPEG bytes for a camera, or None."""
        with self.lock:
            return self.frame_dict.get(cam_id)

    def get_stats(self) -> dict:
        """Return a copy of the stats dict (safe to serialize as JSON)."""
        with self.lock:
            return dict(self.stats_dict)

    def get_camera_statuses(self) -> list:
        """
        Merge config (url, title) with live thread state (active, fps, violations).
        Used by GET /api/cameras/ and the frontend polling loop.
        """
        cfg = get_config()
        feeds = cfg.get("camera_feeds", [])
        titles = cfg.get("camera_titles", [])
        result = []
        for i, url in enumerate(feeds):
            title = titles[i] if i < len(titles) else f"Camera {i}"
            is_alive = i in self.threads and self.threads[i].is_alive()
            stats = self.stats_dict.get(i, {})
            result.append({
                "id": i,
                "url": url,
                "title": title,
                "active": is_alive,
                "fps": stats.get("fps", 0),
                "violations": stats.get("violations", 0),
                "frames": stats.get("frames", 0),
                "status": stats.get("status", "stopped"),
                "runtime_fallbacks": dict(self.runtime_fallbacks),
            })
        return result

    def is_running(self) -> bool:
        """True if start_all() has been called and threads are active."""
        return self._running


# Module-level singleton — imported directly by route modules
camera_manager = CameraManager()
