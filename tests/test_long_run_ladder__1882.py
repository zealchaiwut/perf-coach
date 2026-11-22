"""P6-8 (#1882) — long-run ladder weekly series and red state."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from types import SimpleNamespace

from backend.services import long_run_ladder as lrl
from backend.services.weekly_rollup import bangkok_week_start


def w(wd, dist, secs, *, wid=None, wtype="run"):
    return SimpleNamespace(
        id=wid or uuid.uuid4(),
        workout_date=wd,
        distance_km=dist,
        duration_seconds=secs,
        start_time=None,
        workout_type=wtype,
    )


def race(rd, dist=21.1, *, role="long_run", addon_id=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        race_date=rd,
        distance_km=dist,
        role=role,
        priority="B",
        race_type="race",
        addon_workout_id=addon_id,
    )


def test_race_plus_addon_counts_as_one_bar():
    main_id = uuid.uuid4()
    addon_id = uuid.uuid4()
    rd = date(2026, 6, 7)
    ws = bangkok_week_start(rd)
    we = ws + timedelta(days=6)
    workouts = [
        w(rd, 21.0, 7200, wid=main_id),
        w(rd, 3.0, 1200, wid=addon_id),
        w(ws + timedelta(days=2), 10.0, 3600),
    ]
    r = race(rd, addon_id=addon_id)
    actual, _ = lrl.week_actual_max_seconds(workouts, [r], ws, we)
    assert actual == 7200 + 1200


def test_red_state_two_week_rule():
    weeks = [
        {"actual_seconds": 5400, "target_seconds": 7200},
        {"actual_seconds": 5000, "target_seconds": 7200},
        {"actual_seconds": 8000, "target_seconds": 7200},
        {"actual_seconds": 5000, "target_seconds": 7200},
        {"actual_seconds": 4800, "target_seconds": 7200},
    ]
    assert lrl.red_state_triggered(weeks[:2]) is True
    assert lrl.red_state_triggered(weeks[2:4]) is False
    assert lrl.red_state_triggered(weeks[3:5]) is True


def test_red_state_resets_when_gap_under_20_min():
    weeks = [
        {"actual_seconds": 7100, "target_seconds": 7200},
        {"actual_seconds": 7050, "target_seconds": 7200},
    ]
    assert lrl.red_state_triggered(weeks) is False


def test_planned_long_run_target_prefers_longest():
    rows = [
        SimpleNamespace(
            session_type="run",
            name="Easy",
            structure={"subtype": "easy_run", "blocks": [{"duration_min": 40}]},
        ),
        SimpleNamespace(
            session_type="run",
            name="Long",
            structure={"subtype": "long_run", "blocks": [{"duration_min": 130}]},
        ),
    ]
    assert lrl._week_target(rows, 7200) == 130 * 60
