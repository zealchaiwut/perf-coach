"""
Tests for issue #356: user_preferences table and per-user TSS thresholds.

6 AC anchors:
  (a) UserPreferences model importable
  (b) unique constraint blocks duplicate user_id
  (c) default row created at migration
  (d) estimate_tss_for_workout reads FTP from user_preferences when row exists
  (e) estimate_tss_for_workout falls back to defaults when row missing or ftp_w null
  (f) cascade delete removes user_preferences row when parent user deleted

Tests for issue #357: GET and PATCH /api/user-preferences endpoints.

8 AC anchors:
  (357-a) GET lazy-creates row on first call
  (357-b) GET response includes row + defaults block
  (357-c) PATCH ftp_w to 320 persists; subsequent GET reflects 320
  (357-d) PATCH ftp_w to null succeeds (unset)
  (357-e) PATCH ftp_w to 1000 returns 422
  (357-f) PATCH timezone to "Asia/Bangkok" succeeds
  (357-g) PATCH timezone to "Mars/Olympus" returns 422
  (357-h) PATCH preferred_units returns 422
"""
import uuid
import logging
import pytest
import httpx
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db import engine
from backend.services.tss import estimate_tss_for_workout, FTP_W

BASE = "http://127.0.0.1:9001"
_TEST_PASSWORD = "up357-tests-pw"


# ── helpers ───────────────────────────────────────────────────────────────────

def _make_user(prefix: str = "up") -> str:
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        row = conn.execute(
            text("INSERT INTO users (name) VALUES (:n) RETURNING id"),
            {"n": name},
        ).fetchone()
    return str(row.id)


def _drop_user(uid: str) -> None:
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": uid})


def _insert_prefs(conn, uid: str, ftp_w=None, threshold_hr=None, threshold_pace=None):
    conn.execute(
        text(
            "INSERT INTO user_preferences (user_id, ftp_w, threshold_hr, threshold_pace_seconds_per_km) "
            "VALUES (:uid, :ftp, :hr, :pace)"
        ),
        {"uid": uid, "ftp": ftp_w, "hr": threshold_hr, "pace": threshold_pace},
    )


class _MockWorkout:
    def __init__(self, avg_power_w=None, avg_pace_seconds_per_km=None,
                 duration_seconds=3600, avg_hr=None, distance_km=None):
        self.avg_power_w = avg_power_w
        self.avg_pace_seconds_per_km = avg_pace_seconds_per_km
        self.duration_seconds = duration_seconds
        self.avg_hr = avg_hr
        self.distance_km = distance_km


# ── (a) Model importable ───────────────────────────────────────────────────────

def test_a_model_importable():
    """AC (a): UserPreferences importable from backend.models and instantiates without error."""
    from backend.models import UserPreferences
    obj = UserPreferences()
    assert obj is not None


# ── (b) Unique constraint blocks duplicate user_id ────────────────────────────

def test_b_unique_constraint_blocks_duplicate_user_id():
    """AC (b): Second row with same user_id raises IntegrityError."""
    uid = _make_user("up_b")
    try:
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                _insert_prefs(conn, uid)
                _insert_prefs(conn, uid)
    finally:
        _drop_user(uid)


# ── (c) Default row exists after migration ────────────────────────────────────

def test_c_default_row_created_at_migration():
    """AC (c): At least one user_preferences row exists (migration seeded default user)."""
    with engine.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM user_preferences")).scalar()
    assert count >= 1, "Migration must insert at least one default user_preferences row"


# ── (d) estimate_tss_for_workout reads FTP from user_preferences ───────────────

def test_d_estimate_tss_reads_ftp_from_user_preferences():
    """AC (d): When user_preferences.ftp_w=300, TSS uses 300 not the hardcoded 280."""
    uid = _make_user("up_d")
    try:
        with engine.begin() as conn:
            _insert_prefs(conn, uid, ftp_w=300)
        with engine.connect() as conn:
            # power=300, FTP=300 → IF=1.0, duration=3600 → TSS=100
            workout = _MockWorkout(avg_power_w=300)
            tss, method = estimate_tss_for_workout(workout, user_id=uid, db=conn)
        assert method == "power"
        assert tss == 100
    finally:
        _drop_user(uid)


# ── (e) Falls back to defaults when row missing or ftp_w null ─────────────────

def test_e_falls_back_to_defaults_when_row_missing(caplog):
    """AC (e-1): No user_preferences row → uses default FTP_W=280, logs warning."""
    uid = _make_user("up_e1")
    try:
        with engine.connect() as conn:
            # power=FTP_W → IF=1.0 → TSS=100 confirms default was used
            workout = _MockWorkout(avg_power_w=FTP_W)
            with caplog.at_level(logging.WARNING, logger="backend.services.tss"):
                tss, method = estimate_tss_for_workout(workout, user_id=uid, db=conn)
        assert method == "power"
        assert tss == 100
        assert any("default" in r.message.lower() or "preferences" in r.message.lower()
                   for r in caplog.records)
    finally:
        _drop_user(uid)


def test_e_falls_back_to_defaults_when_ftp_w_null(caplog):
    """AC (e-2): user_preferences row present but ftp_w=NULL → uses default FTP_W=280."""
    uid = _make_user("up_e2")
    try:
        with engine.begin() as conn:
            _insert_prefs(conn, uid, ftp_w=None)
        with engine.connect() as conn:
            workout = _MockWorkout(avg_power_w=FTP_W)
            with caplog.at_level(logging.WARNING, logger="backend.services.tss"):
                tss, method = estimate_tss_for_workout(workout, user_id=uid, db=conn)
        assert method == "power"
        assert tss == 100
        assert any("default" in r.message.lower() or "null" in r.message.lower()
                   for r in caplog.records)
    finally:
        _drop_user(uid)


# ── (f) Cascade delete removes user_preferences row ──────────────────────────

def test_f_cascade_delete_removes_preferences():
    """AC (f): Deleting parent user also deletes user_preferences row."""
    uid = _make_user("up_f")
    with engine.begin() as conn:
        _insert_prefs(conn, uid)

    # Confirm row exists
    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM user_preferences WHERE user_id = :uid"), {"uid": uid}
        ).scalar()
    assert count == 1

    # Delete user — cascade should remove prefs too
    _drop_user(uid)

    with engine.connect() as conn:
        count = conn.execute(
            text("SELECT COUNT(*) FROM user_preferences WHERE user_id = :uid"), {"uid": uid}
        ).scalar()
    assert count == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Issue #357 — GET and PATCH /api/user-preferences API endpoint tests
# All tests use only HTTP calls (no direct DB access) so they work against any
# environment the server is configured for.
# ═══════════════════════════════════════════════════════════════════════════════

def _api_create_user(prefix: str = "up357") -> str:
    """Create a user via API and return its uid."""
    name = f"{prefix}_{uuid.uuid4().hex[:8]}"
    resp = httpx.post(f"{BASE}/api/users", json={"name": name}, timeout=10)
    assert resp.status_code == 201, f"User creation failed: {resp.text}"
    return resp.json()["id"]


def _api_delete_user(uid: str) -> None:
    httpx.delete(f"{BASE}/api/users/{uid}", timeout=10)


# ── (357-a) GET lazy-creates row on first call ────────────────────────────────

def test_357a_get_lazy_creates_row():
    """AC (357-a): GET for brand-new user (no prefs row) returns 200 and creates row."""
    uid = _api_create_user("up357a")
    try:
        resp = httpx.get(f"{BASE}/api/user-preferences", params={"user_id": uid}, timeout=10)
        assert resp.status_code == 200

        # Second call must still be 200 (idempotent, not duplicate)
        resp2 = httpx.get(f"{BASE}/api/user-preferences", params={"user_id": uid}, timeout=10)
        assert resp2.status_code == 200
    finally:
        _api_delete_user(uid)


# ── (357-b) GET response includes row + defaults block ────────────────────────

def test_357b_get_response_shape():
    """AC (357-b): GET response body has 'row' and 'defaults' keys with correct defaults."""
    uid = _api_create_user("up357b")
    try:
        resp = httpx.get(f"{BASE}/api/user-preferences", params={"user_id": uid}, timeout=10)
        assert resp.status_code == 200
        body = resp.json()
        assert "row" in body
        assert "defaults" in body

        defaults = body["defaults"]
        assert defaults["ftp_w"] == 280
        assert defaults["threshold_hr"] == 170
        assert defaults["threshold_pace_seconds_per_km"] == 270

        row = body["row"]
        # id and timestamps must NOT appear in row
        assert "id" not in row
        assert "created_at" not in row
        assert "updated_at" not in row
        # editable fields present
        assert "ftp_w" in row
        assert "timezone" in row
    finally:
        _api_delete_user(uid)


# ── (357-c) PATCH ftp_w to 320 persists ──────────────────────────────────────

def test_357c_patch_ftp_w_persists():
    """AC (357-c): PATCH ftp_w=320 → 200; subsequent GET shows ftp_w=320."""
    uid = _api_create_user("up357c")
    try:
        patch_resp = httpx.patch(
            f"{BASE}/api/user-preferences", json={"user_id": uid, "ftp_w": 320}, timeout=10
        )
        assert patch_resp.status_code == 200
        assert patch_resp.json()["ftp_w"] == 320

        get_resp = httpx.get(f"{BASE}/api/user-preferences", params={"user_id": uid}, timeout=10)
        assert get_resp.status_code == 200
        assert get_resp.json()["row"]["ftp_w"] == 320
    finally:
        _api_delete_user(uid)


# ── (357-d) PATCH ftp_w to null succeeds ─────────────────────────────────────

def test_357d_patch_ftp_w_null_succeeds():
    """AC (357-d): PATCH ftp_w=null (unset) returns 200 with ftp_w null."""
    uid = _api_create_user("up357d")
    try:
        # First set a value
        httpx.patch(f"{BASE}/api/user-preferences", json={"user_id": uid, "ftp_w": 300}, timeout=10)
        # Then unset it
        resp = httpx.patch(
            f"{BASE}/api/user-preferences", json={"user_id": uid, "ftp_w": None}, timeout=10
        )
        assert resp.status_code == 200
        assert resp.json()["ftp_w"] is None
    finally:
        _api_delete_user(uid)


# ── (357-e) PATCH ftp_w to 1000 returns 422 ──────────────────────────────────

def test_357e_patch_ftp_w_out_of_range():
    """AC (357-e): PATCH ftp_w=1000 (>600) returns 422."""
    uid = _api_create_user("up357e")
    try:
        resp = httpx.patch(
            f"{BASE}/api/user-preferences", json={"user_id": uid, "ftp_w": 1000}, timeout=10
        )
        assert resp.status_code == 422
    finally:
        _api_delete_user(uid)


# ── (357-f) PATCH timezone to "Asia/Bangkok" succeeds ────────────────────────

def test_357f_patch_timezone_valid():
    """AC (357-f): PATCH timezone='Asia/Bangkok' returns 200."""
    uid = _api_create_user("up357f")
    try:
        resp = httpx.patch(
            f"{BASE}/api/user-preferences",
            json={"user_id": uid, "timezone": "Asia/Bangkok"},
            timeout=10,
        )
        assert resp.status_code == 200
        assert resp.json()["timezone"] == "Asia/Bangkok"
    finally:
        _api_delete_user(uid)


# ── (357-g) PATCH timezone to "Mars/Olympus" returns 422 ─────────────────────

def test_357g_patch_timezone_invalid():
    """AC (357-g): PATCH timezone='Mars/Olympus' returns 422."""
    uid = _api_create_user("up357g")
    try:
        resp = httpx.patch(
            f"{BASE}/api/user-preferences",
            json={"user_id": uid, "timezone": "Mars/Olympus"},
            timeout=10,
        )
        assert resp.status_code == 422
    finally:
        _api_delete_user(uid)


# ── (357-h) PATCH preferred_units returns 422 ────────────────────────────────

def test_357h_patch_non_editable_field():
    """AC (357-h): PATCH preferred_units (non-editable) returns 422."""
    uid = _api_create_user("up357h")
    try:
        resp = httpx.patch(
            f"{BASE}/api/user-preferences",
            json={"user_id": uid, "preferred_units": "imperial"},
            timeout=10,
        )
        assert resp.status_code == 422
    finally:
        _api_delete_user(uid)
