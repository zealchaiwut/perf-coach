"""P4-13 (#1860) — race debrief: lesson parsing, decision links, Debrief chip, consult lessons."""
import uuid
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.models import Decision
from backend.services import decision_lessons as dl
from backend.services import race_list as rl
from backend.services import session_consult as sc

UID = uuid.uuid4()
RACE_ID = uuid.uuid4()

DEBRIEF = """prompt_version: race-debrief-v1
session_id: 3f2b1c0e-8a7d-4e6f-9b5a-1c2d3e4f5a6b

CHANGES TO APPLY
lessons:  Went out too fast in the first 5 km
          Take the first gel before 40 minutes
skeleton: add one 90 minute long run with fuel practice
goal:     keep 4:30:00
review:   long runs and first gel timing, 4 weeks
"""

CHECKIN = """CHANGES TO APPLY
prefs:    plyo_sessions_per_week  0 -> 1
skeleton: move long run Sat -> Sun
review:   weight trend + endurance score, 2 weeks
"""


# ── parse fixtures ───────────────────────────────────────────────────────────

def test_debrief_paste_with_two_lessons_parses_both():
    assert dl.parse_lessons(DEBRIEF) == ["Went out too fast in the first 5 km", "Take the first gel before 40 minutes"]
    assert dl.looks_like_race_debrief(DEBRIEF)
    assert dl.session_id_in(DEBRIEF) == "3f2b1c0e-8a7d-4e6f-9b5a-1c2d3e4f5a6b"


def test_ordinary_checkin_paste_is_untouched():
    assert dl.parse_lessons(CHECKIN) == []
    assert not dl.looks_like_race_debrief(CHECKIN)
    assert dl.session_id_in(CHECKIN) is None


def test_lesson_formats_and_limits():
    assert dl.parse_lessons("lessons:\n- a\n- b\n- c\n- d\n") == ["a", "b", "c"]  # at most three
    assert dl.parse_lessons("lessons:\n1. one\n2) two\nskeleton: x") == ["one", "two"]
    assert dl.parse_lessons("lessons: single\n\nreview: later") == ["single"]  # blank line ends it
    assert dl.parse_lessons("lessons:  <1-3 one-line lessons>") == []  # unfilled placeholder
    assert dl.parse_lessons("lessons: a: with colon\nreview: x") == ["a: with colon"]
    assert dl.parse_lessons(None) == [] and dl.parse_lessons("") == []
    assert len(dl.parse_lessons("lessons: " + "x" * 500)[0]) <= dl.LESSON_MAX_CHARS


def test_lessons_line_alone_marks_a_debrief():
    assert dl.looks_like_race_debrief("lessons: pace the first 5k")
    assert dl.looks_like_race_debrief("prompt_version: race-debrief-v1")
    assert not dl.looks_like_race_debrief("skeleton: more lessons: none")


def test_prompt_version_constant_matches_consult_module():
    assert dl.PROMPT_VERSION_RACE == sc.PROMPT_VERSION_RACE


# ── decisions: links, derived lessons, raw_text immutable ───────────────────

class FakeDB:
    def __init__(self, race=True, workout=None):
        self.added = []
        self._race = race
        self._workout = workout

    def query(self, model):
        q = MagicMock()
        name = getattr(model, "__name__", "")
        found = SimpleNamespace(id=RACE_ID) if (name == "Race" and self._race) else (self._workout if name == "Workout" else None)
        q.filter.return_value.first.return_value = found
        return q

    def add(self, o):
        self.added.append(o)

    def commit(self):
        pass

    def refresh(self, o):
        o.created_at = datetime(2026, 11, 8, tzinfo=timezone.utc)


@contextmanager
def decisions_api(db):
    from backend.auth import resolve_user
    from backend.main import app
    from backend.models import User
    from backend.routers import decisions as dr

    app.dependency_overrides[resolve_user] = lambda: User(id=UID, name="t")
    try:
        with patch.object(dr, "Session") as S:
            S.return_value.__enter__.return_value = db
            yield TestClient(app)
    finally:
        app.dependency_overrides.pop(resolve_user, None)


def test_post_with_race_links_it_and_returns_lessons_and_raw_text_untouched():
    db = FakeDB()
    with decisions_api(db) as c:
        r = c.post("/api/decisions", json={"raw_text": DEBRIEF, "race_id": str(RACE_ID)})
    assert r.status_code == 201
    body = r.json()
    assert body["race_id"] == str(RACE_ID) and body["session_id"] is None
    assert body["lessons"] == ["Went out too fast in the first 5 km", "Take the first gel before 40 minutes"]
    assert body["raw_text"] == DEBRIEF.strip()  # stored verbatim, lessons derived on read
    assert db.added[0].race_id == RACE_ID


def test_post_ordinary_checkin_has_no_link_and_no_lessons():
    with decisions_api(FakeDB()) as c:
        r = c.post("/api/decisions", json={"raw_text": CHECKIN})
    assert r.status_code == 201
    assert r.json()["race_id"] is None and r.json()["lessons"] == []


def test_post_rejects_bad_ids_and_unowned_race():
    with decisions_api(FakeDB()) as c:
        assert c.post("/api/decisions", json={"raw_text": DEBRIEF, "race_id": "nope"}).status_code == 422
    with decisions_api(FakeDB(race=False)) as c:
        assert c.post("/api/decisions", json={"raw_text": DEBRIEF, "race_id": str(RACE_ID)}).status_code == 404
        assert c.post("/api/decisions", json={"raw_text": DEBRIEF, "session_id": str(uuid.uuid4())}).status_code == 404


def test_session_link_resolves_its_race():
    wid = uuid.uuid4()
    workout = SimpleNamespace(id=wid, user_id=UID, workout_date=date(2026, 11, 8), distance_km=42.2)
    db = FakeDB(workout=workout)
    with decisions_api(db) as c, patch("backend.services.session_consult._find_linked_race",
                                       return_value=(SimpleNamespace(id=RACE_ID), True)):
        r = c.post("/api/decisions", json={"raw_text": DEBRIEF, "session_id": str(wid)})
    assert r.status_code == 201 and r.json()["session_id"] == str(wid) and r.json()["race_id"] == str(RACE_ID)


# ── model + migration ────────────────────────────────────────────────────────

def test_model_columns_and_migration_are_nullable_with_downgrade():
    assert Decision.__table__.c.race_id.nullable and Decision.__table__.c.session_id.nullable
    src = next(Path("alembic/versions").glob("*_decisions_race_session_links.py")).read_text()
    assert "column_exists" in src and "def downgrade" in src and "drop_column" in src
    assert "ondelete=\"SET NULL\"" in src


# ── Debrief chip on race rows ────────────────────────────────────────────────

def test_debrief_by_race_maps_newest_linked_decision():
    older = SimpleNamespace(id=uuid.uuid4(), race_id=RACE_ID, raw_text=CHECKIN, decided_on=date(2026, 11, 1))
    newer = SimpleNamespace(id=uuid.uuid4(), race_id=RACE_ID, raw_text=DEBRIEF, decided_on=date(2026, 11, 9))
    db = MagicMock()
    db.query.return_value.filter.return_value.order_by.return_value.all.return_value = [newer, older]
    out = rl.debrief_by_race(db, UID, [RACE_ID])
    assert list(out) == [str(RACE_ID)]
    assert out[str(RACE_ID)] == {
        "decision_id": str(newer.id), "decided_on": "2026-11-09", "lessons_count": 2,
        "link": f"/coach#decision-{newer.id}",
    }
    assert rl.debrief_by_race(db, UID, []) == {}


def test_chip_appears_on_completed_row_only_when_linked():
    from backend.models import Race

    race = SimpleNamespace(id=RACE_ID, name="Bangsaen21", race_date=date(2026, 11, 8), distance_km=21.1,
                           goal_time_seconds=7200, goal_pace_seconds_per_km=341, priority="B", race_type="race",
                           status="done", actual_time_seconds=6900, user_id=UID)
    linked = SimpleNamespace(id=uuid.uuid4(), race_id=RACE_ID, raw_text=DEBRIEF, decided_on=date(2026, 11, 9))

    def run(decisions):
        db = MagicMock()

        def query(arg):
            q = MagicMock()
            if arg is Race:
                q.filter.return_value.order_by.return_value.all.return_value = [race]
            elif getattr(arg, "__name__", "") == "Decision":
                q.filter.return_value.order_by.return_value.all.return_value = decisions
            else:
                q.filter.return_value.all.return_value = []
            return q

        db.query.side_effect = query
        with patch.object(rl, "next_a_race", return_value=None):
            return rl.build_race_list(db, UID, date(2026, 11, 20))["completed"][0]

    assert run([linked])["debrief"]["link"].endswith(str(linked.id))
    assert run([])["debrief"] is None


def test_chip_and_link_wiring_in_frontend():
    js = Path("frontend/js/v2-performance.js").read_text()
    assert "data-debrief-chip" in js and "debriefChip(r)" in js
    coach = Path("frontend/js/coach.js").read_text()
    assert 'id="decision-' in coach and "focusHashDecision" in coach and "payload.race_id" in coach
    assert "race-debrief-v1" in coach and "lessons" in coach
    assert 'id="dc-race"' in Path("frontend/pages/coach.html").read_text()


# ── consult prompt carries linked lessons ────────────────────────────────────

def _race(rid=None, **kw):
    base = dict(id=rid or uuid.uuid4(), user_id=UID, race_date=date(2026, 9, 27), distance_km=21.1,
                actual_time_seconds=6600)
    base.update(kw)
    return SimpleNamespace(**base)


def _consult_session(decisions):
    db = MagicMock()

    def query(arg):
        q = MagicMock()
        if getattr(arg, "__name__", "") == "Decision":
            q.filter.return_value.order_by.return_value.all.return_value = decisions
        else:  # the race-day workout lookup
            q.filter.return_value.order_by.return_value.first.return_value = None
        return q

    db.query.side_effect = query
    return db


def test_previous_races_block_prints_linked_lessons():
    r = _race()
    d = SimpleNamespace(raw_text=DEBRIEF, decided_on=date(2026, 9, 28), created_at=datetime(2026, 9, 28, tzinfo=timezone.utc))
    lines = sc._previous_race_lines(_consult_session([d]), [r])
    assert len(lines) == 1
    assert "lessons: (1) Went out too fast in the first 5 km. (2) Take the first gel before 40 minutes." in lines[0]
    assert "none recorded" not in lines[0]


def test_previous_races_block_keeps_none_recorded_without_lessons():
    r = _race()
    plain = SimpleNamespace(raw_text=CHECKIN, decided_on=date(2026, 9, 28), created_at=datetime(2026, 9, 28, tzinfo=timezone.utc))
    assert sc._previous_race_lines(_consult_session([]), [r])[0].endswith("lessons: none recorded")
    assert sc._previous_race_lines(_consult_session([plain]), [r])[0].endswith("lessons: none recorded")


def test_previous_races_block_dedupes_and_caps_lessons():
    r = _race()
    mk = lambda text, day: SimpleNamespace(raw_text=text, decided_on=date(2026, 9, day), created_at=datetime(2026, 9, day, tzinfo=timezone.utc))
    ds = [mk("lessons: a\n b\n c", 29), mk("lessons: a\n d\n e", 28), mk("lessons: f\n g\n h", 27)]
    line = sc._previous_race_lines(_consult_session(ds), [r])[0]
    assert line.count("(") >= 1 and "(6)" in line and "(7)" not in line
    assert line.count(" a.") == 1  # duplicate dropped
