"""HTTP client for delegating heavy paths to the compute worker (worker_app.py).

Environment variables:
  WORKER_BASE_URL               Base URL of the compute worker, e.g. http://zeal-server:9100
                                If unset, delegate_* functions raise WorkerUnavailable.
  WORKER_SHARED_SECRET          Shared secret sent as X-Worker-Secret header.
  ROUTE_FULL_SYNC_FALLBACK_TO_INPROCESS  Set to "1" to allow in-process fallback when
                                          the worker is unreachable (opt-in, off by default).
  ROUTE_BACKFILL_FALLBACK_TO_INPROCESS   Same for backfill (opt-in, off by default).
"""
import json
import os
import urllib.request as _urllib_request
import urllib.error


class WorkerUnavailable(Exception):
    """Raised when the compute worker cannot be reached or is not configured."""


def get_worker_base_url() -> str | None:
    return os.getenv("WORKER_BASE_URL", "").strip() or None


def get_worker_shared_secret() -> str | None:
    return os.getenv("WORKER_SHARED_SECRET", "").strip() or None


def _post(path: str, payload: dict, timeout: int = 10) -> dict:
    base_url = get_worker_base_url()
    if not base_url:
        raise WorkerUnavailable("WORKER_BASE_URL is not configured")

    secret = get_worker_shared_secret()
    if not secret:
        raise WorkerUnavailable("WORKER_SHARED_SECRET is not configured")

    url = base_url.rstrip("/") + path
    data = json.dumps(payload).encode()
    req = _urllib_request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "X-Worker-Secret": secret,
        },
        method="POST",
    )
    try:
        with _urllib_request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.URLError as exc:
        raise WorkerUnavailable(f"Worker unreachable: {exc}") from exc
    except Exception as exc:
        raise WorkerUnavailable(f"Worker request failed: {exc}") from exc


def delegate_sync(
    user_id: str,
    sources: list[str],
    full: bool = False,
    triggered_by: str = "manual",
) -> dict:
    """Delegate a sync job to the worker's /internal/sync/run."""
    return _post(
        "/internal/sync/run",
        {
            "user_id": user_id,
            "sources": sources,
            "full": full,
            "triggered_by": triggered_by,
        },
    )


def delegate_backfill(user_id: str) -> dict:
    """Delegate a performance backfill to the worker's /internal/performance/backfill."""
    return _post("/internal/performance/backfill", {"user_id": user_id})
