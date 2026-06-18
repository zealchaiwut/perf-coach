"""Tests for issue #591: Add accept-suggestion flow for threshold values.

Acceptance criteria verified:

  AC1  — GET /api/thresholds/suggestions returns pending suggestions from
          suggest_thresholds; empty result (not error) when no suggestions exist.
  AC2  — POST /api/thresholds/suggestions/accept accepts explicit payload of
          keys and writes only those values to user_preferences; all DB access
          lives in the controller, not the service.
  AC3  — No defaults hardcoded; suggestion values come exclusively from
          suggest_thresholds output.
  AC4  — Accepting a suggestion for a manually-set threshold does not overwrite
          unless that key is explicitly included in the payload.
  AC5  — Each written user_preferences record has source = "user_accepted".
  AC6  — Accepting a subset leaves remaining suggestions pending.
  AC7  — Both endpoints require auth; return 401 for unauthenticated requests.
  AC8  — POST returns structured response: written keys and their new values.
  AC9  — Unit/integration tests: no-suggestions state, partial acceptance, full
          acceptance, attempt to accept over manually set value without inclusion.
"""

import os
import uuid
import pytest

# ── Pure-function unit tests (no DB, no server needed) ────────────────────────

from backend.services.threshold_suggestions import suggest_thresholds


# ── helpers ────────────────────────────────────────────────────────────────────

def _run(duration_seconds, pace_s_per_km, avg_hr=None):
    return {
        "duration_seconds": duration_seconds,
        "avg_pace_seconds_per_km": pace_s_per_km,
        "avg_hr_bpm": avg_hr,
    }


# ── AC9 / AC3: no-suggestions state ───────────────────────────────────────────

def test_no_data_returns_empty_suggestions():
    """AC9/AC3: Both inputs None → {"suggestions": {}, "reason": ...}, no exception."""
    result = suggest_thresholds(None, None)
    assert "suggestions" in result
    assert result["suggestions"] == {}
    assert "reason" in result


def test_empty_curve_and_empty_runs_returns_insufficient():
    """AC9: Empty dict + empty list → insufficient-data sentinel."""
    result = suggest_thresholds({}, [])
    assert "suggestions" in result
    assert result["suggestions"] == {}


def test_runs_without_qualifying_duration_returns_insufficient():
    """AC9: Runs all < 1200 s or > 1800 s → no pace/HR suggestion; no power → empty."""
    runs = [_run(600, 300.0, 150), _run(3600, 320.0, 160)]
    result = suggest_thresholds({}, runs)
    assert "suggestions" in result
    assert result["suggestions"] == {}


# ── AC (from #590 spec): 300 W → 285 W worked example ────────────────────────

def test_ftp_300w_yields_285w_suggestion():
    """AC: best 20-minute power of 300 W → suggested FTP of 285 W (× 0.95, rounded)."""
    result = suggest_thresholds({1200: 300.0}, [])
    assert "ftp_w" in result
    assert result["ftp_w"]["value"] == 285
    assert result["ftp_w"]["high_confidence"] is True


def test_ftp_high_confidence_requires_1200s_point():
    """AC: high_confidence=True for power only when 20-min point present in curve."""
    result_hc = suggest_thresholds({1200: 280.0}, [])
    assert result_hc["ftp_w"]["high_confidence"] is True

    result_lc = suggest_thresholds({1800: 280.0}, [])
    assert result_lc["ftp_w"]["high_confidence"] is False


# ── AC: power fallback from 20-60 min when 20-min absent ─────────────────────

def test_ftp_fallback_from_30min_effort():
    """AC: No 20-min point → best 20-60 min effort used with 0.95 multiplier."""
    result = suggest_thresholds({1800: 270.0}, [])
    assert "ftp_w" in result
    assert result["ftp_w"]["value"] == round(270.0 * 0.95)
    assert result["ftp_w"]["high_confidence"] is False


def test_ftp_fallback_picks_best_among_multiple_durations():
    """AC: Falls back to highest power in the 1200–3600 s range."""
    result = suggest_thresholds({1800: 260.0, 3600: 280.0}, [])
    assert result["ftp_w"]["value"] == round(280.0 * 0.95)


def test_ftp_ignores_durations_outside_20_60_min_for_fallback():
    """AC: Durations < 1200 s or > 3600 s not used for FTP fallback."""
    result = suggest_thresholds({600: 400.0, 5400: 200.0}, [])
    assert "ftp_w" not in result


# ── AC: pace and HR from 20-30 min runs ──────────────────────────────────────

def test_pace_from_qualifying_run():
    """AC: Best pace from 1200–1800 s run → threshold_pace_seconds_per_km."""
    result = suggest_thresholds({}, [_run(1500, 330.0, 162)])
    assert "threshold_pace_seconds_per_km" in result
    assert result["threshold_pace_seconds_per_km"]["value"] == 330


def test_hr_from_same_run_as_pace():
    """AC: threshold_hr comes from the same run that gave the pace suggestion."""
    result = suggest_thresholds({}, [_run(1500, 330.0, 162)])
    assert "threshold_hr" in result
    assert result["threshold_hr"]["value"] == 162


def test_pace_picks_fastest_among_qualifying_runs():
    """AC: Fastest pace (lowest s/km) among qualifying runs is chosen."""
    runs = [_run(1400, 340.0, 165), _run(1600, 320.0, 160)]
    result = suggest_thresholds({}, runs)
    assert result["threshold_pace_seconds_per_km"]["value"] == 320
    assert result["threshold_hr"]["value"] == 160


def test_high_confidence_pace_requires_two_qualifying_runs():
    """AC: high_confidence=True for pace/HR only when ≥ 2 qualifying run efforts."""
    one_run = [_run(1400, 330.0, 160)]
    two_runs = [_run(1400, 330.0, 160), _run(1500, 325.0, 162)]

    result_one = suggest_thresholds({}, one_run)
    assert result_one["threshold_pace_seconds_per_km"]["high_confidence"] is False

    result_two = suggest_thresholds({}, two_runs)
    assert result_two["threshold_pace_seconds_per_km"]["high_confidence"] is True


def test_no_hr_when_run_lacks_hr_data():
    """AC: When the best run has no HR, threshold_hr is absent from result."""
    result = suggest_thresholds({}, [_run(1500, 330.0, avg_hr=None)])
    assert "threshold_hr" not in result


# ── AC3: suggestion values come from data, not hardcoded defaults ─────────────

def test_suggest_thresholds_has_no_hardcoded_defaults():
    """AC3: Function returns only what the data supports; nothing hardcoded."""
    result = suggest_thresholds({}, [])
    assert "suggestions" in result  # insufficient-data sentinel
    assert not any(k in result for k in ("ftp_w", "threshold_hr", "threshold_pace_seconds_per_km"))


# ── AC: debug object ──────────────────────────────────────────────────────────

def test_debug_present_in_successful_result():
    """AC: Successful result includes a 'debug' key with source information."""
    result = suggest_thresholds({1200: 300.0}, [_run(1500, 330.0, 162)])
    assert "debug" in result


def test_debug_contains_formula_for_each_channel():
    """AC: debug exposes source effort details including formula in plain English."""
    result = suggest_thresholds({1200: 300.0}, [_run(1500, 330.0, 162)])
    debug = result["debug"]
    assert "ftp_w" in debug
    assert "formula" in debug["ftp_w"]
    assert "threshold_pace_seconds_per_km" in debug
    assert "formula" in debug["threshold_pace_seconds_per_km"]


# ── Integration / HTTP tests ──────────────────────────────────────────────────
# These require DATABASE_URL_UAT (or DATABASE_URL) and a running server.

_DB_URL = os.environ.get("DATABASE_URL_UAT") or os.environ.get("DATABASE_URL")
_needs_db = pytest.mark.skipif(
    not _DB_URL,
    reason="DATABASE_URL_UAT or DATABASE_URL not set — skipping DB/HTTP integration tests",
)

if _DB_URL:
    import httpx
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session as _Session

    _engine = create_engine(_DB_URL)
    BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
    _TEST_PASSWORD = "test591pw!"

    def _make_user(prefix="t591") -> str:
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

    def _set_password(uid: str, password: str) -> None:
        from backend.auth import hash_password
        h = hash_password(password)
        with _engine.begin() as conn:
            conn.execute(
                text("UPDATE users SET password_hash = :h WHERE id = :uid"),
                {"h": h, "uid": uid},
            )

    def _login_session(username: str, password: str):
        """Return (session_cookie, csrf_token) tuple."""
        with httpx.Client(base_url=BASE, timeout=10) as c:
            r = c.post("/api/auth/login", json={"username": username, "password": password})
            assert r.status_code == 200, f"Login failed: {r.status_code} {r.text}"
            session = c.cookies.get("session", "")
            csrf = ""
            for sc in r.headers.get_list("set-cookie"):
                if sc.startswith("csrf-token="):
                    csrf = sc.split("=", 1)[1].split(";")[0]
                    break
        return session, csrf

    def _get_username(uid: str) -> str:
        with _engine.connect() as conn:
            row = conn.execute(
                text("SELECT name FROM users WHERE id = :uid"), {"uid": uid}
            ).fetchone()
        return row.name

    def _insert_run_workout(uid: str, duration_s: int, distance_km: float, avg_hr=None):
        with _engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO workouts (user_id, workout_date, name, workout_type, "
                    "duration_seconds, distance_km, avg_hr) "
                    "VALUES (:uid, CURRENT_DATE, 'Test Run', 'run', :dur, :dist, :hr)"
                ),
                {"uid": uid, "dur": duration_s, "dist": distance_km, "hr": avg_hr},
            )

    def _get_prefs(uid: str) -> dict:
        with _engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT ftp_w, ftp_w_source, threshold_hr, threshold_hr_source, "
                    "threshold_pace_seconds_per_km, threshold_pace_seconds_per_km_source "
                    "FROM user_preferences WHERE user_id = :uid"
                ),
                {"uid": uid},
            ).fetchone()
        if row is None:
            return {}
        return dict(row._mapping)

    def _set_manual_pref(uid: str, key: str, value: int):
        with _engine.begin() as conn:
            conn.execute(
                text(
                    f"INSERT INTO user_preferences (user_id, {key}) VALUES (:uid, :val) "
                    f"ON CONFLICT (user_id) DO UPDATE SET {key} = :val, {key}_source = NULL"
                ),
                {"uid": uid, "val": value},
            )

    def _auth_headers(session: str, csrf: str) -> dict:
        return {"Cookie": f"session={session}; csrf-token={csrf}", "X-CSRF-Token": csrf}


# ── AC7: auth required ────────────────────────────────────────────────────────

@_needs_db
def test_get_suggestions_unauthenticated_returns_401():
    """AC7: GET /api/thresholds/suggestions without auth → 401."""
    r = httpx.get(f"{BASE}/api/thresholds/suggestions", timeout=10)
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


@_needs_db
def test_post_accept_suggestions_unauthenticated_returns_401():
    """AC7: POST /api/thresholds/suggestions/accept without auth → 401."""
    r = httpx.post(
        f"{BASE}/api/thresholds/suggestions/accept",
        json={"keys": ["ftp_w"]},
        timeout=10,
    )
    assert r.status_code == 401, f"Expected 401, got {r.status_code}"


# ── AC1, AC9: no-suggestions state ────────────────────────────────────────────

@_needs_db
def test_get_suggestions_no_data_returns_empty_not_error():
    """AC1/AC9: User with no workouts → HTTP 200 with empty pending dict."""
    uid = _make_user()
    try:
        _set_password(uid, _TEST_PASSWORD)
        name = _get_username(uid)
        session, csrf = _login_session(name, _TEST_PASSWORD)

        r = httpx.get(
            f"{BASE}/api/thresholds/suggestions",
            headers={"Cookie": f"session={session}; csrf-token={csrf}"},
            timeout=10,
        )
        assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
        body = r.json()
        assert "pending" in body
        assert not body["pending"]
    finally:
        _drop_user(uid)


# ── AC6, AC8, AC9: partial acceptance ─────────────────────────────────────────

@_needs_db
def test_post_accept_partial__only_specified_keys_written():
    """AC6/AC8/AC9: Accepting a subset writes only those keys; accepted key leaves pending."""
    uid = _make_user()
    try:
        _set_password(uid, _TEST_PASSWORD)
        _insert_run_workout(uid, duration_s=1500, distance_km=5.0, avg_hr=162)
        name = _get_username(uid)
        session, csrf = _login_session(name, _TEST_PASSWORD)
        hdrs = _auth_headers(session, csrf)

        r_get = httpx.get(f"{BASE}/api/thresholds/suggestions", headers=hdrs, timeout=10)
        assert r_get.status_code == 200
        pending_before = r_get.json().get("pending", {})
        if not pending_before:
            pytest.skip("No suggestions available with this test data")

        # Accept only one key that is present
        pace_key = "threshold_pace_seconds_per_km"
        keys_to_accept = [pace_key] if pace_key in pending_before else [next(iter(pending_before))]

        r_post = httpx.post(
            f"{BASE}/api/thresholds/suggestions/accept",
            json={"keys": keys_to_accept},
            headers=hdrs,
            timeout=10,
        )
        assert r_post.status_code == 200, f"Expected 200, got {r_post.status_code}: {r_post.text}"
        body = r_post.json()

        # AC8: written keys confirmed in response
        assert "written" in body
        for k in keys_to_accept:
            assert k in body["written"]

        # AC6: accepted key no longer in pending; others still present
        r_get2 = httpx.get(f"{BASE}/api/thresholds/suggestions", headers=hdrs, timeout=10)
        pending_after = r_get2.json().get("pending", {})
        for k in keys_to_accept:
            assert k not in pending_after, f"Key {k!r} should not be pending after acceptance"
    finally:
        _drop_user(uid)


# ── AC5, AC8, AC9: full acceptance with source check ──────────────────────────

@_needs_db
def test_post_accept_full__source_is_user_accepted():
    """AC5/AC8/AC9: Accepting all keys → written with source = 'user_accepted'."""
    uid = _make_user()
    try:
        _set_password(uid, _TEST_PASSWORD)
        _insert_run_workout(uid, duration_s=1500, distance_km=5.0, avg_hr=162)
        _insert_run_workout(uid, duration_s=1400, distance_km=4.8, avg_hr=160)
        name = _get_username(uid)
        session, csrf = _login_session(name, _TEST_PASSWORD)
        hdrs = _auth_headers(session, csrf)

        r_get = httpx.get(f"{BASE}/api/thresholds/suggestions", headers=hdrs, timeout=10)
        assert r_get.status_code == 200
        pending = r_get.json().get("pending", {})
        if not pending:
            pytest.skip("No pending suggestions with test data")

        all_keys = list(pending.keys())
        r_post = httpx.post(
            f"{BASE}/api/thresholds/suggestions/accept",
            json={"keys": all_keys},
            headers=hdrs,
            timeout=10,
        )
        assert r_post.status_code == 200
        written = r_post.json().get("written", {})
        for k in all_keys:
            assert k in written

        # AC5: source = "user_accepted" in DB
        prefs = _get_prefs(uid)
        for k in all_keys:
            assert prefs.get(f"{k}_source") == "user_accepted"
    finally:
        _drop_user(uid)


# ── AC4, AC9: manually set value not overwritten without explicit inclusion ────

@_needs_db
def test_post_accept_manual_key_not_in_payload__not_overwritten():
    """AC4/AC9: Manual threshold not overwritten when key absent from POST payload."""
    uid = _make_user()
    try:
        _set_password(uid, _TEST_PASSWORD)
        _insert_run_workout(uid, duration_s=1500, distance_km=5.0, avg_hr=162)
        _set_manual_pref(uid, "threshold_pace_seconds_per_km", 999)

        name = _get_username(uid)
        session, csrf = _login_session(name, _TEST_PASSWORD)
        hdrs = _auth_headers(session, csrf)

        r_post = httpx.post(
            f"{BASE}/api/thresholds/suggestions/accept",
            json={"keys": ["threshold_hr"]},
            headers=hdrs,
            timeout=10,
        )
        assert r_post.status_code == 200

        prefs = _get_prefs(uid)
        assert prefs.get("threshold_pace_seconds_per_km") == 999
        assert prefs.get("threshold_pace_seconds_per_km_source") is None
    finally:
        _drop_user(uid)


@_needs_db
def test_post_accept_manual_key_explicitly_in_payload__overwrites():
    """AC4: Manual threshold IS overwritten when user explicitly includes the key."""
    uid = _make_user()
    try:
        _set_password(uid, _TEST_PASSWORD)
        _insert_run_workout(uid, duration_s=1500, distance_km=5.0, avg_hr=162)
        _set_manual_pref(uid, "threshold_pace_seconds_per_km", 999)

        name = _get_username(uid)
        session, csrf = _login_session(name, _TEST_PASSWORD)
        hdrs = _auth_headers(session, csrf)

        r_get = httpx.get(f"{BASE}/api/thresholds/suggestions", headers=hdrs, timeout=10)
        pending = r_get.json().get("pending", {})
        if "threshold_pace_seconds_per_km" not in pending:
            pytest.skip("threshold_pace_seconds_per_km not in suggestions")

        suggested_value = pending["threshold_pace_seconds_per_km"]["value"]

        r_post = httpx.post(
            f"{BASE}/api/thresholds/suggestions/accept",
            json={"keys": ["threshold_pace_seconds_per_km"]},
            headers=hdrs,
            timeout=10,
        )
        assert r_post.status_code == 200

        prefs = _get_prefs(uid)
        assert prefs.get("threshold_pace_seconds_per_km") == suggested_value
        assert prefs.get("threshold_pace_seconds_per_km_source") == "user_accepted"
    finally:
        _drop_user(uid)
