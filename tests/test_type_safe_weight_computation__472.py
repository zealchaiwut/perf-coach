"""Type-safe weight computation in project_hit_date (issue #472).

Verifies that project_hit_date handles weight_kg values that arrive as
strings or plain floats from the database without raising TypeError.
"""
from __future__ import annotations

import datetime
import operator as _op
from decimal import Decimal
from types import SimpleNamespace

import pytest

from backend.services.weight_plan import project_hit_date


# ── shared helpers ───────────────────────────────────────────────────────────


def _target(start_w, target_w):
    today = datetime.date.today()
    return SimpleNamespace(
        user_id=None,
        start_weight_kg=Decimal(str(start_w)),
        target_weight_kg=Decimal(str(target_w)),
        start_date=today - datetime.timedelta(days=90),
        target_date=today + datetime.timedelta(days=90),
    )


class _FakeEntry:
    def __init__(self, entry_date, weight_kg):
        self.entry_date = entry_date
        self.weight_kg = weight_kg  # deliberate: stored as-is, not pre-wrapped


class _FakeQuery:
    def __init__(self, entries):
        self._entries = list(entries)
        self._date_min = None
        self._date_max = None

    def filter(self, *args, **kwargs):
        for arg in args:
            try:
                val = arg.right.value
                if isinstance(val, datetime.date):
                    op = arg.operator
                    if op is _op.ge:
                        self._date_min = val
                    elif op is _op.le:
                        self._date_max = val
            except AttributeError:
                pass
        return self

    def _apply_date_filter(self):
        result = self._entries
        if self._date_min is not None:
            result = [e for e in result if e.entry_date >= self._date_min]
        if self._date_max is not None:
            result = [e for e in result if e.entry_date <= self._date_max]
        return result

    def order_by(self, *args, **kwargs):
        return self

    def all(self):
        return sorted(self._apply_date_filter(), key=lambda e: e.entry_date)


class _FakeSession:
    def __init__(self, entries):
        self._entries = entries

    def query(self, model):
        return _FakeQuery(list(self._entries))


# ── AC1: string weight_kg values do not raise TypeError ─────────────────────


def test_project_hit_date_string_weight_kg_no_type_error():
    """AC1: string weight_kg (as can come from some DB drivers) is handled safely."""
    today = datetime.date.today()
    t = _target(85.0, 75.0)
    entries = [
        _FakeEntry(today - datetime.timedelta(days=6), "81.0"),
        _FakeEntry(today, "80.5"),
    ]
    session = _FakeSession(entries)
    # Must not raise TypeError; returns a date or None
    result = project_hit_date(t, session, today)
    assert result is None or isinstance(result, datetime.date)


# ── AC2: float weight_kg values work correctly ───────────────────────────────


def test_project_hit_date_float_weight_kg():
    """AC2: float weight_kg (native Python float from ORM) is handled safely."""
    today = datetime.date.today()
    t = _target(85.0, 75.0)
    entries = [
        _FakeEntry(today - datetime.timedelta(days=6), 81.0),
        _FakeEntry(today, 80.5),
    ]
    session = _FakeSession(entries)
    result = project_hit_date(t, session, today)
    assert result is None or isinstance(result, datetime.date)


# ── AC3: int weight_kg values work correctly ─────────────────────────────────


def test_project_hit_date_int_weight_kg():
    """AC3: integer weight_kg is handled safely."""
    today = datetime.date.today()
    t = _target(85, 75)
    entries = [
        _FakeEntry(today - datetime.timedelta(days=6), 82),
        _FakeEntry(today, 81),
    ]
    session = _FakeSession(entries)
    result = project_hit_date(t, session, today)
    assert result is None or isinstance(result, datetime.date)


# ── AC4: string values produce correct projection math ───────────────────────


def test_project_hit_date_string_weight_correct_math():
    """AC4: string weight_kg produces the same result as Decimal weight_kg."""
    today = datetime.date.today()
    t = _target(85.0, 75.0)

    def _make_session(weight_type):
        entries = [
            _FakeEntry(today - datetime.timedelta(days=6), weight_type("81.0")),
            _FakeEntry(today - datetime.timedelta(days=3), weight_type("80.5")),
            _FakeEntry(today, weight_type("80.0")),
        ]
        return _FakeSession(entries)

    result_decimal = project_hit_date(t, _make_session(lambda v: Decimal(v)), today)
    result_string = project_hit_date(t, _make_session(lambda v: v), today)

    # Both must succeed and agree on the projected date
    assert result_string is not None
    assert result_decimal is not None
    assert result_string == result_decimal
