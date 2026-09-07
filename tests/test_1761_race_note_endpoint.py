"""Tests for issue #1761: race-note endpoint returning structured facts.

Acceptance criteria verified:
AC1: Endpoint returns goal time, finish time, delta, distance, priority, status for one race.
AC2: Response includes personal-record context (set_pr flag, margin) and training-load snapshot.
AC3: Checkpoint splits are included when they exist.
AC4: Response is a versioned JSON contract with no prompt text or narrative prose.
"""
import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.auth import resolve_user
from backend.main import app

_UID = uuid.UUID("00000000-0000-0000-0000-000000001761")
_RACE_ID = uuid.UUID("11111111-1111-1111-1111-111111111761")


class _FakeUser:
    id = _UID
    name = "test-user-1761"
    is_admin = False
    is_active = True


@pytest.fixture(autouse=True)
def _patch_resolve_user():
    app.dependency_overrides[resolve_user] = lambda: _FakeUser()
    yield
    app.dependency_overrides.pop(resolve_user, None)


def _client() -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


def _make_race(
    race_id=_RACE_ID,
    user_id=_UID,
    name="Boston Marathon",
    race_date=date(2026, 4, 20),
    distance_km=Decimal("42.195"),
    priority="A",
    status="done",
    goal_time_seconds=10800,
    actual_time_seconds=11100,
):
    r = MagicMock()
    r.id = race_id
    r.user_id = user_id
    r.name = name
    r.race_date = race_date
    r.distance_km = distance_km
    r.priority = priority
    r.status = status
    r.goal_time_seconds = goal_time_seconds
    r.actual_time_seconds = actual_time_seconds
    return r


def _make_snapshot(ctl=62.5, atl=55.0, tsb=7.5):
    s = MagicMock()
    s.ctl = ctl
    s.atl = atl
    s.tsb = tsb
    return s


def _make_pr(track_key="marathon", track_name="Marathon", value_numeric=Decimal("11100")):
    pr = MagicMock()
    pr.track_key = track_key
    pr.track_name = track_name
    pr.value_numeric = value_numeric
    return pr


def _make_checkpoint(
    label="Halfway",
    target_distance_km=Decimal("21.0975"),
    target_pace_seconds_per_km=255,
    target_duration_seconds=5400,
    met=True,
):
    cp = MagicMock()
    cp.label = label
    cp.target_distance_km = target_distance_km
    cp.target_pace_seconds_per_km = target_pace_seconds_per_km
    cp.target_duration_seconds = target_duration_seconds
    cp.met = met
    return cp


def _mock_session(
    race,
    snapshot=None,
    prs_on_date=None,
    prev_prs=None,
    checkpoints=None,
):
    """Build a context-manager Session mock for the race-note endpoint."""
    mock_sess = MagicMock()
    mock_sess.__enter__ = MagicMock(return_value=mock_sess)
    mock_sess.__exit__ = MagicMock(return_value=False)
    mock_sess.get.return_value = race

    def _query_side_effect(model):
        from backend.models import TrainingLoadSnapshot, PersonalRecord, RaceCheckpoint
        q = MagicMock()
        if model is TrainingLoadSnapshot:
            q.filter.return_value.first.return_value = snapshot
        elif model is PersonalRecord:
            # first call: prs with achieved_on == race_date → .filter().all()
            q.filter.return_value.all.return_value = prs_on_date or []
            # second call: prev prs for same track_key → .filter().order_by().all()
            q.filter.return_value.order_by.return_value.all.return_value = prev_prs or []
        elif model is RaceCheckpoint:
            q.filter.return_value.order_by.return_value.all.return_value = checkpoints or []
        return q

    mock_sess.query.side_effect = _query_side_effect

    mock_session_cls = MagicMock()
    mock_session_cls.return_value = mock_sess
    return mock_session_cls


def _get_note(race_id=str(_RACE_ID), session_mock=None):
    if session_mock is None:
        session_mock = _mock_session(_make_race())
    with patch("backend.main.Session", session_mock):
        return _client().get(f"/api/races/{race_id}/note")


# ── AC4: versioned contract ────────────────────────────────────────────────────


def test_note_response_has_version_field():
    """AC4: Response carries a 'version' field at the top level."""
    resp = _get_note()
    assert resp.status_code == 200
    body = resp.json()
    assert "version" in body
    assert body["version"] == "1"


def test_note_response_has_no_prose_keys():
    """AC4: Response contains no prompt-text, narrative, or coaching keys."""
    resp = _get_note()
    body = resp.json()
    prose_keys = {"prompt", "narrative", "coaching", "message", "advice", "summary"}
    all_keys = set(body.keys())
    overlap = all_keys & prose_keys
    assert not overlap, f"Unexpected prose keys in response: {overlap}"


# ── AC1: race facts ────────────────────────────────────────────────────────────


def test_note_returns_200_for_valid_race():
    """AC1: Endpoint returns 200 for an existing race belonging to the current user."""
    resp = _get_note()
    assert resp.status_code == 200


def test_note_returns_goal_time():
    """AC1: Response includes goal_time_seconds."""
    resp = _get_note()
    assert resp.json()["race"]["goal_time_seconds"] == 10800


def test_note_returns_finish_time():
    """AC1: Response includes finish_time_seconds (actual_time_seconds)."""
    resp = _get_note()
    assert resp.json()["race"]["finish_time_seconds"] == 11100


def test_note_delta_positive_when_slower_than_goal():
    """AC1: goal_vs_finish_delta_seconds is positive when finish > goal (slower)."""
    race = _make_race(goal_time_seconds=10800, actual_time_seconds=11100)
    resp = _get_note(session_mock=_mock_session(race))
    assert resp.json()["race"]["goal_vs_finish_delta_seconds"] == 300


def test_note_delta_negative_when_faster_than_goal():
    """AC1: goal_vs_finish_delta_seconds is negative when finish < goal (faster)."""
    race = _make_race(goal_time_seconds=10800, actual_time_seconds=10500)
    resp = _get_note(session_mock=_mock_session(race))
    assert resp.json()["race"]["goal_vs_finish_delta_seconds"] == -300


def test_note_delta_null_when_no_finish_time():
    """AC1: delta is null when actual_time_seconds is None."""
    race = _make_race(goal_time_seconds=10800, actual_time_seconds=None)
    resp = _get_note(session_mock=_mock_session(race))
    assert resp.json()["race"]["goal_vs_finish_delta_seconds"] is None


def test_note_delta_null_when_no_goal_time():
    """AC1: delta is null when goal_time_seconds is None."""
    race = _make_race(goal_time_seconds=None, actual_time_seconds=11100)
    resp = _get_note(session_mock=_mock_session(race))
    assert resp.json()["race"]["goal_vs_finish_delta_seconds"] is None


def test_note_returns_distance():
    """AC1: Response includes distance_km."""
    resp = _get_note()
    assert resp.json()["race"]["distance_km"] == pytest.approx(42.195, abs=0.001)


def test_note_returns_priority():
    """AC1: Response includes priority."""
    resp = _get_note()
    assert resp.json()["race"]["priority"] == "A"


def test_note_returns_status():
    """AC1: Response includes status."""
    resp = _get_note()
    assert resp.json()["race"]["status"] == "done"


# ── AC1: error handling ────────────────────────────────────────────────────────


def test_note_returns_404_for_unknown_race():
    """AC1: 404 when the race does not exist."""
    m = _mock_session(None)
    resp = _get_note(session_mock=m)
    assert resp.status_code == 404


def test_note_returns_400_for_invalid_uuid():
    """AC1: 400 when race_id is not a valid UUID."""
    resp = _client().get("/api/races/not-a-uuid/note")
    assert resp.status_code == 400


def test_note_returns_404_when_race_belongs_to_different_user():
    """AC1: 404 when the race exists but belongs to a different user."""
    other_uid = uuid.UUID("99999999-9999-9999-9999-999999999999")
    race = _make_race(user_id=other_uid)
    resp = _get_note(session_mock=_mock_session(race))
    assert resp.status_code == 404


def test_note_requires_auth():
    """AC1: Unauthenticated request returns 401."""
    app.dependency_overrides.pop(resolve_user, None)
    try:
        resp = _client().get(f"/api/races/{_RACE_ID}/note")
        assert resp.status_code == 401
    finally:
        app.dependency_overrides[resolve_user] = lambda: _FakeUser()


# ── AC2: personal-record context ──────────────────────────────────────────────


def test_note_pr_context_set_pr_true_when_pr_on_race_date():
    """AC2: personal_record.set_pr is true when a PR was achieved on the race date."""
    pr = _make_pr()
    resp = _get_note(session_mock=_mock_session(_make_race(), prs_on_date=[pr]))
    assert resp.json()["personal_record"]["set_pr"] is True


def test_note_pr_context_null_when_no_pr_on_race_date():
    """AC2: personal_record is null when no PR was achieved on the race date."""
    resp = _get_note(session_mock=_mock_session(_make_race(), prs_on_date=[]))
    assert resp.json()["personal_record"] is None


def test_note_pr_context_includes_track_key_and_name():
    """AC2: personal_record includes track_key and track_name."""
    pr = _make_pr(track_key="marathon", track_name="Marathon")
    resp = _get_note(session_mock=_mock_session(_make_race(), prs_on_date=[pr]))
    body = resp.json()["personal_record"]
    assert body["track_key"] == "marathon"
    assert body["track_name"] == "Marathon"


def test_note_pr_context_includes_value_seconds():
    """AC2: personal_record includes value_seconds (the PR time)."""
    pr = _make_pr(value_numeric=Decimal("11100"))
    resp = _get_note(session_mock=_mock_session(_make_race(), prs_on_date=[pr]))
    assert resp.json()["personal_record"]["value_seconds"] == pytest.approx(11100)


def test_note_pr_margin_seconds_negative_when_improvement():
    """AC2: margin_seconds is negative when this PR is faster than the previous one."""
    pr = _make_pr(value_numeric=Decimal("11100"))
    prev_pr = _make_pr(value_numeric=Decimal("11220"))
    resp = _get_note(session_mock=_mock_session(
        _make_race(), prs_on_date=[pr], prev_prs=[prev_pr]
    ))
    # 11100 - 11220 = -120 (improved by 2 minutes)
    assert resp.json()["personal_record"]["margin_seconds"] == pytest.approx(-120)


def test_note_pr_margin_seconds_null_when_no_previous_pr():
    """AC2: margin_seconds is null when this is the athlete's first PR for the distance."""
    pr = _make_pr(value_numeric=Decimal("11100"))
    resp = _get_note(session_mock=_mock_session(
        _make_race(), prs_on_date=[pr], prev_prs=[]
    ))
    assert resp.json()["personal_record"]["margin_seconds"] is None


# ── AC2: training-load snapshot ───────────────────────────────────────────────


def test_note_fitness_includes_ctl_atl_tsb_when_snapshot_exists():
    """AC2: fitness block includes ctl, atl, tsb from the training-load snapshot."""
    snap = _make_snapshot(ctl=62.5, atl=55.0, tsb=7.5)
    resp = _get_note(session_mock=_mock_session(_make_race(), snapshot=snap))
    fitness = resp.json()["fitness"]
    assert fitness["ctl"] == pytest.approx(62.5)
    assert fitness["atl"] == pytest.approx(55.0)
    assert fitness["tsb"] == pytest.approx(7.5)


def test_note_fitness_null_when_no_snapshot():
    """AC2: fitness is null when no training-load snapshot exists for the race date."""
    resp = _get_note(session_mock=_mock_session(_make_race(), snapshot=None))
    assert resp.json()["fitness"] is None


# ── AC3: checkpoint splits ────────────────────────────────────────────────────


def test_note_checkpoints_empty_when_none_exist():
    """AC3: checkpoints is an empty list when no checkpoints exist for the race."""
    resp = _get_note(session_mock=_mock_session(_make_race(), checkpoints=[]))
    assert resp.json()["checkpoints"] == []


def test_note_checkpoints_included_when_they_exist():
    """AC3: Checkpoints are present in the response when the race has them."""
    cp = _make_checkpoint(label="Halfway", target_distance_km=Decimal("21.0975"), met=True)
    resp = _get_note(session_mock=_mock_session(_make_race(), checkpoints=[cp]))
    cps = resp.json()["checkpoints"]
    assert len(cps) == 1
    assert cps[0]["label"] == "Halfway"
    assert cps[0]["met"] is True


def test_note_checkpoints_include_target_fields():
    """AC3: Each checkpoint includes target distance, pace, and duration."""
    cp = _make_checkpoint(
        target_distance_km=Decimal("21.0975"),
        target_pace_seconds_per_km=255,
        target_duration_seconds=5400,
    )
    resp = _get_note(session_mock=_mock_session(_make_race(), checkpoints=[cp]))
    cp_data = resp.json()["checkpoints"][0]
    assert cp_data["target_distance_km"] == pytest.approx(21.0975, abs=0.001)
    assert cp_data["target_pace_seconds_per_km"] == 255
    assert cp_data["target_duration_seconds"] == 5400


def test_note_multiple_checkpoints_returned():
    """AC3: All checkpoints for a race are returned."""
    cps = [
        _make_checkpoint(label="10K", target_distance_km=Decimal("10.0")),
        _make_checkpoint(label="Halfway", target_distance_km=Decimal("21.0975")),
        _make_checkpoint(label="30K", target_distance_km=Decimal("30.0")),
    ]
    resp = _get_note(session_mock=_mock_session(_make_race(), checkpoints=cps))
    assert len(resp.json()["checkpoints"]) == 3
