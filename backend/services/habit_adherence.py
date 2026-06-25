"""Pure functions for habit adherence: breakdowns, slipping detection, trend/nudge copy.

No database access. No network I/O. No side effects. Caller supplies all data.
"""

from __future__ import annotations

import datetime
from collections import defaultdict
from datetime import date, timedelta
from typing import Any


# Minimum number of log-days required to surface a meaningful breakdown.
_MIN_HISTORY_DAYS: int = 7

# A habit is "slipping" when adherence dropped at least this many percentage
# points from the previous window to the current window.
_SLIP_THRESHOLD: float = 10.0


def _iter_days(start: date, end: date):
    """Yield each date from start through end inclusive."""
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def compute_adherence_breakdown(
    habits: list[Any],
    logs_by_habit: dict,
    start_date: date,
    end_date: date,
) -> dict[str, Any]:
    """Compute per-habit adherence breakdowns over a date range.

    Pure function — no I/O, no DB access, no mutations.

    Parameters
    ----------
    habits:
        List of habit objects with ``.id`` (UUID or str) and ``.name`` (str).
    logs_by_habit:
        Mapping of str(habit_id) -> list of log objects with a ``.log_date``
        (date) attribute.
    start_date:
        First date of the evaluation window (inclusive).
    end_date:
        Last date of the evaluation window (inclusive).

    Returns
    -------
    dict
        Two keys:

        ``per_habit``
            List of per-habit dicts (one per habit), each with:
            - ``habit_id`` (str)
            - ``name`` (str)
            - ``completion_rate`` (float 0–100)
            - ``streak`` (int) — current consecutive logged days
            - ``missed_days`` (int)
            - ``total_days`` (int) — window length in days
            - ``logged_days`` (int)
            - ``weekday_pct`` (dict[int, float]) — adherence % per weekday (0=Mon)
            - ``overall_avg`` (float) — mean weekday adherence %

        ``building_state``
            Dict with ``active`` (bool) and ``reason`` (str or None).
            ``active`` is True when history is too short to be meaningful.
    """
    all_dates = list(_iter_days(start_date, end_date))
    total_days = len(all_dates)

    # Check global history length
    all_log_dates: set[date] = set()
    for logs in logs_by_habit.values():
        for log in logs:
            all_log_dates.add(log.log_date)

    if len(all_log_dates) < _MIN_HISTORY_DAYS:
        return {
            "per_habit": [],
            "building_state": {
                "active": True,
                "reason": (
                    f"Not enough history yet "
                    f"({len(all_log_dates)} of {_MIN_HISTORY_DAYS} required days logged)."
                ),
            },
        }

    per_habit = []

    for habit in habits:
        habit_id_str = str(habit.id)
        logs = logs_by_habit.get(habit_id_str, [])

        # Index logs by date (any log on a date counts as completion)
        logged_date_set: set[date] = {log.log_date for log in logs if start_date <= log.log_date <= end_date}
        logged_days = len(logged_date_set)
        missed_days = total_days - logged_days
        completion_rate = (logged_days / total_days * 100.0) if total_days > 0 else 0.0

        # Current streak: consecutive days back from end_date
        streak = 0
        d = end_date
        while d >= start_date:
            if d in logged_date_set:
                streak += 1
                d -= timedelta(days=1)
            else:
                break

        # Weekday adherence: group scheduled days by weekday and count completion
        weekday_scheduled: dict[int, int] = defaultdict(int)
        weekday_logged: dict[int, int] = defaultdict(int)
        for day in all_dates:
            wd = day.weekday()
            weekday_scheduled[wd] += 1
            if day in logged_date_set:
                weekday_logged[wd] += 1

        weekday_pct: dict[int, float] = {}
        for wd in range(7):
            sched = weekday_scheduled.get(wd, 0)
            if sched > 0:
                weekday_pct[wd] = weekday_logged.get(wd, 0) / sched * 100.0
            else:
                weekday_pct[wd] = 0.0

        overall_avg = sum(weekday_pct.values()) / 7.0 if weekday_pct else 0.0

        per_habit.append({
            "habit_id": habit_id_str,
            "name": habit.name,
            "completion_rate": round(completion_rate, 2),
            "streak": streak,
            "missed_days": missed_days,
            "total_days": total_days,
            "logged_days": logged_days,
            "weekday_pct": weekday_pct,
            "overall_avg": round(overall_avg, 2),
        })

    return {
        "per_habit": per_habit,
        "building_state": {"active": False, "reason": None},
    }


def detect_slipping_habits(
    current_breakdown: list[dict[str, Any]],
    prev_breakdown: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Identify habits whose adherence dropped materially between two windows.

    Pure function — no I/O, no DB access, no mutations.

    Parameters
    ----------
    current_breakdown:
        ``per_habit`` list from :func:`compute_adherence_breakdown` for the
        current window.
    prev_breakdown:
        ``per_habit`` list from :func:`compute_adherence_breakdown` for the
        previous (comparison) window.

    Returns
    -------
    list of dict
        Each dict has:
        - ``habit_id`` (str)
        - ``name`` (str)
        - ``prev_percent`` (float) — completion_rate in the prior window
        - ``current_percent`` (float) — completion_rate in the current window
        - ``drop`` (float) — how much it dropped (positive = worse)

        Only habits whose drop >= ``_SLIP_THRESHOLD`` are included.
        If prev_breakdown is empty (brand-new data), returns [].
    """
    if not current_breakdown or not prev_breakdown:
        return []

    prev_by_id = {h["habit_id"]: h for h in prev_breakdown}

    slipping = []
    for habit in current_breakdown:
        hid = habit["habit_id"]
        prev = prev_by_id.get(hid)
        if prev is None:
            continue
        prev_pct = float(prev["completion_rate"])
        curr_pct = float(habit["completion_rate"])
        drop = prev_pct - curr_pct
        if drop >= _SLIP_THRESHOLD:
            slipping.append({
                "habit_id": hid,
                "name": habit["name"],
                "prev_percent": round(prev_pct, 2),
                "current_percent": round(curr_pct, 2),
                "drop": round(drop, 2),
            })

    return slipping


# Minimum number of distinct logged days before we consider a habit "built"
MIN_HISTORY_DAYS = 7

# Words that must never appear in nudge copy (AC12)
FORBIDDEN_NUDGE_WORDS: frozenset[str] = frozenset(
    {
        "failed",
        "failure",
        "missed",
        "bad",
        "lazy",
        "terrible",
        "awful",
        "disappointing",
        "shame",
        "shameful",
        "guilt",
        "guilty",
        "broke",
        "ruined",
    }
)

_DAY_NAMES = [
    "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",
]

# Nudge templates keyed by (trend, adherence_tier)
# adherence_tier: "high" ≥80%, "mid" 40–79%, "low" <40%
_NUDGES: dict[tuple[str, str], list[str]] = {
    ("stable", "high"): [
        "You've been really consistent — this habit is becoming part of you.",
        "Solid week. You're building something that lasts.",
        "Great consistency. Keep showing up just like this.",
    ],
    ("stable", "mid"): [
        "Good progress this week. Every day you show up counts.",
        "You're making it happen. Steady is strong.",
        "Progress over perfection — you're doing it.",
    ],
    ("stable", "low"): [
        "You're still in the game. Small steps build lasting change.",
        "Every effort counts, no matter the size. Keep going.",
        "You've got this. Each attempt moves you forward.",
    ],
    ("declining", "high"): [
        "You're still doing well — a small nudge to keep the momentum alive.",
        "Strong foundation here. A gentle reminder to keep the rhythm.",
        "You've built great consistency. Let's carry it forward.",
    ],
    ("declining", "mid"): [
        "The last few days have been quieter — that's okay. Pick one day to restart.",
        "Life has a way of interrupting routines. When you're ready, pick up where you left off.",
        "It's okay to pause. Whenever you're ready, we'll be here.",
    ],
    ("declining", "low"): [
        "Life happens. Whenever you're ready, we'll be here.",
        "No pressure — just here when you want to come back to this.",
        "Rest is part of the process. Come back when it feels right.",
    ],
    ("building", "any"): [
        "Keep going — your streak is just getting started.",
        "You're planting the seeds. Keep showing up.",
        "Every log counts. You're building something real.",
    ],
}


def _adherence_tier(pct: float) -> str:
    if pct >= 80:
        return "high"
    if pct >= 40:
        return "mid"
    return "low"


def _nudge_for(trend: str, adherence_pct: float, *, habit_name: str = "", idx: int = 0) -> str:
    if trend == "building":
        messages = _NUDGES[("building", "any")]
    else:
        tier = _adherence_tier(adherence_pct)
        messages = _NUDGES.get((trend, tier), _NUDGES[("stable", "mid")])
    return messages[idx % len(messages)]


def _count_this_week(logs: list, today: datetime.date, window: int = 7) -> int:
    """Count logs that fall within the most-recent `window` days (inclusive of today)."""
    cutoff = today - datetime.timedelta(days=window - 1)
    return sum(1 for log in logs if cutoff <= log.log_date <= today)


def _count_period(logs: list, start: datetime.date, end: datetime.date) -> int:
    return sum(1 for log in logs if start <= log.log_date <= end)


def _best_worst_day(logs: list) -> tuple[str | None, str | None]:
    """Return (best_day_name, worst_day_name) across all logs by day-of-week frequency.

    Returns (None, None) when there are no logs.
    """
    if not logs:
        return None, None

    counts: dict[int, int] = defaultdict(int)
    total_weeks_seen: dict[int, int] = defaultdict(int)

    for log in logs:
        counts[log.log_date.weekday()] += 1

    if not counts:
        return None, None

    # Need at least 2 distinct days to report a meaningful best/worst
    if len(counts) < 2:
        return None, None

    best_wd = max(counts, key=lambda wd: counts[wd])
    worst_wd = min(counts, key=lambda wd: counts[wd])

    # Only differ if they're actually different
    if best_wd == worst_wd:
        return None, None

    return _DAY_NAMES[best_wd], _DAY_NAMES[worst_wd]


def compute_habit_adherence(
    habit: Any,
    logs: list,
    today: datetime.date,
    habit_id: str,
    current_window: int = 7,
    prior_window: int = 7,
    nudge_idx: int = 0,
) -> dict:
    """Compute adherence, trend, and nudge for a single habit.

    Parameters
    ----------
    habit:
        ORM row or fake with schedule_type, name attributes.
    logs:
        All habit log entries for this habit (any date range).
    today:
        Reference date for windowing.
    habit_id:
        String ID to embed in the response.
    current_window:
        Number of days (including today) for the current adherence window.
    prior_window:
        Number of days immediately before the current window for trend comparison.
    nudge_idx:
        Deterministic index into the nudge message list (use habit sort position).

    Returns
    -------
    dict with keys: habit_id, habit_name, met_count, scheduled_count,
        adherence_percent, best_day, worst_day, trend, nudge, building.
    """
    # Current period: last `current_window` days (today inclusive)
    current_end = today
    current_start = today - datetime.timedelta(days=current_window - 1)

    # Prior period: `prior_window` days immediately before current_start
    prior_end = current_start - datetime.timedelta(days=1)
    prior_start = prior_end - datetime.timedelta(days=prior_window - 1)

    met_current = _count_period(logs, current_start, current_end)
    scheduled_count = current_window
    adherence_pct = met_current / scheduled_count * 100

    # Determine building state
    total_logged = len(set(log.log_date for log in logs))
    building = total_logged < MIN_HISTORY_DAYS

    # Trend: compare current vs prior adherence
    met_prior = _count_period(logs, prior_start, prior_end)
    prior_pct = met_prior / prior_window * 100 if prior_window else 0

    if building:
        trend = "stable"
    elif prior_pct > adherence_pct + 15:
        trend = "declining"
    else:
        trend = "stable"

    best_day, worst_day = _best_worst_day(logs)

    nudge_trend = "building" if building else trend
    nudge = _nudge_for(nudge_trend, adherence_pct, habit_name=getattr(habit, "name", ""), idx=nudge_idx)

    return {
        "habit_id": habit_id,
        "habit_name": getattr(habit, "name", ""),
        "met_count": met_current,
        "scheduled_count": scheduled_count,
        "adherence_percent": round(adherence_pct, 1),
        "best_day": best_day,
        "worst_day": worst_day,
        "trend": trend,
        "nudge": nudge,
        "building": building,
    }


def build_adherence_payload(
    habits: list,
    logs_by_habit: dict[str, list],
    today: datetime.date,
) -> dict:
    """Build the full adherence payload for the API endpoint.

    Parameters
    ----------
    habits:
        List of active habit ORM rows (or fakes) with .id and .name.
    logs_by_habit:
        Mapping of str(habit_id) → list of log rows for that habit.
    today:
        Reference date.

    Returns
    -------
    dict with keys: building (bool), reason (str|None), habits (list).
    """
    if not habits:
        return {
            "building": True,
            "reason": "no_habits",
            "habits": [],
        }

    results = []
    for idx, habit in enumerate(habits):
        hid = str(habit.id) if hasattr(habit, "id") else str(getattr(habit, "habit_id", ""))
        logs = logs_by_habit.get(hid, [])
        entry = compute_habit_adherence(
            habit=habit,
            logs=logs,
            today=today,
            habit_id=hid,
            nudge_idx=idx,
        )
        results.append(entry)

    all_building = all(r["building"] for r in results)
    any_building = any(r["building"] for r in results)

    if all_building:
        reason = "insufficient_history"
    elif any_building:
        reason = "some_habits_building"
    else:
        reason = None

    return {
        "building": all_building,
        "reason": reason,
        "habits": results,
    }
