"""Narrative section primitives — the LLM-free half of the old coach_narrative.

Now / Focus / Dream / Reflection is the shape of the coach's Markdown message.
Rendering it, parsing it back, and choosing which session preset the nudge points
at are all deterministic — they were only ever in ``coach_narrative`` because the
LLM assembly lived next door.

Split out so the deterministic coach path (``coach_brief.compose_coach_brief`` →
``brief_to_text`` → ``weekly_coach_message``) can run without importing a module
whose reason for existing is an LLM call. ``coach_narrative`` is parked; this is
what survives it.

Note the ``SECTION_ORDER`` here is the *narrative* one (four Markdown sections).
``coach_brief_map`` has its own, unrelated ``SECTION_ORDER`` for the v4 brief's
card sections — do not cross the two.
"""

from __future__ import annotations

import re

SECTION_ORDER = ("now", "focus", "dream", "reflection")
SECTION_HEADERS = {
    "now": "## Now",
    "focus": "## Focus",
    "dream": "## Dream",
    "reflection": "## Reflection",
}


def sections_to_text(sections: dict[str, str]) -> str:
    parts = []
    for key in SECTION_ORDER:
        body = (sections.get(key) or "").strip()
        parts.append(f"{SECTION_HEADERS[key]}\n{body}")
    return "\n\n".join(parts)


def parse_sections_from_text(text: str) -> dict[str, str]:
    """Split Markdown ## Now/Focus/Dream/Reflection into a dict."""
    if not text:
        return {k: "" for k in SECTION_ORDER}
    pattern = re.compile(
        r"^##\s+(Now|Focus|Dream|Reflection)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    matches = list(pattern.finditer(text))
    out = {k: "" for k in SECTION_ORDER}
    if not matches:
        # Legacy weekly message — put everything in Now
        out["now"] = text.strip()
        return out
    for i, m in enumerate(matches):
        key = m.group(1).lower()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        if key in out:
            out[key] = text[start:end].strip()
    return out


def apply_chosen_preset(facts: dict, chosen_code: str | None) -> dict:
    """Point the nudge at a session preset; update facts nudge/chosen_preset.

    ``chosen_code`` was the LLM's pick, validated against ``active_presets``.
    With the narrative LLM parked the deterministic path passes None, which
    takes the first active preset — the same branch a rejected or absent LLM
    pick always took.
    """
    from backend.services.gap_analysis.session_presets import pick_preset_by_code

    presets = facts.get("active_presets") or []
    if not presets:
        return facts
    picked = pick_preset_by_code(presets, chosen_code) if chosen_code else None
    if picked is None:
        picked = presets[0]
    facts["chosen_preset"] = picked
    facts["nudge"] = {
        "focus_id": picked.get("code"),
        "focus_label": picked.get("name") or picked.get("kind"),
        "next_action": (
            f"{picked.get('name') or picked.get('kind')} ({picked.get('summary')})"
        ),
        "why": picked.get("notes"),
        "preset_code": picked.get("code"),
    }
    return facts
