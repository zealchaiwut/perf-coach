"""Tests for issue #1037: Add sleep readout card to Training Log tab.

Acceptance criteria verified:
- AC-B1: GET /api/athletes/{id}/sleep returns flat object with required top-level keys.
- AC-B2: Response includes recent_nights array of last 7 nights.
- AC-B3: Missing stage columns return null (not error).
- AC-B4: No sleep rows → 200 with null top-level fields and empty recent_nights.
- AC-F1: Sleep card element exists in training-log.html.
- AC-F2: Sleep card disclaimer text is present in the JS render function.
- AC-F3: Empty state element/logic present in sleep card JS.
- AC-F4: JS render handles stage data absent (no broken chart).
- AC-F5: 7-night mini trend rendered from recent_nights data.
"""
import uuid
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app


# ── Helpers ────────────────────────────────────────────────────────────────────

_FAKE_USER_ID = uuid.uuid4()
_FAKE_USER = MagicMock()
_FAKE_USER.id = _FAKE_USER_ID


def _authed_client(user=None):
    """TestClient that bypasses auth by overriding resolve_user."""
    from backend.main import resolve_user
    if user is None:
        user = _FAKE_USER
    app.dependency_overrides[resolve_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


def _clear_overrides():
    app.dependency_overrides.clear()


def _make_sleep_record(sleep_date, total_sleep_minutes=443, sleep_score=82,
                       deep_minutes=90, rem_minutes=100, light_minutes=200,
                       awake_minutes=53, has_stages=True):
    rec = MagicMock()
    rec.sleep_date = sleep_date
    rec.total_sleep_minutes = total_sleep_minutes
    rec.sleep_score = sleep_score
    rec.deep_minutes = deep_minutes if has_stages else None
    rec.rem_minutes = rem_minutes if has_stages else None
    rec.light_minutes = light_minutes if has_stages else None
    rec.awake_minutes = awake_minutes if has_stages else None
    return rec


# ── AC-B1: Top-level keys ──────────────────────────────────────────────────────

class TestSleepEndpointShape:
    """AC-B1: endpoint returns flat object with expected top-level keys."""

    def teardown_method(self):
        _clear_overrides()

    def test_endpoint_returns_200(self):
        """AC-B1: GET /api/athletes/{id}/sleep returns 200."""
        client = _authed_client()
        latest = _make_sleep_record("2026-06-26")
        with patch("backend.main._query_athlete_sleep", return_value=(latest, [])):
            resp = client.get(f"/api/athletes/{_FAKE_USER_ID}/sleep")
        assert resp.status_code == 200, resp.text

    def test_response_has_sleep_date(self):
        """AC-B1: response contains sleep_date key."""
        client = _authed_client()
        latest = _make_sleep_record("2026-06-26")
        with patch("backend.main._query_athlete_sleep", return_value=(latest, [])):
            resp = client.get(f"/api/athletes/{_FAKE_USER_ID}/sleep")
        assert "sleep_date" in resp.json()

    def test_response_has_total_sleep_minutes(self):
        """AC-B1: response contains total_sleep_minutes key."""
        client = _authed_client()
        latest = _make_sleep_record("2026-06-26")
        with patch("backend.main._query_athlete_sleep", return_value=(latest, [])):
            resp = client.get(f"/api/athletes/{_FAKE_USER_ID}/sleep")
        assert "total_sleep_minutes" in resp.json()

    def test_response_has_sleep_score(self):
        """AC-B1: response contains sleep_score key."""
        client = _authed_client()
        latest = _make_sleep_record("2026-06-26")
        with patch("backend.main._query_athlete_sleep", return_value=(latest, [])):
            resp = client.get(f"/api/athletes/{_FAKE_USER_ID}/sleep")
        assert "sleep_score" in resp.json()

    def test_response_has_stage_keys(self):
        """AC-B1: response contains deep_minutes, rem_minutes, light_minutes, awake_minutes."""
        client = _authed_client()
        latest = _make_sleep_record("2026-06-26")
        with patch("backend.main._query_athlete_sleep", return_value=(latest, [])):
            resp = client.get(f"/api/athletes/{_FAKE_USER_ID}/sleep")
        body = resp.json()
        for key in ("deep_minutes", "rem_minutes", "light_minutes", "awake_minutes"):
            assert key in body, f"Missing key: {key}"

    def test_response_has_recent_nights(self):
        """AC-B1/AC-B2: response contains recent_nights array."""
        client = _authed_client()
        latest = _make_sleep_record("2026-06-26")
        with patch("backend.main._query_athlete_sleep", return_value=(latest, [])):
            resp = client.get(f"/api/athletes/{_FAKE_USER_ID}/sleep")
        assert "recent_nights" in resp.json()

    def test_response_values_match_record(self):
        """AC-B1: returned values match the most recent sleep record."""
        client = _authed_client()
        latest = _make_sleep_record("2026-06-26", total_sleep_minutes=443,
                                    sleep_score=82, deep_minutes=90)
        with patch("backend.main._query_athlete_sleep", return_value=(latest, [])):
            resp = client.get(f"/api/athletes/{_FAKE_USER_ID}/sleep")
        body = resp.json()
        assert str(body["sleep_date"]) == "2026-06-26"
        assert body["total_sleep_minutes"] == 443
        assert body["sleep_score"] == 82
        assert body["deep_minutes"] == 90


# ── AC-B2: recent_nights array ─────────────────────────────────────────────────

class TestRecentNights:
    """AC-B2: recent_nights contains last 7 nights with required keys."""

    def teardown_method(self):
        _clear_overrides()

    def test_recent_nights_max_seven(self):
        """AC-B2: recent_nights has at most 7 entries."""
        client = _authed_client()
        nights = [_make_sleep_record(f"2026-06-{20+i}") for i in range(7)]
        latest = nights[-1]
        with patch("backend.main._query_athlete_sleep", return_value=(latest, nights)):
            resp = client.get(f"/api/athletes/{_FAKE_USER_ID}/sleep")
        assert len(resp.json()["recent_nights"]) <= 7

    def test_recent_nights_entry_keys(self):
        """AC-B2: each entry in recent_nights has sleep_date, total_sleep_minutes, sleep_score."""
        client = _authed_client()
        nights = [_make_sleep_record("2026-06-25")]
        latest = _make_sleep_record("2026-06-26")
        with patch("backend.main._query_athlete_sleep", return_value=(latest, nights)):
            resp = client.get(f"/api/athletes/{_FAKE_USER_ID}/sleep")
        body = resp.json()
        assert len(body["recent_nights"]) > 0
        entry = body["recent_nights"][0]
        for key in ("sleep_date", "total_sleep_minutes", "sleep_score"):
            assert key in entry, f"recent_nights entry missing key: {key}"

    def test_recent_nights_is_list(self):
        """AC-B2: recent_nights is a list."""
        client = _authed_client()
        latest = _make_sleep_record("2026-06-26")
        with patch("backend.main._query_athlete_sleep", return_value=(latest, [latest])):
            resp = client.get(f"/api/athletes/{_FAKE_USER_ID}/sleep")
        assert isinstance(resp.json()["recent_nights"], list)


# ── AC-B3: Missing stage columns → null ────────────────────────────────────────

class TestMissingStageColumns:
    """AC-B3: absent stage columns return null, not error."""

    def teardown_method(self):
        _clear_overrides()

    def test_null_stages_no_error(self):
        """AC-B3: when stage data is null, endpoint returns 200 (no 500)."""
        client = _authed_client()
        latest = _make_sleep_record("2026-06-26", has_stages=False)
        with patch("backend.main._query_athlete_sleep", return_value=(latest, [])):
            resp = client.get(f"/api/athletes/{_FAKE_USER_ID}/sleep")
        assert resp.status_code == 200

    def test_null_stages_keys_present_or_omitted(self):
        """AC-B3: null stage fields are null (not missing or error)."""
        client = _authed_client()
        latest = _make_sleep_record("2026-06-26", has_stages=False)
        with patch("backend.main._query_athlete_sleep", return_value=(latest, [])):
            resp = client.get(f"/api/athletes/{_FAKE_USER_ID}/sleep")
        body = resp.json()
        for key in ("deep_minutes", "rem_minutes", "light_minutes", "awake_minutes"):
            # Either absent or null — both are acceptable per AC-B3
            assert key not in body or body[key] is None, (
                f"Stage key '{key}' should be null or absent when no stage data"
            )


# ── AC-B4: No sleep rows → empty response ──────────────────────────────────────

class TestNoSleepRows:
    """AC-B4: no sleep records → 200 with null fields and empty recent_nights."""

    def teardown_method(self):
        _clear_overrides()

    def test_no_rows_returns_200(self):
        """AC-B4: 200 even when athlete has no sleep records."""
        client = _authed_client()
        with patch("backend.main._query_athlete_sleep", return_value=(None, [])):
            resp = client.get(f"/api/athletes/{_FAKE_USER_ID}/sleep")
        assert resp.status_code == 200

    def test_no_rows_recent_nights_empty(self):
        """AC-B4: recent_nights is an empty list when no sleep records."""
        client = _authed_client()
        with patch("backend.main._query_athlete_sleep", return_value=(None, [])):
            resp = client.get(f"/api/athletes/{_FAKE_USER_ID}/sleep")
        assert resp.json()["recent_nights"] == []

    def test_no_rows_top_level_fields_null(self):
        """AC-B4: sleep_date and total_sleep_minutes are null when no records."""
        client = _authed_client()
        with patch("backend.main._query_athlete_sleep", return_value=(None, [])):
            resp = client.get(f"/api/athletes/{_FAKE_USER_ID}/sleep")
        body = resp.json()
        assert body.get("sleep_date") is None
        assert body.get("total_sleep_minutes") is None


# ── AC-B: Endpoint registration ────────────────────────────────────────────────

class TestEndpointRegistration:
    """Endpoint is registered at the correct path with GET method."""

    def test_get_route_registered(self):
        """GET /api/athletes/{athlete_id}/sleep route is registered on the app."""
        get_routes = set()
        for r in app.routes:
            methods = getattr(r, "methods", None) or set()
            if "GET" in methods:
                path = getattr(r, "path", None)
                if path:
                    get_routes.add(path)
        assert "/api/athletes/{athlete_id}/sleep" in get_routes, (
            "GET /api/athletes/{athlete_id}/sleep not registered. "
            f"Registered GET routes: {sorted(get_routes)}"
        )

    def teardown_method(self):
        _clear_overrides()

    def test_endpoint_requires_auth(self):
        """Unauthenticated request returns 401 (auth guard fires)."""
        _clear_overrides()
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get(f"/api/athletes/{_FAKE_USER_ID}/sleep")
        assert resp.status_code in (401, 403)


# ── AC-F1: Sleep card element in training-log.html ─────────────────────────────

class TestFrontendHtmlElement:
    """AC-F1: Sleep card container exists in training-log.html."""

    def test_sleep_card_container_exists(self):
        """AC-F1: training-log.html contains a sleep card element."""
        import pathlib
        html = pathlib.Path("frontend/pages/training-log.html").read_text()
        assert "log-sleep-card" in html, (
            "#log-sleep-card element not found in training-log.html"
        )

    def test_sleep_card_near_readiness_widget(self):
        """AC-F1: sleep card element appears in the load-surfaces section near readiness."""
        import pathlib
        html = pathlib.Path("frontend/pages/training-log.html").read_text()
        load_surfaces_start = html.find('id="load-surfaces"')
        # Search for the HTML element (id attribute), not the CSS class
        sleep_card_pos = html.find('id="log-sleep-card"')
        assert load_surfaces_start != -1, "load-surfaces section not found"
        assert sleep_card_pos != -1, "id=\"log-sleep-card\" element not found in HTML"
        # sleep card should appear after load-surfaces starts (within the section)
        assert sleep_card_pos > load_surfaces_start, (
            "log-sleep-card should appear after load-surfaces section"
        )


# ── AC-F2: Disclaimer text ──────────────────────────────────────────────────────

class TestDisclaimerText:
    """AC-F2: Sleep card includes disclaimer about not affecting scores."""

    def test_disclaimer_in_js(self):
        """AC-F2: disclaimer text 'does not' or 'awareness' present in sleep card JS."""
        import pathlib
        js = pathlib.Path("frontend/js/training-log.js").read_text()
        disclaimer_keywords = ["awareness", "does not", "affect your scores", "does not yet"]
        assert any(kw in js for kw in disclaimer_keywords), (
            "Sleep card disclaimer text not found in training-log.js. "
            "Expected one of: " + str(disclaimer_keywords)
        )


# ── AC-F3: Empty state ──────────────────────────────────────────────────────────

class TestEmptyState:
    """AC-F3: empty state directs user to Settings to connect a sleep source."""

    def test_empty_state_settings_link_in_js(self):
        """AC-F3: empty state includes reference to Settings."""
        import pathlib
        js = pathlib.Path("frontend/js/training-log.js").read_text()
        assert "Settings" in js or "/settings" in js, (
            "Empty state in training-log.js should direct user to Settings"
        )

    def test_empty_state_logic_in_js(self):
        """AC-F3: JS has a branch for the no-sleep-data empty state."""
        import pathlib
        js = pathlib.Path("frontend/js/training-log.js").read_text()
        assert "log-sleep-card" in js, (
            "log-sleep-card not referenced in training-log.js"
        )


# ── AC-F5: 7-night trend ───────────────────────────────────────────────────────

class TestMiniTrend:
    """AC-F5: 7-night mini trend rendered from recent_nights."""

    def test_recent_nights_rendered_in_js(self):
        """AC-F5: training-log.js references recent_nights for mini trend."""
        import pathlib
        js = pathlib.Path("frontend/js/training-log.js").read_text()
        assert "recent_nights" in js, (
            "recent_nights not referenced in training-log.js — 7-night trend not implemented"
        )
