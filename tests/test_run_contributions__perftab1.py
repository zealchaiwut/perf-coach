"""Tests for per-run marginal contributions (run_contributions) — the single
source for every per-session delta badge on the Performance tab and the
workout-detail panel.

Semantics (see running_performance._aggregate_and_shape):
  contribution(run) = display_score(today, all points)
                    − display_score(today, all points minus this run)
- A maintenance run below the decayed top-3 → exactly 0.0 (never negative —
  the old date-diff contributions blamed runs for pure time-decay drift).
- A run holding up today's top-3 → its real positive lift.
- A run decayed out of relevance → 0.0.
Pure functions, no DB.
"""
from __future__ import annotations

from datetime import date, timedelta

from backend.services.running_performance import compute_speed_score


def _interval_run(run_id: str, days_ago: int, pace_s_per_km: float) -> dict:
    d = (date.today() - timedelta(days=days_ago)).isoformat()
    return {
        "run_id": run_id,
        "workout_date": d,
        # band must be a DEFAULT_SPEED_BANDS member ("hard"/"interval") for
        # the lap to qualify — pace then derives from distance/duration.
        "laps": [{
            "band": "hard", "distance_km": 1.0,
            "duration_seconds": pace_s_per_km, "avg_hr": 165,
        }],
    }


_PREFS = {"threshold_pace_seconds_per_km": 280}


def _score(runs):
    return compute_speed_score(runs, _PREFS, None)


def test_run_contributions_keyed_by_run_id_and_never_negative():
    runs = [
        _interval_run("r1", 40, 260),
        _interval_run("r2", 30, 262),
        _interval_run("r3", 20, 258),
        _interval_run("r4", 10, 330),  # much slower session
        _interval_run("r5", 3, 255),
    ]
    res = _score(runs)
    rc = res["run_contributions"]
    assert set(rc.keys()) == {"r1", "r2", "r3", "r4", "r5"}
    # A run can only ever ADD to (or not affect) the decayed-top-3 score —
    # removing it can never make the score HIGHER, so no contribution is < 0.
    assert all(v >= 0 for v in rc.values()), rc


def test_maintenance_run_below_top3_contributes_exactly_zero():
    # Three dominant recent efforts + one slow old one that can't crack
    # today's top-3 even after the others' decay.
    runs = [
        _interval_run("strong1", 8, 250),
        _interval_run("strong2", 5, 251),
        _interval_run("strong3", 3, 252),
        _interval_run("weak", 10, 400),
    ]
    res = _score(runs)
    assert res["run_contributions"]["weak"] == 0.0


def test_decayed_out_run_contributes_zero():
    runs = [
        _interval_run("ancient", 85, 250),  # strong but ~12 weeks old
        _interval_run("s1", 8, 258),
        _interval_run("s2", 5, 259),
        _interval_run("s3", 3, 260),
    ]
    res = _score(runs)
    assert res["run_contributions"]["ancient"] == 0.0


def test_top3_member_contributes_positive():
    runs = [
        _interval_run("s1", 8, 258),
        _interval_run("s2", 5, 259),
        _interval_run("s3", 3, 260),
        _interval_run("best", 2, 240),  # clearly the best recent effort
    ]
    res = _score(runs)
    assert res["run_contributions"]["best"] > 0


def test_body_modifier_applied_consistently_to_contributions():
    runs = [
        _interval_run("s1", 8, 258),
        _interval_run("s2", 5, 259),
        _interval_run("s3", 3, 260),
        _interval_run("best", 2, 240),
    ]
    neutral = compute_speed_score(runs, _PREFS, None, body_modifier=1.0)
    boosted = compute_speed_score(runs, _PREFS, None, body_modifier=1.05)
    # Contributions live on the displayed (modifier-applied) scale, same as
    # the score itself — a 5% uplift scales the marginal lift too.
    n = neutral["run_contributions"]["best"]
    b = boosted["run_contributions"]["best"]
    assert b > n > 0


def test_legacy_date_contributions_still_present():
    # Back-compat: the date-keyed map is still returned (other consumers /
    # older clients), even though badges now use run_contributions.
    runs = [
        _interval_run("s1", 8, 258),
        _interval_run("s2", 5, 259),
        _interval_run("s3", 3, 260),
    ]
    res = _score(runs)
    assert "contributions" in res and isinstance(res["contributions"], dict)
