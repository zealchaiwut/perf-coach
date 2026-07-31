"""Phase 3 — three goal habits and correlation evidence (spec §8, §12).

Two decisions are pinned here because both are easy to erode by accident:

- **D6: three goal habits only.** Weigh-in, protein-first, long-run fuel. Two of
  them verify themselves; only protein-first asks for a tap.
- **D8: no streaks, especially not near food.** A streak turns one missed day
  into a reason to stop. The habit surface shows correlation sentences instead —
  an argument for keeping the habit, not a scold about yesterday.

Spec §12 asks for a static test that no streak computation reaches a food habit
surface. That test reads the source, because the regression it guards against is
somebody wiring an existing streak helper into the goal-habit surface later.
"""
from __future__ import annotations

import datetime
import inspect
import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session as _OrmSess
from sqlalchemy.pool import StaticPool

try:  # pragma: no cover - registration is idempotent per process
    @compiles(JSONB, "sqlite")
    def _jsonb_as_json_on_sqlite(type_, compiler, **kw):  # noqa: D401
        return "JSON"
except Exception:  # pragma: no cover - already registered by another module
    pass

from backend.models import Base, Habit, HabitLog, User, WeightEntry, Workout  # noqa: E402
from backend.services import goal_habits, habit_evidence  # noqa: E402
from backend.services.goal_habits import (  # noqa: E402
    GOAL_HABIT_KEYS,
    LONG_RUN_FUEL_SOURCE,
    LONG_RUN_MIN_MINUTES,
    WEIGH_IN_SOURCE,
    ensure_goal_habits,
    goal_habit_ids,
)
from backend.services.habit_autofill import _compute_date_values  # noqa: E402
from backend.services.habit_evidence import (  # noqa: E402
    MIN_PAIRS,
    MIN_PER_GROUP,
    build_evidence,
    compare_groups,
)

TODAY = datetime.date(2026, 7, 30)
_UTC = datetime.timezone.utc


@pytest.fixture
def db_engine():
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
        engine,
        tables=[
            User.__table__, Habit.__table__, HabitLog.__table__,
            WeightEntry.__table__, Workout.__table__,
        ],
    )
    return engine


@pytest.fixture
def session_user(db_engine):
    with _OrmSess(db_engine) as session:
        user = User(
            id=uuid.uuid4(), name="lean", is_admin=False, is_active=True,
            created_at=datetime.datetime.now(_UTC),
        )
        session.add(user)
        session.commit()
        yield session, user.id


# ═════════════════════════════════════════════════════════════════════════════
# The three goal habits (D6)
# ═════════════════════════════════════════════════════════════════════════════

def test_exactly_three_goal_habits(session_user):
    session, uid = session_user
    created = ensure_goal_habits(session, uid)
    session.commit()
    assert set(created) == set(GOAL_HABIT_KEYS)
    assert len(GOAL_HABIT_KEYS) == 3


def test_goal_habits_are_named_and_marked_as_focus(session_user):
    session, uid = session_user
    created = ensure_goal_habits(session, uid)
    session.commit()
    assert created["weigh_in"].name == "Morning weigh-in"
    assert created["protein_first"].name == "Protein first"
    assert created["long_run_fuel"].name == "Long-run fuel"
    assert all(h.is_focus is True for h in created.values())
    assert all(h.section == "training" for h in created.values())


def test_two_of_three_verify_themselves(session_user):
    """Only protein-first asks for a tap — the other two autofill."""
    session, uid = session_user
    created = ensure_goal_habits(session, uid)
    session.commit()
    assert created["weigh_in"].auto_fill_source == WEIGH_IN_SOURCE
    assert created["long_run_fuel"].auto_fill_source == LONG_RUN_FUEL_SOURCE
    assert created["protein_first"].auto_fill_source is None


def test_ensure_is_idempotent(session_user):
    session, uid = session_user
    first = ensure_goal_habits(session, uid)
    session.commit()
    first_ids = {k: str(v.id) for k, v in first.items()}
    second = ensure_goal_habits(session, uid)
    session.commit()
    assert {k: str(v.id) for k, v in second.items()} == first_ids
    assert session.query(Habit).filter(Habit.user_id == uid).count() == 3


def test_an_existing_habit_is_adopted_not_duplicated(session_user):
    """An athlete who already tracked one of these keeps their history."""
    session, uid = session_user
    existing = Habit(
        id=uuid.uuid4(), user_id=uid, name="Protein first", habit_type="binary",
        schedule_type="daily", tracking_type="daily_checkmark", active=True,
        is_archived=False, sort_order=9, display_order=9, section="general",
        created_at=datetime.datetime.now(_UTC),
    )
    session.add(existing)
    session.commit()

    created = ensure_goal_habits(session, uid)
    session.commit()
    assert str(created["protein_first"].id) == str(existing.id)
    assert session.query(Habit).filter(Habit.user_id == uid).count() == 3
    assert created["protein_first"].section == "training"


def test_general_habits_are_left_alone(session_user):
    """Journaling and the like stay in general, untouched."""
    session, uid = session_user
    other = Habit(
        id=uuid.uuid4(), user_id=uid, name="Journaling", habit_type="binary",
        schedule_type="daily", tracking_type="daily_checkmark", active=True,
        is_archived=False, sort_order=5, display_order=5, section="general",
        created_at=datetime.datetime.now(_UTC),
    )
    session.add(other)
    session.commit()

    ensure_goal_habits(session, uid)
    session.commit()
    session.refresh(other)
    assert other.section == "general"
    assert other.is_focus in (None, False)


def test_goal_habit_ids_returns_nothing_before_they_exist(session_user):
    session, uid = session_user
    assert goal_habit_ids(session, uid) == {}


def test_goal_habit_ids_maps_every_role_after_ensure(session_user):
    session, uid = session_user
    ensure_goal_habits(session, uid)
    session.commit()
    assert set(goal_habit_ids(session, uid)) == set(GOAL_HABIT_KEYS)


# ═════════════════════════════════════════════════════════════════════════════
# Long-run fuel autofill
# ═════════════════════════════════════════════════════════════════════════════

class _Run:
    def __init__(self, *, minutes, fuelled, wtype="run", day=TODAY):
        self.workout_date = day
        self.workout_type = wtype
        self.duration_seconds = int(minutes * 60)
        self.fuelled = fuelled


def test_a_fuelled_long_run_ticks_the_habit():
    values = _compute_date_values(
        LONG_RUN_FUEL_SOURCE, [_Run(minutes=110, fuelled=True)]
    )
    assert values == {TODAY: 1.0}


def test_an_unfuelled_long_run_does_not_tick():
    values = _compute_date_values(
        LONG_RUN_FUEL_SOURCE, [_Run(minutes=110, fuelled=False)]
    )
    assert values == {}


def test_unknown_fuelling_never_claims_the_habit():
    """`fuelled` is nullable and None means UNKNOWN, not "no" — but a habit must
    never claim the athlete fuelled a run when nothing recorded that they did."""
    values = _compute_date_values(
        LONG_RUN_FUEL_SOURCE, [_Run(minutes=110, fuelled=None)]
    )
    assert values == {}


def test_a_short_run_does_not_count_however_it_was_fuelled():
    values = _compute_date_values(
        LONG_RUN_FUEL_SOURCE,
        [_Run(minutes=LONG_RUN_MIN_MINUTES - 5, fuelled=True)],
    )
    assert values == {}


def test_a_long_strength_session_is_not_a_long_run():
    values = _compute_date_values(
        LONG_RUN_FUEL_SOURCE,
        [_Run(minutes=120, fuelled=True, wtype="strength")],
    )
    assert values == {}


def test_a_run_without_a_duration_is_skipped():
    run = _Run(minutes=110, fuelled=True)
    run.duration_seconds = None
    assert _compute_date_values(LONG_RUN_FUEL_SOURCE, [run]) == {}


# ═════════════════════════════════════════════════════════════════════════════
# Correlation evidence instead of streaks (D8, spec §12)
# ═════════════════════════════════════════════════════════════════════════════

def _pairs(with_values, without_values) -> list[dict]:
    return (
        [{"habit_value": True, "outcome_value": v} for v in with_values]
        + [{"habit_value": False, "outcome_value": v} for v in without_values]
    )


def test_the_spec_sentence_renders_with_real_numbers():
    """Spec §8's own example: "Weeks you fuelled the long run, HR drift
    averaged 3.1% vs 6.8%."."""
    result = build_evidence(
        _pairs([3.0, 3.2, 3.1, 2.9], [6.5, 7.1, 6.8]),
        "hr_drift",
        "fuelled the long run",
    )
    assert result["readable"] is True
    assert result["sentence"] == (
        "Weeks you fuelled the long run, HR drift averaged 3.0% vs 6.8%."
    )
    assert result["better"] == "with"


def test_no_sentence_without_enough_weeks():
    result = build_evidence(_pairs([3.0, 3.2], [6.5]), "hr_drift", "fuelled")
    assert result["readable"] is False
    assert result["sentence"] is None
    assert str(MIN_PAIRS) in result["reason"]


def test_no_sentence_when_one_group_is_empty():
    """All-yes weeks compare nothing."""
    result = build_evidence(_pairs([3.0] * 8, []), "hr_drift", "fuelled")
    assert result["readable"] is False
    assert "with and without" in result["reason"]


def test_one_observation_in_a_group_is_not_enough():
    result = build_evidence(_pairs([3.0] * 7, [6.0]), "hr_drift", "fuelled")
    assert result["readable"] is False
    assert result["n_without"] < MIN_PER_GROUP


def test_lower_is_better_metrics_read_as_wins():
    """3.1% vs 6.8% drift is a win, not a decline."""
    result = compare_groups(_pairs([3.0] * 4, [6.8] * 4), "hr_drift")
    assert result["better"] == "with"


def test_higher_is_better_metrics_read_the_other_way():
    result = compare_groups(_pairs([82.0] * 4, [70.0] * 4), "readiness")
    assert result["better"] == "with"
    worse = compare_groups(_pairs([60.0] * 4, [78.0] * 4), "readiness")
    assert worse["better"] == "without"


def test_a_negligible_gap_is_reported_as_no_difference():
    """Two numbers a hair apart are not evidence of anything."""
    result = build_evidence(_pairs([5.00] * 4, [5.02] * 4), "hr_drift", "fuelled")
    assert result["better"] == "same"
    assert "about the same" in result["sentence"]
    assert "no difference worth acting on" in result["sentence"]


def test_an_unknown_metric_yields_no_sentence():
    result = build_evidence(_pairs([1.0] * 4, [2.0] * 4), "vibes", "fuelled")
    assert result["readable"] is False
    assert result["sentence"] is None


def test_missing_outcome_values_are_skipped():
    pairs = _pairs([3.0, 3.1, 3.2, 2.9], [6.5, 6.8, 7.0])
    pairs.append({"habit_value": True, "outcome_value": None})
    assert build_evidence(pairs, "hr_drift", "fuelled")["n_with"] == 4


def test_evidence_never_claims_causation():
    result = build_evidence(
        _pairs([3.0, 3.2, 3.1, 2.9], [6.5, 7.1, 6.8]), "hr_drift", "fuelled the long run"
    )
    lowered = result["sentence"].lower()
    for causal in ("because", "caused", "thanks to", "due to", "proves"):
        assert causal not in lowered


# ── No streaks (spec §12) ────────────────────────────────────────────────────

def _code_without_docstrings(module) -> str:
    """Module source with docstrings and comments stripped.

    Both modules *discuss* streaks at length — explaining why they have none is
    the point. What must be absent is streak COMPUTATION, so the prose is
    removed before checking.
    """
    import ast

    source = inspect.getsource(module)
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            if (
                node.body
                and isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
            ):
                node.body.pop(0)
    return ast.unparse(tree)


@pytest.mark.parametrize("module", [habit_evidence, goal_habits])
def test_no_streak_is_computed_in_any_goal_habit_surface(module):
    """Spec §12: no streak computation in any habit surface tied to food."""
    code = _code_without_docstrings(module).lower()
    assert "streak" not in code


@pytest.mark.parametrize("name", ["Protein first", "Long-run fuel"])
def test_food_habits_are_identifiable_so_streaks_can_be_kept_off_them(name):
    class _H:
        pass

    h = _H()
    h.name = name
    assert goal_habits.is_food_habit(h) is True


def test_the_weigh_in_habit_is_not_a_food_habit():
    class _H:
        pass

    h = _H()
    h.name = "Morning weigh-in"
    assert goal_habits.is_food_habit(h) is False


def test_no_streak_helper_is_imported_by_the_goal_habit_surface():
    """Static guard: the regression is somebody wiring habit_stats' streak
    helpers into the goal-habit surface later."""
    for module in (goal_habits, habit_evidence):
        source = inspect.getsource(module)
        assert "habit_streak" not in source
        assert "from backend.services.habit_stats" not in source
