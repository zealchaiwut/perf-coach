"""Tests for issue #1036: Add Sleep via Health Sync card to Settings Integrations.

AC coverage:
  AC1 – GET /api/integrations/drive-sleep/status returns flat JSON with exactly:
         status, folder_id, last_sync_at, records_total
  AC2 – Settings Integrations section renders a card titled "Sleep via Health Sync"
  AC3 – Not-connected state: Connect button + hint about Health Sync exporting sleep data
  AC4 – Connected state: folder, last_sync_at, records_total, Sync Now button, Disconnect button
  AC5 – Card state driven solely by the `status` field from the status endpoint
  AC6 – Actions provide feedback (loading state, success, error)
"""
import time
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.auth import create_session_cookie, COOKIE_NAME, generate_csrf_token, CSRF_COOKIE_NAME
from backend.main import app, resolve_user

_USER_ID = "00000000-0000-0000-0000-000000001036"


def _mock_user(user_id=_USER_ID):
    u = MagicMock()
    u.id = user_id
    return u


def _make_client():
    mock_user = _mock_user()

    async def _fake_resolve_user():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve_user
    session_cookie = create_session_cookie(_USER_ID, time.time())
    csrf = generate_csrf_token()
    client = TestClient(
        app,
        cookies={COOKIE_NAME: session_cookie, CSRF_COOKIE_NAME: csrf},
        headers={"X-CSRF-Token": csrf},
    )
    return client, mock_user


def _teardown():
    app.dependency_overrides.pop(resolve_user, None)


# ── AC1: status endpoint returns flat JSON with exactly the right keys ─────────

def test_drive_sleep_status_not_connected_keys():
    """Status endpoint returns exactly status, folder_id, last_sync_at, records_total."""
    client, _ = _make_client()
    try:
        with patch("backend.main.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

            # No DriveSleepConnection row
            mock_query = MagicMock()
            mock_query.filter.return_value.one_or_none.return_value = None
            mock_query.filter.return_value.count.return_value = 0
            mock_session.query.return_value = mock_query

            resp = client.get("/api/integrations/drive-sleep/status")
            assert resp.status_code == 200
            data = resp.json()
            assert set(data.keys()) == {"status", "folder_id", "last_sync_at", "records_total"}, (
                f"Expected exactly status/folder_id/last_sync_at/records_total, got {set(data.keys())}"
            )
    finally:
        _teardown()


def test_drive_sleep_status_not_connected_values():
    """When not connected, status=not_connected, folder_id=null, last_sync_at=null, records_total=0."""
    client, _ = _make_client()
    try:
        with patch("backend.main.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

            mock_query = MagicMock()
            mock_query.filter.return_value.one_or_none.return_value = None
            mock_query.filter.return_value.count.return_value = 0
            mock_session.query.return_value = mock_query

            resp = client.get("/api/integrations/drive-sleep/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "not_connected"
            assert data["folder_id"] is None
            assert data["last_sync_at"] is None
            assert data["records_total"] == 0
    finally:
        _teardown()


def test_drive_sleep_status_connected_values():
    """When connected, returns populated status, folder_id, last_sync_at, records_total."""
    from datetime import datetime, timezone

    client, _ = _make_client()
    try:
        with patch("backend.main.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

            conn_row = MagicMock()
            conn_row.status = "connected"
            conn_row.folder_id = "1AbCdEfGhIjKlMnOpQrStUvWxYz12345"
            conn_row.last_sync_at = datetime(2026, 6, 27, 10, 0, 0, tzinfo=timezone.utc)

            call_count = [0]

            def _query_side_effect(model):
                call_count[0] += 1
                mock_q = MagicMock()
                if hasattr(model, "__tablename__") and model.__tablename__ == "sleep_records":
                    mock_q.filter.return_value.count.return_value = 42
                else:
                    mock_q.filter.return_value.one_or_none.return_value = conn_row
                return mock_q

            mock_session.query.side_effect = _query_side_effect

            resp = client.get("/api/integrations/drive-sleep/status")
            assert resp.status_code == 200
            data = resp.json()
            assert data["status"] == "connected"
            assert data["folder_id"] == "1AbCdEfGhIjKlMnOpQrStUvWxYz12345"
            assert data["last_sync_at"] is not None
            assert "2026-06-27" in data["last_sync_at"]
            assert data["records_total"] == 42
    finally:
        _teardown()


def test_drive_sleep_status_requires_auth():
    """Status endpoint returns 401 when not authenticated."""
    client = TestClient(app)
    resp = client.get("/api/integrations/drive-sleep/status")
    assert resp.status_code == 401


def test_drive_sleep_status_no_extra_keys():
    """Response must be a flat object with exactly 4 keys — no extras."""
    client, _ = _make_client()
    try:
        with patch("backend.main.Session") as mock_session_cls:
            mock_session = MagicMock()
            mock_session_cls.return_value.__enter__ = MagicMock(return_value=mock_session)
            mock_session_cls.return_value.__exit__ = MagicMock(return_value=False)

            mock_query = MagicMock()
            mock_query.filter.return_value.one_or_none.return_value = None
            mock_query.filter.return_value.count.return_value = 5
            mock_session.query.return_value = mock_query

            resp = client.get("/api/integrations/drive-sleep/status")
            data = resp.json()
            assert len(data) == 4, f"Expected exactly 4 keys, got {len(data)}: {list(data.keys())}"
    finally:
        _teardown()


# ── AC2: Settings page has a card titled "Sleep via Health Sync" ───────────────

def test_settings_page_has_sleep_health_sync_card():
    """Settings page HTML contains a card titled 'Sleep via Health Sync'."""
    with open("frontend/pages/settings.html", encoding="utf-8") as f:
        html = f.read()
    assert "Sleep via Health Sync" in html, (
        "Expected 'Sleep via Health Sync' card title in settings.html"
    )


def test_settings_page_sleep_card_in_integrations_section():
    """Sleep via Health Sync card is inside the integrations section."""
    with open("frontend/pages/settings.html", encoding="utf-8") as f:
        html = f.read()
    integrations_pos = html.find('id="section-integrations"')
    assert integrations_pos != -1, "section-integrations not found"
    card_pos = html.find("Sleep via Health Sync")
    assert card_pos != -1, "'Sleep via Health Sync' not found"
    assert card_pos > integrations_pos, (
        "Sleep via Health Sync card must appear after section-integrations"
    )


def test_settings_page_sleep_card_uses_integration_card_class():
    """Sleep via Health Sync card uses the integration-card CSS class."""
    with open("frontend/pages/settings.html", encoding="utf-8") as f:
        html = f.read()
    comment_pos = html.find("Sleep via Health Sync")
    assert comment_pos != -1
    # The integration-card div follows the comment; search the next 300 chars
    nearby = html[comment_pos:comment_pos + 300]
    assert "integration-card" in nearby, (
        "Sleep via Health Sync card must use integration-card CSS class"
    )


# ── AC3: Not-connected state elements ─────────────────────────────────────────

def test_settings_page_sleep_card_has_connect_action():
    """Settings page includes a Connect action for the Sleep via Health Sync card."""
    with open("frontend/pages/settings.html", encoding="utf-8") as f:
        html = f.read()
    assert "drive-sleep-connect" in html or "health-sync-connect" in html, (
        "Expected a Connect action element for the Sleep via Health Sync card"
    )


def test_settings_page_sleep_card_has_hint_text():
    """Not-connected state shows a hint about Health Sync exporting sleep data."""
    with open("frontend/pages/settings.html", encoding="utf-8") as f:
        html = f.read()
    assert "Health Sync" in html, "Expected hint text mentioning Health Sync"
    assert "sleep" in html.lower(), "Expected hint text mentioning sleep"


# ── AC4: Connected state elements in JS ───────────────────────────────────────

def test_settings_page_sleep_card_has_sync_now_action():
    """JavaScript includes a Sync Now action for the Sleep via Health Sync card."""
    with open("frontend/pages/settings.html", encoding="utf-8") as f:
        html = f.read()
    assert "Sync Now" in html, "Expected 'Sync Now' button text in settings.html"


def test_settings_page_sleep_card_has_disconnect_action():
    """JavaScript includes a Disconnect action for the Sleep via Health Sync card."""
    with open("frontend/pages/settings.html", encoding="utf-8") as f:
        html = f.read()
    # Should have disconnect logic somewhere in the page
    assert "drive-sleep-disconnect" in html or "Disconnect" in html, (
        "Expected Disconnect action in settings.html"
    )


def test_settings_page_sleep_card_shows_records_total():
    """Connected state renders the records_total value."""
    with open("frontend/pages/settings.html", encoding="utf-8") as f:
        html = f.read()
    assert "records_total" in html, (
        "Expected records_total to be referenced in settings.html JS"
    )


def test_settings_page_sleep_card_shows_last_sync_at():
    """Connected state renders the last_sync_at timestamp."""
    with open("frontend/pages/settings.html", encoding="utf-8") as f:
        html = f.read()
    assert "last_sync_at" in html, (
        "Expected last_sync_at to be referenced in settings.html JS"
    )


# ── AC5: Status field drives card state ───────────────────────────────────────

def test_settings_page_loads_status_from_integrations_endpoint():
    """JS fetches /api/integrations/drive-sleep/status to determine card state."""
    with open("frontend/pages/settings.html", encoding="utf-8") as f:
        html = f.read()
    assert "/api/integrations/drive-sleep/status" in html, (
        "Expected fetch of /api/integrations/drive-sleep/status in settings.html JS"
    )


def test_status_field_determines_connected_vs_not():
    """The status field value (connected/not_connected) drives the card state in JS."""
    with open("frontend/pages/settings.html", encoding="utf-8") as f:
        html = f.read()
    assert "connected" in html, "Expected 'connected' status handling in JS"
    assert "not_connected" in html or "not connected" in html.lower(), (
        "Expected not-connected state handling in JS"
    )


# ── AC6: User feedback ────────────────────────────────────────────────────────

def test_settings_page_sleep_card_has_feedback_element():
    """Sleep via Health Sync card has a feedback element for user messages."""
    with open("frontend/pages/settings.html", encoding="utf-8") as f:
        html = f.read()
    assert "health-sync-feedback" in html or "drive-sleep-feedback" in html, (
        "Expected a feedback element for the Sleep via Health Sync card"
    )


# ── Model availability ────────────────────────────────────────────────────────

def test_drive_sleep_connection_model_importable():
    """DriveSleepConnection model must be importable from backend.models."""
    from backend.models import DriveSleepConnection  # noqa: F401


def test_drive_sleep_connection_model_columns():
    """DriveSleepConnection must have required columns."""
    from backend.models import DriveSleepConnection
    col_names = {c.key for c in DriveSleepConnection.__table__.columns}
    required = {"id", "user_id", "folder_id", "status", "last_sync_at", "created_at", "updated_at"}
    assert required.issubset(col_names), f"Missing columns: {required - col_names}"


def test_sleep_record_model_importable():
    """SleepRecord model must be importable from backend.models."""
    from backend.models import SleepRecord  # noqa: F401
