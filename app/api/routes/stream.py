"""
app/api/routes/stream.py
------------------------
MJPEG streaming endpoint.

Each camera's latest annotated JPEG frame is stored in CameraManager.frame_dict
by the background camera thread. This endpoint serves those frames as a
multipart/x-mixed-replace MJPEG stream — the browser simply sets the stream
URL as an <img src> and it updates in real time.

The async generator sleeps 33 ms between frames (~30 fps cap). If the camera
has no frame yet (not started or still connecting) it yields a 1x1 placeholder
JPEG to keep the HTTP connection alive without spinning.

GET /api/stream/{cam_id}     — live MJPEG stream for that camera
GET /api/stream/status/all   — JSON snapshot of per-camera stats
"""

import asyncio
from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.services.camera_manager import camera_manager

router = APIRouter()

# Minimal valid JPEG (1×1 dark gray pixel) served while camera is warming up
PLACEHOLDER_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t"
    b"\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a"
    b"\x1f\x1e\x1d\x1a\x1c\x1c $.' \",#\x1c\x1c(7),01444\x1f'9=82<.342\x1e"
    b"C\x00\t\t\t\x0c\x0b\x0c\x18\r\r\x182!\x1c!22222222222222222222222222"
    b"22222222222222222222222222\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01"
    b"\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01\x01\x01"
    b"\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04\x05\x06\x07"
    b"\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03\x03\x02\x04\x03"
    b"\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03\x00\x04\x11\x05\x12!"
    b"1A\x06\x13Qa\x07\"q\x142\x81\x91\xa1\x08#B\xb1\xc1\x15R\xd1"
    b"\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%&'()*456789:CDEFGHIJ"
    b"STUVWXYZ\xff\xda\x00\x08\x01\x01\x00\x00?\x00\xf5\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xd9"
)


@router.get("/{cam_id}")
async def stream_camera(cam_id: int, request: Request):
    """
    Stream annotated JPEG frames for a single camera as MJPEG.

    Use as an <img> src in the browser:
        <img src="/api/stream/0">

    The stream runs indefinitely until the client disconnects.
    """
    async def generate():
        try:
            while True:
                # Important: break as soon as browser navigates away/unmounts <img>
                # to avoid orphan MJPEG responses consuming connection slots.
                if await request.is_disconnected():
                    break

                frame = camera_manager.get_latest_frame(cam_id)
                # Fall back to placeholder if camera hasn't produced a frame yet
                jpeg = frame if frame is not None else PLACEHOLDER_JPEG
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n\r\n" + jpeg + b"\r\n"
                )
                await asyncio.sleep(0.033)  # ~30 fps — prevents busy-looping the event loop
        except asyncio.CancelledError:
            # Client connection closed; exit generator cleanly.
            return

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
        headers={
            # Prevent proxy/browser buffering that can stall visible updates.
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Pragma": "no-cache",
            "Expires": "0",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/status/all")
def stream_status():
    """Return a snapshot of per-camera stats (fps, violations, status)."""
    return camera_manager.get_stats()
