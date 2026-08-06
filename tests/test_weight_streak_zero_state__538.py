"""
Tests for issue #538: Weight page streak badge zero-state copy.

The weight-tab revamp retired the streak badge in favour of the coverage gate
(see test_weight_page_frontend__revamp.py / test_weight_lock_group__revamp.py).
These ACs are kept as skipped documentation of the prior contract.
"""
import pytest

pytestmark = pytest.mark.skip(
    reason="streak badge retired by weight-tab revamp; coverage gate replaces it"
)


def test_streak_zero_shows_no_streak_yet():
    assert False


def test_streak_one_shows_singular():
    assert False


def test_streak_plural_template_present():
    assert False


def test_html_default_is_not_zero_day_streak():
    assert False


def test_js_ternary_covers_all_three_cases():
    assert False
