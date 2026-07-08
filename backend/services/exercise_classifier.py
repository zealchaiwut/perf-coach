"""Exercise body-part classifier.

Classifies a strength exercise name into a set of body-part ratios using the
Groq LLM (via backend.services.llm).  Stores results in the exercise_catalog
table so each exercise is only classified once; manual overrides are preserved.

Body parts recognised (no others are accepted):
  chest, back, shoulders, biceps, triceps, core, quads, hamstrings, glutes, calves
"""

from __future__ import annotations

import re
from typing import Optional

import backend.services.llm as llm_svc
from backend.utils.log import get_logger

_log = get_logger(__name__)

VALID_BODY_PARTS = frozenset({
    "chest", "back", "shoulders", "biceps", "triceps",
    "core", "quads", "hamstrings", "glutes", "calves",
})

_CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "body_parts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "part": {
                        "type": "string",
                        "enum": sorted(VALID_BODY_PARTS),
                    },
                    "ratio": {
                        "type": "number",
                        "minimum": 0.0,
                        "maximum": 1.0,
                    },
                },
                "required": ["part", "ratio"],
                "additionalProperties": False,
            },
            "minItems": 1,
        }
    },
    "required": ["body_parts"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """\
You are a strength and conditioning expert who classifies exercises by which \
muscle groups they primarily and secondarily work.

For each exercise name, return a JSON object with a "body_parts" array. Each \
entry has:
  "part"  — one of: back, biceps, calves, chest, core, glutes, hamstrings, \
quads, shoulders, triceps
  "ratio" — a float in [0, 1] representing the share of training stress for \
that muscle group

Rules:
- Ratios must sum to 1.0 (within 0.02 tolerance).
- Include only muscle groups meaningfully loaded (ratio >= 0.05).
- For compound lifts split the stress across all loaded groups.
- Be accurate and concise; do not invent muscle group names.
"""


def normalize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip().lower())


def _validate_body_parts(raw: list) -> list[dict]:
    """Normalise LLM output: filter to valid parts, clamp ratios, renormalise."""
    cleaned = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        part = str(item.get("part", "")).lower().strip()
        if part not in VALID_BODY_PARTS:
            continue
        try:
            ratio = float(item["ratio"])
        except (KeyError, TypeError, ValueError):
            continue
        if ratio < 0.04:
            continue
        cleaned.append({"part": part, "ratio": ratio})

    if not cleaned:
        return []

    total = sum(c["ratio"] for c in cleaned)
    if total <= 0:
        return []
    return [{"part": c["part"], "ratio": round(c["ratio"] / total, 4)} for c in cleaned]


def classify_exercise(name: str) -> Optional[list[dict]]:
    """Call LLM to classify exercise name → body_parts list, or return None.

    Returns None when LLM is disabled, the call fails, or the response can't
    be validated. Callers should handle None gracefully (skip or show pending).
    Does NOT write to the database — that's the endpoint's responsibility.
    """
    if not llm_svc.llm_enabled():
        return None

    key = normalize_name(name)
    raw = llm_svc.complete_structured(
        system=_SYSTEM_PROMPT,
        user=f'Classify this exercise: "{key}"',
        schema_name="exercise_body_parts",
        json_schema=_CLASSIFY_SCHEMA,
        model_tier="fast",
    )
    if raw is None:
        return None

    validated = _validate_body_parts(raw.get("body_parts", []))
    if not validated:
        _log.warning("LLM returned invalid body_parts for exercise %r: %s", key, raw)
        return None

    return validated


def get_or_classify(name: str, db) -> Optional[dict]:
    """Return existing catalog entry dict, or LLM-classify and save it.

    Returns {"name", "body_parts", "source"} dict or None if classification
    is not possible (LLM disabled, call failed, etc.).
    db is an open SQLAlchemy Session.
    """
    from backend.models import ExerciseCatalog
    from datetime import datetime, timezone

    key = normalize_name(name)
    existing = db.query(ExerciseCatalog).filter_by(name=key).first()
    if existing is not None:
        return {"name": existing.name, "body_parts": existing.body_parts, "source": existing.source}

    body_parts = classify_exercise(key)
    if body_parts is None:
        return None

    row = ExerciseCatalog(
        name=key,
        body_parts=body_parts,
        source="llm",
        updated_at=datetime.now(timezone.utc),
    )
    try:
        db.add(row)
        db.flush()
        return {"name": row.name, "body_parts": row.body_parts, "source": row.source}
    except Exception as exc:
        db.rollback()
        _log.warning("Failed to save catalog entry for %r: %s", key, exc)
        # Try a fresh read in case a concurrent request already inserted it
        existing = db.query(ExerciseCatalog).filter_by(name=key).first()
        if existing is not None:
            return {"name": existing.name, "body_parts": existing.body_parts, "source": existing.source}
        return None
