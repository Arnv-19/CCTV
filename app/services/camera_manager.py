"""
app/services/camera_manager.py
--------------------------------
Singleton that owns all camera processes and shared frame data.

Lifecycle:
  initialize()  — FastAPI startup: opens serial port
  start_all()   — spawns ingestion processes + result handler threads + inference servers
  stop_all()    — signals everything to stop, joins with timeouts
  shutdown()    — stop_all() + close serial

Architecture (shared-inference):
  ingestion_worker   (mp.Process, 1 per camera) — FFmpeg/webcam → frame_queue
  inference_server   (mp.Process, 1 per model)  — batch GPU predict → result_queues
  result_handler     (threading.Thread, 1 per camera) — alarm/MJPEG/stats

DB is the source of truth for cameras, models, buzzers.
config.yaml owns only transport timing (cooldown, snapshot interval, batch size).
"""

import threading
import multiprocessing as mp
import sys
import os
import time
from pathlib import Path

import psutil

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from app.config import get_config
from alarm import init_serial, close_serial
from camera_worker import ingestion_worker, result_handler_worker
from inference_server import inference_server_loop
from app.services.burglar_alarm_service import fetch_burglar_config
from app.services.camera_db_helpers import (
    load_cameras_from_db,
    load_model_config_for_camera,
    fetch_buzzers_for_camera,
    fetch_enabled_models_for_camera,
    _resolve_local_path,
)
from app.services.alert_writer import alert_writer_loop, STOP_SENTINEL
from app.controllers.feature_config_controller import get_camera_feature_config
from app.controllers.dynamic_fps_controller import decide_camera_fps


def _is_network_source(url) -> bool:
    """True for webcam indices or network stream URLs."""
    if isinstance(url, int):
        return True
    if not isinstance(url, str):
        return False
    s = url.strip()
    return s.isdigit() or s.startswith(
        ("rtsp://", "rtmp://", "http://", "https://", "udp://", "tcp://")
    )


class CameraManager:
    def __init__(self):
        self._mp_manager = mp.Manager()

        # frame_dict is written only by result_handler_worker threads (main process),
        # so a plain dict avoids Manager IPC on every frame — fixes event-loop blocking.
        self.frame_dict  = {}                         # {cam_id: jpeg_bytes}
        self.stats_dict  = self._mp_manager.dict()   # {cam_id: {status, fps, ...}} — written by subprocesses
        self.lock        = self._mp_manager.Lock()

        # Per-camera ingestion processes
        self.processes:   dict[int, mp.Process]       = {}
        self.stop_events: dict[int, mp.Event]         = {}

        # Shared-inference architecture
        self.frame_queues:             dict = {}   # {model_path: mp.Queue}
        self.result_queues             = self._mp_manager.dict()   # {cam_id: mp.Queue}
        self._inference_servers:       dict = {}   # {model_path: mp.Process}
        self._inference_stop_events:   dict = {}   # {model_path: mp.Event}
        self._cam_model_map:           dict = {}   # {cam_id: model_path}

        # Result handler threads (in main process)
        self._result_handler_threads:     dict[int, threading.Thread] = {}
        self._result_handler_stop_events: dict[int, threading.Event]  = {}

        # Alert writer
        self.alert_queue             = mp.Queue()
        self._alert_writer_thread: threading.Thread | None = None

        # Fallback class lists (populated from config.yaml when DB has no assignment)
        self.violation_classes: list = []
        self.safe_classes:      list = []
        self.helmet_class:      str | None = None
        self.no_helmet_class:   str | None = None

        self.runtime_fallbacks = {
            "model_fallback": False, "source_fallback": False,
            "active_model_path": None, "requested_model_path": None,
        }
        self._running = False

        # Resource metrics
        self._process = psutil.Process(os.getpid())
        self._process_cpu_sample = {
            "cpu_time": sum(self._process.cpu_times()[:2]),
            "sample_at": time.time(),
        }
        self._thread_cpu_samples: dict[int, dict] = {}
        self._cpu_percent_primed = False

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def initialize(self):
        """Called at FastAPI startup. Opens serial port."""
        init_serial()
        print("[CameraManager] Initialized — call /api/cameras/start to begin detection.")

    def shutdown(self):
        """Stop all cameras, close serial, clean up the mp.Manager."""
        self.stop_all()
        close_serial()
        try:
            self.alert_queue.close()
            self._mp_manager.shutdown()
        except Exception:
            pass

    # ── Start / stop all ──────────────────────────────────────────────────────

    def start_all(self):
        """
        Start inference servers + per-camera workers for all active cameras.
        Cameras and models come from DB; alarm timing from config.yaml.
        No-op if already running.
        """
        if self._running:
            if any(p.is_alive() for p in self.processes.values()):
                return
            # All processes died unexpectedly — reset and restart cleanly
            print("[CameraManager] Processes died without stop — resetting for restart.")
            self._reset_state()

        cfg = get_config()

        # Transport / timing always from config.yaml
        cooldown          = cfg.get("alarm_cooldown_sec", 5)
        snapshot_cooldown = cfg.get("snapshot_cooldown_sec", 120)
        yolo_imgsz        = cfg.get("yolo_imgsz", 640)
        inference_fps     = cfg.get("inference_fps", 4)
        batch_size        = cfg.get("inference_batch_size", 8)
        burglar_test_sound = cfg.get("burglar_test_sound", False)

        # Build per-camera config list from DB; fall back to config.yaml if empty
        camera_configs = self._build_camera_configs(cfg)
        if cfg.get("dynamic_fps", {}).get("enabled"):
            dyn_settings = cfg.get("dynamic_fps", {})
            for cam_cfg in camera_configs:
                cam_cfg["ingestion_fps"] = decide_camera_fps(
                    camera_count=len(camera_configs),
                    camera_id=cam_cfg["id"],
                    requested_fps=cam_cfg.get("ingestion_fps"),
                    settings=dyn_settings,
                )

        self._start_alert_writer()
        self._launch_inference_servers(camera_configs, batch_size, inference_fps, yolo_imgsz)
        self._launch_camera_workers(
            camera_configs, cooldown, snapshot_cooldown, yolo_imgsz, burglar_test_sound, inference_fps
        )

        self._running = True

    def stop_all(self):
        """Stop all ingestion processes, result handler threads, inference servers."""
        # 1. Ingestion processes
        for ev in self.stop_events.values():
            ev.set()
        for proc in self.processes.values():
            proc.join(timeout=3)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=2)
                if proc.is_alive():
                    proc.kill()
        self.processes.clear()
        self.stop_events.clear()

        # 2. Result handler threads
        for ev in self._result_handler_stop_events.values():
            ev.set()
        for t in self._result_handler_threads.values():
            t.join(timeout=2)
        self._result_handler_threads.clear()
        self._result_handler_stop_events.clear()

        # 3. Inference server processes
        for mk, srv in list(self._inference_servers.items()):
            if srv is not None and srv.is_alive():
                stop_ev = self._inference_stop_events.get(mk)
                if stop_ev:
                    stop_ev.set()
                fq = self.frame_queues.get(mk)
                if fq:
                    try:
                        fq.put_nowait(None)   # stop sentinel
                    except Exception:
                        pass
                srv.join(timeout=5)
                if srv.is_alive():
                    srv.terminate()
                    srv.join(timeout=2)
        self._inference_servers.clear()
        self._inference_stop_events.clear()
        self.frame_queues.clear()
        self._cam_model_map.clear()
        self.result_queues.clear()

        self.frame_dict.clear()
        self.stats_dict.clear()
        self._thread_cpu_samples.clear()
        self._running = False
        self._stop_alert_writer()

    # ── Single-camera start / stop ─────────────────────────────────────────────

    def start_camera(self, cam_id: int):
        """
        Start (or restart) one camera by its DB id.
        Reads fresh config from DB; falls back to config.yaml when not found.
        """
        cfg = get_config()

        # Camera source from DB
        db_cams = load_cameras_from_db()
        db_cam  = next((c for c in db_cams if c["id"] == cam_id), None)

        if db_cam:
            url              = db_cam["stream_url"]
            ingestion_fps    = db_cam["ingestion_fps"]
            detection_width  = db_cam["detection_width"]
            detection_height = db_cam["detection_height"]
        else:
            feeds = cfg.get("camera_feeds", [])
            if cam_id >= len(feeds):
                raise ValueError(f"Camera {cam_id} not found in DB or config")
            url              = feeds[cam_id]
            ingestion_fps    = cfg.get("ingestion_fps", 4)
            detection_width  = cfg.get("detection_frame_width", 640)
            detection_height = cfg.get("detection_frame_height", 480)

        if cfg.get("dynamic_fps", {}).get("enabled"):
            active_count = len(db_cams) if db_cams else max(1, len(cfg.get("camera_feeds", [])))
            ingestion_fps = decide_camera_fps(
                camera_count=active_count,
                camera_id=cam_id,
                requested_fps=ingestion_fps,
                settings=cfg.get("dynamic_fps", {}),
            )

        # Model config from DB
        model_cfg = load_model_config_for_camera(cam_id)
        if model_cfg:
            threshold         = model_cfg["confidence_threshold"]
            violation_classes = model_cfg["violation_classes"]
            safe_classes      = model_cfg["safe_classes"]
        else:
            threshold         = cfg.get("confidence_threshold", 0.25)
            violation_classes = self.violation_classes
            safe_classes      = self.safe_classes

        self._start_alert_writer()

        if cam_id not in self.result_queues:
            self.result_queues[cam_id] = self._mp_manager.Queue(maxsize=4)

        cam_mk          = self._cam_model_map.get(cam_id) or next(iter(self.frame_queues), None)
        cam_frame_queue = self.frame_queues.get(cam_mk) if cam_mk else None

        self._start_camera_worker(
            cam_id=cam_id,
            url=url,
            threshold=threshold,
            cooldown=cfg.get("alarm_cooldown_sec", 5),
            snapshot_cooldown=cfg.get("snapshot_cooldown_sec", 120),
            violation_classes=violation_classes,
            safe_classes=safe_classes,
            detection_width=detection_width,
            detection_height=detection_height,
            yolo_imgsz=cfg.get("yolo_imgsz", 640),
            ingestion_fps=ingestion_fps,
            inference_fps=cfg.get("inference_fps", 4),
            burglar_test_sound=cfg.get("burglar_test_sound", False),
            frame_queue=cam_frame_queue,
        )

    def stop_camera(self, cam_id: int):
        """Stop one camera's ingestion process and result handler thread."""
        if cam_id in self.stop_events:
            self.stop_events[cam_id].set()
            proc = self.processes.get(cam_id)
            if proc is not None:
                proc.join(timeout=3)
                if proc.is_alive():
                    proc.terminate()
                    proc.join(timeout=2)
                    if proc.is_alive():
                        proc.kill()
            del self.stop_events[cam_id]
            self.processes.pop(cam_id, None)

        rh_ev = self._result_handler_stop_events.pop(cam_id, None)
        if rh_ev:
            rh_ev.set()
        rh_t = self._result_handler_threads.pop(cam_id, None)
        if rh_t:
            rh_t.join(timeout=2)

        self._thread_cpu_samples.pop(cam_id, None)

    # ── Data accessors ─────────────────────────────────────────────────────────

    def get_latest_frame(self, cam_id: int) -> bytes | None:
        return self.frame_dict.get(cam_id)

    def get_stats(self) -> dict:
        with self.lock:
            return dict(self.stats_dict)

    def is_running(self) -> bool:
        return self._running

    def get_camera_statuses(self) -> list:
        """
        Return per-camera status merged with live process state.
        Reads from DB; falls back to config.yaml when cameras table is empty.
        """
        db_cams = load_cameras_from_db()
        with self.lock:
            stats_snap = {k: dict(v) for k, v in self.stats_dict.items()}

        if db_cams:
            return [
                {
                    "id":        cam["id"],
                    "url":       cam["stream_url"],
                    "title":     cam["name"],
                    "active":    self._is_alive(cam["id"]),
                    **self._cam_stats(cam["id"], stats_snap),
                }
                for cam in db_cams
            ]

        # Fallback: config.yaml
        cfg    = get_config()
        feeds  = cfg.get("camera_feeds", [])
        titles = cfg.get("camera_titles", [])
        return [
            {
                "id":        i,
                "url":       url,
                "title":     titles[i] if i < len(titles) else f"Camera {i}",
                "active":    self._is_alive(i),
                **self._cam_stats(i, stats_snap),
            }
            for i, url in enumerate(feeds)
        ]

    def get_resource_metrics(self) -> dict:
        """Return system + process resource usage."""
        now           = time.time()
        logical_cores = psutil.cpu_count(logical=True) or 1
        sys_mem       = psutil.virtual_memory()

        if not self._cpu_percent_primed:
            psutil.cpu_percent(interval=None)
            self._cpu_percent_primed = True
        sys_cpu = round(psutil.cpu_percent(interval=None), 1)

        proc_times  = self._process.cpu_times()
        proc_cpu_t  = proc_times.user + proc_times.system
        prev        = self._process_cpu_sample
        elapsed     = max(now - prev["sample_at"], 1e-6)
        proc_cpu_sc = max(0.0, (proc_cpu_t - prev["cpu_time"]) / elapsed * 100.0)
        self._process_cpu_sample = {"cpu_time": proc_cpu_t, "sample_at": now}
        proc_mem    = self._process.memory_info()

        return {
            "measured_at": round(now, 3),
            "system": {
                "cpu_logical_cores":    logical_cores,
                "cpu_physical_cores":   psutil.cpu_count(logical=False) or logical_cores,
                "cpu_percent":          sys_cpu,
                "total_memory_gb":      round(sys_mem.total    / 1024 ** 3, 2),
                "used_memory_gb":       round(sys_mem.used     / 1024 ** 3, 2),
                "available_memory_gb":  round(sys_mem.available / 1024 ** 3, 2),
                "memory_percent":       round(sys_mem.percent, 1),
            },
            "process": {
                "pid":                       self._process.pid,
                "thread_count":              self._process.num_threads(),
                "cpu_percent_single_core":   round(proc_cpu_sc, 1),
                "cpu_percent_total_machine": round(min(100.0, proc_cpu_sc / logical_cores), 1),
                "rss_memory_mb":             round(proc_mem.rss / 1024 ** 2, 2),
                "vms_memory_mb":             round(proc_mem.vms / 1024 ** 2, 2),
            },
        }

    # ── Private helpers ────────────────────────────────────────────────────────

    def _reset_state(self):
        self.processes.clear()
        self.stop_events.clear()
        self.frame_dict.clear()
        with self.lock:
            self.stats_dict.clear()
        self._running = False

    def _is_alive(self, cam_id: int) -> bool:
        proc = self.processes.get(cam_id)
        return proc is not None and proc.is_alive()

    def _cam_stats(self, cam_id: int, stats_snap: dict) -> dict:
        stats = stats_snap.get(cam_id, {})
        return {
            "fps":             stats.get("fps", 0),
            "violations":      stats.get("violations", 0),
            "frames":          stats.get("frames", 0),
            "status":          stats.get("status", "stopped"),
            "runtime_fallbacks": dict(self.runtime_fallbacks),
        }

    def _build_camera_configs(self, cfg: dict) -> list[dict]:
        """Return per-camera config list from DB, falling back to config.yaml."""
        db_cameras = load_cameras_from_db()

        if db_cameras:
            configs = []
            for cam in db_cameras:
                cam_id    = cam["id"]
                model_cfg = load_model_config_for_camera(cam_id)

                if model_cfg is None:
                    model_cfg = self._fallback_model_cfg(cfg)
                    print(f"[CameraManager] Camera {cam_id}: no DB assignment — using config.yaml model.")

                configs.append({
                    "id":               cam_id,
                    "url":              cam["stream_url"],
                    "ingestion_fps":    cam["ingestion_fps"],
                    "detection_width":  cam["detection_width"],
                    "detection_height": cam["detection_height"],
                    **model_cfg,
                })
            print(f"[CameraManager] Starting {len(configs)} camera(s) from DB.")
            return configs

        # Fallback: config.yaml camera_feeds
        print("[CameraManager] No cameras in DB — falling back to config.yaml camera_feeds.")
        model_cfg = self._fallback_model_cfg(cfg)
        feeds     = cfg.get("camera_feeds", [])
        return [
            {
                "id":               i,
                "url":              url,
                "ingestion_fps":    cfg.get("ingestion_fps", 4),
                "detection_width":  cfg.get("detection_frame_width", 640),
                "detection_height": cfg.get("detection_frame_height", 480),
                **model_cfg,
            }
            for i, url in enumerate(feeds)
            if url is not None and (not isinstance(url, str) or url.strip())
        ]

    def _fallback_model_cfg(self, cfg: dict) -> dict:
        """Build model config dict from config.yaml when DB has no assignment."""
        from detector import load_class_names

        model_path = cfg.get("model_path", "")
        abs_main   = str(_resolve_local_path(model_path)) if model_path else None

        class_file = cfg.get("class_file")
        if class_file:
            _, hc, nhc, viol, safe = load_class_names(str(_resolve_local_path(class_file)))
            self.helmet_class      = hc
            self.no_helmet_class   = nhc
            self.violation_classes = viol
            self.safe_classes      = safe
        else:
            viol = self.violation_classes
            safe = self.safe_classes

        gloves  = cfg.get("gloves_model_path", "")
        person  = cfg.get("person_model_path", "")
        vehicle = cfg.get("vehicle_model_path", "")
        return {
            "main_model_path":      abs_main,
            "gloves_model_path":    str(_resolve_local_path(gloves))  if gloves  else None,
            "person_model_path":    str(_resolve_local_path(person))  if person  else None,
            "vehicle_model_path":   str(_resolve_local_path(vehicle)) if vehicle else None,
            "confidence_threshold": cfg.get("confidence_threshold", 0.25),
            "violation_classes":    viol,
            "safe_classes":         safe,
        }

    def _launch_inference_servers(
        self, camera_configs: list, batch_size: int, inference_fps: float, yolo_imgsz: int,
    ):
        """One InferenceServer process per unique main model path."""
        model_groups: dict[str, list] = {}
        for cam_cfg in camera_configs:
            mk = cam_cfg.get("main_model_path")
            if mk:
                model_groups.setdefault(mk, []).append(cam_cfg)

        if not model_groups:
            print("[CameraManager] Warning: no model path resolved — inference server not started.")

        # Pre-create result queues
        for cam_cfg in camera_configs:
            cam_id = cam_cfg["id"]
            if cam_id not in self.result_queues:
                self.result_queues[cam_id] = self._mp_manager.Queue(maxsize=4)
        if 0 not in self.result_queues:
            self.result_queues[0] = self._mp_manager.Queue(maxsize=4)

        for mk, group in model_groups.items():
            rep         = group[0]
            cam_ids     = [c["id"] for c in group]
            fq          = mp.Queue(maxsize=batch_size * max(1, len(group)) * 2)
            self.frame_queues[mk] = fq
            stop_ev     = mp.Event()
            self._inference_stop_events[mk] = stop_ev

            # Build the unified models dict from DB-loaded paths.
            # "main" is required. "gloves" and "burglar" drive MediaPipe/KCF logic
            # in result_handler_worker. "vehicle" drives vehicle + OCR detection.
            # All paths come from ai_models + camera_model_assignments in the DB.
            _models: dict = {"main": mk}
            gp = rep.get("gloves_model_path")
            pp = rep.get("person_model_path")
            vp = rep.get("vehicle_model_path")
            if gp:
                _models["gloves"]  = gp
            if pp:
                _models["burglar"] = pp
            if vp:
                _models["vehicle"] = vp

            srv = mp.Process(
                target=inference_server_loop,
                kwargs=dict(
                    models=_models,
                    frame_queue=fq,
                    result_queues=self.result_queues,
                    stop_event=stop_ev,
                    batch_size=batch_size,
                    batch_timeout=max(0.02, 1.0 / max(1, float(inference_fps))),
                    threshold=rep.get("confidence_threshold", 0.25),
                    yolo_imgsz=yolo_imgsz,
                ),
                daemon=True,
                name=f"InferenceServer-{Path(mk).stem}",
            )
            self._inference_servers[mk] = srv
            srv.start()
            print(
                f"[CameraManager] InferenceServer started: model='{Path(mk).name}' "
                f"PID={srv.pid} cameras={cam_ids} batch={batch_size}"
            )

    def _launch_camera_workers(
        self,
        camera_configs: list,
        cooldown: float,
        snapshot_cooldown: float,
        yolo_imgsz: int,
        burglar_test_sound: bool,
        inference_fps: float,
    ):
        """Start ingestion process + result handler thread for each camera."""
        started_any = False

        for cam_cfg in camera_configs:
            cam_id = cam_cfg["id"]
            url    = cam_cfg["url"]
            mk     = cam_cfg.get("main_model_path")

            if not url or (isinstance(url, str) and not url.strip()):
                continue

            if not _is_network_source(url):
                src_abs = _resolve_local_path(str(url))
                if not src_abs.exists():
                    print(f"[CameraManager] Warning: source not found for camera {cam_id}: {url}")
                    with self.lock:
                        self.stats_dict[cam_id] = {"status": "error", "fps": 0, "violations": 0, "frames": 0}
                    continue

            self._cam_model_map[cam_id] = mk
            self._start_camera_worker(
                cam_id=cam_id,
                url=url,
                threshold=cam_cfg.get("confidence_threshold", 0.25),
                cooldown=cooldown,
                snapshot_cooldown=snapshot_cooldown,
                violation_classes=cam_cfg.get("violation_classes", []),
                safe_classes=cam_cfg.get("safe_classes", []),
                detection_width=cam_cfg.get("detection_width", 960),
                detection_height=cam_cfg.get("detection_height", 720),
                yolo_imgsz=yolo_imgsz,
                ingestion_fps=cam_cfg.get("ingestion_fps", 4),
                inference_fps=inference_fps,
                burglar_test_sound=burglar_test_sound,
                frame_queue=self.frame_queues.get(mk),
            )
            started_any = True

        if not started_any:
            self.runtime_fallbacks["source_fallback"] = True
            print("[CameraManager] Warning: no valid sources — falling back to webcam 0.")
            first_mk = next(iter(self.frame_queues), None)
            self._cam_model_map[0] = first_mk
            cfg = get_config()
            self._start_camera_worker(
                cam_id=0, url=0,
                threshold=cfg.get("confidence_threshold", 0.25),
                cooldown=cooldown,
                snapshot_cooldown=snapshot_cooldown,
                violation_classes=self.violation_classes,
                safe_classes=self.safe_classes,
                detection_width=cfg.get("detection_frame_width", 960),
                detection_height=cfg.get("detection_frame_height", 720),
                yolo_imgsz=yolo_imgsz,
                ingestion_fps=cfg.get("ingestion_fps", 4),
                inference_fps=inference_fps,
                burglar_test_sound=burglar_test_sound,
                frame_queue=self.frame_queues.get(first_mk),
            )
        else:
            self.runtime_fallbacks["source_fallback"] = False

    def _start_camera_worker(
        self,
        cam_id: int,
        url,
        threshold: float,
        cooldown: float,
        snapshot_cooldown: float,
        violation_classes: list,
        safe_classes: list,
        detection_width: int,
        detection_height: int,
        yolo_imgsz: int,
        ingestion_fps: float,
        inference_fps: float,
        burglar_test_sound: bool,
        frame_queue,
    ):
        """
        Start (or restart) ingestion process + result handler thread for one camera.
        All per-camera config (buzzers, enabled models, burglar alarm) is fetched
        fresh from the DB here in the main process before spawning the worker.
        """
        # Stop any existing workers for this slot
        if cam_id in self.stop_events:
            self.stop_events[cam_id].set()
            old_proc = self.processes.get(cam_id)
            if old_proc and old_proc.is_alive():
                old_proc.join(timeout=2)
                if old_proc.is_alive():
                    old_proc.terminate()
                    old_proc.join(timeout=1)

        old_rh_ev = self._result_handler_stop_events.pop(cam_id, None)
        if old_rh_ev:
            old_rh_ev.set()
        old_rh_t = self._result_handler_threads.pop(cam_id, None)
        if old_rh_t:
            old_rh_t.join(timeout=2)

        # Fetch per-camera config from DB (plain dicts — picklable)
        assigned_buzzers  = fetch_buzzers_for_camera(cam_id)
        enabled_models    = fetch_enabled_models_for_camera(cam_id)
        burglar_alarm_cfg = fetch_burglar_config(cam_id)
        feature_config    = get_camera_feature_config(cam_id)

        if cam_id not in self.result_queues:
            self.result_queues[cam_id] = self._mp_manager.Queue(maxsize=4)

        if frame_queue is None:
            frame_queue = mp.Queue(maxsize=16)   # throwaway when no inference server

        # Ingestion process
        ing_stop = mp.Event()
        self.stop_events[cam_id] = ing_stop

        proc = mp.Process(
            target=ingestion_worker,
            args=(cam_id, url, frame_queue, ing_stop, self.stats_dict, self.lock),
            kwargs=dict(
                detection_width=detection_width,
                detection_height=detection_height,
                ingestion_fps=ingestion_fps,
            ),
            daemon=True,
            name=f"Ingestion-{cam_id}",
        )
        self.processes[cam_id] = proc
        proc.start()

        # Result handler thread
        rh_stop = threading.Event()
        self._result_handler_stop_events[cam_id] = rh_stop

        rh_thread = threading.Thread(
            target=result_handler_worker,
            kwargs=dict(
                cam_id=cam_id,
                result_queue=self.result_queues[cam_id],
                frame_dict=self.frame_dict,
                lock=self.lock,
                threshold=threshold,
                helmet_class=self.helmet_class or "",
                no_helmet_class=self.no_helmet_class or "",
                cooldown=cooldown,
                stop_event=rh_stop,
                stats_dict=self.stats_dict,
                assigned_buzzers=assigned_buzzers,
                alert_queue=self.alert_queue,
                snapshot_cooldown=snapshot_cooldown,
                detection_width=detection_width,
                detection_height=detection_height,
                yolo_imgsz=yolo_imgsz,
                enabled_models=enabled_models,
                violation_classes=violation_classes or self.violation_classes,
                safe_classes=safe_classes or self.safe_classes,
                burglar_alarm_config=burglar_alarm_cfg,
                burglar_test_sound=bool(burglar_test_sound),
                feature_config=feature_config,
            ),
            daemon=True,
            name=f"ResultHandler-{cam_id}",
        )
        self._result_handler_threads[cam_id] = rh_thread
        rh_thread.start()

        print(
            f"[CameraManager] Camera {cam_id} started — "
            f"PID={proc.pid}, TID={rh_thread.native_id} "
            f"({len(assigned_buzzers)} buzzer(s))"
        )

    # ── Alert writer ───────────────────────────────────────────────────────────

    def _start_alert_writer(self):
        if self._alert_writer_thread and self._alert_writer_thread.is_alive():
            return
        self._alert_writer_thread = threading.Thread(
            target=alert_writer_loop,
            args=(self.alert_queue,),
            daemon=True,
            name="AlertWriter",
        )
        self._alert_writer_thread.start()
        print("[CameraManager] AlertWriter started.")

    def _stop_alert_writer(self):
        if self._alert_writer_thread and self._alert_writer_thread.is_alive():
            self.alert_queue.put(STOP_SENTINEL)
            self._alert_writer_thread.join(timeout=5)
        self._alert_writer_thread = None


# Module-level singleton — imported directly by route modules
camera_manager = CameraManager()
