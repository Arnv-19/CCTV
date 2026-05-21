"""
app/main.py
-----------
FastAPI application factory.

Startup: initialises the DB (tables + admin seed), loads YOLO model,
         opens serial port.
Shutdown: stops camera threads, closes serial.
"""

# Must be set before any multiprocessing objects (including mp.Manager) are
# created. 'spawn' is required on Linux+CUDA (fork is not GPU-safe) and is
# already the default on macOS — setting it explicitly makes both platforms
# behave identically.
import multiprocessing as _mp
if _mp.get_start_method(allow_none=True) is None:
    _mp.set_start_method("spawn")

import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.services.camera_manager import camera_manager

# Existing routes
from app.api.routes import cameras, config_routes, alarm, logs, stream

# New routes
from app.api.routes import auth, users, buzzers, camera_buzzers, camera_models, alerts as alerts_router, rois
from app.api.routes import burglar_alarm as burglar_alarm_router
from app.api.routes import ai_models as ai_models_router
from app.api.routes import camera_assignments as camera_assignments_router
from app.api.routes import missing_person, crowd_alert, dynamic_fps, snapshot_whatsapp, burglar_alarm_verify
from app.api.routes import files as files_router
from app.api.routes import vehicle_detection as vehicle_detection_router


class SafeStaticFiles(StaticFiles):
    """StaticFiles variant that safely ignores non-HTTP scopes (e.g. websockets)."""

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            if scope.get("type") == "websocket":
                await send({"type": "websocket.close", "code": 1000})
            return
        await super().__call__(scope, receive, send)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Ensure DB tables exist and admin is seeded on every startup
    try:
        from app.db.init_db import init
        init()
    except Exception as e:
        print(f"[DB] init_db warning: {e}")

    camera_manager.initialize()
    yield
    camera_manager.shutdown()


app = FastAPI(
    title="Axis CCTV",
    version="3.0.0",
    description="Real-time CCTV AI platform with PostgreSQL, JWT auth, and multi-transport alarms",
    lifespan=lifespan,
)

_raw_origins = os.getenv("CORS_ORIGINS", "*").strip()
_CORS_ORIGINS = [o.strip() for o in _raw_origins.split(",")] if "," in _raw_origins else [_raw_origins]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Existing routes ────────────────────────────────────────────────────────
app.include_router(cameras.router,       prefix="/api/cameras",  tags=["cameras"])
app.include_router(config_routes.router, prefix="/api/config",   tags=["config"])
app.include_router(alarm.router,         prefix="/api/alarm",    tags=["alarm"])
app.include_router(logs.router,          prefix="/api/logs",     tags=["logs"])
app.include_router(stream.router,        prefix="/api/stream",   tags=["stream"])

# ── New routes ─────────────────────────────────────────────────────────────
app.include_router(auth.router,            prefix="/api/auth",            tags=["auth"])
app.include_router(users.router,           prefix="/api/users",           tags=["users"])
app.include_router(buzzers.router,         prefix="/api/buzzers",         tags=["buzzers"])
app.include_router(camera_buzzers.router,  prefix="/api/camera-buzzers",  tags=["camera-buzzers"])
app.include_router(camera_models.router,   prefix="/api/camera-models",   tags=["camera-models"])
app.include_router(alerts_router.router,   prefix="/api/alerts",          tags=["alerts"])
app.include_router(rois.router,            prefix="/api/rois",            tags=["rois"])

# app.include_router(alerts_router.router,        prefix="/api/alerts",          tags=["alerts"])
# app.include_router(rois.router,                 prefix="/api/rois",            tags=["rois"])
app.include_router(burglar_alarm_router.router,       prefix="/api/burglar-alarm",        tags=["burglar-alarm"])
app.include_router(ai_models_router.router,           prefix="/api/ai-models",            tags=["ai-models"])
app.include_router(camera_assignments_router.router,  prefix="/api/camera-assignments",   tags=["camera-assignments"])
app.include_router(missing_person.router,             prefix="/api/missing-person",       tags=["missing-person"])
app.include_router(crowd_alert.router,                prefix="/api/crowd-alert",          tags=["crowd-alert"])
app.include_router(dynamic_fps.router,                prefix="/api/dynamic-fps",          tags=["dynamic-fps"])
app.include_router(snapshot_whatsapp.router,          prefix="/api/snapshot-whatsapp",    tags=["snapshot-whatsapp"])
app.include_router(burglar_alarm_verify.router,       prefix="/api/burglar-alarm/verify", tags=["burglar-alarm"])
app.include_router(files_router.router,               prefix="/api/files",                tags=["files"])
app.include_router(vehicle_detection_router.router,   prefix="/api/vehicle-detections",   tags=["vehicle-detections"])


# ── Health check (used by CI/CD deploy pipeline) ──────────────────────────
_START_TIME = time.time()

@app.get("/health", tags=["health"], include_in_schema=False)
def health():
    return JSONResponse({
        "status": "ok",
        "uptime_seconds": round(time.time() - _START_TIME, 1),
    })


# ── Serve React production build ──────────────────────────────────────────
frontend_build = Path(__file__).parent.parent / "frontend" / "dist"
if frontend_build.exists():
    app.mount("/", SafeStaticFiles(directory=str(frontend_build), html=True), name="static")
