"""Issue #1840 — coach week typed-text import."""

from datetime import date
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.services.coach_week_import import (
    _tss_from_duration,
    apply_coach_week_import,
    parse_coach_week_line,
    parse_coach_week_text,
    validate_commit_rows,
)


WEEK = date(2026, 11, 9)  # Monday


@pytest.mark.parametrize(
    "line,run_type,duration,unparsed",
    [
        ("Tue easy 60min", "easy", 60.0, False),
        ("Thu tempo 2km x 7", "tempo", None, False),  # distance inferred below
        ("Sat long 130min", "long", 130.0, False),
        ("Sun race 45min", "race", 45.0, False),
        ("not a session line at all", None, None, True),
    ],
)
def test_parser_table(line, run_type, duration, unparsed):
    row = parse_coach_week_line(
        line,
        week_start=WEEK,
        line_index=0,
        median_pace=360.0,
    )
    if unparsed:
        assert row["parse_status"] == "unparsed"
        assert row["blocks_commit"]
        return
    assert row["parse_status"] == "ok"
    assert row["run_type"] == run_type
    if duration is not None:
        assert row["duration_minutes"] == pytest.approx(duration, rel=1e-2)
    if "km x" in line.lower():
        assert row["inferred"] is True
        assert row["distance_km"] == pytest.approx(14.0, rel=1e-2)


def test_distance_only_row_is_inferred_flagged():
    row = parse_coach_week_line("Sat long 18km", week_start=WEEK, line_index=0, median_pace=400.0)
    assert row["parse_status"] == "ok"
    assert row["inferred"] is True
    assert row["duration_minutes"] == pytest.approx(18 * 400 / 60, rel=1e-2)


def test_easy_tss_formula():
    assert _tss_from_duration(60, "easy") == pytest.approx(49.0, rel=1e-2)


def test_unparsed_row_blocks_commit():
    rows = [
        parse_coach_week_line("Tue easy 60min", week_start=WEEK, line_index=0),
        parse_coach_week_line("garbage!!!", week_start=WEEK, line_index=1),
    ]
    with pytest.raises(ValueError, match="unparsed"):
        validate_commit_rows(rows)


class _Q:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *a, **k):
        return self

    def all(self):
        return list(self._rows)


class _Sess:
    def __init__(self, rows):
        self._rows = rows
        self.deleted = []
        self.added = []

    def query(self, model):
        return _Q(self._rows)

    def delete(self, row):
        self.deleted.append(row)

    def add(self, row):
        self.added.append(row)


def test_reimport_replaces_only_future_unmatched_coach():
    today = date(2026, 11, 12)  # Thursday
    uid = uuid4()
    past_coach = SimpleNamespace(
        user_id=uid,
        planned_date=date(2026, 11, 10),
        plan_source="coach",
        matched_workout_id=None,
        status="planned",
    )
    future_coach = SimpleNamespace(
        user_id=uid,
        planned_date=date(2026, 11, 14),
        plan_source="coach",
        matched_workout_id=None,
        status="planned",
    )
    future_matched = SimpleNamespace(
        user_id=uid,
        planned_date=date(2026, 11, 15),
        plan_source="coach",
        matched_workout_id=uuid4(),
        status="done_manual",
    )
    support = SimpleNamespace(
        user_id=uid,
        planned_date=date(2026, 11, 13),
        plan_source="support",
        matched_workout_id=None,
        status="planned",
    )
    sess = _Sess([past_coach, future_coach, future_matched, support])
    row = parse_coach_week_line("Fri easy 50min", week_start=WEEK, line_index=0)
    out = apply_coach_week_import(sess, uid, week_start=WEEK, rows=[row], today=today)
    assert out["removed"] == 1
    assert future_coach in sess.deleted
    assert past_coach not in sess.deleted
    assert future_matched not in sess.deleted
    assert support not in sess.deleted
    assert out["created"] == 1


def test_parse_text_commit_allowed_false_with_garbage():
    class _DB:
        def query(self, *a, **k):
            return self

        def filter(self, *a, **k):
            return self

        def all(self):
            return []

    payload = parse_coach_week_text(
        _DB(),
        uuid4(),
        week_start=WEEK,
        text="Tue easy 60min\noops",
        today=date(2026, 11, 9),
    )
    assert payload["commit_allowed"] is False