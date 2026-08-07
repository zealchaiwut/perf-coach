"""Home brief-related cards after home revamp v2.

Issue #1499 originally added three Daily Brief widgets into gridstack.
Revamp v2 retired gridstack and the form/advisories brief cards; the week
plan teaser remains as #home-brief-week-plan-card in the plain CSS columns.
These tests track the surviving surface (and the layout engine change).
"""
import pathlib
import os
import pytest
import httpx


_ROOT = pathlib.Path(__file__).parent.parent
_HOME_HTML = (_ROOT / "frontend" / "pages" / "home.html").read_text()

_UAT_PORT = os.environ.get("UAT_PORT", "").strip()
BASE_URL = os.environ.get("UAT_BASE_URL") or (
    ("http://localhost:" + _UAT_PORT) if _UAT_PORT else ""
)


@pytest.fixture
def client():
    if not BASE_URL:
        pytest.skip("UAT_BASE_URL / UAT_PORT not set")
    with httpx.Client(base_url=BASE_URL, timeout=10.0, follow_redirects=False) as c:
        yield c


def test_daily_brief_widget_cards__week_plan_in_cols_layout():
    """Week plan card lives in #home-cols; gridstack wrappers are gone."""
    assert 'id="home-brief-week-plan-card"' in _HOME_HTML
    assert 'id="home-cols"' in _HOME_HTML
    assert 'class="grid-stack-item"' not in _HOME_HTML
    assert not (_ROOT / "frontend" / "js" / "home-grid.js").exists()


def test_daily_brief_widget_cards__retired_brief_hosts_gone():
    """Form + advisories brief hosts were removed with the revamp."""
    assert 'id="home-brief-form-card"' not in _HOME_HTML
    assert 'id="home-brief-advisories-card"' not in _HOME_HTML


def test_daily_brief_widget_cards__week_plan_module_loaded():
    assert "home-brief-week-plan-card.js" in _HOME_HTML
    week_js = (_ROOT / "frontend" / "js" / "home-brief-week-plan-card.js").read_text()
    assert "function esc(" in week_js or "AppCommon.escapeHtml" in week_js


def test_daily_brief_widget_cards__weight_trend_host_present():
    """Weight logging moved to morning; trend card remains on Home."""
    assert 'id="home-weight-trend"' in _HOME_HTML
    assert "home-weight-trend.js" in _HOME_HTML
    assert 'id="home-weight-widget"' not in _HOME_HTML


def test_daily_brief_widget_cards__api_endpoint_exists():
    pytest.skip("live UAT optional — /api/brief/today covered elsewhere when server is up")


def test_daily_brief_widget_cards__impeccable_check_passes():
    pytest.skip("manual — impeccable detect must be run locally, not HTTP-tested")
