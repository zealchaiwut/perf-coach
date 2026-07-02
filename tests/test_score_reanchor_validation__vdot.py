"""Validation targets for the VDOT score re-anchor (proposal §6 / fix prompt §6).

Each test maps to one documented validation target. These exercise the pure
compute_endurance_score / compute_speed_score on synthetic runs so the
behaviours are deterministic and don't depend on live data.
"""
import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.services.running_performance import (  # noqa: E402
    compute_endurance_score,
    compute_speed_score,
)
from backend.services.zone_constants import make_zone_constants  # noqa: E402
from backend.services import vdot as _vdot  # noqa: E402


_TODAY = date.today()


def _prefs():
    return {
        "ftp_w": 200,
        "threshold_hr": 165,
        "threshold_pace_seconds_per_km": 300,
        "duration_curve_bests": None,
        "aerobic_decoupling_threshold": 8.0,
    }


def _zc():
    return make_zone_constants()


def _hard_run(run_id, days_ago, pace_s_per_km, dist_km=1.0):
    """A hard/interval run whose effort is `dist_km` at `pace_s_per_km`."""
    dur = pace_s_per_km * dist_km
    d = (_TODAY - timedelta(days=days_ago)).isoformat()
    return {
        "run_id": run_id,
        "workout_date": d,
        "laps": [{"band": "hard", "avg_power": 260.0, "avg_hr": 165.0,
                  "distance_km": dist_km, "duration_seconds": dur}],
        "decoupling_pct": None,
        "avg_power": 260.0, "avg_hr": 165.0,
        "distance_km": dist_km, "duration_seconds": dur,
        "speed_signal": 1.2,
    }


def _easy_run(run_id, days_ago, pace_s_per_km, avg_hr=140.0, dist_km=3.0, decoupling_pct=5.0):
    dur = pace_s_per_km * dist_km
    d = (_TODAY - timedelta(days=days_ago)).isoformat()
    return {
        "run_id": run_id,
        "workout_date": d,
        "laps": [{"band": "easy", "avg_power": 180.0, "avg_hr": avg_hr,
                  "distance_km": dist_km, "duration_seconds": dur}],
        "decoupling_pct": decoupling_pct,
        "avg_power": 180.0, "avg_hr": avg_hr,
        "distance_km": dist_km, "duration_seconds": dur,
    }


# ── Target 1: an aborted/slow session does NOT lower Speed ──────────────────────

def test_aborted_session_does_not_lower_speed():
    """A slow/aborted effort (low perf) must not drag the top-3 mean down."""
    fast = [_hard_run(f"f{i}", days_ago=10 + i, pace_s_per_km=200.0) for i in range(3)]
    score_clean = compute_speed_score(fast, _prefs(), _zc())["score"]

    # Add an aborted session (very slow pace → low perf) on the most recent day.
    aborted = _hard_run("aborted", days_ago=1, pace_s_per_km=420.0)
    score_with_aborted = compute_speed_score(fast + [aborted], _prefs(), _zc())["score"]

    assert score_with_aborted >= score_clean - 0.01, (
        f"aborted session lowered speed: {score_clean} → {score_with_aborted}"
    )


# ── Target 2: one outlier-fast point moves the score by ≤ ~1/3 of its excess ────

def test_outlier_fast_point_dampened_by_top3_mean():
    """One blip-fast effort moves the top-3 mean by at most ~1/3 of its excess."""
    base = [_hard_run(f"b{i}", days_ago=10 + i, pace_s_per_km=240.0) for i in range(3)]
    base_score = compute_speed_score(base, _prefs(), _zc())["score"]

    outlier = _hard_run("blip", days_ago=1, pace_s_per_km=150.0)  # much faster
    outlier_perf = _vdot.rescale_to_score(
        _vdot.vdot_from_pace_duration(1000.0 / (150.0 / 60.0), 150.0 / 60.0)
    )
    new_score = compute_speed_score(base + [outlier], _prefs(), _zc())["score"]

    excess = outlier_perf - base_score
    move = new_score - base_score
    assert 0 < move <= excess / 3.0 + 0.5, (
        f"outlier moved score by {move}, excess {excess} (should be ≤ ~1/3)"
    )


# ── Target 3: a training gap → flat for 2 weeks, then ~1.5 pts/week ─────────────

def test_training_gap_decays_after_grace():
    """After the last run, score is flat for the 2-week grace, then falls ~1.5/wk."""
    # Three equal efforts, most recent `gap` days ago.
    def score_after_gap(gap_days):
        runs = [_hard_run(f"g{i}", days_ago=gap_days + i, pace_s_per_km=220.0) for i in range(3)]
        return compute_speed_score(runs, _prefs(), _zc())["score"]

    s0 = score_after_gap(1)     # essentially "now"
    s_grace = score_after_gap(14)  # 2 weeks — still inside grace
    s_3wk = score_after_gap(21)    # 3 weeks — 1 week past grace → −1.5
    s_4wk = score_after_gap(28)    # 4 weeks → −3.0

    assert abs(s_grace - s0) < 0.6, f"score should be ~flat within grace: {s0} vs {s_grace}"
    assert s_3wk < s_grace, "score must fall after the grace window"
    # ~1.5 pts/week between week 3 and week 4.
    assert abs((s_3wk - s_4wk) - 1.5) < 0.4, f"weekly decay off: {s_3wk} → {s_4wk}"


# ── Target 4: race floor holds ──────────────────────────────────────────────────

def test_race_floor_holds_against_mediocre_training():
    """Mediocre runs after a strong race can't pull the score below the decayed floor."""
    # A strong race 5 days ago → high perf floor.
    race_perf_val = _vdot.rescale_to_score(
        _vdot.vdot_from_pace_duration((10.0 * 1000.0) / (2400.0 / 60.0), 2400.0 / 60.0)
    )  # 10 km in 40:00
    race = {"perf": race_perf_val, "date": (_TODAY - timedelta(days=5)).isoformat()}

    # Three mediocre (slow) training runs after the race.
    mediocre = [_hard_run(f"m{i}", days_ago=1 + i, pace_s_per_km=360.0) for i in range(3)]

    result = compute_speed_score(mediocre, _prefs(), _zc(), race_perf=race)
    floor = race_perf_val - _vdot.decay_points(5)
    assert result["score"] >= floor - 0.01, (
        f"score {result['score']} fell below race floor {floor}"
    )


# ── Target 5: fewer than 3 qualifying runs → building_baseline ──────────────────

def test_fewer_than_three_runs_building_baseline():
    runs = [_hard_run(f"r{i}", days_ago=3 + i, pace_s_per_km=220.0) for i in range(2)]
    result = compute_speed_score(runs, _prefs(), _zc())
    assert result.get("state") == "building_baseline"


# ── Target 6: missing threshold_hr → needs_thresholds (endurance) ───────────────

def test_missing_threshold_hr_needs_thresholds():
    prefs = dict(_prefs())
    prefs["threshold_hr"] = None
    runs = [_easy_run(f"e{i}", days_ago=3 + i, pace_s_per_km=360.0) for i in range(4)]
    result = compute_endurance_score(runs, prefs, _zc())
    assert result.get("state") == "needs_thresholds"


# ── Target 7: block delta small/sane on a normal ramp (no "+43") ────────────────

def test_block_delta_sane_on_normal_ramp():
    """A normal ~monthly improvement should yield a small score(now)−score(4wk) delta.

    Emulates the frontend block delta: score at the last date minus the score at
    the trend point ~4 weeks earlier, on the absolute band.
    """
    # A gently improving speed series over ~8 weeks (slightly faster each week).
    runs = []
    for wk in range(8):
        days_ago = (7 - wk) * 7 + 1
        pace = 250.0 - wk * 3.0  # ~3 s/km/week faster — a realistic ramp
        runs.append(_hard_run(f"w{wk}", days_ago=days_ago, pace_s_per_km=pace))

    result = compute_speed_score(runs, _prefs(), _zc())
    trend = result["trend"]
    trend_dates = [date.fromisoformat(d) for d in result["trend_dates"]]

    last = trend[-1]
    cutoff = trend_dates[-1] - timedelta(days=28)
    base = None
    for i in range(len(trend) - 1, -1, -1):
        if trend_dates[i] <= cutoff:
            base = trend[i]
            break
    assert base is not None, "need a trend point ~4 weeks back"
    delta = last - base
    # A month of a gentle ramp is a few points — nowhere near the old "+43".
    assert 0 <= delta < 12, f"block delta artifact: {delta}"
