"""Habit-outcome correlation insight builder.

Pure function — no DB access. Caller supplies all data.

Tone rules for insight copy are delegated to
:mod:`backend.services.coaching_voice` so phrase changes propagate here
automatically.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import statistics
from typing import Any

from backend.services.habit_outcome_alignment import align_habit_and_outcome
from backend.services.habit_correlation import compute_correlation
import backend.services.coaching_voice as coaching_voice

# ---------------------------------------------------------------------------
# Configuration helpers — threshold must never be a hardcoded literal
# ---------------------------------------------------------------------------

def _read_min_sample_size() -> int:
    """Return minimum overlapping-day threshold from env; default 7."""
    raw = os.environ.get("HABIT_INSIGHTS_MIN_SAMPLE_SIZE", "7")
    try:
        return max(2, int(raw))
    except (ValueError, TypeError):
        return 7


# Internal confidence threshold (minimum |r| to surface an insight)
_MIN_ABS_R: float = 0.1

# Lag values (in days) to try for each habit-outcome pair
_LAG_OPTIONS: tuple[int, ...] = (0, 1, 2)

# Outcome fields sourced from DailyMetric that this builder knows about
OUTCOME_FIELDS: tuple[str, ...] = ("energy", "mood", "sleep_quality", "hrv")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _outcome_label(outcome_name: str) -> str:
    return outcome_name.replace("_", " ").title()


def _generate_line(
    habit_name: str,
    outcome_name: str,
    coefficient: float,
    lag_days: int,
) -> str:
    """Return a plain-English sentence describing the insight.

    Delegates to coaching_voice.reframe_line_builder so that tone changes
    propagate from the shared voice module without edits here.
    """
    direction = "up" if coefficient >= 0 else "down"
    label = _outcome_label(outcome_name)
    if lag_days == 0:
        context = f"associated with higher '{label}' scores on the same day"
    else:
        day_word = "day" if lag_days == 1 else "days"
        context = f"associated with higher '{label}' scores {lag_days} {day_word} later"
    if coefficient < 0:
        context = context.replace("higher", "lower")
    return coaching_voice.praise_line_builder(
        f"'{habit_name}' habit",
        None,
        direction,
        context,
    )


def _pearson(x_seq: list[float], y_seq: list[float]) -> float:
    """Return Pearson r using stdlib statistics.correlation (Python 3.10+)."""
    return statistics.correlation(x_seq, y_seq)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_insights(
    habits: list[Any],
    habit_logs_by_habit: dict[str, dict[str, float]],
    outcome_series_by_name: dict[str, dict[str, float]],
    min_sample_size: int | None = None,
) -> tuple[list[dict[str, Any]], bool, str | None]:
    """Compute habit-outcome correlations and return the insight triple.

    All DB access is the caller's responsibility; this function is pure.

    Parameters
    ----------
    habits:
        Sequence of habit objects with ``.id`` (UUID) and ``.name`` (str).
    habit_logs_by_habit:
        Mapping of str(habit_id) -> {date_str: numeric value}.
        Boolean completion logs should be converted to 1.0/0.0 by the caller.
    outcome_series_by_name:
        Mapping of outcome_name -> {date_str: float}.
    min_sample_size:
        Override for the configured threshold. Reads the
        ``HABIT_INSIGHTS_MIN_SAMPLE_SIZE`` env var when ``None``.

    Returns
    -------
    (insights, building, reason)
        insights: list of insight dicts (empty when building=True).
        building: True when data is insufficient.
        reason: human-readable explanation when building=True; None otherwise.
    """
    if min_sample_size is None:
        min_sample_size = _read_min_sample_size()

    # Determine global overlap: days where ANY habit log AND ANY outcome exist
    all_habit_dates: set[str] = set()
    for logs in habit_logs_by_habit.values():
        if logs:
            all_habit_dates.update(logs.keys())

    all_outcome_dates: set[str] = set()
    for series in outcome_series_by_name.values():
        if series:
            all_outcome_dates.update(series.keys())

    overlap_count = len(all_habit_dates & all_outcome_dates)

    if overlap_count < min_sample_size:
        if not all_habit_dates:
            reason: str = "Not enough habit logs yet."
        elif not all_outcome_dates:
            reason = "Not enough outcome data yet."
        else:
            reason = (
                f"Not enough overlapping days yet "
                f"({overlap_count} of {min_sample_size} required)."
            )
        return [], True, reason

    # Compute the best (highest |r|) correlation per (habit, outcome) pair
    insights: list[dict[str, Any]] = []

    for habit in habits:
        habit_id_str = str(habit.id)
        logs = habit_logs_by_habit.get(habit_id_str) or {}
        if not logs:
            continue

        for outcome_name, outcome_series in outcome_series_by_name.items():
            if not outcome_series:
                continue

            best: dict[str, Any] | None = None

            for lag in _LAG_OPTIONS:
                pairs, _ = align_habit_and_outcome(logs, outcome_series, lag)
                n = len(pairs)
                if n < min_sample_size:
                    continue

                x = [float(p["habit_value"]) for p in pairs]
                y = [float(p["outcome_value"]) for p in pairs]

                # Pearson requires variance in both series
                if len(set(x)) < 2 or len(set(y)) < 2:
                    continue

                try:
                    r = _pearson(x, y)
                except statistics.StatisticsError:
                    continue

                # Clamp to [-1, 1] for guaranteed serialisation safety
                r = max(-1.0, min(1.0, r))

                if abs(r) < _MIN_ABS_R:
                    continue

                if best is None or abs(r) > abs(best["coefficient"]):
                    best = {
                        "habit_id": habit_id_str,
                        "habit_name": habit.name,
                        "outcome_name": outcome_name,
                        "coefficient": round(r, 4),
                        "sample_size": n,
                        "lag_days": lag,
                        "line": _generate_line(
                            habit.name, outcome_name, r, lag
                        ),
                    }

            if best is not None:
                insights.append(best)

    return insights, False, None


# ── #883 plain-language insight builder (kept alongside #885 build_insights) ──
def _lag_description(lag_days):
    """Return a human-readable lag label for use inside an insight string."""
    if lag_days == 0:
        return "same-day"
    if lag_days == 1:
        return "next-day"
    return f"{lag_days}-day-later"


def build_habit_outcome_insights(
    habits,
    outcome_series,
    lags=None,
    min_n=10,
    min_r=0.1,
):
    """Build plain-language association strings for every (habit, outcome, lag) triple
    that clears the supplied confidence bar.

    The function is deliberately stateless and data-source agnostic.  All DB
    access is delegated entirely to the caller — no queries, file I/O, or network
    calls occur here.

    Args:
        habits: A list of dicts, each with:
            - ``name`` (str): human-readable habit name.
            - ``logs`` (dict[str, bool]): mapping of ``YYYY-MM-DD`` date strings
              to boolean completion values for that day.
            Pass ``None`` or an empty list when no habits are available.
        outcome_series: A dict mapping outcome name strings to their date-keyed
            numeric series.  Each value is a dict mapping ``YYYY-MM-DD`` date
            strings to float measurements.  Supported by the existing callers:
            ``readiness_tsb``, ``daily_load``, ``weight_trend``.  Adding a new
            outcome requires only adding it to this dict — no changes to this
            function.
            Pass ``None`` or ``{}`` when no outcomes are available.
        lags: A list of non-negative integers specifying which lag offsets to
            test.  Defaults to ``[0, 1]`` (same-day and next-day).
        min_n: Minimum number of aligned pairs required for a triple to survive.
            Triples whose sample size is strictly less than ``min_n`` are
            suppressed.  Defaults to ``10``.
        min_r: Minimum absolute correlation coefficient required for a triple to
            survive.  Triples whose ``|r|`` is strictly less than ``min_r`` are
            suppressed.  Defaults to ``0.1``.

    Returns:
        A two-element tuple ``(insights, reason)``.

        ``insights`` is a list of plain-language strings, one per surviving
        triple.  Each string names the habit, the outcome, the direction of
        association (``higher`` or ``lower``), the lag (e.g. ``same-day`` or
        ``next-day``), the correlation coefficient (``r = X.XX``), and the
        sample size (``n = NN``).  All phrasing is associative — causal language
        such as *causes*, *leads to*, *results in*, or *drives* does not appear.

        ``reason`` is an empty string when at least one insight is returned.
        It is a non-empty human-readable string when the list is empty,
        explaining which condition was triggered (no habits, no outcomes, or no
        triples met the confidence bar).

    Worked example::

        habits = [
            {
                "name": "Sleep ≥ 7h",
                "logs": {
                    "2025-01-01": True,
                    "2025-01-02": False,
                    "2025-01-03": True,
                    # ... 27 more days, alternating True/False
                },
            }
        ]
        outcome_series = {
            "readiness_tsb": {
                "2025-01-01": 80.0,
                "2025-01-02": 40.0,
                "2025-01-03": 80.0,
                # ... 27 more days matching the habit pattern
            }
        }

        insights, reason = build_habit_outcome_insights(
            habits,
            outcome_series,
            lags=[0],
            min_n=5,
            min_r=0.1,
        )

        # Intermediate: align_habit_and_outcome produces 30 pairs at lag=0.
        # compute_correlation returns r ≈ 1.0 and n = 30, both above thresholds.
        #
        # Expected output (one insight):
        # insights == [
        #     "days you hit your Sleep ≥ 7h habit, same-day readiness tsb "
        #     "tends to be higher (r = 1.00, n = 30)"
        # ]
        # reason == ""
    """
    if lags is None:
        lags = [0, 1]

    if not habits:
        return [], "no habits provided; habit list is missing or empty"

    if not outcome_series:
        return [], "no outcome series provided; outcome dict is missing or empty"

    insights = []

    for habit in habits:
        habit_name = habit["name"]
        habit_logs = habit.get("logs") or {}

        for outcome_name, series in outcome_series.items():
            for lag in lags:
                pairs, _debug = align_habit_and_outcome(habit_logs, series, lag)
                corr = compute_correlation(pairs)

                if corr["n"] < min_n:
                    continue
                if abs(corr["r"]) < min_r:
                    continue
                if corr["reason"]:
                    continue

                lag_desc = _lag_description(lag)
                direction = "higher" if corr["r"] > 0 else "lower"
                readable_outcome = outcome_name.replace("_", " ")

                insight = (
                    f"days you hit your {habit_name} habit, "
                    f"{lag_desc} {readable_outcome} tends to be {direction} "
                    f"(r = {corr['r']:.2f}, n = {corr['n']})"
                )
                insights.append(insight)

    if not insights:
        return [], "no habit-outcome pairs met the confidence minimum (min_n or min_r)"

    return insights, ""


# ── LLM coaching overlay (issue #1312) ────────────────────────────────────────

_MAX_INSIGHT_LINE_LEN = 250
_MEDICAL_TERMS = ("doctor", "injury", "medical", "diagnos", "treat", "pain", "consult")

_INSIGHTS_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {"type": "string"},
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}


def _insights_facts_text(insights: list[dict]) -> str:
    facts = [{k: v for k, v in ins.items() if k != "line"} for ins in insights]
    return json.dumps(facts, sort_keys=True)


def _insights_signature(insights: list[dict]) -> str:
    return hashlib.sha256(_insights_facts_text(insights).encode()).hexdigest()


def _validate_insight_lines(lines: list[str], facts_text: str, expected_count: int) -> bool:
    if len(lines) != expected_count:
        return False
    for line in lines:
        if len(line) > _MAX_INSIGHT_LINE_LEN:
            return False
        for num in re.findall(r"\d+(?:\.\d+)?", line):
            if num not in facts_text:
                return False
        if any(term in line.lower() for term in _MEDICAL_TERMS):
            return False
    return True


def apply_llm_insights(
    insights: list[dict],
    user_id: str,
    db=None,
) -> list[dict]:
    """Replace insight 'line' values with LLM prose when LLM is enabled.

    Falls back to the original coaching_voice lines on any failure.
    Pure-function callers (build_insights) are not modified.
    """
    if not insights:
        return insights

    import backend.services.llm as _llm  # lazy to avoid circular at module load

    if not _llm.llm_enabled():
        return insights

    facts_text = _insights_facts_text(insights)
    sig = _insights_signature(insights)

    system = (
        "You are a performance coach writing concise, factual habit insights. "
        "Rules: one line per insight, max 250 characters, no medical or injury advice, "
        "use only numbers given in the facts (no invented figures), "
        "no exclamation marks, no emoji, associative language only (not causal)."
    )
    facts_lines = [
        f"{i+1}. Habit '{ins['habit_name']}' vs '{ins['outcome_name']}': "
        f"r={ins['coefficient']}, n={ins['sample_size']}, lag={ins['lag_days']}d"
        for i, ins in enumerate(insights)
    ]
    user = (
        "Write one coaching insight line per numbered entry below. "
        "Return JSON: {\"lines\": [...]}.\n" + "\n".join(facts_lines)
    )

    def _generate():
        return _llm.complete_structured(
            system=system,
            user=user,
            schema_name="habit_insights_lines",
            json_schema=_INSIGHTS_JSON_SCHEMA,
            model_tier="fast",
        )

    result = _llm.get_or_generate(
        user_id=user_id,
        surface="habit_insights",
        signature=sig,
        generate_fn=_generate,
        db=db,
    )

    if result is None:
        return insights

    lines = result.get("lines", [])
    if not _validate_insight_lines(lines, facts_text, len(insights)):
        return insights

    return [{**ins, "line": lines[i]} for i, ins in enumerate(insights)]
