"""Phase 4 — calibration sprints and the weight hypothesis (spec §9, §12).

Two ideas, both about refusing to overclaim:

- A **calibration sprint** is a bounded measurement week, never a diet. The end
  date is visible from the moment it starts, because an open-ended "just track
  for a while" is the shape of the five attempts that already failed.
- **Optimal racing weight is a hypothesis**, not a number off a chart. The
  output has no target and never will — "as lean as I can" has no stopping rule,
  which is exactly what makes it dangerous.

Spec §9 acceptance: a sprint starts and ends on its own dates; maintenance
updates from ≥5 days of data and flips `maintenance_source` to `measured`; the
hypothesis view renders without a hard target.
"""
from __future__ import annotations

import datetime
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

from backend.models import (  # noqa: E402
    Base,
    CalibrationSprint,
    FuelEntry,
    FuelSettings,
    PerformanceScoreHistory,
    PlannedSession,
    User,
    WeightEntry,
    Workout,
)
from backend.services import calibration_sprint as cs  # noqa: E402
from backend.services.calibration_sprint import (  # noqa: E402
    MAX_SPRINT_DAYS,
    MIN_SPRINT_DAYS,
    SPRINT_MIN_LOGGED_DAYS,
    SprintError,
    close_sprint,
    sprint_status,
    start_sprint,
)
from backend.services.weight_hypothesis import (  # noqa: E402
    MIN_BUCKETS,
    MIN_PAIRS,
    compute_hypothesis,
)

TODAY = datetime.date(2026, 7, 30)
_UTC = datetime.timezone.utc

_TABLES = (
    User, CalibrationSprint, FuelEntry, FuelSettings, WeightEntry,
    Workout, PlannedSession, PerformanceScoreHistory,
)


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

    Base.metadata.create_all(engine, tables=[m.__table__ for m in _TABLES])
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
# The sprint is bounded (spec §9)
# ═════════════════════════════════════════════════════════════════════════════

def test_a_sprint_has_a_visible_end_date_from_the_start(session_user):
    """The bound is the feature: an open-ended sprint is just another diet."""
    session, uid = session_user
    sprint = start_sprint(session, uid, days=7, today=TODAY)
    session.commit()
    assert sprint.start_date == TODAY
    assert sprint.end_date == TODAY + datetime.timedelta(days=6)


def test_a_seven_day_sprint_spans_seven_days_inclusive(session_user):
    session, uid = session_user
    sprint = start_sprint(session, uid, days=7, today=TODAY)
    session.commit()
    assert (sprint.end_date - sprint.start_date).days + 1 == 7


@pytest.mark.parametrize("days", [MIN_SPRINT_DAYS, 6, MAX_SPRINT_DAYS])
def test_valid_lengths_are_accepted(session_user, days):
    session, uid = session_user
    sprint = start_sprint(session, uid, days=days, today=TODAY)
    session.commit()
    assert (sprint.end_date - sprint.start_date).days + 1 == days


@pytest.mark.parametrize("days", [1, 4, 8, 30])
def test_out_of_range_lengths_are_rejected(session_user, days):
    """Shorter than 5 can't recalibrate; longer than 7 stops being a sprint."""
    session, uid = session_user
    with pytest.raises(SprintError, match="days"):
        start_sprint(session, uid, days=days, today=TODAY)


def test_two_sprints_cannot_run_at_once(session_user):
    session, uid = session_user
    start_sprint(session, uid, today=TODAY)
    session.commit()
    with pytest.raises(SprintError, match="already running"):
        start_sprint(session, uid, today=TODAY)


def test_a_sprint_cannot_start_far_in_the_future(session_user):
    session, uid = session_user
    with pytest.raises(SprintError, match="week ahead"):
        start_sprint(
            session, uid, start_date=TODAY + datetime.timedelta(days=30), today=TODAY
        )


def test_the_countdown_includes_the_final_day(session_user):
    """The last day still has logging left in it — "1 to go", not "0"."""
    session, uid = session_user
    start_sprint(session, uid, days=5, today=TODAY)
    session.commit()
    last_day = TODAY + datetime.timedelta(days=4)
    status = sprint_status(session, uid, last_day)
    assert status["days_remaining"] == 1


def test_a_sprint_stops_being_active_after_its_end_date(session_user):
    """It ends on its own date — nobody has to remember to stop it."""
    session, uid = session_user
    start_sprint(session, uid, days=5, today=TODAY)
    session.commit()
    after = TODAY + datetime.timedelta(days=10)
    assert sprint_status(session, uid, after)["active"] is False


def test_status_with_no_sprint_reports_one_is_due(session_user):
    session, uid = session_user
    status = sprint_status(session, uid, TODAY)
    assert status["active"] is False
    assert status["due"] is True


def test_a_recent_sprint_means_the_next_is_not_yet_due(session_user):
    """Monthly cadence — not "whenever you feel bad about it"."""
    session, uid = session_user
    start_sprint(session, uid, days=5, today=TODAY)
    session.commit()
    just_after = TODAY + datetime.timedelta(days=8)
    status = sprint_status(session, uid, just_after)
    assert status["active"] is False
    assert status["due"] is False
    assert status["next_due_date"] is not None


def test_the_next_sprint_becomes_due_after_the_cadence(session_user):
    session, uid = session_user
    start_sprint(session, uid, days=5, today=TODAY)
    session.commit()
    later = TODAY + datetime.timedelta(days=cs.SPRINT_CADENCE_DAYS + 1)
    assert sprint_status(session, uid, later)["due"] is True


# ── Copy: a measurement week, never a diet ───────────────────────────────────

@pytest.mark.parametrize("key", sorted(cs.COPY))
@pytest.mark.parametrize("banned", ["diet", "restrict", "cheat", "willpower", "discipline"])
def test_no_sprint_copy_frames_it_as_a_diet(key, banned):
    assert banned not in cs.COPY[key].lower()


def test_the_copy_contract_is_enforced():
    with pytest.raises(ValueError, match="diet"):
        cs.assert_measurement_copy("Time for your monthly diet week.")


def test_active_copy_names_the_end_date(session_user):
    session, uid = session_user
    start_sprint(session, uid, days=5, today=TODAY)
    session.commit()
    message = sprint_status(session, uid, TODAY)["message"]
    assert "Measurement week" in message
    assert (TODAY + datetime.timedelta(days=4)).isoformat() in message


# ═════════════════════════════════════════════════════════════════════════════
# Closing and recalibration (spec §9 acceptance)
# ═════════════════════════════════════════════════════════════════════════════

def _log_days(session, uid, start, n, *, kcal_rows=True, weight=80.0):
    for i in range(n):
        day = start + datetime.timedelta(days=i)
        session.add(
            WeightEntry(
                id=uuid.uuid4(), user_id=uid, entry_date=day,
                weight_kg=weight - 0.05 * i, source="imported",
                created_at=datetime.datetime.now(_UTC),
            )
        )
        if kcal_rows:
            session.add(
                FuelEntry(
                    id=uuid.uuid4(), user_id=uid, entry_date=day,
                    meat_g=400, rice_g=400, eggs=2, fruit_g=200,
                    oil_tsp=2, other_kcal=300,
                    created_at=datetime.datetime.now(_UTC),
                )
            )
    session.commit()


def test_enough_logged_days_recalibrates_maintenance(session_user):
    """Spec §9 acceptance: maintenance updates from ≥5 days and flips to
    `measured`."""
    session, uid = session_user
    start_sprint(session, uid, days=7, today=TODAY)
    session.commit()
    _log_days(session, uid, TODAY, 6)

    result = close_sprint(session, uid, today=TODAY + datetime.timedelta(days=6))
    session.commit()

    assert result["closed"] is True
    assert result["recalibrated"] is True
    assert result["maintenance_source"] == "measured"

    settings = session.query(FuelSettings).filter(FuelSettings.user_id == uid).first()
    assert settings.maintenance_source == "measured"
    assert settings.base_kcal == result["new_base_kcal"]


def test_too_few_logged_days_completes_without_recalibrating(session_user):
    """A sprint that fell short is completed, not failed — a measurement that
    didn't take is not a moral event."""
    session, uid = session_user
    start_sprint(session, uid, days=7, today=TODAY)
    session.commit()
    _log_days(session, uid, TODAY, 2)

    result = close_sprint(session, uid, today=TODAY + datetime.timedelta(days=6))
    session.commit()

    assert result["status"] == "completed"
    assert result["recalibrated"] is False
    assert str(SPRINT_MIN_LOGGED_DAYS) in result["message"]


def test_a_short_sprint_message_carries_no_blame(session_user):
    session, uid = session_user
    start_sprint(session, uid, days=7, today=TODAY)
    session.commit()
    _log_days(session, uid, TODAY, 2)
    result = close_sprint(session, uid, today=TODAY + datetime.timedelta(days=6))
    lowered = result["message"].lower()
    for banned in ("failed", "should have", "try harder", "diet"):
        assert banned not in lowered


def test_a_sprint_can_be_abandoned(session_user):
    session, uid = session_user
    start_sprint(session, uid, days=7, today=TODAY)
    session.commit()
    result = close_sprint(session, uid, abandon=True, today=TODAY)
    session.commit()
    assert result["status"] == "abandoned"


def test_closing_without_a_sprint_is_reported_not_raised(session_user):
    session, uid = session_user
    assert close_sprint(session, uid, today=TODAY)["closed"] is False


def test_logged_days_counts_only_days_with_real_intake(session_user):
    session, uid = session_user
    start_sprint(session, uid, days=7, today=TODAY)
    session.commit()
    _log_days(session, uid, TODAY, 3)
    _log_days(session, uid, TODAY + datetime.timedelta(days=3), 2, kcal_rows=False)

    status = sprint_status(session, uid, TODAY + datetime.timedelta(days=5))
    assert status["logged_days"] == 3
    assert status["can_recalibrate"] is False


def test_can_recalibrate_flips_at_the_threshold(session_user):
    session, uid = session_user
    start_sprint(session, uid, days=7, today=TODAY)
    session.commit()
    _log_days(session, uid, TODAY, SPRINT_MIN_LOGGED_DAYS)
    status = sprint_status(session, uid, TODAY + datetime.timedelta(days=5))
    assert status["logged_days"] == SPRINT_MIN_LOGGED_DAYS
    assert status["can_recalibrate"] is True


def test_calibrate_accepts_the_sprint_minimums():
    """Without the override the stock 14-day / 10-entry floor makes this feature
    unreachable for a structural-deficit athlete, who never logs food."""
    from backend.services.fuel import CalibrateNeedsMoreData, calibrate

    day = datetime.date(2026, 7, 20)
    weights = [(day + datetime.timedelta(days=i), 80.0 - 0.05 * i) for i in range(6)]
    triples = [(day + datetime.timedelta(days=i), 2200, 2400, 500) for i in range(6)]

    with pytest.raises(CalibrateNeedsMoreData):
        calibrate(weights, triples)

    result = calibrate(weights, triples, min_days=5, min_entries=5)
    assert result["maintenance_source"] == "measured"


# ═════════════════════════════════════════════════════════════════════════════
# The hypothesis — never a target (spec §9)
# ═════════════════════════════════════════════════════════════════════════════

def _pairs(spec: list[tuple[float, float, int]]) -> list[dict]:
    """(weight, score, repeat) → flat pair list."""
    out = []
    for weight, score, n in spec:
        out.extend({"weight_kg": weight, "score": score} for _ in range(n))
    return out


def test_the_output_has_no_target_key():
    """The whole point. "As lean as I can" has no stopping rule."""
    result = compute_hypothesis(
        _pairs([(84.0, 40.0, 10), (83.0, 44.0, 10), (82.0, 46.0, 10), (81.0, 43.0, 10)])
    )
    for forbidden in ("target_kg", "target", "goal_kg", "goal", "on_track"):
        assert forbidden not in result


def test_it_locates_the_weight_where_scores_were_highest():
    result = compute_hypothesis(
        _pairs([(84.0, 40.0, 10), (83.0, 44.0, 10), (82.0, 48.0, 10), (81.0, 43.0, 10)])
    )
    assert result["readable"] is True
    assert result["peak_estimate_kg"] == 82.0


def test_the_peak_can_be_heavier_than_the_athlete_expects():
    """It may be 85 kg, not 79 — that is the finding, not a failure."""
    result = compute_hypothesis(
        _pairs([(85.0, 50.0, 10), (84.0, 45.0, 10), (83.0, 41.0, 10), (82.0, 38.0, 10)])
    )
    assert result["peak_estimate_kg"] == 85.0


def test_a_band_is_reported_not_a_point():
    result = compute_hypothesis(
        _pairs([(84.0, 40.0, 10), (83.0, 44.0, 10), (82.0, 48.0, 10), (81.0, 43.0, 10)])
    )
    lo, hi = result["band_kg"]
    assert lo < result["peak_estimate_kg"] < hi


def test_too_few_days_says_so_plainly():
    result = compute_hypothesis(_pairs([(83.0, 44.0, 4), (82.0, 46.0, 4)]))
    assert result["readable"] is False
    assert str(MIN_PAIRS) in result["reason"]
    assert result["peak_estimate_kg"] is None


def test_a_narrow_weight_range_cannot_locate_a_peak():
    """An athlete who has only ever been 84-85 kg has no evidence about 80."""
    result = compute_hypothesis(_pairs([(84.5, 44.0, 20), (84.0, 45.0, 20)]))
    assert result["readable"] is False
    assert "narrow" in result["reason"]


def test_sparse_buckets_are_not_eligible_to_be_the_peak():
    """One freak day at 79 kg must not become the recommendation."""
    result = compute_hypothesis(
        _pairs([(84.0, 40.0, 10), (83.0, 44.0, 10), (82.0, 46.0, 10), (81.0, 43.0, 10)])
        + _pairs([(79.0, 99.0, 1)])
    )
    assert result["peak_estimate_kg"] != 79.0


def test_confidence_is_reported_and_never_high():
    """Coverage-based, and this signal never earns "high"."""
    result = compute_hypothesis(
        _pairs([(84.0, 40.0, 10), (83.0, 44.0, 10), (82.0, 48.0, 10), (81.0, 43.0, 10)])
    )
    assert result["confidence"] in ("very low", "low", "moderate")


def test_the_sentence_refuses_to_claim_causation():
    result = compute_hypothesis(
        _pairs([(84.0, 40.0, 10), (83.0, 44.0, 10), (82.0, 48.0, 10), (81.0, 43.0, 10)])
    )
    assert "not proof that the weight caused it" in result["sentence"]


def test_direction_says_where_the_band_sits_relative_to_now():
    pairs = _pairs(
        [(84.0, 40.0, 10), (83.0, 44.0, 10), (82.0, 48.0, 10), (81.0, 43.0, 10)]
    )
    pairs.append({"weight_kg": 86.0, "score": 39.0})
    result = compute_hypothesis(pairs)
    assert result["current_weight_kg"] == 86.0
    assert result["direction"] == "below_current"


def test_no_pairs_is_not_an_error():
    result = compute_hypothesis([])
    assert result["readable"] is False
    assert result["peak_estimate_kg"] is None
    assert result["n_pairs"] == 0


def test_buckets_are_reported_for_inspection():
    result = compute_hypothesis(
        _pairs([(84.0, 40.0, 10), (83.0, 44.0, 10), (82.0, 48.0, 10), (81.0, 43.0, 10)])
    )
    assert len(result["buckets"]) >= MIN_BUCKETS
    assert all("mean_score" in b and "n" in b for b in result["buckets"])
