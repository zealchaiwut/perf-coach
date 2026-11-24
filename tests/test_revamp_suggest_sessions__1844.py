"""Issue #1844 — deterministic suggest fill to week target."""

from datetime import date, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from backend.services.revamp_suggest_sessions import (
    GAP_MIN_SUGGEST_TSS,
    apply_week_suggestions,
    suggest_week_fill,
)


def test_gap_at_or_below_min_returns_no_proposals(monkeypatch):
    ws = date(2026, 11, 10)

    class _Sess:
        def query(self, *a, **k):
            return self

        def filter(self, *a, **k):
            return self

        def order_by(self, *a, **k):
            return self

        def all(self):
            return []

    monkeypatch.setattr(
        "backend.services.revamp_suggest_sessions.weekly_rollup",
        lambda *a, **k: {"target_tss": 100.0, "planned_tss": 98.0, "phase": "build"},
    )
    monkeypatch.setattr("backend.services.revamp_suggest_sessions._build_ctx", lambda *a, **k: None)
    out = suggest_week_fill(_Sess(), uuid4(), week_start=ws, today=ws)
    assert out["proposed"] == []
    assert GAP_MIN_SUGGEST_TSS >= 2


def test_fill_algorithm_is_deterministic_for_fixed_ctx(monkeypatch):
    """Same mocked context + empty rules → identical proposed list twice."""
    from backend.services.revamp_suggest_sessions import _Ctx, suggest_week_fill

    ws = date(2026, 11, 10)
    ctx = _Ctx(
        user_id=uuid4(),
        week_start=ws,
        today=ws,
        target_tss=120.0,
        week_gap=30.0,
        phase="build",
        rest_days=[],
        max_consecutive=3,
        acwr_ceiling=400.0,
        races=[],
        exercise_groups={},
        sessions=[],
    )

    class _Sess:
        def query(self, *a, **k):
            return self

        def filter(self, *a, **k):
            return self

        def order_by(self, *a, **k):
            return self

        def all(self):
            return []

    monkeypatch.setattr("backend.services.revamp_suggest_sessions._build_ctx", lambda *a, **k: ctx)
    monkeypatch.setattr(
        "backend.services.revamp_suggest_sessions._load_candidates",
        lambda *a, **k: [
            {
                "candidate_id": "builtin:mobility",
                "name": "Mobility block",
                "session_type": "mobility",
                "structure": {"target_tss": 12},
                "estimated_tss": 12.0,
            }
        ],
    )
    monkeypatch.setattr(
        "backend.services.revamp_suggest_sessions._pick_day",
        lambda ctx, views, cand: ws + timedelta(days=2),
    )
    a = suggest_week_fill(_Sess(), ctx.user_id, week_start=ws, today=ws)
    b = suggest_week_fill(_Sess(), ctx.user_id, week_start=ws, today=ws)
    assert a["proposed"] == b["proposed"]
    assert a["proposed"]


def test_apply_creates_rows():
    class _Sess:
        def __init__(self):
            self.rows = []

        def add(self, row):
            self.rows.append(row)

    sess = _Sess()
    proposed = [
        {
            "planned_date": "2026-11-12",
            "session_type": "mobility",
            "name": "Mobility block",
            "structure": {"target_tss": 12},
        }
    ]
    out = apply_week_suggestions(sess, uuid4(), proposed)
    assert out["created"] == 1
    assert sess.rows[0].plan_source == "support"