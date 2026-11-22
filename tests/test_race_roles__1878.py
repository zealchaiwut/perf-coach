"""P6-4 (#1878) — race roles, targets, add-on runs and role results."""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.main import app
from backend.models import Race, User
from backend.services import race_roles as rr
from backend.services.race_list import match_run

UID = uuid.uuid4()


def race(**kw):
    base = dict(
        id=uuid.uuid4(),
        user_id=UID,
        name="Test",
        race_date=date(2026, 6, 1),
        distance_km=21.1,
        goal_time_seconds=6300,
        priority="B",
        race_type="race",
        role="pb",
        status="done",
        actual_time_seconds=None,
        power_cap_w=None,
        addon_distance_km=None,
        goal_band_low_seconds=None,
        goal_band_high_seconds=None,
        addon_workout_id=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def workout(wd, dist, secs, *, start=None, power=250, wtype="run", wid=None):
    return SimpleNamespace(
        id=wid or uuid.uuid4(),
        workout_date=wd,
        distance_km=dist,
        duration_seconds=secs,
        start_time=start,
        avg_power=power,
        workout_type=wtype,
    )


# ── role column wins ──────────────────────────────────────────────────────────

def test_race_role_uses_db_column_over_priority():
    assert rr.race_role(race(priority="C", role="pb")) == "pb"
    assert rr.race_role(race(priority="A", role="fun")) == "fun"


# ── PB limit warning ──────────────────────────────────────────────────────────

def _block_races():
    a1 = race(id=uuid.uuid4(), role="a_race", race_date=date(2026, 1, 1), priority="A")
    pb1 = race(id=uuid.uuid4(), role="pb", race_date=date(2026, 2, 1))
    pb2 = race(id=uuid.uuid4(), role="pb", race_date=date(2026, 3, 1))
    pb3 = race(id=uuid.uuid4(), role="pb", race_date=date(2026, 4, 1))
    a2 = race(id=uuid.uuid4(), role="a_race", race_date=date(2026, 6, 1), priority="A")
    return [a1, pb1, pb2, pb3, a2]


def test_pb_limit_warns_on_third_pb_in_block():
    races = _block_races()
    assert rr.pb_limit_warning(races, races[1]) is None
    assert rr.pb_limit_warning(races, races[2]) is None
    warn = rr.pb_limit_warning(races, races[3])
    assert warn is not None and "PB #3" in warn


def test_pb_limit_ignores_non_pb():
    races = _block_races()
    assert rr.pb_limit_warning(races, race(role="long_run", race_date=date(2026, 4, 1))) is None


# ── add-on linking ────────────────────────────────────────────────────────────

def test_addon_links_within_sixty_minutes_same_day():
    r = race(role="long_run", race_date=date(2026, 5, 10))
    main_start = datetime(2026, 5, 10, 8, 0, tzinfo=timezone.utc)
    main = workout(r.race_date, 21.0, 7200, start=main_start, wid=uuid.uuid4())
    addon_start = main_start + timedelta(hours=2)
    addon = workout(r.race_date, 3.0, 1200, start=addon_start)
    found = rr.find_addon_workout(r, main, [main, addon])
    assert found is addon


def test_addon_skips_wrong_day_or_late_start():
    r = race(role="long_run", race_date=date(2026, 5, 10))
    main_start = datetime(2026, 5, 10, 8, 0, tzinfo=timezone.utc)
    main = workout(r.race_date, 21.0, 7200, start=main_start)
    race_end = main_start + timedelta(seconds=7200)
    late = workout(r.race_date, 3.0, 1200, start=race_end + timedelta(minutes=61))
    assert rr.find_addon_workout(r, main, [main, late]) is None
    next_day = workout(date(2026, 5, 11), 3.0, 1200, start=main_start + timedelta(hours=2))
    assert rr.find_addon_workout(r, main, [main, next_day]) is None


# ── role results ──────────────────────────────────────────────────────────────

def test_role_result_pb_pass_fail():
    assert rr.compute_role_result(race(role="pb", actual_time_seconds=6200, goal_time_seconds=6300))["status"] == "pass"
    assert rr.compute_role_result(race(role="pb", actual_time_seconds=6400, goal_time_seconds=6300))["status"] == "fail"


def test_role_result_a_race_band():
    r = race(role="a_race", actual_time_seconds=6300, goal_band_low_seconds=6200, goal_band_high_seconds=6400)
    assert rr.compute_role_result(r)["status"] == "pass"
    assert rr.compute_role_result(race(role="a_race", actual_time_seconds=6100, goal_band_low_seconds=6200, goal_band_high_seconds=6400))["status"] == "fast"
    assert rr.compute_role_result(race(role="a_race", actual_time_seconds=6500, goal_band_low_seconds=6200, goal_band_high_seconds=6400))["status"] == "slow"


def test_role_result_long_run_power_and_addon():
    r = race(role="long_run", power_cap_w=260, addon_distance_km=3.0)
    main = workout(date(2026, 6, 1), 21.0, 7200, power=265)
    addon = workout(date(2026, 6, 1), 3.0, 1200)
    assert rr.compute_role_result(r, main, addon)["status"] == "pass"
    assert rr.compute_role_result(r, main, workout(date(2026, 6, 1), 2.0, 800))["status"] == "fail"
    assert rr.compute_role_result(r, workout(date(2026, 6, 1), 21.0, 7200, power=280), addon)["status"] == "fail"


def test_role_result_fun_is_none():
    assert rr.compute_role_result(race(role="fun")) is None


# ── API shape ─────────────────────────────────────────────────────────────────

@patch("backend.main._race_dict_enriched")
@patch("backend.main.Session")
def test_patch_race_accepts_role_fields(mock_session_cls, mock_enriched):
    from backend.main import resolve_user

    mock_session = MagicMock()
    mock_session_cls.return_value.__enter__.return_value = mock_session
    rid = uuid.uuid4()
    row = Race(id=rid, user_id=UID, name="x", race_date=date(2026, 7, 1), distance_km=10.0, role="long_run")
    mock_session.get.return_value = row
    mock_enriched.return_value = {"id": str(rid), "role": "long_run", "power_cap_w": 250}

    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        client = TestClient(app)
        r = client.patch(
            f"/api/races/{rid}",
            json={"role": "long_run", "power_cap_w": 250, "addon_distance_km": 2.0},
        )
        assert r.status_code == 200
        assert row.role == "long_run"
        assert row.power_cap_w == 250
        assert float(row.addon_distance_km) == 2.0
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_match_run_still_used_for_main_workout():
    rdate = date(2026, 8, 1)
    assert match_run(rdate, 10.0, [workout(rdate, 10.0, 3000)]) is not None