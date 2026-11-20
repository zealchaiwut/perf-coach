"""Plan warnings (P3-11, #1845)."""
from __future__ import annotations

import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from backend.services.plan_warnings import _layout_hint, settings_save_allowed


def test_layout_hint_suggests_shorten_rebuild():
    s = {
        "build_weeks": 8,
        "peak_hold_weeks": 4,
        "taper_factors": [0.75, 0.55],
        "rebuild_weeks": 6,
        "recover_weeks": 1,
    }
    hint = _layout_hint(s, 3)
    assert "rebuild" in hint.lower()


def test_post_race_marathon_checkpoint_clash():
    from backend.services.plan_warnings import _clashes_from_rows

    anchor = SimpleNamespace(
        id=uuid.uuid4(), name="Marathon A", race_date=date(2026, 10, 1), distance_km=42.2
    )
    cp = SimpleNamespace(
        id=uuid.uuid4(),
        race_id=uuid.uuid4(),
        label="18k shakeout",
        target_date=date(2026, 10, 7),
        target_distance_km=18,
    )
    clashes = _clashes_from_rows([anchor], [], [cp])
    assert clashes and clashes[0]["entity_type"] == "checkpoint"
    assert clashes[0]["suggested_date"] == "2026-10-14"


def test_settings_save_blocked_when_layout_invalid(monkeypatch):
    from backend.services import plan_warnings as pw

    class _Sess:
        def query(self, *a, **k):
            return self

        def filter(self, *a, **k):
            return self

        def order_by(self, *a, **k):
            return self

        def first(self):
            return SimpleNamespace(race_date=date(2026, 12, 1), distance_km=42.2, name="A")

    def boom(**_kwargs):
        raise pw.LoadPlanLayoutError("fixture")

    monkeypatch.setattr(pw, "validate_block_layout", boom)
    monkeypatch.setattr(pw, "block_start_for_race", lambda *a, **k: date(2026, 6, 1))
    monkeypatch.setattr(pw, "chronic_weekly_tss", lambda *a, **k: 200.0)
    monkeypatch.setattr(pw, "weeks_from_block_start_to_race", lambda *a, **k: 10)
    monkeypatch.setattr(pw, "_series_week_count", lambda *a, **k: 20)
    err = pw.layout_error(_Sess(), uuid.uuid4(), {})
    assert err and err["blocks_settings_save"]
    assert not settings_save_allowed(_Sess(), uuid.uuid4(), {})

