"""
Issue #1508 — docs/features/api.md documents GET /api/planned-sessions with
the wrong response shape (flat array vs. week-bundle object).

AC: The GET /api/planned-sessions section must document the real week-bundle
shape returned by the handler:
    {"from": "YYYY-MM-DD", "to": "YYYY-MM-DD", "days": [{"date", "dow",
     "planned": [...], "unplanned": [...]}]}
not the old flat array [{"id", "user_id", "planned_date", ...}].
"""
import re
from pathlib import Path

DOC_PATH = Path(__file__).parent.parent / "docs" / "features" / "api.md"


def _extract_planned_sessions_section(text: str) -> str:
    """Return the subsection between the GET /api/planned-sessions heading and
    the next top-level '---' divider or end-of-file."""
    start = text.find("## `GET /api/planned-sessions`")
    assert start != -1, "GET /api/planned-sessions section not found in api.md"
    end = text.find("\n---\n", start + 1)
    return text[start:end] if end != -1 else text[start:]


def test_response_is_not_flat_array():
    """The old (wrong) shape began with '[' — a JSON array. It must be gone."""
    section = _extract_planned_sessions_section(DOC_PATH.read_text())
    # Find the JSON block inside the section
    code_blocks = re.findall(r"```json\s*(.*?)```", section, re.DOTALL)
    # There should be at least one response example
    assert code_blocks, "No JSON code block found in GET /api/planned-sessions section"
    response_block = code_blocks[0].strip()
    assert not response_block.startswith("["), (
        "Response example must not be a flat JSON array — "
        "the handler returns a week-bundle object, not a list"
    )


def test_response_has_from_to_days():
    """Top-level keys 'from', 'to', and 'days' must appear in the response example."""
    section = _extract_planned_sessions_section(DOC_PATH.read_text())
    code_blocks = re.findall(r"```json\s*(.*?)```", section, re.DOTALL)
    assert code_blocks, "No JSON code block in GET /api/planned-sessions section"
    block = code_blocks[0]
    for key in ('"from"', '"to"', '"days"'):
        assert key in block, (
            f"{key} not found in GET /api/planned-sessions response example — "
            "must document the week-bundle structure"
        )


def test_days_array_has_date_dow_planned_unplanned():
    """Each day object in 'days' must document 'date', 'dow', 'planned', and 'unplanned'."""
    section = _extract_planned_sessions_section(DOC_PATH.read_text())
    code_blocks = re.findall(r"```json\s*(.*?)```", section, re.DOTALL)
    assert code_blocks, "No JSON code block in GET /api/planned-sessions section"
    block = code_blocks[0]
    for key in ('"date"', '"dow"', '"planned"', '"unplanned"'):
        assert key in block, (
            f"{key} not documented inside the 'days' array — "
            "each day object must have date, dow, planned, and unplanned"
        )


def test_no_user_id_in_top_level_response():
    """The old flat-array shape had 'user_id' at the top level; the real response
    does not expose it — make sure the example no longer contains it."""
    section = _extract_planned_sessions_section(DOC_PATH.read_text())
    code_blocks = re.findall(r"```json\s*(.*?)```", section, re.DOTALL)
    assert code_blocks, "No JSON code block in GET /api/planned-sessions section"
    block = code_blocks[0]
    assert '"user_id"' not in block, (
        '"user_id" must not appear in the response example — '
        "the handler does not return user_id in the week-bundle"
    )


def test_planned_session_fields_documented():
    """The per-session dict fields (id, planned_date, session_type, status,
    actual, estimated_tss, plan_warnings) must be mentioned in the field table."""
    section = _extract_planned_sessions_section(DOC_PATH.read_text())
    for field in ("actual", "estimated_tss", "plan_warnings", "status"):
        assert field in section, (
            f"Field '{field}' not documented in GET /api/planned-sessions section"
        )
