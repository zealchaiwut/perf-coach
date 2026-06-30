"""Tests for issue #1151: Make economy priors tunable via config.

Acceptance Criteria covered:
  AC1 — Lag length is defined in config and read at runtime; changing it
         produces different model output.
  AC2 — Ramp window (valid range 6–12 weeks) is defined in config and
         validated on load; out-of-range values raise a clear error.
  AC3 — Speed-dependence weights are defined in config (as a list/dict)
         and applied by the model at runtime.
  AC4 — Combination bonus is defined in config and read at runtime.
  AC5 — All four parameters have documented default values in config.
  AC6 — No parameter value is hard-coded in the model or pipeline source files.
  AC7 — py_compile passes cleanly on all modified files.
  AC8 — Unit test confirms that mutating each config value produces a
         measurable difference in model output.
"""

from __future__ import annotations

import py_compile
import pathlib
from datetime import date, timedelta


# ── AC1: lag length in config, changing it changes model output ───────────────

class TestLagLengthAC1:
    """AC1: lag_length_days is defined in config and controls kernel peak."""

    def test_economy_config_module_importable(self):
        from backend.services.economy_config import EconomyPriorConfig  # noqa: F401
        assert EconomyPriorConfig is not None

    def test_default_config_has_lag_length_days(self):
        from backend.services.economy_config import DEFAULT_ECONOMY_CONFIG
        assert hasattr(DEFAULT_ECONOMY_CONFIG, "lag_length_days")
        assert isinstance(DEFAULT_ECONOMY_CONFIG.lag_length_days, int)
        assert DEFAULT_ECONOMY_CONFIG.lag_length_days > 0

    def test_changing_lag_length_changes_ceiling_bonus_output(self):
        """AC1 / AC8: different lag_length_days → different compute_ceiling_bonus output."""
        from backend.services.ceiling_bonus import compute_ceiling_bonus
        from backend.services.economy_config import EconomyPriorConfig

        ref = date(2026, 1, 1)
        # Use a session 30 days back — well within both lag windows
        history = [(ref - timedelta(days=30), 100.0)]

        cfg_short = EconomyPriorConfig(lag_length_days=28)   # peak at 4 weeks
        cfg_long = EconomyPriorConfig(lag_length_days=42)    # peak at 6 weeks (default)

        bonus_short = compute_ceiling_bonus(history, ref, config=cfg_short)
        bonus_long = compute_ceiling_bonus(history, ref, config=cfg_long)

        assert bonus_short != bonus_long, (
            f"Different lag_length_days must produce different bonus: "
            f"lag=28 → {bonus_short}, lag=42 → {bonus_long}"
        )

    def test_lag_length_day30_at_peak_produces_higher_bonus_than_nonpeak(self):
        """AC1: session at exact lag_length_days gets peak kernel weight."""
        from backend.services.ceiling_bonus import compute_ceiling_bonus
        from backend.services.economy_config import EconomyPriorConfig

        ref = date(2026, 1, 1)
        lag = 35
        cfg = EconomyPriorConfig(lag_length_days=lag)

        at_peak = compute_ceiling_bonus([(ref - timedelta(days=lag), 100.0)], ref, config=cfg)
        at_early = compute_ceiling_bonus([(ref - timedelta(days=3), 100.0)], ref, config=cfg)

        assert at_peak > at_early, (
            f"Session at peak lag ({lag}d) should outweigh very recent session: "
            f"at_peak={at_peak}, at_early={at_early}"
        )


# ── AC2: ramp window validated 6–12 weeks ────────────────────────────────────

class TestRampWindowValidationAC2:
    """AC2: ramp_window_days must be 42–84 days (6–12 weeks); others raise ValueError."""

    def test_default_ramp_window_is_valid(self):
        from backend.services.economy_config import DEFAULT_ECONOMY_CONFIG
        assert hasattr(DEFAULT_ECONOMY_CONFIG, "ramp_window_days")
        assert 42 <= DEFAULT_ECONOMY_CONFIG.ramp_window_days <= 84

    def test_ramp_window_too_short_raises(self):
        """AC2 / UAT step 3: ramp_window_days=4 weeks (28 days) raises ValueError."""
        from backend.services.economy_config import EconomyPriorConfig
        import pytest
        with pytest.raises(ValueError, match="ramp_window_days"):
            EconomyPriorConfig(ramp_window_days=28)  # 4 weeks — below minimum

    def test_ramp_window_too_long_raises(self):
        """AC2: ramp_window_days=13 weeks (91 days) raises ValueError."""
        from backend.services.economy_config import EconomyPriorConfig
        import pytest
        with pytest.raises(ValueError, match="ramp_window_days"):
            EconomyPriorConfig(ramp_window_days=91)  # 13 weeks — above maximum

    def test_ramp_window_zero_raises(self):
        """AC2: ramp_window_days=0 raises ValueError."""
        from backend.services.economy_config import EconomyPriorConfig
        import pytest
        with pytest.raises(ValueError):
            EconomyPriorConfig(ramp_window_days=0)

    def test_ramp_window_boundary_min_42_valid(self):
        """AC2 / UAT step 4: ramp_window_days=42 (6 weeks) is valid."""
        from backend.services.economy_config import EconomyPriorConfig
        cfg = EconomyPriorConfig(ramp_window_days=42)  # 6 weeks — minimum valid
        assert cfg.ramp_window_days == 42

    def test_ramp_window_boundary_max_84_valid(self):
        """AC2 / UAT step 4: ramp_window_days=84 (12 weeks) is valid."""
        from backend.services.economy_config import EconomyPriorConfig
        cfg = EconomyPriorConfig(ramp_window_days=84)  # 12 weeks — maximum valid
        assert cfg.ramp_window_days == 84

    def test_ramp_window_mid_range_valid(self):
        """AC2: ramp_window_days=56 (8 weeks) is valid."""
        from backend.services.economy_config import EconomyPriorConfig
        cfg = EconomyPriorConfig(ramp_window_days=56)
        assert cfg.ramp_window_days == 56

    def test_ramp_window_41_raises(self):
        """AC2: one day below 6 weeks (41 days) raises ValueError."""
        from backend.services.economy_config import EconomyPriorConfig
        import pytest
        with pytest.raises(ValueError):
            EconomyPriorConfig(ramp_window_days=41)

    def test_ramp_window_85_raises(self):
        """AC2: one day above 12 weeks (85 days) raises ValueError."""
        from backend.services.economy_config import EconomyPriorConfig
        import pytest
        with pytest.raises(ValueError):
            EconomyPriorConfig(ramp_window_days=85)

    def test_changing_ramp_window_changes_output(self):
        """AC2 / AC8: sessions outside shorter window contribute nothing."""
        from backend.services.ceiling_bonus import compute_ceiling_bonus
        from backend.services.economy_config import EconomyPriorConfig

        ref = date(2026, 1, 1)
        # Session 70 days ago — inside 84-day window, outside 42-day window
        history = [(ref - timedelta(days=70), 100.0)]

        cfg_narrow = EconomyPriorConfig(ramp_window_days=42)
        cfg_wide = EconomyPriorConfig(ramp_window_days=84)

        bonus_narrow = compute_ceiling_bonus(history, ref, config=cfg_narrow)
        bonus_wide = compute_ceiling_bonus(history, ref, config=cfg_wide)

        assert bonus_narrow == 0.0, (
            f"70-day-old session must not contribute within 42-day window; "
            f"got {bonus_narrow}"
        )
        assert bonus_wide > 0.0, (
            f"70-day-old session must contribute within 84-day window; "
            f"got {bonus_wide}"
        )


# ── AC3: speed-dependence weights in config ───────────────────────────────────

class TestSpeedWeightsAC3:
    """AC3: speed_weights are defined in config (dict) and applied by the model."""

    def test_default_config_has_speed_weights_dict(self):
        from backend.services.economy_config import DEFAULT_ECONOMY_CONFIG
        assert hasattr(DEFAULT_ECONOMY_CONFIG, "speed_weights")
        sw = DEFAULT_ECONOMY_CONFIG.speed_weights
        assert isinstance(sw, dict)
        assert "strength_speed_scale" in sw
        assert "strength_fitness_scale" in sw
        assert "plyo_speed_threshold" in sw
        assert "plyo_below_taper_fraction" in sw

    def test_changing_strength_speed_scale_changes_output(self):
        """AC3 / AC8: different strength_speed_scale → different stimulus."""
        from backend.services.economy_stimulus import compute_economy_stimulus
        from backend.services.economy_config import EconomyPriorConfig

        cfg_low = EconomyPriorConfig(speed_weights={
            "strength_speed_scale": 10.0,
            "strength_fitness_scale": 100.0,
            "plyo_speed_threshold": 12.0,
            "plyo_below_taper_fraction": 0.1,
        })
        cfg_high = EconomyPriorConfig(speed_weights={
            "strength_speed_scale": 40.0,
            "strength_fitness_scale": 100.0,
            "plyo_speed_threshold": 12.0,
            "plyo_below_taper_fraction": 0.1,
        })

        result_low = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0, config=cfg_low)
        result_high = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0, config=cfg_high)

        assert result_low != result_high, (
            f"Different strength_speed_scale must produce different stimulus: "
            f"scale=10 → {result_low}, scale=40 → {result_high}"
        )

    def test_lower_strength_speed_scale_gives_higher_stimulus_at_fixed_speed(self):
        """AC3: halving strength_speed_scale doubles the speed factor, increasing stimulus."""
        from backend.services.economy_stimulus import compute_economy_stimulus
        from backend.services.economy_config import EconomyPriorConfig

        base_weights = {
            "strength_fitness_scale": 100.0,
            "plyo_speed_threshold": 12.0,
            "plyo_below_taper_fraction": 0.1,
        }
        cfg_low_scale = EconomyPriorConfig(speed_weights={**base_weights, "strength_speed_scale": 10.0})
        cfg_high_scale = EconomyPriorConfig(speed_weights={**base_weights, "strength_speed_scale": 40.0})

        result_low = compute_economy_stimulus(500.0, 0.0, 10.0, 0.0, config=cfg_low_scale)
        result_high = compute_economy_stimulus(500.0, 0.0, 10.0, 0.0, config=cfg_high_scale)

        # Lower scale → larger speed factor → higher stimulus
        assert result_low > result_high, (
            f"Lower strength_speed_scale should increase stimulus: "
            f"scale=10 ({result_low}) must exceed scale=40 ({result_high})"
        )

    def test_changing_plyo_speed_threshold_changes_output(self):
        """AC3 / AC8: different plyo_speed_threshold → different plyo stimulus."""
        from backend.services.economy_stimulus import compute_economy_stimulus
        from backend.services.economy_config import EconomyPriorConfig

        base_weights = {
            "strength_speed_scale": 20.0,
            "strength_fitness_scale": 100.0,
            "plyo_below_taper_fraction": 0.1,
        }
        # Threshold at 8 km/h — running at 10 km/h is above threshold (taper)
        cfg_low_thresh = EconomyPriorConfig(speed_weights={**base_weights, "plyo_speed_threshold": 8.0})
        # Threshold at 15 km/h — running at 10 km/h is below threshold (no heavy taper)
        cfg_high_thresh = EconomyPriorConfig(speed_weights={**base_weights, "plyo_speed_threshold": 15.0})

        result_low = compute_economy_stimulus(0.0, 200.0, 10.0, 50.0, config=cfg_low_thresh)
        result_high = compute_economy_stimulus(0.0, 200.0, 10.0, 50.0, config=cfg_high_thresh)

        assert result_low != result_high, (
            f"Different plyo_speed_threshold must produce different stimulus: "
            f"thresh=8 → {result_low}, thresh=15 → {result_high}"
        )

    def test_speed_weights_applied_via_config_param(self):
        """AC3: compute_economy_stimulus accepts a config parameter with speed_weights."""
        from backend.services.economy_stimulus import compute_economy_stimulus
        from backend.services.economy_config import EconomyPriorConfig

        cfg = EconomyPriorConfig()
        result = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0, config=cfg)
        assert result > 0.0


# ── AC4: combination bonus in config ──────────────────────────────────────────

class TestCombinationBonusAC4:
    """AC4: combination_bonus is defined in config and applied at runtime."""

    def test_default_config_has_combination_bonus(self):
        from backend.services.economy_config import DEFAULT_ECONOMY_CONFIG
        assert hasattr(DEFAULT_ECONOMY_CONFIG, "combination_bonus")
        assert isinstance(DEFAULT_ECONOMY_CONFIG.combination_bonus, float)
        assert DEFAULT_ECONOMY_CONFIG.combination_bonus > 0.0

    def test_changing_combination_bonus_changes_output(self):
        """AC4 / AC8: different combination_bonus → different combined stimulus."""
        from backend.services.economy_stimulus import compute_economy_stimulus
        from backend.services.economy_config import EconomyPriorConfig

        cfg_no_bonus = EconomyPriorConfig(combination_bonus=1.0)   # no bonus
        cfg_bonus = EconomyPriorConfig(combination_bonus=1.2)      # 20% bonus

        result_no = compute_economy_stimulus(500.0, 200.0, 10.0, 50.0, config=cfg_no_bonus)
        result_yes = compute_economy_stimulus(500.0, 200.0, 10.0, 50.0, config=cfg_bonus)

        assert result_yes > result_no, (
            f"Higher combination_bonus must increase combined stimulus: "
            f"bonus=1.0 → {result_no}, bonus=1.2 → {result_yes}"
        )

    def test_combination_bonus_1_equals_sum_of_individuals(self):
        """AC4: bonus=1.0 means combined equals sum of each computed separately."""
        from backend.services.economy_stimulus import compute_economy_stimulus
        from backend.services.economy_config import EconomyPriorConfig

        cfg = EconomyPriorConfig(combination_bonus=1.0)
        strength_only = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0, config=cfg)
        plyo_only = compute_economy_stimulus(0.0, 200.0, 10.0, 50.0, config=cfg)
        combined = compute_economy_stimulus(500.0, 200.0, 10.0, 50.0, config=cfg)

        assert abs(combined - (strength_only + plyo_only)) < 1e-9, (
            f"With bonus=1.0, combined ({combined}) must equal "
            f"strength ({strength_only}) + plyo ({plyo_only})"
        )

    def test_combination_bonus_only_applies_when_both_present(self):
        """AC4: changing bonus only affects output when both loads are non-zero."""
        from backend.services.economy_stimulus import compute_economy_stimulus
        from backend.services.economy_config import EconomyPriorConfig

        cfg_low = EconomyPriorConfig(combination_bonus=1.0)
        cfg_high = EconomyPriorConfig(combination_bonus=1.5)

        # Strength-only — bonus should NOT change output
        str_low = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0, config=cfg_low)
        str_high = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0, config=cfg_high)
        assert str_low == str_high, "Bonus must not affect strength-only output"

        # Combined — bonus SHOULD change output
        comb_low = compute_economy_stimulus(500.0, 200.0, 10.0, 50.0, config=cfg_low)
        comb_high = compute_economy_stimulus(500.0, 200.0, 10.0, 50.0, config=cfg_high)
        assert comb_high > comb_low, "Bonus must increase combined output"


# ── AC5: all four parameters have documented defaults ─────────────────────────

class TestDocumentedDefaultsAC5:
    """AC5: each parameter has a documented default in config."""

    def test_all_four_parameters_present_in_default_config(self):
        from backend.services.economy_config import DEFAULT_ECONOMY_CONFIG
        assert hasattr(DEFAULT_ECONOMY_CONFIG, "lag_length_days")
        assert hasattr(DEFAULT_ECONOMY_CONFIG, "ramp_window_days")
        assert hasattr(DEFAULT_ECONOMY_CONFIG, "speed_weights")
        assert hasattr(DEFAULT_ECONOMY_CONFIG, "combination_bonus")

    def test_default_lag_length_is_42_days(self):
        """Default lag_length_days = 42 (6 weeks)."""
        from backend.services.economy_config import DEFAULT_ECONOMY_CONFIG
        assert DEFAULT_ECONOMY_CONFIG.lag_length_days == 42

    def test_default_ramp_window_is_84_days(self):
        """Default ramp_window_days = 84 (12 weeks)."""
        from backend.services.economy_config import DEFAULT_ECONOMY_CONFIG
        assert DEFAULT_ECONOMY_CONFIG.ramp_window_days == 84

    def test_default_combination_bonus_is_1_1(self):
        """Default combination_bonus = 1.1."""
        from backend.services.economy_config import DEFAULT_ECONOMY_CONFIG
        assert abs(DEFAULT_ECONOMY_CONFIG.combination_bonus - 1.1) < 1e-9

    def test_default_speed_weights_have_expected_values(self):
        """Default speed_weights match prior hard-coded constants."""
        from backend.services.economy_config import DEFAULT_ECONOMY_CONFIG
        sw = DEFAULT_ECONOMY_CONFIG.speed_weights
        assert abs(sw["strength_speed_scale"] - 20.0) < 1e-9
        assert abs(sw["strength_fitness_scale"] - 100.0) < 1e-9
        assert abs(sw["plyo_speed_threshold"] - 12.0) < 1e-9
        assert abs(sw["plyo_below_taper_fraction"] - 0.1) < 1e-9


# ── AC6: no hard-coded values in model source files ───────────────────────────

class TestNoHardCodedValuesAC6:
    """AC6: model source files must not contain literal copies of the 4 config values."""

    def _read_source(self, module_name: str) -> str:
        import importlib
        mod = importlib.import_module(module_name)
        path = pathlib.Path(mod.__file__)
        if path.suffix == ".pyc":
            path = path.with_suffix(".py")
        return path.read_text()

    def test_economy_stimulus_has_no_hardcoded_combination_bonus(self):
        """AC6: economy_stimulus.py must not contain the literal '1.1' as a standalone constant."""
        src = self._read_source("backend.services.economy_stimulus")
        # The value should not appear as a bare float literal assignment
        assert "= 1.1" not in src, (
            "combination_bonus value 1.1 must not be hard-coded in economy_stimulus.py"
        )

    def test_ceiling_bonus_reads_from_config_not_hardcoded_lag(self):
        """AC6: ceiling_bonus.py must not define LAG_PEAK_DAYS as a bare integer literal."""
        src = self._read_source("backend.services.ceiling_bonus")
        # LAG_PEAK_DAYS should not be assigned directly as int 42
        assert "LAG_PEAK_DAYS: int = 42" not in src, (
            "LAG_PEAK_DAYS must not be hard-coded as 42 in ceiling_bonus.py; "
            "it must come from economy_config"
        )

    def test_ceiling_bonus_reads_from_config_not_hardcoded_window(self):
        """AC6: ceiling_bonus.py must not define LAG_WINDOW_DAYS as a bare integer literal."""
        src = self._read_source("backend.services.ceiling_bonus")
        assert "LAG_WINDOW_DAYS: int = 84" not in src, (
            "LAG_WINDOW_DAYS must not be hard-coded as 84 in ceiling_bonus.py; "
            "it must come from economy_config"
        )


# ── AC7: py_compile passes on all modified files ──────────────────────────────

class TestPyCompileAC7:
    """AC7: py_compile passes on all modified source files."""

    def _compile(self, rel_path: str) -> None:
        p = pathlib.Path(__file__).parent.parent / rel_path
        assert p.exists(), f"File not found: {p}"
        py_compile.compile(str(p), doraise=True)

    def test_economy_config_compiles(self):
        self._compile("backend/services/economy_config.py")

    def test_economy_stimulus_compiles(self):
        self._compile("backend/services/economy_stimulus.py")

    def test_ceiling_bonus_compiles(self):
        self._compile("backend/services/ceiling_bonus.py")

    def test_backfill_economy_compiles(self):
        self._compile("backend/services/backfill_economy.py")


# ── AC8: mutating each config value produces measurable difference ────────────

class TestMutatingConfigAC8:
    """AC8: unit test confirms each config parameter, when changed, alters model output."""

    def test_mutating_lag_length_changes_output(self):
        """AC8: lag_length_days change → ceiling_bonus output change."""
        from backend.services.ceiling_bonus import compute_ceiling_bonus
        from backend.services.economy_config import EconomyPriorConfig

        ref = date(2026, 3, 1)
        history = [(ref - timedelta(days=35), 500.0)]

        out_a = compute_ceiling_bonus(history, ref, config=EconomyPriorConfig(lag_length_days=28))
        out_b = compute_ceiling_bonus(history, ref, config=EconomyPriorConfig(lag_length_days=42))
        assert out_a != out_b, f"lag_length mutation must change output: {out_a} vs {out_b}"

    def test_mutating_ramp_window_changes_output(self):
        """AC8: ramp_window_days change → ceiling_bonus output change."""
        from backend.services.ceiling_bonus import compute_ceiling_bonus
        from backend.services.economy_config import EconomyPriorConfig

        ref = date(2026, 3, 1)
        history = [(ref - timedelta(days=60), 500.0)]  # 60 days back

        out_narrow = compute_ceiling_bonus(history, ref, config=EconomyPriorConfig(ramp_window_days=42))
        out_wide = compute_ceiling_bonus(history, ref, config=EconomyPriorConfig(ramp_window_days=84))
        assert out_narrow != out_wide, (
            f"ramp_window mutation must change output: {out_narrow} vs {out_wide}"
        )

    def test_mutating_speed_weights_changes_output(self):
        """AC8: speed_weights change → compute_economy_stimulus output change."""
        from backend.services.economy_stimulus import compute_economy_stimulus
        from backend.services.economy_config import EconomyPriorConfig

        sw_base = {"strength_fitness_scale": 100.0, "plyo_speed_threshold": 12.0,
                   "plyo_below_taper_fraction": 0.1}
        cfg_a = EconomyPriorConfig(speed_weights={**sw_base, "strength_speed_scale": 10.0})
        cfg_b = EconomyPriorConfig(speed_weights={**sw_base, "strength_speed_scale": 40.0})

        out_a = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0, config=cfg_a)
        out_b = compute_economy_stimulus(500.0, 0.0, 10.0, 50.0, config=cfg_b)
        assert out_a != out_b, f"speed_weights mutation must change output: {out_a} vs {out_b}"

    def test_mutating_combination_bonus_changes_output(self):
        """AC8: combination_bonus change → compute_economy_stimulus output change."""
        from backend.services.economy_stimulus import compute_economy_stimulus
        from backend.services.economy_config import EconomyPriorConfig

        cfg_a = EconomyPriorConfig(combination_bonus=1.0)
        cfg_b = EconomyPriorConfig(combination_bonus=1.3)

        out_a = compute_economy_stimulus(500.0, 200.0, 10.0, 50.0, config=cfg_a)
        out_b = compute_economy_stimulus(500.0, 200.0, 10.0, 50.0, config=cfg_b)
        assert out_a != out_b, (
            f"combination_bonus mutation must change output: {out_a} vs {out_b}"
        )

    def test_restoring_defaults_restores_baseline(self):
        """AC8 / UAT step 7: restoring config to defaults restores baseline output."""
        from backend.services.economy_stimulus import compute_economy_stimulus
        from backend.services.economy_config import EconomyPriorConfig, DEFAULT_ECONOMY_CONFIG

        # Baseline with default config
        baseline = compute_economy_stimulus(500.0, 200.0, 10.0, 50.0, config=DEFAULT_ECONOMY_CONFIG)

        # Modified config
        cfg_modified = EconomyPriorConfig(combination_bonus=1.5)
        modified = compute_economy_stimulus(500.0, 200.0, 10.0, 50.0, config=cfg_modified)
        assert modified != baseline

        # Restored to defaults
        cfg_restored = EconomyPriorConfig()
        restored = compute_economy_stimulus(500.0, 200.0, 10.0, 50.0, config=cfg_restored)
        assert abs(restored - baseline) < 1e-9, (
            f"Restoring defaults must restore baseline: {restored} vs {baseline}"
        )

    def test_default_config_output_matches_prior_hardcoded_baseline(self):
        """AC8 / UAT step 1: default config produces same output as prior hard-coded values.

        Baseline computed from prior constants:
          strength_speed_scale=20, strength_fitness_scale=100,
          plyo_speed_threshold=12, plyo_below_taper_fraction=0.1,
          combination_bonus=1.1
        Inputs: strength_load=500, plyo_contacts=200, speed_kmh=10, fitness_score=50
        Expected: (500 * 1.5 * 1.5 + 200 * (1 - 0.1 * 10/12)) * 1.1
                = (1125 + 200 * 0.9167) * 1.1 ≈ (1125 + 183.33) * 1.1 ≈ 1439.17
        """
        from backend.services.economy_stimulus import compute_economy_stimulus
        from backend.services.economy_config import DEFAULT_ECONOMY_CONFIG

        result = compute_economy_stimulus(500.0, 200.0, 10.0, 50.0, config=DEFAULT_ECONOMY_CONFIG)
        expected = (500.0 * 1.5 * 1.5 + 200.0 * (1.0 - 0.1 * (10.0 / 12.0))) * 1.1
        assert abs(result - expected) < 1e-6, (
            f"Default config must match prior baseline: got {result}, expected {expected}"
        )
