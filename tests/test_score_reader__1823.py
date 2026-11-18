"""Issue #1823 — canonical score reader."""
from types import SimpleNamespace
from unittest.mock import patch

from backend.services import score_reader


def _payload():
    return {
        "state": "scored",
        "generated_at": "2026-11-08T00:00:00+00:00",
        "endurance": {
            "score": 41.0,
            "block_delta": 1.2,
            "anchors": [{"date": "2026-10-01", "is_stale": False, "title": "Long run"}],
        },
        "speed": {
            "score": 47.0,
            "block_delta": -0.5,
            "anchors": [{"date": "2026-09-20", "is_stale": True, "title": "Intervals"}],
        },
    }


def test_get_scores_overall_matches_performance_payload():
    with patch.object(score_reader, "get_performance_payload", return_value=_payload()):
        out = score_reader.get_scores("00000000-0000-0000-0000-000000000001")
    assert out["overall"]["speed"]["score"] == 47.0
    assert out["overall"]["endurance"]["score"] == 41.0
    assert out["overall"]["speed"]["stale"] is True


def test_race_specific_can_differ_from_overall():
    race = SimpleNamespace(race_date="2026-11-01", distance_km=42.195)
    session = object()
    overall = {
        "endurance": {"score": 41.0, "delta_28d": None, "anchor_date": None, "anchor_title": None, "stale": False},
        "speed": {"score": 47.0, "delta_28d": None, "anchor_date": None, "anchor_title": None, "stale": False},
    }
    with patch.object(score_reader, "get_scores", return_value={"overall": overall}):
        with patch.object(score_reader, "_latest_race_perf", return_value={"perf": 52.3, "date": "2026-10-15"}):
            out = score_reader.get_race_scores(session, "uid", race)
    assert out["race_specific"]["speed"]["score"] == 52.3
    assert out["race_specific"]["speed"]["score"] != 47.0


def test_export_and_reader_same_speed():
    with patch.object(score_reader, "get_performance_payload", return_value=_payload()):
        from backend.services.coach_export import _assemble_performance

        user = SimpleNamespace(id="00000000-0000-0000-0000-000000000001")
        perf = _assemble_performance(user)
        reader = score_reader.get_scores(user.id)
    assert perf["overall"]["speed"]["score"] == reader["overall"]["speed"]["score"]


def test_session_signal_reason_when_short_run():
    w = SimpleNamespace(endurance_signal=None, speed_signal=None, duration_seconds=30 * 60)
    block = score_reader.session_signal(w)
    assert block["session_signal"]["endurance"]["reason"] == "run_under_40_min"