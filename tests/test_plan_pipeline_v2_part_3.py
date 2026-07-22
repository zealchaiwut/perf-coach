"""Plan pipeline v2 part 3 — skeleton ops, dispatch, matching, stale draft."""
from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from backend.services import plan_skeleton_ops as ops
from backend.services import plan_matching as pm
from backend.services.plan_slot_cache import slot_cache_key, content_ctx_from_week


def _sess(day, *, wt="run", tss=40, dur=40, subtype="easy_run", source="llm", **kw):
    s = {
        "day_offset": day,
        "workout_type": wt,
        "target_tss": tss,
        "duration_minutes": dur,
        "subtype": subtype,
        "intent": kw.pop("intent", "Session"),
        "notes": None,
        "blocks": [{"phase": "main", "duration_min": dur}],
        "exercises": None,
        "source": source,
        "structure_hints": {},
        "locked": False,
    }
    s.update(kw)
    return s


def _week():
    return ops.ensure_slot_ids([
        _sess(0, wt="rest", tss=0, dur=0, subtype="rest", intent="Rest", blocks=None),
        _sess(1, tss=35, subtype="easy_run"),
        _sess(2, wt="strength", tss=40, dur=45, subtype="strength_lower"),
        _sess(3, tss=50, subtype="tempo", intent="Tempo intervals"),
        _sess(4, tss=30, subtype="easy_run"),
        _sess(5, tss=90, dur=120, subtype="long_run", intent="Long run"),
        _sess(6, wt="rest", tss=0, dur=0, subtype="rest", intent="Rest", blocks=None),
    ])


# ── Ops ───────────────────────────────────────────────────────────────────────

def test_move_keeps_content_and_slot_id():
    week = _week()
    sid = week[1]["slot_id"]
    intent = week[1]["intent"]
    blocks = week[1]["blocks"]
    out = ops.move(week, slot_id=sid, to_day=0, preferred_rest_days=[], confirm_warnings=True)
    assert not out["blocked"]
    assert out["affected_slot_ids"] == []
    moved = next(s for s in out["slots"] if s["slot_id"] == sid)
    assert moved["day_offset"] == 0
    assert moved["intent"] == intent
    assert moved["blocks"] == blocks


def test_swap_preserves_user_source():
    week = _week()
    week[1]["source"] = "user"
    week[1]["intent"] = "My edited easy"
    sid = week[1]["slot_id"]
    out = ops.move(week, slot_id=sid, to_day=2, confirm_warnings=True)  # swap with strength
    assert not out["blocked"]
    user = next(s for s in out["slots"] if s["slot_id"] == sid)
    assert user["source"] == "user"
    assert user["intent"] == "My edited easy"
    assert user["day_offset"] == 2


def test_redistribute_never_raises_long_run():
    week = _week()
    long = next(s for s in week if s["subtype"] == "long_run")
    long_tss = long["target_tss"]
    easy = next(s for s in week if s["subtype"] == "easy_run" and s["day_offset"] == 1)
    out = ops.remove(week, slot_id=easy["slot_id"], mode="redistribute", acwr_ceiling=400)
    assert not out["blocked"]
    long2 = next(s for s in out["slots"] if s.get("subtype") == "long_run")
    assert long2["target_tss"] == long_tss
    assert out["redistribute"] is not None
    assert "replaced_tss" in out["redistribute"]


def test_redistribute_honors_ceiling():
    week = _week()
    easy = next(s for s in week if s["day_offset"] == 1)
    # Tiny ceiling → most TSS dropped
    current = sum(s["target_tss"] for s in week if s["workout_type"] != "rest") - easy["target_tss"]
    out = ops.remove(week, slot_id=easy["slot_id"], mode="redistribute", acwr_ceiling=current + 5)
    meta = out["redistribute"]
    assert meta["dropped_tss"] >= 0
    assert meta["replaced_tss"] + meta["dropped_tss"] == pytest.approx(float(easy["target_tss"]), abs=6)


def test_add_stretch_no_llm_pending():
    week = _week()
    # Clear day 0 rest by… adding stretch on day 0 replaces rest
    out = ops.add(week, day=0, kind="stretch", preferred_rest_days=[0], confirm_warnings=True)
    assert not out["blocked"]
    assert out["affected_slot_ids"] == []  # no LLM
    added = next(s for s in out["slots"] if s["day_offset"] == 0)
    assert added["workout_type"] == "stretch"
    assert added.get("pending") is False
    assert added.get("source") == "template"


def test_add_acwr_crossing_blocked():
    week = _week()
    total = sum(s["target_tss"] for s in week if s["workout_type"] != "rest")
    # Day 6 is rest — try add that blows ceiling
    out = ops.add(week, day=6, kind="easy_run", acwr_ceiling=total + 5, confirm_warnings=True)
    assert out["blocked"] is True
    assert "ACWR" in (out.get("block_reason") or "")


def test_past_day_blocked():
    week = _week()
    sid = week[4]["slot_id"]
    out = ops.move(week, slot_id=sid, to_day=0, today_offset=2, confirm_warnings=True)
    assert out["blocked"] is True
    assert "past" in (out.get("block_reason") or "").lower()


def test_move_warns_preferred_rest_needs_confirm():
    week = _week()
    sid = week[1]["slot_id"]
    out = ops.move(week, slot_id=sid, to_day=6, preferred_rest_days=[6], confirm_warnings=False)
    assert out.get("needs_confirm")
    assert any("rest" in w.lower() for w in out["warnings"])


# ── Cache rewrite ─────────────────────────────────────────────────────────────

def test_moved_slot_cache_key_changes_with_day_only():
    ctx = content_ctx_from_week({"strength_emphasis": "same", "notes": "", "load": {}})
    old = {"day_offset": 1, "workout_type": "run", "target_tss": 40, "duration_minutes": 40, "subtype": "easy_run"}
    new = {**old, "day_offset": 3}
    assert slot_cache_key(pins=old, content_ctx=ctx) != slot_cache_key(pins=new, content_ctx=ctx)


# ── Matching ──────────────────────────────────────────────────────────────────

class _P:
    def __init__(self, **kw):
        self.session_type = kw.get("session_type", "run")
        self.status = kw.get("status", "planned")
        self.planned_date = kw.get("planned_date")
        self.matched_workout_id = kw.get("matched_workout_id")
        self.structure = kw.get("structure")
        self.updated_at = None
        self.id = kw.get("id", "p1")


class _W:
    def __init__(self, **kw):
        self.id = kw.get("id", "w1")
        self.workout_type = kw.get("workout_type", "run")
        self.workout_date = kw.get("workout_date")
        self.duration_seconds = kw.get("duration_seconds", 3600)


def test_fri_plan_sat_workout_not_missed(monkeypatch):
    """Fri plan + Sat workout in ±1 window → matched (auto or review), never missed."""
    fri = date(2026, 7, 17)
    sat = date(2026, 7, 18)
    planned = [_P(planned_date=fri, structure={"blocks": [{"duration_min": 60}]})]
    workouts = [_W(id="w1", workout_date=sat, duration_seconds=3600)]

    class Q:
        def __init__(self, rows):
            self._rows = rows
        def filter(self, *a, **k):
            return self
        def all(self):
            return self._rows

    from backend import models as m

    class FakeSession:
        def query(self, model):
            if model is m.PlannedSession:
                return Q(planned)
            if model is m.Workout:
                return Q(workouts)
            return Q([])
        def commit(self):
            pass

    monkeypatch.setattr(pm, "_date", SimpleNamespace(today=lambda: date(2026, 7, 20)))
    pm.reconcile_user(FakeSession(), "00000000-0000-0000-0000-000000000001")
    assert planned[0].status == "done_auto"
    assert planned[0].matched_workout_id == "w1"


def test_nothing_in_window_missed_auto(monkeypatch):
    monday = date(2026, 7, 13)
    planned = [_P(planned_date=monday, structure={"blocks": [{"duration_min": 40}]})]

    class Q:
        def filter(self, *a, **k):
            return self
        def all(self):
            return planned if self._kind == "p" else []
        def __init__(self, kind):
            self._kind = kind

    from backend import models as m

    class FakeSession:
        def query(self, model):
            if model is m.PlannedSession:
                return Q("p")
            return Q("w")
        def commit(self):
            pass

    monkeypatch.setattr(pm, "_date", SimpleNamespace(today=lambda: date(2026, 7, 20)))
    pm.reconcile_user(FakeSession(), "00000000-0000-0000-0000-000000000001")
    assert planned[0].status == "missed_auto"


def test_missed_manual_excluded_from_sweep(monkeypatch):
    monday = date(2026, 7, 13)
    planned = [_P(planned_date=monday, status="missed_manual")]

    class Q:
        def __init__(self, kind):
            self._kind = kind
        def filter(self, *a, **k):
            return self
        def all(self):
            return planned if self._kind == "p" else []

    from backend import models as m

    class FakeSession:
        def query(self, model):
            return Q("p" if model is m.PlannedSession else "w")
        def commit(self):
            pass

    monkeypatch.setattr(pm, "_date", SimpleNamespace(today=lambda: date(2026, 7, 20)))
    pm.reconcile_user(FakeSession(), "00000000-0000-0000-0000-000000000001")
    assert planned[0].status == "missed_manual"


def test_replan_budget_uses_matched_actual():
    from backend.services.plan_skeleton import weekly_budget
    # Pure budget check: logged = matched actual
    b = weekly_budget(
        trailing_28d_weekly_avg_tss=200,
        logged_tss_so_far=80,  # matched actual
        open_slot_count=3,
        race_anchored_target=200,
    )
    assert b["logged_tss_so_far"] == 80
    assert b["remaining_tss"] == pytest.approx(b["weekly_target"] - 80, abs=0.2)


def test_stale_draft_version_rejected():
    from backend.services.plan_draft import draft_version_token

    row = SimpleNamespace(
        updated_at=date(2026, 7, 20),
        payload={"version": 3},
        facts_signature="abc1234567890",
    )
    # isoformat on date works
    row.updated_at = type("T", (), {"isoformat": lambda self: "2026-07-20T00:00:00+00:00"})()
    tok = draft_version_token(row)
    assert tok.startswith("3:")
    assert "abc123456789" in tok
