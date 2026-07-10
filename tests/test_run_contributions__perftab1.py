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


def test_maintenance_run_below_top3_contributes_the_consistency_bonus():
    # Three dominant recent efforts + one slow old one that can't crack
    # today's top-3 even after the others' decay. It still nudges the score
    # by exactly the consistency bonus (vdot.CONSISTENCY_BONUS_PER_RUN) —
    # steady training visibly counts, but can never fake fitness.
    from backend.services.vdot import CONSISTENCY_BONUS_PER_RUN

    runs = [
        _interval_run("strong1", 8, 250),
        _interval_run("strong2", 5, 251),
        _interval_run("strong3", 3, 252),
        _interval_run("weak", 10, 400),
    ]
    res = _score(runs)
    assert res["run_contributions"]["weak"] == CONSISTENCY_BONUS_PER_RUN


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


def test_improve_hint_targets_plus_four_with_a_concrete_pace():
    """The card's "how do I raise this" line: to reach score+4, the hint
    names the pace a single new effort must hit at the reference duration —
    and the perf it demands must actually be enough (top-3 math inverted)."""
    runs = [
        _interval_run("s1", 8, 258),
        _interval_run("s2", 5, 259),
        _interval_run("s3", 3, 260),
    ]
    res = _score(runs)
    h = res["improve_hint"]
    assert h is not None
    assert h["target_score"] == min(100, round(res["score"]) + 4)
    assert h["pace_seconds_per_km"] > 0
    assert h["effort_minutes"] > 0
    # Demanded pace must be FASTER than the current efforts' pace (a slower
    # run can't raise the score).
    assert h["pace_seconds_per_km"] < 258


def test_power_fallback_short_window_produces_no_speed_point():
    """A sub-2-minute power surge can't define a run's speed effort (seen
    live: a 112 s uphill 1.3x-power window fabricated a 4:14/km flat effort
    worth perf 62.6 and a +8.9 badge on a 6:28/km session)."""
    run = {
        "run_id": "uphill",
        "workout_date": (date.today() - timedelta(days=3)).isoformat(),
        "laps": [{"band": "steady", "distance_km": 1.0, "duration_seconds": 380, "avg_hr": 150}],
        "speed_signal": 1.3, "speed_signal_basis": "power",
        "speed_signal_window_seconds": 112,
        "distance_km": 5.8, "duration_seconds": 2252, "avg_power": 180, "ftp_w": 200,
    }
    baseline = [_interval_run(f"b{i}", 5 + i, 300) for i in range(3)]
    res = _score(baseline + [run])
    assert "uphill" not in res["debug"]["perRunEfficiency"]


def test_power_fallback_pace_clamped_to_fastest_real_lap():
    """The power→pace conversion can never claim a pace faster than the run
    actually demonstrated — an uphill power ratio implies no flat speed."""
    run = {
        "run_id": "uphill2",
        "workout_date": (date.today() - timedelta(days=3)).isoformat(),
        # No hard-band laps → falls to the power fallback; fastest REAL lap 380 s/km.
        "laps": [{"band": "steady", "distance_km": 1.0, "duration_seconds": 380, "avg_hr": 150}],
        "speed_signal": 1.5, "speed_signal_basis": "power",
        "speed_signal_window_seconds": 300,
        "distance_km": 5.8, "duration_seconds": 2252, "avg_power": 190, "ftp_w": 200,
    }
    baseline = [_interval_run(f"b{i}", 5 + i, 300) for i in range(3)]
    res = _score(baseline + [run])
    perf_uphill = res["debug"]["perRunEfficiency"].get("uphill2")
    assert perf_uphill is not None
    # A 380 s/km effort at 5 min must score BELOW the 300 s/km baseline runs.
    baseline_perfs = [res["debug"]["perRunEfficiency"][f"b{i}"] for i in range(3)]
    assert perf_uphill < min(baseline_perfs)


def test_implausible_fast_laps_are_sensor_garbage_and_ignored():
    """Laps claiming a pace faster than 2:30/km (beyond the world mile
    record) are corrupted data, not efforts — seen live: three '1 km in
    ~81 s' laps pinned the Speed score at a perfect 100."""
    garbage = {
        "run_id": "corrupt",
        "workout_date": (date.today() - timedelta(days=4)).isoformat(),
        "laps": [{"band": "hard", "distance_km": 0.98, "duration_seconds": 81, "avg_hr": 160}],
    }
    baseline = [_interval_run(f"b{i}", 5 + i, 300) for i in range(3)]
    res = _score(baseline + [garbage])
    assert "corrupt" not in res["debug"]["perRunEfficiency"]
    assert res["score"] < 90


def test_manual_laps_take_precedence_over_diluted_auto_splits():
    """Stryd lap-button reps are the speed effort's first-preference source:
    a 2-min rep at ~4:30/km is invisible inside a 1 km auto-split (diluted
    to ~6:15/km by the recovery jog), but when the athlete marked reps, the
    reps ARE the demonstration — seen live: recovering the operator's
    manual laps lifted Speed from 33.7 to 52.6."""
    diluted = {
        "run_id": "reps",
        "workout_date": (date.today() - timedelta(days=3)).isoformat(),
        # Auto-split view: diluted, classifies steady — would never qualify.
        "laps": [{"band": "steady", "distance_km": 1.0, "duration_seconds": 375, "avg_hr": 150}],
        # Lap-button view: six ~2-min reps at ~4:30/km, classified hard.
        "manual_laps": [
            {"band": "hard", "distance_km": 0.43, "duration_seconds": 118, "avg_hr": 150}
            for _ in range(6)
        ],
    }
    baseline = [_interval_run(f"b{i}", 5 + i, 320) for i in range(3)]
    res = _score(baseline + [diluted])
    perf = res["debug"]["perRunEfficiency"].get("reps")
    assert perf is not None, "manual laps must produce a speed point"
    # And it must reflect the REP pace (~274 s/km), i.e. score above the
    # slower 320 s/km baselines.
    baseline_perfs = [res["debug"]["perRunEfficiency"][f"b{i}"] for i in range(3)]
    assert perf > max(baseline_perfs)


def test_manual_laps_respect_plausibility_filter():
    garbage = {
        "run_id": "junk",
        "workout_date": (date.today() - timedelta(days=3)).isoformat(),
        "laps": [],
        "manual_laps": [{"band": "hard", "distance_km": 1.0, "duration_seconds": 80, "avg_hr": 160}],
    }
    baseline = [_interval_run(f"b{i}", 5 + i, 300) for i in range(3)]
    res = _score(baseline + [garbage])
    assert "junk" not in res["debug"]["perRunEfficiency"]


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
