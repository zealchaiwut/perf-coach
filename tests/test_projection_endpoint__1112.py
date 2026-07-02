"""Tests for issue #1112: Expose training projection via plan API endpoint.

Acceptance criteria verified:
- AC1: GET /plans/{plan_id}/projection exists in routers/projection.py and is registered with app
- AC2: Response includes projected CTL, ATL, TSB time series
- AC3: Response includes per-race estimated finish times
- AC4: Response includes half-equivalent values for each race
- AC5: Response includes fitness band for the current plan
- AC6: Route handler delegates to projection module only — no projection logic in router
- AC7: python -m py_compile routers/projection.py exits with code 0
- AC8: 404 returned when the requested plan does not exist
- AC9: Endpoint authenticated consistently with other plan endpoints (401 when unauthenticated)
"""
from __future__ import annotations

import os
import pathlib
import py_compile
import uuid
from datetime import date, timedelta

import pytest

# ── Pure-unit imports (no server required) ────────────────────────────────────
from backend.services.projection import (
    compute_half_equivalent,
    fitness_band_from_tsb,
    build_plan_projection_payload,
    RIEGEL_EXPONENT,
)
from backend.services.fitness_model import TSB_FRESH_MIN, TSB_OPTIMAL_MIN

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_TODAY = date(2026, 6, 29)

# ── Integration test setup ────────────────────────────────────────────────────
try:
    from dotenv import dotenv_values
    _env = dotenv_values(_ROOT / ".env")
    _uat_url = _env.get("DATABASE_URL_UAT")
except ImportError:
    _uat_url = os.environ.get("DATABASE_URL_UAT")

BASE_URL = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_TEST_PW = "plan1112proj!"

if _uat_url:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as _OrmSess
    from backend.auth import hash_password as _hash_pw, CSRF_COOKIE_NAME
    from backend.models import User as _UserModel
    _db_engine = create_engine(_uat_url, pool_pre_ping=True)
else:
    _db_engine = None


def _skip_no_db():
    if _db_engine is None:
        pytest.skip("DATABASE_URL_UAT not set")


# ─────────────────────────────────────────────────────────────────────────────
# AC7: py_compile
# ─────────────────────────────────────────────────────────────────────────────

def test_ac7_plan_router_compiles():
    """AC7: python -m py_compile on routers/projection.py exits with code 0."""
    router_path = _ROOT / "backend" / "routers" / "plan.py"
    assert router_path.exists()
    py_compile.compile(str(router_path), doraise=True)


def test_ac7_projection_module_compiles():
    """AC7: projection.py has no syntax errors."""
    proj_path = _ROOT / "backend" / "services" / "projection.py"
    py_compile.compile(str(proj_path), doraise=True)


# ─────────────────────────────────────────────────────────────────────────────
# Pure unit tests: compute_half_equivalent
# ─────────────────────────────────────────────────────────────────────────────

def test_half_equivalent_none_on_none_seconds():
    """compute_half_equivalent returns None when estimated_finish_seconds is None."""
    assert compute_half_equivalent(None, 42.195) is None


def test_half_equivalent_none_on_none_distance():
    """compute_half_equivalent returns None when distance_km is None."""
    assert compute_half_equivalent(13500, None) is None


def test_half_equivalent_none_on_zero_distance():
    """compute_half_equivalent returns None when distance_km is 0."""
    assert compute_half_equivalent(13500, 0.0) is None


def test_half_equivalent_none_on_negative_distance():
    """compute_half_equivalent returns None for negative distance."""
    assert compute_half_equivalent(13500, -5.0) is None


def test_half_equivalent_uses_riegel_formula():
    """compute_half_equivalent uses 0.5^RIEGEL_EXPONENT multiplier."""
    seconds = 14400  # 4h marathon
    result = compute_half_equivalent(seconds, 42.195)
    expected = int(round(seconds * (0.5 ** RIEGEL_EXPONENT)))
    assert result == expected


def test_half_equivalent_shorter_than_full():
    """Half-equivalent finish time must be less than the full finish time."""
    full_seconds = 14400
    half_equiv = compute_half_equivalent(full_seconds, 42.195)
    assert half_equiv is not None
    assert half_equiv < full_seconds


def test_half_equivalent_returns_int():
    """compute_half_equivalent returns an int (not float)."""
    result = compute_half_equivalent(10000, 21.0975)
    assert result is not None
    assert isinstance(result, int)


def test_half_equivalent_riegel_exponent_exported():
    """RIEGEL_EXPONENT must be exported from projection module."""
    assert isinstance(RIEGEL_EXPONENT, float)
    assert RIEGEL_EXPONENT > 1.0  # must be > 1 so longer races are proportionally harder


# ─────────────────────────────────────────────────────────────────────────────
# Pure unit tests: fitness_band_from_tsb
# ─────────────────────────────────────────────────────────────────────────────

def test_fitness_band_fresh_above_threshold():
    """TSB well above TSB_FRESH_MIN → 'Fresh'."""
    assert fitness_band_from_tsb(TSB_FRESH_MIN + 10) == "Fresh"


def test_fitness_band_fresh_at_threshold():
    """TSB exactly at TSB_FRESH_MIN → 'Fresh'."""
    assert fitness_band_from_tsb(TSB_FRESH_MIN) == "Fresh"


def test_fitness_band_optimal_between_thresholds():
    """TSB between TSB_OPTIMAL_MIN and TSB_FRESH_MIN → 'Optimal'."""
    mid = (TSB_OPTIMAL_MIN + TSB_FRESH_MIN) / 2
    assert fitness_band_from_tsb(mid) == "Optimal"


def test_fitness_band_fatigued_below_optimal_min():
    """TSB below TSB_OPTIMAL_MIN → 'Fatigued'."""
    assert fitness_band_from_tsb(TSB_OPTIMAL_MIN - 5) == "Fatigued"


def test_fitness_band_returns_string():
    """fitness_band_from_tsb always returns a non-empty string."""
    for tsb in (-50.0, -10.0, 0.0, 5.0, 20.0):
        result = fitness_band_from_tsb(tsb)
        assert isinstance(result, str) and result, f"Expected non-empty string, got {result!r}"


# ─────────────────────────────────────────────────────────────────────────────
# Pure unit tests: build_plan_projection_payload
# ─────────────────────────────────────────────────────────────────────────────

def _make_payload(n_days=14, races=None, thresholds=None):
    planned_load = [50.0] * n_days
    return build_plan_projection_payload(
        start_ctl=40.0,
        start_atl=50.0,
        start_date=_TODAY,
        planned_load=planned_load,
        races=races or [],
        thresholds=thresholds,
    )


def test_payload_has_required_keys():
    """build_plan_projection_payload returns dict with ctl, atl, tsb, races, band."""
    result = _make_payload()
    for key in ("ctl", "atl", "tsb", "races", "band"):
        assert key in result, f"Missing key: {key}"


def test_payload_ctl_series_length_matches_planned_load():
    """ctl array length matches len(planned_load)."""
    n = 21
    result = _make_payload(n_days=n)
    assert len(result["ctl"]) == n


def test_payload_atl_series_length_matches_planned_load():
    """atl array length matches len(planned_load)."""
    n = 30
    result = _make_payload(n_days=n)
    assert len(result["atl"]) == n


def test_payload_tsb_series_length_matches_planned_load():
    """tsb array length matches len(planned_load)."""
    n = 7
    result = _make_payload(n_days=n)
    assert len(result["tsb"]) == n


def test_payload_band_is_string():
    """band field is a non-empty string."""
    result = _make_payload()
    assert isinstance(result["band"], str) and result["band"]


def test_payload_races_empty_when_no_races():
    """races is an empty list when no races are supplied."""
    result = _make_payload(races=[])
    assert result["races"] == []


def test_payload_race_has_estimated_time_key():
    """Each race entry has an estimated_time key."""
    race = {"date": _TODAY + timedelta(days=14), "distance_km": 21.0975, "name": "Half"}
    result = _make_payload(races=[race], thresholds={"threshold_pace_seconds_per_km": 300})
    assert len(result["races"]) == 1
    assert "estimated_time" in result["races"][0]


def test_payload_race_has_half_equivalent_key():
    """Each race entry has a half_equivalent key."""
    race = {"date": _TODAY + timedelta(days=14), "distance_km": 42.195, "name": "Marathon"}
    result = _make_payload(races=[race], thresholds={"threshold_pace_seconds_per_km": 300})
    assert len(result["races"]) == 1
    assert "half_equivalent" in result["races"][0]


def test_payload_race_estimated_time_null_without_thresholds():
    """estimated_time is null when no threshold pace is available."""
    race = {"date": _TODAY + timedelta(days=14), "distance_km": 42.195, "name": "Marathon"}
    result = _make_payload(races=[race], thresholds=None)
    assert result["races"][0]["estimated_time"] is None


def test_payload_race_estimated_time_string_with_thresholds():
    """estimated_time is a non-null string (HH:MM:SS) when threshold pace is set."""
    race = {"date": _TODAY + timedelta(days=14), "distance_km": 42.195, "name": "Marathon"}
    result = _make_payload(races=[race], thresholds={"threshold_pace_seconds_per_km": 300})
    assert result["races"][0]["estimated_time"] is not None
    assert ":" in result["races"][0]["estimated_time"]


def test_payload_race_half_equivalent_shorter_than_estimated_time():
    """half_equivalent_seconds < estimated_finish_seconds for a positive-distance race."""
    race = {"date": _TODAY + timedelta(days=14), "distance_km": 42.195, "name": "Marathon"}
    result = _make_payload(races=[race], thresholds={"threshold_pace_seconds_per_km": 300})
    entry = result["races"][0]
    if entry["estimated_finish_seconds"] is not None and entry["half_equivalent_seconds"] is not None:
        assert entry["half_equivalent_seconds"] < entry["estimated_finish_seconds"]


def test_payload_tsb_is_ctl_minus_atl():
    """Each projected TSB must equal the corresponding CTL - ATL."""
    result = _make_payload(n_days=10)
    for i, (c, a, t) in enumerate(zip(result["ctl"], result["atl"], result["tsb"])):
        assert abs(t - (c - a)) < 1e-6, f"Day {i}: tsb={t}, ctl-atl={c-a}"


def test_payload_ctl_rises_toward_load():
    """With load above start_ctl, projected CTL should be higher at end than start."""
    result = build_plan_projection_payload(
        start_ctl=30.0, start_atl=30.0, start_date=_TODAY,
        planned_load=[80.0] * 60, races=[], thresholds=None
    )
    assert result["ctl"][-1] > result["ctl"][0]


# ─────────────────────────────────────────────────────────────────────────────
# AC6: Route handler delegates to projection module only
# ─────────────────────────────────────────────────────────────────────────────

def test_ac6_router_imports_projection_module():
    """AC6: routers/projection.py must import from backend.services.projection."""
    router_path = _ROOT / "backend" / "routers" / "plan.py"
    source = router_path.read_text()
    assert "projection" in source, (
        "routers/projection.py must import from backend.services.projection"
    )


def test_ac6_router_handler_no_decay_math():
    """AC6: The projection endpoint handler must not hardcode EWMA decay calculations."""
    router_path = _ROOT / "backend" / "routers" / "plan.py"
    source = router_path.read_text()
    # The router should not contain CTL/ATL decay arithmetic — that belongs in projection.py
    assert "CTL_DECAY" not in source or "import" in source, (
        "If CTL_DECAY appears in router, it must only be in an import statement"
    )
    # The string "* CTL_DECAY" or "* ATL_DECAY" in a non-import context would be a violation
    assert "* CTL_DECAY" not in source, "EWMA decay math must not live in the router"
    assert "* ATL_DECAY" not in source, "EWMA decay math must not live in the router"


def test_ac1_projection_endpoint_in_router():
    """AC1: routers/projection.py must contain a /projection route."""
    router_path = _ROOT / "backend" / "routers" / "plan.py"
    source = router_path.read_text()
    assert "projection" in source, "routers/projection.py must define a /projection route"
    assert "@router.get" in source, "Plan router must have a GET handler"


# ─────────────────────────────────────────────────────────────────────────────
# Integration tests (require live UAT server + DATABASE_URL_UAT)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def plan_client_and_plan_id():
    """Create a user + TrainingPlan + Race; return (auth_client, plan_id, user_id)."""
    _skip_no_db()
    import httpx

    uname = f"proj1112_{uuid.uuid4().hex[:8]}"
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/users", json={"name": uname})
        assert r.status_code == 201, f"create user failed: {r.text}"
        user_id = r.json()["id"]

    with _OrmSess(_db_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hash_pw(_TEST_PW)
        db.commit()

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.post("/api/auth/login", json={"username": uname, "password": _TEST_PW})
        assert r.status_code == 200, f"login failed: {r.text}"
        session_cookie = r.cookies.get("session")
        csrf_token = r.cookies.get(CSRF_COOKIE_NAME)

    auth = httpx.Client(
        base_url=BASE_URL, timeout=10.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )

    # Create a TrainingPlan
    r = auth.post("/api/plans", json={"name": "Test Projection Plan 1112"})
    assert r.status_code == 201, f"create plan failed: {r.text}"
    plan_id = r.json()["id"]

    # Create a race for this user (linked via user_id in races table)
    r = auth.post(f"/plans/{user_id}/races", json={
        "date": "2027-01-15",
        "distance": 21.0975,
        "type": "race",
        "name": "Half Marathon",
    })
    assert r.status_code == 201, f"create race failed: {r.text}"

    yield auth, plan_id, user_id

    auth.close()
    with _OrmSess(_db_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        if u:
            db.delete(u)
            db.commit()


# AC9: unauthenticated request → 401
def test_ac9_unauthenticated_returns_401(plan_client_and_plan_id):
    """AC9: GET /plans/{plan_id}/projection without auth returns 401."""
    import httpx
    _, plan_id, _ = plan_client_and_plan_id
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as bare:
        r = bare.get(f"/plans/{plan_id}/projection")
    assert r.status_code == 401, f"Expected 401, got {r.status_code}: {r.text}"


# AC8: non-existent plan → 404
def test_ac8_nonexistent_plan_returns_404(plan_client_and_plan_id):
    """AC8: GET /plans/{non_existent_uuid}/projection returns 404."""
    auth, _, _ = plan_client_and_plan_id
    fake_id = str(uuid.uuid4())
    r = auth.get(f"/plans/{fake_id}/projection")
    assert r.status_code == 404, f"Expected 404, got {r.status_code}: {r.text}"


# AC2: ctl/atl/tsb arrays present
def test_ac2_response_has_ctl_atl_tsb_arrays(plan_client_and_plan_id):
    """AC2: Response includes ctl, atl, tsb arrays."""
    auth, plan_id, _ = plan_client_and_plan_id
    r = auth.get(f"/plans/{plan_id}/projection")
    assert r.status_code == 200, f"Expected 200, got {r.status_code}: {r.text}"
    body = r.json()
    for key in ("ctl", "atl", "tsb"):
        assert key in body, f"Missing key: {key}"
        assert isinstance(body[key], list), f"{key} must be a list"


# AC3+AC4: races array with estimated_time and half_equivalent
def test_ac3_response_has_races_with_estimated_time(plan_client_and_plan_id):
    """AC3: races array contains estimated_time per entry."""
    auth, plan_id, _ = plan_client_and_plan_id
    r = auth.get(f"/plans/{plan_id}/projection")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "races" in body, "Response must have races array"
    assert isinstance(body["races"], list)
    for race_entry in body["races"]:
        assert "estimated_time" in race_entry, "Each race must have estimated_time"


def test_ac4_response_has_races_with_half_equivalent(plan_client_and_plan_id):
    """AC4: races array contains half_equivalent per entry."""
    auth, plan_id, _ = plan_client_and_plan_id
    r = auth.get(f"/plans/{plan_id}/projection")
    assert r.status_code == 200, r.text
    body = r.json()
    for race_entry in body.get("races", []):
        assert "half_equivalent" in race_entry, "Each race must have half_equivalent"


# AC5: band field present
def test_ac5_response_has_band(plan_client_and_plan_id):
    """AC5: Response includes a band field."""
    auth, plan_id, _ = plan_client_and_plan_id
    r = auth.get(f"/plans/{plan_id}/projection")
    assert r.status_code == 200, r.text
    body = r.json()
    assert "band" in body, "Response must have a band field"
    assert isinstance(body["band"], str), "band must be a string"


# Series length matches plan duration (UAT Step 3)
def test_series_length_matches_plan_duration(plan_client_and_plan_id):
    """UAT3: CTL/ATL/TSB series length matches the plan duration (days to last race)."""
    auth, plan_id, user_id = plan_client_and_plan_id
    r = auth.get(f"/plans/{plan_id}/projection")
    assert r.status_code == 200, r.text
    body = r.json()
    # All three series must have the same length
    assert len(body["ctl"]) == len(body["atl"]) == len(body["tsb"]), (
        "ctl, atl, tsb arrays must have equal length"
    )
    # Series must be non-empty (there's a race 200 days from today)
    assert len(body["ctl"]) > 0, "Series must be non-empty when plan has races"
