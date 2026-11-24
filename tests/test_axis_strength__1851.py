"""P4-4 (#1851) — strength and power-to-weight scores."""
from datetime import date, timedelta
from pathlib import Path

import pytest

from backend.services import axis_strength as s
from backend.services.axis_spec import interpolate_marathon_profile

AS_OF = date(2026, 11, 20)
ANCHORS = s.normalize_anchor_lifts(None)


def lift(days_ago, name, weight, reps, *, sets=None):
    import json
    return {
        "workout_date": AS_OF - timedelta(days=days_ago), "name": name,
        "weight_kg": weight, "reps": reps,
        "sets_json": json.dumps(sets) if sets is not None else None,
    }


def test_e1rm_math():
    assert s.e1rm(24, 8) == pytest.approx(30.4)
    assert s.e1rm(100, 30) == pytest.approx(200.0)
    assert s.e1rm(60, 1) == pytest.approx(62.0)
    assert s.e1rm(0, 8) is None and s.e1rm(None, 8) is None and s.e1rm(20, None) is None


@pytest.mark.parametrize("reps,expected", [(8, 8.0), ("8/side", 8.0), ("10 per side", 10.0), ("12", 12.0), ("", None), (None, None), (0, None)])
def test_side_reps_handling(reps, expected):
    assert s.parse_reps(reps) == expected
    if expected:
        assert s.e1rm(20, reps) == pytest.approx(20 * (1 + expected / 30))


def test_best_set_skips_warmups_and_picks_highest_e1rm():
    sets = [
        {"type": "warmup", "weight": 100, "reps": 10},
        {"type": "working", "weight": 24, "reps": "8/side"},
        {"type": "working", "weight": 20, "reps": 12},
    ]
    assert s.best_set_e1rm(sets) == pytest.approx(max(24 * (1 + 8 / 30), 20 * (1 + 12 / 30)))


def test_strength_worked_example():
    rows = [
        lift(3, "Single-leg deadlift", None, None, sets=[{"type": "working", "weight": 24, "reps": "8/side"}]),
        lift(5, "Standing calf raise", 60, 10),
    ]
    out = s.compute_strength(rows, ANCHORS, 70.0, AS_OF)
    # sldl: 30.4 / (0.6*70) = 0.7238 ; calf: 80 / (1.2*70) = 0.9524 ; mean 0.8381 -> 84
    assert out["score"] == 84
    by = {a["key"]: a for a in out["anchors"]}
    assert by["single_leg_deadlift"]["ratio"] == pytest.approx(0.724, abs=1e-3)
    assert by["calf_raise"]["ratio"] == pytest.approx(0.952, abs=1e-3)
    assert out["stale"] is False and out["never_measured"] is False


def test_strength_caps_at_100_and_uses_best_in_window():
    rows = [lift(2, "calf raise", 200, 10), lift(10, "calf raise", 60, 10)]
    out = s.compute_strength(rows, ANCHORS, 70.0, AS_OF)
    assert out["score"] == 100


def test_unlogged_anchor_excluded_from_mean():
    out = s.compute_strength([lift(5, "calf raise", 84, 10)], ANCHORS, 70.0, AS_OF)
    # only the calf anchor counts: 84*(1+10/30)=112 / 84 = 1.333 -> 100
    assert out["score"] == 100
    by = {a["key"]: a for a in out["anchors"]}
    assert by["single_leg_deadlift"]["ratio"] is None


def test_strength_old_lift_is_stale_not_never_measured():
    out = s.compute_strength([lift(80, "calf raise", 60, 10)], ANCHORS, 70.0, AS_OF)
    assert out["score"] is not None and out["stale"] is True and out["never_measured"] is False


def test_strength_never_measured_without_lifts_or_mass():
    assert s.compute_strength([], ANCHORS, 70.0, AS_OF)["never_measured"] is True
    out = s.compute_strength([lift(5, "calf raise", 60, 10)], ANCHORS, None, AS_OF)
    assert out["score"] is None and out["never_measured"] is True


def test_power_to_weight_worked_example():
    target = interpolate_marathon_profile(12600)["power_to_weight_w_per_kg"]
    assert target == 3.2
    pool = [{"power_w": 200}, {"power_w": 210}, {"power_w": 260}]
    out = s.compute_power_to_weight(pool, 70.0, 3, target)
    assert out["raw"] == 3.0
    assert out["score"] == 94  # 3.0 / 3.2 = 93.75
    assert out["stale"] is False


def test_power_to_weight_clamps():
    assert s.power_to_weight_score(5.0, 3.2) == 100
    assert s.power_to_weight_score(0.0, 3.2) == 0


def test_missing_weigh_ins_make_p2w_stale_not_wrong():
    pool = [{"power_w": 210}]
    fresh = s.compute_power_to_weight(pool, 70.0, 14, 3.2)
    old = s.compute_power_to_weight(pool, 70.0, 15, 3.2)
    assert fresh["stale"] is False and old["stale"] is True
    assert old["score"] == fresh["score"] and old["score"] is not None
    none = s.compute_power_to_weight(pool, None, None, 3.2)
    assert none["score"] is None and none["never_measured"] is True and none["stale"] is True


def test_p2w_never_measured_without_power():
    out = s.compute_power_to_weight([], 70.0, 2, 3.2)
    assert out["score"] is None and out["never_measured"] is True


def test_trend_mass_uses_ewma():
    entries = [{"date": AS_OF - timedelta(days=i), "weight_kg": w} for i, w in [(2, 72.0), (1, 71.0), (0, 70.0)]]
    entries.reverse()  # chronological
    mass = s.trend_mass_from_entries(entries)
    assert 70.0 < mass < 72.0
    assert s.trend_mass_from_entries([]) is None


def test_normalize_anchor_lifts_defaults_and_validation():
    keys = [a["key"] for a in s.normalize_anchor_lifts([])]
    assert keys == ["single_leg_deadlift", "calf_raise"]
    custom = s.normalize_anchor_lifts([{"label": "Hip thrust", "target_factor": 1.5}])
    assert custom[0]["match"] == ["hip thrust"] and custom[0]["key"] == "hip_thrust"
    assert s.normalize_anchor_lifts([{"label": "x", "target_factor": -1}])[0]["key"] == "single_leg_deadlift"


def test_anchor_factors_are_the_documented_ones():
    f = {a["key"]: a["target_factor"] for a in s.DEFAULT_ANCHOR_LIFTS}
    assert f == {"single_leg_deadlift": 0.6, "calf_raise": 1.2}


def test_routes_and_migration():
    from backend.main import app
    paths = {r.path for r in app.routes}
    assert "/api/performance/anchor-lifts" in paths
    from backend.models import UserPreferences
    assert "anchor_lifts" in UserPreferences.__table__.columns.keys()
    src = Path("alembic/versions/b12573ca9afa_user_preferences_anchor_lifts.py").read_text()
    assert "drop_column" in src and "column_exists" in src


def test_anchor_lifts_endpoint_requires_session():
    from fastapi.testclient import TestClient
    from backend.main import app
    c = TestClient(app)
    assert c.get("/api/performance/anchor-lifts").status_code == 401
    assert c.put("/api/performance/anchor-lifts", json={"anchors": []}).status_code == 401
