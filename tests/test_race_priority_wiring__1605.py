"""The race's priority actually reaches the taper calculation — issue #1605.

``tests/test_taper_recommendation__711.py`` already covers the service: given a
``priority`` key, ``taper_recommendation`` picks the right constant. Those 37
tests passed on the day they were written and then stopped running entirely,
because the module they import from lost ``A_RACE_TAPER_DAYS`` in a merge
conflict resolution (``262f4e12``) and every collection since was an ImportError.

So the service was tested and the wiring was not, and the wiring is what broke.
This file tests the wiring: that ``races.priority`` is read and handed to the
calculation, and that the constants exist for the service tests to import.

Three features have now been silently reverted by merges in this repo
(``compute_losing_lean_mass_flag``, ``B_RACE_TIGHTENING_FLOOR``, and this one).
Each time the regression test was the only witness and each time it was a
collection error nobody saw — see #1606 for the suite-level fix.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from backend.services import training_load

REPO = Path(__file__).resolve().parents[1]


# ── The constants exist ───────────────────────────────────────────────────────

def test_priority_taper_constants_exist():
    """Their absence is the exact ImportError that hid this bug for 41 days."""
    assert training_load.A_RACE_TAPER_DAYS == 14
    assert training_load.B_RACE_TAPER_DAYS == 7


def test_a_race_taper_is_longer_than_b_race():
    """The whole point: a goal race earns a full taper, a tune-up does not."""
    assert training_load.A_RACE_TAPER_DAYS > training_load.B_RACE_TAPER_DAYS


# ── The service honours priority ──────────────────────────────────────────────

def test_taper_recommendation_accepts_priority():
    src = inspect.getsource(training_load.taper_recommendation)
    assert 'fitness_state.get("priority"' in src
    assert "B_RACE_TAPER_DAYS" in src
    assert "A_RACE_TAPER_DAYS" in src


def test_unknown_priority_falls_back_to_the_a_race_taper():
    """Anything that isn't "B" stays conservative. A null or a "C" must not
    accidentally shorten a taper."""
    src = inspect.getsource(training_load.taper_recommendation)
    assert 'B_RACE_TAPER_DAYS if priority == "B" else A_RACE_TAPER_DAYS' in src


# ── The caller threads it through ─────────────────────────────────────────────
#
# This is the actual regression. The service could read `priority` all along;
# main.py simply never put it in the dict.

def _race_readiness_source() -> str:
    """The block that builds fitness_state and calls taper_recommendation."""
    src = (REPO / "backend" / "main.py").read_text()
    call = src.index("taper_raw = taper_recommendation(")
    # Walk back to the fitness_state literal feeding that call.
    start = src.rindex("fitness_state = {", 0, call)
    return src[start:call]


def test_fitness_state_carries_the_race_priority():
    block = _race_readiness_source()
    assert '"priority"' in block, (
        "main.py builds fitness_state without a priority key, so every race — "
        "A, B and C — gets the A-race taper. This is issue #1605."
    )


def test_priority_comes_from_the_race_row_not_a_constant():
    """Hardcoding "A" here would make the test above pass while leaving the bug
    exactly as it was."""
    block = _race_readiness_source()
    assert "race" in block and "priority" in block
    assert 'getattr(race, "priority", None)' in block


def test_priority_defaults_when_the_race_has_none():
    """races.priority is nullable; a null must not crash and must not shorten
    the taper."""
    block = _race_readiness_source()
    assert 'or "A"' in block


# ── The data is there to read ─────────────────────────────────────────────────

def test_races_table_has_a_priority_column():
    """The column existed the whole time the feature was reverted — the data
    was never the missing piece."""
    models = (REPO / "backend" / "models.py").read_text()
    assert "RACE_PRIORITY_VALUES" in models
    assert "ck_races_priority_values" in models


# ── The docs agree ────────────────────────────────────────────────────────────

def test_training_load_doc_mentions_the_priority_split():
    """docs/calculations/training-load.md documented only DEFAULT_TAPER_DAYS,
    so the doc agreed with the broken code and gave no signal."""
    doc = (REPO / "docs" / "calculations" / "training-load.md")
    if not doc.exists():
        pytest.skip("training-load.md not present")
    text = doc.read_text()
    assert "A_RACE_TAPER_DAYS" in text or "B_RACE_TAPER_DAYS" in text, (
        "the taper doc still describes a single taper length"
    )
