"""Scheduled batch Banister refit pipeline (issue #1206).

Entry point::

    from backend.services.banister_pipeline import run_banister_refit_pipeline
    results = run_banister_refit_pipeline(user_ids)

For each user:
  1. Fetch paired (tss_for_day, ctl) history from ``training_load_snapshots``.
  2. Call ``fit_banister_params``.
  3. On success: call ``validate_banister_fit``, then ``save_banister_params``.
  4. On failure (data gate, convergence failure, implausibility): emit a
     WARNING log and leave existing stored params (or population defaults) in
     effect.  No exception is surfaced.
"""

from __future__ import annotations

import logging
import uuid as _uuid_mod
from contextlib import contextmanager
from typing import Any, Callable, Iterator, List

from sqlalchemy.orm import Session

from backend.services.banister_fitting import fit_banister_params, validate_banister_fit
from backend.services.banister_params import save_banister_params
from backend.models import TrainingLoadSnapshot

_log = logging.getLogger("backend.services.banister_pipeline")


def fetch_banister_history(
    session: Session,
    user_id: Any,
) -> tuple[list[float], list[float]]:
    """Return paired (load_series, perf_series) for *user_id*.

    Queries ``training_load_snapshots`` ordered chronologically.
    Uses ``tss_for_day`` as the training-load input and ``ctl`` (Chronic
    Training Load) as the performance proxy — a smoothed fitness signal that
    accumulates the Banister model response for the athlete.

    Returns two parallel lists; both are empty when no snapshots exist.
    """
    rows = (
        session.query(TrainingLoadSnapshot.tss_for_day, TrainingLoadSnapshot.ctl)
        .filter(TrainingLoadSnapshot.user_id == user_id)
        .order_by(TrainingLoadSnapshot.snapshot_date)
        .all()
    )
    loads = [float(r.tss_for_day) for r in rows]
    perfs = [float(r.ctl) for r in rows]
    return loads, perfs


def run_banister_refit_pipeline(
    user_ids: List[str],
    *,
    session_factory: Callable[[], Any] | None = None,
) -> dict[str, str]:
    """Batch Banister parameter refit for the given user IDs.

    Parameters
    ----------
    user_ids:
        List of user ID strings to process in this batch.
    session_factory:
        Optional callable that returns a SQLAlchemy Session context manager.
        Defaults to ``Session(backend.db.engine)``.  Pass a custom factory
        in tests to use an in-memory SQLite session.

    Returns
    -------
    dict mapping each user ID string to one of:
    * ``"ok"``               — fit succeeded; new params stored.
    * ``"skipped:<reason>"`` — fit skipped; prior params / defaults unchanged.
    """
    _factory = session_factory or _default_session_factory()

    results: dict[str, str] = {}
    for user_id in user_ids:
        uid_str = str(user_id)
        try:
            with _factory() as session:
                outcome = _process_one_user(session, user_id)
                results[uid_str] = outcome
        except Exception:
            _log.exception("banister_pipeline: unhandled error for user %s", uid_str)
            results[uid_str] = "error"
    return results


# ── internals ────────────────────────────────────────────────────────────────


def _default_session_factory():
    from backend.db import engine

    @contextmanager
    def _factory() -> Iterator[Session]:
        with Session(engine) as sess:
            yield sess

    return _factory


def _to_uuid(user_id: Any) -> Any:
    """Coerce a string or UUID to a uuid.UUID object for SQLAlchemy queries."""
    if isinstance(user_id, _uuid_mod.UUID):
        return user_id
    try:
        return _uuid_mod.UUID(str(user_id))
    except ValueError:
        return user_id


def _process_one_user(session: Session, user_id: Any) -> str:
    """Fit, validate, and store Banister params for one user.

    Returns ``"ok"`` on success or a ``"skipped:<reason>"`` string when any
    guard-rail fires.  WARNING entries are logged for every skip.
    """
    uid = _to_uuid(user_id)
    loads, perfs = fetch_banister_history(session, uid)
    n = min(len(loads), len(perfs))

    params = fit_banister_params(loads, perfs)

    if params is None:
        if n < 14:
            reason = f"data gate: only {n} paired observation(s), minimum 14 required"
        else:
            reason = "fitting failed: convergence failure or implausible parameters"
        _log.warning(
            "banister_pipeline: skip user %s — %s",
            user_id,
            reason,
        )
        return f"skipped:{reason}"

    tau1, tau2, k1, k2 = params

    if not validate_banister_fit(tau1, tau2, k1, k2):
        reason = "post-fit validation failed (non-finite or out-of-range values)"
        _log.warning(
            "banister_pipeline: skip user %s — %s",
            user_id,
            reason,
        )
        return f"skipped:{reason}"

    save_banister_params(session, uid, tau1=tau1, tau2=tau2, k1=k1, k2=k2)
    session.commit()
    _log.info(
        "banister_pipeline: saved params for user %s — tau1=%.2f tau2=%.2f k1=%.4f k2=%.4f",
        uid,
        tau1,
        tau2,
        k1,
        k2,
    )
    return "ok"
