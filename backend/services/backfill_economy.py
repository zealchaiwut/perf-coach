"""Backfill economy model across historical strength and plyo sessions (issue #1149).

Reads all ``strength_sessions`` and ``plyo_sessions`` rows for a user, computes
economy stimulus per calendar date, then derives the lagged ceiling bonus for
each date in chronological order using ``compute_ceiling_bonus``.

The results are UPSERTED into ``economy_ceiling_snapshots`` so the function is
safe to call repeatedly (idempotent).

Default economy parameters
--------------------------
``speed_kmh``    : 10.0 km/h  — a typical easy-run warm-up pace used when
                   per-session speed data is unavailable.
``fitness_score``: 50.0       — mid-range default; avoids over-weighting or
                   under-weighting early in the backfill when CTL data may be
                   sparse.  A future pass can re-run with real CTL values once
                   ``training_load_snapshots`` is fully populated.

Strength-load derivation
------------------------
Priority 1: volume-load = ``sets × reps × load`` (all three must be non-null)
Priority 2: RPE-duration = ``session_rpe × duration_minutes`` (fallback)
Priority 3: 0.0 if neither pattern is available.

Multiple rows on the same date are summed before computing stimulus.

Public API
----------
_compute_strength_load(sets, reps, load, session_rpe, duration_minutes) → float
compute_economy_snapshots(strength_by_date, plyo_by_date, *, speed_kmh,
                           fitness_score) → list[dict]
backfill_economy_for_user(user_id, db) → dict  (summary)
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import text

from backend.services.ceiling_bonus import compute_ceiling_bonus
from backend.services.economy_stimulus import compute_economy_stimulus

# ── Default constants used when per-session speed/fitness data is unavailable ─

_DEFAULT_SPEED_KMH: float = 10.0
_DEFAULT_FITNESS_SCORE: float = 50.0


# ── Helpers ───────────────────────────────────────────────────────────────────

def _compute_strength_load(
    sets: Optional[int],
    reps: Optional[int],
    load: Optional[float],
    session_rpe: Optional[int],
    duration_minutes: Optional[int],
) -> float:
    """Derive a scalar strength-load value from a StrengthSession row.

    Priority 1: volume-load path (sets × reps × load).
    Priority 2: RPE × duration fallback.
    Priority 3: 0.0 when no computable path exists.
    """
    if sets is not None and reps is not None and load is not None:
        return float(sets) * float(reps) * float(load)
    if session_rpe is not None and duration_minutes is not None:
        return float(session_rpe) * float(duration_minutes)
    return 0.0


# ── Core computation (pure, no DB access) ────────────────────────────────────

def compute_economy_snapshots(
    strength_by_date: dict[date, float],
    plyo_by_date: dict[date, float],
    *,
    speed_kmh: float = _DEFAULT_SPEED_KMH,
    fitness_score: float = _DEFAULT_FITNESS_SCORE,
) -> list[dict]:
    """Compute economy stimulus and lagged ceiling bonus for each session date.

    Parameters
    ----------
    strength_by_date:
        Mapping of ``session_date → total_strength_load`` (sum of all strength
        rows for that day).
    plyo_by_date:
        Mapping of ``session_date → total_foot_contacts`` (sum of all plyo rows
        for that day).
    speed_kmh:
        Representative running speed used to weight each modality.
    fitness_score:
        Current athlete fitness level used to amplify the strength prior.

    Returns
    -------
    list[dict]
        One dict per unique session date, sorted chronologically.  Each dict
        has keys: ``snapshot_date``, ``economy_stimulus``, ``ceiling_bonus``.
    """
    all_dates = sorted(set(strength_by_date) | set(plyo_by_date))

    stimulus_history: list[tuple[date, float]] = []
    snapshots: list[dict] = []

    for session_date in all_dates:
        sl = strength_by_date.get(session_date, 0.0)
        pc = plyo_by_date.get(session_date, 0.0)
        stimulus = compute_economy_stimulus(sl, pc, speed_kmh, fitness_score)

        # Ceiling bonus uses only sessions BEFORE this date (prior history)
        bonus = compute_ceiling_bonus(stimulus_history, session_date)

        snapshots.append({
            "snapshot_date": session_date,
            "economy_stimulus": stimulus,
            "ceiling_bonus": bonus,
        })

        # Add today's stimulus to history for future sessions
        stimulus_history.append((session_date, stimulus))

    return snapshots


# ── DB-backed backfill ────────────────────────────────────────────────────────

def backfill_economy_for_user(user_id: str, db) -> dict:
    """Backfill economy ceiling snapshots for a single user.

    Reads ``strength_sessions`` and ``plyo_sessions``, computes stimuli and
    ceiling bonuses in chronological order, then UPSERTs the results into
    ``economy_ceiling_snapshots``.

    Parameters
    ----------
    user_id:
        UUID string of the target user.
    db:
        A SQLAlchemy connection or session that supports ``.execute(text, params)``.

    Returns
    -------
    dict with keys:
        ``sessions_processed`` — total unique session dates processed.
        ``strength_dates``     — number of distinct strength-session dates found.
        ``plyo_dates``         — number of distinct plyo-session dates found.
        ``snapshots_written``  — number of rows upserted.
    """
    # ── 1. Aggregate strength load by date ────────────────────────────────────
    strength_rows = db.execute(
        text(
            """
            SELECT session_date,
                   sets, reps, load::float, session_rpe, duration_minutes
            FROM strength_sessions
            WHERE user_id = :uid
            ORDER BY session_date
            """
        ),
        {"uid": user_id},
    ).fetchall()

    strength_by_date: dict[date, float] = {}
    for row in strength_rows:
        session_date, sets, reps, load, rpe, dur = (
            row[0], row[1], row[2], row[3], row[4], row[5]
        )
        sl = _compute_strength_load(
            sets=sets, reps=reps, load=load,
            session_rpe=rpe, duration_minutes=dur,
        )
        strength_by_date[session_date] = strength_by_date.get(session_date, 0.0) + sl

    # ── 2. Aggregate plyo foot contacts by date ───────────────────────────────
    plyo_rows = db.execute(
        text(
            """
            SELECT session_date, SUM(foot_contacts)::float AS total_contacts
            FROM plyo_sessions
            WHERE user_id = :uid
            GROUP BY session_date
            ORDER BY session_date
            """
        ),
        {"uid": user_id},
    ).fetchall()

    plyo_by_date: dict[date, float] = {
        row[0]: float(row[1]) for row in plyo_rows
    }

    # ── 3. Pure computation ───────────────────────────────────────────────────
    snapshots = compute_economy_snapshots(
        strength_by_date=strength_by_date,
        plyo_by_date=plyo_by_date,
    )

    # ── 4. Upsert into economy_ceiling_snapshots ──────────────────────────────
    for snap in snapshots:
        db.execute(
            text(
                """
                INSERT INTO economy_ceiling_snapshots
                    (user_id, snapshot_date, economy_stimulus, ceiling_bonus)
                VALUES (:user_id, :snapshot_date, :economy_stimulus, :ceiling_bonus)
                ON CONFLICT (user_id, snapshot_date) DO UPDATE SET
                    economy_stimulus = EXCLUDED.economy_stimulus,
                    ceiling_bonus    = EXCLUDED.ceiling_bonus,
                    computed_at      = now()
                """
            ),
            {
                "user_id": user_id,
                "snapshot_date": snap["snapshot_date"],
                "economy_stimulus": snap["economy_stimulus"],
                "ceiling_bonus": snap["ceiling_bonus"],
            },
        )

    return {
        "sessions_processed": len(snapshots),
        "strength_dates": len(strength_by_date),
        "plyo_dates": len(plyo_by_date),
        "snapshots_written": len(snapshots),
    }
