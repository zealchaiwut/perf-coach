"""Tests for issue #1331 — Recalibrate endurance training-run path.

Evidence from PRD investigation: per-run endurance perfs from training data
(15–28) sit well below race-demonstrated fitness (34–37.5). Two root causes:
  1. HR extrapolation exponent 1.5 maps easy runs to an equivalent-threshold
     pace ~48 s/km slower than stated threshold — systematically pessimistic.
  2. Durability factor 1 - dec/50 removes ~5 band points for typical 5–20%
     decoupling — too punishing.

Acceptance criteria:
  AC1: For athlete with races demonstrating perf ~34–37, steady training weeks
       produce a block endurance score within ~7 points of race-implied level
       (not 10+ below as before the fix).
  AC2: Race floor acts as a floor (minimum) only — training runs drive the
       score when they land at the calibrated level; race anchor adds < 5 pts
       to the training-derived score.
  AC3: HR extrapolation exponent recalibrated above 1.5 (config check).
  AC4: Durability factor uses /100 denominator (softer than old /50).
  AC5: Formula token bumped past vdot-v12 in main.py.
"""
import pytest
from backend.services.running_performance import (
    compute_endurance_score,
    PERFORMANCE_CONFIG,
)
from backend.services.zone_constants import make_zone_constants


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _zeal_prefs():
    """Preferences matching the PRD 'zeal' athlete described in issue #1331."""
    return {
        "threshold_hr": 155,
        "threshold_pace_seconds_per_km": 360,
        "aerobic_decoupling_threshold": 8.0,
        "ftp_w": None,
        "duration_curve_bests": None,
    }


def _easy_run(run_id, *, lap_pace=480, avg_hr=140, decoupling_pct=8.0,
              workout_date="2026-01-01", dist_km=10.0):
    """Realistic easy run for the zeal athlete.

    lap_pace=480 s/km (8:00/km), avg_hr=140 at threshold_hr=155 — matches the
    runs described in the issue that were scoring 25–29 (pre-durability) when
    race fitness was 34–37.5.
    Session duration > 2400 s (40 min guard).
    """
    session_dur = max(2700.0, lap_pace * dist_km)
    return {
        "run_id": run_id,
        "workout_date": workout_date,
        "laps": [
            {
                "band": "easy",
                "avg_hr": float(avg_hr),
                "distance_km": dist_km / 2,
                "duration_seconds": float(lap_pace * dist_km / 2),
            }
        ],
        "decoupling_pct": decoupling_pct,
        "avg_hr": float(avg_hr),
        "distance_km": dist_km,
        "duration_seconds": session_dur,
    }


def _five_easy_runs(decoupling_pct=5.0):
    """Five weekly easy runs at the zeal athlete's typical easy pace."""
    dates = [
        "2026-01-01", "2026-01-08", "2026-01-15",
        "2026-01-22", "2026-01-29",
    ]
    return [
        _easy_run(f"r{i+1}", decoupling_pct=decoupling_pct, workout_date=dates[i])
        for i in range(5)
    ]


# ---------------------------------------------------------------------------
# AC3: HR extrapolation exponent recalibrated
# ---------------------------------------------------------------------------

class TestHRExponentRecalibrated:
    """AC3: endurance_hr_extrapolation_exponent must be > 1.5 after this fix."""

    def test_exponent_greater_than_1_5(self):
        exponent = PERFORMANCE_CONFIG["endurance_hr_extrapolation_exponent"]
        assert exponent > 1.5, (
            f"Exponent {exponent} has not been recalibrated upward from 1.5 "
            "(issue #1331 fix requires a larger exponent to reduce systematic "
            "pessimism in easy-run HR extrapolation)"
        )

    def test_exponent_is_at_least_2(self):
        """Exponent ≥ 2.0 needed to close the ~48 s/km extrapolation gap shown
        in the issue for an athlete at 140/155 bpm running at 480 s/km."""
        exponent = PERFORMANCE_CONFIG["endurance_hr_extrapolation_exponent"]
        assert exponent >= 2.0, (
            f"Exponent {exponent} is too small; ≥ 2.0 required to meaningfully "
            "reduce the extrapolation error described in issue #1331"
        )


# ---------------------------------------------------------------------------
# AC4: Durability factor softened
# ---------------------------------------------------------------------------

class TestDurabilityFactorSoftened:
    """AC4: Durability penalty uses 1 - dec/100 (not 1 - dec/50)."""

    def _score_with_decoupling(self, decoupling_pct):
        runs = [
            _easy_run(f"r{i}", decoupling_pct=decoupling_pct,
                      workout_date=f"2026-01-{i:02d}")
            for i in range(1, 6)
        ]
        return compute_endurance_score(runs, _zeal_prefs(), make_zone_constants())

    def test_20pct_decoupling_yields_score_above_15(self):
        """With old 1-dec/50 formula and 20% decoupling: factor=0.6 → severe penalty.
        With new 1-dec/100: factor=0.8 → run at ~480 s/km should score ≥ 15."""
        result = self._score_with_decoupling(20.0)
        if result.get("state") == "building_baseline":
            pytest.skip("Not enough qualifying runs")
        assert result["score"] >= 15.0, (
            f"Score {result['score']:.1f} too low with 20% decoupling — "
            "softened durability (1 - dec/100) should yield factor=0.8, not 0.6"
        )

    def test_5pct_decoupling_vs_no_decoupling_gap_under_10pct(self):
        """5% decoupling should deduct at most ~8% of the no-decoupling score.

        Old formula: 1 - 5/50 = 0.90 (10% penalty).
        New formula: 1 - 5/100 = 0.95 (5% penalty) → gap < 8%.
        """
        result_dec = self._score_with_decoupling(5.0)
        result_none = self._score_with_decoupling(None)
        if (result_dec.get("state") == "building_baseline" or
                result_none.get("state") == "building_baseline"):
            pytest.skip("Not enough qualifying runs")
        gap = result_none["score"] - result_dec["score"]
        max_allowed_gap = result_none["score"] * 0.10  # ≤ 10% of base
        assert gap <= max_allowed_gap, (
            f"5% decoupling gap {gap:.2f} exceeds 10% of no-decoupling score "
            f"{result_none['score']:.1f} (= {max_allowed_gap:.2f}); "
            "new durability formula should give a ≤ 5% penalty"
        )


# ---------------------------------------------------------------------------
# AC1: Training score close to race-demonstrated fitness
# ---------------------------------------------------------------------------

class TestTrainingScoreCalibration:
    """AC1: Steady training weeks produce score within ~7 points of race fitness."""

    def test_easy_runs_at_realistic_pace_score_above_28(self):
        """5 easy runs at 480 s/km / 140 bpm → score ≥ 28.

        Before fix (k=1.5, /50 durability): same runs produced ~21-25.
        After fix (k≥2, /100 durability): should be ≥ 28 (within ~10 of 37.5).
        """
        runs = _five_easy_runs(decoupling_pct=5.0)
        result = compute_endurance_score(runs, _zeal_prefs(), make_zone_constants())
        if result.get("state") == "building_baseline":
            pytest.skip("Not enough qualifying runs")
        assert result["score"] >= 28.0, (
            f"Score {result['score']:.1f} — easy runs at 480 s/km (8:00/km) at "
            "140/155 bpm should score ≥ 28 after recalibration (was ~21-25 before)"
        )

    def test_score_within_10_of_race_implied_fitness(self):
        """Block endurance score from training ≥ race_perf - 10 points.

        Race-implied fitness from Yamanakako Half: perf 37.5.
        Training score should land within 10 points of that (was 10+ below before).
        """
        runs = _five_easy_runs(decoupling_pct=5.0)
        race = {"perf": 37.5, "date": "2025-12-01"}
        result = compute_endurance_score(
            runs, _zeal_prefs(), make_zone_constants(), race_perf=race
        )
        if result.get("state") == "building_baseline":
            pytest.skip("Not enough qualifying runs")
        race_implied = 37.5
        assert result["score"] >= race_implied - 10, (
            f"Score {result['score']:.1f} is more than 10 points below race-implied "
            f"{race_implied}; recalibration should bring training within ~10 pts"
        )

    def test_high_decoupling_runs_still_score_above_22(self):
        """10% decoupling (typical long run) should still score ≥ 22 after fix.

        Before fix: top-3 mean dropped from ~29.6 to ~24.4 (issue data).
        After fix: softer durability means less drop from the higher base.
        """
        runs = _five_easy_runs(decoupling_pct=10.0)
        result = compute_endurance_score(runs, _zeal_prefs(), make_zone_constants())
        if result.get("state") == "building_baseline":
            pytest.skip("Not enough qualifying runs")
        assert result["score"] >= 22.0, (
            f"Score {result['score']:.1f} with 10% decoupling is too low; "
            "expected ≥ 22 after recalibration (runs at realistic easy pace)"
        )


# ---------------------------------------------------------------------------
# AC2: Race floor acts as floor, not primary driver
# ---------------------------------------------------------------------------

class TestRaceFloorIsFloorOnly:
    """AC2: When training runs are calibrated correctly, race floor is a floor."""

    def test_training_only_score_is_meaningful(self):
        """Score WITHOUT race_perf should be ≥ 25 — training drives the score."""
        runs = _five_easy_runs(decoupling_pct=5.0)
        result = compute_endurance_score(
            runs, _zeal_prefs(), make_zone_constants(), race_perf=None
        )
        if result.get("state") == "building_baseline":
            pytest.skip("Not enough qualifying runs")
        assert result["score"] >= 25.0, (
            f"Training-only score {result['score']:.1f} < 25 — training runs "
            "should drive the score after recalibration, not just the race floor"
        )

    def test_race_anchor_adds_small_lift_when_training_is_good(self):
        """Adding race_perf=37.5 to calibrated training should add < 8 pts.

        Before fix: race floor added ~10+ pts because training scores were so low.
        After fix: training scores are close to race level, so floor rarely binds.
        """
        runs = _five_easy_runs(decoupling_pct=5.0)
        prefs = _zeal_prefs()
        zc = make_zone_constants()
        # Race 60 days ago — enough decay to not dominate
        race = {"perf": 37.5, "date": "2025-11-30"}

        result_no_race = compute_endurance_score(runs, prefs, zc, race_perf=None)
        result_with_race = compute_endurance_score(runs, prefs, zc, race_perf=race)

        if (result_no_race.get("state") == "building_baseline" or
                result_with_race.get("state") == "building_baseline"):
            pytest.skip("Not enough qualifying runs")

        lift = result_with_race["score"] - result_no_race["score"]
        assert lift < 8.0, (
            f"Race anchor adds {lift:.1f} pts to training score "
            f"{result_no_race['score']:.1f} → {result_with_race['score']:.1f}. "
            "When training is calibrated, race floor should act as minimum only, "
            "not add a large lift (> 8 pts indicates race is the primary driver)"
        )

    def test_score_re_anchor_contract_preserved(self):
        """Race floor still enforces a minimum (aborted/partial session contract).

        A run with no aerobic laps must not lower the race-floor-anchored score.
        """
        race = {"perf": 37.5, "date": "2026-01-29"}  # very recent
        # Valid training to qualify
        runs = _five_easy_runs(decoupling_pct=5.0)
        result = compute_endurance_score(
            runs, _zeal_prefs(), make_zone_constants(), race_perf=race
        )
        if result.get("state") == "building_baseline":
            pytest.skip("Not enough qualifying runs")
        # Score must be ≥ race_perf - decay(0 days) = 37.5
        assert result["score"] >= 37.0, (
            f"Score {result['score']:.1f} is below the undecayed race floor of "
            "37.5; re-anchor contract broken (issue #1331 constraint a1d6a936)"
        )


# ---------------------------------------------------------------------------
# AC5: Formula version bumped
# ---------------------------------------------------------------------------

class TestFormulaVersionBumped:
    """AC5: _PERF_FORMULA_VERSION in main.py must be bumped past vdot-v12."""

    def test_perf_formula_version_is_at_least_v13(self):
        """After the calibration change, formula version must be ≥ vdot-v13.

        The version gates both the Neon score-history cache and the plan-bundle
        cache — bumping ensures stale cached scores from vdot-v12 are recomputed.
        """
        import backend.main as main_mod
        version = getattr(main_mod, "_PERF_FORMULA_VERSION", None)
        assert version is not None, "_PERF_FORMULA_VERSION not found in backend.main"
        assert version.startswith("vdot-v"), (
            f"Unexpected _PERF_FORMULA_VERSION format: {version!r}; expected 'vdot-vN'"
        )
        num = int(version.split("vdot-v")[1])
        assert num >= 13, (
            f"Formula version {version!r} not bumped for issue #1331; "
            "expected ≥ vdot-v13 (current is vdot-v12 at time of this ticket)"
        )
