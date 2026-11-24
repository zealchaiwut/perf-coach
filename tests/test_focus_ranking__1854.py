"""P4-7 (#1854) — focus ranking, why-not card, work mapping and the queue into Plan."""
import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.services import focus_ranking as fr
from backend.services import revamp_suggest_sessions as rss

TODAY = date(2026, 11, 20)  # Friday; week Monday = 2026-11-16


def ax(name, score, *, stale=False, never=False):
    return {"axis": name, "score": None if never else score, "stale": stale, "never_measured": never}


FIXTURE = [
    ax("endurance", 60),
    ax("speed", 20),                   # huge gap but weight 0.05
    ax("economy", 44),
    ax("strength", 58),
    ax("mobility", 40),
    ax("power_to_weight", 61),
    ax("durability", 10, stale=True),  # biggest weighted gap but stale
]


def test_weights_sum_to_one_and_match_spec():
    assert sum(fr.WEIGHTS_MARATHON.values()) == pytest.approx(1.0)
    assert sum(fr.WEIGHTS_HALF.values()) == pytest.approx(1.0)
    assert fr.WEIGHTS_MARATHON == {
        "durability": 0.25, "economy": 0.20, "endurance": 0.20, "power_to_weight": 0.15,
        "strength": 0.10, "speed": 0.05, "mobility": 0.05,
    }
    assert fr.WEIGHTS_HALF["speed"] == 0.15 and fr.WEIGHTS_HALF["durability"] == 0.15


def test_distance_picks_weight_table():
    assert fr.weights_for_distance(42.195)[0] == "marathon"
    assert fr.weights_for_distance(21.0975)[0] == "half"
    assert fr.weights_for_distance(None)[0] == "marathon"


def test_ranking_excludes_stale_and_applies_weights():
    out = fr.rank_axes(FIXTURE, 42.195)
    # eligible weighted gaps: economy 56*.20=11.2, endurance 40*.20=8, power_to_weight 39*.15=5.85,
    # mobility 60*.05=3, strength 42*.10=4.2, speed 80*.05=4 ; durability stale (excluded)
    assert out["focus"]["axis"] == "economy"
    assert out["focus"]["weighted_gap"] == 11.2
    assert [w["axis"] for w in out["why_not"]] == [
        "endurance", "power_to_weight", "strength", "speed", "mobility", "durability",
    ]
    assert out["distance_class"] == "marathon"


def test_half_distance_changes_winner():
    axes = [ax("speed", 30), ax("economy", 60), ax("endurance", 80)]
    # marathon: speed .05*70=3.5 < economy .20*40=8
    assert fr.rank_axes(axes, 42.2)["focus"]["axis"] == "economy"
    # half: speed .15*70=10.5 > economy 8
    assert fr.rank_axes(axes, 21.1)["focus"]["axis"] == "speed"


def test_why_not_reasons():
    out = fr.rank_axes([ax("economy", 40), ax("mobility", 10), ax("strength", 80), ax("durability", 50, stale=True)], 42.2)
    reasons = {w["axis"]: w["reason"] for w in out["why_not"]}
    assert reasons["mobility"] == "Lower priority for this distance"
    assert reasons["strength"] == "Smaller weighted gap"
    assert reasons["durability"] == "Not ranked · anchor stale"
    assert len(out["why_not"]) == 6
    for w in out["why_not"]:
        assert not w["reason"].startswith(w["label"])
        if w["score_display"] is not None:
            assert str(w["score_display"]) not in w["reason"]


def test_never_measured_and_all_stale_have_no_focus():
    out = fr.rank_axes([ax("economy", None, never=True), ax("speed", 50, stale=True)], 42.2)
    assert out["focus"] is None
    assert "speed" in [w["axis"] for w in out["why_not"]]
    assert fr.rank_axes([], 42.2)["focus"] is None


def test_work_mapping():
    assert fr.WORK_MAP["economy"]["template_tags"] == ["plyo", "heavy_calf_raise", "drills"]
    assert "long_run_length" in fr.WORK_MAP["durability"]["template_tags"]
    assert fr.WORK_MAP["strength"]["template_tags"] == ["anchor_lift_block"]
    assert fr.WORK_MAP["mobility"]["template_tags"] == ["stretch_block"]
    assert fr.COACH_OWNED_AXES == {"endurance", "speed", "power_to_weight"}
    assert fr.QUEUEABLE_AXES == {"economy", "durability", "strength", "mobility"}


@pytest.mark.parametrize("axis", ["endurance", "speed", "power_to_weight"])
def test_coach_owned_axes_never_create_queue_records(axis):
    session = MagicMock()
    with pytest.raises(fr.QueueError) as e:
        fr.queue_focus_work(session, uuid.uuid4(), axis, TODAY, phase_for_week=lambda w: "build")
    assert e.value.status == 422 and "advice only" in e.value.detail
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_unknown_axis_rejected():
    with pytest.raises(fr.QueueError) as e:
        fr.validate_queue_axis("vo2max")
    assert e.value.status == 422


def test_earliest_week_skips_taper_and_race_weeks():
    mon = fr.week_monday(TODAY)
    phases = {mon: "taper", mon + timedelta(days=7): "race_week", mon + timedelta(days=14): "recover",
              mon + timedelta(days=21): "rebuild"}
    assert fr.earliest_queue_week(phases.get, TODAY) == mon + timedelta(days=21)
    phases[mon] = "build"
    assert fr.earliest_queue_week(phases.get, TODAY) == mon
    assert fr.earliest_queue_week(lambda w: "taper", TODAY) is None
    assert fr.earliest_queue_week(lambda w: "peak_hold", TODAY) is None


def test_queue_creates_dated_record_and_is_idempotent():
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    mon = fr.week_monday(TODAY)
    phase = lambda w: "build" if w == mon + timedelta(days=7) else "taper"
    row, created = fr.queue_focus_work(session, uuid.uuid4(), "economy", TODAY, phase_for_week=phase)
    assert created is True
    added = session.add.call_args[0][0]
    assert added.axis == "economy" and added.earliest_week == mon + timedelta(days=7)
    assert added.template_tags == ["plyo", "heavy_calf_raise", "drills"]
    assert added.tss_estimate == 22.0 and added.status == "queued"

    existing = SimpleNamespace(axis="economy")
    session2 = MagicMock()
    session2.query.return_value.filter.return_value.first.return_value = existing
    row, created = fr.queue_focus_work(session2, uuid.uuid4(), "economy", TODAY, phase_for_week=phase)
    assert row is existing and created is False
    session2.add.assert_not_called()


def test_no_eligible_week_is_409():
    session = MagicMock()
    session.query.return_value.filter.return_value.first.return_value = None
    with pytest.raises(fr.QueueError) as e:
        fr.queue_focus_work(session, uuid.uuid4(), "economy", TODAY, phase_for_week=lambda w: "taper")
    assert e.value.status == 409


def _row(axis, week):
    return SimpleNamespace(
        id=uuid.uuid4(), axis=axis, earliest_week=week, template_tags=list(fr.WORK_MAP[axis]["template_tags"]),
        tss_estimate=fr.WORK_MAP[axis]["tss_estimate"], status="queued",
    )


def test_queue_lands_in_p310_candidates_for_the_right_week_only():
    mon = fr.week_monday(TODAY)
    target = mon + timedelta(days=7)
    rows = [_row("economy", target), _row("durability", target), _row("strength", target + timedelta(days=7))]
    with patch.object(fr, "queued_items", return_value=rows):
        cands, notes = fr.candidates_for_week(MagicMock(), uuid.uuid4(), target, "build")
        assert [c["session_type"] for c in cands] == ["plyo"]
        assert cands[0]["candidate_id"].startswith("queue:")
        assert cands[0]["structure"]["template_tags"] == ["plyo", "heavy_calf_raise", "drills"]
        assert [n["axis"] for n in notes] == ["durability"]  # notes-only, not a session
        # earlier week: nothing yet
        assert fr.candidates_for_week(MagicMock(), uuid.uuid4(), mon, "build") == ([], [])
        # never in taper / race week
        assert fr.candidates_for_week(MagicMock(), uuid.uuid4(), target, "taper") == ([], [])
        assert fr.candidates_for_week(MagicMock(), uuid.uuid4(), target, "race_week") == ([], [])


def test_load_candidates_puts_queued_work_first():
    target = fr.week_monday(TODAY) + timedelta(days=7)
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.all.return_value = []
    with patch.object(fr, "queued_items", return_value=[_row("economy", target)]), \
            patch.object(rss, "estimate_historical_pace_and_tss", return_value={}):
        out = rss._load_candidates(session, uuid.uuid4(), race_week=False, week_start=target, phase="build")
        assert out[0]["candidate_id"].startswith("queue:") and out[0]["session_type"] == "plyo"
        taper = rss._load_candidates(session, uuid.uuid4(), race_week=False, week_start=target, phase="taper")
        assert not any(c["candidate_id"].startswith("queue:") for c in taper)


def test_apply_marks_queue_item_applied():
    q = SimpleNamespace(user_id=uuid.uuid4(), status="queued")
    session = MagicMock()
    session.get.return_value = q
    item = {"planned_date": "2026-11-24", "session_type": "plyo", "name": "x", "structure": {},
            "queue_item_id": str(uuid.uuid4())}
    out = rss.apply_week_suggestions(session, q.user_id, [item])
    assert out == {"created": 1} and q.status == "applied"


def test_endpoints_require_session_and_validate():
    from backend.main import app
    from backend.auth import resolve_user
    from backend.models import User

    c = TestClient(app)
    assert c.get("/api/performance/focus").status_code == 401
    assert c.post("/api/performance/focus/queue", json={}).status_code == 401
    app.dependency_overrides[resolve_user] = lambda: User(id=uuid.uuid4(), name="t")
    try:
        r = c.post("/api/performance/focus/queue", json={"axis": "speed"})
        assert r.status_code == 422 and "advice only" in r.json()["detail"]
        assert c.delete("/api/performance/focus/queue/not-a-uuid").status_code == 400
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_migration_model_and_page_wiring():
    from backend.models import PerformanceQueueItem
    for col in ("axis", "template_tags", "tss_estimate", "earliest_week", "status"):
        assert col in PerformanceQueueItem.__table__.columns.keys()
    src = Path("alembic/versions/8d8cd37743d3_create_performance_queue_items.py").read_text()
    assert "drop_table" in src and "table_exists" in src
    js = Path("frontend/js/v2-performance.js").read_text()
    assert "/api/performance/focus" in js and "/api/performance/focus/queue" in js
    assert "queued" in js
