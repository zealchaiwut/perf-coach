"""Phase 0 — the consult loop's system of record (lean-program spec §5).

The acceptance criterion for Phase 0 is one round trip: a consult produces a
change list → pasted into one field → appears in the next export → the following
consult references it by date. Without it, the same conversation happens in
October with no way to know whether the swaps worked.

Two design choices are pinned here because they are the ones most likely to get
"improved" into a project:

- **No parser.** ``raw_text`` is stored verbatim. The MVP is one textarea.
- **``raw_text`` is immutable.** Only outcome fields can be patched, so the
  history can't be rewritten once the answer is known.
"""
from __future__ import annotations

import datetime
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.pool import StaticPool
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session as _OrmSess

try:  # pragma: no cover - registration is idempotent per process
    @compiles(JSONB, "sqlite")
    def _jsonb_as_json_on_sqlite(type_, compiler, **kw):  # noqa: D401
        return "JSON"
except Exception:  # pragma: no cover - already registered by another module
    pass

from backend.auth import resolve_user  # noqa: E402
from backend.main import app  # noqa: E402
from backend.models import Base, Decision, User  # noqa: E402
from backend.routers import decisions as decisions_router  # noqa: E402
from backend.services import coach_export as ce  # noqa: E402

TODAY = datetime.date(2026, 7, 30)
_UTC = datetime.timezone.utc

CHANGES_BLOCK = """CHANGES TO APPLY
prefs:    plyo_sessions_per_week  0 → 1
skeleton: move long run Sat → Sun
goal:     none
habits:   protein-first, every meal
review:   weight trend + endurance score, 2 weeks"""


@pytest.fixture
def db_engine():
    """In-memory SQLite shared across threads.

    ``TestClient`` runs the app in a worker thread. With the default pool each
    thread gets its OWN connection, and for ``:memory:`` a connection *is* the
    database — so the app thread would see an empty schema. StaticPool +
    ``check_same_thread=False`` pins every caller to one connection.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _register_pg_functions(dbapi_conn, _record):  # pragma: no cover - plumbing
        dbapi_conn.create_function(
            "now", 0, lambda: datetime.datetime.now(_UTC).isoformat(sep=" ")
        )
        dbapi_conn.create_function("gen_random_uuid", 0, lambda: str(uuid.uuid4()))

    Base.metadata.create_all(
        engine, tables=[User.__table__, Decision.__table__]
    )
    return engine


@pytest.fixture
def user_id(db_engine):
    with _OrmSess(db_engine) as session:
        user = User(
            id=uuid.uuid4(),
            name="lean-program",
            is_admin=False,
            is_active=True,
            created_at=datetime.datetime.now(_UTC),
        )
        session.add(user)
        session.commit()
        return user.id


class _StubUser:
    def __init__(self, uid) -> None:
        self.id = uid
        self.name = "lean-program"


@pytest.fixture
def client(db_engine, user_id, monkeypatch):
    monkeypatch.setattr(decisions_router, "engine", db_engine)
    app.dependency_overrides[resolve_user] = lambda: _StubUser(user_id)
    yield TestClient(app)
    app.dependency_overrides.pop(resolve_user, None)


# ── Storing a decision ───────────────────────────────────────────────────────

def test_pasting_a_changes_block_stores_it_verbatim(client):
    """One textarea, no parser — the block goes in exactly as the consult wrote it."""
    res = client.post("/api/decisions", json={"raw_text": CHANGES_BLOCK})
    assert res.status_code == 201
    body = res.json()
    assert body["raw_text"] == CHANGES_BLOCK
    assert body["source"] == "consult"
    assert body["applied"] is True


def test_decided_on_defaults_to_today(client):
    body = client.post("/api/decisions", json={"raw_text": "swap the oil"}).json()
    assert body["decided_on"] == datetime.date.today().isoformat()


def test_review_date_defaults_rather_than_being_left_null(client):
    """A decision with no review date is one nobody ever checks."""
    body = client.post("/api/decisions", json={"raw_text": "swap the oil"}).json()
    assert body["review_on"] is not None
    expected = datetime.date.today() + datetime.timedelta(
        days=decisions_router.DEFAULT_REVIEW_DAYS
    )
    assert body["review_on"] == expected.isoformat()


def test_explicit_review_date_is_kept(client):
    body = client.post(
        "/api/decisions",
        json={"raw_text": "swap the oil", "review_on": "2026-08-20"},
    ).json()
    assert body["review_on"] == "2026-08-20"


def test_tags_are_trimmed_and_blanks_dropped(client):
    body = client.post(
        "/api/decisions",
        json={"raw_text": "x", "tags": ["  fuel ", "", "   ", "training"]},
    ).json()
    assert body["tags"] == ["fuel", "training"]


@pytest.mark.parametrize("raw", ["", "   ", "\n"])
def test_empty_paste_is_rejected(client, raw):
    res = client.post("/api/decisions", json={"raw_text": raw})
    assert res.status_code == 422


def test_oversized_paste_is_rejected(client):
    res = client.post(
        "/api/decisions",
        json={"raw_text": "x" * (decisions_router.RAW_TEXT_MAX_CHARS + 1)},
    )
    assert res.status_code == 422


def test_future_decision_date_is_rejected(client):
    future = (datetime.date.today() + datetime.timedelta(days=3)).isoformat()
    res = client.post("/api/decisions", json={"raw_text": "x", "decided_on": future})
    assert res.status_code == 422


def test_bad_date_format_is_rejected(client):
    res = client.post("/api/decisions", json={"raw_text": "x", "decided_on": "30/07/2026"})
    assert res.status_code == 422


def test_too_many_tags_rejected(client):
    res = client.post(
        "/api/decisions",
        json={"raw_text": "x", "tags": [f"t{i}" for i in range(decisions_router.MAX_TAGS + 1)]},
    )
    assert res.status_code == 422


# ── Reading the log ──────────────────────────────────────────────────────────

def test_log_returns_newest_first(client):
    for day, text in (("2026-07-01", "first"), ("2026-07-20", "second"), ("2026-07-28", "third")):
        client.post("/api/decisions", json={"raw_text": text, "decided_on": day})
    rows = client.get("/api/decisions").json()["decisions"]
    assert [r["raw_text"] for r in rows] == ["third", "second", "first"]


def test_log_respects_the_limit(client):
    for i in range(5):
        client.post("/api/decisions", json={"raw_text": f"d{i}"})
    assert len(client.get("/api/decisions?limit=2").json()["decisions"]) == 2


def test_log_is_scoped_to_the_session_user(client, db_engine, user_id):
    """Another athlete's decisions must never appear in my log."""
    client.post("/api/decisions", json={"raw_text": "mine"})
    with _OrmSess(db_engine) as session:
        other = User(
            id=uuid.uuid4(), name="someone-else", is_admin=False, is_active=True,
            created_at=datetime.datetime.now(_UTC),
        )
        session.add(other)
        session.commit()
        session.add(
            Decision(
                id=uuid.uuid4(), user_id=other.id, decided_on=TODAY,
                source="consult", raw_text="theirs", applied=True,
            )
        )
        session.commit()

    rows = client.get("/api/decisions").json()["decisions"]
    assert [r["raw_text"] for r in rows] == ["mine"]


def test_endpoints_require_a_session(db_engine, monkeypatch):
    monkeypatch.setattr(decisions_router, "engine", db_engine)
    app.dependency_overrides.pop(resolve_user, None)
    anon = TestClient(app)
    assert anon.get("/api/decisions").status_code in (401, 403)
    assert anon.post("/api/decisions", json={"raw_text": "x"}).status_code in (401, 403)


# ── Closing the loop ─────────────────────────────────────────────────────────

def test_outcome_can_be_recorded_later(client):
    """The half of the loop that makes the log worth keeping."""
    created = client.post("/api/decisions", json={"raw_text": CHANGES_BLOCK}).json()
    res = client.patch(
        f"/api/decisions/{created['id']}",
        json={"outcome_note": "held for 2 weeks, trend moved -0.4 kg"},
    )
    assert res.status_code == 200
    assert res.json()["outcome_note"] == "held for 2 weeks, trend moved -0.4 kg"


def test_raw_text_is_immutable(client):
    """What the consult said stays what it said — the history can't be rewritten."""
    created = client.post("/api/decisions", json={"raw_text": CHANGES_BLOCK}).json()
    client.patch(f"/api/decisions/{created['id']}", json={"raw_text": "something else"})
    rows = client.get("/api/decisions").json()["decisions"]
    assert rows[0]["raw_text"] == CHANGES_BLOCK


def test_a_declined_change_can_be_marked_not_applied(client):
    created = client.post("/api/decisions", json={"raw_text": "add a second plyo day"}).json()
    res = client.patch(f"/api/decisions/{created['id']}", json={"applied": False})
    assert res.json()["applied"] is False


def test_patching_someone_elses_decision_is_a_404(client, db_engine):
    with _OrmSess(db_engine) as session:
        other = User(
            id=uuid.uuid4(), name="other", is_admin=False, is_active=True,
            created_at=datetime.datetime.now(_UTC),
        )
        session.add(other)
        session.commit()
        d = Decision(
            id=uuid.uuid4(), user_id=other.id, decided_on=TODAY,
            source="consult", raw_text="theirs", applied=True,
        )
        session.add(d)
        session.commit()
        other_id = str(d.id)

    assert client.patch(f"/api/decisions/{other_id}", json={"applied": False}).status_code == 404
    assert client.delete(f"/api/decisions/{other_id}").status_code == 404


def test_mispasted_entry_can_be_deleted(client):
    created = client.post("/api/decisions", json={"raw_text": "oops"}).json()
    assert client.delete(f"/api/decisions/{created['id']}").status_code == 204
    assert client.get("/api/decisions").json()["decisions"] == []


def test_invalid_id_is_a_400_not_a_500(client):
    assert client.patch("/api/decisions/not-a-uuid", json={"applied": False}).status_code == 400
    assert client.delete("/api/decisions/not-a-uuid").status_code == 400


# ── The export block ─────────────────────────────────────────────────────────

def _assemble(db_engine, uid, today=TODAY):
    with _OrmSess(db_engine) as session:
        user = session.get(User, uid)
        return ce._assemble_decisions(session, user, today)


def test_export_carries_the_decision_history(client, db_engine, user_id):
    client.post(
        "/api/decisions",
        json={"raw_text": CHANGES_BLOCK, "decided_on": "2026-07-16", "tags": ["fuel"]},
    )
    rows = _assemble(db_engine, user_id)
    assert len(rows) == 1
    assert rows[0]["raw_text"] == CHANGES_BLOCK
    assert rows[0]["tags"] == ["fuel"]
    assert rows[0]["decided_on"] == "2026-07-16"


def test_export_states_how_long_ago_each_decision_was(client, db_engine, user_id):
    """"Two weeks ago" is what the coach needs; a bare date makes it do arithmetic."""
    client.post("/api/decisions", json={"raw_text": "x", "decided_on": "2026-07-16"})
    assert _assemble(db_engine, user_id)[0]["days_ago"] == 14


def test_export_is_capped_at_the_row_limit(client, db_engine, user_id):
    for i in range(ce.DECISION_ROWS + 5):
        day = TODAY - datetime.timedelta(days=i)
        client.post("/api/decisions", json={"raw_text": f"d{i}", "decided_on": day.isoformat()})
    assert len(_assemble(db_engine, user_id)) == ce.DECISION_ROWS


def test_a_decision_past_its_review_date_is_flagged(client, db_engine, user_id):
    """The single most actionable thing in the block — computed here, not left
    to the reader to work out."""
    client.post(
        "/api/decisions",
        json={"raw_text": "swap the oil", "decided_on": "2026-07-01", "review_on": "2026-07-15"},
    )
    assert _assemble(db_engine, user_id)[0]["due_for_review"] is True


def test_a_reviewed_decision_is_not_flagged_again(client, db_engine, user_id):
    created = client.post(
        "/api/decisions",
        json={"raw_text": "swap the oil", "decided_on": "2026-07-01", "review_on": "2026-07-15"},
    ).json()
    client.patch(f"/api/decisions/{created['id']}", json={"outcome_note": "worked"})
    assert _assemble(db_engine, user_id)[0]["due_for_review"] is False


def test_a_future_review_date_is_not_flagged(client, db_engine, user_id):
    client.post(
        "/api/decisions",
        json={"raw_text": "x", "decided_on": "2026-07-28", "review_on": "2026-08-20"},
    )
    assert _assemble(db_engine, user_id)[0]["due_for_review"] is False


def test_no_decisions_yields_an_empty_list_not_an_error(db_engine, user_id):
    assert _assemble(db_engine, user_id) == []


# ── Phase 0 acceptance: the full round trip ──────────────────────────────────

def test_round_trip_consult_to_export_references_it_by_date(client, db_engine, user_id):
    """Spec §5 acceptance: a change list pasted into one field appears in the
    next export, dated, so the following consult can reference it."""
    client.post(
        "/api/decisions",
        json={"raw_text": CHANGES_BLOCK, "decided_on": "2026-07-16"},
    )
    export_rows = _assemble(db_engine, user_id)
    blob = ce.build_consult_blob({"decisions": export_rows, "volume_plays": []})

    assert "2026-07-16" in blob
    assert "plyo_sessions_per_week" in blob
    assert "Read `decisions[]` first" in blob
