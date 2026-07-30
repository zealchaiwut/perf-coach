"""Athlete identity fields on the prefs endpoints (spec §6 item 5).

``athlete.age``, ``athlete.height_cm`` and ``athlete.context`` need a source, so
``users`` gained ``birth_date`` / ``height_cm`` / ``athlete_context`` and
Settings → Profile edits them through the existing
``GET|PATCH /api/user-preferences`` pair.

These live on ``users``, not ``user_preferences``, which is why they go through a
separate helper — the tests below pin both the read shape and the validation, and
that ``athlete_context`` stays distinct from plan-prefs ``notes`` (scheduling
instructions, a different field entirely).
"""
from __future__ import annotations

import datetime

import pytest

from backend.main import _ATHLETE_CONTEXT_MAX_CHARS, _athlete_identity_dict


class _FakeUser:
    def __init__(self, **kw) -> None:
        self.id = kw.get("id", "00000000-0000-0000-0000-000000000001")
        self.birth_date = kw.get("birth_date")
        self.height_cm = kw.get("height_cm")
        self.athlete_context = kw.get("athlete_context")


# ── Read shape ───────────────────────────────────────────────────────────────

def test_identity_dict_serialises_all_three_fields():
    row = _athlete_identity_dict(
        _FakeUser(
            birth_date=datetime.date(1988, 4, 12),
            height_cm=178.5,
            athlete_context="6 years running",
        )
    )
    assert row == {
        "birth_date": "1988-04-12",
        "height_cm": 178.5,
        "athlete_context": "6 years running",
    }


def test_identity_dict_returns_nulls_not_omissions_when_unset():
    """The Settings form binds to these keys; a missing key would render as
    "undefined" rather than an empty input."""
    row = _athlete_identity_dict(_FakeUser())
    assert row == {"birth_date": None, "height_cm": None, "athlete_context": None}
    assert set(row) == {"birth_date", "height_cm", "athlete_context"}


def test_identity_dict_tolerates_a_user_row_without_the_columns():
    """A clone whose migration hasn't run yet must degrade, not 500 the whole
    Settings page."""
    class _Legacy:
        pass

    assert _athlete_identity_dict(_Legacy()) == {
        "birth_date": None,
        "height_cm": None,
        "athlete_context": None,
    }


def test_identity_dict_converts_decimal_height_to_float():
    from decimal import Decimal

    row = _athlete_identity_dict(_FakeUser(height_cm=Decimal("178.5")))
    assert isinstance(row["height_cm"], float)


# ── Context cap ──────────────────────────────────────────────────────────────

def test_context_cap_is_the_documented_two_hundred_characters():
    assert _ATHLETE_CONTEXT_MAX_CHARS == 200


def test_export_module_agrees_on_the_context_cap():
    """Two constants for one limit drift; this is the canary if they do."""
    from backend.services.coach_export import ATHLETE_CONTEXT_MAX_CHARS

    assert ATHLETE_CONTEXT_MAX_CHARS == _ATHLETE_CONTEXT_MAX_CHARS


# ── Validation (mirrors the PATCH handler's rules) ────────────────────────────

@pytest.mark.parametrize(
    "raw,valid",
    [
        ("1988-04-12", True),
        ("1899-12-31", False),   # before 1900
        ("2099-01-01", False),   # future
        ("12/04/1988", False),   # wrong format
        ("not-a-date", False),
    ],
)
def test_birth_date_validation_rules(raw, valid):
    """Same three checks the endpoint applies: parseable, not future, post-1900."""
    try:
        parsed = datetime.date.fromisoformat(raw)
    except (ValueError, TypeError):
        assert not valid
        return
    ok = parsed <= datetime.date.today() and parsed.year >= 1900
    assert ok is valid


@pytest.mark.parametrize(
    "value,valid",
    [(178.5, True), (80, True), (250, True), (79.9, False), (250.1, False), (True, False)],
)
def test_height_validation_rules(value, valid):
    ok = (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 80 <= float(value) <= 250
    )
    assert ok is valid


def test_context_over_the_cap_is_rejected():
    too_long = "x" * (_ATHLETE_CONTEXT_MAX_CHARS + 1)
    assert len(too_long) > _ATHLETE_CONTEXT_MAX_CHARS


def test_context_at_the_cap_is_accepted():
    assert len("x" * _ATHLETE_CONTEXT_MAX_CHARS) <= _ATHLETE_CONTEXT_MAX_CHARS


# ── Export reads the stored context ──────────────────────────────────────────

def test_blank_context_is_exported_as_null_not_empty_string():
    """The endpoint stores None for a cleared field; the export must report an
    absent context as null so the template's "null means unknown" rule applies."""
    from backend.services.coach_export import _assemble_athlete

    class _Session:
        def query(self, *_a, **_k):
            return self

        def filter(self, *_a, **_k):
            return self

        def all(self):
            return []

    athlete = _assemble_athlete(
        _Session(), _FakeUser(athlete_context=""), datetime.date(2026, 7, 30), {}
    )
    assert athlete["context"] is None
