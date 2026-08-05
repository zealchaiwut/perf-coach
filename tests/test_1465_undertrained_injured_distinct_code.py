"""Tests for issue #1465: undertrained_area_under_ramp injured branch must emit
a distinct code so downstream consumers can distinguish "load this area" from
"defer, you are injured" without parsing prose.

AC coverage:
- AC1: Injured branch emits code="undertrained_area_under_ramp_deferred", not
       "undertrained_area_under_ramp"
- AC1: Non-injured branch still emits code="undertrained_area_under_ramp"
       (no regression)
- AC2: The two codes are machine-distinguishable by the code field alone —
       no prose parsing required
- AC3: strength_lapsed is suppressed when "undertrained_area_under_ramp_deferred"
       fires (injured finding still acts as a structural rule for suppression)
- AC4: "undertrained_area_under_ramp_deferred" returns None from
       get_template (no load-adding action for a recovery-deferring finding)
- AC4: evidence_text produces a non-empty string for the deferred code
"""
from __future__ import annotations

import datetime
from typing import Optional


from backend.services.gap_analysis.rules.undertrained_area_under_ramp import (
    undertrained_area_under_ramp,
)
from backend.services.gap_analysis.rules.strength_lapsed import strength_lapsed

TODAY = datetime.date(2026, 7, 14)
WEEK_START = TODAY - datetime.timedelta(days=TODAY.weekday())  # 2026-07-07

LOADING_CODE = "undertrained_area_under_ramp"
DEFERRED_CODE = "undertrained_area_under_ramp_deferred"


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _injury(body_area: str, severity: int, ended_on: Optional[datetime.date] = None) -> dict:
    return {
        "body_area": body_area,
        "severity": severity,
        "started_on": (TODAY - datetime.timedelta(days=7)).isoformat(),
        "ended_on": ended_on.isoformat() if ended_on else None,
    }


def _make_weekly_tss(values: list[float]) -> list[dict]:
    buckets = []
    for i, v in enumerate(values):
        ws = WEEK_START - datetime.timedelta(weeks=len(values) - 1 - i)
        buckets.append({"week_start": ws.isoformat(), "running_tss": v})
    return buckets


def _make_muscle_rows(group: str, volumes: list[float]) -> list[dict]:
    rows = []
    for i, v in enumerate(volumes):
        ws = WEEK_START - datetime.timedelta(weeks=len(volumes) - 1 - i)
        rows.append({"week_start": ws.isoformat(), "muscle_group": group, "weekly_load": v})
    return rows


def _ramp_inputs(
    group: str,
    volume: list[float],
    tss: list[float],
    injury_log: Optional[list[dict]] = None,
) -> dict:
    from backend.services.gap_analysis.rules.undertrained_area_under_ramp import LOWER_BODY_PRIORITY_GROUPS
    muscle_volume = _make_muscle_rows(group, volume)
    n = len(volume)
    for other in LOWER_BODY_PRIORITY_GROUPS:
        if other != group:
            muscle_volume.extend(_make_muscle_rows(other, [5.0] * n))
    return {
        "week_start": WEEK_START,
        "muscle_volume": muscle_volume,
        "training_load": {"weekly": _make_weekly_tss(tss)},
        "injury_log": injury_log or [],
    }


ZERO_VOLUME = [5.0, 0.0, 0.0, 0.0, 0.0]   # 4 trailing zero weeks — meets threshold
RAMP_TSS = [40.0, 50.0, 58.0, 66.0, 74.0]  # clear ramp > 10%


# ─────────────────────────────────────────────────────────────────────────────
# AC1 — code distinction between injured and non-injured branches
# ─────────────────────────────────────────────────────────────────────────────

class TestDistinctCode:

    def test_non_injured_branch_emits_loading_code(self):
        """No injury: code must be "undertrained_area_under_ramp"."""
        result = undertrained_area_under_ramp(_ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS))
        assert result is not None
        assert result.code == LOADING_CODE

    def test_injured_branch_emits_deferred_code(self):
        """Active severe injury: code must be "undertrained_area_under_ramp_deferred"."""
        injury_log = [_injury("left_calf", severity=2)]
        result = undertrained_area_under_ramp(
            _ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS, injury_log=injury_log)
        )
        assert result is not None
        assert result.code == DEFERRED_CODE

    def test_injured_code_differs_from_loading_code(self):
        """The two codes are distinct strings — a consumer can branch on code alone."""
        assert LOADING_CODE != DEFERRED_CODE

    def test_injured_branch_severity_is_still_2(self):
        """Severity stays 2 for the deferred finding (same priority as loading finding)."""
        injury_log = [_injury("left_calf", severity=2)]
        result = undertrained_area_under_ramp(
            _ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS, injury_log=injury_log)
        )
        assert result is not None
        assert result.severity == 2

    def test_injured_branch_target_is_muscle_group(self):
        """Deferred finding still names the injured muscle group as target."""
        injury_log = [_injury("left_calf", severity=2)]
        result = undertrained_area_under_ramp(
            _ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS, injury_log=injury_log)
        )
        assert result is not None
        assert result.target == "calf"

    def test_injured_branch_recommendation_defers_to_recovery(self):
        """Deferred finding recommendation must mention recovery, defer, or avoid."""
        injury_log = [_injury("left_calf", severity=2)]
        result = undertrained_area_under_ramp(
            _ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS, injury_log=injury_log)
        )
        assert result is not None
        text = result.recommendation.lower()
        assert any(word in text for word in ("recover", "defer", "avoid", "injury"))

    def test_non_injured_branch_recommendation_is_loading(self):
        """Non-injured finding recommendation must mention reintroduce or strength work."""
        result = undertrained_area_under_ramp(_ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS))
        assert result is not None
        text = result.recommendation.lower()
        assert any(word in text for word in ("reintroduce", "strength", "volume", "targeted"))


# ─────────────────────────────────────────────────────────────────────────────
# AC2 — regression: resolved or mild injury does not emit deferred code
# ─────────────────────────────────────────────────────────────────────────────

class TestDeferredCodeNotEmittedForNonSevere:

    def test_healed_injury_emits_loading_code(self):
        """A healed injury (ended_on set) does NOT cause deferred code."""
        injury_log = [
            _injury("left_calf", severity=2, ended_on=TODAY - datetime.timedelta(days=5))
        ]
        result = undertrained_area_under_ramp(
            _ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS, injury_log=injury_log)
        )
        assert result is not None
        assert result.code == LOADING_CODE

    def test_mild_active_injury_emits_loading_code(self):
        """Active injury severity=1 does NOT cause deferred code (threshold is 2)."""
        injury_log = [_injury("left_calf", severity=1)]
        result = undertrained_area_under_ramp(
            _ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS, injury_log=injury_log)
        )
        assert result is not None
        assert result.code == LOADING_CODE

    def test_hamstring_injury_does_not_suppress_calf_finding(self):
        """Injury to a different muscle group does not trigger deferred code for calf."""
        injury_log = [_injury("left_hamstring", severity=3)]
        result = undertrained_area_under_ramp(
            _ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS, injury_log=injury_log)
        )
        assert result is not None
        assert result.code == LOADING_CODE


# ─────────────────────────────────────────────────────────────────────────────
# AC3 — strength_lapsed suppression still works for deferred code
# ─────────────────────────────────────────────────────────────────────────────

class TestStrengthLapsedSuppression:

    def test_strength_lapsed_suppressed_by_deferred_code(self):
        """strength_lapsed must be suppressed when deferred-recovery finding fired."""
        result = strength_lapsed({
            "week_start": WEEK_START,
            "structural_dose": {"last_strength_days_ago": 30},
            "other_findings_codes": [DEFERRED_CODE],
        })
        assert result is None

    def test_strength_lapsed_suppressed_by_loading_code(self):
        """strength_lapsed must still be suppressed by the original loading code."""
        result = strength_lapsed({
            "week_start": WEEK_START,
            "structural_dose": {"last_strength_days_ago": 30},
            "other_findings_codes": [LOADING_CODE],
        })
        assert result is None

    def test_strength_lapsed_not_suppressed_by_unrelated_code(self):
        """Unrelated code does not suppress strength_lapsed."""
        result = strength_lapsed({
            "week_start": WEEK_START,
            "structural_dose": {"last_strength_days_ago": 30},
            "other_findings_codes": ["some_other_rule"],
        })
        assert result is not None
        assert result.code == "strength_lapsed"


# ─────────────────────────────────────────────────────────────────────────────
# AC4 — deferred code has no load-adding template (recovery, not load action)
# ─────────────────────────────────────────────────────────────────────────────

class TestDeferredCodeTemplate:

    def test_get_template_returns_none_for_deferred_code(self):
        """get_template("undertrained_area_under_ramp_deferred") returns None (no
        load-adding action for a recovery-deferring finding)."""
        from backend.services.gap_analysis.templates import get_template
        result = get_template(DEFERRED_CODE)
        assert result is None

    def test_evidence_text_produces_string_for_deferred_code(self):
        """render_evidence_text returns a non-empty string for the deferred code."""
        from backend.services.gap_analysis.evidence_text import render_evidence_text
        injury_log = [_injury("left_calf", severity=2)]
        finding = undertrained_area_under_ramp(
            _ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS, injury_log=injury_log)
        )
        assert finding is not None
        assert finding.code == DEFERRED_CODE
        text = render_evidence_text(finding.code, finding.evidence, finding.target)
        assert isinstance(text, str)
        assert len(text) > 0
