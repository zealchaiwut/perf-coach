"""Tests for issue #413: Build weight target management page (/weight/targets) (runs against UAT)

Risk: MEDIUM — new frontend page with multiple UI sections, no auth/security/destructive changes.
→ 1-2 tests per criterion where HTTP-testable; visual/JS-driven ACs marked manual.

Prerequisites: tester413 user must exist in UAT DB with password "Test413pass!".
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

def test_build_weight_target_management_page__route_returns_200(client):
    # AC: Route /weight/targets registered; returns weight-targets.html
    r = client.get("/weight/targets")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}"
    assert "text/html" in r.headers.get("content-type", ""), "Response is not HTML"


def test_build_weight_target_management_page__weight_targets_js_loaded(client):
    # AC: Logic lives in frontend/js/weight-targets.js
    r = client.get("/weight/targets")
    assert r.status_code == 200
    assert "weight-targets.js" in r.text, "weight-targets.js script tag missing from page"


# ── Section A — Header ────────────────────────────────────────────────────────

def test_build_weight_target_management_page__breadcrumb_and_title(client):
    # AC: Breadcrumb renders with back link to /weight and page title "Weight targets"
    r = client.get("/weight/targets")
    html = r.text
    assert 'href="/weight"' in html, "Breadcrumb link to /weight missing"
    assert "Weight targets" in html, "Page title 'Weight targets' missing"


def test_build_weight_target_management_page__set_new_target_button_present(client):
    # AC: "Set new target" button appears in header right
    r = client.get("/weight/targets")
    assert "Set new target" in r.text, "'Set new target' button text missing"


def test_build_weight_target_management_page__disabled_button_tooltip(client):
    # AC: Disabled button shows tooltip "End or replace the current target first"
    r = client.get("/weight/targets")
    assert "End or replace the current target first" in r.text, "Tooltip text missing"


# ── Section B — Active Target Card (static HTML elements) ────────────────────

def test_build_weight_target_management_page__active_target_banner(client):
    # AC: Banner pill reads "ACTIVE TARGET"
    r = client.get("/weight/targets")
    assert "ACTIVE TARGET" in r.text, "'ACTIVE TARGET' banner text missing"


def test_build_weight_target_management_page__active_card_edit_end_buttons(client):
    # AC: Card header includes edit (pencil) icon button and end (X) icon button
    r = client.get("/weight/targets")
    html = r.text
    assert 'id="edit-target-btn"' in html, "Edit target button missing"
    assert 'id="end-target-btn"' in html, "End target button missing"


def test_build_weight_target_management_page__pace_stats_grid_elements(client):
    # AC: 3-up pace stats grid shows Remaining kg, Pace needed kg/wk, Your current pace kg/wk
    r = client.get("/weight/targets")
    html = r.text
    assert "Remaining" in html, "Remaining kg stat label missing"
    assert "Pace needed" in html, "Pace needed stat label missing"
    assert "current pace" in html.lower(), "Current pace stat label missing"


# ── Section B — Set New Target Form (static HTML elements) ───────────────────

def test_build_weight_target_management_page__new_target_form_fields(client):
    # AC: Fields: start weight, start date, target weight, target date, notes
    r = client.get("/weight/targets")
    html = r.text
    assert 'id="form-start-weight"' in html, "form-start-weight field missing"
    assert 'id="form-start-date"' in html, "form-start-date field missing"
    assert 'id="form-target-weight"' in html, "form-target-weight field missing"
    assert 'id="form-target-date"' in html, "form-target-date field missing"
    assert 'id="form-notes"' in html, "form-notes field missing"


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
    active_r = client.get(f"{WT}/active", params={"user_id": user_id})
    if active_r.status_code == 200 and active_r.json().get("target"):
        active_id = active_r.json()["target"]["id"]
        # End endpoint requires a recent weight entry; log one if needed
        today = _dt.date.today().isoformat()
        client.post(WE, json={"user_id": user_id, "entry_date": today, "weight_kg": 85.0},
                    headers=_csrf_headers(client))
        client.post(f"{WT}/{active_id}/end", json={"status": "abandoned"}, headers=_csrf_headers(client))

    today = _dt.date.today()
    payload = {
        "user_id": user_id,
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

def test_build_weight_target_management_page__milestone_strip_elements(client):
    # AC: Horizontal rail with labeled points and gradient fill
    r = client.get("/weight/targets")
    html = r.text
    assert 'id="milestone-rail"' in html, "milestone-rail element missing"
    assert 'id="milestone-track-fill"' in html, "milestone-track-fill element missing"
    assert "milestone-strip" in html, "milestone-strip container missing"


# ── Section D — Stats Summary Card ───────────────────────────────────────────

def test_build_weight_target_management_page__stats_summary_four_up_grid(client):
    # AC: 4-up grid shows Targets set, Targets achieved, Total weight lost, Avg pace kg/wk
    r = client.get("/weight/targets")
    html = r.text
    assert "Targets set" in html, "'Targets set' stat label missing"
    assert "Targets achieved" in html, "'Targets achieved' stat label missing"
    assert "Total weight lost" in html, "'Total weight lost' stat label missing"
    assert "Avg pace" in html, "'Avg pace' stat label missing"


def test_build_weight_target_management_page__api_history_endpoint(client, user_id):
    # AC: All values computed client-side from GET /api/weight-targets/history
    r = client.get(f"{WT}/history", params={"user_id": user_id})
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    data = r.json()
    assert "targets" in data, "Response missing 'targets' key"
    assert isinstance(data["targets"], list)


# ── Section E — History Table ─────────────────────────────────────────────────

def test_build_weight_target_management_page__history_table_columns(client):
    # AC: Columns: Status, Name, Pace kg/wk, Result weight, Delta, Duration days, Actions
    r = client.get("/weight/targets")
    html = r.text
    for col in ("Status", "Name", "Pace kg/wk", "Result weight", "Delta", "Duration days", "Actions"):
        assert col in html, f"History table column '{col}' missing"


def test_build_weight_target_management_page__filter_pills_present(client):
    # AC: Filter pills at top: All / Achieved / Replaced / Abandoned
    r = client.get("/weight/targets")
    html = r.text
    for label in ("All", "Achieved", "Replaced", "Abandoned"):
        assert f'data-filter="{label.lower()}"' in html, f"Filter pill '{label}' missing"


# ── Edit Modal ────────────────────────────────────────────────────────────────

def test_build_weight_target_management_page__edit_modal_fields(client):
    # AC: Edit modal editable fields: target_weight, target_date, notes
    r = client.get("/weight/targets")
    html = r.text
    assert 'id="edit-target-weight"' in html, "Edit modal target weight field missing"
    assert 'id="edit-target-date"' in html, "Edit modal target date field missing"
    assert 'id="edit-notes"' in html, "Edit modal notes field missing"


# ── End Modal ─────────────────────────────────────────────────────────────────

def test_build_weight_target_management_page__end_modal_two_options(client):
    # AC: End modal presents "Mark as achieved" / "Mark as abandoned"
    r = client.get("/weight/targets")
    html = r.text
    assert "Mark as achieved" in html, "'Mark as achieved' button text missing"
    assert "Mark as abandoned" in html, "'Mark as abandoned' button text missing"


# ── API: active target endpoint ───────────────────────────────────────────────

def test_build_weight_target_management_page__api_active_target_returns_200(client, user_id):
    # AC: GET /api/weight-targets/active used to populate active card
    r = client.get(f"{WT}/active", params={"user_id": user_id})
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
