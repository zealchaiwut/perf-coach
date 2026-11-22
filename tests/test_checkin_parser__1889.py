"""P6-15 (#1889) — check-in prompt parser and round-trip."""
from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.models import WeeklyCheckIn
from backend.services.checkin_changes import PROMPT_VERSION_WEEKLY, parse_changes_block
from backend.services.weekly_checkin import apply_paste_back, build_prompt_preview_stub


SAMPLE_REPLY = """Thanks for the check-in.

CHANGES TO APPLY
lessons:  Keep long run on Sunday
skeleton: Move intervals to Tuesday
goal:     Hold marathon goal pace work
review:   weight trend, 2026-11-29
"""


def test_parser_finds_block_with_extra_prose():
    items = parse_changes_block(SAMPLE_REPLY, decided_on=date(2026, 11, 22))
    keys = {i["change_type"] for i in items}
    assert keys >= {"lessons", "skeleton", "goal", "review"}
    review = next(i for i in items if i["change_type"] == "review")
    assert review["review_on"] == "2026-11-29"


def test_round_trip_paste_carries_to_next_week():
    uid = uuid.uuid4()
    session = MagicMock()
    ws = date(2026, 11, 2)
    row = WeeklyCheckIn(user_id=uid, week_start=ws, carried_changes=[], snapshot={})

    def query(model):
        q = MagicMock()
        if model is WeeklyCheckIn:
            q.filter.return_value.first.return_value = None
        return q

    session.query.side_effect = query
    added = []
    session.add.side_effect = lambda o: added.append(o)
    result = apply_paste_back(session, uid, row, SAMPLE_REPLY, date(2026, 11, 8))
    assert len(result["parsed"]) >= 3
    nxt_rows = [o for o in added if isinstance(o, WeeklyCheckIn) and o.week_start == date(2026, 11, 9)]
    assert nxt_rows and len(nxt_rows[0].carried_changes) >= 3


def test_prompt_includes_version():
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.all.return_value = []
    session.query.return_value.filter.return_value.order_by.return_value.limit.return_value.first.return_value = None
    row = WeeklyCheckIn(user_id=uuid.uuid4(), week_start=date(2026, 11, 2), carried_changes=[], snapshot={"week_start": "2026-11-02"})
    text = build_prompt_preview_stub(session, row.user_id, row.snapshot, [], row, date(2026, 11, 8))
    assert PROMPT_VERSION_WEEKLY in text
    assert "CHANGES TO APPLY" in text