"""Tests for issue #1579 — SCHEMA.md must document the 6 tables added in the
2026-07-22 release and note migration d35f3915950e's one-way caveat."""

import pathlib
import re

SCHEMA_MD = pathlib.Path(__file__).parent.parent / "SCHEMA.md"


def _text() -> str:
    return SCHEMA_MD.read_text()


# AC: one section per table matching backend/models.py


def test_schema_has_daily_briefs_section():
    assert "## daily_briefs" in _text(), "SCHEMA.md missing ## daily_briefs section"


def test_schema_has_plan_drafts_section():
    assert "## plan_drafts" in _text(), "SCHEMA.md missing ## plan_drafts section"


def test_schema_has_training_preferences_section():
    assert "## training_preferences" in _text(), "SCHEMA.md missing ## training_preferences section"


def test_schema_has_preference_proposals_section():
    assert "## preference_proposals" in _text(), "SCHEMA.md missing ## preference_proposals section"


def test_schema_has_user_custom_presets_section():
    assert "## user_custom_presets" in _text(), "SCHEMA.md missing ## user_custom_presets section"


def test_schema_has_preference_import_audits_section():
    assert "## preference_import_audits" in _text(), "SCHEMA.md missing ## preference_import_audits section"


# AC: migration caveats noted

def test_schema_notes_d35f3915950e_as_one_way():
    """The migration d35f3915950e is effectively one-way; SCHEMA.md must say so."""
    text = _text()
    assert "d35f3915950e" in text, "Migration id d35f3915950e not mentioned in SCHEMA.md"
    # Find all occurrences and check that at least one has the one-way/downgrade caveat nearby.
    start = 0
    found = False
    while True:
        idx = text.find("d35f3915950e", start)
        if idx == -1:
            break
        surrounding = text[max(0, idx - 200): idx + 1500]
        if "one-way" in surrounding or "downgrade" in surrounding.lower():
            found = True
            break
        start = idx + 1
    assert found, (
        "SCHEMA.md mentions d35f3915950e but does not note its one-way / downgrade caveat"
    )


def test_schema_notes_dedup_delete_caveat():
    """The unaudited dedup DELETE in d35f3915950e's upgrade must be called out."""
    text = _text()
    start = 0
    found = False
    while True:
        idx = text.find("d35f3915950e", start)
        if idx == -1:
            break
        surrounding = text[max(0, idx - 200): idx + 1500]
        if "dedup" in surrounding or "DELETE" in surrounding or "unaudited" in surrounding:
            found = True
            break
        start = idx + 1
    assert found, (
        "SCHEMA.md does not mention the dedup DELETE / unaudited aspect of d35f3915950e"
    )


# Spot-check that the weekly_coach_messages section reflects the for_date column
# (was missing before d35f3915950e documentation was updated)

def test_weekly_coach_messages_has_for_date_column():
    text = _text()
    # Find the weekly_coach_messages section
    match = re.search(r"## weekly_coach_messages.*?(?=\n## |\Z)", text, re.DOTALL)
    assert match, "weekly_coach_messages section not found"
    section = match.group(0)
    assert "for_date" in section, (
        "weekly_coach_messages section does not document the for_date column"
    )


def test_weekly_coach_messages_unique_is_user_date():
    """After d35f3915950e, uniqueness is (user_id, for_date), not (user_id, for_week)."""
    text = _text()
    match = re.search(r"## weekly_coach_messages.*?(?=\n## |\Z)", text, re.DOTALL)
    assert match, "weekly_coach_messages section not found"
    section = match.group(0)
    assert "uq_weekly_coach_messages_user_date" in section, (
        "weekly_coach_messages section still references old uq_weekly_coach_messages_user_week "
        "instead of the current uq_weekly_coach_messages_user_date"
    )
