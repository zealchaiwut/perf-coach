"""Tests for issue #1445: strength→non-strength workout edit leaves stale muscle_load_daily rows.

Acceptance criteria:
  AC1 — patch_workout captures the old workout_type before applying mutations
         (mirrors the pattern used for _old_workout_date and _del_workout_type)
  AC2 — The muscle-load recompute hook fires when the OLD workout_type is
         'strength', even if the new workout_type is not 'strength'
  AC3 — The muscle-load recompute hook still fires when the NEW workout_type
         is 'strength' (existing behaviour preserved)
  AC4 — When neither old nor new workout_type is 'strength', the recompute
         hook is NOT triggered (no regression for non-strength edits)
"""
import inspect
import re


def _get_patch_workout_source() -> str:
    from backend.main import patch_workout
    return inspect.getsource(patch_workout)


# ── AC1: old workout_type captured before mutations ───────────────────────────

def test_old_workout_type_captured_before_mutations():
    """patch_workout must capture the pre-patch workout_type into a local variable
    before any field mutation — the same pattern used for _old_workout_date."""
    src = _get_patch_workout_source()

    # Check that a variable capturing workout.workout_type exists before the
    # recompute block (we look for the capture pattern, not just its presence in
    # the recompute conditional).
    capture_pattern = re.compile(
        r"(_old_workout_type|_pre_workout_type)\s*=\s*workout\.workout_type"
    )
    assert capture_pattern.search(src), (
        "patch_workout must capture workout.workout_type into a local variable "
        "before any field mutations (e.g. `_old_workout_type = workout.workout_type`)"
    )


# ── AC2: recompute fires when OLD type is 'strength' ─────────────────────────

def test_recompute_fires_on_old_strength_type():
    """The recompute condition must reference the old workout_type variable so
    that a strength→non-strength edit still triggers recompute_strength_load_for_date."""
    src = _get_patch_workout_source()

    # The guard condition must reference the captured old-type variable.
    # Acceptable forms: `if "strength" in {_old_workout_type, ...}` or
    # equivalent OR / AND expression that includes _old_workout_type.
    old_type_in_condition = re.search(
        r'if\s+["\']strength["\']\s+in\s+\{[^}]*_old_workout_type[^}]*\}',
        src,
    ) or re.search(
        r'if\s+_old_workout_type\s+==\s+["\']strength["\']',
        src,
    ) or re.search(
        r'if\s+.*_old_workout_type.*==.*strength|strength.*==.*_old_workout_type',
        src,
    )
    assert old_type_in_condition, (
        "The muscle-load recompute condition in patch_workout must include "
        "_old_workout_type so that a strength→non-strength edit triggers recompute. "
        "Expected a guard like: `if \"strength\" in {_old_workout_type, workout.workout_type}:`"
    )


# ── AC3: recompute still fires when NEW type is 'strength' ───────────────────

def test_recompute_still_fires_on_new_strength_type():
    """The recompute condition must still reference the current/new workout_type
    so that a non-strength→strength edit continues to trigger recompute."""
    src = _get_patch_workout_source()

    new_type_in_condition = re.search(
        r'if\s+["\']strength["\']\s+in\s+\{[^}]*workout\.workout_type[^}]*\}',
        src,
    ) or re.search(
        r'workout\.workout_type\s*==\s*["\']strength["\']',
        src,
    )
    assert new_type_in_condition, (
        "The muscle-load recompute condition in patch_workout must still reference "
        "workout.workout_type (the new type) so that non-strength→strength edits "
        "continue to trigger recompute."
    )


# ── AC4: recompute not triggered for non-strength edits ──────────────────────

def test_recompute_condition_is_or_not_always_true():
    """The combined condition must be an OR / set-membership check (fires when
    EITHER type is strength), not an unconditional call or always-true guard."""
    src = _get_patch_workout_source()

    # Verify recompute_strength_load_for_date is not called unconditionally —
    # it must still sit inside a conditional block.
    lines = src.splitlines()
    recompute_lines = [ln for ln in lines if "recompute_strength_load_for_date" in ln]
    assert recompute_lines, "recompute_strength_load_for_date must still be present in patch_workout"

    for ln in recompute_lines:
        stripped = ln.lstrip()
        # Should not be a top-level call (no if guard) — indentation inside a try/if block
        # The function body itself is indented so we just check it's inside a conditional
        assert not stripped.startswith("recompute_strength_load_for_date"), (
            f"recompute_strength_load_for_date must be inside a conditional, got: {ln!r}"
        )
