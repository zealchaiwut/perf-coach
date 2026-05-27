"""
Tests for issue #40: Quick-entry row for today's metrics on home dashboard
Server under test: http://127.0.0.1:9001
"""
import datetime
import pathlib

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def alice_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    alice = next((u for u in res.json() if u["name"] == "Alice"), None)
    assert alice is not None, "Alice not found in /api/users"
    return alice["id"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _delete_today_metric(client, user_id):
    client.delete(f"/api/daily-metrics/{user_id}/{TODAY_STR}")


# ── AC-1: "Today's check-in" card structure in HTML ──────────────────────────

def test_ac1_checkin_section_exists_in_html():
    """home.html must have a section with id='section-checkin'."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="section-checkin"' in html, "Missing id='section-checkin' in home.html"


def test_ac1_checkin_section_title():
    """home.html must contain the heading 'Today's check-in'."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert "Today's check-in" in html, "Missing \"Today's check-in\" heading in home.html"


def test_ac1_checkin_between_stat_cards_and_weight():
    """The check-in section must appear between dash-cards and section-weight in the HTML."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    cards_pos = html.find('id="dash-cards"')
    checkin_pos = html.find('id="section-checkin"')
    weight_pos = html.find('id="section-weight"')
    assert cards_pos != -1 and checkin_pos != -1 and weight_pos != -1, \
        "dash-cards, section-checkin, and section-weight must all exist in home.html"
    assert cards_pos < checkin_pos < weight_pos, \
        "section-checkin must appear between dash-cards and section-weight"


def test_ac1_rhr_input_exists():
    """home.html must have an input for resting HR (id='checkin-rhr')."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="checkin-rhr"' in html, "Missing id='checkin-rhr' input in home.html"


def test_ac1_hrv_input_exists():
    """home.html must have an input for HRV (id='checkin-hrv')."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="checkin-hrv"' in html, "Missing id='checkin-hrv' input in home.html"


def test_ac1_sleep_hours_input_exists():
    """home.html must have an input for sleep hours (id='checkin-sleep')."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="checkin-sleep"' in html, "Missing id='checkin-sleep' input in home.html"


def test_ac1_notes_textarea_exists():
    """home.html must have a textarea for notes (id='checkin-notes')."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="checkin-notes"' in html, "Missing id='checkin-notes' textarea in home.html"


def test_ac1_save_button_exists():
    """home.html must have a save button (id='checkin-save')."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="checkin-save"' in html, "Missing id='checkin-save' button in home.html"


# ── AC-3: Pill selectors for sleep_quality, energy, mood ─────────────────────

def test_ac3_sleep_quality_pill_group_exists():
    """home.html must have a pill group for sleep quality (id='pills-sleep-quality')."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="pills-sleep-quality"' in html, \
        "Missing id='pills-sleep-quality' pill group in home.html"


def test_ac3_energy_pill_group_exists():
    """home.html must have a pill group for energy (id='pills-energy')."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="pills-energy"' in html, "Missing id='pills-energy' pill group in home.html"


def test_ac3_mood_pill_group_exists():
    """home.html must have a pill group for mood (id='pills-mood')."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="pills-mood"' in html, "Missing id='pills-mood' pill group in home.html"


def test_ac3_pill_buttons_1_to_5():
    """Each pill group must contain buttons for values 1 through 5."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    for val in range(1, 6):
        assert f'data-val="{val}"' in html, \
            f"Missing pill button with data-val='{val}' in home.html"


def test_ac3_pill_class_in_html():
    """Pill buttons must use the 'pill' CSS class."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'class="pill"' in html, "Missing class='pill' on pill buttons in home.html"


def test_ac3_pill_wire_up_function_in_js():
    """home.js must have a function to wire up pill group click handlers."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "wireUpPillGroups" in js or "pills-sleep-quality" in js, \
        "home.js must wire up pill group click handlers"


def test_ac3_pill_active_class_in_js():
    """home.js must toggle an 'active' class on pills to indicate selection."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "active" in js, "home.js must use an 'active' class for selected pills"


# ── AC-4: Save button calls PUT upsert endpoint ───────────────────────────────

def test_ac4_init_checkin_save_function_in_js():
    """home.js must have a function that wires up the save button."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "initCheckinSave" in js or "checkin-save" in js, \
        "home.js must wire up the checkin-save button"


def test_ac4_save_uses_put_method():
    """home.js must use PUT (upsert) when saving daily metrics."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    checkin_save_idx = js.find("initCheckinSave")
    assert checkin_save_idx != -1, "Missing initCheckinSave in home.js"
    save_body = js[checkin_save_idx:checkin_save_idx + 800]
    assert "'PUT'" in save_body or '"PUT"' in save_body, \
        "initCheckinSave must use method: 'PUT' for the upsert endpoint"


def test_ac4_save_targets_daily_metrics_endpoint():
    """home.js save must call /api/daily-metrics/{user_id}/{today}."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "/api/daily-metrics/" in js, \
        "home.js must call /api/daily-metrics/ endpoint when saving"


def test_ac4_put_upsert_creates_metric(client, alice_id):
    """PUT /api/daily-metrics/{user_id}/{today} must create a row when none exists."""
    _delete_today_metric(client, alice_id)

    res = client.put(
        f"/api/daily-metrics/{alice_id}/{TODAY_STR}",
        json={"resting_hr": 58, "sleep_hours": 7.5, "energy": 4},
    )
    assert res.status_code == 200, f"PUT upsert failed: {res.status_code} {res.text}"
    data = res.json()
    assert data["resting_hr"] == 58
    assert data["sleep_hours"] == 7.5
    assert data["energy"] == 4


def test_ac4_put_upsert_overwrites_existing(client, alice_id):
    """PUT /api/daily-metrics/{user_id}/{today} must update an existing row."""
    client.put(
        f"/api/daily-metrics/{alice_id}/{TODAY_STR}",
        json={"resting_hr": 58, "energy": 4},
    )
    res = client.put(
        f"/api/daily-metrics/{alice_id}/{TODAY_STR}",
        json={"resting_hr": 60, "energy": 3, "mood": 4},
    )
    assert res.status_code == 200, f"PUT upsert update failed: {res.status_code} {res.text}"
    data = res.json()
    assert data["resting_hr"] == 60
    assert data["energy"] == 3
    assert data["mood"] == 4


def test_ac4_null_fields_cleared_on_put(client, alice_id):
    """PUT with null notes must store null (clearing a previously set value)."""
    client.put(
        f"/api/daily-metrics/{alice_id}/{TODAY_STR}",
        json={"notes": "some notes"},
    )
    res = client.put(
        f"/api/daily-metrics/{alice_id}/{TODAY_STR}",
        json={"notes": None},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["notes"] is None, "PUT with notes=null must clear the notes field"


# ── AC-2: Pre-fill form from GET endpoint ─────────────────────────────────────

def test_ac2_load_checkin_section_function_in_js():
    """home.js must have a loadCheckinSection function."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "loadCheckinSection" in js, "Missing loadCheckinSection function in home.js"


def test_ac2_load_checkin_calls_get_endpoint():
    """home.js loadCheckinSection must call GET /api/daily-metrics/{user_id}/{today}."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    load_idx = js.find("loadCheckinSection")
    assert load_idx != -1
    load_body = js[load_idx:load_idx + 400]
    assert "/api/daily-metrics/" in load_body, \
        "loadCheckinSection must fetch from /api/daily-metrics/"


def test_ac2_get_returns_404_when_no_row(client, alice_id):
    """GET /api/daily-metrics/{user_id}/{today} returns 404 when no row exists."""
    _delete_today_metric(client, alice_id)
    res = client.get(f"/api/daily-metrics/{alice_id}/{TODAY_STR}")
    assert res.status_code == 404, \
        f"Expected 404 for missing metric, got {res.status_code}"


def test_ac2_get_returns_saved_values(client, alice_id):
    """GET /api/daily-metrics/{user_id}/{today} returns saved values after PUT."""
    client.put(
        f"/api/daily-metrics/{alice_id}/{TODAY_STR}",
        json={"resting_hr": 55, "sleep_hours": 7.5, "energy": 4, "notes": "good night"},
    )
    res = client.get(f"/api/daily-metrics/{alice_id}/{TODAY_STR}")
    assert res.status_code == 200
    data = res.json()
    assert data["resting_hr"] == 55
    assert data["sleep_hours"] == 7.5
    assert data["energy"] == 4
    assert data["notes"] == "good night"


def test_ac2_fill_checkin_form_function_in_js():
    """home.js must have a function that fills the form with retrieved data."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "fillCheckinForm" in js, "Missing fillCheckinForm function in home.js"


def test_ac2_checkin_loaded_on_user_ready():
    """home.js must call loadCheckinSection in the userReady / refreshSections flow."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    refresh_idx = js.find("refreshSections")
    assert refresh_idx != -1, "Missing refreshSections in home.js"
    refresh_body = js[refresh_idx:refresh_idx + 200]
    assert "loadCheckinSection" in refresh_body, \
        "refreshSections must call loadCheckinSection"


# ── AC-5: Save success indicator ──────────────────────────────────────────────

def test_ac5_saved_indicator_element_in_html():
    """home.html must have a 'checkin-saved' element for the success indicator."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="checkin-saved"' in html, "Missing id='checkin-saved' element in home.html"


def test_ac5_saved_at_text_in_js():
    """home.js must set 'Saved at HH:MM' text on successful save."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "Saved at" in js, "Missing 'Saved at' success indicator text in home.js"


def test_ac5_saved_indicator_clears_after_timeout():
    """home.js must use setTimeout to clear the 'Saved at' indicator after ~3 seconds."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "setTimeout" in js, "home.js must use setTimeout to clear the saved indicator"
    assert "3000" in js, "home.js must clear saved indicator after 3000ms"


# ── AC-6: Save error handling ─────────────────────────────────────────────────

def test_ac6_error_element_in_html():
    """home.html must have a 'checkin-error' element for inline error messages."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="checkin-error"' in html, "Missing id='checkin-error' element in home.html"


def test_ac6_error_handling_in_js():
    """home.js save must handle non-ok responses and set the error element."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "checkin-error" in js or "setCheckinStatus" in js, \
        "home.js must display inline errors on save failure"


def test_ac6_network_error_message_in_js():
    """home.js must show a network error message when fetch throws."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "Network error" in js or "network error" in js, \
        "home.js must handle fetch failure with a network error message"


def test_ac6_server_422_returns_detail(client, alice_id):
    """PUT with resting_hr=5 (below min 20) must return 422 with detail."""
    res = client.put(
        f"/api/daily-metrics/{alice_id}/{TODAY_STR}",
        json={"resting_hr": 5},
    )
    assert res.status_code == 422, \
        f"Expected 422 for resting_hr=5 (out of range), got {res.status_code}"
    data = res.json()
    assert "detail" in data, "422 response must include a 'detail' field"


# ── AC-7: Mobile-friendly inputs with validation ──────────────────────────────

def test_ac7_rhr_input_has_inputmode_numeric():
    """The resting HR input must have inputmode='numeric' for mobile keyboards."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'inputmode="numeric"' in html, \
        "home.html numeric inputs must have inputmode='numeric'"


def test_ac7_rhr_input_min_max():
    """The resting HR input must have min='20' and max='200'."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    # Check the checkin-rhr section contains min/max
    rhr_idx = html.find('id="checkin-rhr"')
    assert rhr_idx != -1
    rhr_snippet = html[max(0, rhr_idx - 50):rhr_idx + 200]
    assert 'min="20"' in rhr_snippet, "checkin-rhr input must have min='20'"
    assert 'max="200"' in rhr_snippet, "checkin-rhr input must have max='200'"


def test_ac7_hrv_input_min_max():
    """The HRV input must have min='0' and max='300'."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    hrv_idx = html.find('id="checkin-hrv"')
    assert hrv_idx != -1
    hrv_snippet = html[max(0, hrv_idx - 50):hrv_idx + 200]
    assert 'min="0"' in hrv_snippet, "checkin-hrv input must have min='0'"
    assert 'max="300"' in hrv_snippet, "checkin-hrv input must have max='300'"


def test_ac7_sleep_input_min_max():
    """The sleep hours input must have min='0' and max='24'."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    sleep_idx = html.find('id="checkin-sleep"')
    assert sleep_idx != -1
    sleep_snippet = html[max(0, sleep_idx - 50):sleep_idx + 200]
    assert 'min="0"' in sleep_snippet, "checkin-sleep input must have min='0'"
    assert 'max="24"' in sleep_snippet, "checkin-sleep input must have max='24'"


# ── AC-8: Collapsible card with localStorage ──────────────────────────────────

def test_ac8_toggle_button_in_html():
    """home.html must have a toggle button (id='checkin-toggle') to collapse the card."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="checkin-toggle"' in html, "Missing id='checkin-toggle' button in home.html"


def test_ac8_checkin_body_in_html():
    """home.html must have a collapsible body element (id='checkin-body')."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="checkin-body"' in html, "Missing id='checkin-body' element in home.html"


def test_ac8_collapse_uses_localstorage():
    """home.js must read/write localStorage to persist the collapsed state."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "localStorage" in js, "home.js must use localStorage for collapse state"
    assert "checkin-collapsed" in js or "CHECKIN_COLLAPSE_KEY" in js, \
        "home.js must use a localStorage key for the check-in collapsed state"


def test_ac8_init_checkin_toggle_function_in_js():
    """home.js must have a function that initialises the collapse toggle."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "initCheckinToggle" in js or "checkin-toggle" in js, \
        "home.js must initialise the checkin collapse toggle"


def test_ac8_collapsed_class_on_toggle():
    """home.js must add/remove a 'collapsed' class on the toggle button."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "collapsed" in js, "home.js must use a 'collapsed' class on the toggle button"


# ── AC-9: Mobile-responsive layout ────────────────────────────────────────────

def test_ac9_checkin_grid_has_media_query():
    """home.html must define a @media query that makes the checkin-grid 2-column on mobile."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert "checkin-grid" in html, "Missing .checkin-grid in home.html"
    assert "@media" in html, "home.html must have @media queries for responsive layout"


def test_ac9_pill_row_media_query_for_full_width():
    """home.html must have a @media rule that makes pill rows full-width on small screens."""
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert "checkin-pill-row" in html, "Missing .checkin-pill-row in home.html"


# ── Structural: checkin section refresh in JS wiring ─────────────────────────

def test_refresh_sections_calls_load_checkin():
    """home.js refreshSections must call loadCheckinSection."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    refresh_start = js.find("refreshSections")
    assert refresh_start != -1, "Missing refreshSections in home.js"
    refresh_body = js[refresh_start:refresh_start + 250]
    assert "loadCheckinSection" in refresh_body, \
        "refreshSections must call loadCheckinSection"


def test_checkin_user_id_set_on_user_ready():
    """home.js must capture the active userId when userReady fires (for save button)."""
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    # The module-level _checkinUserId variable is set in userReady handler
    assert "_checkinUserId" in js, \
        "home.js must maintain a module-level userId for the check-in save button"
