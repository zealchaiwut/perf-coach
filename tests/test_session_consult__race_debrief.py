"""Session consult prompt (race debrief clipboard) — issue session-consult."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from backend.services.session_consult import (
    MAX_PROMPT_CHARS,
    NOT_AVAILABLE,
    PROMPT_VERSION_RACE,
    PROMPT_VERSION_SESSION,
    _lap_rows_from_splits,
    _trim_prompt_size,
    build_session_consult,
    collapse_lap_rows,
    select_previous_races,
)


def _split(idx: int, dist: float = 1.0, dur: int = 300):
    return SimpleNamespace(
        split_index=idx,
        distance_km=dist,
        duration_seconds=dur,
        avg_power=200,
        avg_hr=150,
        cadence_spm=170,
        stride_length_m=None,
        lap_type="auto",
        intensity_band=None,
    )


def test_collapse_120_laps_to_per_km():
    rows = _lap_rows_from_splits([_split(i) for i in range(1, 121)])
    collapsed = collapse_lap_rows(rows, force_per_km=True)
    assert len(collapsed) <= 60
    assert all(r["lap"] == i + 1 for i, r in enumerate(collapsed))


def test_missing_data_session_kind():
    session = MagicMock()
    uid = uuid.uuid4()
    wid = uuid.uuid4()
    workout = SimpleNamespace(
        id=wid,
        user_id=uid,
        workout_date=date(2026, 3, 1),
        workout_type="run",
        name="Easy",
        distance_km=None,
        duration_seconds=None,
        avg_hr=None,
        max_hr=None,
        avg_power=None,
        np=None,
        avg_cadence_spm=None,
        avg_stride_m=None,
        elevation_m=None,
        temperature_c=None,
        zone2_minutes=None,
        tss=None,
        tss_method=None,
        tss_source=None,
        stryd_activity_pk=None,
        remarks=None,
        feeling=None,
        fuelled=None,
        decoupling_percent=None,
    )

    def q(model):
        qm = MagicMock()
        if model.__name__ == "Workout":
            qm.filter.return_value.order_by.return_value.first.return_value = workout
            qm.get.return_value = workout
        elif model.__name__ == "WorkoutSplit":
            qm.filter.return_value.order_by.return_value.all.return_value = []
        elif model.__name__ == "UserPreferences":
            qm.filter.return_value.first.return_value = None
        elif model.__name__ == "WorkoutFeel":
            qm.filter.return_value.order_by.return_value.first.return_value = None
        elif model.__name__ == "PlannedSession":
            qm.filter.return_value.first.return_value = None
        return qm

    session.get.return_value = workout
    session.query.side_effect = q

    def scores(_s, _u, _d):
        return {
            "endurance": None,
            "speed": None,
            "as_of_date": NOT_AVAILABLE,
            "anchor_date": NOT_AVAILABLE,
            "anchor_effort": NOT_AVAILABLE,
        }

    out = build_session_consult(wid, user_id=uid, db=session, score_reader=scores)
    assert out.kind == "session"
    assert NOT_AVAILABLE in out.prompt
    assert "laps" in out.missing


def test_race_golden_42_laps_snapshot():
    session = MagicMock()
    uid = uuid.uuid4()
    wid = uuid.uuid4()
    race = SimpleNamespace(
        id=uuid.uuid4(),
        user_id=uid,
        name="Bangsaen 42",
        priority="A",
        distance_km=42.195,
        race_date=date(2026, 2, 15),
        goal_time_seconds=4 * 3600,
        goal_pace_seconds_per_km=342,
        actual_time_seconds=4 * 3600 + 120,
        status="done",
        race_type="race",
    )
    workout = SimpleNamespace(
        id=wid,
        user_id=uid,
        workout_date=race.race_date,
        workout_type="run",
        name="Bangsaen 42",
        distance_km=42.195,
        duration_seconds=race.actual_time_seconds,
        avg_hr=155,
        max_hr=172,
        avg_power=240,
        np=255,
        avg_cadence_spm=178,
        avg_stride_m=1.1,
        elevation_m=120,
        temperature_c=29.0,
        zone2_minutes=30,
        tss=310,
        tss_method="power",
        tss_source="calculated",
        stryd_activity_pk=None,
        remarks="Good day",
        feeling="ok",
        fuelled=True,
        decoupling_percent=4.5,
    )
    splits = [_split(i, dist=1.0, dur=340 + i) for i in range(1, 43)]

    def q(model):
        qm = MagicMock()
        name = getattr(model, "__name__", str(model))
        if "Race" in name:
            qm.filter.return_value.all.side_effect = [
                [race],
                [],
            ]
            qm.filter.return_value.order_by.return_value.all.return_value = []
            qm.filter.return_value.order_by.return_value.first.return_value = None
        elif "WorkoutSplit" in name:
            qm.filter.return_value.order_by.return_value.all.return_value = splits
        elif "UserPreferences" in name:
            qm.filter.return_value.first.return_value = SimpleNamespace(
                ftp_w=280, threshold_hr=170, threshold_pace_seconds_per_km=280
            )
        elif "WorkoutFeel" in name:
            qm.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
                notes="Felt controlled"
            )
        elif "TrainingLoadSnapshot" in name:
            qm.filter.return_value.order_by.return_value.first.return_value = SimpleNamespace(
                ctl=55.0, atl=62.0, tsb=-7.0, snapshot_date=race.race_date, tss_for_day=0
            )
            qm.filter.return_value.all.return_value = []
        elif "RacePrediction" in name:
            qm.filter.return_value.order_by.return_value.first.return_value = None
        return qm

    session.get.return_value = workout
    session.query.side_effect = q

    def scores(_s, _u, _d):
        return {
            "endurance": 61.2,
            "speed": 58.0,
            "as_of_date": "2026-02-14",
            "anchor_date": "2026-01-10",
            "anchor_effort": 54.2,
        }

    out = build_session_consult(wid, user_id=uid, db=session, score_reader=scores)
    assert out.kind == "race"
    assert PROMPT_VERSION_RACE in out.prompt
    assert "Bangsaen 42" in out.prompt
    assert "CHANGES TO APPLY" in out.prompt
    assert "derived for this prompt, not canonical" in out.prompt
    assert out.prompt.count("|") >= 42
    assert "61.2" in out.prompt


def test_previous_races_prefers_same_distance():
    session = MagicMock()
    uid = uuid.uuid4()
    races = [
        SimpleNamespace(
            id=uuid.uuid4(),
            user_id=uid,
            race_type="race",
            status="done",
            actual_time_seconds=3600,
            distance_km=42.0,
            race_date=date(2025, 1, 1),
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            user_id=uid,
            race_type="race",
            status="done",
            actual_time_seconds=7200,
            distance_km=21.1,
            race_date=date(2025, 6, 1),
        ),
        SimpleNamespace(
            id=uuid.uuid4(),
            user_id=uid,
            race_type="race",
            status="done",
            actual_time_seconds=3700,
            distance_km=42.2,
            race_date=date(2025, 9, 1),
        ),
    ]
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = races
    picked = select_previous_races(session, uid, 42.195, None, limit=5)
    assert len(picked) == 3
    assert sum(1 for r in picked if abs(float(r.distance_km) - 42.195) < 3) == 2


def test_size_guard_drops_columns():
    rows = _lap_rows_from_splits([_split(i) for i in range(1, 81)])
    from backend.services.session_consult import _lap_table_markdown

    lap_md = _lap_table_markdown(rows)
    base = "x" * (MAX_PROMPT_CHARS - 2000)
    prompt = base + "\n## Laps\n" + lap_md + "\n"
    assert len(prompt) > MAX_PROMPT_CHARS
    notes: list[str] = []
    trimmed, _ = _trim_prompt_size(prompt, lap_md, rows, notes)
    assert len(trimmed) <= MAX_PROMPT_CHARS
    assert any("prompt trimmed" in m for m in notes)


def test_scores_reader_patch():
    session = MagicMock()
    uid = uuid.uuid4()
    wid = uuid.uuid4()
    workout = SimpleNamespace(
        id=wid,
        user_id=uid,
        workout_date=date(2026, 1, 1),
        workout_type="run",
        name="Run",
        distance_km=10.0,
        duration_seconds=3000,
        avg_hr=None,
        max_hr=None,
        avg_power=None,
        np=None,
        avg_cadence_spm=None,
        avg_stride_m=None,
        elevation_m=None,
        temperature_c=None,
        zone2_minutes=None,
        tss=50,
        tss_method="pace",
        tss_source="calculated",
        stryd_activity_pk=None,
        remarks=None,
        feeling=None,
        fuelled=None,
        decoupling_percent=None,
    )

    def q(model):
        qm = MagicMock()
        name = getattr(model, "__name__", str(model))
        if "Race" in name:
            qm.filter.return_value.all.return_value = []
        elif "WorkoutSplit" in name:
            qm.filter.return_value.order_by.return_value.all.return_value = [_split(1)]
        elif "UserPreferences" in name:
            qm.filter.return_value.first.return_value = None
        elif "WorkoutFeel" in name:
            qm.filter.return_value.order_by.return_value.first.return_value = None
        elif "PlannedSession" in name:
            qm.filter.return_value.first.return_value = None
        elif "TrainingLoadSnapshot" in name:
            qm.filter.return_value.order_by.return_value.first.return_value = None
            qm.filter.return_value.all.return_value = []
        return qm

    session.get.return_value = workout
    session.query.side_effect = q

    def patched(_s, _u, _d):
        return {
            "endurance": 77.7,
            "speed": 66.6,
            "as_of_date": "2026-01-01",
            "anchor_date": NOT_AVAILABLE,
            "anchor_effort": NOT_AVAILABLE,
        }

    out = build_session_consult(wid, user_id=uid, db=session, score_reader=patched)
    assert "77.7" in out.prompt
    assert "66.6" in out.prompt
    assert out.kind == "session"
    assert PROMPT_VERSION_SESSION in out.prompt