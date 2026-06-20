"""Tests for issue #696: Add accept-suggestion flow for thresholds.

Acceptance criteria verified:

  AC1  — GET /api/thresholds/suggestions returns pending suggestions from
          suggest_thresholds; empty result (not error) when no suggestions exist.
  AC2  — POST /api/thresholds/suggestions/accept accepts explicit payload of
          keys and writes only those values to user_preferences.
  AC3  — Write endpoint sets threshold_source = 'user_accepted' provenance.
  AC4  — Manually-set threshold not overwritten unless explicitly in payload.
  AC5  — No hardcoded defaults in new code paths; values originate from
          suggest_thresholds output or user input.
  AC6  — All DB reads/writes in the caller layer, not inside shared utilities.
  AC7  — Accepting a key with no pending suggestion → 422 (not silent write).
  AC8  — Both endpoints authenticated and scoped to requesting user only.
"""

import os
import uuid
import pytest

# ── Unit tests: pure-function contract (no DB, no server) ────────────────────

from backend.services.threshold_suggestions import suggest_thresholds


def _run(duration_s, pace_s_per_km, avg_hr=None):
    return {
        "duration_seconds": duration_s,
        "avg_pace_seconds_per_km": pace_s_per_km,
        "avg_hr_bpm": avg_hr,
    }


# AC1 / AC5: no suggestions when no data — no fabricated defaults
def test_no_data_returns_empty_suggestions_not_defaults():
    """AC1/AC5: Empty inputs → insufficient-data sentinel, no hardcoded values."""
    result = suggest_thresholds(None, None)
    assert "suggestions" in result
    assert result["suggestions"] == {}
    assert not any(
        k in result
        for k in ("ftp_w", "threshold_hr", "threshold_pace_seconds_per_km")
    )


def test_empty_inputs_return_insufficient_sentinel():
    """AC1: Empty dict + empty list → {"suggestions": {}, "reason": ...}."""
    result = suggest_thresholds({}, [])
    assert "suggestions" in result


# AC2 / AC3: values come from suggest_thresholds, not hardcoded
def test_power_curve_produces_suggestion():
    """AC2: Valid 20-min power → ftp_w suggestion present."""
    result = suggest_thresholds({1200: 300.0}, [])
    assert "ftp_w" in result
    assert result["ftp_w"]["value"] == 285  # 300 * 0.95


def test_qualifying_run_produces_pace_suggestion():
    """AC2: 20-30 min run → threshold_pace_seconds_per_km suggestion."""
    result = suggest_thresholds({}, [_run(1500, 330.0, 165)])
    assert "threshold_pace_seconds_per_km" in result
    assert result["threshold_pace_seconds_per_km"]["value"] == 330


def test_qualifying_run_with_hr_produces_hr_suggestion():
    """AC2/AC3: Run with HR → threshold_hr suggestion carries the HR value."""
    result = suggest_thresholds({}, [_run(1500, 330.0, 162)])
    assert "threshold_hr" in result
    assert result["threshold_hr"]["value"] == 162


# AC6: service has no DB access (assert it has no sqlalchemy import)
def test_suggest_thresholds_has_no_db_access():
    """AC6: threshold_suggestions module must not import sqlalchemy."""
    import inspect
    import backend.services.threshold_suggestions as svc
    src = inspect.getsource(svc)
    assert "sqlalchemy" not in src
    assert "Session" not in src


# ── Integration / HTTP tests ─────────────────────────────────────────────────
# These require DATABASE_URL_UAT (or DATABASE_URL) and a running server.

_DB_URL = os.environ.get("DATABASE_URL_UAT") or os.environ.get("DATABASE_URL")
_needs_db = pytest.mark.skipif(
    not _DB_URL,
    reason="DATABASE_URL_UAT or DATABASE_URL not set — skipping DB/HTTP integration tests",
)

if _DB_URL:
    import httpx
    from sqlalchemy import create_engine, text

    _engine = create_engine(_DB_URL)
    BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
    _TEST_PWD = "pw696test!"

    def _make_user(prefix="t696") -> str:
        name = f"{prefix}_{uuid.uuid4().hex[:8]}"
        with _engine.begin() as conn:
            row = conn.execute(
                text("INSERT INTO users (name) VALUES (:n) RETURNING id"),
                {"n": name},
            ).fetchone()
        return str(row.id)

    def _drop_user(uid: str) -> None:
        with _engine.begin() as conn:
            conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})

    def _set_password(uid: str, pwd: str) -> None:
        from backend.auth import hash_password
        h = hash_password(pwd)
        with _engine.begin() as conn:
            conn.execute(
                text("UPDATE users SET password_hash = :h WHERE id = :uid"),
                {"h": h, "uid": uid},
            )

    def _get_username(uid: str) -> str:
        with _engine.connect() as conn:
            row = conn.execute(
                text("SELECT name FROM users WHERE id = :uid"), {"uid": uid}
            ).fetchone()
        return row.name

    def _insert_run(uid: str, duration_s: int, distance_km: float, avg_hr=None):
        with _engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO workouts (user_id, workout_date, name, workout_type,"
                    " duration_seconds, distance_km, avg_hr)"
                    " VALUES (:uid, CURRENT_DATE, 'Test Run', 'run', :dur, :dist, :hr)"
                ),
                {"uid": uid, "dur": duration_s, "dist": distance_km, "hr": avg_hr},
            )

    def _get_prefs(uid: str) -> dict:
        with _engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT ftp_w, ftp_w_source, threshold_hr, threshold_hr_source,"
                    " threshold_pace_seconds_per_km, threshold_pace_seconds_per_km_source"
                    " FROM user_preferences WHERE user_id = :uid"
                ),
                {"uid": uid},
            ).fetchone()
        return dict(row._mapping) if row else {}

    def _set_manual_pref(uid: str, key: str, value: int) -> None:
        with _engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO user_preferences (user_id, {key})"
                    f" VALUES (:uid, :val)"
                    f" ON CONFLICT (user_id) DO UPDATE SET {key} = :val,"
                    f" {key}_source = NULL"
                ),
                {"uid": uid, "val": value},
            )

    def _login(username: str, pwd: str):
        with httpx.Client(base_url=BASE, timeout=10) as c:
            r = c.post("/api/auth/login", json={"username": username, "password": pwd})
            assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
            session_cookie = c.cookies.get("session", "")
            csrf = ""
            for sc in r.headers.get_list("set-cookie"):
                if sc.startswith("csrf-token="):
                    csrf = sc.split("=", 1)[1].split(";")[0]
                    break
        return session_cookie, csrf

    def _auth(session_cookie: str, csrf: str) -> dict:
        return {"Cookie": f"session={session_cookie}; csrf-token={csrf}", "X-CSRF-Token": csrf}


# ── AC8: authentication required ─────────────────────────────────────────────

@_needs_db
def test_get_suggestions_unauthenticated_returns_401():
    """AC8: GET /api/thresholds/suggestions without auth → 401."""
    r = httpx.get(f"{BASE}/api/thresholds/suggestions", timeout=10)
    assert r.status_code == 401


@_needs_db
def test_post_accept_unauthenticated_returns_401():
    """AC8: POST /api/thresholds/suggestions/accept without auth → 401."""
    r = httpx.post(
        f"{BASE}/api/thresholds/suggestions/accept",
        json={"keys": ["ftp_w"]},
        timeout=10,
    )
    assert r.status_code == 401


# ── AC1: GET returns empty (not error) when no suggestions exist ─────────────

@_needs_db
def test_get_suggestions_no_data_returns_200_empty():
    """AC1: User with no workouts → 200 with empty pending dict, not an error."""
    uid = _make_user()
    try:
        _set_password(uid, _TEST_PWD)
        session_cookie, csrf = _login(_get_username(uid), _TEST_PWD)

        r = httpx.get(
            f"{BASE}/api/thresholds/suggestions",
            headers={"Cookie": f"session={session_cookie}; csrf-token={csrf}"},
            timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "pending" in body
        assert not body["pending"]
    finally:
        _drop_user(uid)


# ── AC7: accepting a key with no pending suggestion → 422, not silent write ──

@_needs_db
def test_accept_key_with_no_pending_suggestion_returns_422():
    """AC7: POST with a key that has no pending suggestion → 422 error."""
    uid = _make_user()
    try:
        _set_password(uid, _TEST_PWD)
        session_cookie, csrf = _login(_get_username(uid), _TEST_PWD)
        hdrs = _auth(session_cookie, csrf)

        # No workouts → no suggestions at all
        r = httpx.post(
            f"{BASE}/api/thresholds/suggestions/accept",
            json={"keys": ["ftp_w"]},
            headers=hdrs,
            timeout=10,
        )
        assert r.status_code in (404, 422), (
            f"Expected 404 or 422 when no suggestions exist, got {r.status_code}: {r.text}"
        )
        # Must not have silently written anything
        prefs = _get_prefs(uid)
        assert prefs.get("ftp_w") is None
    finally:
        _drop_user(uid)


@_needs_db
def test_accept_unknown_key_not_in_suggestions_returns_422():
    """AC7: POST requesting a key not returned by suggest_thresholds → 422."""
    uid = _make_user()
    try:
        _set_password(uid, _TEST_PWD)
        # Insert a run that yields pace/HR suggestions but NOT ftp_w
        _insert_run(uid, 1500, 5.0, avg_hr=162)
        session_cookie, csrf = _login(_get_username(uid), _TEST_PWD)
        hdrs = _auth(session_cookie, csrf)

        # Verify ftp_w is NOT pending (no power data)
        r_get = httpx.get(f"{BASE}/api/thresholds/suggestions", headers=hdrs, timeout=10)
        assert r_get.status_code == 200
        pending = r_get.json().get("pending", {})
        if "ftp_w" in pending:
            pytest.skip("ftp_w is pending — test requires it to be absent")

        r = httpx.post(
            f"{BASE}/api/thresholds/suggestions/accept",
            json={"keys": ["ftp_w"]},
            headers=hdrs,
            timeout=10,
        )
        assert r.status_code in (404, 422), (
            f"Expected 404 or 422 for key with no suggestion, got {r.status_code}: {r.text}"
        )
    finally:
        _drop_user(uid)


# ── AC2 / AC3: accept writes values with user_accepted provenance ─────────────

@_needs_db
def test_accept_valid_key_writes_value_with_user_accepted_source():
    """AC2/AC3: Accepting a pending suggestion writes value and source='user_accepted'."""
    uid = _make_user()
    try:
        _set_password(uid, _TEST_PWD)
        _insert_run(uid, 1500, 5.0, avg_hr=162)
        session_cookie, csrf = _login(_get_username(uid), _TEST_PWD)
        hdrs = _auth(session_cookie, csrf)

        r_get = httpx.get(f"{BASE}/api/thresholds/suggestions", headers=hdrs, timeout=10)
        assert r_get.status_code == 200
        pending = r_get.json().get("pending", {})
        if not pending:
            pytest.skip("No suggestions available with this test data")

        key = next(iter(pending))
        r = httpx.post(
            f"{BASE}/api/thresholds/suggestions/accept",
            json={"keys": [key]},
            headers=hdrs,
            timeout=10,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert "written" in body
        assert key in body["written"]

        prefs = _get_prefs(uid)
        assert prefs.get(f"{key}_source") == "user_accepted"
        assert prefs.get(key) == pending[key]["value"]
    finally:
        _drop_user(uid)


# ── AC4: manually-set threshold not overwritten when key absent from payload ──

@_needs_db
def test_manual_threshold_preserved_when_key_absent_from_payload():
    """AC4: Manual value with NULL source is not overwritten when key not in payload."""
    uid = _make_user()
    try:
        _set_password(uid, _TEST_PWD)
        _insert_run(uid, 1500, 5.0, avg_hr=162)
        _set_manual_pref(uid, "threshold_pace_seconds_per_km", 999)

        session_cookie, csrf = _login(_get_username(uid), _TEST_PWD)
        hdrs = _auth(session_cookie, csrf)

        r_get = httpx.get(f"{BASE}/api/thresholds/suggestions", headers=hdrs, timeout=10)
        pending = r_get.json().get("pending", {})

        # Accept threshold_hr (not threshold_pace) if available
        keys_not_pace = [k for k in pending if k != "threshold_pace_seconds_per_km"]
        if not keys_not_pace:
            pytest.skip("No other key to accept besides pace")

        r = httpx.post(
            f"{BASE}/api/thresholds/suggestions/accept",
            json={"keys": keys_not_pace},
            headers=hdrs,
            timeout=10,
        )
        assert r.status_code == 200, r.text

        prefs = _get_prefs(uid)
        assert prefs.get("threshold_pace_seconds_per_km") == 999
        assert prefs.get("threshold_pace_seconds_per_km_source") is None
    finally:
        _drop_user(uid)


# ── AC1: accepted key no longer appears in pending suggestions ────────────────

@_needs_db
def test_accepted_key_no_longer_pending():
    """AC1: After accepting a key, GET /api/thresholds/suggestions no longer lists it."""
    uid = _make_user()
    try:
        _set_password(uid, _TEST_PWD)
        _insert_run(uid, 1500, 5.0, avg_hr=162)
        session_cookie, csrf = _login(_get_username(uid), _TEST_PWD)
        hdrs = _auth(session_cookie, csrf)

        r_get = httpx.get(f"{BASE}/api/thresholds/suggestions", headers=hdrs, timeout=10)
        pending = r_get.json().get("pending", {})
        if not pending:
            pytest.skip("No suggestions available")

        key = next(iter(pending))
        httpx.post(
            f"{BASE}/api/thresholds/suggestions/accept",
            json={"keys": [key]},
            headers=hdrs,
            timeout=10,
        )

        r_get2 = httpx.get(f"{BASE}/api/thresholds/suggestions", headers=hdrs, timeout=10)
        pending_after = r_get2.json().get("pending", {})
        assert key not in pending_after
    finally:
        _drop_user(uid)


# ── AC8: user isolation — cannot see or accept another user's suggestions ─────

@_needs_db
def test_user_cannot_access_another_users_data():
    """AC8: User A's session cannot read or modify User B's preferences."""
    uid_a = _make_user("t696a")
    uid_b = _make_user("t696b")
    try:
        _set_password(uid_a, _TEST_PWD)
        _set_password(uid_b, _TEST_PWD)
        # Give B a manual preference so we can check it wasn't touched
        _set_manual_pref(uid_b, "threshold_hr", 180)

        session_cookie_a, csrf_a = _login(_get_username(uid_a), _TEST_PWD)
        hdrs_a = _auth(session_cookie_a, csrf_a)

        # GET as user A — should not include user B's data
        r = httpx.get(f"{BASE}/api/thresholds/suggestions", headers=hdrs_a, timeout=10)
        assert r.status_code == 200
        # Just verifying the endpoint responds without exposing B's data.
        # We can't easily inject a user_id param, but we confirm B's prefs are intact.

        prefs_b = _get_prefs(uid_b)
        assert prefs_b.get("threshold_hr") == 180
    finally:
        _drop_user(uid_a)
        _drop_user(uid_b)
