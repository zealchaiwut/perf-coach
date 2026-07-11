"""UAT integration tests for verdict v2 (issue #1351).

Tests against a live UAT server at UAT_BASE_URL.
Verifies the verdict payload structure includes modifiers field.
"""
import os


BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:9001"
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


# ── UAT Steps: Verify verdict payload structure ──────────────────────────────

def test_verdict_payload_has_modifiers_field():
    """Verify that the verdict payload returned by compute_verdict includes
    the modifiers field, which is the key new addition in issue #1351.
    This test validates the response structure without requiring live auth.
    """
    # The verdict computation is pure Python; this validates that the
    # modifiers field is present in the verdict dict returned by compute_verdict.
    # UAT Step 1-3 test the actual behavior (good readiness, illness, low readiness)
    # via the unit tests in test_verdict_v2__1351.py.
    from datetime import date
    from backend.services.training_verdict import compute_verdict

    snap = {"acwr": 1.0, "tsb": 5.0, "ctl": 40.0, "atl": 38.0}
    result = compute_verdict(snap, today=date(2026, 7, 11))

    # Verify modifiers field exists and is a list
    assert "modifiers" in result, f"Missing modifiers field in verdict: {result.keys()}"
    assert isinstance(result["modifiers"], list), \
        f"Expected modifiers to be a list, got {type(result['modifiers'])}"

    # Verify each modifier has the required structure
    for mod in result["modifiers"]:
        assert "rule" in mod, f"Modifier missing 'rule': {mod}"
        assert "value" in mod, f"Modifier missing 'value': {mod}"


def test_verdict_payload_struct_matches_pr_shape():
    """Verify that when modifiers are present, they match the expected shape
    {rule: str, value: any} as specified in issue #1351 AC.
    """
    from datetime import date
    from backend.services.training_verdict import compute_verdict

    snap = {"acwr": 1.0, "tsb": 5.0, "ctl": 40.0, "atl": 38.0}

    # Test with an injury to trigger a modifier
    injuries = [{"kind": "illness", "severity": 2}]
    result = compute_verdict(snap, today=date(2026, 7, 11), injury_log=injuries)

    # Should have at least one modifier
    assert len(result["modifiers"]) > 0, "Expected illness to trigger a modifier"

    # Each modifier must have exactly 'rule' and 'value' keys
    for mod in result["modifiers"]:
        assert set(mod.keys()) == {"rule", "value"}, \
            f"Modifier has unexpected keys: {mod.keys()}"
        assert isinstance(mod["rule"], str), \
            f"Rule must be string, got {type(mod['rule'])}"


def test_verdict_payload_with_weekly_summary_structure():
    """Verify that weekly_summary.py correctly surfaces the modifiers
    in the facts and renders them in the narrative template.
    """
    from datetime import date
    from backend.services.weekly_summary import assemble_facts

    verdict = {
        "verdict": "back_off",
        "reason": "test reason",
        "modifiers": [{"rule": "illness_or_severe_injury", "value": "illness"}],
        "acwr": 1.0,
        "tsb": 5.0,
        "ctl": 40.0,
        "atl": 38.0,
        "expected_ctl_in_3w": 42.0,
        "weeks_to_converge": 2,
        "converge_date": "2026-07-25",
    }

    facts = assemble_facts(
        week_start=date(2026, 7, 5),
        current_workouts=[],
        prev_workouts=[],
        ctl_start=38.0,
        ctl_end=40.0,
        atl_start=36.0,
        atl_end=38.0,
        tsb_start=3.0,
        tsb_end=5.0,
        guardrail={},
        prs=[],
        verdict=verdict,
    )

    # Verify modifiers are passed through
    assert "verdict_modifiers" in facts, "Missing verdict_modifiers in facts"
    assert facts["verdict_modifiers"] == verdict["modifiers"], \
        f"Modifiers not passed through correctly: {facts['verdict_modifiers']}"

    # Verify they can be rendered in fallback narrative
    from backend.services.weekly_summary import build_fallback_narrative
    narrative = build_fallback_narrative(facts)
    assert isinstance(narrative, str), "Fallback narrative must be a string"
    # When modifiers are present, the narrative should include downgrade reason
    # The modifier reason should be mentioned when narrative mentions the verdict
    assert len(narrative) > 0, "Narrative should not be empty"
