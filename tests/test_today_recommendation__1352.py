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
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.models import PlannedSession, User
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

def _make_session_mock(planned_rows, readiness_score):
    """Build a mock DB session that returns pre-built planned/readiness data."""
    mock_readiness = None
    if readiness_score is not None:
        mock_readiness = MagicMock()
        mock_readiness.score = readiness_score

    mock_db = MagicMock()

    def _query(model_or_col):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.first.return_value = None
        q.all.return_value = []
        if model_or_col is PlannedSession:
            q.all.return_value = planned_rows
        elif model_or_col is type(mock_readiness) and mock_readiness is not None:
            q.first.return_value = mock_readiness
        return q

    mock_db.query.side_effect = _query
    # DailyReadiness.filter chain — differentiate by checking if result is readiness
    # The endpoint does db.query(DailyReadiness).filter(...).first()
    # We detect DailyReadiness by checking the class imported in main
    from backend.models import DailyReadiness as _DR

    def _query2(model_or_col):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.all.return_value = []
        q.first.return_value = None
        if model_or_col is PlannedSession:
            q.all.return_value = planned_rows
        elif model_or_col is _DR:
            q.first.return_value = mock_readiness
        return q

    mock_db.query.side_effect = _query2
    mock_cm = MagicMock()
    mock_cm.__enter__.return_value = mock_db
    mock_cm.__exit__.return_value = False
    return mock_cm


@pytest.fixture()
def rec_client():
    """Mocked client: user with today's readiness=75 and a hard interval run."""
    today = date.today()
    uid = uuid.uuid4()
    ps_id = str(uuid.uuid4())

    mock_ps = MagicMock()
    mock_ps.id = uuid.UUID(ps_id)
    mock_ps.user_id = uid
    mock_ps.planned_date = today
    mock_ps.session_type = "run"
    mock_ps.name = "6×800m intervals"
    mock_ps.structure = {"blocks": _INTERVAL_BLOCKS}
    mock_ps.status = "planned"
    mock_ps.matched_workout_id = None
    mock_ps.notes = None
    mock_ps.created_at = None
    mock_ps.updated_at = None

    mock_user = MagicMock(spec=User)
    mock_user.id = uid

    from backend.main import resolve_user
    app.dependency_overrides[resolve_user] = lambda: mock_user

    with patch("backend.main.Session", return_value=_make_session_mock([mock_ps], 75.0)), \
         patch("backend.main._resolve_current_verdict", return_value={"verdict": "hold"}):
        yield client, ps_id, uid

    app.dependency_overrides.pop(resolve_user, None)


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
    uid = uuid.uuid4()
    mock_user = MagicMock(spec=User)
    mock_user.id = uid

    from backend.main import resolve_user
    app.dependency_overrides[resolve_user] = lambda: mock_user

    with patch("backend.main.Session", return_value=_make_session_mock([], None)), \
         patch("backend.main._resolve_current_verdict", return_value={"verdict": "hold"}):
        yield client, uid

    app.dependency_overrides.pop(resolve_user, None)


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
    """Two mocked planned sessions: today (hard) and tomorrow.
    PATCH today → today mutates; GET tomorrow → tomorrow unchanged."""
    today = date.today()
    tomorrow = today + timedelta(days=1)
    uid = uuid.uuid4()
    today_id = str(uuid.uuid4())
    tomorrow_id = str(uuid.uuid4())
    today_uuid = uuid.UUID(today_id)
    tomorrow_uuid = uuid.UUID(tomorrow_id)

    # Mutable mock for today (PATCH will set .name, .structure, .updated_at)
    today_ps = MagicMock()
    today_ps.id = today_uuid
    today_ps.user_id = uid
    today_ps.planned_date = today
    today_ps.session_type = "run"
    today_ps.name = "Tempo run"
    today_ps.structure = {"blocks": _TEMPO_BLOCKS}
    today_ps.status = "planned"
    today_ps.matched_workout_id = None
    today_ps.notes = None
    today_ps.created_at = None
    today_ps.updated_at = None

    # Immutable mock for tomorrow
    tomorrow_ps = MagicMock()
    tomorrow_ps.id = tomorrow_uuid
    tomorrow_ps.user_id = uid
    tomorrow_ps.planned_date = tomorrow
    tomorrow_ps.session_type = "run"
    tomorrow_ps.name = "Tempo run"
    tomorrow_ps.structure = {"blocks": _TEMPO_BLOCKS}
    tomorrow_ps.status = "planned"
    tomorrow_ps.matched_workout_id = None
    tomorrow_ps.notes = None
    tomorrow_ps.created_at = None
    tomorrow_ps.updated_at = None

    ps_by_id = {today_uuid: today_ps, tomorrow_uuid: tomorrow_ps}

    def _make_apply_session():
        mock_db = MagicMock()
        mock_db.get.side_effect = lambda model, pid: ps_by_id.get(pid)

        def _query(model_or_col):
            q = MagicMock()
            q.filter.return_value = q
            q.order_by.return_value = q
            q.all.return_value = [tomorrow_ps] if model_or_col is PlannedSession else []
            q.first.return_value = None
            return q

        mock_db.query.side_effect = _query
        mock_cm = MagicMock()
        mock_cm.__enter__.return_value = mock_db
        mock_cm.__exit__.return_value = False
        return mock_cm

    mock_user = MagicMock(spec=User)
    mock_user.id = uid

    from backend.main import resolve_user
    app.dependency_overrides[resolve_user] = lambda: mock_user

    with patch("backend.main.Session", side_effect=lambda *a, **kw: _make_apply_session()):
        yield client, today_id, tomorrow_id, uid

    app.dependency_overrides.pop(resolve_user, None)


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
