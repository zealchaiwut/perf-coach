"""Habit evidence — correlation sentences instead of streaks.

Why not streaks
---------------
A streak turns one missed day into a reason to stop. On a food habit that is
actively harmful: the athlete who breaks a 40-day protein streak on a Tuesday has
been handed a reason to quit on Wednesday. Spec D8 bans them — no daily verdicts,
no streaks anywhere near food — so this module is what the habit surface shows
instead.

What it shows
-------------
A sentence with the athlete's own numbers in it::

    "Weeks you fuelled the long run, HR drift averaged 3.1% vs 6.8%."

That is an argument, not a scold. It says nothing about yesterday and everything
about whether the habit is worth keeping — which is the only question a habit
surface should be answering.

Honesty rules
-------------
- **No sentence without enough pairs.** Below ``MIN_PAIRS`` the answer is "not
  enough data yet", said plainly.
- **No sentence when both groups aren't represented.** A comparison needs weeks
  with the habit and weeks without; all-yes or all-no compares nothing.
- **Direction is stated, causation is not.** The copy says what the numbers did,
  never that the habit caused it.
- **Lower-is-better metrics are handled explicitly**, so "3.1% vs 6.8%" reads as
  the win it is rather than being phrased as a decline.

Pure functions over aligned pairs. No DB, no LLM — this is a template string and
a mean.
"""
from __future__ import annotations

from typing import Iterable, Optional

# Below this many aligned observations, no claim is made at all.
MIN_PAIRS = 6
# Both groups need at least this many observations for the comparison to mean
# anything.
MIN_PER_GROUP = 2
# Relative gap below which the two groups are called "about the same" rather
# than being reported as a difference.
NEGLIGIBLE_RELATIVE_GAP = 0.05


class Metric:
    """An outcome the habit might move, with the copy needed to describe it."""

    def __init__(
        self,
        key: str,
        label: str,
        unit: str,
        *,
        lower_is_better: bool,
        decimals: int = 1,
    ) -> None:
        self.key = key
        self.label = label
        self.unit = unit
        self.lower_is_better = lower_is_better
        self.decimals = decimals

    def format(self, value: float) -> str:
        return f"{value:.{self.decimals}f}{self.unit}"


# The outcomes worth correlating a habit against. Each is something the app
# already computes, so no new measurement is implied by adding one.
METRICS = {
    "hr_drift": Metric("hr_drift", "HR drift", "%", lower_is_better=True),
    "rpe": Metric("rpe", "session RPE", "", lower_is_better=True),
    "readiness": Metric("readiness", "readiness", "", lower_is_better=False, decimals=0),
    "sleep_hours": Metric("sleep_hours", "sleep", " h", lower_is_better=False),
    "resting_hr": Metric("resting_hr", "resting HR", " bpm", lower_is_better=True, decimals=0),
    "tss": Metric("tss", "weekly TSS", "", lower_is_better=False, decimals=0),
}


def _mean(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def compare_groups(pairs: Iterable[dict], metric_key: str) -> dict:
    """Split aligned pairs by habit completion and compare the outcome means.

    Parameters
    ----------
    pairs:
        Dicts with ``habit_value`` (bool) and ``outcome_value`` (numeric) — the
        output shape of ``habit_outcome_alignment.align_habit_and_outcome``.
    metric_key:
        A key of ``METRICS``; unknown keys yield an unreadable result rather
        than a guess at how to phrase the number.

    Returns
    -------
    dict with ``readable``, ``reason``, ``with_mean``, ``without_mean``,
    ``n_with``, ``n_without``, ``better``, ``sentence``.
    """
    metric = METRICS.get(metric_key)
    base = {
        "metric": metric_key,
        "readable": False,
        "reason": None,
        "with_mean": None,
        "without_mean": None,
        "n_with": 0,
        "n_without": 0,
        "better": None,
        "sentence": None,
    }
    if metric is None:
        base["reason"] = f"unknown metric {metric_key!r}"
        return base

    rows = [
        p for p in (pairs or [])
        if p.get("outcome_value") is not None and p.get("habit_value") is not None
    ]
    with_values = [float(p["outcome_value"]) for p in rows if p["habit_value"]]
    without_values = [float(p["outcome_value"]) for p in rows if not p["habit_value"]]
    base["n_with"] = len(with_values)
    base["n_without"] = len(without_values)

    if len(rows) < MIN_PAIRS:
        base["reason"] = (
            f"only {len(rows)} weeks of data — {MIN_PAIRS} are needed before "
            "the comparison says anything"
        )
        return base
    if len(with_values) < MIN_PER_GROUP or len(without_values) < MIN_PER_GROUP:
        base["reason"] = (
            "need weeks both with and without the habit to compare — "
            f"{len(with_values)} with, {len(without_values)} without"
        )
        return base

    with_mean = _mean(with_values)
    without_mean = _mean(without_values)
    base["with_mean"] = round(with_mean, 2)
    base["without_mean"] = round(without_mean, 2)
    base["readable"] = True

    scale = max(abs(with_mean), abs(without_mean)) or 1.0
    if abs(with_mean - without_mean) / scale < NEGLIGIBLE_RELATIVE_GAP:
        base["better"] = "same"
        base["sentence"] = (
            f"{metric.label} was about the same either way "
            f"({metric.format(with_mean)} vs {metric.format(without_mean)}) — "
            "no difference worth acting on yet."
        )
        return base

    with_is_better = (
        with_mean < without_mean if metric.lower_is_better else with_mean > without_mean
    )
    base["better"] = "with" if with_is_better else "without"
    return base


def render_sentence(comparison: dict, habit_phrase: str) -> Optional[str]:
    """Turn a comparison into one sentence naming the habit and both numbers.

    ``habit_phrase`` is the "weeks you ___" clause, e.g. "fuelled the long run".
    Returns None when the comparison isn't readable — silence is correct when
    there is nothing to say.
    """
    if not comparison.get("readable"):
        return None
    if comparison.get("sentence"):
        return comparison["sentence"]

    metric = METRICS.get(comparison["metric"])
    if metric is None:
        return None

    with_txt = metric.format(comparison["with_mean"])
    without_txt = metric.format(comparison["without_mean"])
    return (
        f"Weeks you {habit_phrase}, {metric.label} averaged "
        f"{with_txt} vs {without_txt}."
    )


def build_evidence(pairs: Iterable[dict], metric_key: str, habit_phrase: str) -> dict:
    """Comparison plus its sentence — what a habit surface should render."""
    comparison = compare_groups(pairs, metric_key)
    comparison["sentence"] = render_sentence(comparison, habit_phrase)
    return comparison


# ── DB-backed pair building ──────────────────────────────────────────────────
# Weekly, not daily: the claim is "weeks you fuelled the long run", and a long
# run happens once a week. Daily alignment would compare a Tuesday habit tick to
# a Tuesday with no long run in it.

EVIDENCE_WEEKS = 16


def _week_start(d):
    from datetime import timedelta

    return d - timedelta(days=d.weekday())


def long_run_fuel_pairs(db, user_id, today, weeks: int = EVIDENCE_WEEKS) -> list[dict]:
    """One pair per week: did the long run get fuelled, and what was its HR drift?

    Weeks with no long run are dropped — there was nothing to fuel, so the week
    is evidence of neither outcome.
    """
    from datetime import timedelta

    from backend.models import Habit, HabitLog, Workout
    from backend.services.goal_habits import (
        LONG_RUN_FUEL_SOURCE,
        LONG_RUN_MIN_MINUTES,
    )

    start = _week_start(today) - timedelta(weeks=weeks - 1)

    habit = (
        db.query(Habit)
        .filter(
            Habit.user_id == user_id,
            Habit.auto_fill_source == LONG_RUN_FUEL_SOURCE,
            Habit.is_archived.is_(False),
        )
        .first()
    )
    if habit is None:
        return []

    fuelled_weeks = {
        _week_start(row[0])
        for row in db.query(HabitLog.log_date)
        .filter(
            HabitLog.habit_id == habit.id,
            HabitLog.log_date >= start,
            HabitLog.log_date <= today,
        )
        .all()
    }

    drift_by_week: dict = {}
    rows = (
        db.query(Workout.workout_date, Workout.decoupling_percent)
        .filter(
            Workout.user_id == user_id,
            Workout.workout_date >= start,
            Workout.workout_date <= today,
            Workout.decoupling_percent.isnot(None),
            Workout.duration_seconds >= LONG_RUN_MIN_MINUTES * 60,
        )
        .all()
    )
    for day, drift in rows:
        drift_by_week.setdefault(_week_start(day), []).append(float(drift))

    pairs: list[dict] = []
    for week, drifts in sorted(drift_by_week.items()):
        pairs.append({
            "habit_date": week.isoformat(),
            "habit_value": week in fuelled_weeks,
            "outcome_date": week.isoformat(),
            "outcome_value": sum(drifts) / len(drifts),
        })
    return pairs


def build_user_evidence(db, user_id, today, weeks: int = EVIDENCE_WEEKS) -> list[dict]:
    """Every readable evidence sentence for a user's goal habits.

    Only readable comparisons are returned — an unreadable one has nothing to
    say, and saying "not enough data yet" three times is worse than silence.
    """
    out: list[dict] = []
    try:
        pairs = long_run_fuel_pairs(db, user_id, today, weeks)
    except Exception:  # pragma: no cover — evidence is decoration, never fatal
        return out

    evidence = build_evidence(pairs, "hr_drift", "fuelled the long run")
    if evidence.get("readable") and evidence.get("sentence"):
        out.append({
            "habit": "long_run_fuel",
            "metric": "hr_drift",
            "sentence": evidence["sentence"],
            "with_mean": evidence["with_mean"],
            "without_mean": evidence["without_mean"],
            "n_with": evidence["n_with"],
            "n_without": evidence["n_without"],
            "better": evidence["better"],
        })
    return out
