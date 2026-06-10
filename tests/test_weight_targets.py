"""
Tests for issue #334: WeightTarget model and weight_targets table.
5 AC anchors: (a) import, (b) non-active duplicates OK, (c) two active → IntegrityError,
(d) all four status values accepted, (e) gain goal (target > start) accepted.
"""
import uuid
import datetime
import pytest
from decimal import Decimal
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from backend.db import engine
from backend.models import WeightTarget

_BASE = datetime.date(2099, 4, 1)  # far-future sentinel — avoids seed collisions


def _make_user(prefix: str = "wt") -> str:
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


def _insert_target(conn, uid: str, status: str = "active", *, start: float = 80.0, target: float = 70.0) -> None:
    conn.execute(
        text(
            "INSERT INTO weight_targets "
            "(user_id, start_weight_kg, start_date, target_weight_kg, target_date, status) "
            "VALUES (:uid, :sw, :sd, :tw, :td, :st)"
        ),
        {
            "uid": uid,
            "sw": start,
            "sd": str(_BASE),
            "tw": target,
            "td": str(_BASE + datetime.timedelta(days=90)),
            "st": status,
        },
    )


# ── (a) Model is importable and instantiates without error ────────────────────

def test_a_model_imports_and_instantiates():
    """AC (a): WeightTarget importable from backend.models and instantiates without error."""
    obj = WeightTarget()
    assert obj is not None


# ── (b) Multiple non-active targets for same user do not raise ────────────────

def test_b_multiple_non_active_targets_do_not_raise():
    """AC (b): Multiple 'abandoned' targets for same user all commit without error."""
    uid = _make_user("wt_b")
    try:
        with engine.begin() as conn:
            _insert_target(conn, uid, "abandoned")
            _insert_target(conn, uid, "abandoned")
            _insert_target(conn, uid, "replaced")
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM weight_targets WHERE user_id = :uid"),
                {"uid": uid},
            ).scalar()
        assert count == 3
    finally:
        _drop_user(uid)


# ── (c) Two active targets for same user → IntegrityError ────────────────────

def test_c_two_active_targets_raise_integrity_error():
    """AC (c): Inserting a second 'active' target for the same user raises IntegrityError."""
    uid = _make_user("wt_c")
    try:
        with engine.begin() as conn:
            _insert_target(conn, uid, "active")
        with pytest.raises(IntegrityError):
            with engine.begin() as conn:
                _insert_target(conn, uid, "active")
    finally:
        _drop_user(uid)


# ── (d) All four status values are accepted ───────────────────────────────────

def test_d_all_four_status_values_accepted():
    """AC (d): active, achieved, abandoned, replaced all insert without constraint violations."""
    uid = _make_user("wt_d")
    try:
        with engine.begin() as conn:
            _insert_target(conn, uid, "achieved")
            _insert_target(conn, uid, "abandoned")
            _insert_target(conn, uid, "replaced")
        # Insert 'active' separately (partial unique index allows only one)
        with engine.begin() as conn:
            _insert_target(conn, uid, "active")
        with engine.connect() as conn:
            count = conn.execute(
                text("SELECT COUNT(*) FROM weight_targets WHERE user_id = :uid"),
                {"uid": uid},
            ).scalar()
        assert count == 4
    finally:
        _drop_user(uid)


# ── (e) Gain goal (target_weight_kg > start_weight_kg) accepted ───────────────


def test_e_gain_goal_accepted():
    """AC (e): target_weight_kg > start_weight_kg (gain goal) inserts without error."""
    uid = _make_user("wt_e")
    try:
        with engine.begin() as conn:
            _insert_target(conn, uid, "active", start=60.0, target=75.0)
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT start_weight_kg, target_weight_kg "
                    "FROM weight_targets WHERE user_id = :uid"
                ),
                {"uid": uid},
            ).fetchone()
        assert row is not None
        assert Decimal(str(row.target_weight_kg)) > Decimal(str(row.start_weight_kg))
    finally:
        _drop_user(uid)


# ═══════════════════════════════════════════════════════════════════════════════
# Issue #336 — /api/weight-targets endpoint tests (a) through (k)
# ═══════════════════════════════════════════════════════════════════════════════
import time as _time
import httpx

_API_BASE = "http://127.0.0.1:9001"
_WT = "/api/weight-targets"
_WE = "/api/weight-entries"

_TODAY = datetime.date.today()
_START_DATE = (_TODAY - datetime.timedelta(days=30)).isoformat()
_TARGET_DATE = (_TODAY + datetime.timedelta(days=180)).isoformat()


@pytest.fixture(scope="module")
def http_client():
    with httpx.Client(base_url=_API_BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def api_user_id(http_client):
    """Create a dedicated test user; cascade-delete on teardown."""
    name = f"wt_api_{uuid.uuid4().hex[:8]}"
    res = http_client.post("/api/users", json={"name": name})
    assert res.status_code == 201, res.text
    uid = res.json()["id"]
    yield uid
    http_client.delete(f"/api/users/{uid}")


def _wt_post(client, user_id, **kwargs):
    payload = {
        "user_id": user_id,
        "start_weight_kg": kwargs.get("start_weight_kg", 90.0),
        "start_date": kwargs.get("start_date", _START_DATE),
        "target_weight_kg": kwargs.get("target_weight_kg", 80.0),
        "target_date": kwargs.get("target_date", _TARGET_DATE),
    }
    if "notes" in kwargs:
        payload["notes"] = kwargs["notes"]
    return client.post(_WT, json=payload)


def _log_weight(client, user_id, weight_kg, days_ago=0):
    """Log a weight entry; ignore 409 (duplicate for same date)."""
    d = (_TODAY - datetime.timedelta(days=days_ago)).isoformat()
    r = client.post(_WE, json={"user_id": user_id, "entry_date": d, "weight_kg": weight_kg})
    assert r.status_code in (201, 409), f"Unexpected status logging weight: {r.status_code} {r.text}"
    return r


def _end_target(client, user_id, target_id, status="abandoned"):
    """Log today's weight (ignore 409 duplicate) then end the target."""
    _log_weight(client, user_id, 89.0, days_ago=0)
    r = client.post(f"{_WT}/{target_id}/end", json={"status": status})
    assert r.status_code == 200, f"Failed to end target {target_id}: {r.status_code} {r.text}"
    return r


# ── (a) POST creates target successfully ──────────────────────────────────────

def test_api_a_post_creates_target(http_client, api_user_id):
    """AC (a): POST returns 201 with status='active' and expected fields."""
    res = _wt_post(http_client, api_user_id)
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["status"] == "active"
    assert body["user_id"] == api_user_id
    assert "id" in body
    assert "created_at" in body
    _end_target(http_client, api_user_id, body["id"])


# ── (b) POST with existing active target returns 409 with active_id ───────────

def test_api_b_duplicate_active_returns_409(http_client, api_user_id):
    """AC (b): Second POST while an active target exists → 409 error_code='active_target_exists' with active_id."""
    r1 = _wt_post(http_client, api_user_id)
    assert r1.status_code == 201, r1.text
    active_id = r1.json()["id"]

    r2 = _wt_post(http_client, api_user_id)
    assert r2.status_code == 409, r2.text
    body = r2.json()
    assert body["error_code"] == "active_target_exists"
    assert body["active_id"] == active_id
    assert "message" in body

    _end_target(http_client, api_user_id, active_id)


# ── (c) GET /active returns {"target": null} when no active target ─────────────

def test_api_c_get_active_no_target_returns_null(http_client, api_user_id):
    """AC (c): GET /active → 200 {"target": null} when no active target (not 404)."""
    res = http_client.get(f"{_WT}/active", params={"user_id": api_user_id})
    assert res.status_code == 200, res.text
    assert res.json() == {"target": None}


# ── (d) GET /active returns all computed fields when target exists ─────────────

def test_api_d_get_active_returns_computed_fields(http_client, api_user_id):
    """AC (d): GET /active returns target object with all required computed fields."""
    r = _wt_post(http_client, api_user_id, start_weight_kg=90.0, target_weight_kg=80.0)
    assert r.status_code == 201, r.text
    target_id = r.json()["id"]

    _log_weight(http_client, api_user_id, 88.0, days_ago=7)
    _log_weight(http_client, api_user_id, 87.5, days_ago=0)

    res = http_client.get(f"{_WT}/active", params={"user_id": api_user_id})
    assert res.status_code == 200, res.text
    t = res.json()["target"]
    assert t is not None

    required_fields = [
        "progress_pct", "kg_to_go", "days_remaining",
        "required_pace_kg_per_week", "current_pace_kg_per_week",
        "projected_end_date", "status_label",
    ]
    for field in required_fields:
        assert field in t, f"Missing computed field: {field}"

    assert t["status_label"] in ("on_track", "behind", "ahead")
    assert isinstance(t["progress_pct"], (int, float))
    assert isinstance(t["days_remaining"], int)

    _end_target(http_client, api_user_id, target_id)


# ── (e) progress_pct is correct for partial weight loss ───────────────────────

def test_api_e_progress_pct_correct(http_client, api_user_id):
    """AC (e): progress_pct = kg_lost / total_kg_to_lose * 100 (capped 0-100)."""
    # start=100, target=80 → total=20 kg to lose; current=95 → pct=25.0
    r = _wt_post(http_client, api_user_id, start_weight_kg=100.0, target_weight_kg=80.0)
    assert r.status_code == 201, r.text
    target_id = r.json()["id"]

    _log_weight(http_client, api_user_id, 95.0, days_ago=1)

    res = http_client.get(f"{_WT}/active", params={"user_id": api_user_id})
    assert res.status_code == 200, res.text
    t = res.json()["target"]
    assert t is not None
    assert abs(t["progress_pct"] - 25.0) < 0.5, (
        f"Expected progress_pct≈25.0 (kg_lost=5/total=20), got {t['progress_pct']}"
    )

    _end_target(http_client, api_user_id, target_id)


# ── (f) GET /history returns ended targets sorted by ended_at DESC ─────────────

def test_api_f_history_sorted_by_ended_at_desc(http_client, api_user_id):
    """AC (f): GET /history → 200 with non-active targets sorted ended_at DESC; computed fields present."""
    r1 = _wt_post(http_client, api_user_id)
    assert r1.status_code == 201, r1.text
    id1 = r1.json()["id"]
    _end_target(http_client, api_user_id, id1)

    _time.sleep(0.05)

    r2 = _wt_post(http_client, api_user_id)
    assert r2.status_code == 201, r2.text
    id2 = r2.json()["id"]
    _end_target(http_client, api_user_id, id2)

    res = http_client.get(f"{_WT}/history", params={"user_id": api_user_id})
    assert res.status_code == 200, res.text
    targets = res.json()["targets"]
    assert len(targets) >= 2

    ids = [t["id"] for t in targets]
    assert ids.index(id2) < ids.index(id1), "More recently ended target must come first (DESC)"

    for t in targets:
        assert "achieved_weight_kg" in t
        assert "achieved_pct" in t
        assert "duration_days" in t


# ── (g) PATCH on active target succeeds ───────────────────────────────────────

def test_api_g_patch_active_target_succeeds(http_client, api_user_id):
    """AC (g): PATCH allowed fields (target_weight_kg, target_date, notes) → 200."""
    r = _wt_post(http_client, api_user_id)
    assert r.status_code == 201, r.text
    target_id = r.json()["id"]

    res = http_client.patch(f"{_WT}/{target_id}", json={"target_weight_kg": 78.0})
    assert res.status_code == 200, res.text
    body = res.json()
    assert abs(body["target_weight_kg"] - 78.0) < 0.01

    _end_target(http_client, api_user_id, target_id)


# ── (h) PATCH on non-active target returns 422 ────────────────────────────────

def test_api_h_patch_non_active_target_returns_422(http_client, api_user_id):
    """AC (h): PATCH on ended (non-active) target → 422."""
    r = _wt_post(http_client, api_user_id)
    assert r.status_code == 201, r.text
    target_id = r.json()["id"]
    _end_target(http_client, api_user_id, target_id)

    res = http_client.patch(f"{_WT}/{target_id}", json={"notes": "too late"})
    assert res.status_code == 422, res.text


# ── (i) POST /end transitions target to achieved ──────────────────────────────

def test_api_i_end_target_achieved(http_client, api_user_id):
    """AC (i): POST /{id}/end with status='achieved' sets status, ended_at, end_weight_kg."""
    r = _wt_post(http_client, api_user_id)
    assert r.status_code == 201, r.text
    target_id = r.json()["id"]

    _log_weight(http_client, api_user_id, 85.0, days_ago=0)

    res = http_client.post(f"{_WT}/{target_id}/end", json={"status": "achieved"})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["status"] == "achieved"
    assert body["end_weight_kg"] is not None
    assert body["ended_at"] is not None


# ── (j) After ending, a new POST succeeds (no 409) ────────────────────────────

def test_api_j_new_target_after_ending_succeeds(http_client, api_user_id):
    """AC (j): After ending the active target, a new POST creates successfully (no 409)."""
    r1 = _wt_post(http_client, api_user_id)
    assert r1.status_code == 201, r1.text
    _end_target(http_client, api_user_id, r1.json()["id"])

    r2 = _wt_post(http_client, api_user_id)
    assert r2.status_code == 201, f"Expected 201 after previous target was ended: {r2.text}"
    _end_target(http_client, api_user_id, r2.json()["id"])


# ── (k) POST /end with no recent weight entry returns 422 ─────────────────────

def test_api_k_end_without_recent_weight_returns_422(http_client):
    """AC (k): POST /end when no weight_entries within 7 days → 422 with guidance message."""
    name = f"wt_k_{uuid.uuid4().hex[:8]}"
    res = http_client.post("/api/users", json={"name": name})
    assert res.status_code == 201, res.text
    uid_k = res.json()["id"]

    try:
        r = _wt_post(http_client, uid_k)
        assert r.status_code == 201, r.text
        target_id = r.json()["id"]

        res = http_client.post(f"{_WT}/{target_id}/end", json={"status": "achieved"})
        assert res.status_code == 422, res.text
        detail = res.json().get("detail", "")
        assert "Log a recent weight" in detail, f"Expected guidance message, got: {detail!r}"
    finally:
        http_client.delete(f"/api/users/{uid_k}")
