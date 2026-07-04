"""Tests for issue #1123: Monthly digest card form chip fix.

_renderMonth() checks data.form_tsb_change, but the monthly API doesn't return
that field — it returns fitness_ctl_change and form_recovered. This means the
form chip is always silently absent in the monthly view. Fix: update _sdChips to
use fitness_ctl_change / form_recovered when form_tsb_change is absent.

AC1: _renderMonth() no longer relies solely on form_tsb_change; fitness_ctl_change
     (numeric delta) or form_recovered (boolean badge) is used for the monthly form chip.
AC2: Monthly digest card renders a form chip/badge when API returns a non-null
     fitness_ctl_change value or a form_recovered value.
AC3: Monthly summary API endpoint response contract is unchanged — no new fields
     added or removed.
AC4: When fitness_ctl_change is null/absent, no form chip is rendered and no JS error.
AC5: Chip value correctly reflects API data (numeric delta for fitness_ctl_change,
     'Recovered'/'Not recovered' label for form_recovered).
"""
import os
import re

import pytest


@pytest.fixture(scope="module")
def training_log_js():
    js_path = os.path.join(os.path.dirname(__file__), "../frontend/js/training-log.js")
    with open(js_path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def main_py():
    path = os.path.join(os.path.dirname(__file__), "../backend/main.py")
    with open(path, encoding="utf-8") as f:
        return f.read()


# ── AC1: fitness_ctl_change referenced in JS ────────────────────────────────────

def test_sdchips_references_fitness_ctl_change(training_log_js):
    """AC1: JS must reference fitness_ctl_change for the monthly form chip."""
    assert "fitness_ctl_change" in training_log_js, (
        "frontend/js/training-log.js must reference fitness_ctl_change to render "
        "the monthly form chip (the monthly API returns this field, not form_tsb_change)"
    )


def test_sdchips_references_form_recovered(training_log_js):
    """AC1: JS must reference form_recovered for the monthly form badge."""
    assert "form_recovered" in training_log_js, (
        "frontend/js/training-log.js must reference form_recovered to render "
        "a Recovered/Not recovered badge in the monthly form chip"
    )


def test_form_tsb_change_still_present_for_weekly(training_log_js):
    """AC1: form_tsb_change must still be referenced for the weekly form chip path."""
    assert "form_tsb_change" in training_log_js, (
        "form_tsb_change must remain in training-log.js for the weekly view — "
        "the weekly summary endpoint still returns this field"
    )


# ── AC2: Form chip renders for monthly data ──────────────────────────────────────

def test_fitness_ctl_change_has_null_guard(training_log_js):
    """AC2: JS must have a null guard on fitness_ctl_change before rendering the chip."""
    has_guard = re.search(
        r"fitness_ctl_change\s*!=\s*null"
        r"|fitness_ctl_change\s*!==\s*null"
        r"|if\s*\([^)]*fitness_ctl_change",
        training_log_js,
    )
    assert has_guard, (
        "JS must guard the monthly form chip with a null check on fitness_ctl_change (AC2/AC4)"
    )


def test_chip_shows_recovered_label(training_log_js):
    """AC2: JS must render a 'Recovered' label derived from form_recovered=true."""
    assert "Recovered" in training_log_js, (
        "JS must render 'Recovered' label when form_recovered is true (AC2/AC5)"
    )


def test_chip_shows_not_recovered_label(training_log_js):
    """AC2: JS must render a 'Not recovered' label derived from form_recovered=false."""
    has_not_recovered = (
        "Not recovered" in training_log_js
        or "not recovered" in training_log_js
    )
    assert has_not_recovered, (
        "JS must render a 'Not recovered' label when form_recovered is false (AC2/AC5)"
    )


# ── AC3: API response contract unchanged ────────────────────────────────────────

def test_monthly_api_still_returns_fitness_ctl_change(main_py):
    """AC3: Monthly API endpoint must still return fitness_ctl_change."""
    assert '"fitness_ctl_change"' in main_py, (
        "Monthly summary API must still include fitness_ctl_change in its response (AC3)"
    )


def test_monthly_api_still_returns_form_recovered(main_py):
    """AC3: Monthly API endpoint must still return form_recovered."""
    assert '"form_recovered"' in main_py, (
        "Monthly summary API must still include form_recovered in its response (AC3)"
    )


def test_monthly_api_does_not_add_form_tsb_change(main_py):
    """AC3: Monthly API must NOT add form_tsb_change to its response payload."""
    mpayload_match = re.search(
        r"_mpayload\s*=\s*\{(.+?)\}\s*\n\s*_summary_cache_put",
        main_py,
        re.DOTALL,
    )
    assert mpayload_match, "_mpayload block not found in backend/main.py"
    block = mpayload_match.group(1)
    assert "form_tsb_change" not in block, (
        "Monthly API must NOT include form_tsb_change in its response "
        "— the fix is frontend-only (AC3)"
    )


# ── AC4: No chip and no error when fitness_ctl_change is null ───────────────────

def test_null_fitness_ctl_change_guarded(training_log_js):
    """AC4: JS handles null fitness_ctl_change without rendering a chip or throwing."""
    has_guard = re.search(
        r"fitness_ctl_change\s*!=\s*null"
        r"|fitness_ctl_change\s*!==\s*null"
        r"|if\s*\([^)]*fitness_ctl_change\s*!=",
        training_log_js,
    )
    assert has_guard, (
        "JS must null-guard fitness_ctl_change so no chip renders and no error is "
        "thrown when the value is absent (AC4)"
    )


# ── AC5: Chip value correctly reflects API data ──────────────────────────────────

def test_fmt_delta_called_with_fitness_ctl_change(training_log_js):
    """AC5: JS must format the fitness_ctl_change value via _fmtDelta for the chip."""
    has_fmt = re.search(
        r"_fmtDelta\s*\(\s*(?:data\.)?fitness_ctl_change",
        training_log_js,
    )
    assert has_fmt, (
        "JS must call _fmtDelta(data.fitness_ctl_change, ...) to format the monthly "
        "form chip value so the numeric delta is displayed correctly (AC5)"
    )
