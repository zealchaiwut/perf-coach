"""Tests for issue #1187: Reconcile polarized-split default high band bound.

Decision: the authoritative high-band lower bound is 15 (range [15, 20]).
This matches both the original AC from ticket #1131 and the module docstring.
The UAT step that used high=13 as on-target was incorrect and is corrected here.

Acceptance Criteria anchored:
  AC1 - A single authoritative high-band bound is documented.
  AC2 - The default range literal in polarized_split.py matches the chosen bound.
  AC3 - The module docstring matches the chosen bound exactly.
  AC4 - All pytest tests use example inputs consistent with the chosen bound.
  AC5 - on_target=True at the lower bound; on_target=False one unit below it.
"""
import pathlib
import re

import pytest

from backend.services.polarized_split import check_polarized_split, _DEFAULT_BOUNDS


CHOSEN_LOW = 15   # authoritative lower bound for the high band
CHOSEN_HIGH = 20  # authoritative upper bound for the high band


# ---------------------------------------------------------------------------
# AC2 — default range literal
# ---------------------------------------------------------------------------

def test_default_high_bound_lower():
    """AC2: _DEFAULT_BOUNDS['high'][0] must equal the chosen lower bound (15)."""
    assert _DEFAULT_BOUNDS["high"][0] == CHOSEN_LOW, (
        f"Expected default high lower bound to be {CHOSEN_LOW}, "
        f"got {_DEFAULT_BOUNDS['high'][0]}"
    )


def test_default_high_bound_upper():
    """AC2: _DEFAULT_BOUNDS['high'][1] must equal the chosen upper bound (20)."""
    assert _DEFAULT_BOUNDS["high"][1] == CHOSEN_HIGH, (
        f"Expected default high upper bound to be {CHOSEN_HIGH}, "
        f"got {_DEFAULT_BOUNDS['high'][1]}"
    )


# ---------------------------------------------------------------------------
# AC3 — docstring matches code
# ---------------------------------------------------------------------------

def test_docstring_matches_code():
    """AC3: The module docstring high-band entry must show [15, 20] to match the code."""
    src_path = (
        pathlib.Path(__file__).parents[1]
        / "backend"
        / "services"
        / "polarized_split.py"
    )
    source = src_path.read_text()
    # Docstring must show 'high     [15, 20]' (possibly with varying whitespace)
    match = re.search(r"high\s+\[(\d+),\s*(\d+)\]", source)
    assert match is not None, "Could not find 'high [lo, hi]' in module docstring"
    doc_lo = int(match.group(1))
    doc_hi = int(match.group(2))
    assert doc_lo == _DEFAULT_BOUNDS["high"][0], (
        f"Docstring high lower bound ({doc_lo}) must match code ({_DEFAULT_BOUNDS['high'][0]})"
    )
    assert doc_hi == _DEFAULT_BOUNDS["high"][1], (
        f"Docstring high upper bound ({doc_hi}) must match code ({_DEFAULT_BOUNDS['high'][1]})"
    )


# ---------------------------------------------------------------------------
# AC5 — on_target at lower bound, off_target one unit below
# ---------------------------------------------------------------------------

def test_high_at_chosen_lower_bound_is_on_target():
    """AC5: high=15 (the chosen lower bound) must be on_target=True for the high band."""
    result = check_polarized_split(low=80, moderate=5, high=CHOSEN_LOW)
    bands = {d["band"] for d in result["deviations"]}
    assert "high" not in bands, (
        f"high={CHOSEN_LOW} is the lower bound and must not deviate"
    )


def test_high_one_below_lower_bound_is_off_target():
    """AC5: high=14 (one unit below chosen lower bound 15) must be on_target=False."""
    one_below = CHOSEN_LOW - 1
    result = check_polarized_split(low=80, moderate=5, high=one_below)
    bands = {d["band"]: d["direction"] for d in result["deviations"]}
    assert "high" in bands, (
        f"high={one_below} is below the lower bound {CHOSEN_LOW} and must deviate"
    )
    assert bands["high"] == "below"


def test_high_at_upper_bound_is_on_target():
    """AC5: high=20 (the upper bound) must not deviate."""
    result = check_polarized_split(low=75, moderate=5, high=CHOSEN_HIGH)
    bands = {d["band"] for d in result["deviations"]}
    assert "high" not in bands, (
        f"high={CHOSEN_HIGH} is the upper bound and must not deviate"
    )


def test_high_one_above_upper_bound_is_off_target():
    """AC5: high=21 (one above upper bound 20) must deviate above."""
    one_above = CHOSEN_HIGH + 1
    result = check_polarized_split(low=75, moderate=3, high=one_above)
    bands = {d["band"]: d["direction"] for d in result["deviations"]}
    assert "high" in bands
    assert bands["high"] == "above"


# ---------------------------------------------------------------------------
# AC4 — no test should pass high=13 as on-target given bound [15, 20]
# ---------------------------------------------------------------------------

def test_high_13_is_below_target():
    """AC4: With bound [15, 20], high=13 must deviate (not on-target)."""
    result = check_polarized_split(low=80, moderate=7, high=13)
    assert result["on_target"] is False
    bands = {d["band"]: d["direction"] for d in result["deviations"]}
    assert "high" in bands
    assert bands["high"] == "below"
