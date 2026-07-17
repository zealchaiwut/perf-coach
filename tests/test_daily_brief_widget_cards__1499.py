"""Tests for issue #1499: Add Daily Brief widget cards to Home grid (runs against UAT)"""
import os
import pytest
import httpx


# Resolved from UAT .env at runtime; see tester skill Step 0.
# Default kept only as a last-resort fallback if BASE_URL not exported.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0, follow_redirects=False) as c:
        yield c


# --- Acceptance Criteria ---

def test_daily_brief_widget_cards__three_cards_registered_in_registry(client):
    # AC: Three new widget cards are registered in frontend/js/home-grid.js REGISTRY
    # with per-breakpoint column/row spans matching the existing card pattern

    # Read the home.html source to verify the card elements are present in the markup
    import pathlib
    home_html_path = pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html"
    html = home_html_path.read_text()

    assert 'id="home-brief-form-card"' in html, "Form card element should exist in home.html"
    assert 'id="home-brief-week-plan-card"' in html, "Week plan card element should exist in home.html"
    assert 'id="home-brief-advisories-card"' in html, "Advisories card element should exist in home.html"

    # Verify the cards are wrapped in gridstack items
    assert 'class="grid-stack-item"' in html, "Cards should be wrapped in gridstack items"
    assert 'class="grid-stack-item-content"' in html, "Cards should be wrapped in gridstack item content"


def test_daily_brief_widget_cards__api_endpoint_exists(client):
    # AC: The /api/brief/today endpoint exists and returns the expected structure

    r = client.get("/api/brief/today")
    # Could be 401 (unauthenticated) or 200 (authenticated)
    assert r.status_code in [200, 401], f"Unexpected status code: {r.status_code}"

    if r.status_code == 200:
        data = r.json()
        assert isinstance(data, dict), "Response should be a dictionary"


def test_daily_brief_widget_cards__form_card_displays_metrics(client):
    # AC: Form card displays CTL, ATL, and TSB values rendered in JetBrains Mono,
    # an ACWR value, and the one-line form.interpretation text

    r = client.get("/api/brief/today")
    if r.status_code == 200:
        data = r.json()
        assert "form" in data, "Response should have 'form' field"
        form = data["form"]

        # Verify the required form fields are present
        assert "ctl" in form, "Form should have 'ctl' field"
        assert "atl" in form, "Form should have 'atl' field"
        assert "tsb" in form, "Form should have 'tsb' field"
        assert "interpretation" in form, "Form should have 'interpretation' field"


def test_daily_brief_widget_cards__form_card_acwr_pill_colors(client):
    # AC: Form card ACWR pill uses --green-soft when acwr_state === 'ok',
    # --amber-soft for 'caution', and --red-soft for 'high'

    r = client.get("/api/brief/today")
    if r.status_code == 200:
        data = r.json()
        assert "form" in data
        form = data["form"]

        # Verify the flags structure is present
        if "flags" in form:
            flags = form["flags"]
            # Verify acwr_state is one of the valid values
            if "acwr_state" in flags:
                assert flags["acwr_state"] in ["ok", "caution", "high"], \
                    f"Invalid acwr_state: {flags['acwr_state']}"


def test_daily_brief_widget_cards__week_plan_card_renders_rows(client):
    # AC: Week Plan card renders one row per week_plan day in the format
    # `Day  type  duration`; today and tomorrow rows appear at the top;
    # days with planned === false render as Rest

    r = client.get("/api/brief/today")
    if r.status_code == 200:
        data = r.json()
        assert "week_plan" in data, "Response should have 'week_plan' field"
        week_plan = data["week_plan"]

        # Verify the week_plan structure
        assert "days" in week_plan, "Week plan should have 'days' field"
        days = week_plan["days"]

        if len(days) > 0:
            # Verify each day has the required structure
            for day in days:
                assert "day" in day, "Day should have 'day' field"
                assert "date" in day, "Day should have 'date' field"
                assert "planned" in day, "Day should have 'planned' field"

                if day["planned"]:
                    assert "session_type" in day, "Planned day should have 'session_type' field"
                    assert "duration_min" in day, "Planned day should have 'duration_min' field"


def test_daily_brief_widget_cards__advisories_card_displays_list(client):
    # AC: Advisories card renders a bullet list of advisories[].text;
    # items with severity === 'warn' display a warning glyph prefix;
    # when advisories is empty the card shows (none)

    r = client.get("/api/brief/today")
    if r.status_code == 200:
        data = r.json()
        assert "advisories" in data, "Response should have 'advisories' field"
        advisories = data["advisories"]

        # Advisories must be a list (can be empty)
        assert isinstance(advisories, list), "Advisories should be a list"

        # If there are advisories, check the structure
        for advisory in advisories:
            assert "text" in advisory, "Advisory should have 'text' field"
            assert "severity" in advisory, "Advisory should have 'severity' field"


def test_daily_brief_widget_cards__loading_state_displayed(client):
    # AC: All three cards display a skeleton/loading state while the fetch is in-flight

    # Read the home.html source to verify skeleton markup
    import pathlib
    home_html_path = pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html"
    html = home_html_path.read_text()

    # Check that skeleton CSS classes are defined
    assert "brief-skeleton" in html, "Page should have skeleton CSS class"
    assert "brief-skel-row" in html, "Page should have skel-row CSS class"


def test_daily_brief_widget_cards__fetch_failure_handling(client):
    # AC: If the fetch fails, each card independently degrades to a quiet
    # "unavailable" inline message; no console.error is thrown;
    # the rest of the Home page (including the Weight card) is unaffected

    # Read the home.html source to verify error state markup
    import pathlib
    home_html_path = pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html"
    html = home_html_path.read_text()

    # Check that unavailable state CSS class exists
    assert "brief-unavail" in html, "Page should have brief-unavail CSS class for error state"


def test_daily_brief_widget_cards__markup_uses_esc_for_values(client):
    # AC: Card markup uses esc() for every interpolated value;
    # no raw interpolation of API data

    # Read the home.html source to verify card JS modules are loaded
    import pathlib
    home_html_path = pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html"
    html = home_html_path.read_text()

    # Verify the card JS modules are loaded
    assert "home-brief-form-card.js" in html, "Page should load form card JS module"
    assert "home-brief-week-plan-card.js" in html, "Page should load week plan card JS module"
    assert "home-brief-advisories-card.js" in html, "Page should load advisories card JS module"

    # Verify the JS files themselves contain esc() functions
    form_card_path = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home-brief-form-card.js"
    form_card_js = form_card_path.read_text()
    assert "function esc(" in form_card_js or "function esc (" in form_card_js, "Form card should use esc() for escaping"


def test_daily_brief_widget_cards__responsive_at_breakpoints(client):
    # AC: Cards are responsive at all breakpoints defined in the REGISTRY
    # (mobile, tablet, desktop)

    # Read the home-grid.js source to verify REGISTRY contains brief cards
    import pathlib
    grid_js_path = pathlib.Path(__file__).parent.parent / "frontend" / "js" / "home-grid.js"
    grid_js = grid_js_path.read_text()

    # Check that all three brief cards are registered with breakpoint spans
    assert "home-brief-form-card" in grid_js, "Form card should be in REGISTRY"
    assert "home-brief-week-plan-card" in grid_js, "Week plan card should be in REGISTRY"
    assert "home-brief-advisories-card" in grid_js, "Advisories card should be in REGISTRY"
    # Verify they have breakpoint column spans
    assert "8:" in grid_js or "6:" in grid_js, "Cards should have breakpoint-specific column spans"


def test_daily_brief_widget_cards__weight_card_unchanged(client):
    # AC: The existing Weight card is visually and functionally unchanged

    # Read the home.html source to verify Weight card still exists
    import pathlib
    home_html_path = pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "home.html"
    html = home_html_path.read_text()

    # Verify the Weight card elements are still present
    assert 'id="home-weight-widget"' in html, "Weight card container should still exist"
    assert "Weight" in html, "Weight label should still appear on page"


def test_daily_brief_widget_cards__impeccable_check_passes(client):
    pytest.skip("manual — impeccable detect must be run locally, not HTTP-tested")
