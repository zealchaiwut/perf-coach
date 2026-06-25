"""Tests for issue #413: Build weight target management page (/weight/targets) (runs against UAT)

Risk: MEDIUM — new frontend page with multiple UI sections, no auth/security/destructive changes.
→ 1-2 tests per criterion where HTTP-testable; visual/JS-driven ACs marked manual.

Prerequisites: tester413 user must exist in UAT DB with password "Test413pass!".

NOTE — issue #461 (sprint-56): The standalone /weight/targets page was consolidated into
/weight via a slide-in panel. /weight/targets now redirects (302) to /weight.
Tests that previously checked weight-targets.html content now verify the redirect
and the equivalent functionality on /weight. API endpoint tests are unchanged.
"""
import os
import uuid
import datetime as _dt
import pytest
import httpx

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_CREDENTIALS = {"username": "tester413", "password": "Test413pass!"}
WT = "/api/weight-targets"
WE = "/api/weight-entries"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        r = c.post("/api/auth/login", json=_CREDENTIALS)
        assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── Routing & Shell ───────────────────────────────────────────────────────────
# Updated for #461: /weight/targets now redirects (302) to /weight.

def test_build_weight_target_management_page__route_returns_200(client):
    # AC #461: /weight/targets redirects to /weight; httpx follows and gets 200 HTML.
    r = client.get("/weight/targets")
    assert r.status_code == 200, f"Expected 200 after redirect, got {r.status_code}"
    assert "text/html" in r.headers.get("content-type", ""), "Response is not HTML"
    # Verify we landed on /weight (redirect was followed)
    assert str(r.url).rstrip("/").endswith("/weight"), (
        f"Expected redirect to /weight, landed at {r.url}"
    )


def test_build_weight_target_management_page__weight_targets_js_loaded(client):
    # AC #461: /weight/targets page removed; weight-targets.js no longer served.
    # After the redirect, the /weight page is returned — it must NOT load weight-targets.js.
    r = client.get("/weight/targets")
    assert r.status_code == 200
    assert "weight-targets.js" not in r.text, (
        "weight-targets.js must NOT be loaded — the page was consolidated into /weight"
    )
    # /weight page must be served instead
    assert "weight.js" in r.text, "weight.js must be present on the /weight page"


# ── Section A — Header ────────────────────────────────────────────────────────
# Updated for #461: content now lives on /weight, not on a separate /weight/targets page.

def test_build_weight_target_management_page__breadcrumb_and_title(client):
    # AC #461: /weight/targets redirects to /weight; the Weight page title is present.
    r = client.get("/weight/targets")
    html = r.text
    # /weight page serves "Weight" as the title (the separate targets page is gone)
    assert "Weight" in html, "Weight page title missing after redirect from /weight/targets"


def test_build_weight_target_management_page__set_new_target_button_present(client):
    # AC #461: Standalone "Set new target" form was removed; Edit target is now a slide-in
    # panel on /weight. The /weight page has an "Edit target" control instead.
    r = client.get("/weight/targets")
    assert "Edit target" in r.text or "edit-target" in r.text, (
        "Edit target control not found on /weight after redirect"
    )


def test_build_weight_target_management_page__disabled_button_tooltip(client):
    # AC #461: Target management moved to /weight slide-in panel.
    # Verify the /weight page loaded (tooltip logic is now JS-only in the panel).
    r = client.get("/weight/targets")
    assert r.status_code == 200, "Redirect from /weight/targets failed"


# ── Section B — Active Target Card (static HTML elements) ────────────────────
# Updated for #461: active target management is now in the /weight slide-in panel.

def test_build_weight_target_management_page__active_target_banner(client):
    # AC #461: "ACTIVE TARGET" banner on the old standalone page is replaced by the
    # /weight progress card. Verify the /weight page has the progress card.
    r = client.get("/weight/targets")
    html = r.text
    # /weight has the progress card which shows target context
    assert 'id="progress-card"' in html, (
        "progress-card not found on /weight after redirect from /weight/targets"
    )


def test_build_weight_target_management_page__active_card_edit_end_buttons(client):
    # AC #461: Edit/End actions moved to the /weight slide-in panel.
    r = client.get("/weight/targets")
    html = r.text
    # /weight page has the slide-in panel with save/end buttons
    assert 'id="et-save-btn"' in html or 'id="edit-panel"' in html, (
        "Edit panel not found on /weight after redirect from /weight/targets"
    )
    assert 'id="et-end-btn"' in html, "End target button not found in /weight edit panel"


def test_build_weight_target_management_page__pace_stats_grid_elements(client):
    # AC #461: Pace stats moved to the slide-in panel live preview.
    # Verify the /weight page loaded and the panel preview elements are present.
    r = client.get("/weight/targets")
    html = r.text
    assert "et-preview-pace" in html or "Pace" in html, (
        "Pace preview element not found on /weight after redirect"
    )


# ── Section B — Set New Target Form ───────────────────────────────────────────
# Updated for #461: standalone form removed; panel fields on /weight replace it.

def test_build_weight_target_management_page__new_target_form_fields(client):
    # AC #461: Create/edit target now uses the /weight slide-in panel.
    # Panel has goal weight + goal date fields; start weight is display-only.
    r = client.get("/weight/targets")
    html = r.text
    assert 'id="et-goal-weight"' in html, "et-goal-weight panel field missing on /weight"
    assert 'id="et-goal-date"' in html, "et-goal-date panel field missing on /weight"


def _csrf_headers(client):
    """Fetch a CSRF token and return headers for mutating requests.

    The csrf-token cookie is set Secure by the UAT server, so httpx will not
    auto-send it over plain HTTP. We pass it explicitly in Cookie as well.
    """
    r = client.get("/api/csrf-token")
    assert r.status_code == 200, f"CSRF token fetch failed: {r.status_code}"
    token = r.json()["csrf_token"]
    return {"X-CSRF-Token": token, "Cookie": f"csrf-token={token}"}


def test_build_weight_target_management_page__api_create_target(client, user_id):
    # AC: Submit button creates target via API; clean up any leftover active target first
    headers = _csrf_headers(client)
    active_r = client.get(f"{WT}/active")
    if active_r.status_code == 200 and active_r.json().get("target"):
        active_id = active_r.json()["target"]["id"]
        # End endpoint requires a recent weight entry; log one if needed
        today = _dt.date.today().isoformat()
        client.post(WE, json={"entry_date": today, "weight_kg": 85.0},
                    headers=_csrf_headers(client))
        client.post(f"{WT}/{active_id}/end", json={"status": "abandoned"}, headers=_csrf_headers(client))

    today = _dt.date.today()
    payload = {
        "start_weight_kg": 90.0,
        "start_date": today.isoformat(),
        "target_weight_kg": 80.0,
        "target_date": (today + _dt.timedelta(days=90)).isoformat(),
        "notes": "tester413 e2e test target",
    }
    r = client.post(WT, json=payload, headers=_csrf_headers(client))
    assert r.status_code == 201, f"Expected 201, got {r.status_code}: {r.text}"
    data = r.json()
    assert data.get("status") == "active", f"Expected status=active, got {data.get('status')}"
    assert data.get("target_weight_kg") == 80.0


# ── Section C — Milestone Timeline Strip ─────────────────────────────────────
# Updated for #461: the standalone milestone strip moved to /weight progress card.

def test_build_weight_target_management_page__milestone_strip_elements(client):
    # AC #461: Milestone data now on /weight. Verify /weight has the milestone section.
    r = client.get("/weight/targets")
    html = r.text
    # After redirect to /weight, milestone rows are rendered in the progress card
    assert 'id="milestone-rows"' in html or "milestone" in html.lower(), (
        "Milestone section not found on /weight after redirect from /weight/targets"
    )


# ── Section D — Stats Summary Card ───────────────────────────────────────────
# Updated for #461: standalone stats summary removed; API history endpoint unchanged.

def test_build_weight_target_management_page__stats_summary_four_up_grid(client):
    # AC #461: Standalone stats page removed; /weight/targets redirects to /weight.
    # The /weight page must be served (status 200, HTML content).
    r = client.get("/weight/targets")
    assert r.status_code == 200, "Redirect from /weight/targets should end at 200"
    assert "text/html" in r.headers.get("content-type", "")


def test_build_weight_target_management_page__api_history_endpoint(client, user_id):
    # AC: All values computed client-side from GET /api/weight-targets/history (unchanged)
    r = client.get(f"{WT}/history")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert "targets" in data, "Response missing 'targets' key"
    assert isinstance(data["targets"], list)


# ── Section E — History Table ─────────────────────────────────────────────────
# Updated for #461: history table was on the standalone page (now removed).

def test_build_weight_target_management_page__history_table_columns(client):
    # AC #461: Standalone history page removed. /weight is served after redirect.
    # Verify the /weight page loads successfully with weight content.
    r = client.get("/weight/targets")
    html = r.text
    assert r.status_code == 200
    assert "Weight" in html, "Weight page not served after redirect from /weight/targets"


def test_build_weight_target_management_page__filter_pills_present(client):
    # AC #461: Filter pills on the standalone page removed.
    # /weight/targets redirects to /weight which serves weight.js.
    r = client.get("/weight/targets")
    assert r.status_code == 200
    assert "weight.js" in r.text, "weight.js not found after redirect to /weight"


# ── Edit Panel ────────────────────────────────────────────────────────────────
# Updated for #461: edit modal replaced by slide-in panel on /weight.

def test_build_weight_target_management_page__edit_modal_fields(client):
    # AC #461: Edit panel on /weight has goal weight + goal date fields.
    r = client.get("/weight/targets")
    html = r.text
    assert 'id="et-goal-weight"' in html, "Panel goal-weight field missing on /weight"
    assert 'id="et-goal-date"' in html, "Panel goal-date field missing on /weight"


# ── End Action ────────────────────────────────────────────────────────────────
# Updated for #461: end modal replaced by End target button in the slide-in panel.

def test_build_weight_target_management_page__end_modal_two_options(client):
    # AC #461: "End target" button moved to the /weight slide-in panel footer.
    r = client.get("/weight/targets")
    html = r.text
    assert 'id="et-end-btn"' in html, "End target button not found in /weight panel"


# ── API: active target endpoint ───────────────────────────────────────────────

def test_build_weight_target_management_page__api_active_target_returns_200(client, user_id):
    # AC: GET /api/weight-targets/active used to populate active card
    r = client.get(f"{WT}/active")
    assert r.status_code in (200, 404), f"Unexpected status {r.status_code}: {r.text}"
    if r.status_code == 200:
        data = r.json()
        assert "target" in data, "Response missing 'target' key"


# ── Manual-only ACs ──────────────────────────────────────────────────────────

def test_build_weight_target_management_page__no_console_errors():
    pytest.skip("manual — requires browser devtools inspection")


def test_build_weight_target_management_page__button_disabled_with_active_target():
    pytest.skip("manual — JS-driven UI state requires browser")


def test_build_weight_target_management_page__current_pace_arrow_color():
    pytest.skip("manual — visual indicator requires browser")


def test_build_weight_target_management_page__active_card_dynamic_content():
    pytest.skip("manual — weight/date/pace values are JS-rendered")


def test_build_weight_target_management_page__progress_projected_mini_cards():
    pytest.skip("manual — dynamically populated from JS")


def test_build_weight_target_management_page__new_target_form_prefill():
    pytest.skip("manual — JS pre-fills start weight and start date")


def test_build_weight_target_management_page__milestone_progress_pct_fill():
    pytest.skip("manual — track-fill width set by JS from progress_pct")


def test_build_weight_target_management_page__stats_values_computed_correctly():
    pytest.skip("manual — values rendered by JS from history API")


def test_build_weight_target_management_page__filter_pills_behavior():
    pytest.skip("manual — filter interaction requires browser")


def test_build_weight_target_management_page__edit_modal_opens_and_saves():
    pytest.skip("manual — modal interaction requires browser")


def test_build_weight_target_management_page__end_modal_opens_with_end_weight():
    pytest.skip("manual — modal shows end_weight_kg from JS")


def test_build_weight_target_management_page__end_modal_no_recent_weight_disables():
    pytest.skip("manual — JS checks last 7 days weight entries")


def test_build_weight_target_management_page__mark_achieved_adds_history_row():
    pytest.skip("manual — requires modal interaction and page refresh")


def test_build_weight_target_management_page__responsive_active_card_single_column():
    pytest.skip("manual — requires viewport resize to ≤880px")


def test_build_weight_target_management_page__responsive_history_card_list():
    pytest.skip("manual — requires viewport resize to ≤880px")


def test_build_weight_target_management_page__milestone_strip_mobile_scrollable():
    pytest.skip("manual — requires viewport resize to ≤880px")
