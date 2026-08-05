"""Tests for issue #853: _hcalInitialized flag never reset on userChanged.

Verifies that the habits calendar state is properly reset when a userChanged
event fires, so a user switch without page reload does not show stale data
from the previous user.

AC1: On userChanged, _hcalInitialized is reset to false so initHabitCal()
     re-runs month/week-start initialisation for the new user context.
AC2: On userChanged, hcalFetchedRange is cleared so _fetchCalendarRange
     performs a fresh server fetch (no stale cache hit from the previous user).
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).parent.parent


def _js() -> str:
    return (ROOT / "frontend" / "js" / "habits.js").read_text()


# ── AC1: _hcalInitialized reset on userChanged ───────────────────────────────

def test_user_changed_resets_hcal_initialized():
    """AC1: The userChanged handler sets _hcalInitialized = false."""
    js = _js()
    # Locate the userChanged event listener block
    idx = js.find("userChanged")
    assert idx != -1, "habits.js must have a userChanged event listener"

    # Grab a reasonable window around it (2000 chars covers the handler body)
    handler_region = js[idx: idx + 2000]

    assert "_hcalInitialized = false" in handler_region, (
        "The userChanged handler must reset _hcalInitialized = false so that "
        "initHabitCal() re-initialises month/week-start for the new user (AC1)"
    )


# ── AC2: hcalFetchedRange cleared on userChanged ─────────────────────────────

def test_user_changed_clears_hcal_fetched_range():
    """AC2: The userChanged handler sets hcalFetchedRange = null."""
    js = _js()
    idx = js.find("userChanged")
    assert idx != -1, "habits.js must have a userChanged event listener"

    handler_region = js[idx: idx + 2000]

    assert "hcalFetchedRange = null" in handler_region, (
        "The userChanged handler must set hcalFetchedRange = null so that "
        "_fetchCalendarRange performs a fresh fetch after a user switch (AC2)"
    )


# ── Guard: resets appear BEFORE the loadAndRender() call ─────────────────────

def test_resets_precede_load_and_render():
    """AC1+AC2: Both resets happen before loadAndRender() is called."""
    js = _js()
    idx = js.find("userChanged")
    assert idx != -1

    handler_region = js[idx: idx + 2000]

    # Find positions of each token within the handler region
    pos_initialized = handler_region.find("_hcalInitialized = false")
    pos_fetched     = handler_region.find("hcalFetchedRange = null")
    pos_load        = handler_region.find("loadAndRender")

    assert pos_initialized != -1, "_hcalInitialized reset not found in userChanged handler"
    assert pos_fetched     != -1, "hcalFetchedRange reset not found in userChanged handler"
    assert pos_load        != -1, "loadAndRender call not found in userChanged handler"

    assert pos_initialized < pos_load, (
        "_hcalInitialized = false must appear before loadAndRender() in the userChanged handler"
    )
    assert pos_fetched < pos_load, (
        "hcalFetchedRange = null must appear before loadAndRender() in the userChanged handler"
    )
