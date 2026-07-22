"""Draft-first Plan UX: skeleton add (no sync LLM) + apply-slot."""
from __future__ import annotations

from datetime import date, timedelta

from backend.services import plan_skeleton_ops as ops
from backend.services.plan_draft import (
    apply_draft_slot,
    ensure_draft_shell,
    get_draft,
    upsert_draft,
)


def test_ops_add_easy_run_is_template_instant():
    result = ops.add([], day=1, kind="easy_run", confirm_warnings=True)
    assert result["blocked"] is False
    assert result["affected_slot_ids"] == []
    assert result.get("added_slot_id")
    sess = next(s for s in result["slots"] if s.get("slot_id") == result["added_slot_id"])
    assert sess["pending"] is False
    assert sess["source"] == "template"
    assert sess["workout_type"] == "run"
    # Template stamp should fill something actionable
    assert sess.get("intent") or sess.get("notes") or sess.get("blocks") or sess.get("exercises")


def test_ops_add_strength_is_template_instant():
    result = ops.add([], day=2, kind="light_strength", confirm_warnings=True)
    assert result["affected_slot_ids"] == []
    sess = next(s for s in result["slots"] if s.get("slot_id") == result["added_slot_id"])
    assert sess["pending"] is False
    assert sess["workout_type"] == "strength"


def test_ops_add_custom_keeps_user_blocks():
    blocks = [
        {"phase": "warmup", "duration_min": 8},
        {"phase": "main", "duration_min": 20, "repeat": 1, "target": "easy"},
        {"phase": "cooldown", "duration_min": 7},
    ]
    result = ops.add(
        [],
        day=3,
        kind="custom",
        confirm_warnings=True,
        custom={
            "workout_type": "run",
            "subtype": "tempo",
            "target_tss": 55,
            "duration_minutes": 35,
            "intent": "Tempo keep",
            "structure": {"blocks": blocks},
        },
    )
    assert result["blocked"] is False
    sess = next(s for s in result["slots"] if s.get("slot_id") == result["added_slot_id"])
    assert sess["intent"] == "Tempo keep"
    assert sess["blocks"] == blocks
    assert sess.get("exercises") in (None, [])


def test_apply_draft_slot_creates_one_planned():
    """Apply one draft slot → PlannedSession; draft stays open."""
    from sqlalchemy.orm import Session
    from backend.db import engine
    from backend.models import User, PlannedSession, PlanDraft
    import uuid
    import pytest

    if engine is None:
        pytest.skip("no engine")

    uid = uuid.uuid4()
    today = date.today()
    ws = today - timedelta(days=today.weekday())
    day = min(6, max(0, (today - ws).days + 1))
    if day > 6:
        day = 6

    with Session(engine) as db:
        u = User(id=uid, name=f"draft-ux-{uid.hex[:8]}", is_active=True)
        db.add(u)
        db.commit()
        try:
            ensure_draft_shell(db, uid, ws)
            sid = str(uuid.uuid4())
            payload = {
                "sessions": [{
                    "slot_id": sid,
                    "day_offset": day,
                    "workout_type": "run",
                    "subtype": "easy_run",
                    "target_tss": 30,
                    "duration_minutes": 30,
                    "intent": "Easy run",
                    "notes": "keep it easy",
                    "blocks": [{"name": "easy", "duration_min": 30}],
                    "exercises": None,
                    "source": "template",
                    "pending": False,
                }],
                "slots": [],
                "version": 1,
            }
            upsert_draft(db, uid, ws, payload, status="fresh")
            res = apply_draft_slot(db, uid, ws, slot_id=sid, today=today)
            assert res["ok"] is True, res
            assert res.get("created_id")
            db.commit()

            ps = db.get(PlannedSession, uuid.UUID(res["created_id"]))
            assert ps is not None
            assert ps.session_type == "run"

            draft = get_draft(db, uid, ws)
            assert draft["status"] != "applied"
            remaining = [
                s for s in (draft["payload"].get("sessions") or [])
                if s.get("slot_id") == sid
            ]
            assert remaining == []
        finally:
            db.query(PlannedSession).filter(PlannedSession.user_id == uid).delete()
            db.query(PlanDraft).filter(PlanDraft.user_id == uid).delete()
            db.query(User).filter(User.id == uid).delete()
            db.commit()
