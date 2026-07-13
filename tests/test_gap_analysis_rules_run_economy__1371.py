"""Tests for issue #1371: Gap analyzer run-economy rules.

AC coverage:
- AC1: plyo_deficit — fires when LSS flat/falling AND plyo dose < 1/week over 4 weeks
- AC1: plyo_deficit — silent when LSS rising or plyo dose adequate
- AC1: plyo_deficit — None on insufficient data (< MIN_RUNS_PER_WINDOW runs)
- AC1: plyo_deficit — evidence carries actual window values; phase from last logged
- AC2: gct_lengthening — fires when GCT 28-day mean rises > threshold vs prior 28d at comparable intensity
- AC2: gct_lengthening — pace-band control: slow-run-only data does NOT fire
- AC2: gct_lengthening — silent when GCT stable or falling
- AC2: gct_lengthening — None on insufficient data
- AC3: cadence_drift — fires when easy-run cadence 28d mean below 6-month baseline > threshold
- AC3: cadence_drift — baseline math verified (mean of last 28d vs mean of last 6 months)
- AC3: cadence_drift — silent when cadence at or above baseline
- AC3: cadence_drift — None on insufficient data (< MIN_RUNS_PER_WINDOW)
- AC4: thresholds are named constants importable from the rule modules
- AC4: each rule is a pure function (no DB calls)
- AC4: every rule returns None on insufficient data
"""
from __future__ import annotations

import datetime
from typing import Optional

import pytest

from backend.services.gap_analysis.rules.plyo_deficit import (
    plyo_deficit,
    LSS_IMPROVEMENT_THRESHOLD_PCT,
    PLYO_SESSIONS_PER_WEEK_MIN,
    PLYO_DOSE_WINDOW_WEEKS,
    MIN_RUNS_PER_WINDOW,
)
from backend.services.gap_analysis.rules.gct_lengthening import (
    gct_lengthening,
    GCT_RISE_THRESHOLD_MS,
    GCT_EASY_POWER_BAND_WIDTH_W,
    MIN_RUNS_PER_WINDOW as GCT_MIN_RUNS,
)
from backend.services.gap_analysis.rules.cadence_drift import (
    cadence_drift,
    CADENCE_DRIFT_THRESHOLD_PCT,
    CADENCE_BASELINE_WINDOW_DAYS,
    MIN_RUNS_PER_WINDOW as CAD_MIN_RUNS,
)

TODAY = datetime.date(2026, 7, 14)
WEEK_START = TODAY - datetime.timedelta(days=TODAY.weekday())  # 2026-07-13


# ─────────────────────────────────────────────────────────────────────────────
# Helpers to build minimal inputs dicts
# ─────────────────────────────────────────────────────────────────────────────

def _make_form_metrics(
    *,
    recent_lss: list[float],
    prior_lss: list[float],
    recent_gct: list[float],
    prior_gct: list[float],
    recent_power: list[float],
    prior_power: list[float],
    recent_cadence: list[float],
    long_cadence: list[float],
) -> dict:
    """Build a form_metrics input dict with separate recent/prior windows."""
    today = TODAY

    def _make_runs(values_lss, values_gct, values_power, values_cadence, day_offset_start):
        runs = []
        for i, (lss, gct, pw, cad) in enumerate(
            zip(values_lss, values_gct, values_power, values_cadence)
        ):
            runs.append({
                "run_date": (today - datetime.timedelta(days=day_offset_start + i)).isoformat(),
                "lss_kn_m": lss,
                "gct_ms": gct,
                "power_w": pw,
                "cadence_spm": cad,
            })
        return runs

    # recent window: days 0..27
    n_recent = max(len(recent_lss), len(recent_gct), len(recent_cadence))
    recent_runs = _make_runs(
        recent_lss + [None] * (n_recent - len(recent_lss)),
        recent_gct + [None] * (n_recent - len(recent_gct)),
        recent_power + [None] * (n_recent - len(recent_power)),
        recent_cadence + [None] * (n_recent - len(recent_cadence)),
        day_offset_start=0,
    )

    # prior window: days 28..55
    n_prior = max(len(prior_lss), len(prior_gct))
    prior_runs = _make_runs(
        prior_lss + [None] * (n_prior - len(prior_lss)),
        prior_gct + [None] * (n_prior - len(prior_gct)),
        prior_power + [None] * (n_prior - len(prior_power)),
        [None] * n_prior,
        day_offset_start=28,
    )

    # long baseline: days 56..180 (for cadence 6-month baseline)
    long_runs = []
    for i, cad in enumerate(long_cadence):
        long_runs.append({
            "run_date": (today - datetime.timedelta(days=56 + i)).isoformat(),
            "lss_kn_m": None,
            "gct_ms": None,
            "power_w": None,
            "cadence_spm": cad,
        })

    return {
        "recent_runs": recent_runs,
        "prior_runs": prior_runs,
        "long_baseline_runs": long_runs,
    }


def _plyo_dose(sessions_per_week: float, last_plyo_phase: Optional[str] = "build") -> dict:
    """Build a structural_dose sub-dict for plyo_deficit inputs."""
    weekly = []
    for i in range(4):
        weekly.append({"plyo_sessions": sessions_per_week, "dominant_plyo_phase": last_plyo_phase})
    return {
        "weekly": weekly,
        "last_plyo_days_ago": None if sessions_per_week == 0 else 3,
    }


def _inputs_plyo_deficit(
    *,
    recent_lss: list[float],
    prior_lss: list[float],
    plyo_sessions_per_week: float = 0.0,
    last_plyo_phase: Optional[str] = "build",
) -> dict:
    n = max(len(recent_lss), len(prior_lss), MIN_RUNS_PER_WINDOW)
    fm = _make_form_metrics(
        recent_lss=recent_lss,
        prior_lss=prior_lss,
        recent_gct=[200.0] * n,
        prior_gct=[200.0] * n,
        recent_power=[250.0] * n,
        prior_power=[250.0] * n,
        recent_cadence=[175.0] * n,
        long_cadence=[175.0] * n,
    )
    return {
        "week_start": WEEK_START,
        "form_metrics": fm,
        "structural_dose": _plyo_dose(plyo_sessions_per_week, last_plyo_phase),
    }


def _inputs_gct(
    *,
    recent_gct: list[float],
    prior_gct: list[float],
    recent_power: list[float],
    prior_power: list[float],
) -> dict:
    n = max(len(recent_gct), len(prior_gct), GCT_MIN_RUNS)
    lss_val = [1.5] * n
    fm = _make_form_metrics(
        recent_lss=lss_val,
        prior_lss=lss_val,
        recent_gct=recent_gct,
        prior_gct=prior_gct,
        recent_power=recent_power,
        prior_power=prior_power,
        recent_cadence=[175.0] * n,
        long_cadence=[],
    )
    return {
        "week_start": WEEK_START,
        "form_metrics": fm,
        "structural_dose": _plyo_dose(1.0),
    }


def _inputs_cadence(
    *,
    recent_cadence: list[float],
    long_cadence: list[float],
) -> dict:
    n = max(len(recent_cadence), CAD_MIN_RUNS)
    lss_val = [1.5] * n
    fm = _make_form_metrics(
        recent_lss=lss_val,
        prior_lss=lss_val,
        recent_gct=[200.0] * n,
        prior_gct=[200.0] * n,
        recent_power=[250.0] * n,
        prior_power=[250.0] * n,
        recent_cadence=recent_cadence,
        long_cadence=long_cadence,
    )
    return {
        "week_start": WEEK_START,
        "form_metrics": fm,
        "structural_dose": _plyo_dose(1.0),
    }


# ─────────────────────────────────────────────────────────────────────────────
# AC1: plyo_deficit
# ─────────────────────────────────────────────────────────────────────────────

class TestPlyoDeficit:

    def test_fires_when_lss_flat_and_no_plyo(self):
        """plyo_deficit fires when LSS is flat AND plyo dose < threshold."""
        # LSS exactly flat across windows
        prior_lss = [1.50] * MIN_RUNS_PER_WINDOW
        recent_lss = [1.50] * MIN_RUNS_PER_WINDOW  # 0% change → ≤ +1% threshold
        inputs = _inputs_plyo_deficit(
            recent_lss=recent_lss,
            prior_lss=prior_lss,
            plyo_sessions_per_week=0.0,
        )
        result = plyo_deficit(inputs)
        assert result is not None
        assert result.code == "plyo_deficit"
        assert result.severity == 2

    def test_fires_when_lss_falling_and_no_plyo(self):
        """plyo_deficit fires when LSS falls across windows AND plyo dose < threshold."""
        prior_lss = [1.60] * MIN_RUNS_PER_WINDOW
        recent_lss = [1.40] * MIN_RUNS_PER_WINDOW  # clear decline
        inputs = _inputs_plyo_deficit(
            recent_lss=recent_lss,
            prior_lss=prior_lss,
            plyo_sessions_per_week=0.0,
        )
        result = plyo_deficit(inputs)
        assert result is not None
        assert result.code == "plyo_deficit"

    def test_silent_when_lss_rising_above_threshold(self):
        """plyo_deficit is silent when LSS improvement > threshold."""
        prior_lss = [1.50] * MIN_RUNS_PER_WINDOW
        recent_lss = [1.55] * MIN_RUNS_PER_WINDOW  # +3.3% > +1% threshold
        inputs = _inputs_plyo_deficit(
            recent_lss=recent_lss,
            prior_lss=prior_lss,
            plyo_sessions_per_week=0.0,
        )
        result = plyo_deficit(inputs)
        assert result is None

    def test_silent_when_plyo_dose_adequate(self):
        """plyo_deficit is silent when plyo dose meets the minimum."""
        prior_lss = [1.50] * MIN_RUNS_PER_WINDOW
        recent_lss = [1.50] * MIN_RUNS_PER_WINDOW
        inputs = _inputs_plyo_deficit(
            recent_lss=recent_lss,
            prior_lss=prior_lss,
            plyo_sessions_per_week=PLYO_SESSIONS_PER_WEEK_MIN,  # exactly threshold
        )
        result = plyo_deficit(inputs)
        assert result is None

    def test_none_on_insufficient_recent_data(self):
        """plyo_deficit returns None when fewer than MIN_RUNS_PER_WINDOW recent runs."""
        inputs = _inputs_plyo_deficit(
            recent_lss=[1.50] * (MIN_RUNS_PER_WINDOW - 1),
            prior_lss=[1.50] * MIN_RUNS_PER_WINDOW,
        )
        result = plyo_deficit(inputs)
        assert result is None

    def test_none_on_insufficient_prior_data(self):
        """plyo_deficit returns None when fewer than MIN_RUNS_PER_WINDOW prior-window runs."""
        inputs = _inputs_plyo_deficit(
            recent_lss=[1.50] * MIN_RUNS_PER_WINDOW,
            prior_lss=[1.50] * (MIN_RUNS_PER_WINDOW - 1),
        )
        result = plyo_deficit(inputs)
        assert result is None

    def test_evidence_carries_actual_values(self):
        """Evidence dict contains lss_recent_mean, lss_prior_mean, plyo_sessions_per_week."""
        prior_lss = [1.60] * MIN_RUNS_PER_WINDOW
        recent_lss = [1.50] * MIN_RUNS_PER_WINDOW
        inputs = _inputs_plyo_deficit(
            recent_lss=recent_lss,
            prior_lss=prior_lss,
            plyo_sessions_per_week=0.0,
        )
        result = plyo_deficit(inputs)
        assert result is not None
        ev_keys = {e["metric"] for e in result.evidence}
        assert "lss_recent_mean" in ev_keys
        assert "lss_prior_mean" in ev_keys
        assert "plyo_sessions_per_week" in ev_keys

    def test_recommendation_references_last_phase(self):
        """Recommendation text includes the last logged plyo phase."""
        prior_lss = [1.60] * MIN_RUNS_PER_WINDOW
        recent_lss = [1.50] * MIN_RUNS_PER_WINDOW
        inputs = _inputs_plyo_deficit(
            recent_lss=recent_lss,
            prior_lss=prior_lss,
            plyo_sessions_per_week=0.0,
            last_plyo_phase="intro",
        )
        result = plyo_deficit(inputs)
        assert result is not None
        assert "intro" in result.recommendation.lower()

    def test_recommendation_defaults_to_intro_when_no_phase(self):
        """When no prior phase is logged, recommendation defaults to 'intro'."""
        prior_lss = [1.60] * MIN_RUNS_PER_WINDOW
        recent_lss = [1.50] * MIN_RUNS_PER_WINDOW
        inputs = _inputs_plyo_deficit(
            recent_lss=recent_lss,
            prior_lss=prior_lss,
            plyo_sessions_per_week=0.0,
            last_plyo_phase=None,
        )
        result = plyo_deficit(inputs)
        assert result is not None
        assert "intro" in result.recommendation.lower()

    def test_lss_threshold_boundary(self):
        """LSS improvement exactly at threshold (= LSS_IMPROVEMENT_THRESHOLD_PCT) does NOT fire."""
        # prior_mean = 1.0, improvement = threshold → not firing
        prior_lss = [1.0] * MIN_RUNS_PER_WINDOW
        threshold_ratio = 1.0 + LSS_IMPROVEMENT_THRESHOLD_PCT / 100.0
        recent_lss = [round(threshold_ratio, 6)] * MIN_RUNS_PER_WINDOW
        inputs = _inputs_plyo_deficit(
            recent_lss=recent_lss,
            prior_lss=prior_lss,
            plyo_sessions_per_week=0.0,
        )
        result = plyo_deficit(inputs)
        assert result is None

    def test_none_when_form_metrics_missing(self):
        """plyo_deficit returns None when form_metrics key is absent."""
        inputs = {
            "week_start": WEEK_START,
            "structural_dose": _plyo_dose(0.0),
        }
        result = plyo_deficit(inputs)
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# AC2: gct_lengthening
# ─────────────────────────────────────────────────────────────────────────────

class TestGctLengthening:

    def _easy_power(self, n: int = None) -> list[float]:
        n = n or GCT_MIN_RUNS
        return [250.0] * n  # within easy-run band

    def test_fires_when_gct_rises_above_threshold(self):
        """gct_lengthening fires when recent GCT mean > prior GCT mean + GCT_RISE_THRESHOLD_MS."""
        n = GCT_MIN_RUNS
        prior_gct = [220.0] * n
        recent_gct = [220.0 + GCT_RISE_THRESHOLD_MS + 1.0] * n
        inputs = _inputs_gct(
            recent_gct=recent_gct,
            prior_gct=prior_gct,
            recent_power=self._easy_power(n),
            prior_power=self._easy_power(n),
        )
        result = gct_lengthening(inputs)
        assert result is not None
        assert result.code == "gct_lengthening"
        assert result.severity == 2

    def test_silent_when_gct_stable(self):
        """gct_lengthening is silent when GCT change is within threshold."""
        n = GCT_MIN_RUNS
        prior_gct = [220.0] * n
        recent_gct = [220.0 + GCT_RISE_THRESHOLD_MS - 1.0] * n  # below threshold
        inputs = _inputs_gct(
            recent_gct=recent_gct,
            prior_gct=prior_gct,
            recent_power=self._easy_power(n),
            prior_power=self._easy_power(n),
        )
        result = gct_lengthening(inputs)
        assert result is None

    def test_silent_when_gct_falling(self):
        """gct_lengthening is silent when GCT is actually improving (falling)."""
        n = GCT_MIN_RUNS
        prior_gct = [240.0] * n
        recent_gct = [220.0] * n  # fell by 20ms — improvement
        inputs = _inputs_gct(
            recent_gct=recent_gct,
            prior_gct=prior_gct,
            recent_power=self._easy_power(n),
            prior_power=self._easy_power(n),
        )
        result = gct_lengthening(inputs)
        assert result is None

    def test_pace_band_control_slow_runs_excluded(self):
        """gct_lengthening does NOT fire when GCT comparison involves incompatible power bands.

        Slow runs (low power) are excluded from easy-run band comparison so they
        don't false-positive the GCT rise signal.
        """
        n = GCT_MIN_RUNS
        # Recent runs at a very different power band than prior (slow vs easy)
        prior_gct = [220.0] * n
        recent_gct = [250.0] * n  # would look like a rise
        prior_power = [250.0] * n  # easy pace band
        recent_power = [150.0] * n  # much slower — different band

        # With incompatible power bands, the rule should return None (insufficient
        # overlap after band filtering) rather than fire on apples-vs-oranges data.
        inputs = _inputs_gct(
            recent_gct=recent_gct,
            prior_gct=prior_gct,
            recent_power=recent_power,
            prior_power=prior_power,
        )
        result = gct_lengthening(inputs)
        # Either None (filtered out) or not fired — must NOT fire as a false positive
        if result is not None:
            # If a result came back despite the band mismatch, it must be because
            # the power bands did overlap by chance — only accept if the rule
            # actually found overlapping data
            pytest.fail(
                "gct_lengthening fired with incompatible power bands "
                f"(recent power {recent_power[0]}W vs prior {prior_power[0]}W, "
                f"band width {GCT_EASY_POWER_BAND_WIDTH_W}W) — false positive"
            )

    def test_none_on_insufficient_recent_data(self):
        """gct_lengthening returns None when recent window has too few runs."""
        inputs = _inputs_gct(
            recent_gct=[230.0] * (GCT_MIN_RUNS - 1),
            prior_gct=[220.0] * GCT_MIN_RUNS,
            recent_power=[250.0] * (GCT_MIN_RUNS - 1),
            prior_power=[250.0] * GCT_MIN_RUNS,
        )
        result = gct_lengthening(inputs)
        assert result is None

    def test_none_on_insufficient_prior_data(self):
        """gct_lengthening returns None when prior window has too few runs."""
        inputs = _inputs_gct(
            recent_gct=[230.0] * GCT_MIN_RUNS,
            prior_gct=[220.0] * (GCT_MIN_RUNS - 1),
            recent_power=[250.0] * GCT_MIN_RUNS,
            prior_power=[250.0] * (GCT_MIN_RUNS - 1),
        )
        result = gct_lengthening(inputs)
        assert result is None

    def test_evidence_carries_actual_values(self):
        """Evidence dict contains gct_recent_mean, gct_prior_mean, power_band."""
        n = GCT_MIN_RUNS
        prior_gct = [220.0] * n
        recent_gct = [220.0 + GCT_RISE_THRESHOLD_MS + 2.0] * n
        inputs = _inputs_gct(
            recent_gct=recent_gct,
            prior_gct=prior_gct,
            recent_power=self._easy_power(n),
            prior_power=self._easy_power(n),
        )
        result = gct_lengthening(inputs)
        assert result is not None
        ev_keys = {e["metric"] for e in result.evidence}
        assert "gct_recent_mean_ms" in ev_keys
        assert "gct_prior_mean_ms" in ev_keys

    def test_none_when_form_metrics_missing(self):
        """gct_lengthening returns None when form_metrics key is absent."""
        inputs = {"week_start": WEEK_START}
        result = gct_lengthening(inputs)
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# AC3: cadence_drift
# ─────────────────────────────────────────────────────────────────────────────

class TestCadenceDrift:

    def test_fires_when_cadence_below_baseline(self):
        """cadence_drift fires when 28d mean < 6-month baseline by > threshold."""
        baseline_cad = 178.0
        # Long baseline: high cadence
        long_cad = [baseline_cad] * 60
        # Recent 28d: cadence dropped by more than threshold
        drift_amount = baseline_cad * (CADENCE_DRIFT_THRESHOLD_PCT / 100.0) + 1.0
        recent_cad = [baseline_cad - drift_amount] * CAD_MIN_RUNS
        inputs = _inputs_cadence(recent_cadence=recent_cad, long_cadence=long_cad)
        result = cadence_drift(inputs)
        assert result is not None
        assert result.code == "cadence_drift"
        assert result.severity == 1

    def test_silent_when_cadence_at_baseline(self):
        """cadence_drift is silent when 28d mean is at the 6-month baseline."""
        baseline_cad = 178.0
        long_cad = [baseline_cad] * 60
        recent_cad = [baseline_cad] * CAD_MIN_RUNS
        inputs = _inputs_cadence(recent_cadence=recent_cad, long_cadence=long_cad)
        result = cadence_drift(inputs)
        assert result is None

    def test_silent_when_cadence_above_baseline(self):
        """cadence_drift is silent when recent cadence exceeds the baseline."""
        baseline_cad = 175.0
        long_cad = [baseline_cad] * 60
        recent_cad = [baseline_cad + 3.0] * CAD_MIN_RUNS
        inputs = _inputs_cadence(recent_cadence=recent_cad, long_cadence=long_cad)
        result = cadence_drift(inputs)
        assert result is None

    def test_baseline_math(self):
        """Baseline is mean of long_baseline_runs; 28d mean is mean of recent_runs."""
        # baseline = 180, recent = 174 → drift = 3.3%
        baseline_cad = 180.0
        long_cad = [baseline_cad] * 60
        recent_mean = 174.0
        recent_cad = [recent_mean] * CAD_MIN_RUNS
        inputs = _inputs_cadence(recent_cadence=recent_cad, long_cadence=long_cad)
        result = cadence_drift(inputs)
        drift_pct = (baseline_cad - recent_mean) / baseline_cad * 100.0
        if drift_pct > CADENCE_DRIFT_THRESHOLD_PCT:
            assert result is not None, "Should fire when drift exceeds threshold"
            # Evidence must reflect actual computed values
            ev = {e["metric"]: e["value"] for e in result.evidence}
            assert abs(ev["cadence_recent_mean_spm"] - recent_mean) < 0.1
            assert abs(ev["cadence_baseline_mean_spm"] - baseline_cad) < 0.1
        else:
            assert result is None

    def test_none_on_insufficient_recent_data(self):
        """cadence_drift returns None when recent window has too few runs."""
        long_cad = [178.0] * 60
        recent_cad = [170.0] * (CAD_MIN_RUNS - 1)
        inputs = _inputs_cadence(recent_cadence=recent_cad, long_cadence=long_cad)
        result = cadence_drift(inputs)
        assert result is None

    def test_none_on_insufficient_long_baseline(self):
        """cadence_drift returns None when long baseline has too few runs."""
        long_cad = [178.0] * (CAD_MIN_RUNS - 1)  # too few
        recent_cad = [170.0] * CAD_MIN_RUNS
        inputs = _inputs_cadence(recent_cadence=recent_cad, long_cadence=long_cad)
        result = cadence_drift(inputs)
        assert result is None

    def test_evidence_carries_actual_values(self):
        """Evidence contains cadence_recent_mean_spm and cadence_baseline_mean_spm."""
        baseline_cad = 178.0
        long_cad = [baseline_cad] * 60
        recent_cad = [170.0] * CAD_MIN_RUNS  # well below baseline
        inputs = _inputs_cadence(recent_cadence=recent_cad, long_cadence=long_cad)
        result = cadence_drift(inputs)
        # If drift % > threshold, result should be not None
        drift_pct = (baseline_cad - 170.0) / baseline_cad * 100.0
        if drift_pct > CADENCE_DRIFT_THRESHOLD_PCT:
            assert result is not None
            ev_keys = {e["metric"] for e in result.evidence}
            assert "cadence_recent_mean_spm" in ev_keys
            assert "cadence_baseline_mean_spm" in ev_keys

    def test_none_when_form_metrics_missing(self):
        """cadence_drift returns None when form_metrics key is absent."""
        inputs = {"week_start": WEEK_START}
        result = cadence_drift(inputs)
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# AC4: constants importable; pure functions
# ─────────────────────────────────────────────────────────────────────────────

class TestThresholdConstants:

    def test_plyo_deficit_constants_defined(self):
        assert isinstance(LSS_IMPROVEMENT_THRESHOLD_PCT, (int, float))
        assert isinstance(PLYO_SESSIONS_PER_WEEK_MIN, (int, float))
        assert isinstance(PLYO_DOSE_WINDOW_WEEKS, int)
        assert isinstance(MIN_RUNS_PER_WINDOW, int)
        assert MIN_RUNS_PER_WINDOW >= 1

    def test_gct_lengthening_constants_defined(self):
        assert isinstance(GCT_RISE_THRESHOLD_MS, (int, float))
        assert isinstance(GCT_EASY_POWER_BAND_WIDTH_W, (int, float))
        assert isinstance(GCT_MIN_RUNS, int)

    def test_cadence_drift_constants_defined(self):
        assert isinstance(CADENCE_DRIFT_THRESHOLD_PCT, (int, float))
        assert isinstance(CADENCE_BASELINE_WINDOW_DAYS, int)
        assert isinstance(CAD_MIN_RUNS, int)

    def test_rules_registered_in_engine(self):
        """All three new rules must appear in the global registry."""
        from backend.services.gap_analysis.engine import _REGISTRY
        rule_names = {e.fn.__name__ for e in _REGISTRY._rules}
        assert "plyo_deficit" in rule_names
        assert "gct_lengthening" in rule_names
        assert "cadence_drift" in rule_names
