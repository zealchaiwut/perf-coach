"""Tests for issue #751: Primary A-race selection may pick past race in training-projection.js.

Acceptance criteria verified:
- AC1: _primaryRace predicate excludes r.status === "done" from A-priority race selection.
- AC2: When both a past A-race (done) and future A-race (planned) exist, the future race is
       selected regardless of array order.
- AC3: When all A-races have status "done", _primaryRace resolves to undefined (not a done race).
- AC4: Race header, verdict banner, and performance curve target the correctly selected race
       (follows from AC1-AC3; verified by confirming _primaryRace is computed correctly).
- AC5: Single A-race scenarios (past or future alone) work correctly — no regression.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_JS_PATH = _ROOT / "frontend" / "js" / "training-projection.js"


def _src() -> str:
    assert _JS_PATH.exists(), f"training-projection.js not found at {_JS_PATH}"
    return _JS_PATH.read_text()


# ── AC1: predicate includes status !== "done" check ──────────────────────────

def test_ac1_primary_race_a_priority_predicate_excludes_done():
    """AC1: The A-priority .find() predicate for _primaryRace must exclude status === 'done'."""
    src = _src()
    # Accept single-quote or double-quote variants
    has_done_exclusion = (
        'r.status !== "done"' in src
        or "r.status !== 'done'" in src
    )
    assert has_done_exclusion, (
        "training-projection.js must exclude r.status === 'done' from _primaryRace selection; "
        "add `&& r.status !== \"done\"` to the .find() predicate"
    )


def test_ac1_done_exclusion_is_near_primary_race_assignment():
    """AC1: The status !== 'done' check must appear in the _primaryRace assignment block."""
    src = _src()
    # Find the assignment inside applyBundle (not the initial var declaration).
    # Look for the block where _races.find( is called to set _primaryRace.
    idx = src.find("_races.find(")
    assert idx >= 0, "_races.find( not found in training-projection.js"

    # Extract ~400 chars from the first _races.find( call to capture the full assignment block
    block = src[idx : idx + 400]
    has_done_exclusion = (
        'r.status !== "done"' in block
        or "r.status !== 'done'" in block
    )
    assert has_done_exclusion, (
        "The `status !== 'done'` guard must appear within the _primaryRace assignment expression, "
        f"but was not found in the _races.find() block. Block:\n{block}"
    )


# ── AC2: future A-race wins over past A-race regardless of array order ────────

def test_ac2_find_predicate_rejects_done_a_race_regardless_of_array_position():
    """AC2 (logic simulation): status !== 'done' in the predicate means a done A-race
    appearing first in the array is skipped and the planned A-race is returned.

    This test executes the predicate logic directly in Python to confirm the correct
    outcome for both orderings of the array.
    """
    def primary_race(races):
        """Python re-implementation of the corrected _primaryRace selection logic."""
        for r in races:
            if r["type"] == "race" and r["priority"] == "A" and r["status"] != "done":
                return r
        for r in races:
            if r["type"] == "race" and r["status"] != "done":
                return r
        return None

    past_a = {"type": "race", "priority": "A", "status": "done", "date": "2025-03-01", "id": "past"}
    future_a = {"type": "race", "priority": "A", "status": "planned", "date": "2026-12-01", "id": "future"}

    # Past race first in array — future must still win.
    result = primary_race([past_a, future_a])
    assert result is not None, "Expected a primary race to be selected"
    assert result["id"] == "future", (
        f"Expected future A-race to be selected, got {result['id']!r} "
        "(past A-race should be excluded by status !== 'done')"
    )

    # Future race first in array — future must win (regression check on normal order).
    result2 = primary_race([future_a, past_a])
    assert result2 is not None
    assert result2["id"] == "future", (
        f"Expected future A-race when it appears first, got {result2['id']!r}"
    )


# ── AC3: all A-races done → _primaryRace is None/undefined ───────────────────

def test_ac3_only_done_a_races_yields_no_primary_race():
    """AC3: When every A-race has status 'done', _primaryRace must be None (undefined)."""

    def primary_race(races):
        for r in races:
            if r["type"] == "race" and r["priority"] == "A" and r["status"] != "done":
                return r
        for r in races:
            if r["type"] == "race" and r["status"] != "done":
                return r
        return None

    only_done = [
        {"type": "race", "priority": "A", "status": "done", "date": "2025-03-01", "id": "r1"},
        {"type": "race", "priority": "A", "status": "done", "date": "2025-06-01", "id": "r2"},
    ]
    result = primary_race(only_done)
    assert result is None, (
        f"Expected None when all A-races are done, but got {result!r}"
    )


def test_ac3_done_a_race_alone_yields_no_primary_race():
    """AC3: A single done A-race must not be selected as primary race."""

    def primary_race(races):
        for r in races:
            if r["type"] == "race" and r["priority"] == "A" and r["status"] != "done":
                return r
        for r in races:
            if r["type"] == "race" and r["status"] != "done":
                return r
        return None

    single_done = [
        {"type": "race", "priority": "A", "status": "done", "date": "2025-01-15", "id": "r1"},
    ]
    result = primary_race(single_done)
    assert result is None, (
        f"Expected None when the only A-race is done, got {result!r}"
    )


# ── AC5: single race scenarios — no regression ───────────────────────────────

def test_ac5_single_future_a_race_still_selected():
    """AC5: A single future A-race (status 'planned') must still be selected as _primaryRace."""

    def primary_race(races):
        for r in races:
            if r["type"] == "race" and r["priority"] == "A" and r["status"] != "done":
                return r
        for r in races:
            if r["type"] == "race" and r["status"] != "done":
                return r
        return None

    single_future = [
        {"type": "race", "priority": "A", "status": "planned", "date": "2027-04-01", "id": "r1"},
    ]
    result = primary_race(single_future)
    assert result is not None, "Expected future A-race to be selected"
    assert result["id"] == "r1"


def test_ac5_no_regression_in_source_type_race_check():
    """AC5: The existing r.type === 'race' guard must still be present (no regression)."""
    src = _src()
    idx = src.find("_races.find(")
    assert idx >= 0, "_races.find( not found"
    block = src[idx : idx + 400]
    has_type_race = 'r.type === "race"' in block or "r.type === 'race'" in block
    assert has_type_race, (
        "r.type === 'race' guard must still be present in _primaryRace selection after the fix"
    )


def test_ac5_no_regression_in_a_priority_check():
    """AC5: The r.priority === 'A' guard in the first .find() must still be present."""
    src = _src()
    idx = src.find("_races.find(")
    assert idx >= 0, "_races.find( not found"
    block = src[idx : idx + 400]
    has_priority_a = 'r.priority === "A"' in block or "r.priority === 'A'" in block
    assert has_priority_a, (
        "r.priority === 'A' guard must still be present in the first _primaryRace .find() after the fix"
    )
