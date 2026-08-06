"""Issue #1699: fill_strength generated rows must not be stamped state='done' at
creation, so that structure_actual_spend / estimate_planned_session_metrics do
not report a non-zero actual_tss before the athlete has done anything.
"""
from __future__ import annotations

import random

from backend.services.plan_pattern_fill import fill_strength
from backend.services.plan_pattern_seeds import default_exercises, default_strength_patterns
from backend.services.session_pins import structure_actual_spend, sum_spend
from backend.services.training_load import estimate_planned_session_metrics


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strength_content(seed: int = 42, subtype: str = "strength_lower") -> dict:
    pat = next(p for p in default_strength_patterns() if p["subtype"] == subtype)
    pool = default_exercises()
    return fill_strength(
        pat,
        {"duration_minutes": 50, "target_tss": 40, "subtype": subtype},
        pool,
        rng=random.Random(seed),
    )


# ---------------------------------------------------------------------------
# AC1: all generated rows have state="pending", not "done"
# ---------------------------------------------------------------------------

def test_fill_strength_generated_rows_are_pending():
    """fill_strength must stamp generated rows state='pending', never 'done'."""
    content = _strength_content()
    exercises = content["exercises"]
    assert exercises, "fill_strength must produce at least one exercise"
    done_rows = [e["name"] for e in exercises if e.get("state") == "done"]
    assert not done_rows, (
        f"Generated rows must not have state='done' at creation; offenders: {done_rows}"
    )
    pending_rows = [e["name"] for e in exercises if e.get("state") == "pending"]
    assert len(pending_rows) == len(exercises), (
        f"Expected all {len(exercises)} rows to be 'pending', got {len(pending_rows)}"
    )


def test_fill_strength_plyo_generated_rows_are_pending():
    """Plyo slot generated rows must also be 'pending'."""
    try:
        content = _strength_content(seed=7, subtype="plyo")
    except StopIteration:
        return  # no plyo pattern in seeds — skip gracefully
    exercises = content["exercises"]
    if not exercises:
        return
    done_rows = [e["name"] for e in exercises if e.get("state") == "done"]
    assert not done_rows, f"Plyo generated rows must not have state='done': {done_rows}"


# ---------------------------------------------------------------------------
# AC2: structure_actual_spend returns None for an all-pending structure
# ---------------------------------------------------------------------------

def test_structure_actual_spend_returns_none_for_all_pending():
    """Before the athlete logs anything, actual_spend must be None."""
    content = _strength_content()
    result = structure_actual_spend(content)
    assert result is None, (
        f"structure_actual_spend must return None for all-pending session; "
        f"got actual_tss={result.get('actual_tss') if result else 'N/A'}"
    )


def test_structure_actual_spend_returns_spend_after_done():
    """Once at least one row is marked done, actual_spend must be non-None."""
    content = _strength_content()
    import copy
    struct = copy.deepcopy(content)
    # Mark first row as done so the athlete has logged something
    struct["exercises"][0]["state"] = "done"
    result = structure_actual_spend(struct)
    assert result is not None, "structure_actual_spend should return data when at least one row is done"
    assert result["actual_tss"] is not None


# ---------------------------------------------------------------------------
# AC3: sum_spend with only_done=True skips pending rows
# ---------------------------------------------------------------------------

def test_sum_spend_only_done_skips_pending():
    """sum_spend(only_done=True) must not count pending rows."""
    exercises = [
        {"name": "A", "spend_tss": 10, "spend_min": 8, "state": "done"},
        {"name": "B", "spend_tss": 5, "spend_min": 4, "state": "pending"},
        {"name": "C", "spend_tss": 3, "spend_min": 3, "state": "skipped"},
    ]
    tss, mins = sum_spend(exercises, only_done=True)
    assert tss == 10.0, f"Expected tss=10 (only done row A), got {tss}"
    assert mins == 8.0, f"Expected mins=8 (only done row A), got {mins}"


def test_sum_spend_only_done_counts_missing_state_as_done():
    """Rows without a state (legacy DB rows) still count as done for backward compat."""
    exercises = [
        {"name": "A", "spend_tss": 10, "spend_min": 8},  # no state — legacy row, treat as done
        {"name": "B", "spend_tss": 5, "spend_min": 4, "state": "pending"},
    ]
    tss, mins = sum_spend(exercises, only_done=True)
    assert tss == 10.0, f"Legacy row (no state) must be counted as done; tss={tss}"


# ---------------------------------------------------------------------------
# AC4: estimate_planned_session_metrics falls back to baseline for all-pending
# ---------------------------------------------------------------------------

def test_estimate_planned_session_metrics_uses_baseline_not_actual_tss():
    """For a freshly generated (all-pending) strength session, the estimator must
    fall back to the historical baseline, not return 0 or actual spend.
    """
    content = _strength_content()
    baseline = {"strength_tss_per_min": 1.0}  # simple: 1 TSS/min
    result = estimate_planned_session_metrics(baseline, "strength", content)
    # Should use 50 min × 1.0 TSS/min = 50, not 0 from actual spend
    assert result["estimated_tss"] is not None, "Baseline estimate must not be None"
    assert result["estimated_tss"] > 0, (
        f"Baseline estimate must be > 0, got {result['estimated_tss']}"
    )


def test_estimate_planned_session_metrics_uses_actual_after_logging():
    """After the athlete marks rows done, the actual TSS should take precedence."""
    import copy
    content = _strength_content()
    struct = copy.deepcopy(content)
    # Athlete completes first exercise
    struct["exercises"][0]["state"] = "done"
    struct["exercises"][0]["spend_tss"] = 20.0
    # Mark rest skipped so the actual result is predictable
    for ex in struct["exercises"][1:]:
        ex["state"] = "skipped"

    baseline = {"strength_tss_per_min": 1.0}
    result = estimate_planned_session_metrics(baseline, "strength", struct)
    assert result["estimated_tss"] == 20, (
        f"After logging, actual_tss (20) should be used; got {result['estimated_tss']}"
    )
