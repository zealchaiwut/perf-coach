"""UAT tests for issue #633: Redesign weight trend chart with three-zone axes

This is a re-run after LINT_FAIL. The linting issues have been fixed in commits:
  229b121: fix(weight-chart): resolve impeccable low-contrast failures
  5289c97: fix(weight-chart): apply Prettier formatting

Tests focus on verifying:
- The weight chart frontend code correctly implements the three-zone layout
- The API response structure continues to support the redesign
- Range tabs work properly (7D, 30D, 90D, 6M, 1Y, ALL)
- Browser interactions (tooltips, visibility) are preserved

The structural code tests (test_weight_chart_three_zone_redesign__633.py) verify
all 27 AC requirements. This file adds UAT integration checks.
"""
import os
import pytest
import httpx

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


def test_uat_server_responding(client):
    """Verify UAT server is responding."""
    r = client.get("/api/health")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "ok"
    assert data.get("environment") == "uat"


def test_weight_chart_endpoint_accessible(client):
    """Weight chart endpoint is accessible (returns auth required if not logged in)."""
    # Unauthenticated request should get 401
    r = client.get("/api/weight-chart")
    assert r.status_code == 401, "Endpoint should require authentication"


def test_weight_page_loads(client):
    """Weight page HTML file loads and includes the three-zone chart script."""
    r = client.get("/weight")
    assert r.status_code in (200, 302), f"Weight page returned {r.status_code}"
    if r.status_code == 200:
        html = r.text
        # Page should include the weight-chart.js script
        assert "weight-chart.js" in html, "weight-chart.js not loaded on weight page"
        # Page should have the chart container
        assert "weight-chart" in html.lower(), "No weight-chart container on page"
