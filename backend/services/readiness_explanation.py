"""Readiness explanation service (issue #1313).

Exposes:
  build_rule_based_explanation(factors)  — pure function, no I/O
  numeral_guard_passes(text, facts_str)  — validate LLM numerals against input facts
  build_explanation_signature(...)       — cache key for llm_generations
  get_readiness_explanation(...)         — LLM + cache wrapper, falls back to rule-based
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

import backend.services.llm as llm
from backend.utils.log import get_logger

_log = get_logger(__name__)

_MAX_EXPLANATION_LEN = 500

_FACTOR_LABELS = {
    "sleep_hours": "sleep",
    "hrv": "HRV",
    "rhr": "resting HR",
    "energy": "energy",
    "mood": "mood",
    "sleep_quality": "sleep quality",
}

_EXPLANATION_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "explanation": {"type": "string"},
    },
    "required": ["explanation"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Rule-based fallback — pure function
# ---------------------------------------------------------------------------

def _fmt_value(factor: str, value) -> str:
    if value is None:
        return "—"
    v = float(value)
    if factor == "sleep_hours":
        return f"{v:.1f}h"
    if factor in ("hrv",):
        return f"{v:.1f} ms"
    if factor in ("rhr",):
        return f"{v:.0f} bpm"
    if factor in ("energy", "mood", "sleep_quality"):
        return f"{v:.1f}/5"
    return str(v)


def build_rule_based_explanation(factors: list[dict[str, Any]]) -> str:
    """Build a plain-English 1-sentence explanation from up to 3 top factors.

    factors: list of dicts with keys: factor, value, score (0-100), impact
    Pure function — no I/O.
    """
    # Sort by abs deviation from neutral (50)
    with_dev = [
        (f, abs((f.get("score") or 50.0) - 50.0))
        for f in factors
        if f.get("value") is not None
    ]
    with_dev.sort(key=lambda x: x[1], reverse=True)
    top = with_dev[:3]

    if not top:
        return "All signals are within normal range."

    positives = [f for f, _ in top if (f.get("impact") == "positive")]
    negatives = [f for f, _ in top if (f.get("impact") == "negative")]

    def _label(f):
        return _FACTOR_LABELS.get(f["factor"], f["factor"])

    def _val(f):
        return _fmt_value(f["factor"], f.get("value"))

    parts = []
    if negatives:
        neg_str = " and ".join(f"{_label(f)} ({_val(f)})" for f in negatives)
        parts.append(f"Score lowered by {neg_str}.")
    if positives:
        pos_str = " and ".join(f"{_label(f)} ({_val(f)})" for f in positives)
        parts.append(f"Score boosted by {pos_str}.")

    if not parts:
        # All neutral
        return "All signals are within normal range."

    return " ".join(parts)


# ---------------------------------------------------------------------------
# Numeral guard
# ---------------------------------------------------------------------------

def numeral_guard_passes(text: str, facts_str: str) -> bool:
    """Return True iff every number in text appears verbatim in facts_str."""
    nums = re.findall(r"\d+(?:\.\d+)?", text)
    for n in nums:
        if n not in facts_str:
            return False
    return True


# ---------------------------------------------------------------------------
# Cache signature
# ---------------------------------------------------------------------------

def build_explanation_signature(user_id: str, target_date: str, facts: dict) -> str:
    canonical = json.dumps(
        {"user": user_id, "date": target_date, "facts": facts},
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()[:64]


# ---------------------------------------------------------------------------
# LLM + cache wrapper
# ---------------------------------------------------------------------------

def _facts_to_str(facts: dict) -> str:
    """Serialize facts dict to a string used for numeral validation."""
    return " ".join(f"{k}={v}" for k, v in facts.items() if v is not None)


def get_readiness_explanation(
    user_id: str,
    target_date: str,
    facts: dict,
    fallback_factors: list[dict[str, Any]],
    *,
    db=None,
) -> str:
    """Return explanation string — LLM when enabled and valid, else rule-based.

    facts: dict of raw metric values and baselines (used as LLM inputs)
    fallback_factors: list of factor dicts (factor, value, score, impact) for rule-based
    """
    fallback = build_rule_based_explanation(fallback_factors)

    if not llm.llm_enabled():
        return fallback

    facts_str = _facts_to_str(facts)
    sig = build_explanation_signature(user_id, target_date, facts)

    system = (
        "You are a performance coach writing brief, factual readiness explanations. "
        "Rules: 1-2 sentences, max 400 characters, use ONLY the numbers given in the data, "
        "no medical advice, no emoji, no exclamation marks, supportive tone."
    )
    user_prompt = (
        "Write a 1-2 sentence explanation of why the readiness score is what it is "
        "for today, using only the values given.\n"
        f"Data: {facts_str}\n"
        "Return JSON: {\"explanation\": \"...\"}"
    )

    def _generate():
        return llm.complete_structured(
            system=system,
            user=user_prompt,
            schema_name="readiness_explanation",
            json_schema=_EXPLANATION_JSON_SCHEMA,
            model_tier="fast",
        )

    result = llm.get_or_generate(
        user_id=user_id,
        surface="readiness_explanation",
        signature=sig,
        generate_fn=_generate,
        db=db,
    )

    if result is None:
        return fallback

    text = result.get("explanation", "")
    if not text:
        return fallback

    if len(text) > _MAX_EXPLANATION_LEN:
        return fallback

    if not numeral_guard_passes(text, facts_str):
        _log.warning("readiness_explanation: numeral guard failed, using fallback")
        return fallback

    return text
