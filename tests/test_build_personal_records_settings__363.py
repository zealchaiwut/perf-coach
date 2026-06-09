"""TDD tests for issue #363: Build Personal Records section in settings page.

AC items covered (static HTML analysis + live API):
  AC1  — section-personal-records div exists in settings.html
  AC2  — table columns: Track / Current best / Achieved on / Trend / Actions
  AC4  — "Add a record" button/CTA present
  AC5  — track_key dropdown populated from /api/personal-records/tracks
  AC6  — "Other (custom)" option exists in track dropdown
  AC9  — source dropdown contains Manual / Race / Test / Other
  AC10 — optional notes field present
  AC11 — POST /api/personal-records creates record; visible in GET list
  AC12 — Edit (pencil) and History icons present in actions HTML
  AC14 — DELETE /api/personal-records/{id} removes record
  AC15 — GET /api/personal-records/history returns correct structure
  AC17 — empty state copy is exact
  AC18 — home.js PR widget links to /settings#personal-records

Browser-only ACs skipped (need DevTools/Selenium):
  AC3, AC7, AC8 (frontend validation), AC13 (edit pre-fill),
  AC16 (oldest-first modal), AC19 (no console errors)

Prerequisites: tester363 user must exist in UAT DB with password "Test363pass!".
"""
import os
from pathlib import Path

import httpx
import pytest

BASE_URL = os.environ.get("UAT_BASE_URL", "http://localhost:9001")
_CREDENTIALS = {"username": "tester363", "password": "Test363pass!"}

_HOME_JS = Path(__file__).parent.parent / "frontend" / "js" / "home.js"
_SETTINGS_HTML = Path(__file__).parent.parent / "frontend" / "pages" / "settings.html"


# ── Auth helpers ──────────────────────────────────────────────────────────────

def _login():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        r = c.post("/api/auth/login", json=_CREDENTIALS)
        assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
        session = c.cookies.get("session", "")
        csrf = ""
        for sc in r.headers.get_list("set-cookie"):
            if sc.startswith("csrf-token="):
                csrf = sc.split("=", 1)[1].split(";")[0]
                break
        assert session and csrf, f"Missing cookies after login: session={bool(session)}, csrf={bool(csrf)}"
        return session, csrf


class _AuthedClient:
    def __init__(self, base_url, session, csrf):
        self._session = session
        self._csrf = csrf
        self._cookie_header = f"session={session}; csrf-token={csrf}"
        self._client = httpx.Client(base_url=base_url, timeout=10.0)

    def _headers(self, extra=None):
        h = {"Cookie": self._cookie_header, "X-CSRF-Token": self._csrf}
        if extra:
            h.update(extra)
        return h

    def get(self, url, **kw):
        kw.setdefault("headers", {})
        kw["headers"].update({"Cookie": self._cookie_header})
        return self._client.get(url, **kw)

    def post(self, url, **kw):
        kw.setdefault("headers", {})
        kw["headers"].update(self._headers({"Content-Type": "application/json"}))
        return self._client.post(url, **kw)

    def patch(self, url, **kw):
        kw.setdefault("headers", {})
        kw["headers"].update(self._headers({"Content-Type": "application/json"}))
        return self._client.patch(url, **kw)

    def delete(self, url, **kw):
        kw.setdefault("headers", {})
        kw["headers"].update(self._headers())
        return self._client.delete(url, **kw)

    def close(self):
        self._client.close()


@pytest.fixture(scope="module")
def authed_client():
    session, csrf = _login()
    c = _AuthedClient(BASE_URL, session, csrf)
    yield c
    c.close()


@pytest.fixture(scope="module")
def user_id(authed_client):
    r = authed_client.get("/api/auth/me")
    assert r.status_code == 200, f"auth/me failed: {r.status_code}"
    return r.json()["id"]


@pytest.fixture(scope="module")
def settings_html(authed_client):
    r = authed_client.get("/settings")
    assert r.status_code == 200
    return r.text


# ── AC1: section div exists ───────────────────────────────────────────────────

def test_pr_section_div_exists(settings_html):
    # AC1: Personal Records section div with correct id exists in settings.html
    assert 'id="section-personal-records"' in settings_html, \
        "section-personal-records div missing from settings.html"


def test_pr_section_nav_item_exists(settings_html):
    # AC1: nav item with data-section="personal-records" is present
    assert 'data-section="personal-records"' in settings_html, \
        "Personal Records nav item missing"


# ── AC2: table columns ────────────────────────────────────────────────────────

def test_pr_table_column_track(settings_html):
    assert ">Track<" in settings_html or ">Track</th>" in settings_html or \
        "Track" in settings_html, "Table column 'Track' missing"


def test_pr_table_column_current_best(settings_html):
    assert "Current best" in settings_html, "Table column 'Current best' missing"


def test_pr_table_column_achieved_on(settings_html):
    assert "Achieved on" in settings_html, "Table column 'Achieved on' missing"


def test_pr_table_column_trend(settings_html):
    assert "Trend" in settings_html, "Table column 'Trend' missing"


def test_pr_table_column_actions(settings_html):
    assert "Actions" in settings_html, "Table column 'Actions' missing"


# ── AC4: "Add a record" button ────────────────────────────────────────────────

def test_pr_add_button_present(settings_html):
    # AC4: "Add a record" button appears above the table
    assert "Add a record" in settings_html, \
        "'Add a record' button/CTA missing from settings.html"


def test_pr_add_button_has_id(settings_html):
    assert 'id="pr-add-btn"' in settings_html, "pr-add-btn element missing"


# ── AC5: tracks dropdown ──────────────────────────────────────────────────────

def test_pr_track_select_present(settings_html):
    # AC5: track dropdown element exists to be populated from /api/personal-records/tracks
    assert 'id="pr-track-select"' in settings_html, "pr-track-select dropdown missing"


def test_tracks_api_returns_track_name(authed_client):
    # AC5: GET /api/personal-records/tracks returns tracks with track_name
    r = authed_client.get("/api/personal-records/tracks")
    assert r.status_code == 200
    data = r.json()
    assert "tracks" in data
    for t in data["tracks"]:
        assert "track_name" in t, f"track_name missing in track {t}"


# ── AC6: "Other (custom)" option ──────────────────────────────────────────────

def test_pr_other_custom_option_present(settings_html):
    # AC6: "Other (custom)" option exists in track dropdown
    assert "Other (custom)" in settings_html, \
        "'Other (custom)' option missing from track dropdown"


def test_pr_custom_track_key_input_present(settings_html):
    # AC6: custom track_key text input exists (hidden until Other selected)
    assert 'id="pr-custom-track-key"' in settings_html, \
        "Custom track key input missing"


# ── AC8: future date input ────────────────────────────────────────────────────

def test_pr_achieved_on_input_present(settings_html):
    # AC8: achieved_on date input exists in the form
    assert 'id="pr-achieved-on"' in settings_html, "pr-achieved-on date input missing"


# ── AC9: source dropdown options ──────────────────────────────────────────────

def test_pr_source_option_manual(settings_html):
    assert ">Manual<" in settings_html or "Manual</option>" in settings_html or \
        'value="Manual"' in settings_html, "Source option 'Manual' missing"


def test_pr_source_option_race(settings_html):
    assert ">Race<" in settings_html or "Race</option>" in settings_html or \
        'value="Race"' in settings_html, "Source option 'Race' missing"


def test_pr_source_option_test(settings_html):
    assert ">Test<" in settings_html or "Test</option>" in settings_html or \
        'value="Test"' in settings_html, "Source option 'Test' missing"


def test_pr_source_option_other(settings_html):
    assert ">Other<" in settings_html or "Other</option>" in settings_html or \
        'value="Other"' in settings_html, "Source option 'Other' missing"


# ── AC10: notes field ─────────────────────────────────────────────────────────

def test_pr_notes_field_present(settings_html):
    # AC10: optional notes field present in form
    assert 'id="pr-notes"' in settings_html, \
        "Notes field (id=pr-notes) missing from Personal Records form"


# ── AC11: POST creates record + visible in GET ────────────────────────────────

def test_pr_create_record_returns_201(authed_client, user_id):
    # AC11: POST /api/personal-records creates record
    payload = {
        "user_id": user_id,
        "track_key": "test_363_squat",
        "track_name": "Test 363 Squat",
        "track_type": "weight",
        "value_numeric": 80.0,
        "achieved_on": "2026-01-15",
        "source": "Test",
    }
    r = authed_client.post("/api/personal-records", json=payload)
    assert r.status_code == 201, f"POST failed: {r.status_code} {r.text}"
    body = r.json()
    assert body["track_key"] == "test_363_squat"
    assert body["id"]
    # Cleanup
    authed_client.delete(f"/api/personal-records/{body['id']}")


def test_pr_created_record_in_get_list(authed_client, user_id):
    # AC11: created record appears in GET /api/personal-records list
    payload = {
        "user_id": user_id,
        "track_key": "test_363_halfm",
        "track_name": "Test 363 Half Marathon",
        "track_type": "time",
        "value_numeric": 5400.0,
        "achieved_on": "2026-02-01",
        "source": "Race",
    }
    r = authed_client.post("/api/personal-records", json=payload)
    assert r.status_code == 201
    rec_id = r.json()["id"]

    list_r = authed_client.get("/api/personal-records")
    assert list_r.status_code == 200
    ids = [rec["id"] for rec in list_r.json()]
    assert rec_id in ids, "Created record not found in GET list"

    authed_client.delete(f"/api/personal-records/{rec_id}")


# ── AC12: Edit + History icons in HTML ────────────────────────────────────────

def test_pr_edit_btn_class_present(settings_html):
    # AC12: edit (pencil) button class exists in HTML
    assert "pr-edit-btn" in settings_html, "pr-edit-btn class missing from actions cell HTML"


def test_pr_history_btn_class_present(settings_html):
    # AC12: history icon button class exists in HTML
    assert "pr-history-btn" in settings_html, "pr-history-btn class missing from actions cell HTML"


# ── AC14: DELETE removes record ───────────────────────────────────────────────

def test_pr_delete_removes_record(authed_client, user_id):
    # AC14: DELETE removes record; table refresh shows it gone
    payload = {
        "user_id": user_id,
        "track_key": "test_363_delete",
        "track_name": "Test 363 Delete",
        "track_type": "weight",
        "value_numeric": 50.0,
        "achieved_on": "2026-01-10",
        "source": "Manual",
    }
    r = authed_client.post("/api/personal-records", json=payload)
    assert r.status_code == 201
    rec_id = r.json()["id"]

    del_r = authed_client.delete(f"/api/personal-records/{rec_id}")
    assert del_r.status_code == 204

    list_r = authed_client.get("/api/personal-records")
    ids = [rec["id"] for rec in list_r.json()]
    assert rec_id not in ids, "Deleted record still appears in GET list"


# ── AC15: history endpoint ────────────────────────────────────────────────────

def test_pr_history_endpoint_returns_correct_structure(authed_client, user_id):
    # AC15: GET /api/personal-records/history returns track_key + history list
    # Insert two records for the same track to test improvement_from_prev
    p1 = {
        "user_id": user_id, "track_key": "test_363_hist", "track_name": "Test 363 Hist",
        "track_type": "weight", "value_numeric": 100.0, "achieved_on": "2026-01-01", "source": "Test",
    }
    p2 = {
        "user_id": user_id, "track_key": "test_363_hist", "track_name": "Test 363 Hist",
        "track_type": "weight", "value_numeric": 110.0, "achieved_on": "2026-03-01", "source": "Test",
    }
    r1 = authed_client.post("/api/personal-records", json=p1)
    r2 = authed_client.post("/api/personal-records", json=p2)
    assert r1.status_code == 201
    assert r2.status_code == 201
    id1, id2 = r1.json()["id"], r2.json()["id"]

    hist_r = authed_client.get(
        "/api/personal-records/history",
        params={"user_id": user_id, "track_key": "test_363_hist"},
    )
    assert hist_r.status_code == 200
    body = hist_r.json()
    assert body["track_key"] == "test_363_hist"
    assert len(body["history"]) >= 2
    for entry in body["history"]:
        assert "value_formatted" in entry
        assert "achieved_on" in entry
        assert "improvement_from_prev" in entry

    authed_client.delete(f"/api/personal-records/{id1}")
    authed_client.delete(f"/api/personal-records/{id2}")


# ── AC17: empty state copy ────────────────────────────────────────────────────

def test_pr_empty_state_copy(settings_html):
    # AC17: exact empty state copy matches spec
    expected = "Set your personal records to track progress over time"
    assert expected in settings_html, \
        f"Empty state copy missing: '{expected}'"


def test_pr_empty_state_cta_present(settings_html):
    # AC17: prominent "Add a record" CTA in empty state
    assert 'id="pr-empty-add-btn"' in settings_html, \
        "Empty state CTA button (id=pr-empty-add-btn) missing"


def test_pr_empty_state_onboarding_copy(settings_html):
    # AC17: onboarding copy mentions half marathon + 10K + lifts
    assert "half marathon" in settings_html.lower() or "1RM" in settings_html, \
        "Empty state onboarding copy missing half marathon / 1RM mention"


# ── AC18: home.js PR widget link ──────────────────────────────────────────────

def test_pr_widget_link_points_to_settings_anchor():
    # AC18: PR widget "All tracks" link in home.js points to /settings#personal-records
    js = _HOME_JS.read_text(encoding="utf-8")
    assert "/settings#personal-records" in js, \
        "home.js PR widget does not link to /settings#personal-records"


# ── browser-only ACs (skipped) ────────────────────────────────────────────────

def test_pr_value_input_adapts_for_time_tracks():
    pytest.skip("manual — value input type adaptation requires browser JS execution")


def test_pr_future_date_blocked_by_client():
    pytest.skip("manual — client-side date validation requires browser test")


def test_pr_edit_form_pre_filled():
    pytest.skip("manual — edit pre-fill requires browser interaction")


def test_pr_history_modal_shows_oldest_first():
    pytest.skip("manual — history modal order requires browser test")


def test_pr_no_console_errors():
    pytest.skip("manual — requires browser DevTools console inspection")
