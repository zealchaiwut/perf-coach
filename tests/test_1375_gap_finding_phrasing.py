"""Tests for issue #1375: LLM coach phrasing for gap findings.

AC coverage:
- AC1: Per-finding phrasing via Groq client; numeral guard discards bad output.
- AC2: Cached in llm_generations (surface="gap_finding"); regen only on evidence change.
- AC3: LLM disabled/failed/guard-tripped → deterministic template; phrasing_source field present.
- AC4: LLM schema is single text field only (no severity/recommendation/target).
- AC5: Mocked LLM shape + guard, cache hit/regen on evidence change, fallback path.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from unittest.mock import MagicMock, patch


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_finding(code="no_recent_plyo", severity=2, recommendation="Add plyometrics.",
                  evidence=None, target=None):
    return {
        "code": code,
        "severity": severity,
        "recommendation": recommendation,
        "evidence": evidence or [{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}],
        "target": target,
    }


def _sig(user_id, week_start, code, evidence):
    """Mirror the signature function from phrasing module."""
    canonical = json.dumps(
        {"user": str(user_id), "week": str(week_start), "code": code, "evidence": evidence},
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:64]


# ── AC1: Phrasing via LLM; numeral guard ─────────────────────────────────────

class TestLLMPhrasing:
    """AC1: LLM produces phrasing; numbers in output must match input facts."""






# ── AC2: Caching ──────────────────────────────────────────────────────────────

class TestCaching:
    """AC2: Cached under surface='gap_finding'; signature over user+week+code+evidence."""

    def test_build_phrasing_signature_deterministic(self):
        """Same inputs always produce the same signature."""
        from backend.services.gap_analysis.phrasing import build_phrasing_signature

        uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
        evidence = [{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}]

        sig1 = build_phrasing_signature(uid, "2026-07-07", "no_recent_plyo", evidence)
        sig2 = build_phrasing_signature(uid, "2026-07-07", "no_recent_plyo", evidence)
        assert sig1 == sig2

    def test_build_phrasing_signature_changes_on_evidence(self):
        """Different evidence values produce different signatures."""
        from backend.services.gap_analysis.phrasing import build_phrasing_signature

        uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
        ev1 = [{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}]
        ev2 = [{"metric": "days_since_plyo", "value": 40, "threshold": 28, "window": "28d"}]  # changed

        sig1 = build_phrasing_signature(uid, "2026-07-07", "no_recent_plyo", ev1)
        sig2 = build_phrasing_signature(uid, "2026-07-07", "no_recent_plyo", ev2)
        assert sig1 != sig2

    def test_build_phrasing_signature_changes_on_week(self):
        """Different week_start produces a different signature."""
        from backend.services.gap_analysis.phrasing import build_phrasing_signature

        uid = uuid.UUID("00000000-0000-0000-0000-000000000001")
        ev = [{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}]

        sig1 = build_phrasing_signature(uid, "2026-07-07", "no_recent_plyo", ev)
        sig2 = build_phrasing_signature(uid, "2026-07-14", "no_recent_plyo", ev)
        assert sig1 != sig2



    def test_evidence_change_produces_different_signature(self):
        """Evidence value change means a different cache key (new generate call)."""
        from backend.services.gap_analysis.phrasing import build_phrasing_signature

        uid = uuid.uuid4()
        week = "2026-07-07"
        code = "no_recent_plyo"

        ev_old = [{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}]
        ev_new = [{"metric": "days_since_plyo", "value": 42, "threshold": 28, "window": "28d"}]

        assert build_phrasing_signature(uid, week, code, ev_old) != \
               build_phrasing_signature(uid, week, code, ev_new)


# ── AC3: Fallback paths ───────────────────────────────────────────────────────

class TestFallbackPaths:
    """AC3: LLM disabled/failed/guard-tripped → template fallback; phrasing_source present."""

    def test_llm_disabled_returns_template(self):
        """When LLM is disabled, phrasing_source='template' and text is deterministic."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding(
            code="no_recent_plyo",
            evidence=[{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}],
        )

        with patch("backend.services.llm.llm_enabled", return_value=False):
            result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert result["phrasing_source"] == "template"
        assert "35" in result["phrasing"]
        assert isinstance(result["phrasing"], str)
        assert len(result["phrasing"]) > 0






# ── AC4: Schema enforces single text field only ───────────────────────────────

class TestSchemaShape:
    """AC4: LLM JSON schema has only 'phrasing' — no severity/recommendation/target."""

    def test_phrasing_json_schema_shape(self):
        """The LLM schema exported from phrasing module has only 'phrasing' property."""
        from backend.services.gap_analysis.phrasing import _PHRASING_JSON_SCHEMA

        props = _PHRASING_JSON_SCHEMA.get("properties", {})
        assert "phrasing" in props
        assert "severity" not in props
        assert "recommendation" not in props
        assert "target" not in props
        assert _PHRASING_JSON_SCHEMA.get("additionalProperties") is False

    def test_phrasing_json_schema_required(self):
        """The phrasing field is required in the schema."""
        from backend.services.gap_analysis.phrasing import _PHRASING_JSON_SCHEMA

        assert "phrasing" in _PHRASING_JSON_SCHEMA.get("required", [])



# ── AC5 (also integration): API field shape both paths ────────────────────────

class TestAPIFieldShape:
    """API response findings include phrasing + phrasing_source on both paths."""


    def test_enrich_findings_with_phrasing_template_path(self):
        """enrich_finding_with_phrasing adds both fields when LLM is off."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding(
            code="strength_lapsed",
            evidence=[{"metric": "days_since_strength", "value": 28, "threshold": 21, "window": "21d"}],
        )

        with patch("backend.services.llm.llm_enabled", return_value=False):
            result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert "phrasing" in result
        assert "phrasing_source" in result
        assert result["phrasing_source"] == "template"
        assert "28" in result["phrasing"] or "strength" in result["phrasing"].lower()

    def test_phrasing_source_is_string_literal(self):
        """phrasing_source is exactly 'llm' or 'template' (never None or other)."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding()

        with patch("backend.services.llm.llm_enabled", return_value=False):
            r = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")
        assert r["phrasing_source"] in ("llm", "template")

        with patch("backend.services.llm.llm_enabled", return_value=True), \
             patch("backend.services.llm.get_or_generate", return_value={"phrasing": "No plyo in 35 days."}):
            r = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")
        assert r["phrasing_source"] in ("llm", "template")


# ── Priority 2, step 6: the LLM phrasing path is parked ───────────────────────
#
# Issue #1375 built an LLM one-liner for each gap finding, with a numeral guard,
# a length cap, a cache and a template fallback for every failure mode. All of
# it worked. It is parked anyway: the template path already covered every case,
# so the LLM was buying a nicer sentence for the same information on a surface
# the athlete reads in passing — and it put a provider call behind a findings
# list. See docs/features/consolidation.md.
#
# The tests that asserted `phrasing_source == "llm"` and exercised the guard,
# cap, cache and empty-output fallbacks went with it — every one of those paths
# is now unreachable, so they were asserting dead code. These replace them: they
# pin that the LLM stays unconsulted.

class TestLLMPathParked:
    def test_llm_is_not_consulted_even_when_enabled(self):
        """Enabled provider, valid response, and it still returns the template.

        This is the actual park. If someone restores the `if not
        llm.llm_enabled()` early-return, this is what fails."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding(
            code="no_recent_plyo",
            evidence=[{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}],
        )
        llm_text = "You haven't done plyometrics in 35 days — aim for one session every 28 days."

        with patch("backend.services.llm.llm_enabled", return_value=True) as mock_enabled, \
             patch("backend.services.llm.get_or_generate", return_value={"phrasing": llm_text}) as mock_gen:
            result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert result["phrasing_source"] == "template"
        assert result["phrasing"] != llm_text
        mock_gen.assert_not_called()
        mock_enabled.assert_not_called()

    def test_field_shape_is_unchanged_by_the_park(self):
        """Callers still get the same two keys — main.py reads both."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding(
            evidence=[{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}],
        )
        result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert set(result.keys()) == {"phrasing", "phrasing_source"}
        assert isinstance(result["phrasing"], str) and result["phrasing"]
        assert result["phrasing_source"] == "template"

    def test_phrasing_matches_the_deterministic_evidence_text(self):
        """The template path is render_evidence_text — no second renderer."""
        from backend.services.gap_analysis.evidence_text import render_evidence_text
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        evidence = [{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}]
        finding = _make_finding(code="no_recent_plyo", evidence=evidence)

        result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")
        assert result["phrasing"] == render_evidence_text(
            "no_recent_plyo", evidence, finding.get("target")
        )
