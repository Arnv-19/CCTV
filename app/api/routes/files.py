"""
app/api/routes/files.py
-----------------------
Server-side file browser — admin only.

Endpoint:
  GET /api/files/browse?dir=weights   List .pt / .task files under the project root.
  Returns a sorted list of paths relative to the project root.
"""

from pathlib import Path
from fastapi import APIRouter, Depends, Query, HTTPException

from app.dependencies import require_admin
from app.db.models import User

router = APIRouter()

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_ALLOWED_EXTENSIONS = {".pt", ".task"}


@router.get("/browse")
def browse_files(
    dir: str = Query("", description="Subdirectory relative to project root"),
    _: User = Depends(require_admin),
):
    """
    Return all model weight files (.pt, .task) found under *dir* (default: project root).
    Path traversal is blocked — only paths inside the project root are allowed.
    """
    base = _PROJECT_ROOT

    if dir:
        try:
            target = (base / dir).resolve()
            target.relative_to(base)   # raises ValueError if outside project root
        except ValueError:
            raise HTTPException(400, "Directory outside project root is not allowed")
    else:
        target = base

    if not target.exists():
        return []

    files = []
    for ext in _ALLOWED_EXTENSIONS:
        for p in sorted(target.rglob(f"*{ext}")):
            try:
                files.append(str(p.relative_to(base)))
            except ValueError:
                pass

    return sorted(files)
