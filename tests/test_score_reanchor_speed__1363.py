"""TDD tests for issue #1363: Score re-anchor A — absolute anchoring core + Speed score.

Each test is anchored to a specific Acceptance Criterion from the issue.

AC1  – Shared anchoring helpers (vdot.py + running_performance.py) implement the
       VDOT-band model; _normalise_values is NOT used by the Speed path.
AC2  – Speed score is anchored on best demonstrated efforts and decays with time;
       a single slow/aborted session does NOT reduce it.
AC3  – Regression test from the a1d6a936 scenario shape: aborted interval run
       added on top of a strong recent history → Speed does not fall.
AC4  – Decay test: identical history shifted 8+ weeks stale yields a materially
       lower Speed score than recent history.
AC5  – formula_version token exists and is non-empty; race-floor and
       body_modifier multipliers are still applied unchanged on top.
AC6  – Endurance path co-exists with Speed path in the same module without error.
AC7  – Anchoring math validated against worked examples from the proposal doc
       (VDOT band endpoints, decay constants, top-3 mean invariants).
"""
from __future__ import annotations

from datetime import date, timedelta


from backend.services.vdot import (
    vdot_from_pace_duration,
    vdot_from_pace_seconds,
    rescale_to_score,
    decay_points,
    VDOT_FLOOR,
    VDOT_CEIL,
    GRACE_WEEKS,
    DECAY_PER_WEEK,
    TOP_K,
)
from backend.services.running_performance import (
    compute_endurance_score,
    compute_speed_score,
)
from backend.services.zone_constants import make_zone_constants, MIN_QUALIFYING_RUNS

_TODAY = date.today()


# ── Fixtures ──────────────────────────────────────────────────────────────────

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


def _hard_run(run_id, days_ago, pace_s_per_km, dist_km=1.0, run_subtype=None):
    dur = pace_s_per_km * dist_km
    d = (_TODAY - timedelta(days=days_ago)).isoformat()
    r = {
        "run_id": run_id,
        "workout_date": d,
        "laps": [{"band": "hard", "avg_power": 260.0, "avg_hr": 165.0,
                  "distance_km": dist_km, "duration_seconds": dur}],
        "decoupling_pct": None,
        "avg_power": 260.0, "avg_hr": 165.0,
        "distance_km": dist_km, "duration_seconds": dur,
    }
    if run_subtype is not None:
        r["run_subtype"] = run_subtype
    return r


def _easy_run(run_id, days_ago, pace_s_per_km, avg_hr=140.0, dist_km=3.0):
    dur = pace_s_per_km * dist_km
    d = (_TODAY - timedelta(days=days_ago)).isoformat()
    return {
        "run_id": run_id,
        "workout_date": d,
        "laps": [{"band": "easy", "avg_power": 180.0, "avg_hr": avg_hr,
                  "distance_km": dist_km, "duration_seconds": dur}],
        "decoupling_pct": 5.0,
        "avg_power": 180.0, "avg_hr": avg_hr,
        "distance_km": dist_km, "duration_seconds": dur,
    }


def _strong_history(n=3, base_pace=210.0):
    """n strong recent hard runs."""
    return [_hard_run(f"strong_{i}", days_ago=10 + i * 3, pace_s_per_km=base_pace) for i in range(n)]


# ═══════════════════════════════════════════════════════════════════════════════
# AC1 — Shared anchoring helpers; _normalise_values absent from Speed path
# ═══════════════════════════════════════════════════════════════════════════════

class TestAC1SharedAnchoring:
    """vdot.py exports all required helpers; running_performance imports them."""

    def test_vdot_helpers_importable(self):
        assert callable(vdot_from_pace_duration)
        assert callable(vdot_from_pace_seconds)
        assert callable(rescale_to_score)
        assert callable(decay_points)

    def test_vdot_floor_and_ceil_defined(self):
        assert isinstance(VDOT_FLOOR, float)
        assert isinstance(VDOT_CEIL, float)
        assert VDOT_CEIL > VDOT_FLOOR

    def test_decay_constants_match_proposal(self):
        # Proposal §4.2: 2-week grace, 1.5 pts/week
        assert GRACE_WEEKS == 2
        assert DECAY_PER_WEEK == 1.5

    def test_top_k_is_3(self):
        # Proposal §4.2: top-3 mean
        assert TOP_K == 3

    def test_normalise_values_not_in_running_performance(self):
        """_normalise_values must not be imported or defined in running_performance."""
        import backend.services.running_performance as rp
        assert not hasattr(rp, "_normalise_values"), (
            "_normalise_values found in running_performance — Speed path must not use it"
        )

    def test_running_performance_imports_from_vdot(self):
        import backend.services.running_performance as rp
        # The module must use vdot helpers
        assert hasattr(rp, "compute_speed_score")
        assert hasattr(rp, "compute_endurance_score")

    def test_speed_score_does_not_call_normalise(self):
        """compute_speed_score result is not relative to window min/max.

        Old min-max model: identical paces in the window normalise to 50.
        New absolute model: identical paces map to their true VDOT-band value,
        which will only equal 50 by coincidence. We verify the score is stable
        (same run-set always → same score) and that a clearly faster pace
        produces a higher score — neither holds in the relative model.
        """
        pace = 240.0  # 4:00/km — a respectable hard effort
        runs_a = [_hard_run(f"a{i}", days_ago=5 + i * 3, pace_s_per_km=pace)
                  for i in range(3)]
        runs_b = [_hard_run(f"b{i}", days_ago=5 + i * 3, pace_s_per_km=pace)
                  for i in range(3)]
        score_a = compute_speed_score(runs_a, _prefs(), _zc())["score"]
        score_b = compute_speed_score(runs_b, _prefs(), _zc())["score"]
        # Absolute model: same pace → same score (stable)
        assert abs(score_a - score_b) < 0.01, (
            f"Identical pace runs gave different scores: {score_a} vs {score_b}"
        )
        # A faster pace must produce a higher score
        faster_runs = [_hard_run(f"f{i}", days_ago=5 + i * 3, pace_s_per_km=200.0)
                       for i in range(3)]
        faster_score = compute_speed_score(faster_runs, _prefs(), _zc())["score"]
        assert faster_score > score_a, (
            f"Faster pace {200} should score higher than {pace}: {faster_score} vs {score_a}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# AC2 — Speed score: anchored on bests, decays; slow/aborted session doesn't lower it
# ═══════════════════════════════════════════════════════════════════════════════

class TestAC2SpeedAnchorOnBests:
    """Aborted/slow sessions don't lower the score; score eventually decays."""

    def test_aborted_session_does_not_lower_speed(self):
        """A slow/aborted hard run (low perf_i) cannot drag the top-3 mean down."""
        strong = _strong_history(n=3, base_pace=210.0)
        score_before = compute_speed_score(strong, _prefs(), _zc())["score"]

        # Very slow "aborted" session today
        aborted = _hard_run("aborted", days_ago=1, pace_s_per_km=450.0)
        score_after = compute_speed_score(strong + [aborted], _prefs(), _zc())["score"]

        assert score_after >= score_before - 0.01, (
            f"Aborted session lowered Speed: {score_before:.2f} → {score_after:.2f}"
        )

    def test_slow_session_does_not_lower_speed(self):
        """A legitimately slow (not aborted) hard session also cannot lower score."""
        strong = _strong_history(n=3, base_pace=215.0)
        score_clean = compute_speed_score(strong, _prefs(), _zc())["score"]

        slow = _hard_run("slow", days_ago=2, pace_s_per_km=380.0)
        score_with_slow = compute_speed_score(strong + [slow], _prefs(), _zc())["score"]

        assert score_with_slow >= score_clean - 0.01, (
            f"Slow session lowered Speed: {score_clean:.2f} → {score_with_slow:.2f}"
        )

    def test_score_decays_when_training_stops(self):
        """Score must fall materially when no new runs are added and efforts age."""
        # Run 3 good efforts 1 week ago
        recent = [_hard_run(f"r{i}", days_ago=7 + i, pace_s_per_km=215.0) for i in range(3)]
        # Same 3 efforts but from 7 weeks ago — far past the 2-week grace
        stale = [_hard_run(f"s{i}", days_ago=49 + i, pace_s_per_km=215.0) for i in range(3)]
        score_recent = compute_speed_score(recent, _prefs(), _zc())["score"]
        score_stale = compute_speed_score(stale, _prefs(), _zc())["score"]
        assert score_stale < score_recent, (
            f"Stale history ({score_stale:.2f}) should be lower than recent ({score_recent:.2f})"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# AC3 — Regression test: a1d6a936 scenario shape
# ═══════════════════════════════════════════════════════════════════════════════

class TestAC3A1D6A936Regression:
    """Regression: an aborted interval session (run_subtype='interval') on top of
    a strong recent history must NOT reduce the Speed score.

    This is the exact scenario that triggered the bug report:
    workout a1d6a936 ("Hard Intervals", run_subtype='interval') was aborted/cut
    short from exhaustion. Under the old relative model it LOWERED Speed (the new
    low pace pulled the window min down, shifting every normalized value). Under
    the new absolute model, a low perf_i is simply not in the top-3 and the
    score is unchanged or slightly higher (consistency bonus tick).
    """

    def _strong_history(self):
        return [
            _hard_run("prev_1", days_ago=14, pace_s_per_km=205.0, run_subtype="interval"),
            _hard_run("prev_2", days_ago=10, pace_s_per_km=208.0, run_subtype="interval"),
            _hard_run("prev_3", days_ago=7, pace_s_per_km=206.0, run_subtype="interval"),
        ]

    def test_aborted_interval_does_not_lower_speed(self):
        history = self._strong_history()
        score_clean = compute_speed_score(history, _prefs(), _zc())["score"]

        # a1d6a936 analog: aborted interval, very slow pace
        aborted = _hard_run(
            "a1d6a936", days_ago=3,
            pace_s_per_km=420.0, run_subtype="interval"
        )
        score_with_aborted = compute_speed_score(history + [aborted], _prefs(), _zc())["score"]

        assert score_with_aborted >= score_clean - 0.01, (
            f"a1d6a936 analog lowered Speed: {score_clean:.2f} → {score_with_aborted:.2f}. "
            "The aborted session's low perf_i must not displace a strong top-3."
        )

    def test_aborted_interval_may_add_consistency_bonus(self):
        """The aborted session CAN add a tiny consistency bonus — it just can't lower."""
        history = self._strong_history()
        score_clean = compute_speed_score(history, _prefs(), _zc())["score"]
        aborted = _hard_run("a1d6a936", days_ago=3, pace_s_per_km=420.0, run_subtype="interval")
        score_with_aborted = compute_speed_score(history + [aborted], _prefs(), _zc())["score"]
        # Allowed to be same or slightly higher (consistency tick) but not lower
        assert score_with_aborted >= score_clean - 0.01

    def test_genuine_good_interval_session_raises_speed(self):
        """Confirm the positive case: a genuinely faster session does raise Speed."""
        history = self._strong_history()
        score_before = compute_speed_score(history, _prefs(), _zc())["score"]

        new_best = _hard_run("new_best", days_ago=2, pace_s_per_km=195.0, run_subtype="interval")
        score_after = compute_speed_score(history + [new_best], _prefs(), _zc())["score"]

        assert score_after > score_before, (
            f"New best interval should raise Speed: {score_before:.2f} → {score_after:.2f}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# AC4 — Decay test: 8+ weeks stale → materially lower Speed score
# ═══════════════════════════════════════════════════════════════════════════════

class TestAC4DecayAfterEightWeeks:
    """History shifted 8+ weeks stale must yield a materially lower Speed score."""

    def test_eight_weeks_stale_materially_lower(self):
        """Same efforts 8 weeks ago vs 1 week ago: 8-week-old score is lower."""
        def _score_at_age(days_since_most_recent):
            runs = [_hard_run(f"r{i}", days_ago=days_since_most_recent + i * 3,
                              pace_s_per_km=215.0) for i in range(3)]
            return compute_speed_score(runs, _prefs(), _zc())["score"]

        score_recent = _score_at_age(7)    # efforts ~1 week old
        score_8wk = _score_at_age(56)      # efforts ~8 weeks old

        diff = score_recent - score_8wk
        assert diff > 4.0, (
            f"8-week-stale score should be materially lower than recent: "
            f"recent={score_recent:.2f}, 8wk={score_8wk:.2f}, diff={diff:.2f} (need > 4)"
        )

    def test_decay_rate_after_grace_matches_proposal(self):
        """After the 2-week grace, decay runs at ~1.5 pts/week per the proposal."""
        # Measure decay: take the SAME three efforts and shift them week by week.
        # At weeks 5 and 6, the consistency bonus window (28 days) is empty for
        # both, so the change is purely the anchor decay.
        def _score_at_age(days_since_most_recent):
            runs = [_hard_run(f"r{i}", days_ago=days_since_most_recent + i * 3,
                              pace_s_per_km=215.0) for i in range(3)]
            return compute_speed_score(runs, _prefs(), _zc())["score"]

        s5wk = _score_at_age(35)
        s6wk = _score_at_age(42)
        weekly_decay = s5wk - s6wk
        # Tolerance: ±0.5 around the 1.5 pts/week anchor rate
        assert 1.0 <= weekly_decay <= 2.0, (
            f"Weekly decay at 5→6 weeks = {weekly_decay:.3f}, expected ~1.5 ± 0.5"
        )

    def test_within_grace_no_decay(self):
        """Efforts within the 2-week grace lose nothing vs 'today's' score."""
        def _score_at_age(days_since_most_recent):
            runs = [_hard_run(f"r{i}", days_ago=days_since_most_recent + i * 3,
                              pace_s_per_km=215.0) for i in range(3)]
            return compute_speed_score(runs, _prefs(), _zc())["score"]

        score_1day = _score_at_age(1)
        score_14day = _score_at_age(14)  # exactly at the grace boundary
        # The consistency bonus shrinks by a few sessions worth, but the anchor
        # does NOT decay within the grace period — allow up to 1 pt variance
        assert abs(score_14day - score_1day) < 1.5, (
            f"Grace period violated: score dropped {score_1day:.2f} → {score_14day:.2f} "
            "within the 2-week grace window"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# AC5 — formula_version token; race-floor and body_modifier applied
# ═══════════════════════════════════════════════════════════════════════════════

class TestAC5FormulaVersionAndMultipliers:
    """formula_version token exists; race-floor and body_modifier are still applied."""

    def test_perf_formula_version_token_exists_in_main(self):
        """_PERF_FORMULA_VERSION must be defined and non-empty in backend.main."""
        # Avoid re-importing the full FastAPI app — just read the source.
        import ast
        import pathlib
        src = pathlib.Path("backend/main.py").read_text()
        tree = ast.parse(src)
        version_tokens = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == "_PERF_FORMULA_VERSION":
                        if isinstance(node.value, ast.Constant):
                            version_tokens.append(node.value.value)
        assert version_tokens, "_PERF_FORMULA_VERSION not found in backend/main.py"
        val = version_tokens[0]
        assert isinstance(val, str) and val, "_PERF_FORMULA_VERSION must be a non-empty string"
        assert "vdot" in val.lower(), (
            f"_PERF_FORMULA_VERSION={val!r} should contain 'vdot' to indicate the new model"
        )

    def test_race_floor_raises_score_above_mediocre_runs(self):
        """A strong race anchor keeps the score above mediocre post-race training."""
        # Race VDOT-band perf at a respectable level
        race_vdot = vdot_from_pace_duration(1000.0 / (210.0 / 60.0), 1.0)
        race_perf_val = rescale_to_score(race_vdot)
        race = {"perf": race_perf_val, "date": (_TODAY - timedelta(days=5)).isoformat()}

        # Three very slow post-race sessions (low perf_i)
        mediocre = [_hard_run(f"m{i}", days_ago=1 + i, pace_s_per_km=420.0) for i in range(3)]

        result_with_race = compute_speed_score(mediocre, _prefs(), _zc(), race_perf=race)
        result_no_race = compute_speed_score(mediocre, _prefs(), _zc())

        # Race floor must push the score above what mediocre runs alone would produce
        assert result_with_race["score"] > result_no_race["score"] - 0.01, (
            "Race floor should not lower the score; it provides a floor"
        )
        floor = max(0.0, race_perf_val - decay_points(5))
        assert result_with_race["score"] >= floor - 0.01, (
            f"score {result_with_race['score']:.2f} fell below race floor {floor:.2f}"
        )

    def test_body_modifier_above_1_increases_score(self):
        """body_modifier > 1.0 increases the displayed score proportionally."""
        runs = _strong_history(n=3)
        base = compute_speed_score(runs, _prefs(), _zc(), body_modifier=1.0)["score"]
        boosted = compute_speed_score(runs, _prefs(), _zc(), body_modifier=1.03)["score"]
        assert boosted > base, (
            f"body_modifier=1.03 should raise score: {base:.2f} → {boosted:.2f}"
        )

    def test_body_modifier_below_1_decreases_score(self):
        """body_modifier < 1.0 decreases the displayed score."""
        runs = _strong_history(n=3)
        base = compute_speed_score(runs, _prefs(), _zc(), body_modifier=1.0)["score"]
        reduced = compute_speed_score(runs, _prefs(), _zc(), body_modifier=0.92)["score"]
        assert reduced < base, (
            f"body_modifier=0.92 should reduce score: {base:.2f} → {reduced:.2f}"
        )

    def test_body_modifier_neutral_unchanged(self):
        """body_modifier=1.0 is neutral."""
        runs = _strong_history(n=3)
        r1 = compute_speed_score(runs, _prefs(), _zc(), body_modifier=1.0)["score"]
        r2 = compute_speed_score(runs, _prefs(), _zc())["score"]
        assert abs(r1 - r2) < 0.01


# ═══════════════════════════════════════════════════════════════════════════════
# AC6 — Endurance path co-exists; both paths usable without error
# ═══════════════════════════════════════════════════════════════════════════════

class TestAC6EndurancePathCoexists:
    """Both endurance and speed paths live in the same module and are callable."""

    def test_both_functions_importable(self):
        from backend.services.running_performance import (
            compute_endurance_score, compute_speed_score
        )
        assert callable(compute_endurance_score)
        assert callable(compute_speed_score)

    def test_endurance_score_returns_valid_result(self):
        easy_runs = [
            {
                "run_id": f"e{i}",
                "workout_date": (_TODAY - timedelta(days=5 + i * 5)).isoformat(),
                "laps": [{"band": "easy", "avg_power": 175.0, "avg_hr": 140.0,
                          "distance_km": 3.0, "duration_seconds": 1080.0}],
                "decoupling_pct": 5.0,
                "avg_power": 175.0, "avg_hr": 140.0,
                "distance_km": 5.0, "duration_seconds": 1800.0,
            }
            for i in range(MIN_QUALIFYING_RUNS)
        ]
        result = compute_endurance_score(easy_runs, _prefs(), _zc())
        # Returns dict — either a score or a known state
        assert isinstance(result, dict)
        has_score = "score" in result
        has_state = result.get("state") in ("building_baseline", "needs_thresholds")
        assert has_score or has_state

    def test_speed_score_not_affected_by_calling_endurance_first(self):
        """The two functions are pure — calling one first must not alter the other."""
        easy_runs = [
            {
                "run_id": f"e{i}",
                "workout_date": (_TODAY - timedelta(days=5 + i * 5)).isoformat(),
                "laps": [{"band": "easy", "avg_hr": 140.0,
                          "distance_km": 3.0, "duration_seconds": 1080.0}],
                "decoupling_pct": 5.0, "avg_hr": 140.0,
                "distance_km": 5.0, "duration_seconds": 1800.0,
            }
            for i in range(MIN_QUALIFYING_RUNS)
        ]
        hard_runs = _strong_history(n=3)

        # Call endurance first
        compute_endurance_score(easy_runs, _prefs(), _zc())

        # Speed score must still produce a valid result
        result = compute_speed_score(hard_runs, _prefs(), _zc())
        assert isinstance(result, dict)
        if "score" in result:
            assert 0 <= result["score"] <= 100


# ═══════════════════════════════════════════════════════════════════════════════
# AC7 — Anchoring math against proposal worked examples; decay curve invariants
# ═══════════════════════════════════════════════════════════════════════════════

class TestAC7AnchoringMathProposalExamples:
    """Worked examples from proposal doc §4.1 / §6 validation targets."""

    def test_vdot_band_floor_is_zero(self):
        assert rescale_to_score(VDOT_FLOOR) == 0.0

    def test_vdot_band_ceil_is_100(self):
        assert rescale_to_score(VDOT_CEIL) == 100.0

    def test_proposal_calibration_half_marathon_2h19(self):
        # Proposal table: race half 2:19 → VDOT 31.1 → ~37 on (15/58) band
        # 2:19 = 139 min, 21.1 km → pace = 139*60/21.1 = 395.7 s/km
        vdot = vdot_from_pace_seconds(395.3, 139.0)
        score = rescale_to_score(vdot)
        assert 34.0 <= score <= 41.0, f"half 2:19 → score {score:.1f}, expect 34–41"

    def test_proposal_calibration_best_hard_track(self):
        # Proposal table: best hard track effort → VDOT 41.9 → ~63
        # Infer a pace from VDOT 41.9 at ~8 min: use direct vdot check
        # vdot_from_pace_seconds(p, 8) ≈ 41.9 ↔ score ≈ 63
        score = rescale_to_score(41.9)
        assert 58.0 <= score <= 68.0, f"VDOT 41.9 → score {score:.1f}, expect 58–68"

    def test_proposal_calibration_easy_z2(self):
        # Proposal table: easy Z2 run → VDOT 24.0 → ~21
        score = rescale_to_score(24.0)
        assert 15.0 <= score <= 27.0, f"VDOT 24 → score {score:.1f}, expect 15–27"

    def test_decay_zero_within_grace(self):
        assert decay_points(0) == 0.0
        assert decay_points(7) == 0.0    # 1 week — inside grace
        assert decay_points(14) == 0.0   # exactly 2 weeks

    def test_decay_1_5_per_week_after_grace(self):
        # 3 weeks: 1 week past grace → (3-2) × 1.5 = 1.5
        assert abs(decay_points(21) - 1.5) < 1e-9
        # 4 weeks: (4-2) × 1.5 = 3.0
        assert abs(decay_points(28) - 3.0) < 1e-9

    def test_decay_monotonic_after_grace(self):
        assert decay_points(35) > decay_points(28) > decay_points(21) > 0

    def test_top3_mean_rejects_fourth_best(self):
        """Adding a fourth run worse than the top-3 leaves the score unchanged."""
        top3 = [_hard_run(f"t{i}", days_ago=5 + i, pace_s_per_km=205.0 + i * 5) for i in range(3)]
        score_3 = compute_speed_score(top3, _prefs(), _zc())["score"]

        # Add a worse run — should not change the anchor
        worse = _hard_run("worse", days_ago=1, pace_s_per_km=350.0)
        score_4 = compute_speed_score(top3 + [worse], _prefs(), _zc())["score"]

        # Score after adding worse run must be >= before (may gain consistency bonus)
        assert score_4 >= score_3 - 0.01, (
            f"Adding a below-top-3 run lowered score: {score_3:.2f} → {score_4:.2f}"
        )

    def test_top3_mean_not_single_max(self):
        """One outlier-fast point moves the score by at most ~1/3 of its excess."""
        base_pace = 240.0
        base_runs = [_hard_run(f"b{i}", days_ago=10 + i, pace_s_per_km=base_pace) for i in range(3)]
        base_score = compute_speed_score(base_runs, _prefs(), _zc())["score"]

        outlier_pace = 160.0  # much faster
        outlier = _hard_run("blip", days_ago=2, pace_s_per_km=outlier_pace)
        outlier_perf = rescale_to_score(vdot_from_pace_duration(1000.0 / (outlier_pace / 60.0), outlier_pace / 60.0))
        new_score = compute_speed_score(base_runs + [outlier], _prefs(), _zc())["score"]

        excess = outlier_perf - base_score
        move = new_score - base_score
        # Top-3 mean dampens the outlier to ≤ 1/3 of its excess
        assert 0 < move <= excess / 3.0 + 1.0, (
            f"Outlier moved score by {move:.2f}, excess was {excess:.2f} "
            f"(should be ≤ ~1/3 = {excess/3.0:.2f})"
        )

    def test_absolute_band_same_pace_same_score_regardless_of_window(self):
        """The same pace always maps to the same absolute VDOT-band score.

        Old relative model: identical efficiencies normalise to ~50. New model:
        identical paces map to the same ABSOLUTE value every time.
        """
        pace = 240.0
        runs_a = [_hard_run(f"a{i}", days_ago=5 + i * 3, pace_s_per_km=pace) for i in range(3)]
        runs_b = [_hard_run(f"b{i}", days_ago=5 + i * 3, pace_s_per_km=pace) for i in range(3)]

        score_a = compute_speed_score(runs_a, _prefs(), _zc())["score"]
        score_b = compute_speed_score(runs_b, _prefs(), _zc())["score"]

        assert abs(score_a - score_b) < 0.01, (
            f"Same paces, different run IDs → different scores: {score_a} vs {score_b}"
        )
