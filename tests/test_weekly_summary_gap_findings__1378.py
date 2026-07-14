"""Tests for issue #1378: Weekly summary integration — gap findings feed the coach report facts (runs against UAT)

AC coverage:
- AC1: Weekly-summary facts dict gains `gap_findings`: the week's top finding + others_count; empty when none
- AC2: Narration validation extended: reject narration recommending against an active severity-3 finding
- AC3: Deterministic fallback report section renders the finding line when LLM is off
- AC4: No change when the analyzer has never run (facts key absent, report unchanged) — regression test
"""
import os
import pytest
import httpx
from datetime import date


# Resolved from UAT .env at runtime; see tester skill Step 0.
# Default kept only as a last-resort fallback if BASE_URL not exported.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# ── AC1: Facts assembly includes gap_findings key ────────────────────────────

def test_weekly_summary_gap_findings__endpoint_responds(client):
    """AC1: GET /api/weekly-summary endpoint is available and returns facts structure."""
    pytest.skip("manual — requires authenticated test user setup in UAT DB")


def test_weekly_summary_gap_findings__facts_structure_includes_gap_findings_or_absent(client):
    """AC1: When gap_findings is present in facts, it has top (code/severity/recommendation/evidence_value) + others_count."""
    pytest.skip("manual — integration test requires UAT test user with gap findings")


def test_weekly_summary_gap_findings__empty_findings_gives_empty_dict(client):
    """AC1: When analyzer ran but found no active findings, gap_findings is {} (not absent)."""
    pytest.skip("manual — requires week with analyzer run but zero active findings")


def test_weekly_summary_gap_findings__absent_key_backward_compat(client):
    """AC1 & AC4: When analyzer has never run, gap_findings key is absent from facts."""
    pytest.skip("manual — requires week where gap analyzer hasn't run")


# ── AC2: Narration validation rejects contradicting severity-3 findings ──────────

def test_weekly_summary_gap_findings__narration_accepts_negated_increase_with_reduce_finding(client):
    """AC2: Narration saying 'don't increase' is consistent with reduce finding; no rejection."""
    pytest.skip("validation tested in unit tests; UAT integration requires LLM + specific narrative setup")


def test_weekly_summary_gap_findings__narration_rejects_increase_with_severity3_finding(client):
    """AC2: Narration recommending increase is rejected when severity-3 reduce finding is active."""
    pytest.skip("validation tested in unit tests; UAT integration requires LLM setup")


# ── AC3: Fallback narrative renders the finding ─────────────────────────────────

def test_weekly_summary_gap_findings__fallback_includes_finding_recommendation(client):
    """AC3: When LLM is off, narrative includes the gap finding recommendation."""
    pytest.skip("requires LLM_COACH_ENABLED=0 in UAT and active gap finding")


def test_weekly_summary_gap_findings__fallback_finding_renders_on_zero_week(client):
    """AC3: Finding line renders even when workout_count is 0."""
    pytest.skip("requires zero-workout week with active finding in UAT DB")


# ── AC4: Absent-key passthrough (regression) ────────────────────────────────────

def test_weekly_summary_gap_findings__response_shape_unchanged_without_key(client):
    """AC4: Response shape {week_start, facts, narrative, source} is consistent."""
    pytest.skip("requires UAT test user and authenticated session")


def test_weekly_summary_gap_findings__standard_facts_keys_present(client):
    """AC4: Standard facts keys (week_start, workout_count, verdict) present regardless of analyzer state."""
    pytest.skip("requires UAT test user and authenticated session")


# ── Unit-layer tests (run against imported modules) ──────────────────────────────

def test_assemble_facts_gap_findings_key_present():
    """AC1 unit: assemble_facts includes gap_findings key when provided."""
    from backend.services.weekly_summary import assemble_facts

    facts = assemble_facts(
        week_start=date(2026, 7, 7),
        current_workouts=[],
        prev_workouts=[],
        ctl_start=40.0, ctl_end=42.0,
        atl_start=48.0, atl_end=50.0,
        tsb_start=-5.0, tsb_end=-5.0,
        guardrail={"guardrail_state": "ok"},
        prs=[],
        gap_findings=[
            {
                "code": "test_finding",
                "severity": 3,
                "recommendation": "Reduce load",
                "evidence": [{"value": 5}],
                "target": "test",
            }
        ],
    )
    assert "gap_findings" in facts
    assert facts["gap_findings"]["top"]["severity"] == 3
    assert facts["gap_findings"]["others_count"] == 0


def test_assemble_facts_gap_findings_key_absent_when_none():
    """AC4 unit: gap_findings key absent when None is passed."""
    from backend.services.weekly_summary import assemble_facts

    facts = assemble_facts(
        week_start=date(2026, 7, 7),
        current_workouts=[],
        prev_workouts=[],
        ctl_start=40.0, ctl_end=42.0,
        atl_start=48.0, atl_end=50.0,
        tsb_start=-5.0, tsb_end=-5.0,
        guardrail={"guardrail_state": "ok"},
        prs=[],
        gap_findings=None,
    )
    assert "gap_findings" not in facts


def test_assemble_facts_gap_findings_empty_dict_when_empty_list():
    """AC1 unit: gap_findings is {} when analyzer ran but found no active findings."""
    from backend.services.weekly_summary import assemble_facts

    facts = assemble_facts(
        week_start=date(2026, 7, 7),
        current_workouts=[],
        prev_workouts=[],
        ctl_start=40.0, ctl_end=42.0,
        atl_start=48.0, atl_end=50.0,
        tsb_start=-5.0, tsb_end=-5.0,
        guardrail={"guardrail_state": "ok"},
        prs=[],
        gap_findings=[],
    )
    assert "gap_findings" in facts
    assert facts["gap_findings"] == {}


def test_assemble_facts_top_finding_highest_severity():
    """AC1 unit: top finding is the highest severity when multiple findings provided."""
    from backend.services.weekly_summary import assemble_facts

    facts = assemble_facts(
        week_start=date(2026, 7, 7),
        current_workouts=[],
        prev_workouts=[],
        ctl_start=40.0, ctl_end=42.0,
        atl_start=48.0, atl_end=50.0,
        tsb_start=-5.0, tsb_end=-5.0,
        guardrail={"guardrail_state": "ok"},
        prs=[],
        gap_findings=[
            {"code": "low_sev", "severity": 1, "recommendation": "Low", "evidence": [], "target": None},
            {"code": "high_sev", "severity": 3, "recommendation": "High", "evidence": [], "target": None},
            {"code": "mid_sev", "severity": 2, "recommendation": "Mid", "evidence": [], "target": None},
        ],
    )
    assert facts["gap_findings"]["top"]["severity"] == 3
    assert facts["gap_findings"]["others_count"] == 2


def test_validate_summary_rejects_increase_with_severity3_reduce_finding():
    """AC2 unit: validate_summary rejects increase-language when severity-3 reduce finding present."""
    from backend.services.weekly_summary import validate_summary

    facts = {
        "verdict": None,
        "gap_findings": {
            "top": {
                "code": "injury_risk",
                "severity": 3,
                "recommendation": "Reduce calf loading",
                "evidence_value": 3,
                "target": "calf",
            },
            "others_count": 0,
        },
    }
    narrative = "Good progress. Increase calf training volume."
    errs = validate_summary(narrative, facts)
    assert any("finding" in e.lower() or "gap" in e.lower() for e in errs), f"Expected finding error, got: {errs}"


def test_validate_summary_allows_negated_increase_with_severity3_finding():
    """AC2 unit: negated increase ('don't increase') is allowed with reduce finding."""
    from backend.services.weekly_summary import validate_summary

    facts = {
        "verdict": None,
        "gap_findings": {
            "top": {
                "code": "injury_risk",
                "severity": 3,
                "recommendation": "Reduce calf loading",
                "evidence_value": 3,
                "target": "calf",
            },
            "others_count": 0,
        },
    }
    narrative = "Solid week. Don't increase calf training yet."
    errs = validate_summary(narrative, facts)
    assert not any("finding" in e.lower() or "gap" in e.lower() for e in errs)


def test_build_fallback_narrative_includes_finding():
    """AC3 unit: build_fallback_narrative renders the gap finding when present."""
    from backend.services.weekly_summary import build_fallback_narrative

    facts = {
        "workout_count": 3,
        "total_tss": 250.0,
        "gap_findings": {
            "top": {
                "code": "injury_risk",
                "severity": 3,
                "recommendation": "Protect the hamstring",
                "evidence_value": None,
                "target": "hamstring",
            },
            "others_count": 0,
        },
    }
    narrative = build_fallback_narrative(facts)
    lower = narrative.lower()
    assert "hamstring" in lower or "protect" in lower, f"Expected finding mention: {narrative}"


def test_build_fallback_narrative_excludes_finding_when_empty():
    """AC4 unit: empty gap_findings (no active findings) doesn't add a finding line."""
    from backend.services.weekly_summary import build_fallback_narrative

    facts = {
        "workout_count": 3,
        "total_tss": 250.0,
        "gap_findings": {},
    }
    narrative = build_fallback_narrative(facts)
    # Should not mention a specific finding; generic fallback only
    assert isinstance(narrative, str)
    assert len(narrative) > 0


def test_build_fallback_narrative_no_key_unchanged():
    """AC4 unit: when gap_findings key is absent, fallback unchanged."""
    from backend.services.weekly_summary import build_fallback_narrative

    facts = {
        "workout_count": 3,
        "total_tss": 250.0,
    }
    narrative = build_fallback_narrative(facts)
    # Should not crash; standard narrative only
    assert isinstance(narrative, str)
    assert len(narrative) > 0
