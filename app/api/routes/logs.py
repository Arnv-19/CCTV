"""
app/api/routes/logs.py
----------------------
Endpoints for reading and clearing the violation log.

The log file (logs/alerts.log) is appended to by camera_worker.log_violation()
whenever a no-helmet detection fires. This endpoint lets the frontend poll for
recent entries without exposing filesystem access directly.

GET    /api/logs/?lines=100   Return the last N lines (default 100, max 1000)
DELETE /api/logs/             Truncate the log file to empty
"""

from fastapi import APIRouter, Query
from pathlib import Path

router = APIRouter()

# Absolute path to the alert log file
LOG_PATH = Path(__file__).parent.parent.parent.parent / "logs" / "alerts.log"


@router.get("/")
def get_logs(lines: int = Query(default=100, ge=1, le=1000)):
    """
    Return the most recent `lines` entries from alerts.log.
    Returns an empty list if the file does not exist yet.
    """
    if not LOG_PATH.exists():
        return {"logs": []}
    with open(LOG_PATH, "r") as f:
        all_lines = f.readlines()
    # Slice from the end to get the most recent entries
    recent = all_lines[-lines:]
    return {"logs": [l.strip() for l in recent if l.strip()]}


@router.delete("/")
def clear_logs():
    """Truncate alerts.log to empty (does not delete the file)."""
    if LOG_PATH.exists():
        LOG_PATH.write_text("")
    return {"message": "Logs cleared"}
