"""Issue #1711: dead backend functions must be removed.

AC1 — apply_swap is not exported from backend.services.session_swap.
AC2 — apply_add is not exported from backend.services.session_swap.
AC3 — merge_pinned_and_filled is not exported from backend.services.session_pins.
AC4 — rank_swap_candidates and all other live helpers remain importable.
"""
from __future__ import annotations

import importlib


def test_apply_swap_removed():
    mod = importlib.import_module("backend.services.session_swap")
    assert not hasattr(mod, "apply_swap"), (
        "apply_swap is dead code (only referenced in tests, "
        "actual mutation is done client-side in _smApplyCandidate) — it must be deleted"
    )


def test_apply_add_removed():
    mod = importlib.import_module("backend.services.session_swap")
    assert not hasattr(mod, "apply_add"), (
        "apply_add is dead code (only referenced in tests, "
        "actual mutation is done client-side in _smApplyCandidate) — it must be deleted"
    )


def test_merge_pinned_and_filled_removed():
    mod = importlib.import_module("backend.services.session_pins")
    assert not hasattr(mod, "merge_pinned_and_filled"), (
        "merge_pinned_and_filled is dead code (never called in production or tests) — it must be deleted"
    )


def test_rank_swap_candidates_still_exists():
    """Live function used by the swap picker endpoint must remain."""
    from backend.services.session_swap import rank_swap_candidates  # noqa: F401
    assert callable(rank_swap_candidates)


def test_session_pins_live_helpers_still_exist():
    """Live helpers used throughout the codebase must remain."""
    from backend.services.session_pins import (  # noqa: F401
        exercise_is_pinned,
        split_pinned_exercises,
        sum_spend,
        exercise_spend,
        structure_actual_spend,
        refill_contract,
        block_key,
        stamp_generated,
    )
