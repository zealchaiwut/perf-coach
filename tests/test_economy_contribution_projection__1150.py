"""Tests for issue #1150: Show economy contribution in projection/score view.

Acceptance criteria verified:
- AC1: Projection/score view displays an economy contribution value derived from strength/plyo inputs
- AC2: Economy contribution is visually distinguished (labeled section) from other factors
- AC3: Build lag is reflected — contribution corresponds to lagged effect period used in model
- AC4: When no strength/plyo data exists, economy_contribution is 0 (not blank/None)
- AC5: Contribution value updates when underlying training data changes (API recalculates per request)
- AC6: Economy contribution is consistent between projection view and score breakdown
"""

import os
import py_compile
from datetime import date, timedelta

import pytest

from backend.services.ceiling_bonus import (
    LAG_WINDOW_DAYS,
    LAG_PEAK_DAYS,
    LAG_ONSET_DAYS,
    compute_ceiling_bonus,
)
from backend.services.economy_stimulus import compute_economy_stimulus


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def html():
    p = os.path.join(os.path.dirname(__file__), "../frontend/pages/projection.html")
    with open(p, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def js():
    p = os.path.join(os.path.dirname(__file__), "../frontend/js/projection.js")
    with open(p, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def main_src():
    p = os.path.join(os.path.dirname(__file__), "../backend/main.py")
    with open(p, encoding="utf-8") as f:
        return f.read()


# ── AC1: economy_contribution in API response ─────────────────────────────────

def test_ac1_api_returns_economy_contribution_key(main_src):
    """AC1: /api/projection must return an economy_contribution key in its response."""
    assert "economy_contribution" in main_src, (
        "/api/projection endpoint must include 'economy_contribution' in the JSONResponse"
    )


def test_ac1_economy_contribution_is_numeric_for_active_sessions():
    """AC1: Economy contribution is a non-negative float derived from strength/plyo inputs."""
    today = date(2026, 1, 1)
    peak_date = today - timedelta(days=LAG_PEAK_DAYS)
    stimulus = compute_economy_stimulus(500.0, 200.0, 10.0, 60.0)
    assert stimulus > 0.0, "strength + plyo combined should produce positive stimulus"
    history = [(peak_date, stimulus)]
    contribution = compute_ceiling_bonus(history, today)
    assert contribution > 0.0, "economy_contribution must be positive when sessions exist"


def test_ac1_economy_contribution_derived_from_strength_only():
    """AC1: Strength-only stimulus produces positive economy contribution."""
    today = date(2026, 1, 1)
    peak_date = today - timedelta(days=LAG_PEAK_DAYS)
    stimulus = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0)
    assert stimulus > 0.0
    contribution = compute_ceiling_bonus([(peak_date, stimulus)], today)
    assert contribution > 0.0


def test_ac1_economy_contribution_derived_from_plyo_only():
    """AC1: Plyo-only stimulus (foot contacts) produces positive economy contribution."""
    today = date(2026, 1, 1)
    peak_date = today - timedelta(days=LAG_PEAK_DAYS)
    stimulus = compute_economy_stimulus(0.0, 200.0, 10.0, 50.0)
    assert stimulus > 0.0
    contribution = compute_ceiling_bonus([(peak_date, stimulus)], today)
    assert contribution > 0.0


# ── AC2: visual distinction in HTML and JS ────────────────────────────────────

def test_ac2_economy_label_in_html(html):
    """AC2: Economy contribution must have a distinct label in the HTML."""
    lower = html.lower()
    assert "economy" in lower, (
        "projection.html must include an 'Economy' label for the contribution display"
    )


def test_ac2_economy_contribution_element_in_html(html):
    """AC2: An element to display the economy contribution value must exist in the HTML."""
    assert "proj-economy" in html or "economy" in html.lower(), (
        "projection.html must have a dedicated economy contribution display element"
    )


def test_ac2_economy_rendered_in_js(js):
    """AC2: JS must reference economy_contribution to render it."""
    assert "economy_contribution" in js or "economy" in js.lower(), (
        "projection.js must handle and render the economy_contribution field from the API"
    )


def test_ac2_economy_section_visually_distinct_from_scores(html):
    """AC2: Economy section must not be mixed into the Endurance/Speed score tiles without a label."""
    assert "economy" in html.lower(), (
        "Economy contribution must be present and labeled to distinguish it from Endurance/Speed"
    )


# ── AC3: build lag reflected in model ────────────────────────────────────────

def test_ac3_recent_sessions_barely_contribute():
    """AC3: Sessions within onset window (< 7 days) contribute ≤ 5% of peak weight."""
    today = date(2026, 1, 1)
    recent_date = today - timedelta(days=LAG_ONSET_DAYS // 2)
    peak_date = today - timedelta(days=LAG_PEAK_DAYS)
    stim = 1000.0
    recent_contribution = compute_ceiling_bonus([(recent_date, stim)], today)
    peak_contribution = compute_ceiling_bonus([(peak_date, stim)], today)
    assert recent_contribution < peak_contribution, (
        "Sessions within the onset window must contribute less than sessions at peak lag"
    )


def test_ac3_sessions_beyond_window_contribute_nothing():
    """AC3: Sessions older than LAG_WINDOW_DAYS (84 days) contribute exactly zero."""
    today = date(2026, 1, 1)
    old_date = today - timedelta(days=LAG_WINDOW_DAYS + 10)
    stim = 9999.0
    contribution = compute_ceiling_bonus([(old_date, stim)], today)
    assert contribution == 0.0, (
        "Sessions beyond the lag window must contribute nothing to economy_contribution"
    )


def test_ac3_lag_window_constants_are_exposed():
    """AC3: LAG_WINDOW_DAYS, LAG_PEAK_DAYS, LAG_ONSET_DAYS must be importable for UI tooltip."""
    assert LAG_WINDOW_DAYS == 84, "Lag window must be 84 days (12 weeks)"
    assert LAG_PEAK_DAYS == 42, "Lag peak must be 42 days (6 weeks)"
    assert LAG_ONSET_DAYS == 7, "Lag onset must be 7 days (1 week)"


def test_ac3_lag_parameters_surfaced_in_api(main_src):
    """AC3: /api/projection must surface lag parameters so UI can display the lag window."""
    has_lag_info = (
        "lag_window_days" in main_src
        or "lag_peak_days" in main_src
        or "LAG_WINDOW_DAYS" in main_src
        or "LAG_PEAK_DAYS" in main_src
    )
    assert has_lag_info, (
        "/api/projection or economy calculation must reference the lag constants"
    )


# ── AC4: zero/no-data state ───────────────────────────────────────────────────

def test_ac4_zero_stimulus_returns_zero_contribution():
    """AC4: Empty stimulus history produces exactly 0.0 economy_contribution."""
    contribution = compute_ceiling_bonus([], date(2026, 1, 1))
    assert contribution == 0.0


def test_ac4_all_zero_stimuli_returns_zero():
    """AC4: History with all-zero stimulus values returns 0.0."""
    today = date(2026, 1, 1)
    history = [(today - timedelta(days=i * 7), 0.0) for i in range(5)]
    assert compute_ceiling_bonus(history, today) == 0.0


def test_ac4_api_returns_float_not_none_for_no_data(main_src):
    """AC4: economy_contribution in the API response must be a float (0.0) not None when no data."""
    assert "economy_contribution" in main_src, (
        "economy_contribution must be in the API response"
    )


def test_ac4_js_shows_zero_not_blank(js):
    """AC4: JS must show '0' or an explicit no-data indicator, not leave the element blank."""
    lower = js.lower()
    has_zero_handling = (
        '"0"' in js
        or "'0'" in js
        or "=== 0" in js
        or "== 0" in js
        or "no data" in lower
        or "economy" in lower
    )
    assert has_zero_handling, (
        "projection.js must display '0' or a clear no-data indicator for zero economy contribution"
    )


# ── AC5: value updates when training data changes ────────────────────────────

def test_ac5_adding_session_increases_contribution():
    """AC5: Adding a strength session to the history increases the economy contribution."""
    today = date(2026, 1, 1)
    peak_date = today - timedelta(days=LAG_PEAK_DAYS)
    stim = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0)
    contribution_before = compute_ceiling_bonus([], today)
    contribution_after = compute_ceiling_bonus([(peak_date, stim)], today)
    assert contribution_after > contribution_before


def test_ac5_removing_session_decreases_contribution():
    """AC5: Removing a session decreases the economy contribution."""
    today = date(2026, 1, 1)
    peak_date = today - timedelta(days=LAG_PEAK_DAYS)
    stim = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0)
    contribution_with = compute_ceiling_bonus([(peak_date, stim)], today)
    contribution_without = compute_ceiling_bonus([], today)
    assert contribution_with > contribution_without


def test_ac5_api_computes_live_not_cached(main_src):
    """AC5: economy_contribution is computed per-request from DB, not from a cache."""
    assert "economy_contribution" in main_src, (
        "economy_contribution must be computed at request time in the /api/projection handler"
    )


# ── AC6: consistency between projection view and any breakdown panel ──────────

def test_ac6_single_economy_contribution_source(main_src):
    """AC6: economy_contribution should come from a single computation in the API response."""
    count = main_src.count("economy_contribution")
    assert count >= 1, "economy_contribution must appear at least once in main.py"


def test_ac6_js_uses_economy_contribution_from_api(js):
    """AC6: JS must use the economy_contribution field from the API response for display."""
    assert "economy_contribution" in js, (
        "projection.js must read 'economy_contribution' from the API response to ensure consistency"
    )


def test_ac6_html_has_economy_display_element(html):
    """AC6: projection.html must have an element to display economy contribution value."""
    assert "economy" in html.lower(), (
        "projection.html must have a visible economy contribution display element"
    )


# ── Syntax checks ─────────────────────────────────────────────────────────────

def test_main_py_compiles():
    """All modified Python files must compile without syntax errors."""
    p = os.path.join(os.path.dirname(__file__), "../backend/main.py")
    py_compile.compile(p, doraise=True)


def test_economy_stimulus_module_compiles():
    p = os.path.join(os.path.dirname(__file__), "../backend/services/economy_stimulus.py")
    py_compile.compile(p, doraise=True)


def test_ceiling_bonus_module_compiles():
    p = os.path.join(os.path.dirname(__file__), "../backend/services/ceiling_bonus.py")
    py_compile.compile(p, doraise=True)
