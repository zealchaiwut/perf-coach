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

    def test_llm_response_accepted_when_numbers_match(self):
        """Valid LLM response (numerals all from facts) is accepted."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding(
            code="no_recent_plyo",
            evidence=[{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}],
        )
        llm_text = "You haven't done plyometrics in 35 days — aim for one session every 28 days."

        with patch("backend.services.llm.llm_enabled", return_value=True), \
             patch("backend.services.llm.get_or_generate", return_value={"phrasing": llm_text}):
            result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert result["phrasing"] == llm_text
        assert result["phrasing_source"] == "llm"

    def test_numeral_guard_rejects_hallucinated_numbers(self):
        """LLM output with numbers not in input facts → fallback to template."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding(
            code="no_recent_plyo",
            evidence=[{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}],
        )
        # "42" is not in the evidence facts (35, 28 are)
        bad_llm_text = "You haven't trained plyometrics in 42 days."

        with patch("backend.services.llm.llm_enabled", return_value=True), \
             patch("backend.services.llm.get_or_generate", return_value={"phrasing": bad_llm_text}):
            result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        # Numeral guard should trip → fallback
        assert result["phrasing_source"] == "template"
        assert "35" in result["phrasing"] or "plyo" in result["phrasing"].lower()

    def test_numeral_guard_allows_all_input_numbers(self):
        """LLM output whose numbers are a subset of input facts passes the guard."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding(
            code="gct_lengthening",
            evidence=[
                {"metric": "gct_recent_mean_ms", "value": 248, "threshold": None, "window": "28d"},
                {"metric": "gct_prior_mean_ms", "value": 241, "threshold": None, "window": "28d_prior"},
                {"metric": "gct_rise_ms", "value": 7, "threshold": 5, "window": "28d_vs_prior_28d"},
            ],
        )
        # 248, 241, 7 all appear in evidence
        llm_text = "Your ground contact time is now 248 ms, up 7 ms from your prior baseline of 241 ms."

        with patch("backend.services.llm.llm_enabled", return_value=True), \
             patch("backend.services.llm.get_or_generate", return_value={"phrasing": llm_text}):
            result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert result["phrasing_source"] == "llm"
        assert result["phrasing"] == llm_text

    def test_phrasing_length_capped(self):
        """LLM output exceeding max length → fallback to template."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding()
        long_text = "A" * 600  # over any reasonable cap

        with patch("backend.services.llm.llm_enabled", return_value=True), \
             patch("backend.services.llm.get_or_generate", return_value={"phrasing": long_text}):
            result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert result["phrasing_source"] == "template"


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

    def test_get_or_generate_called_with_gap_finding_surface(self):
        """get_or_generate is invoked with surface='gap_finding'."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding()
        captured: list[dict] = []

        def fake_get_or_generate(user_id, surface, signature, generate_fn, *, db=None, model_tier="fast"):
            captured.append({"user_id": user_id, "surface": surface, "signature": signature})
            return {"phrasing": "No plyometrics in 35 days — add one session per 28 days."}

        with patch("backend.services.llm.llm_enabled", return_value=True), \
             patch("backend.services.llm.get_or_generate", side_effect=fake_get_or_generate):
            get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert len(captured) == 1
        assert captured[0]["surface"] == "gap_finding"

    def test_cache_hit_returns_same_text(self):
        """When get_or_generate returns cached payload, same phrasing is returned."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        cached_text = "Cached coach sentence about 35 days of no plyo."
        finding = _make_finding(
            evidence=[{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}],
        )

        with patch("backend.services.llm.llm_enabled", return_value=True), \
             patch("backend.services.llm.get_or_generate", return_value={"phrasing": cached_text}):
            r1 = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert r1["phrasing"] == cached_text
        assert r1["phrasing_source"] == "llm"

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

    def test_llm_returns_none_fallback_to_template(self):
        """When LLM call returns None (network failure etc.), use template."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding(
            evidence=[{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}],
        )

        with patch("backend.services.llm.llm_enabled", return_value=True), \
             patch("backend.services.llm.get_or_generate", return_value=None):
            result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert result["phrasing_source"] == "template"
        assert isinstance(result["phrasing"], str)
        assert len(result["phrasing"]) > 0

    def test_both_paths_have_identical_field_shape(self):
        """Both LLM and template paths return same dict shape."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding(
            evidence=[{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}],
        )
        uid = uuid.uuid4()

        with patch("backend.services.llm.llm_enabled", return_value=False):
            template_result = get_finding_phrasing(finding, user_id=uid, week_start="2026-07-07")

        with patch("backend.services.llm.llm_enabled", return_value=True), \
             patch("backend.services.llm.get_or_generate", return_value={
                 "phrasing": "No plyometrics in 35 days — aim for one every 28 days."
             }):
            llm_result = get_finding_phrasing(finding, user_id=uid, week_start="2026-07-07")

        assert set(template_result.keys()) == {"phrasing", "phrasing_source"}
        assert set(llm_result.keys()) == {"phrasing", "phrasing_source"}
        assert template_result["phrasing_source"] == "template"
        assert llm_result["phrasing_source"] == "llm"

    def test_empty_phrasing_from_llm_falls_back(self):
        """Empty string from LLM → fallback to template."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding()

        with patch("backend.services.llm.llm_enabled", return_value=True), \
             patch("backend.services.llm.get_or_generate", return_value={"phrasing": ""}):
            result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert result["phrasing_source"] == "template"
        assert len(result["phrasing"]) > 0

    def test_guard_trip_uses_template_text(self):
        """Guard-tripped phrasing falls back to render_evidence_text output."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing
        from backend.services.gap_analysis.evidence_text import render_evidence_text

        evidence = [{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}]
        finding = _make_finding(code="no_recent_plyo", evidence=evidence)

        # LLM returns number not in facts
        with patch("backend.services.llm.llm_enabled", return_value=True), \
             patch("backend.services.llm.get_or_generate", return_value={"phrasing": "99 days gone"}):
            result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        expected = render_evidence_text("no_recent_plyo", evidence, None)
        assert result["phrasing"] == expected
        assert result["phrasing_source"] == "template"


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

    def test_complete_structured_called_with_phrasing_schema(self):
        """complete_structured is invoked with the single-field schema."""
        import backend.services.llm as llm_mod
        from backend.services.gap_analysis.phrasing import _PHRASING_JSON_SCHEMA

        finding = _make_finding(
            evidence=[{"metric": "days_since_plyo", "value": 35, "threshold": 28, "window": "28d"}],
        )
        captured_schemas: list[dict] = []

        original_complete = llm_mod.complete_structured

        def capturing_complete(system, user, schema_name, json_schema, **kwargs):
            captured_schemas.append(json_schema)
            return {"phrasing": "No plyo in 35 days — target 28-day cycle."}

        def fake_get_or_generate(user_id, surface, signature, generate_fn, **kw):
            return generate_fn()

        with patch("backend.services.llm.llm_enabled", return_value=True), \
             patch.object(llm_mod, "complete_structured", side_effect=capturing_complete), \
             patch("backend.services.llm.get_or_generate", side_effect=fake_get_or_generate):
            from backend.services.gap_analysis.phrasing import get_finding_phrasing
            get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert len(captured_schemas) == 1
        schema = captured_schemas[0]
        props = schema.get("properties", {})
        assert list(props.keys()) == ["phrasing"]
        assert schema.get("additionalProperties") is False


# ── AC5 (also integration): API field shape both paths ────────────────────────

class TestAPIFieldShape:
    """API response findings include phrasing + phrasing_source on both paths."""

    def test_enrich_findings_with_phrasing_llm_path(self):
        """enrich_finding_with_phrasing adds both fields when LLM succeeds."""
        from backend.services.gap_analysis.phrasing import get_finding_phrasing

        finding = _make_finding(
            code="strength_lapsed",
            evidence=[{"metric": "days_since_strength", "value": 28, "threshold": 21, "window": "21d"}],
        )
        llm_text = "Your last strength session was 28 days ago — aim for one every 21 days."

        with patch("backend.services.llm.llm_enabled", return_value=True), \
             patch("backend.services.llm.get_or_generate", return_value={"phrasing": llm_text}):
            result = get_finding_phrasing(finding, user_id=uuid.uuid4(), week_start="2026-07-07")

        assert result["phrasing"] == llm_text
        assert result["phrasing_source"] == "llm"

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
