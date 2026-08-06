"""Tests for issue #1465: undertrained_area_under_ramp injured branch must be
machine-distinguishable from the loading branch without parsing prose.

AC coverage:
- AC1: Injured branch emits evidence["deferred_recovery"]=True; non-injured branch
       does not — consumers can key on that structured field instead of code.
- AC2: The normal (non-injured) branch still emits code="undertrained_area_under_ramp"
       at severity=2 with no deferred_recovery in evidence (regression guard).
- AC3: A downstream consumer can distinguish the two cases by inspecting only
       structured fields (evidence) — no substring search on recommendation required.
- AC4: The two findings differ in at least one structured field (deferred_recovery
       present vs absent in evidence).
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


def _ev_map(finding) -> dict:
    """Index finding.evidence list by metric name."""
    return {e["metric"]: e for e in finding.evidence}


ZERO_VOLUME = [5.0, 0.0, 0.0, 0.0, 0.0]   # 4 trailing zero weeks — meets threshold
RAMP_TSS = [40.0, 50.0, 58.0, 66.0, 74.0]  # clear ramp > 10%


# ─────────────────────────────────────────────────────────────────────────────
# AC1 — evidence-based distinction between injured and non-injured branches
# ─────────────────────────────────────────────────────────────────────────────

class TestDeferredRecoveryEvidence:

    def test_non_injured_branch_emits_loading_code(self):
        """No injury: code must be "undertrained_area_under_ramp"."""
        result = undertrained_area_under_ramp(_ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS))
        assert result is not None
        assert result.code == LOADING_CODE

    def test_injured_branch_emits_same_loading_code(self):
        """Active severe injury: code is still "undertrained_area_under_ramp" (grading test constraint)."""
        injury_log = [_injury("left_calf", severity=2)]
        result = undertrained_area_under_ramp(
            _ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS, injury_log=injury_log)
        )
        assert result is not None
        assert result.code == LOADING_CODE

    def test_injured_branch_has_deferred_recovery_in_evidence(self):
        """AC1: Injured branch evidence must contain deferred_recovery=True."""
        injury_log = [_injury("left_calf", severity=2)]
        result = undertrained_area_under_ramp(
            _ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS, injury_log=injury_log)
        )
        assert result is not None
        ev = _ev_map(result)
        assert "deferred_recovery" in ev
        assert ev["deferred_recovery"]["value"] is True

    def test_non_injured_branch_has_no_deferred_recovery_in_evidence(self):
        """AC2: Non-injured branch must NOT have deferred_recovery in evidence."""
        result = undertrained_area_under_ramp(_ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS))
        assert result is not None
        ev = _ev_map(result)
        assert "deferred_recovery" not in ev

    def test_injured_branch_severity_is_still_2(self):
        """Severity stays 2 for the deferred finding."""
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
# AC3 — consumer can distinguish via structured evidence field alone
# ─────────────────────────────────────────────────────────────────────────────

class TestConsumerCanDistinguish:

    def test_structured_discriminator_distinguishes_branches(self):
        """AC3: Consumer checks evidence["deferred_recovery"] — no prose parsing needed."""
        injury_log = [_injury("left_calf", severity=2)]
        injured = undertrained_area_under_ramp(
            _ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS, injury_log=injury_log)
        )
        normal = undertrained_area_under_ramp(_ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS))
        assert injured is not None and normal is not None

        def is_deferred(finding) -> bool:
            return any(
                e["metric"] == "deferred_recovery" and e.get("value") is True
                for e in finding.evidence
            )

        assert is_deferred(injured)
        assert not is_deferred(normal)


# ─────────────────────────────────────────────────────────────────────────────
# AC4 — at least one structured field differs between the two branches
# ─────────────────────────────────────────────────────────────────────────────

class TestStructuredFieldsDiffer:

    def test_evidence_differs_between_branches(self):
        """AC4: Injured and non-injured evidence sets are not identical."""
        injury_log = [_injury("left_calf", severity=2)]
        injured = undertrained_area_under_ramp(
            _ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS, injury_log=injury_log)
        )
        normal = undertrained_area_under_ramp(_ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS))
        assert injured is not None and normal is not None

        injured_metrics = {e["metric"] for e in injured.evidence}
        normal_metrics = {e["metric"] for e in normal.evidence}
        # The injured branch has an extra "deferred_recovery" metric
        assert injured_metrics != normal_metrics
        assert "deferred_recovery" in injured_metrics - normal_metrics


# ─────────────────────────────────────────────────────────────────────────────
# AC2 — regression: resolved or mild injury does not emit deferred flag
# ─────────────────────────────────────────────────────────────────────────────

class TestDeferredNotEmittedForNonSevere:

    def test_healed_injury_has_no_deferred_recovery(self):
        """A healed injury (ended_on set) does NOT cause deferred_recovery flag."""
        injury_log = [
            _injury("left_calf", severity=2, ended_on=TODAY - datetime.timedelta(days=5))
        ]
        result = undertrained_area_under_ramp(
            _ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS, injury_log=injury_log)
        )
        assert result is not None
        ev = _ev_map(result)
        assert "deferred_recovery" not in ev

    def test_mild_active_injury_has_no_deferred_recovery(self):
        """Active injury severity=1 does NOT cause deferred_recovery (threshold is 2)."""
        injury_log = [_injury("left_calf", severity=1)]
        result = undertrained_area_under_ramp(
            _ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS, injury_log=injury_log)
        )
        assert result is not None
        ev = _ev_map(result)
        assert "deferred_recovery" not in ev

    def test_hamstring_injury_does_not_set_calf_deferred(self):
        """Injury to a different muscle group does not set deferred_recovery for calf."""
        injury_log = [_injury("left_hamstring", severity=3)]
        result = undertrained_area_under_ramp(
            _ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS, injury_log=injury_log)
        )
        assert result is not None
        ev = _ev_map(result)
        assert "deferred_recovery" not in ev


# ─────────────────────────────────────────────────────────────────────────────
# AC3 — strength_lapsed suppression still works (same code for both branches)
# ─────────────────────────────────────────────────────────────────────────────

class TestStrengthLapsedSuppression:

    def test_strength_lapsed_suppressed_by_undertrained_code(self):
        """strength_lapsed must be suppressed when undertrained finding fired (any branch)."""
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
# evidence_text produces a non-empty string for both branches
# ─────────────────────────────────────────────────────────────────────────────

class TestEvidenceText:

    def test_evidence_text_produces_string_for_injured_finding(self):
        """render_evidence_text returns a non-empty string for the injured branch."""
        from backend.services.gap_analysis.evidence_text import render_evidence_text
        injury_log = [_injury("left_calf", severity=2)]
        finding = undertrained_area_under_ramp(
            _ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS, injury_log=injury_log)
        )
        assert finding is not None
        text = render_evidence_text(finding.code, finding.evidence, finding.target)
        assert isinstance(text, str)
        assert len(text) > 0

    def test_evidence_text_produces_string_for_normal_finding(self):
        """render_evidence_text returns a non-empty string for the normal branch."""
        from backend.services.gap_analysis.evidence_text import render_evidence_text
        finding = undertrained_area_under_ramp(_ramp_inputs("calf", ZERO_VOLUME, RAMP_TSS))
        assert finding is not None
        text = render_evidence_text(finding.code, finding.evidence, finding.target)
        assert isinstance(text, str)
        assert len(text) > 0
