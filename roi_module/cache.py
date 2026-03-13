"""
Thread-safe in-memory ROI cache.

Keyed by camera_id → list of active ROI dicts.
Supports TTL expiry and explicit invalidation on CRUD operations.
"""

from __future__ import annotations

import threading
import time
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class ROICache:
    """Thread-safe LRU-style cache with per-entry TTL."""

    def __init__(self, ttl_seconds: int = 60) -> None:
        self._store: Dict[str, List[dict]] = {}
        self._timestamps: Dict[str, float] = {}
        self._lock = threading.RLock()
        self._ttl = ttl_seconds

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, camera_id: str) -> Optional[List[dict]]:
        with self._lock:
            if camera_id not in self._store:
                return None
            age = time.monotonic() - self._timestamps.get(camera_id, 0)
            if age > self._ttl:
                self._evict(camera_id)
                logger.debug("ROI cache expired for camera %s", camera_id)
                return None
            return self._store[camera_id]

    def set(self, camera_id: str, rois: List[dict]) -> None:
        with self._lock:
            self._store[camera_id] = rois
            self._timestamps[camera_id] = time.monotonic()
            logger.debug("ROI cache set for camera %s (%d entries)", camera_id, len(rois))

    def invalidate(self, camera_id: str) -> None:
        with self._lock:
            self._evict(camera_id)
            logger.debug("ROI cache invalidated for camera %s", camera_id)

    def invalidate_all(self) -> None:
        with self._lock:
            self._store.clear()
            self._timestamps.clear()
            logger.debug("ROI cache fully cleared")

    def stats(self) -> dict:
        with self._lock:
            return {
                "entries": len(self._store),
                "camera_ids": list(self._store.keys()),
                "ttl_seconds": self._ttl,
            }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _evict(self, camera_id: str) -> None:
        self._store.pop(camera_id, None)
        self._timestamps.pop(camera_id, None)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_cache: Optional[ROICache] = None
_cache_lock = threading.Lock()


def get_roi_cache() -> ROICache:
    """Return the module-level ROICache singleton (lazy init)."""
    global _cache
    if _cache is None:
        with _cache_lock:
            if _cache is None:
                from .config import roi_config
                _cache = ROICache(ttl_seconds=roi_config.cache_ttl_seconds)
    return _cache
