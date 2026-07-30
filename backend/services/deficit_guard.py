"""Deficit auto-pause — the guards that stop a cut before it costs fitness.

The rule that shapes every string in this module
------------------------------------------------
When a guard fires, the copy says **EAT MORE**. Never "try harder", never
"tighten up", never anything that reads as the athlete's fault. A paused deficit
is the program working, not the athlete failing, and copy that implies otherwise
turns a safety mechanism into a reason to disengage.

``assert_eat_more_copy`` enforces this at import time for every message here, so
a future edit can't quietly reintroduce a scolding.

Triggers (spec §4) — any one pauses
-----------------------------------
========================  =====================================================
``injury_or_illness``     a niggle, injury or illness is logged and open
``ctl_falling``           chronic load is dropping while the deficit is on
``scores_declining``      endurance or speed down 2+ consecutive weeks
``recovery_degrading``    RHR rising or sleep shortening against baseline
``lean_mass_falling``     lean-mass trend down 3+ weeks — the scale's real job
========================  =====================================================

Each is computed from data the app already owns; none involves an LLM. The
engine is a pure function over gathered inputs (``evaluate``), with a thin DB
wrapper (``guard_for_user``) so callers don't hand-roll the queries.

Why pause rather than warn
--------------------------
A warning next to an unchanged deficit is a warning that gets scrolled past. The
deficit actually goes to zero: ``effective_deficit_kcal`` returns 0 while any
guard is active, and the fuel budget follows it up automatically.
"""
from __future__ import annotations

import logging
from datetime import date as _date, timedelta as _timedelta
from typing import Optional

_log = logging.getLogger(__name__)

# Consecutive weeks of decline before the score guard fires.
SCORE_DECLINE_WEEKS = 2
# CTL drop (TSS/day) over the trailing window that counts as "falling" rather
# than noise — the EWMA wobbles by a few tenths day to day.
CTL_FALL_THRESHOLD = 2.0
CTL_LOOKBACK_DAYS = 14
# Resting-HR rise and sleep loss against the trailing baseline that count as
# recovery degrading. Both are deliberately generous: this guard should fire on
# a trend, not on one bad night.
RHR_RISE_BPM = 3.0
SLEEP_DROP_HOURS = 0.75
RECOVERY_RECENT_DAYS = 7
RECOVERY_BASELINE_DAYS = 28

# One message per trigger. Every one says eat more.
PAUSE_COPY = {
    "injury_or_illness": (
        "Deficit paused — you're carrying an injury or illness. Eat more: "
        "recovery needs the energy more than the cut does."
    ),
    "ctl_falling": (
        "Deficit paused — your chronic load is falling while you're in a "
        "deficit. Eat more and let the training come back first."
    ),
    "scores_declining": (
        "Deficit paused — endurance or speed has been sliding for two weeks. "
        "Eat more; the cut is costing you fitness."
    ),
    "recovery_degrading": (
        "Deficit paused — resting HR and sleep say you're under-recovered. "
        "Eat more until they settle."
    ),
    "lean_mass_falling": (
        "Deficit paused — lean mass has been falling for three weeks. Eat more: "
        "this is the weight you don't want to lose."
    ),
}

_BANNED_PHRASES = ("try harder", "tighten up", "discipline", "willpower", "cheat", "failed")


def assert_eat_more_copy(message: str) -> str:
    """Guard the tone contract: every pause message says eat more and blames nobody."""
    lowered = message.lower()
    if "eat more" not in lowered:
        raise ValueError(f"pause copy must say 'eat more': {message!r}")
    for phrase in _BANNED_PHRASES:
        if phrase in lowered:
            raise ValueError(f"pause copy must not say {phrase!r}: {message!r}")
    return message


for _msg in PAUSE_COPY.values():  # fail at import, not in front of the athlete
    assert_eat_more_copy(_msg)


def evaluate(
    *,
    has_open_injury_or_illness: bool = False,
    ctl_change_14d: Optional[float] = None,
    endurance_declining_weeks: int = 0,
    speed_declining_weeks: int = 0,
    rhr_recent: Optional[float] = None,
    rhr_baseline: Optional[float] = None,
    sleep_recent_hours: Optional[float] = None,
    sleep_baseline_hours: Optional[float] = None,
    lean_mass_falling_weeks: int = 0,
) -> dict:
    """Pure guard evaluation. Any trigger pauses; all firing reasons are reported.

    Missing inputs never trigger a pause — an absent signal is not a bad signal,
    and a guard that fires on missing data would pause the cut permanently for
    anyone who doesn't wear a sleep tracker.

    Returns ``{active, reasons[], reason, message, effective_deficit_multiplier}``.
    ``reason`` is the highest-priority firing trigger, for a one-line summary.
    """
    reasons: list[str] = []

    if has_open_injury_or_illness:
        reasons.append("injury_or_illness")

    if ctl_change_14d is not None and ctl_change_14d <= -CTL_FALL_THRESHOLD:
        reasons.append("ctl_falling")

    if (
        endurance_declining_weeks >= SCORE_DECLINE_WEEKS
        or speed_declining_weeks >= SCORE_DECLINE_WEEKS
    ):
        reasons.append("scores_declining")

    rhr_rising = (
        rhr_recent is not None
        and rhr_baseline is not None
        and (rhr_recent - rhr_baseline) >= RHR_RISE_BPM
    )
    sleep_short = (
        sleep_recent_hours is not None
        and sleep_baseline_hours is not None
        and (sleep_baseline_hours - sleep_recent_hours) >= SLEEP_DROP_HOURS
    )
    if rhr_rising or sleep_short:
        reasons.append("recovery_degrading")

    from backend.services.body_composition import LEAN_MASS_FALL_WEEKS

    if lean_mass_falling_weeks >= LEAN_MASS_FALL_WEEKS:
        reasons.append("lean_mass_falling")

    # Priority order for the single-line summary: the most physically urgent
    # reason first, so a niggle isn't reported as a sleep problem.
    priority = (
        "injury_or_illness",
        "lean_mass_falling",
        "scores_declining",
        "ctl_falling",
        "recovery_degrading",
    )
    primary = next((r for r in priority if r in reasons), None)

    return {
        "active": bool(reasons),
        "reasons": reasons,
        "reason": primary,
        "message": PAUSE_COPY[primary] if primary else None,
        "effective_deficit_multiplier": 0.0 if reasons else 1.0,
    }


# ── DB-backed gathering ──────────────────────────────────────────────────────

def _gather_injury(db, user_id) -> bool:
    from backend.models import InjuryLog

    return (
        db.query(InjuryLog)
        .filter(
            InjuryLog.user_id == user_id,
            InjuryLog.ended_on.is_(None),
            InjuryLog.kind.in_(("niggle", "injury", "illness")),
        )
        .first()
        is not None
    )


def _gather_ctl_change(user_id, today: _date) -> Optional[float]:
    from backend.services.training_load import current_load

    now = current_load(str(user_id), as_of=today)
    then = current_load(str(user_id), as_of=today - _timedelta(days=CTL_LOOKBACK_DAYS))
    if now is None or then is None:
        return None
    return round(float(now.get("ctl") or 0.0) - float(then.get("ctl") or 0.0), 2)


def _declining_weeks(series: list[tuple[_date, float]]) -> int:
    """Consecutive most-recent weekly points that fell from the one before."""
    weeks = 0
    for newer, older in zip(reversed(series), reversed(series[:-1])):
        if newer[1] < older[1]:
            weeks += 1
        else:
            break
    return weeks


def _gather_score_declines(db, user_id, today: _date) -> tuple[int, int]:
    """Weekly endurance/speed samples from the persisted score history."""
    from backend.models import PerformanceScoreHistory

    start = today - _timedelta(weeks=8)
    rows = (
        db.query(
            PerformanceScoreHistory.score_date,
            PerformanceScoreHistory.endurance,
            PerformanceScoreHistory.speed,
        )
        .filter(
            PerformanceScoreHistory.user_id == user_id,
            PerformanceScoreHistory.score_date >= start,
            PerformanceScoreHistory.score_date <= today,
        )
        .order_by(PerformanceScoreHistory.score_date.asc())
        .all()
    )
    if not rows:
        return 0, 0

    # One sample per ISO week (the last of each) so day-to-day decay doesn't
    # read as a multi-week decline.
    by_week: dict = {}
    for d, end_score, spd_score in rows:
        by_week[d - _timedelta(days=d.weekday())] = (end_score, spd_score)
    weeks_sorted = sorted(by_week)

    endurance = [(w, by_week[w][0]) for w in weeks_sorted if by_week[w][0] is not None]
    speed = [(w, by_week[w][1]) for w in weeks_sorted if by_week[w][1] is not None]
    return _declining_weeks(endurance), _declining_weeks(speed)


def _gather_recovery(db, user_id, today: _date) -> dict:
    from sqlalchemy import func

    from backend.models import DailyMetric

    def _means(days: int) -> tuple[Optional[float], Optional[float]]:
        start = today - _timedelta(days=days)
        row = (
            db.query(
                func.avg(DailyMetric.resting_hr),
                func.avg(DailyMetric.sleep_hours),
            )
            .filter(
                DailyMetric.user_id == user_id,
                DailyMetric.metric_date > start,
                DailyMetric.metric_date <= today,
            )
            .first()
        )
        rhr = float(row[0]) if row and row[0] is not None else None
        sleep = float(row[1]) if row and row[1] is not None else None
        return rhr, sleep

    rhr_recent, sleep_recent = _means(RECOVERY_RECENT_DAYS)
    rhr_base, sleep_base = _means(RECOVERY_BASELINE_DAYS)
    return {
        "rhr_recent": rhr_recent,
        "rhr_baseline": rhr_base,
        "sleep_recent_hours": sleep_recent,
        "sleep_baseline_hours": sleep_base,
    }


def guard_for_user(db, user_id, today: Optional[_date] = None) -> dict:
    """Evaluate every auto-pause trigger for a user.

    Each gatherer is individually guarded: a signal the app can't read must not
    pause the deficit *or* take the whole guard down. A missing input is treated
    as "no evidence", which is the only safe reading of silence.
    """
    today = today or _date.today()

    def _safe(label, fn, fallback):
        try:
            return fn()
        except Exception as exc:  # pragma: no cover — exercised via degraded tests
            _log.warning("deficit guard input %s unavailable: %s", label, exc)
            return fallback

    from backend.services.body_composition import composition_for_user

    injury = _safe("injury", lambda: _gather_injury(db, user_id), False)
    ctl_change = _safe("ctl", lambda: _gather_ctl_change(user_id, today), None)
    end_weeks, spd_weeks = _safe(
        "scores", lambda: _gather_score_declines(db, user_id, today), (0, 0)
    )
    recovery = _safe("recovery", lambda: _gather_recovery(db, user_id, today), {})
    composition = _safe(
        "composition", lambda: composition_for_user(db, user_id, today), {}
    )

    return evaluate(
        has_open_injury_or_illness=injury,
        ctl_change_14d=ctl_change,
        endurance_declining_weeks=end_weeks,
        speed_declining_weeks=spd_weeks,
        rhr_recent=recovery.get("rhr_recent"),
        rhr_baseline=recovery.get("rhr_baseline"),
        sleep_recent_hours=recovery.get("sleep_recent_hours"),
        sleep_baseline_hours=recovery.get("sleep_baseline_hours"),
        lean_mass_falling_weeks=composition.get("lean_mass_falling_weeks", 0),
    )
