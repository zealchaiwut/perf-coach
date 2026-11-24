"""P4-2 (#1849) — durability score from long-run decoupling."""
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from backend.services import axis_durability as d

AS_OF = date(2026, 11, 20)


def run(days_ago, dec, *, minutes=100, z2_frac=0.8, name="Long run"):
    dur = minutes * 60
    return SimpleNamespace(
        workout_date=AS_OF - timedelta(days=days_ago),
        duration_seconds=dur,
        decoupling_percent=dec,
        zone2_minutes=int(minutes * z2_frac),
        name=name,
    )


def test_worked_example_scores():
    assert d.durability_score_from_median(5.0) == 84
    assert d.durability_score_from_median(8.9) == 53


def test_score_clamps_and_boundaries():
    assert d.durability_score_from_median(3.0) == 100
    assert d.durability_score_from_median(1.0) == 100
    assert d.durability_score_from_median(15.5) == 0
    assert d.durability_score_from_median(30) == 0


def test_median_of_last_four_used():
    runs = [run(1, 5.0), run(8, 5.0), run(15, 5.0), run(22, 5.0), run(29, 40.0)]
    out = d.compute_durability(runs, AS_OF)
    assert out["raw"] == 5.0 and out["score"] == 84 and out["n_runs"] == 4
    assert out["never_measured"] is False
    assert out["anchor_date"] == (AS_OF - timedelta(days=1)).isoformat()


def test_two_or_three_runs_accepted():
    two = d.compute_durability([run(1, 4.0), run(9, 6.0)], AS_OF)
    assert two["raw"] == 5.0 and two["score"] == 84
    three = d.compute_durability([run(1, 4.0), run(9, 6.0), run(20, 9.0)], AS_OF)
    assert three["raw"] == 6.0 and three["n_runs"] == 3


def test_short_run_excluded():
    runs = [run(1, 5.0, minutes=89), run(8, 5.0), run(15, 5.0)]
    out = d.compute_durability(runs, AS_OF)
    assert out["n_runs"] == 2


def test_high_intensity_run_excluded():
    runs = [run(1, 5.0, z2_frac=0.59), run(8, 5.0, z2_frac=0.60), run(15, 5.0)]
    assert d.is_qualifying_run(runs[0]) is False
    assert d.is_qualifying_run(runs[1]) is True
    assert d.compute_durability(runs, AS_OF)["n_runs"] == 2


def test_missing_decoupling_or_zone_minutes_excluded():
    assert d.is_qualifying_run(run(1, None)) is False
    r = run(1, 5.0)
    r.zone2_minutes = None
    assert d.is_qualifying_run(r) is False


@pytest.mark.parametrize("runs", [[], [run(1, 5.0)], [run(1, 5.0, minutes=60)]])
def test_fewer_than_two_runs_is_never_measured(runs):
    out = d.compute_durability(runs, AS_OF)
    assert out["score"] is None and out["raw"] is None
    assert out["never_measured"] is True


def test_stale_when_fewer_than_two_runs_in_45_days():
    old = [run(60, 5.0), run(70, 5.0)]
    out = d.compute_durability(old, AS_OF)
    assert out["score"] == 84 and out["stale"] is True
    fresh = [run(10, 5.0), run(44, 5.0)]
    assert d.compute_durability(fresh, AS_OF)["stale"] is False


def test_future_runs_ignored():
    out = d.compute_durability([run(-3, 5.0), run(1, 5.0)], AS_OF)
    assert out["n_runs"] == 1 and out["never_measured"] is True


def test_dict_runs_supported():
    r = {"workout_date": AS_OF, "duration_seconds": 6000, "decoupling_percent": 3.0,
         "zone2_minutes": 90}
    assert d.is_qualifying_run(r)
