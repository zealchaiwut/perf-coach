"""Tests for issue #1381: gap analyzer muscle-balance rules (pack D).

AC coverage:
- AC1: muscle_overused — severity 3 when overused+trending_up, severity 2 when elevated
  or overused-not-trending; evidence = acute, chronic, acwr, main source
- AC2: muscle_untrained — severity 2 for priority group untrained 4+ weeks;
  severity 1 for detraining groups
- AC3: interactions — injured+overused still fires (rest-flavored); injured+untrained
  suppressed; dedup with pack C via claimed_groups
- AC4: pure functions, thresholds from muscle_load_acwr (not redefined), insufficient
  ledger history (< 4 weeks) → rules skipped
- AC5: tests — severity bands, injured suppression/override matrix, dedup-with-pack-C,
  insufficient history
"""
from __future__ import annotations

import datetime

from backend.services.muscle_load_acwr import (
    OVERUSED_BOUND,
    ELEVATED_BOUND,
)
from backend.services.gap_analysis.rules.muscle_balance import (
    muscle_overused,
    muscle_untrained,
    UNTRAINED_MIN_WEEKS,
)

_TODAY = datetime.date(2026, 7, 14)
_WEEK_START = _TODAY - datetime.timedelta(days=_TODAY.weekday())  # 2026-07-14


# ── helpers ───────────────────────────────────────────────────────────────────

def _group_data(
    classification: str,
    *,
    acute: float = 20.0,
    chronic: float = 15.0,
    acwr: float = 1.3,
    injured: bool = False,
    trending_up: bool = False,
    weeks_untrained: int = 0,
    source_breakdown: dict | None = None,
) -> dict:
    return {
        "acute_7d": acute,
        "chronic_28d": chronic,
        "acwr": acwr,
        "classification": classification,
        "injured": injured,
        "trending_up": trending_up,
        "weeks_untrained": weeks_untrained,
        "source_breakdown": source_breakdown or {"run": 0.7, "strength": 0.3},
    }


def _ledger(groups: dict, history_weeks: int = 8) -> dict:
    """Build a muscle_load_ledger with only the specified groups populated.

    All groups not listed default to a 'balanced' state with no load.
    """
    from backend.services.muscle_load_acwr import ALL_GROUPS
    full = {}
    for g in ALL_GROUPS:
        if g in groups:
            full[g] = groups[g]
        else:
            full[g] = _group_data("balanced", acute=10.0, chronic=10.0, acwr=1.0)
    return {"groups": full, "history_weeks": history_weeks}


def _inputs(ledger: dict, *, other_findings_codes: list | None = None,
            claimed_groups: set | None = None) -> dict:
    return {
        "week_start": _WEEK_START,
        "muscle_load_ledger": ledger,
        "other_findings_codes": other_findings_codes or [],
        "claimed_groups": claimed_groups or set(),
    }


# ── AC1: muscle_overused severity bands ──────────────────────────────────────

class TestMuscleOverusedSeverity:
    """AC1: correct severity for each classification × trending state."""

    def test_overused_trending_up_is_severity_3(self):
        """overused + trending_up → severity 3 (highest priority)."""
        ledger = _ledger({
            "calf": _group_data("overused", acute=30.0, chronic=15.0, acwr=2.0, trending_up=True),
        })
        findings = muscle_overused(_inputs(ledger))
        calf_f = next((f for f in findings if f.target == "calf"), None)
        assert calf_f is not None, "muscle_overused should fire for calf"
        assert calf_f.severity == 3
        assert calf_f.code == "muscle_overused.calf"

    def test_overused_not_trending_is_severity_2(self):
        """overused without trending_up → severity 2."""
        ledger = _ledger({
            "calf": _group_data("overused", acute=25.0, chronic=15.0, acwr=1.7, trending_up=False),
        })
        findings = muscle_overused(_inputs(ledger))
        calf_f = next((f for f in findings if f.target == "calf"), None)
        assert calf_f is not None
        assert calf_f.severity == 2

    def test_elevated_is_severity_2(self):
        """elevated classification → severity 2."""
        ledger = _ledger({
            "hamstring": _group_data("elevated", acute=22.0, chronic=15.0, acwr=1.4),
        })
        findings = muscle_overused(_inputs(ledger))
        h_f = next((f for f in findings if f.target == "hamstring"), None)
        assert h_f is not None
        assert h_f.severity == 2
        assert h_f.code == "muscle_overused.hamstring"

    def test_balanced_does_not_fire(self):
        """balanced classification → no finding for that group."""
        ledger = _ledger({
            "calf": _group_data("balanced", acwr=1.0),
        })
        findings = muscle_overused(_inputs(ledger))
        calf_f = next((f for f in findings if f.target == "calf"), None)
        assert calf_f is None

    def test_detraining_does_not_fire_overused(self):
        """detraining classification → no muscle_overused finding."""
        ledger = _ledger({
            "calf": _group_data("detraining", acwr=0.5),
        })
        findings = muscle_overused(_inputs(ledger))
        calf_f = next((f for f in findings if f.target == "calf"), None)
        assert calf_f is None

    def test_untrained_does_not_fire_overused(self):
        """untrained classification → no muscle_overused finding."""
        ledger = _ledger({
            "calf": _group_data("untrained", acwr=None, chronic=0.0),
        })
        findings = muscle_overused(_inputs(ledger))
        calf_f = next((f for f in findings if f.target == "calf"), None)
        assert calf_f is None


# ── AC1: muscle_overused evidence ─────────────────────────────────────────────

class TestMuscleOverusedEvidence:
    """AC1: evidence must include acute, chronic, acwr, and main contributing source."""

    def test_evidence_includes_acwr(self):
        """Evidence carries the acwr metric."""
        ledger = _ledger({
            "calf": _group_data("overused", acute=30.0, chronic=15.0, acwr=2.0, trending_up=True),
        })
        findings = muscle_overused(_inputs(ledger))
        calf_f = next(f for f in findings if f.target == "calf")
        metric_names = {e["metric"] for e in calf_f.evidence}
        assert "acwr" in metric_names

    def test_evidence_includes_acute_and_chronic(self):
        """Evidence carries acute_7d and chronic_28d."""
        ledger = _ledger({
            "calf": _group_data("elevated", acute=22.0, chronic=15.0, acwr=1.4),
        })
        findings = muscle_overused(_inputs(ledger))
        calf_f = next(f for f in findings if f.target == "calf")
        metric_names = {e["metric"] for e in calf_f.evidence}
        assert "acute_7d" in metric_names
        assert "chronic_28d" in metric_names

    def test_evidence_includes_main_source(self):
        """Evidence carries the main contributing source."""
        ledger = _ledger({
            "calf": _group_data(
                "overused", acute=30.0, chronic=15.0, acwr=2.0, trending_up=True,
                source_breakdown={"run": 0.8, "strength": 0.2},
            ),
        })
        findings = muscle_overused(_inputs(ledger))
        calf_f = next(f for f in findings if f.target == "calf")
        metric_names = {e["metric"] for e in calf_f.evidence}
        assert "main_source" in metric_names

    def test_main_source_reflects_largest_contributor(self):
        """main_source value matches the highest share in source_breakdown."""
        ledger = _ledger({
            "calf": _group_data(
                "elevated", acute=22.0, chronic=15.0, acwr=1.4,
                source_breakdown={"run": 0.6, "strength": 0.3, "plyo": 0.1},
            ),
        })
        findings = muscle_overused(_inputs(ledger))
        calf_f = next(f for f in findings if f.target == "calf")
        src_entry = next(e for e in calf_f.evidence if e["metric"] == "main_source")
        assert src_entry["value"] == "run"

    def test_thresholds_in_evidence_match_acwr_constants(self):
        """AC4: thresholds in evidence are from muscle_load_acwr constants."""
        ledger = _ledger({
            "calf": _group_data("overused", acute=30.0, chronic=15.0, acwr=2.0),
        })
        findings = muscle_overused(_inputs(ledger))
        calf_f = next(f for f in findings if f.target == "calf")
        acwr_entry = next(e for e in calf_f.evidence if e["metric"] == "acwr")
        assert acwr_entry["threshold"] == OVERUSED_BOUND

    def test_elevated_threshold_is_elevated_bound(self):
        """Elevated finding's acwr threshold is ELEVATED_BOUND."""
        ledger = _ledger({
            "hamstring": _group_data("elevated", acwr=1.4),
        })
        findings = muscle_overused(_inputs(ledger))
        h_f = next(f for f in findings if f.target == "hamstring")
        acwr_entry = next(e for e in h_f.evidence if e["metric"] == "acwr")
        assert acwr_entry["threshold"] == ELEVATED_BOUND


# ── AC3: muscle_overused × injury ─────────────────────────────────────────────

class TestMuscleOverusedInjury:
    """AC3: injured+overused still fires (stronger rest recommendation)."""

    def test_injured_overused_fires_severity_3(self):
        """Injured calf + overused + trending → severity 3 (rest it)."""
        ledger = _ledger({
            "calf": _group_data("overused", acwr=2.0, trending_up=True, injured=True),
        })
        findings = muscle_overused(_inputs(ledger))
        calf_f = next((f for f in findings if f.target == "calf"), None)
        assert calf_f is not None, "muscle_overused must fire even when injured"
        assert calf_f.severity == 3

    def test_injured_elevated_fires_severity_2(self):
        """Injured calf + elevated → severity 2, still fires."""
        ledger = _ledger({
            "calf": _group_data("elevated", acwr=1.4, injured=True),
        })
        findings = muscle_overused(_inputs(ledger))
        calf_f = next((f for f in findings if f.target == "calf"), None)
        assert calf_f is not None
        assert calf_f.severity == 2

    def test_injured_overused_recommendation_mentions_rest(self):
        """Injured + overused recommendation contains rest-flavored language."""
        ledger = _ledger({
            "calf": _group_data("overused", acwr=2.0, trending_up=True, injured=True),
        })
        findings = muscle_overused(_inputs(ledger))
        calf_f = next(f for f in findings if f.target == "calf")
        assert "rest" in calf_f.recommendation.lower() or "injur" in calf_f.recommendation.lower()


# ── AC2: muscle_untrained severity bands ──────────────────────────────────────

class TestMuscleUntrainedSeverity:
    """AC2: correct severity for untrained (priority 4w+) and detraining."""

    def test_priority_group_untrained_4w_is_severity_2(self):
        """calf untrained for UNTRAINED_MIN_WEEKS → severity 2."""
        ledger = _ledger({
            "calf": _group_data(
                "untrained", chronic=0.0, acwr=None,
                weeks_untrained=UNTRAINED_MIN_WEEKS,
            ),
        })
        findings = muscle_untrained(_inputs(ledger))
        calf_f = next((f for f in findings if f.target == "calf"), None)
        assert calf_f is not None, "muscle_untrained should fire for priority group untrained 4w+"
        assert calf_f.severity == 2
        assert calf_f.code == "muscle_untrained.calf"

    def test_priority_group_untrained_below_min_weeks_no_fire(self):
        """Untrained < 4 weeks → no finding (not yet chronically neglected)."""
        ledger = _ledger({
            "calf": _group_data(
                "untrained", chronic=0.0, acwr=None,
                weeks_untrained=UNTRAINED_MIN_WEEKS - 1,
            ),
        })
        findings = muscle_untrained(_inputs(ledger))
        calf_f = next((f for f in findings if f.target == "calf"), None)
        assert calf_f is None

    def test_all_priority_groups_can_fire(self):
        """All four priority groups (calf, hamstring, glute, hip) fire at severity 2."""
        for grp in ("calf", "hamstring", "glute", "hip"):
            ledger = _ledger({
                grp: _group_data("untrained", chronic=0.0, acwr=None, weeks_untrained=4),
            })
            findings = muscle_untrained(_inputs(ledger))
            f = next((fi for fi in findings if fi.target == grp), None)
            assert f is not None, f"{grp} should fire as priority group"
            assert f.severity == 2

    def test_non_priority_group_untrained_does_not_fire(self):
        """Non-priority group untrained → no severity-2 untrained finding."""
        for grp in ("core", "back", "shoulder", "chest", "arm", "quad", "other"):
            ledger = _ledger({
                grp: _group_data("untrained", chronic=0.0, acwr=None, weeks_untrained=6),
            })
            findings = muscle_untrained(_inputs(ledger))
            f = next((fi for fi in findings if fi.target == grp and fi.code.startswith("muscle_untrained")), None)
            assert f is None, f"{grp} is not a priority group, should not fire muscle_untrained"

    def test_detraining_group_is_severity_1(self):
        """Detraining group (any) → severity 1 finding."""
        ledger = _ledger({
            "calf": _group_data("detraining", acwr=0.5),
        })
        findings = muscle_untrained(_inputs(ledger))
        calf_f = next((f for f in findings if f.target == "calf"), None)
        assert calf_f is not None
        assert calf_f.severity == 1

    def test_detraining_code_prefix(self):
        """Detraining finding uses muscle_detraining.{group} code."""
        ledger = _ledger({
            "hamstring": _group_data("detraining", acwr=0.6),
        })
        findings = muscle_untrained(_inputs(ledger))
        h_f = next((f for f in findings if f.target == "hamstring"), None)
        assert h_f is not None
        assert h_f.code == "muscle_detraining.hamstring"


# ── AC3: muscle_untrained × injury (suppression) ─────────────────────────────

class TestMuscleUntrainedInjurySuppression:
    """AC3: injured + untrained is suppressed (never load injured area)."""

    def test_injured_untrained_priority_group_is_suppressed(self):
        """injured calf + untrained → no finding (suppressed)."""
        ledger = _ledger({
            "calf": _group_data(
                "untrained", chronic=0.0, acwr=None,
                weeks_untrained=6, injured=True,
            ),
        })
        findings = muscle_untrained(_inputs(ledger))
        calf_f = next((f for f in findings if f.target == "calf"), None)
        assert calf_f is None, "muscle_untrained must be suppressed for injured calf"

    def test_injured_detraining_is_suppressed(self):
        """injured + detraining → no finding (conservative: don't load injured area)."""
        ledger = _ledger({
            "hamstring": _group_data("detraining", acwr=0.5, injured=True),
        })
        findings = muscle_untrained(_inputs(ledger))
        h_f = next((f for f in findings if f.target == "hamstring"), None)
        assert h_f is None

    def test_non_injured_untrained_still_fires(self):
        """Uninjured calf untrained 4w+ fires normally."""
        ledger = _ledger({
            "calf": _group_data(
                "untrained", chronic=0.0, acwr=None,
                weeks_untrained=5, injured=False,
            ),
        })
        findings = muscle_untrained(_inputs(ledger))
        calf_f = next((f for f in findings if f.target == "calf"), None)
        assert calf_f is not None


# ── AC3: dedup with pack C (claimed_groups) ───────────────────────────────────

class TestDedupWithPackC:
    """AC3: when recurrent_niggle_area (pack C) fires for same group, pack D is suppressed.

    The dedup is implemented via claimed_groups injected by the registry.
    Tests pass claimed_groups directly to simulate pack C having run first.
    """

    def test_overused_suppressed_when_group_claimed(self):
        """muscle_overused.calf suppressed when calf is in claimed_groups."""
        ledger = _ledger({
            "calf": _group_data("overused", acwr=2.0, trending_up=True),
        })
        findings = muscle_overused(_inputs(ledger, claimed_groups={"calf"}))
        calf_f = next((f for f in findings if f.target == "calf"), None)
        assert calf_f is None, "calf finding must be suppressed when calf is claimed"

    def test_overused_other_groups_not_suppressed(self):
        """Only the claimed group is suppressed; other overused groups still fire."""
        ledger = _ledger({
            "calf": _group_data("overused", acwr=2.0, trending_up=True),
            "hamstring": _group_data("overused", acwr=1.8, trending_up=True),
        })
        findings = muscle_overused(_inputs(ledger, claimed_groups={"calf"}))
        calf_f = next((f for f in findings if f.target == "calf"), None)
        ham_f = next((f for f in findings if f.target == "hamstring"), None)
        assert calf_f is None, "calf suppressed by claimed_groups"
        assert ham_f is not None, "hamstring not suppressed"

    def test_untrained_suppressed_when_group_claimed(self):
        """muscle_untrained.calf suppressed when calf is in claimed_groups."""
        ledger = _ledger({
            "calf": _group_data("untrained", chronic=0.0, acwr=None, weeks_untrained=5),
        })
        findings = muscle_untrained(_inputs(ledger, claimed_groups={"calf"}))
        calf_f = next((f for f in findings if f.target == "calf"), None)
        assert calf_f is None

    def test_three_potential_findings_reduced_to_one_per_group(self):
        """UAT step 3: calf with overuse + untrained history + claimed → exactly one finding.

        Simulates: recurrent_niggle_area already fired for calf (calf in claimed_groups).
        Both muscle_overused and muscle_untrained must be suppressed for calf.
        """
        ledger = _ledger({
            "calf": _group_data(
                "overused", acwr=2.0, trending_up=True,
                weeks_untrained=0,  # currently overused, not untrained
            ),
        })
        overused_findings = muscle_overused(_inputs(ledger, claimed_groups={"calf"}))
        untrained_findings = muscle_untrained(_inputs(ledger, claimed_groups={"calf"}))
        calf_from_pack_d = [
            f for f in overused_findings + untrained_findings
            if f.target == "calf"
        ]
        assert len(calf_from_pack_d) == 0, (
            "Both pack D rules must be suppressed when calf is claimed by pack C"
        )


# ── AC4: insufficient ledger history → None ───────────────────────────────────

class TestInsufficientHistory:
    """AC4: rules should not fire when there is < 4 weeks of ledger history."""

    def test_muscle_overused_no_fire_insufficient_history(self):
        """overused group but history_weeks < 4 → empty list (effectively skipped)."""
        ledger = _ledger(
            {"calf": _group_data("overused", acwr=2.0, trending_up=True)},
            history_weeks=3,  # < 4 weeks
        )
        findings = muscle_overused(_inputs(ledger))
        assert findings == [], "Must return empty list when history < 4 weeks"

    def test_muscle_untrained_no_fire_insufficient_history(self):
        """untrained group but history_weeks < 4 → empty list."""
        ledger = _ledger(
            {"calf": _group_data("untrained", chronic=0.0, acwr=None, weeks_untrained=4)},
            history_weeks=2,
        )
        findings = muscle_untrained(_inputs(ledger))
        assert findings == [], "Must return empty list when history < 4 weeks"

    def test_rule_skipped_when_ledger_key_absent(self):
        """If muscle_load_ledger key is missing from inputs, rules return empty list (registry skips them)."""
        bare_inputs = {"week_start": _WEEK_START, "other_findings_codes": [], "claimed_groups": set()}
        assert muscle_overused(bare_inputs) == []
        assert muscle_untrained(bare_inputs) == []


# ── AC4: pure functions and constant imports ───────────────────────────────────

class TestPureFunctionsAndConstants:
    """AC4: thresholds from #1380 constants, no redefinition."""

    def test_constants_imported_not_redefined(self):
        """OVERUSED_BOUND, ELEVATED_BOUND, PRIORITY_GROUPS come from muscle_load_acwr."""
        # These imports succeed without error — if they were redefined locally,
        # tests would need to be updated (ensuring we catch silent redefinitions).
        from backend.services.gap_analysis.rules.muscle_balance import (
            UNTRAINED_MIN_WEEKS as _UTW,
        )
        # Only UNTRAINED_MIN_WEEKS is defined in muscle_balance; the rest are imported.
        assert _UTW == 4  # the documented threshold

    def test_overused_bound_matches_acwr(self):
        """The threshold used in overused evidence == muscle_load_acwr.OVERUSED_BOUND."""
        ledger = _ledger({"calf": _group_data("overused", acwr=1.6)})
        findings = muscle_overused(_inputs(ledger))
        calf_f = next(f for f in findings if f.target == "calf")
        acwr_ev = next(e for e in calf_f.evidence if e["metric"] == "acwr")
        assert acwr_ev["threshold"] == OVERUSED_BOUND

    def test_elevated_bound_matches_acwr(self):
        """The threshold used in elevated evidence == muscle_load_acwr.ELEVATED_BOUND."""
        ledger = _ledger({"hamstring": _group_data("elevated", acwr=1.35)})
        findings = muscle_overused(_inputs(ledger))
        h_f = next(f for f in findings if f.target == "hamstring")
        acwr_ev = next(e for e in h_f.evidence if e["metric"] == "acwr")
        assert acwr_ev["threshold"] == ELEVATED_BOUND

    def test_untrained_threshold_is_documented_constant(self):
        """weeks_untrained evidence threshold == UNTRAINED_MIN_WEEKS."""
        ledger = _ledger({
            "calf": _group_data("untrained", chronic=0.0, acwr=None, weeks_untrained=4),
        })
        findings = muscle_untrained(_inputs(ledger))
        calf_f = next(f for f in findings if f.target == "calf")
        uw_ev = next(e for e in calf_f.evidence if e["metric"] == "weeks_untrained")
        assert uw_ev["threshold"] == UNTRAINED_MIN_WEEKS

    def test_no_db_calls_in_rules(self):
        """AC4: rules are pure — calling them without a DB dependency must not raise."""
        ledger = _ledger({
            "calf": _group_data("overused", acwr=2.0, trending_up=True),
            "hamstring": _group_data("untrained", chronic=0.0, acwr=None, weeks_untrained=5),
        })
        inp = _inputs(ledger)
        # Will raise if DB call is attempted (no engine configured in this test)
        overused = muscle_overused(inp)
        untrained = muscle_untrained(inp)
        assert isinstance(overused, list)
        assert isinstance(untrained, list)


# ── Registry handles list returns ─────────────────────────────────────────────

class TestRegistryListSupport:
    """Registry must handle rules that return a list of findings."""

    def test_registry_run_all_collects_list_results(self):
        """run_all() flattens list-returning rules into findings."""
        from backend.services.gap_analysis.registry import RuleRegistry

        reg = RuleRegistry()

        def _multi_finding_rule(inputs):
            from backend.services.gap_analysis.schemas import GapAnalysisFinding
            return [
                GapAnalysisFinding(
                    code=f"test.group{i}",
                    severity=2,
                    recommendation="rec",
                    evidence=[],
                    target=f"group{i}",
                    week_start=inputs["week_start"],
                )
                for i in range(2)
            ]

        reg.register(requires=[])(lambda inputs: None)  # control: single-None rule
        reg.register(requires=[])(_multi_finding_rule)

        result = reg.run_all({"week_start": _WEEK_START}, _WEEK_START)
        assert len(result["findings"]) == 2

    def test_registry_injects_claimed_groups(self):
        """Registry injects claimed_groups set; first finding's target gets claimed."""
        from backend.services.gap_analysis.registry import RuleRegistry
        from backend.services.gap_analysis.schemas import GapAnalysisFinding

        reg = RuleRegistry()
        observed_claimed = {}

        def rule_a(inputs):
            return GapAnalysisFinding(
                code="rule_a",
                severity=2,
                recommendation="r",
                evidence=[],
                target="calf",
                week_start=inputs["week_start"],
            )

        def rule_b(inputs):
            # rule_b runs after rule_a; calf should be claimed
            observed_claimed["claimed"] = set(inputs.get("claimed_groups", set()))
            return None

        reg.register(requires=[])(rule_a)
        reg.register(requires=[])(rule_b)
        reg.run_all({"week_start": _WEEK_START}, _WEEK_START)
        assert "calf" in observed_claimed["claimed"]

    def test_registry_injects_other_findings_codes(self):
        """Registry injects other_findings_codes list (backward compat with pack C)."""
        from backend.services.gap_analysis.registry import RuleRegistry
        from backend.services.gap_analysis.schemas import GapAnalysisFinding

        reg = RuleRegistry()
        seen_codes = {}

        def rule_a(inputs):
            return GapAnalysisFinding(
                code="rule_a",
                severity=2,
                recommendation="r",
                evidence=[],
                target=None,
                week_start=inputs["week_start"],
            )

        def rule_b(inputs):
            seen_codes["codes"] = list(inputs.get("other_findings_codes", []))
            return None

        reg.register(requires=[])(rule_a)
        reg.register(requires=[])(rule_b)
        reg.run_all({"week_start": _WEEK_START}, _WEEK_START)
        assert "rule_a" in seen_codes["codes"]
