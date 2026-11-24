"""Workout session-type tag (easy/tempo/interval/race) and volume Race overlay."""
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.main import _RUN_SUBTYPE_VALUES, _canonical_run_subtype
from backend.services.plan_match_payload import session_kind_for_workout
from backend.services.race_day_tss import race_week_payload
from backend.services.weekly_rollup import _assemble_week

REPO = Path(__file__).resolve().parents[1]
FEEL_JS = (REPO / "frontend" / "js" / "lib" / "v2-feel-buttons.js").read_text(encoding="utf-8")
RD4_JS = (REPO / "frontend" / "js" / "lib" / "run-detail-view.js").read_text(encoding="utf-8")
DRAWER_JS = (REPO / "frontend" / "js" / "v2-run-drawer.js").read_text(encoding="utf-8")


def test_canonical_subtype_accepts_race_and_aliases():
    assert "race" in _RUN_SUBTYPE_VALUES
    assert _canonical_run_subtype("race") == "race"
    assert _canonical_run_subtype("Intervals") == "interval"
    assert _canonical_run_subtype("long_run") == "longrun"
    assert _canonical_run_subtype("nope") is None


def test_session_kind_race_from_subtype():
    run = SimpleNamespace(workout_type="run", run_subtype="race", distance_km=9.0)
    interval = SimpleNamespace(workout_type="run", run_subtype="interval", distance_km=8.0)
    easy = SimpleNamespace(workout_type="run", run_subtype="easy", distance_km=9.0)
    assert session_kind_for_workout(run) == "race"
    assert session_kind_for_workout(interval) == "quality_run"
    assert session_kind_for_workout(easy) == "run"


def test_assemble_week_tss_race_from_tagged_workout():
    race = SimpleNamespace(
        tss=87.0, workout_type="run", run_subtype="race",
        distance_km=9.0, duration_seconds=3600, workout_date=date(2026, 11, 22),
        start_time=None,
    )
    easy = SimpleNamespace(
        tss=78.0, workout_type="run", run_subtype="easy",
        distance_km=8.9, duration_seconds=3300, workout_date=date(2026, 11, 18),
        start_time=None,
    )
    out = _assemble_week(
        ws=date(2026, 11, 16),
        we=date(2026, 11, 22),
        today=date(2026, 11, 24),
        workouts=[race, easy],
        planned_rows=[],
        planned_tss_training=0.0,
        race_items=[],
        target_tss_val=334,
        phase_label=None,
    )
    assert out["tss_race"] == 87.0
    assert out["tss_run"] == 165.0


def test_race_week_payload_includes_type_and_skips_nothing_for_checkpoint():
    race = SimpleNamespace(
        id="r1",
        name="Checkpoint",
        race_date=date(2026, 11, 21),
        status="planned",
        priority="C",
        race_type="checkpoint",
        role="long_run",
        distance_km=18.0,
        goal_time_seconds=5400,
        actual_time_seconds=None,
        user_id=None,
        tss_if_override=None,
    )
    out = race_week_payload(
        MagicMock(),
        None,
        date(2026, 11, 16),
        date(2026, 11, 22),
        races=[race],
        workouts=[],
        allow_finish_estimate=False,
    )
    assert len(out) == 1
    assert out[0]["race_type"] == "checkpoint"
    assert out[0]["role"] == "long_run"


def test_drawer_wires_type_chips_next_to_feel():
    assert "id=\"rd4-runtype\"" in RD4_JS
    assert "V2RunTypeButtons" in DRAWER_JS
    assert "Marked as race" in FEEL_JS
    assert "Intervals" in FEEL_JS
    assert "key: 'race'" in FEEL_JS
    assert "run_subtype: value" in FEEL_JS
