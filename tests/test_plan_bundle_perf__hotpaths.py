"""Tests for Task 3 (perf/hot-paths): _plan_signature single-query fingerprint
and shared per-user load/threshold_pace hoisting in the race-readiness loop."""

from datetime import datetime, date, timedelta
from unittest.mock import MagicMock

from backend.main import _plan_signature, _race_readiness_impl, _RACE_READINESS_UNSET


class _FakeSubquery:
    """Stands in for `session.query(...).filter(...).scalar_subquery().label(...)`."""

    def filter(self, *a, **kw):
        return self

    def scalar_subquery(self):
        return self

    def label(self, name):
        return self


def test_plan_signature_is_one_round_trip():
    """_plan_signature must not issue separate scalar()/first() calls per field —
    only a single terminal query (.one()) against the combined scalar-subquery row."""
    terminal_calls = {"scalar": 0, "first": 0, "one": 0}

    def fake_query(*args, **kwargs):
        q = _FakeSubquery()
        q.scalar = lambda: terminal_calls.__setitem__("scalar", terminal_calls["scalar"] + 1) or None
        q.first = lambda: terminal_calls.__setitem__("first", terminal_calls["first"] + 1) or None

        def _one():
            terminal_calls["one"] += 1
            return ("wo_max", 3, "race_max", "race_created", "pace_stamp", "prefs_updated")

        q.one = _one
        return q

    mock_session = MagicMock()
    mock_session.query.side_effect = fake_query

    plan = MagicMock()
    plan.updated_at = datetime(2024, 1, 1)

    result = _plan_signature(mock_session, "user-1", plan)

    assert isinstance(result, str)
    assert len(result) == 64  # sha256 hex digest
    assert terminal_calls["one"] == 1
    assert terminal_calls["scalar"] == 0
    assert terminal_calls["first"] == 0


def test_plan_signature_deterministic_for_same_inputs():
    def fake_query(*args, **kwargs):
        q = _FakeSubquery()
        q.one = lambda: ("wo_max", 3, "race_max", "race_created", "pace_stamp", "prefs_updated")
        return q

    mock_session = MagicMock()
    mock_session.query.side_effect = fake_query

    plan = MagicMock()
    plan.updated_at = datetime(2024, 1, 1)

    r1 = _plan_signature(mock_session, "user-1", plan)
    r2 = _plan_signature(mock_session, "user-1", plan)
    assert r1 == r2


def test_race_readiness_impl_skips_recompute_when_shared_data_passed():
    """When _compute_plan_bundle hoists the 180-day series + threshold_pace out
    of the per-race loop, _race_readiness_impl must not re-derive them."""
    today = date.today()
    start = today - timedelta(days=180)
    series = [(start + timedelta(days=i), 80) for i in range((today - start).days + 1)]
    from backend.services.training_load import compute_load_curves
    curves = compute_load_curves(series)

    race = MagicMock()
    race.id = "race-1"
    race.user_id = "user-1"
    race.race_date = today + timedelta(days=30)
    race.distance_km = 10.0
    race.name = "Test Race"
    race.race_type = "race"
    race.priority = "A"
    race.goal_finish_seconds = None
    race.goal_time_seconds = None
    race.actual_time_seconds = None
    race.status = None

    user = MagicMock()
    user.id = "user-1"

    with (
        __import__("unittest.mock", fromlist=["patch"]).patch("backend.main.Session") as MockSession,
        __import__("unittest.mock", fromlist=["patch"]).patch("backend.main._uuid") as mock_uuid,
        __import__("unittest.mock", fromlist=["patch"]).patch("backend.main.daily_tss_series") as mock_series,
    ):
        mock_uuid.UUID.return_value = "race-1"
        db_mock = MagicMock()
        db_mock.__enter__.return_value = db_mock
        db_mock.__exit__.return_value = False
        db_mock.get.return_value = race
        db_mock.execute.return_value.fetchall.return_value = []
        db_mock.query.return_value.filter.return_value.first.return_value = None
        MockSession.return_value = db_mock

        _race_readiness_impl(
            "race-1",
            user,
            _shared_load_curves=(series, curves),
            _shared_threshold_pace=240.0,
        )

    mock_series.assert_not_called()
