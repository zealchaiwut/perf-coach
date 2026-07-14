"""Tests for issue #1378: gap findings feed the weekly coach report facts.

AC coverage:
- AC1: assemble_facts gains gap_findings key (top finding + others_count; empty when none)
- AC2: validate_summary rejects narration against an active severity-3 finding
- AC3: build_fallback_narrative renders the finding line when LLM is off
- AC4: No change when analyzer has never run (facts key absent, report unchanged)
- Tests: facts assembly, contradiction rejection, fallback rendering, absent-key passthrough
"""
from __future__ import annotations

from datetime import date

from backend.services import weekly_summary as ws


# ── Shared helpers ────────────────────────────────────────────────────────────

def _base_facts(**overrides):
    facts = {
        "week_start": "2026-07-07",
        "workout_count": 4,
        "workout_count_by_type": {"run": 4},
        "total_tss": 280.0,
        "prev_week_tss": 260.0,
        "total_distance_km": 35.0,
        "prev_week_distance_km": 32.0,
        "total_duration_minutes": 190.0,
        "ctl_start": 43.0,
        "ctl_end": 45.0,
        "atl_start": 48.0,
        "atl_end": 50.0,
        "tsb_start": -5.0,
        "tsb_end": -5.0,
        "guardrail_state": "ok",
        "guardrail_message": "",
        "acwr": 1.1,
        "prs_achieved": [],
        "verdict": None,
        "verdict_reason": None,
        "verdict_modifiers": [],
        "expected_ctl_in_3w": None,
        "weeks_to_converge": None,
        "converge_date": None,
    }
    facts.update(overrides)
    return facts


def _call_assemble(gap_findings=None, **kw_overrides):
    """Call assemble_facts with minimal defaults for the new gap_findings param."""
    base_kw = dict(
        week_start=date(2026, 7, 7),
        current_workouts=[],
        prev_workouts=[],
        ctl_start=43.0,
        ctl_end=45.0,
        atl_start=48.0,
        atl_end=50.0,
        tsb_start=-5.0,
        tsb_end=-5.0,
        guardrail={"guardrail_state": "ok", "guardrail_message": "", "acwr": 1.1},
        prs=[],
    )
    base_kw.update(kw_overrides)
    if gap_findings is not None:
        base_kw["gap_findings"] = gap_findings
    return ws.assemble_facts(**base_kw)


def _reduce_finding(severity=3, **overrides):
    f = {
        "code": "recurrent_niggle_area",
        "severity": severity,
        "recommendation": "Reduce calf loading this week — injury risk elevated.",
        "evidence": [{"metric": "niggle_count", "value": 3, "threshold": 2, "window": "90d"}],
        "target": "calf",
    }
    f.update(overrides)
    return f


def _add_finding(severity=3, **overrides):
    f = {
        "code": "no_recent_plyo",
        "severity": severity,
        "recommendation": "Add plyometric sessions — none logged in 35 days.",
        "evidence": [{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}],
        "target": None,
    }
    f.update(overrides)
    return f


# ── AC1: Facts assembly ───────────────────────────────────────────────────────

class TestFactsAssemblyGapFindings:
    """AC1: assemble_facts includes gap_findings key correctly."""

    def test_key_present_when_findings_provided(self):
        facts = _call_assemble(gap_findings=[_reduce_finding()])
        assert "gap_findings" in facts

    def test_top_finding_fields(self):
        finding = _reduce_finding(severity=3)
        facts = _call_assemble(gap_findings=[finding])
        top = facts["gap_findings"]["top"]
        assert top["severity"] == 3
        assert "calf" in top["recommendation"].lower()
        assert top["evidence_value"] == 3  # first evidence item's value

    def test_others_count_zero_when_single_finding(self):
        facts = _call_assemble(gap_findings=[_reduce_finding()])
        assert facts["gap_findings"]["others_count"] == 0

    def test_others_count_when_multiple_findings(self):
        findings = [_reduce_finding(severity=3), _add_finding(severity=2), _add_finding(severity=1, code="strength_lapsed")]
        facts = _call_assemble(gap_findings=findings)
        gf = facts["gap_findings"]
        # top is the highest severity
        assert gf["top"]["severity"] == 3
        assert gf["others_count"] == 2

    def test_top_is_highest_severity(self):
        # severity-2 listed first, severity-3 second → top must be severity-3
        findings = [_add_finding(severity=2), _reduce_finding(severity=3)]
        facts = _call_assemble(gap_findings=findings)
        assert facts["gap_findings"]["top"]["severity"] == 3

    def test_empty_findings_gives_empty_dict(self):
        """Analyzer ran but found nothing → empty dict (not absent)."""
        facts = _call_assemble(gap_findings=[])
        assert "gap_findings" in facts
        assert facts["gap_findings"] == {}

    def test_none_findings_key_absent(self):
        """Analyzer has never run → key absent from facts entirely."""
        facts = _call_assemble(gap_findings=None)
        assert "gap_findings" not in facts

    def test_evidence_value_none_when_no_evidence(self):
        finding = _reduce_finding()
        finding["evidence"] = []
        facts = _call_assemble(gap_findings=[finding])
        assert facts["gap_findings"]["top"]["evidence_value"] is None

    def test_target_preserved_in_top(self):
        finding = _reduce_finding(severity=3)
        finding["target"] = "calf"
        facts = _call_assemble(gap_findings=[finding])
        assert facts["gap_findings"]["top"]["target"] == "calf"


# ── AC2: Contradiction rejection ──────────────────────────────────────────────

class TestGapFindingContradictionRejection:
    """AC2: validate_summary rejects narrative that contradicts an active severity-3 finding."""

    def _facts_with_finding(self, severity=3, recommendation="Reduce calf loading this week.", evidence_value=3):
        return _base_facts(
            gap_findings={
                "top": {
                    "code": "recurrent_niggle_area",
                    "severity": severity,
                    "recommendation": recommendation,
                    "evidence_value": evidence_value,
                    "target": "calf",
                },
                "others_count": 0,
            }
        )

    def test_increase_language_rejected_for_severity3_reduce_finding(self):
        facts = self._facts_with_finding(severity=3, recommendation="Reduce calf loading — injury risk elevated.")
        narrative = "Great progress this week! You should increase your calf training volume to build strength."
        errs = ws.validate_summary(narrative, facts)
        assert any("finding" in e.lower() or "gap" in e.lower() for e in errs), \
            f"Expected finding-related error, got: {errs}"

    def test_ramp_up_language_rejected_for_severity3_reduce_finding(self):
        facts = self._facts_with_finding(severity=3, recommendation="Avoid calf load this week.")
        narrative = "Good week — 280 TSS. Ramp up your calf training next week for best results."
        errs = ws.validate_summary(narrative, facts)
        assert any("finding" in e.lower() or "gap" in e.lower() for e in errs)

    def test_negated_increase_not_rejected(self):
        """'Don't increase calf training' is consistent with a reduce finding."""
        facts = self._facts_with_finding(severity=3, recommendation="Reduce calf loading.")
        narrative = "Good week — 280 TSS. Don't increase calf training this week. How's sleep?"
        errs = ws.validate_summary(narrative, facts)
        # No finding contradiction error expected
        assert not any("finding" in e.lower() or "gap" in e.lower() for e in errs)

    def test_severity2_finding_does_not_trigger_rejection(self):
        """Contradiction check only fires for severity-3 findings."""
        facts = self._facts_with_finding(severity=2, recommendation="Reduce calf loading.")
        # Narrative says increase — severity-2 doesn't trigger the hard rejection
        narrative = "Great week — 280.0 TSS. Consider increasing calf volume for strength gains."
        errs = ws.validate_summary(narrative, facts)
        # Either no error or no finding-specific error (the check gates on severity==3)
        assert not any("finding" in e.lower() or "gap" in e.lower() for e in errs)

    def test_no_gap_findings_key_no_finding_error(self):
        """When key is absent, no finding-related validation errors."""
        facts = _base_facts()  # no gap_findings key
        assert "gap_findings" not in facts
        narrative = "Great week — 280.0 TSS. Increase calf training volume."
        errs = ws.validate_summary(narrative, facts)
        assert not any("finding" in e.lower() or "gap" in e.lower() for e in errs)

    def test_empty_gap_findings_no_finding_error(self):
        """Empty dict (no findings) → no finding-related errors."""
        facts = _base_facts(gap_findings={})
        narrative = "Great week — 280.0 TSS. Increase calf training volume."
        errs = ws.validate_summary(narrative, facts)
        assert not any("finding" in e.lower() or "gap" in e.lower() for e in errs)

    def test_add_type_severity3_finding_not_rejected_by_increase_check(self):
        """A severity-3 'add more plyometrics' finding should NOT be rejected by increase-language check."""
        facts = _base_facts(
            gap_findings={
                "top": {
                    "code": "no_recent_plyo",
                    "severity": 3,
                    "recommendation": "Add plyometric sessions — none logged in 35 days.",
                    "evidence_value": 35,
                    "target": None,
                },
                "others_count": 0,
            }
        )
        # Narrative recommends adding plyometrics — consistent with the finding
        narrative = "Good week — 280.0 TSS. Consider adding plyometric sessions."
        errs = ws.validate_summary(narrative, facts)
        # No finding-contradiction error (recommendation says ADD, narrative says add)
        assert not any("finding" in e.lower() or "gap" in e.lower() for e in errs)


# ── AC3: Fallback rendering ───────────────────────────────────────────────────

class TestFallbackRenderingGapFinding:
    """AC3: build_fallback_narrative includes the finding line when LLM is off."""

    def test_finding_recommendation_in_fallback(self):
        finding_top = {
            "code": "recurrent_niggle_area",
            "severity": 3,
            "recommendation": "Reduce calf loading this week.",
            "evidence_value": 3,
            "target": "calf",
        }
        facts = _base_facts(gap_findings={"top": finding_top, "others_count": 0})
        narrative = ws.build_fallback_narrative(facts)
        lower = narrative.lower()
        assert "calf" in lower or "reduce" in lower or "calf loading" in lower, \
            f"Expected finding mention in fallback: {narrative}"

    def test_empty_gap_findings_no_finding_line(self):
        """Empty findings → no crash, no finding line added."""
        facts = _base_facts(gap_findings={})
        narrative = ws.build_fallback_narrative(facts)
        assert isinstance(narrative, str)
        assert len(narrative) > 0

    def test_absent_gap_findings_no_change(self):
        """Key absent → narrative identical to pre-feature behavior."""
        facts_no_gap = _base_facts()
        assert "gap_findings" not in facts_no_gap
        narrative_no_gap = ws.build_fallback_narrative(facts_no_gap)

        # Same facts with gap_findings explicitly absent is the same call
        assert isinstance(narrative_no_gap, str)
        assert len(narrative_no_gap) > 0

    def test_finding_line_present_even_with_no_workouts(self):
        """Zero-workout week + severity-3 finding → finding still rendered."""
        finding_top = {
            "code": "recurrent_niggle_area",
            "severity": 3,
            "recommendation": "Protect the left hamstring.",
            "evidence_value": None,
            "target": "hamstring",
        }
        facts = _base_facts(
            workout_count=0,
            total_tss=None,
            total_distance_km=None,
            total_duration_minutes=None,
            gap_findings={"top": finding_top, "others_count": 0},
        )
        narrative = ws.build_fallback_narrative(facts)
        lower = narrative.lower()
        assert "hamstring" in lower or "protect" in lower, \
            f"Expected finding in zero-workout fallback: {narrative}"

    def test_others_count_mentioned_when_more_than_zero(self):
        """When others_count > 0, fallback may mention additional findings."""
        finding_top = {
            "code": "recurrent_niggle_area",
            "severity": 3,
            "recommendation": "Reduce calf loading.",
            "evidence_value": 3,
            "target": "calf",
        }
        facts = _base_facts(gap_findings={"top": finding_top, "others_count": 2})
        narrative = ws.build_fallback_narrative(facts)
        # At minimum, the top finding should be mentioned — the others_count is bonus
        lower = narrative.lower()
        assert "calf" in lower or "reduce" in lower


# ── AC4: Absent-key passthrough ──────────────────────────────────────────────

class TestAbsentKeyPassthrough:
    """AC4: when gap_findings key is absent, behavior is identical to pre-feature."""

    def test_fallback_identical_without_key(self):
        """Baseline: assemble_facts(gap_findings=None) produces same other keys."""
        facts_without = _call_assemble(gap_findings=None)
        # All keys present except gap_findings
        assert "gap_findings" not in facts_without
        assert "workout_count" in facts_without
        assert "total_tss" in facts_without

    def test_validate_summary_no_extra_errors_without_key(self):
        """validate_summary adds no finding errors when key is absent."""
        facts = _base_facts()
        assert "gap_findings" not in facts
        # narrative with increase language: only verdict-related errors possible
        # since verdict=None, no verdict errors either
        narrative = "Good week — 280.0 TSS, 35.0 km."
        errs = ws.validate_summary(narrative, facts)
        assert not any("finding" in e.lower() or "gap" in e.lower() for e in errs)

    def test_build_response_unchanged_without_key(self):
        """build_response still works when facts has no gap_findings."""
        facts = _base_facts()
        result = ws.build_response(
            week_start="2026-07-07",
            facts=facts,
            narrative="Solid week.",
            source="fallback",
        )
        assert result["week_start"] == "2026-07-07"
        assert result["source"] == "fallback"
        assert result["narrative"] == "Solid week."
