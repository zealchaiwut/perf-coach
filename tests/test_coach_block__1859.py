"""P4-12 (#1859) — coach block: check-in, review due, evidence chips, history."""
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.services import coach_block as cb

UID = uuid.uuid4()
TODAY = date(2026, 11, 8)  # a Sunday

RAW = """CHANGES TO APPLY
prefs:    plyo_sessions_per_week  0 -> 1
skeleton: move long run Sat -> Sun
goal:     goal pace 6:10 -> 6:05
review:   long runs completed and first gel timing, 2 weeks
review:   check the endurance score
"""


def decision(**kw):
    base = dict(id=uuid.uuid4(), decided_on=date(2026, 10, 25), raw_text=RAW, tags=[], applied=True,
                outcome_note=None, review_on=TODAY, created_at=datetime(2026, 10, 25, tzinfo=timezone.utc),
                source="consult", user_id=UID)
    base.update(kw)
    return SimpleNamespace(**base)


def wk(d, mins, gel=None, wtype="run"):
    return SimpleNamespace(workout_date=d, duration_seconds=mins * 60, workout_type=wtype, first_gel_minute=gel)


# ── due logic boundary ───────────────────────────────────────────────────────

def test_due_today_yes_tomorrow_no_overdue_yes():
    assert cb.is_due(TODAY, None, True, TODAY) is True
    assert cb.is_due(date(2026, 11, 9), None, True, TODAY) is False
    assert cb.is_due(date(2026, 11, 1), None, True, TODAY) is True
    assert cb.is_due(None, None, True, TODAY) is False


def test_outcome_or_not_applied_clears_due():
    assert cb.is_due(TODAY, "worked", True, TODAY) is False
    assert cb.is_due(TODAY, "   ", True, TODAY) is True  # blank note is no outcome
    assert cb.is_due(TODAY, None, False, TODAY) is False


def test_newest_due_picks_latest_decided_and_skips_others():
    old = decision(decided_on=date(2026, 10, 1), review_on=date(2026, 10, 15))
    new = decision(decided_on=date(2026, 10, 25), review_on=TODAY)
    future = decision(decided_on=date(2026, 11, 5), review_on=date(2026, 11, 20))
    answered = decision(decided_on=date(2026, 11, 6), review_on=TODAY, outcome_note="ok")
    assert cb.newest_due([answered, future, new, old], TODAY) is new
    assert cb.newest_due([future, answered], TODAY) is None


# ── text reading ─────────────────────────────────────────────────────────────

def test_review_lines_and_summary_come_from_raw_text():
    assert cb.review_lines(RAW) == ["long runs completed and first gel timing, 2 weeks", "check the endurance score"]
    assert cb.summary_line(RAW) == "skeleton: move long run Sat -> Sun"
    assert cb.summary_line("CHANGES TO APPLY\ngoal:  pace 6:10 -> 6:05\nskeleton: later").startswith("goal:")
    assert cb.summary_line("CHANGES TO APPLY\nhabits: protein") == "habits: protein"
    assert cb.summary_line("just a note") == "just a note"
    assert cb.review_lines("no structure here") == []
    assert len(cb.summary_line("skeleton: " + "x" * 400)) <= cb.SUMMARY_MAX_CHARS


def test_status_chips_open_kept_skipped():
    assert cb.status_of(None, True) == "open"
    assert cb.status_of("held", True) == "kept"
    assert cb.status_of(None, False) == "skipped"
    assert cb.status_of("held", False) == "skipped"


# ── evidence chips: hits and misses ──────────────────────────────────────────

def test_chip_hit_long_runs_count_in_period():
    runs = [wk(date(2026, 10, 26), 100), wk(date(2026, 11, 2), 80), wk(date(2026, 11, 3), 40),
            wk(date(2026, 10, 20), 120), wk(date(2026, 11, 4), 100, wtype="ride")]
    chips = cb.evidence_chips(["How many long runs did I get in?"], runs, date(2026, 10, 25), TODAY)
    assert chips == [{"key": "long_runs", "label": "Long runs since 2026-10-25", "value": 2}]


def test_chip_hit_first_gel_minutes_when_logged():
    runs = [wk(date(2026, 10, 26), 100, gel=45), wk(date(2026, 11, 2), 100, gel=30)]
    chips = cb.evidence_chips(["first gel timing"], runs, date(2026, 10, 25), TODAY)
    assert chips == [{"key": "first_gel", "label": "First gel, 2026-11-02", "value": 30, "unit": "min"}]


def test_chip_misses_are_silently_absent():
    runs = [wk(date(2026, 10, 26), 100)]
    assert cb.evidence_chips(["check the endurance score"], runs, date(2026, 10, 25), TODAY) == []
    assert cb.evidence_chips([], runs, date(2026, 10, 25), TODAY) == []
    # gel phrase but nothing logged (P1-9 not built / no data): no chip, no error
    assert cb.evidence_chips(["first gel timing"], runs, date(2026, 10, 25), TODAY) == []
    no_attr = [SimpleNamespace(workout_date=date(2026, 10, 26), duration_seconds=6000, workout_type="run")]
    assert cb.evidence_chips(["first gel timing"], no_attr, date(2026, 10, 25), TODAY) == []


# ── weekly check-in entry ────────────────────────────────────────────────────

def test_checkin_due_or_done_for_this_week():
    assert cb.week_bounds(TODAY) == (date(2026, 11, 2), date(2026, 11, 8))
    # A decision dated this week is not the check-in record (#1897).
    due = cb.checkin_state([decision(decided_on=date(2026, 11, 2))], TODAY)
    assert due["state"] == "due" and due["link"] == "/v2/performance/check-in" and due["week_start"] == "2026-11-02"
    assert cb.checkin_state([], TODAY)["state"] == "due"
    uid = uuid.uuid4()
    with patch("backend.services.weekly_checkin.is_week_checkin_done", return_value=True):
        done = cb.checkin_state([], TODAY, session=object(), user_id=uid)
    assert done["state"] == "done"


# ── assembled block ──────────────────────────────────────────────────────────

def test_build_block_review_card_and_history():
    d1 = decision()
    d2 = decision(decided_on=date(2026, 10, 1), review_on=date(2026, 10, 15), outcome_note="held 2 weeks")
    d3 = decision(decided_on=date(2026, 9, 1), review_on=date(2026, 9, 15), applied=False)
    block = cb.build_coach_block([d1, d2, d3], [wk(date(2026, 10, 26), 100, gel=40)], TODAY)
    assert block["review_due"]["id"] == str(d1.id)
    assert block["review_due"]["review_lines"][0].startswith("long runs")
    assert {c["key"] for c in block["review_due"]["chips"]} == {"long_runs", "first_gel"}
    assert [h["status"] for h in block["history"]] == ["open", "kept", "skipped"]
    assert block["history"][0]["summary"] == "skeleton: move long run Sat -> Sun"
    assert block["paste_link"] == "/coach#paste"
    assert cb.build_coach_block([], [], TODAY)["review_due"] is None


# ── outcome save and did-not-apply round trip through the decisions PATCH ────

class FakeDB:
    def __init__(self, obj):
        self.obj = obj

    def query(self, *_a):
        q = MagicMock()
        q.filter.return_value.first.return_value = self.obj
        return q

    def commit(self):
        pass

    def refresh(self, _o):
        pass


@contextmanager
def decisions_api(obj):
    from backend.auth import resolve_user
    from backend.main import app
    from backend.models import User
    from backend.routers import decisions as dr

    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        with patch.object(dr, "Session") as S:
            S.return_value.__enter__.return_value = FakeDB(obj)
            yield TestClient(app)
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def _patch_json(obj, body):
    # _decision_dict needs real dates/strings only
    with decisions_api(obj) as client:
        r = client.patch(f"/api/decisions/{obj.id}", json=body)
    return r


def test_outcome_save_round_trip_clears_due_and_marks_kept():
    d = decision()
    assert cb.build_coach_block([d], [], TODAY)["review_due"] is not None
    r = _patch_json(d, {"outcome_note": "  held for two weeks  "})
    assert r.status_code == 200 and r.json()["outcome_note"] == "held for two weeks"
    block = cb.build_coach_block([d], [], TODAY)
    assert block["review_due"] is None and block["history"][0]["status"] == "kept"
    assert block["history"][0]["outcome_note"] == "held for two weeks"


def test_did_not_apply_round_trip_marks_skipped_and_not_due():
    d = decision()
    r = _patch_json(d, {"applied": False})
    assert r.status_code == 200 and r.json()["applied"] is False
    block = cb.build_coach_block([d], [], TODAY)
    assert block["review_due"] is None and block["history"][0]["status"] == "skipped"
    assert d.raw_text == RAW  # raw_text stays immutable


# ── endpoint / page ──────────────────────────────────────────────────────────

def test_endpoint_requires_session():
    from backend.auth import resolve_user
    from backend.main import app
    from backend.models import User

    assert TestClient(app).get("/api/performance/coach-block").status_code == 401
    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        with patch("backend.services.coach_block.fetch_coach_block", return_value={"history": []}):
            r = TestClient(app).get("/api/performance/coach-block")
        assert r.status_code == 200 and r.json() == {"history": []}
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_page_wiring_and_paste_anchor():
    html = Path("frontend/pages/v2-performance.html").read_text()
    js = Path("frontend/js/v2-performance.js").read_text()
    coach_html = Path("frontend/pages/coach.html").read_text()
    assert 'id="v2-perf-coach"' in html and 'id="paste"' in coach_html
    csrf = Path("frontend/js/lib/csrf-fetch.js").read_text()
    for needle in ("window.NavCopy.copyForClaude", "NavCopy.CONSULT_ENDPOINT", "/api/coach/consult", "data-review-due",
                   "data-save-outcome", "data-not-applied", "outcome_note", "applied: false", "data-evidence",
                   "data-paste-link", "data-checkin-state", "applyCoach"):
        assert needle in js
    assert "X-CSRF-Token" in csrf
    assert "/api/csrf-token" not in js
