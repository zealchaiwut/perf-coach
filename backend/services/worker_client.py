"""Delegation seam for heavy paths (worker_app.py).

Trigger mode (WORKER_TRIGGER_MODE, default "queue"):
  queue  — enqueue a row in the Neon-backed job_queue; the worker pulls it
           (backend/services/job_queue.py). Both machines only connect OUTBOUND
           to Neon, so the worker can sit behind home NAT. This is the production
           path. Enqueue is a DB insert, so the worker being offline no longer
           fails the request — the job simply waits in `queued`.
  http   — POST to the worker over HTTP (the legacy push path). Kept for local
           dev / rollout fallback; requires WORKER_BASE_URL + WORKER_SHARED_SECRET.

The function SIGNATURES are unchanged so main.py call sites are untouched.

Environment variables:
  WORKER_TRIGGER_MODE           "queue" (default) | "http".
  WORKER_BASE_URL               Worker URL for http mode, e.g. http://zeal-server:9100.
  WORKER_SHARED_SECRET          Shared secret sent as X-Worker-Secret (http mode).
  ROUTE_FULL_SYNC_FALLBACK_TO_INPROCESS  Set "1" to allow in-process fallback when
                                          the worker is unreachable (opt-in, off by default).
  ROUTE_BACKFILL_FALLBACK_TO_INPROCESS   Same for backfill (opt-in, off by default).
"""
import json
import os
import urllib.request as _urllib_request
import urllib.error


class WorkerUnavailable(Exception):
    """Raised when the compute worker cannot be reached or is not configured
    (http mode only — queue mode never raises this since enqueue is a DB insert)."""


def _trigger_mode() -> str:
    mode = os.getenv("WORKER_TRIGGER_MODE", "queue").strip().lower()
    return mode if mode in ("queue", "http") else "queue"


def should_delegate() -> bool:
    """Whether a heavy job should be handed to the worker rather than run inline.

    queue mode: always (enqueue is a cheap, safe DB insert — the worker being
    offline just leaves the job `queued`). http mode: only when WORKER_BASE_URL
    is configured (otherwise there's nothing to POST to, so run in-process)."""
    if _trigger_mode() == "queue":
        return True
    return get_worker_base_url() is not None


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
    """Delegate a sync job to the worker. queue mode enqueues one job per source
    (dedupe_key mirrors the worker's single-flight intent); http mode POSTs."""
    if _trigger_mode() == "http":
        return _post(
            "/internal/sync/run",
            {"user_id": user_id, "sources": sources, "full": full, "triggered_by": triggered_by},
        )

    from backend.services import job_queue
    job_ids = []
    for source in sources:
        jid = job_queue.enqueue(
            f"{source}_sync",
            {"user_id": user_id, "full": full, "triggered_by": triggered_by},
            enqueued_by="web",
            dedupe_key=f"{source}_sync:{user_id}",
        )
        if jid:
            job_ids.append(jid)
    return {"started": True, "queued": True, "job_ids": job_ids}


def delegate_backfill(user_id: str) -> dict:
    """Delegate a performance backfill to the worker. queue mode enqueues; http POSTs."""
    if _trigger_mode() == "http":
        return _post("/internal/performance/backfill", {"user_id": user_id})

    from backend.services import job_queue
    jid = job_queue.enqueue(
        "backfill",
        {"user_id": user_id},
        enqueued_by="web",
        dedupe_key=f"backfill:{user_id}",
    )
    return {"started": True, "queued": True, "job_ids": [jid] if jid else []}
