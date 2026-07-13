"""Tests for issue #1372: gap analyzer load-mix rules.

AC coverage:
- AC1: intensity_too_hard — fire/no-fire/insufficient + verdict-deferral
- AC2: aerobic_durability_gap — fire/no-fire/insufficient + verdict-deferral
- AC3: speed_neglected — fire/no-fire/insufficient + verdict-deferral
- AC4: back_off verdict → severity 1 + deferred-while-backing-off marker for all rules
- AC5: pure functions, constants documented, insufficient-data → None
"""
from __future__ import annotations

import datetime

import pytest

_DATE = datetime.date(2026, 7, 14)


# ── helpers ───────────────────────────────────────────────────────────────────

def _inputs(**kw) -> dict:
    return {"week_start": _DATE, **kw}


# ── AC1: intensity_too_hard ───────────────────────────────────────────────────

class TestIntensityTooHard:
    def _rule(self):
        from backend.services.gap_analysis.rules.load_mix import intensity_too_hard
        return intensity_too_hard

    def test_fires_when_high_pct_above_target(self):
        """Fire: high zone above the 20% upper bound."""
        rule = self._rule()
        result = rule(_inputs(
            intensity_4w={"low_pct": 55.0, "moderate_pct": 15.0, "high_pct": 30.0},
            training_verdict="build",
        ))
        assert result is not None
        assert result.code == "intensity_too_hard"
        assert result.severity == 2

    def test_silent_when_on_target(self):
        """No-fire: all bands within polarized target bounds."""
        rule = self._rule()
        result = rule(_inputs(
            intensity_4w={"low_pct": 78.0, "moderate_pct": 5.0, "high_pct": 17.0},
            training_verdict="build",
        ))
        assert result is None

    def test_silent_when_high_not_the_problem(self):
        """No-fire: deviation is in low/moderate but high zone is not above target."""
        rule = self._rule()
        result = rule(_inputs(
            intensity_4w={"low_pct": 60.0, "moderate_pct": 25.0, "high_pct": 15.0},
            training_verdict="build",
        ))
        assert result is None

    def test_returns_none_when_intensity_4w_absent(self):
        """Insufficient data: intensity_4w key missing → None."""
        rule = self._rule()
        assert rule(_inputs(training_verdict="build")) is None

    def test_returns_none_when_pct_values_none(self):
        """Insufficient data: any pct is None → None."""
        rule = self._rule()
        result = rule(_inputs(
            intensity_4w={"low_pct": None, "moderate_pct": None, "high_pct": None},
            training_verdict="build",
        ))
        assert result is None

    def test_back_off_verdict_downgrades_to_severity_1(self):
        """AC4: back_off → severity 1 with deferred marker."""
        rule = self._rule()
        result = rule(_inputs(
            intensity_4w={"low_pct": 55.0, "moderate_pct": 15.0, "high_pct": 30.0},
            training_verdict="back_off",
        ))
        assert result is not None
        assert result.severity == 1
        assert "back" in result.recommendation.lower() or "defer" in result.recommendation.lower()

    def test_evidence_contains_high_pct(self):
        """AC5: evidence includes high_pct metric."""
        rule = self._rule()
        result = rule(_inputs(
            intensity_4w={"low_pct": 55.0, "moderate_pct": 15.0, "high_pct": 30.0},
            training_verdict="build",
        ))
        assert result is not None
        metrics = {e["metric"] for e in result.evidence}
        assert any("high" in m for m in metrics)

    def test_fires_at_boundary(self):
        """Fire: high_pct exactly above the 20 upper bound (e.g. 21)."""
        rule = self._rule()
        result = rule(_inputs(
            intensity_4w={"low_pct": 65.0, "moderate_pct": 14.0, "high_pct": 21.0},
            training_verdict="build",
        ))
        assert result is not None

    def test_silent_at_upper_bound(self):
        """No-fire: high_pct exactly at the 20 upper bound (on_target)."""
        rule = self._rule()
        result = rule(_inputs(
            intensity_4w={"low_pct": 75.0, "moderate_pct": 5.0, "high_pct": 20.0},
            training_verdict="build",
        ))
        assert result is None

    def test_registered_in_engine(self):
        """AC5: intensity_too_hard is registered in the engine registry."""
        from backend.services.gap_analysis.engine import _REGISTRY
        names = [e.fn.__name__ for e in _REGISTRY._rules]
        assert "intensity_too_hard" in names

    def test_requires_intensity_4w(self):
        """AC5: Rule is registered with requires=['intensity_4w', ...]."""
        from backend.services.gap_analysis.engine import _REGISTRY
        entry = next(e for e in _REGISTRY._rules if e.fn.__name__ == "intensity_too_hard")
        assert "intensity_4w" in entry.requires


# ── AC2: aerobic_durability_gap ────────────────────────────────────────────────

class TestAerobicDurabilityGap:
    def _rule(self):
        from backend.services.gap_analysis.rules.load_mix import aerobic_durability_gap
        return aerobic_durability_gap

    def test_fires_when_avg_decoupling_above_threshold(self):
        """Fire: avg decoupling above threshold with >= 2 long runs."""
        rule = self._rule()
        result = rule(_inputs(
            long_run_decoupling_4w={"avg_decoupling_pct": 8.5, "count": 3},
            training_verdict="build",
        ))
        assert result is not None
        assert result.code == "aerobic_durability_gap"
        assert result.severity == 2

    def test_silent_when_decoupling_within_threshold(self):
        """No-fire: avg decoupling below threshold."""
        rule = self._rule()
        result = rule(_inputs(
            long_run_decoupling_4w={"avg_decoupling_pct": 3.0, "count": 3},
            training_verdict="build",
        ))
        assert result is None

    def test_silent_when_fewer_than_two_long_runs(self):
        """No-fire: fewer than 2 long runs → insufficient sample size."""
        rule = self._rule()
        result = rule(_inputs(
            long_run_decoupling_4w={"avg_decoupling_pct": 9.0, "count": 1},
            training_verdict="build",
        ))
        assert result is None

    def test_returns_none_when_input_absent(self):
        """Insufficient data: long_run_decoupling_4w key missing → None."""
        rule = self._rule()
        assert rule(_inputs(training_verdict="build")) is None

    def test_returns_none_when_decoupling_pct_none(self):
        """Insufficient data: avg_decoupling_pct is None → None."""
        rule = self._rule()
        result = rule(_inputs(
            long_run_decoupling_4w={"avg_decoupling_pct": None, "count": 3},
            training_verdict="build",
        ))
        assert result is None

    def test_returns_none_when_zero_long_runs(self):
        """Insufficient data: count=0 → None."""
        rule = self._rule()
        result = rule(_inputs(
            long_run_decoupling_4w={"avg_decoupling_pct": None, "count": 0},
            training_verdict="build",
        ))
        assert result is None

    def test_back_off_verdict_downgrades_to_severity_1(self):
        """AC4: back_off → severity 1 with deferred marker."""
        rule = self._rule()
        result = rule(_inputs(
            long_run_decoupling_4w={"avg_decoupling_pct": 8.5, "count": 3},
            training_verdict="back_off",
        ))
        assert result is not None
        assert result.severity == 1
        assert "back" in result.recommendation.lower() or "defer" in result.recommendation.lower()

    def test_evidence_contains_decoupling_pct(self):
        """AC5: evidence includes decoupling metric with threshold."""
        rule = self._rule()
        result = rule(_inputs(
            long_run_decoupling_4w={"avg_decoupling_pct": 8.5, "count": 3},
            training_verdict="build",
        ))
        assert result is not None
        metrics = {e["metric"] for e in result.evidence}
        assert any("decoupling" in m for m in metrics)
        ev = next(e for e in result.evidence if "decoupling" in e["metric"])
        assert ev["threshold"] is not None

    def test_registered_in_engine(self):
        from backend.services.gap_analysis.engine import _REGISTRY
        names = [e.fn.__name__ for e in _REGISTRY._rules]
        assert "aerobic_durability_gap" in names

    def test_requires_long_run_decoupling_4w(self):
        from backend.services.gap_analysis.engine import _REGISTRY
        entry = next(e for e in _REGISTRY._rules if e.fn.__name__ == "aerobic_durability_gap")
        assert "long_run_decoupling_4w" in entry.requires


# ── AC3: speed_neglected ─────────────────────────────────────────────────────

class TestSpeedNeglected:
    def _rule(self):
        from backend.services.gap_analysis.rules.load_mix import speed_neglected
        return speed_neglected

    def test_fires_when_speed_decayed_and_quality_low(self):
        """Fire: speed decayed > threshold AND < 1 quality session/week over 3 weeks."""
        rule = self._rule()
        result = rule(_inputs(
            speed_score_history_8w={
                "oldest_speed": 80.0, "newest_speed": 65.0,
                "formula_version": "v1", "count": 10,
            },
            quality_sessions_3w={"count": 1, "window_weeks": 3},
            training_verdict="build",
        ))
        assert result is not None
        assert result.code == "speed_neglected"
        assert result.severity == 2

    def test_silent_when_speed_not_decayed_enough(self):
        """No-fire: decay below threshold."""
        rule = self._rule()
        result = rule(_inputs(
            speed_score_history_8w={
                "oldest_speed": 80.0, "newest_speed": 78.0,
                "formula_version": "v1", "count": 10,
            },
            quality_sessions_3w={"count": 0, "window_weeks": 3},
            training_verdict="build",
        ))
        assert result is None

    def test_silent_when_quality_sessions_adequate(self):
        """No-fire: even with decay, enough quality sessions per week."""
        rule = self._rule()
        result = rule(_inputs(
            speed_score_history_8w={
                "oldest_speed": 80.0, "newest_speed": 65.0,
                "formula_version": "v1", "count": 10,
            },
            quality_sessions_3w={"count": 4, "window_weeks": 3},
            training_verdict="build",
        ))
        assert result is None

    def test_returns_none_when_speed_history_absent(self):
        """Insufficient data: speed_score_history_8w missing → None."""
        rule = self._rule()
        result = rule(_inputs(
            quality_sessions_3w={"count": 0, "window_weeks": 3},
            training_verdict="build",
        ))
        assert result is None

    def test_returns_none_when_quality_sessions_absent(self):
        """Insufficient data: quality_sessions_3w missing → None."""
        rule = self._rule()
        result = rule(_inputs(
            speed_score_history_8w={
                "oldest_speed": 80.0, "newest_speed": 65.0,
                "formula_version": "v1", "count": 10,
            },
            training_verdict="build",
        ))
        assert result is None

    def test_returns_none_when_speed_history_none(self):
        """Insufficient data: speed_score_history_8w is None → None."""
        rule = self._rule()
        result = rule(_inputs(
            speed_score_history_8w=None,
            quality_sessions_3w={"count": 0, "window_weeks": 3},
            training_verdict="build",
        ))
        assert result is None

    def test_back_off_verdict_downgrades_to_severity_1(self):
        """AC4: back_off → severity 1 with deferred marker."""
        rule = self._rule()
        result = rule(_inputs(
            speed_score_history_8w={
                "oldest_speed": 80.0, "newest_speed": 65.0,
                "formula_version": "v1", "count": 10,
            },
            quality_sessions_3w={"count": 1, "window_weeks": 3},
            training_verdict="back_off",
        ))
        assert result is not None
        assert result.severity == 1
        assert "back" in result.recommendation.lower() or "defer" in result.recommendation.lower()

    def test_evidence_contains_speed_decay(self):
        """AC5: evidence includes speed decay metric with threshold."""
        rule = self._rule()
        result = rule(_inputs(
            speed_score_history_8w={
                "oldest_speed": 80.0, "newest_speed": 65.0,
                "formula_version": "v1", "count": 10,
            },
            quality_sessions_3w={"count": 1, "window_weeks": 3},
            training_verdict="build",
        ))
        assert result is not None
        metrics = {e["metric"] for e in result.evidence}
        assert any("speed" in m or "decay" in m for m in metrics)

    def test_evidence_contains_quality_sessions(self):
        """AC5: evidence includes quality session count."""
        rule = self._rule()
        result = rule(_inputs(
            speed_score_history_8w={
                "oldest_speed": 80.0, "newest_speed": 65.0,
                "formula_version": "v1", "count": 10,
            },
            quality_sessions_3w={"count": 1, "window_weeks": 3},
            training_verdict="build",
        ))
        assert result is not None
        metrics = {e["metric"] for e in result.evidence}
        assert any("quality" in m or "session" in m for m in metrics)

    def test_registered_in_engine(self):
        from backend.services.gap_analysis.engine import _REGISTRY
        names = [e.fn.__name__ for e in _REGISTRY._rules]
        assert "speed_neglected" in names

    def test_requires_speed_inputs(self):
        from backend.services.gap_analysis.engine import _REGISTRY
        entry = next(e for e in _REGISTRY._rules if e.fn.__name__ == "speed_neglected")
        assert "speed_score_history_8w" in entry.requires
        assert "quality_sessions_3w" in entry.requires


# ── AC4: verdict-deferral across rules ────────────────────────────────────────

class TestVerdictDeferral:
    """Explicit AC4 checks: back_off always downgrades to severity 1 with marker."""

    def test_intensity_too_hard_non_back_off_stays_severity_2(self):
        from backend.services.gap_analysis.rules.load_mix import intensity_too_hard
        for verdict in ("hold", "build"):
            result = intensity_too_hard(_inputs(
                intensity_4w={"low_pct": 55.0, "moderate_pct": 15.0, "high_pct": 30.0},
                training_verdict=verdict,
            ))
            assert result is not None
            assert result.severity == 2, f"Expected severity 2 for verdict={verdict}"

    def test_aerobic_durability_gap_non_back_off_stays_severity_2(self):
        from backend.services.gap_analysis.rules.load_mix import aerobic_durability_gap
        for verdict in ("hold", "build"):
            result = aerobic_durability_gap(_inputs(
                long_run_decoupling_4w={"avg_decoupling_pct": 8.5, "count": 3},
                training_verdict=verdict,
            ))
            assert result is not None
            assert result.severity == 2, f"Expected severity 2 for verdict={verdict}"

    def test_speed_neglected_non_back_off_stays_severity_2(self):
        from backend.services.gap_analysis.rules.load_mix import speed_neglected
        for verdict in ("hold", "build"):
            result = speed_neglected(_inputs(
                speed_score_history_8w={
                    "oldest_speed": 80.0, "newest_speed": 65.0,
                    "formula_version": "v1", "count": 10,
                },
                quality_sessions_3w={"count": 1, "window_weeks": 3},
                training_verdict=verdict,
            ))
            assert result is not None
            assert result.severity == 2, f"Expected severity 2 for verdict={verdict}"

    def test_all_rules_fire_when_verdict_missing(self):
        """When training_verdict key absent, rules should still fire at severity 2."""
        from backend.services.gap_analysis.rules.load_mix import (
            intensity_too_hard,
            aerobic_durability_gap,
            speed_neglected,
        )
        r1 = intensity_too_hard(_inputs(
            intensity_4w={"low_pct": 55.0, "moderate_pct": 15.0, "high_pct": 30.0},
        ))
        r2 = aerobic_durability_gap(_inputs(
            long_run_decoupling_4w={"avg_decoupling_pct": 8.5, "count": 3},
        ))
        r3 = speed_neglected(_inputs(
            speed_score_history_8w={
                "oldest_speed": 80.0, "newest_speed": 65.0,
                "formula_version": "v1", "count": 10,
            },
            quality_sessions_3w={"count": 1, "window_weeks": 3},
        ))
        assert r1 is not None and r1.severity == 2
        assert r2 is not None and r2.severity == 2
        assert r3 is not None and r3.severity == 2


# ── AC5: constants and module-level documentation ──────────────────────────────

class TestConstantsAndPurity:
    def test_constants_importable(self):
        """AC5: all threshold constants are importable from load_mix module."""
        from backend.services.gap_analysis.rules import load_mix
        assert hasattr(load_mix, "DECOUPLING_THRESHOLD_PCT")
        assert hasattr(load_mix, "LONG_RUN_MIN_SECONDS")
        assert hasattr(load_mix, "LONG_RUN_MIN_COUNT")
        assert hasattr(load_mix, "SPEED_DECAY_THRESHOLD")
        assert hasattr(load_mix, "QUALITY_SESSIONS_WINDOW_WEEKS")
        assert hasattr(load_mix, "QUALITY_SESSIONS_MIN_PER_WEEK")

    def test_rules_return_none_on_empty_inputs(self):
        """AC5: all rules return None on an empty inputs dict (no keys beyond week_start)."""
        from backend.services.gap_analysis.rules.load_mix import (
            intensity_too_hard,
            aerobic_durability_gap,
            speed_neglected,
        )
        empty = {"week_start": _DATE}
        assert intensity_too_hard(empty) is None
        assert aerobic_durability_gap(empty) is None
        assert speed_neglected(empty) is None

    def test_rules_are_pure_functions(self):
        """AC5: repeated calls produce the same result (no side effects)."""
        from backend.services.gap_analysis.rules.load_mix import intensity_too_hard

        inp = _inputs(
            intensity_4w={"low_pct": 55.0, "moderate_pct": 15.0, "high_pct": 30.0},
            training_verdict="build",
        )
        r1 = intensity_too_hard(inp)
        r2 = intensity_too_hard(inp)
        assert r1 is not None
        assert r2 is not None
        assert r1.code == r2.code
        assert r1.severity == r2.severity
