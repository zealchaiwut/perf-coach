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
  WORKER_TIMEOUT_SECONDS        HTTP timeout in seconds for worker calls (default 10).
                                 Raise this on slow home-server links to avoid spurious
                                 503s for backfill or long sync delegation calls.
  ROUTE_FULL_SYNC_FALLBACK_TO_INPROCESS  Set "1" to allow in-process fallback when
                                          the worker is unreachable (opt-in, off by default).
  ROUTE_BACKFILL_FALLBACK_TO_INPROCESS   Same for backfill (opt-in, off by default).
"""
import json
import logging
import os
import urllib.request as _urllib_request
import urllib.error

_log = logging.getLogger(__name__)


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


def get_worker_timeout() -> int:
    raw = os.getenv("WORKER_TIMEOUT_SECONDS", "").strip()
    try:
        return int(raw) if raw else 10
    except ValueError:
        return 10


def _post(path: str, payload: dict, timeout: int | None = None) -> dict:
    base_url = get_worker_base_url()
    if not base_url:
        _log.warning("WORKER_BASE_URL is not configured")
        raise WorkerUnavailable("Worker configuration error")

    secret = get_worker_shared_secret()
    if not secret:
        _log.warning("WORKER_SHARED_SECRET is not configured")
        raise WorkerUnavailable("Worker configuration error")

    effective_timeout = timeout if timeout is not None else get_worker_timeout()
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
        with _urllib_request.urlopen(req, timeout=effective_timeout) as resp:
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
    timeout: int | None = None,
) -> dict:
    """Delegate a sync job to the worker. queue mode enqueues one job per source
    (dedupe_key mirrors the worker's single-flight intent); http mode POSTs."""
    if _trigger_mode() == "http":
        return _post(
            "/internal/sync/run",
            {"user_id": user_id, "sources": sources, "full": full, "triggered_by": triggered_by},
            timeout=timeout if timeout is not None else get_worker_timeout(),
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


def _flag_on(name: str, default: str = "1") -> bool:
    return os.getenv(name, default).strip().lower() not in ("0", "false", "no", "off", "")


def precompute_on_write_enabled() -> bool:
    """Whether a workout write should offload the training-load recompute to the
    worker (queue mode) instead of running the 180-day EWMA inline. Default on."""
    return _flag_on("PRECOMPUTE_ON_WRITE_ENABLED")


def precompute_after_sync_enabled() -> bool:
    """Whether the worker warms a user's load snapshot after a sync job. Default on."""
    return _flag_on("PRECOMPUTE_AFTER_SYNC_ENABLED")


def delegate_precompute(user_id: str, *, dates=None) -> dict:
    """Enqueue a load-snapshot precompute for one user (queue mode only).

    Deduped per user (`precompute:<user_id>`) so a burst of edits collapses to one
    job. In http mode there is no worker precompute endpoint, so this is a no-op
    and the caller runs its inline fallback. Never raises — a queue hiccup must
    not fail the workout write; the caller falls back to inline recompute."""
    if _trigger_mode() != "queue":
        return {"queued": False}
    try:
        from backend.services import job_queue
        payload = {"user_id": user_id}
        if dates:
            payload["dates"] = [str(d) for d in dates]
        jid = job_queue.enqueue(
            "precompute", payload, enqueued_by="web",
            dedupe_key=f"precompute:{user_id}",
        )
        return {"queued": True, "job_ids": [jid] if jid else []}
    except Exception:
        return {"queued": False}


def delegate_backfill(user_id: str, timeout: int | None = None) -> dict:
    """Delegate a performance backfill to the worker. queue mode enqueues; http POSTs."""
    if _trigger_mode() == "http":
        return _post(
            "/internal/performance/backfill",
            {"user_id": user_id},
            timeout=timeout if timeout is not None else get_worker_timeout(),
        )

    from backend.services import job_queue
    jid = job_queue.enqueue(
        "backfill",
        {"user_id": user_id},
        enqueued_by="web",
        dedupe_key=f"backfill:{user_id}",
    )
    return {"started": True, "queued": True, "job_ids": [jid] if jid else []}
