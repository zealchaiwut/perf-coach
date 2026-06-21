"""Tests for issue #878: weight-targets/arrival-projection endpoint (runs against UAT)"""
import os
import uuid
import pytest
import httpx
from datetime import date, timedelta
from sqlalchemy import create_engine, text


# Resolved from UAT .env at runtime; see tester skill Step 0.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

# Database setup for integration tests
_DB_URL = os.environ.get("DATABASE_URL_UAT") or os.environ.get("DATABASE_URL")
_needs_db = pytest.mark.skipif(
    not _DB_URL,
    reason="DATABASE_URL_UAT or DATABASE_URL not set — skipping HTTP integration tests",
)

if _DB_URL:
    _engine = create_engine(_DB_URL)
    _TEST_PASSWORD = "TestPw878!"

    def _make_user(prefix="t878") -> str:
        """Create a test user and return its UUID."""
        name = f"{prefix}_{uuid.uuid4().hex[:8]}"
        with _engine.begin() as conn:
            row = conn.execute(
                text("INSERT INTO users (name) VALUES (:n) RETURNING id"),
                {"n": name},
            ).fetchone()
        return str(row.id)

    def _drop_user(uid: str) -> None:
        """Delete a user and all related data."""
        with _engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})

    def _set_password(uid: str, password: str) -> None:
        """Hash and set password for a user."""
        from backend.auth import hash_password
        h = hash_password(password)
        with _engine.begin() as conn:
            conn.execute(
                text("UPDATE users SET password_hash = :h, name = :n WHERE id = :uid"),
                {"h": h, "uid": uid, "n": f"user_{uuid.uuid4().hex[:6]}"},
            )

    def _get_username(uid: str) -> str:
        """Get username for a user."""
        with _engine.connect() as conn:
            row = conn.execute(
                text("SELECT name FROM users WHERE id = :uid"), {"uid": uid}
            ).fetchone()
        return row.name if row else None

    def _login_and_get_session(username: str, password: str):
        """Return (session_cookie, csrf_token) tuple."""
        with httpx.Client(base_url=BASE_URL, timeout=10) as c:
            r = c.post("/api/auth/login", json={"username": username, "password": password})
            assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
            session = c.cookies.get("session", "")
            csrf = ""
            for sc in r.headers.get_list("set-cookie"):
                if sc.startswith("csrf-token="):
                    csrf = sc.split("=", 1)[1].split(";")[0]
                    break
        return session, csrf

    def _get_auth_headers(session: str, csrf: str):
        """Build headers dict with session and CSRF tokens."""
        return {"Cookie": f"session={session}; csrf-token={csrf}", "X-CSRF-Token": csrf}


@pytest.fixture
def client():
    """HTTP client fixture."""
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def auth_session():
    """Create a test user and return authenticated session + headers."""
    if not _DB_URL:
        pytest.skip("DATABASE_URL_UAT or DATABASE_URL not set")
    uid = _make_user()
    try:
        _set_password(uid, _TEST_PASSWORD)
        username = _get_username(uid)
        session, csrf = _login_and_get_session(username, _TEST_PASSWORD)
        yield {
            "user_id": uid,
            "username": username,
            "session": session,
            "csrf": csrf,
            "headers": _get_auth_headers(session, csrf),
        }
    finally:
        _drop_user(uid)


@pytest.fixture
def setup_weight_loss_plan(client, auth_session):
    """Set up a user with an active weight-loss plan, active goal, and weight entries."""
    today = date.today()
    start_weight = 95.0
    goal_weight = 85.0
    hdrs = auth_session["headers"]

    # Create active weight target (plan)
    r = client.post(
        "/api/weight-targets",
        json={
            "name": "Loss Plan",
            "start_weight_kg": start_weight,
            "start_date": today.isoformat(),
            "target_weight_kg": goal_weight,
            "target_date": (today + timedelta(days=60)).isoformat(),
        },
        headers=hdrs,
    )
    assert r.status_code == 201, f"Failed to create target: {r.text}"

    # Add weight entries over the last 21 days (ARRIVAL_WINDOW_DAYS)
    # Simulate converging trend: losing 0.5 kg/week
    for i in range(22):
        entry_date = today - timedelta(days=21 - i)
        weight = start_weight - (i * 0.5 / 7.0)  # Approx 0.5 kg/week loss
        r = client.post(
            "/api/weight-entries",
            json={
                "weight_kg": round(weight, 2),
                "entry_date": entry_date.isoformat(),
            },
            headers=hdrs,
        )
        assert r.status_code == 201, f"Failed to add weight entry: {r.text}"

    return auth_session


@pytest.fixture
def setup_gaining_weight_user(client, auth_session):
    """Set up a user whose weight is moving away from goal (gaining on loss plan)."""
    today = date.today()
    start_weight = 90.0
    goal_weight = 85.0
    hdrs = auth_session["headers"]

    # Create active target
    r = client.post(
        "/api/weight-targets",
        json={
            "name": "Gain Plan (Wrong Direction)",
            "start_weight_kg": start_weight,
            "start_date": today.isoformat(),
            "target_weight_kg": goal_weight,
            "target_date": (today + timedelta(days=60)).isoformat(),
        },
        headers=hdrs,
    )
    assert r.status_code == 201, f"Failed to create target: {r.text}"

    # Add weight entries showing upward trend (gaining 0.3 kg/week)
    for i in range(22):
        entry_date = today - timedelta(days=21 - i)
        weight = start_weight + (i * 0.3 / 7.0)  # Approx 0.3 kg/week gain
        r = client.post(
            "/api/weight-entries",
            json={
                "weight_kg": round(weight, 2),
                "entry_date": entry_date.isoformat(),
            },
            headers=hdrs,
        )
        assert r.status_code == 201, f"Failed to add weight entry: {r.text}"

    return auth_session


@pytest.fixture
def setup_no_plan_user(client, auth_session):
    """User with no active plan but might have other data."""
    # Just return auth; no plan created
    return auth_session


@pytest.fixture
def setup_no_goal_user(client, auth_session):
    """User with no active plan/goal (model doesn't allow null goals, so just use user with no plan)."""
    # Note: The WeightTarget model requires target_weight_kg to be non-null, so we
    # can't actually create a plan without a goal. This fixture returns a plain user
    # with no active plan, which satisfies the test scenario.
    return auth_session


@pytest.fixture
def setup_insufficient_data_user(client, auth_session):
    """User with plan and goal but only 1 weight entry (need 2 for rate calculation)."""
    today = date.today()
    hdrs = auth_session["headers"]

    # Create active target
    r = client.post(
        "/api/weight-targets",
        json={
            "name": "Insufficient Data Plan",
            "start_weight_kg": 90.0,
            "start_date": today.isoformat(),
            "target_weight_kg": 80.0,
            "target_date": (today + timedelta(days=60)).isoformat(),
        },
        headers=hdrs,
    )
    assert r.status_code == 201, f"Failed to create target: {r.text}"

    # Add only 1 weight entry
    r = client.post(
        "/api/weight-entries",
        json={
            "weight_kg": 90.0,
            "entry_date": today.isoformat(),
        },
        headers=hdrs,
    )
    assert r.status_code == 201, f"Failed to add weight entry: {r.text}"
    return auth_session


# ── Acceptance Criteria Tests ──

@_needs_db
def test_878__endpoint_accepts_active_plan_and_goal(client, setup_weight_loss_plan):
    """AC1: Endpoint accepts the active plan and goal identifiers."""
    # The endpoint should resolve them internally via session lookup.
    # No explicit parameters passed; the endpoint finds them by user_id and status.
    r = client.get("/api/weight-targets/arrival-projection", headers=setup_weight_loss_plan["headers"])
    assert r.status_code == 200, f"Endpoint failed: {r.text}"


@_needs_db
def test_878__endpoint_calls_project_arrival_and_returns_fields(client, setup_weight_loss_plan):
    """AC2: Calls project_arrival and returns projected_arrival_date, projected_rate, recent_rate."""
    r = client.get("/api/weight-targets/arrival-projection", headers=setup_weight_loss_plan["headers"])
    assert r.status_code == 200

    body = r.json()
    # All four fields should be present
    assert "projected_arrival_date" in body, "Missing projected_arrival_date"
    assert "projected_rate" in body, "Missing projected_rate"
    assert "recent_rate" in body, "Missing recent_rate"
    assert "reason" in body, "Missing reason"

    # For a converging trend, dates and rates should be populated
    assert body["projected_arrival_date"] is not None, "Expected non-null projected_arrival_date"
    assert body["projected_rate"] is not None, "Expected non-null projected_rate"
    assert body["recent_rate"] is not None, "Expected non-null recent_rate"


@_needs_db
def test_878__not_trending_toward_goal_returns_null_projections_with_reason(client, setup_gaining_weight_user):
    """AC3: When not trending toward goal, returns null projections and reason='not_trending_toward_goal'."""
    r = client.get("/api/weight-targets/arrival-projection", headers=setup_gaining_weight_user["headers"])
    assert r.status_code == 200

    body = r.json()
    assert body["projected_arrival_date"] is None, "Expected null projected_arrival_date"
    assert body["projected_rate"] is None, "Expected null projected_rate"
    assert body["recent_rate"] is not None, "Expected non-null recent_rate (current pace)"
    assert body["reason"] == "not_trending_toward_goal", f"Expected reason 'not_trending_toward_goal', got {body.get('reason')}"


@_needs_db
def test_878__missing_plan_returns_empty_state_with_reason(client, setup_no_plan_user):
    """AC4a: Missing active plan returns null fields and reason='no_active_plan' (HTTP 200)."""
    r = client.get("/api/weight-targets/arrival-projection", headers=setup_no_plan_user["headers"])
    assert r.status_code == 200, f"Expected HTTP 200, got {r.status_code}"

    body = r.json()
    assert body["projected_arrival_date"] is None
    assert body["projected_rate"] is None
    assert body["recent_rate"] is None
    assert body["reason"] == "no_active_plan"


@_needs_db
def test_878__missing_goal_returns_empty_state_with_reason(client, setup_no_goal_user):
    """AC4b: No active plan also returns empty state (model requires non-null goal, so this is tested via no_plan case)."""
    # Since the WeightTarget model requires target_weight_kg to be non-null, we can't have
    # a plan without a goal. The endpoint logic still handles that case defensively, but it's
    # exercised implicitly by the no-plan test. For coverage, we verify it here by testing
    # the same user with no active target.
    r = client.get("/api/weight-targets/arrival-projection", headers=setup_no_goal_user["headers"])
    assert r.status_code == 200

    body = r.json()
    assert body["projected_arrival_date"] is None
    assert body["projected_rate"] is None
    assert body["recent_rate"] is None
    # Since there's no plan at all, reason should be no_active_plan
    assert body["reason"] == "no_active_plan"


@_needs_db
def test_878__insufficient_weight_entries_returns_empty_state(client, setup_insufficient_data_user):
    """AC5: Insufficient weight entries returns null fields and reason='insufficient_data' (HTTP 200)."""
    r = client.get("/api/weight-targets/arrival-projection", headers=setup_insufficient_data_user["headers"])
    assert r.status_code == 200

    body = r.json()
    assert body["projected_arrival_date"] is None
    assert body["projected_rate"] is None
    # recent_rate may be null since we need 2 entries to compute a rate
    assert body["reason"] == "insufficient_data"


@_needs_db
def test_878__recent_rate_present_in_not_trending_state(client, setup_gaining_weight_user):
    """AC6: recent_rate field always returned when computable, even in not-trending-toward-goal state."""
    r = client.get("/api/weight-targets/arrival-projection", headers=setup_gaining_weight_user["headers"])
    assert r.status_code == 200

    body = r.json()
    assert body["reason"] == "not_trending_toward_goal"
    # recent_rate should be present and non-null (they have 22 entries over 21 days)
    assert body["recent_rate"] is not None, "recent_rate should be computed even in not-trending state"


@_needs_db
def test_878__response_shape_consistent_across_all_states(client, setup_no_plan_user):
    """AC7: Response shape is consistent (no conditional top-level keys)."""
    r = client.get("/api/weight-targets/arrival-projection", headers=setup_no_plan_user["headers"])
    assert r.status_code == 200

    body = r.json()
    required_keys = {"projected_arrival_date", "projected_rate", "recent_rate", "reason"}
    actual_keys = set(body.keys())

    assert required_keys == actual_keys, f"Expected keys {required_keys}, got {actual_keys}"


@_needs_db
def test_878__happy_path_projection_is_valid_date(client, setup_weight_loss_plan):
    """AC7 extended: Happy path returns a valid ISO-formatted date in the future."""
    r = client.get("/api/weight-targets/arrival-projection", headers=setup_weight_loss_plan["headers"])
    assert r.status_code == 200

    body = r.json()
    arrival_str = body["projected_arrival_date"]
    assert arrival_str is not None

    # Parse and validate it's a valid date
    try:
        arrival = date.fromisoformat(arrival_str)
        today = date.today()
        assert arrival > today, f"Projected arrival {arrival} should be in the future (after {today})"
    except ValueError as e:
        pytest.fail(f"Invalid date format: {arrival_str}: {e}")


@_needs_db
def test_878__projected_rate_matches_recent_rate_on_happy_path(client, setup_weight_loss_plan):
    """Consistency check: projected_rate and recent_rate should match on happy path."""
    r = client.get("/api/weight-targets/arrival-projection", headers=setup_weight_loss_plan["headers"])
    assert r.status_code == 200

    body = r.json()
    # On the happy path (converging), projected_rate should equal recent_rate
    if body["projected_arrival_date"] is not None:
        assert body["projected_rate"] == body["recent_rate"], \
            "projected_rate and recent_rate should match on happy path"


@_needs_db
def test_878__reason_field_null_on_happy_path(client, setup_weight_loss_plan):
    """Consistency check: reason should be null/absent on happy path."""
    r = client.get("/api/weight-targets/arrival-projection", headers=setup_weight_loss_plan["headers"])
    assert r.status_code == 200

    body = r.json()
    if body["projected_arrival_date"] is not None:
        # On happy path, reason should be null or absent (we return None)
        assert body.get("reason") is None, \
            f"Expected reason to be null on happy path, got {body.get('reason')}"
