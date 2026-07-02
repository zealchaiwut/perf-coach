"""Thread-safe in-memory registry for background sync jobs."""
import threading
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional
import uuid

_registry: dict[uuid.UUID, dict] = {}
_lock = threading.Lock()
_TTL = timedelta(hours=24)


class SyncInProgress(Exception):
    pass


def _prune() -> None:
    """Evict finished jobs older than _TTL. Must be called under _lock."""
    cutoff = datetime.now(timezone.utc) - _TTL
    stale = [uid for uid, j in _registry.items()
             if j["finished_at"] is not None and j["finished_at"] < cutoff]
    for uid in stale:
        del _registry[uid]


def start(user_id: uuid.UUID, provider: Literal["strava", "stryd"]) -> dict:
    with _lock:
        _prune()
        existing = _registry.get(user_id)
        if existing and existing["status"] == "running":
            raise SyncInProgress(f"Sync already running for user {user_id}")
        job = {
            "provider": provider,
            "status": "running",
            "phase": None,
            "current": 0,
            "total": None,
            "items_synced": 0,
            "started_at": datetime.now(timezone.utc),
            "finished_at": None,
            "error": None,
        }
        _registry[user_id] = job
        return job


def set_phase(user_id: uuid.UUID, phase: Optional[str]) -> None:
    with _lock:
        if user_id in _registry:
            _registry[user_id]["phase"] = phase


def increment(user_id: uuid.UUID, *, current: int = 0, items_synced: int = 0) -> None:
    with _lock:
        if user_id in _registry:
            _registry[user_id]["current"] += current
            _registry[user_id]["items_synced"] += items_synced


def reset_progress(user_id: uuid.UUID, total: int) -> None:
    with _lock:
        if user_id in _registry:
            _registry[user_id]["current"] = 0
            _registry[user_id]["total"] = total


def mark_success(user_id: uuid.UUID) -> None:
    with _lock:
        if user_id in _registry:
            _registry[user_id]["status"] = "success"
            _registry[user_id]["finished_at"] = datetime.now(timezone.utc)


def mark_error(user_id: uuid.UUID, error: str) -> None:
    with _lock:
        if user_id in _registry:
            _registry[user_id]["status"] = "error"
            _registry[user_id]["error"] = error
            _registry[user_id]["finished_at"] = datetime.now(timezone.utc)


def snapshot(user_id: uuid.UUID) -> Optional[dict]:
    with _lock:
        job = _registry.get(user_id)
        if job is None:
            return None
        return dict(job)
