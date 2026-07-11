"""Tests for today's training recommendation (issue #1352).

AC coverage:
- AC1: GET /api/training/today-recommendation returns planned session summary,
       recommendation, reason, and inputs (readiness, verdict, active_injuries).
- AC2: Deterministic rule matrix:
       verdict back_off + hard session → downgrade
       verdict back_off + easy session → keep
       active illness / readiness < 35 → rest
       verdict hold + hard session → downgrade
       verdict hold + easy session → keep
       verdict build + hard session → keep
       no planned session → no_plan
- AC3: API endpoint returns 200 with correct shape.
- AC4: Apply action: PATCH /api/planned-sessions/{id} converts hard → easy.
- AC5: No-plan case: recommendation is no_plan when no session exists for today.
"""
import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.db import engine
from backend.main import app
from backend.models import DailyMetric, DailyReadiness, PlannedSession, User
from backend.services.today_recommendation import (
    READINESS_REST_THRESHOLD,
    compute_today_recommendation,
    is_hard_session,
)

client = TestClient(app, raise_server_exceptions=True)

# ── Pure-function unit tests (no DB, no HTTP) ─────────────────────────────────

_EASY_BLOCKS = [
    {"phase": "warmup", "duration_min": 10, "repeat": None, "rest_min": None, "target": "easy"},
    {"phase": "main", "duration_min": 30, "repeat": None, "rest_min": None, "target": "easy, conversational"},
    {"phase": "cooldown", "duration_min": 5, "repeat": None, "rest_min": None, "target": "easy"},
]

_INTERVAL_BLOCKS = [
    {"phase": "warmup", "duration_min": 10, "repeat": None, "rest_min": None, "target": "easy"},
    {"phase": "intervals", "duration_min": 5, "repeat": 6, "rest_min": 2, "target": "hard — vo2 pace"},
    {"phase": "cooldown", "duration_min": 8, "repeat": None, "rest_min": None, "target": "easy"},
]

_TEMPO_BLOCKS = [
    {"phase": "warmup", "duration_min": 10, "repeat": None, "rest_min": None, "target": "easy"},
    {"phase": "main", "duration_min": 20, "repeat": None, "rest_min": None, "target": "tempo — comfortably hard"},
    {"phase": "cooldown", "duration_min": 8, "repeat": None, "rest_min": None, "target": "easy"},
]


# ── AC2: is_hard_session classification ──────────────────────────────────────

def test_run_with_interval_blocks_is_hard():
    assert is_hard_session("run", "Intervals", {"blocks": _INTERVAL_BLOCKS}) is True


def test_run_with_tempo_blocks_is_hard():
    assert is_hard_session("run", "Tempo run", {"blocks": _TEMPO_BLOCKS}) is True


def test_run_with_easy_blocks_is_not_hard():
    assert is_hard_session("run", "Easy run", {"blocks": _EASY_BLOCKS}) is False


def test_run_named_long_run_is_hard():
    assert is_hard_session("run", "Long run Sunday", None) is True


def test_rest_session_never_hard():
    assert is_hard_session("rest", None, None) is False


def test_strength_with_hard_name_is_hard():
    assert is_hard_session("strength", "Hard strength session", None) is True


def test_strength_with_normal_name_is_not_hard():
    assert is_hard_session("strength", "Upper body", None) is False


# ── AC2: compute_today_recommendation rule matrix ────────────────────────────

def _rec(*, session_type, session_name=None, structure=None,
         readiness=75, verdict="build", injuries=None):
    return compute_today_recommendation(
        session_type=session_type,
        session_name=session_name,
        session_structure=structure,
        readiness_score=readiness,
        verdict=verdict,
        active_injuries=injuries or [],
    )


def test_no_plan_returns_no_plan():
    r = _rec(session_type=None)
    assert r["recommendation"] == "no_plan"


def test_readiness_below_threshold_returns_rest():
    r = _rec(session_type="run", session_name="Intervals",
             structure={"blocks": _INTERVAL_BLOCKS},
             readiness=READINESS_REST_THRESHOLD - 1)
    assert r["recommendation"] == "rest"
    assert str(READINESS_REST_THRESHOLD - 1) in r["reason"]


def test_readiness_exactly_at_threshold_does_not_rest():
    # < 35, not <=35; score == 35 should not trigger rest
    r = _rec(session_type="run", session_name="Intervals",
             structure={"blocks": _INTERVAL_BLOCKS},
             readiness=READINESS_REST_THRESHOLD)
    assert r["recommendation"] != "rest"


def test_active_injuries_returns_rest():
    r = _rec(session_type="run", session_name="Easy run",
             structure={"blocks": _EASY_BLOCKS},
             readiness=70, injuries=["left knee"])
    assert r["recommendation"] == "rest"


def test_back_off_plus_hard_run_downgrades():
    r = _rec(session_type="run", session_name="Intervals",
             structure={"blocks": _INTERVAL_BLOCKS},
             verdict="back_off")
    assert r["recommendation"] == "downgrade"
    assert r["apply_patch"] is not None


def test_back_off_plus_easy_run_keeps():
    r = _rec(session_type="run", session_name="Easy run",
             structure={"blocks": _EASY_BLOCKS},
             verdict="back_off")
    assert r["recommendation"] == "keep"


def test_hold_plus_hard_run_downgrades():
    r = _rec(session_type="run", session_name="Tempo",
             structure={"blocks": _TEMPO_BLOCKS},
             verdict="hold")
    assert r["recommendation"] == "downgrade"
    assert r["apply_patch"] is not None


def test_hold_plus_easy_run_keeps():
    r = _rec(session_type="run", session_name="Easy run",
             structure={"blocks": _EASY_BLOCKS},
             verdict="hold")
    assert r["recommendation"] == "keep"


def test_build_plus_hard_run_keeps():
    r = _rec(session_type="run", session_name="Intervals",
             structure={"blocks": _INTERVAL_BLOCKS},
             verdict="build", readiness=80)
    assert r["recommendation"] == "keep"


def test_downgrade_apply_patch_has_easy_blocks():
    r = _rec(session_type="run", session_name="6x800m intervals",
             structure={"blocks": _INTERVAL_BLOCKS},
             verdict="back_off")
    patch = r["apply_patch"]
    assert patch is not None
    new_blocks = patch["structure"]["blocks"]
    for block in new_blocks:
        assert "easy" in (block.get("target") or "").lower()


def test_downgrade_apply_patch_preserves_total_duration():
    # total: warmup 10 + intervals 5*6=30 + cooldown 8 = 48 min
    r = _rec(session_type="run", session_name="6x800m intervals",
             structure={"blocks": _INTERVAL_BLOCKS},
             verdict="back_off")
    patch = r["apply_patch"]
    old_total = sum(
        (b["duration_min"] or 0) * max(1, b.get("repeat") or 1)
        for b in _INTERVAL_BLOCKS
    )
    new_total = sum(
        (b["duration_min"] or 0) * max(1, b.get("repeat") or 1)
        for b in patch["structure"]["blocks"]
    )
    assert new_total == old_total


def test_rest_recommendation_has_no_apply_patch():
    r = _rec(session_type="run", session_name="Intervals",
             readiness=20)
    assert r["recommendation"] == "rest"
    assert r["apply_patch"] is None


# ── AC1 & AC3: HTTP endpoint shape ───────────────────────────────────────────

def _make_user(db, suffix="rec1352"):
    u = User(
        id=uuid.uuid4(),
        name=f"test-{suffix}",
        password_hash="x",
        is_active=True,
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture()
def rec_client():
    """TestClient with a session-authenticated user, today's DailyReadiness row,
    and a hard interval run planned for today."""
    today = date.today()
    with Session(engine) as db:
        u = _make_user(db, "rec1352a")
        uid = u.id

        dm_id = uuid.uuid4()
        dm = DailyMetric(
            id=dm_id,
            user_id=uid,
            metric_date=today,
            resting_hr=50,
            hrv=65,
            sleep_hours=8,
            sleep_quality=4,
            energy=4,
            mood=4,
        )
        db.add(dm)
        db.flush()

        dr = DailyReadiness(
            id=uuid.uuid4(),
            user_id=uid,
            date=today,
            score=75,
            components={},
            daily_metric_id=dm_id,
        )
        db.add(dr)

        ps = PlannedSession(
            id=uuid.uuid4(),
            user_id=uid,
            planned_date=today,
            session_type="run",
            name="6×800m intervals",
            structure={"blocks": _INTERVAL_BLOCKS},
            status="planned",
        )
        db.add(ps)
        db.commit()
        ps_id = str(ps.id)

    from backend.main import resolve_user

    def _override():
        with Session(engine) as db2:
            return db2.get(User, uid)

    app.dependency_overrides[resolve_user] = _override
    yield client, ps_id, uid
    app.dependency_overrides.pop(resolve_user, None)
    with Session(engine) as db:
        db.query(DailyReadiness).filter(DailyReadiness.user_id == uid).delete()
        db.query(DailyMetric).filter(DailyMetric.user_id == uid).delete()
        db.query(PlannedSession).filter(PlannedSession.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def test_endpoint_returns_200_with_required_keys(rec_client):
    c, ps_id, uid = rec_client
    resp = c.get("/api/training/today-recommendation")
    assert resp.status_code == 200
    data = resp.json()
    assert "recommendation" in data
    assert "reason" in data
    assert "planned_session" in data
    assert "inputs" in data
    assert "readiness" in data["inputs"]
    assert "verdict" in data["inputs"]
    assert "active_injuries" in data["inputs"]


def test_endpoint_recommendation_values_are_valid(rec_client):
    c, ps_id, uid = rec_client
    resp = c.get("/api/training/today-recommendation")
    data = resp.json()
    assert data["recommendation"] in ("keep", "downgrade", "rest", "no_plan")


def test_endpoint_planned_session_summary_present(rec_client):
    c, ps_id, uid = rec_client
    resp = c.get("/api/training/today-recommendation")
    data = resp.json()
    ps = data["planned_session"]
    assert ps is not None
    assert ps["id"] == ps_id
    assert ps["session_type"] == "run"


# ── AC5: No-plan case ─────────────────────────────────────────────────────────

@pytest.fixture()
def no_plan_client():
    today = date.today()
    with Session(engine) as db:
        u = _make_user(db, "rec1352b")
        uid = u.id
        db.commit()

    from backend.main import resolve_user

    def _override():
        with Session(engine) as db2:
            return db2.get(User, uid)

    app.dependency_overrides[resolve_user] = _override
    yield client, uid
    app.dependency_overrides.pop(resolve_user, None)
    with Session(engine) as db:
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def test_no_plan_endpoint_returns_no_plan(no_plan_client):
    c, uid = no_plan_client
    resp = c.get("/api/training/today-recommendation")
    assert resp.status_code == 200
    data = resp.json()
    assert data["recommendation"] == "no_plan"
    assert data["planned_session"] is None


# ── AC4: Apply action mutates only today's session ────────────────────────────

@pytest.fixture()
def apply_client():
    """Two planned sessions: one today (hard), one tomorrow.
    We'll verify only today's is mutated by the apply action."""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    with Session(engine) as db:
        u = _make_user(db, "rec1352c")
        uid = u.id

        ps_today = PlannedSession(
            id=uuid.uuid4(),
            user_id=uid,
            planned_date=today,
            session_type="run",
            name="Tempo run",
            structure={"blocks": _TEMPO_BLOCKS},
            status="planned",
        )
        ps_tomorrow = PlannedSession(
            id=uuid.uuid4(),
            user_id=uid,
            planned_date=tomorrow,
            session_type="run",
            name="Tempo run",
            structure={"blocks": _TEMPO_BLOCKS},
            status="planned",
        )
        db.add_all([ps_today, ps_tomorrow])
        db.commit()
        today_id = str(ps_today.id)
        tomorrow_id = str(ps_tomorrow.id)

    from backend.main import resolve_user

    def _override():
        with Session(engine) as db2:
            return db2.get(User, uid)

    app.dependency_overrides[resolve_user] = _override
    yield client, today_id, tomorrow_id, uid
    app.dependency_overrides.pop(resolve_user, None)
    with Session(engine) as db:
        db.query(PlannedSession).filter(PlannedSession.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def test_apply_patch_mutates_only_todays_session(apply_client):
    c, today_id, tomorrow_id, uid = apply_client
    # Downgrade today's session by PATCHing via the existing API
    easy_structure = {
        "blocks": [
            {"phase": "main", "duration_min": 38, "repeat": None, "rest_min": None,
             "target": "easy, conversational"}
        ]
    }
    resp = c.patch(f"/api/planned-sessions/{today_id}", json={
        "name": "Easy run",
        "structure": easy_structure,
    })
    assert resp.status_code == 200
    patched = resp.json()
    assert "easy" in patched["name"].lower()

    # Tomorrow's session is unchanged — verify via direct PATCH read-back
    resp2 = c.get(
        "/api/planned-sessions",
        params={"from": str(date.today() + timedelta(days=1)),
                "to": str(date.today() + timedelta(days=1))},
    )
    assert resp2.status_code == 200
    bundle = resp2.json()
    # The bundle shape is {"from","to","days":[{"date","planned":[...],"unplanned":[...]}]}
    all_planned = [ps for day in bundle["days"] for ps in day.get("planned", [])]
    tomorrow_sessions = [s for s in all_planned if s["id"] == tomorrow_id]
    assert len(tomorrow_sessions) == 1
    assert tomorrow_sessions[0]["name"] == "Tempo run"
