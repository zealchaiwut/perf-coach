"""LLM coach phrasing for gap findings (issue #1375).

Exposes:
  build_phrasing_signature(user_id, week_start, code, evidence) → str
  get_finding_phrasing(finding, user_id, week_start, db=None) → {"phrasing": str, "phrasing_source": "llm"|"template"}

LLM path: Groq structured call, JSON-schema output (single phrasing field),
length-capped, numeral guard.  Any failure falls back to render_evidence_text.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import backend.services.llm as llm
from backend.utils.log import get_logger

_log = get_logger(__name__)

_MAX_PHRASING_LEN = 500

_PHRASING_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "phrasing": {"type": "string"},
    },
    "required": ["phrasing"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You are a performance coach writing brief, direct improvement cues for a runner. "
    "Rules: 1-2 sentences, max 400 characters, supportive tone, no emoji, no exclamation marks, "
    "no medical advice. Use ONLY the numbers supplied in the data — do not invent or modify any value. "
    "Rephrase the finding in coach voice; do NOT change severity, target, or recommendation meaning."
)


# ── Numeral guard (mirrors readiness_explanation) ─────────────────────────────

def _numeral_guard_passes(text: str, facts_str: str) -> bool:
    """Return True iff every number in text appears verbatim in facts_str."""
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    return all(n in facts_str for n in nums)


def _evidence_to_facts_str(evidence: list[dict[str, Any]]) -> str:
    """Flatten evidence list values to a string for numeral validation."""
    parts: list[str] = []
    for e in evidence:
        v = e.get("value")
        t = e.get("threshold")
        if v is not None:
            parts.append(str(v))
        if t is not None:
            parts.append(str(t))
    return " ".join(parts)


# ── Cache signature ───────────────────────────────────────────────────────────

def build_phrasing_signature(user_id, week_start, code: str, evidence: list[dict]) -> str:
    """SHA-256 over user+week+code+evidence — cache key for llm_generations."""
    canonical = json.dumps(
        {"user": str(user_id), "week": str(week_start), "code": code, "evidence": evidence},
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:64]


# ── Main public function ──────────────────────────────────────────────────────

def get_finding_phrasing(
    finding: dict[str, Any],
    *,
    user_id,
    week_start,
    db=None,
) -> dict[str, str]:
    """Return {"phrasing": str, "phrasing_source": "template"}.

    PARKED (Priority 2, step 6). This used to try an LLM one-liner first and
    fall back to deterministic evidence_text on any failure — disabled provider,
    network error, numeral-guard trip, length cap, empty output. The template
    path already covered every one of those cases, which is the argument for
    parking: the LLM was producing a nicer sentence for the same information,
    on a surface the athlete reads in passing.

    The LLM body below is left unreachable for one quiet release and goes in the
    step-7 cleanup along with the module.
    """
    from backend.services.gap_analysis.evidence_text import render_evidence_text

    code = finding["code"]
    evidence = finding.get("evidence") or []
    target = finding.get("target")

    fallback_text = render_evidence_text(code, evidence, target)

    def _fallback():
        return {"phrasing": fallback_text, "phrasing_source": "template"}

    # Forced. Was: `if not llm.llm_enabled(): return _fallback()`
    return _fallback()

    facts_str = _evidence_to_facts_str(evidence)
    sig = build_phrasing_signature(user_id, week_start, code, evidence)

    recommendation = finding.get("recommendation", "")
    user_prompt = (
        f"Finding: {code}\n"
        f"Evidence values: {facts_str}\n"
        f"Recommendation: {recommendation}\n"
        "Write a 1-2 sentence coach-voice phrasing of this finding using only the values above.\n"
        'Return JSON: {"phrasing": "..."}'
    )

    def _generate():
        return llm.complete_structured(
            system=_SYSTEM_PROMPT,
            user=user_prompt,
            schema_name="gap_finding_phrasing",
            json_schema=_PHRASING_JSON_SCHEMA,
            model_tier="fast",
        )

    result = llm.get_or_generate(
        user_id=user_id,
        surface="gap_finding",
        signature=sig,
        generate_fn=_generate,
        db=db,
    )

    if result is None:
        return _fallback()

    text = result.get("phrasing", "")
    if not text:
        return _fallback()

    if len(text) > _MAX_PHRASING_LEN:
        _log.warning("gap_finding_phrasing: length cap exceeded for %s, using fallback", code)
        return _fallback()

    if not _numeral_guard_passes(text, facts_str):
        _log.warning("gap_finding_phrasing: numeral guard failed for %s, using fallback", code)
        return _fallback()

    return {"phrasing": text, "phrasing_source": "llm"}
