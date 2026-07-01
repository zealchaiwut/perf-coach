"""Periodic refit scheduler using :class:`threading.Timer` (issue #1170).

Fires a caller-supplied refit callable on a configurable schedule expressed
in seconds.  The default interval is weekly (``WEEKLY_INTERVAL_SECONDS``).

Typical usage::

    from backend.services.model_refit import ModelRefitStore
    from backend.services.refit_scheduler import RefitScheduler

    store = ModelRefitStore(storage_dir="/var/data/fit_versions")

    def do_refit():
        pairs = fetch_training_pairs_from_db()
        store.run_refit(pairs)

    scheduler = RefitScheduler()
    scheduler.start(interval_seconds=RefitScheduler.WEEKLY, refit_callable=do_refit)
    # scheduler.stop() — call on application shutdown
"""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

logger = logging.getLogger(__name__)

WEEKLY_INTERVAL_SECONDS: int = 7 * 24 * 3600


class RefitScheduler:
    """Periodic scheduler that calls *refit_callable* every *interval_seconds*.

    The first invocation fires after the first full interval has elapsed (not
    immediately on start), matching standard cron semantics.
    """

    WEEKLY: int = WEEKLY_INTERVAL_SECONDS

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None
        self._running: bool = False
        self._interval: float = float(WEEKLY_INTERVAL_SECONDS)
        self._callable: Optional[Callable] = None

    def start(self, interval_seconds: float, refit_callable: Callable) -> None:
        """Start the scheduler; fires *refit_callable* every *interval_seconds*.

        Calling :meth:`start` on an already-running scheduler is a no-op.
        """
        with self._lock:
            if self._running:
                return
            self._interval = float(interval_seconds)
            self._callable = refit_callable
            self._running = True
            self._arm()
        logger.info(
            "refit_scheduler: started; interval=%.1fs callable=%s",
            interval_seconds,
            getattr(refit_callable, "__name__", repr(refit_callable)),
        )

    def stop(self) -> None:
        """Stop the scheduler and cancel any pending timer."""
        with self._lock:
            self._running = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None
        logger.info("refit_scheduler: stopped")

    def is_running(self) -> bool:
        """Return ``True`` if the scheduler is active."""
        with self._lock:
            return self._running

    # ── Internals ──────────────────────────────────────────────────────────────

    def _arm(self) -> None:
        self._timer = threading.Timer(self._interval, self._fire)
        self._timer.daemon = True
        self._timer.start()

    def _fire(self) -> None:
        with self._lock:
            if not self._running:
                return
        try:
            self._callable()
        except Exception as exc:
            logger.exception("refit_scheduler: refit callable raised: %s", exc)
        with self._lock:
            if self._running:
                self._arm()
