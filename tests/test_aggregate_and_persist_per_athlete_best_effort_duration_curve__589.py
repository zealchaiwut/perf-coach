"""Tests for issue #589: Aggregate and persist per-athlete best-effort duration curve.

Acceptance criteria covered:
- AC1: Storage model exists with correct columns; one row per athlete.
- AC2: Curve merge only overwrites durations where new run improves on stored value.
- AC3: DB access isolated in repo layer; curve arithmetic in pure logic (no raw SQL).
- AC4: Empty-athlete returns 200 + reason; not an error status.
- AC5: No hardcoded thresholds / bucket sizes in implementation files.
- AC6: Endpoint returns athleteId, curve, debug fields with required shape.
- AC7: Endpoint returns 404 for non-existent athlete ID.
- AC8: Best-effort aggregation calls the compute module, not re-implementing curve math.
- AC9: Unit tests: empty-athlete, single-run, multi-run with partial improvement.
- AC10: Idempotency — reprocessing same run does not change stored curve.
"""

import uuid
import pytest

from backend.services.duration_curve_best_effort import merge_best_effort


# ── Helpers ───────────────────────────────────────────────────────────────────

def _point(duration, value, workout_id=None, date="2026-01-01", confidence="measured"):
    return {
        "duration_seconds": duration,
        "best_value": value,
        "source_workout_id": workout_id or str(uuid.uuid4()),
        "date": date,
        "confidence": confidence,
    }


# ── AC9: empty-athlete path ───────────────────────────────────────────────────

def test_merge_empty_existing_empty_new_returns_empty():
    """AC9/empty-athlete: merging empty existing with empty new points yields empty dict."""
    result = merge_best_effort({}, [])
    assert result == {}


def test_merge_empty_existing_with_null_value_points_stays_empty():
    """AC9: points with best_value=None are not added to the curve."""
    pts = [_point(60, None), _point(300, None)]
    result = merge_best_effort({}, pts)
    assert result == {}


# ── AC9: single-run athlete ───────────────────────────────────────────────────

def test_merge_single_run_adopts_all_valid_points():
    """AC9/single-run: all non-null points from first run are adopted into empty curve."""
    wid = str(uuid.uuid4())
    pts = [
        _point(60, 270.0, workout_id=wid, date="2026-01-10"),
        _point(300, 255.5, workout_id=wid, date="2026-01-10"),
    ]
    result = merge_best_effort({}, pts)
    assert "60" in result
    assert "300" in result
    assert result["60"]["best_value"] == 270.0
    assert result["60"]["workout_id"] == wid
    assert result["60"]["date"] == "2026-01-10"
    assert result["300"]["best_value"] == 255.5


def test_merge_single_run_preserves_confidence():
    """AC9/single-run: confidence field is preserved from source point."""
    wid = str(uuid.uuid4())
    pts = [_point(60, 270.0, workout_id=wid, confidence="approx")]
    result = merge_best_effort({}, pts)
    assert result["60"]["confidence"] == "approx"


# ── AC9: multi-run — partial improvement ─────────────────────────────────────

def test_merge_later_run_improves_one_duration_only():
    """AC9/multi-run: second run improves 60s but not 300s — only 60s entry is replaced."""
    wid1 = str(uuid.uuid4())
    wid2 = str(uuid.uuid4())
    existing = {
        "60": {"best_value": 250.0, "workout_id": wid1, "date": "2026-01-10", "confidence": "measured"},
        "300": {"best_value": 240.0, "workout_id": wid1, "date": "2026-01-10", "confidence": "measured"},
    }
    new_pts = [
        _point(60, 270.0, workout_id=wid2, date="2026-01-15"),   # better
        _point(300, 230.0, workout_id=wid2, date="2026-01-15"),  # worse
    ]
    result = merge_best_effort(existing, new_pts)
    assert result["60"]["best_value"] == 270.0
    assert result["60"]["workout_id"] == wid2
    assert result["300"]["best_value"] == 240.0
    assert result["300"]["workout_id"] == wid1


def test_merge_later_run_adds_new_duration_not_in_existing():
    """AC9/multi-run: new run has a duration not yet in existing curve — it is added."""
    wid1 = str(uuid.uuid4())
    wid2 = str(uuid.uuid4())
    existing = {
        "60": {"best_value": 250.0, "workout_id": wid1, "date": "2026-01-10", "confidence": "measured"},
    }
    new_pts = [
        _point(60, 240.0, workout_id=wid2, date="2026-01-15"),    # worse — not adopted
        _point(1800, 220.0, workout_id=wid2, date="2026-01-15"),  # new duration — adopted
    ]
    result = merge_best_effort(existing, new_pts)
    assert result["60"]["best_value"] == 250.0   # unchanged
    assert result["1800"]["best_value"] == 220.0  # new entry


def test_merge_equal_value_does_not_replace_existing():
    """AC2: when new value equals stored value, existing entry (first workout) is kept."""
    wid1 = str(uuid.uuid4())
    wid2 = str(uuid.uuid4())
    existing = {
        "60": {"best_value": 250.0, "workout_id": wid1, "date": "2026-01-10", "confidence": "measured"},
    }
    new_pts = [_point(60, 250.0, workout_id=wid2, date="2026-01-15")]
    result = merge_best_effort(existing, new_pts)
    assert result["60"]["workout_id"] == wid1  # original kept on tie


# ── AC10: idempotency ─────────────────────────────────────────────────────────

def test_merge_same_run_twice_is_idempotent():
    """AC10: merging the same workout twice produces the same result."""
    wid = str(uuid.uuid4())
    pts = [
        _point(60, 270.0, workout_id=wid, date="2026-01-15"),
        _point(300, 255.0, workout_id=wid, date="2026-01-15"),
    ]
    after_first = merge_best_effort({}, pts)
    after_second = merge_best_effort(after_first, pts)
    assert after_first == after_second


def test_merge_same_run_over_multi_run_curve_is_idempotent():
    """AC10: re-merging run that already contributed some bests does not degrade curve."""
    wid1 = str(uuid.uuid4())
    wid2 = str(uuid.uuid4())
    # wid2 wins 60s, wid1 wins 300s
    existing = {
        "60": {"best_value": 270.0, "workout_id": wid2, "date": "2026-01-15", "confidence": "measured"},
        "300": {"best_value": 240.0, "workout_id": wid1, "date": "2026-01-10", "confidence": "measured"},
    }
    # Re-process wid2 (same values) — should not corrupt 300s entry
    wid2_pts = [
        _point(60, 270.0, workout_id=wid2, date="2026-01-15"),
        _point(300, 230.0, workout_id=wid2, date="2026-01-15"),  # still worse than stored
    ]
    result = merge_best_effort(existing, wid2_pts)
    assert result["60"]["workout_id"] == wid2
    assert result["300"]["workout_id"] == wid1  # wid1 still holds 300s
    assert result["300"]["best_value"] == 240.0


# ── AC8: best-effort module calls compute module ──────────────────────────────

def test_best_effort_module_imports_from_duration_curve():
    """AC8: duration_curve_best_effort imports from duration_curve (not re-implementing)."""
    import inspect
    import backend.services.duration_curve_best_effort as m
    source = inspect.getsource(m)
    assert "duration_curve" in source, (
        "duration_curve_best_effort must import from duration_curve module"
    )


# ── AC3: no raw SQL in computation functions ──────────────────────────────────

def test_merge_best_effort_contains_no_sql():
    """AC3: merge_best_effort is a pure function (no SQLAlchemy or raw SQL calls)."""
    import inspect
    source = inspect.getsource(merge_best_effort)
    # Look for SQL execution patterns, not English words that happen to be SQL keywords
    sql_patterns = ("session.execute", "conn.execute", "op.execute", "text(", "Session(", "engine.")
    for pattern in sql_patterns:
        assert pattern not in source, (
            f"merge_best_effort contains DB call pattern '{pattern}' — violates AC3"
        )


# ── AC5: no hardcoded thresholds / bucket sizes ───────────────────────────────

def test_compute_power_curve_ladder_comes_from_parameter():
    """AC5: compute_power_curve accepts duration_ladder as a parameter."""
    import inspect
    from backend.services.duration_curve import compute_power_curve
    sig = inspect.signature(compute_power_curve)
    assert "duration_ladder" in sig.parameters, (
        "compute_power_curve must accept duration_ladder as a parameter (AC5)"
    )


def test_compute_pace_curve_ladder_comes_from_parameter():
    """AC5: compute_pace_curve accepts duration_ladder as a parameter."""
    import inspect
    from backend.services.duration_curve import compute_pace_curve
    sig = inspect.signature(compute_pace_curve)
    assert "duration_ladder" in sig.parameters, (
        "compute_pace_curve must accept duration_ladder as a parameter (AC5)"
    )


# ── DB-required tests (endpoint and model) ────────────────────────────────────

def test_athlete_duration_curves_model_exists():
    """AC1: AthleteDurationCurve ORM model is importable from backend.models."""
    from backend.models import AthleteDurationCurve
    assert AthleteDurationCurve is not None


def test_athlete_duration_curves_table_has_required_columns():
    """AC1: athlete_duration_curves table has user_id, curve_data, updated_at columns."""
    from sqlalchemy import text
    from backend.db import engine
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'athlete_duration_curves'"
        )).fetchall()
    found = {r[0] for r in rows}
    for col in ("user_id", "curve_data", "updated_at"):
        assert col in found, f"Column '{col}' missing from athlete_duration_curves"


def test_athlete_duration_curves_user_id_is_primary_key():
    """AC1: user_id is the primary key (enforces one row per athlete)."""
    from sqlalchemy import text
    from backend.db import engine
    with engine.connect() as conn:
        count = conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "  ON tc.constraint_name = kcu.constraint_name "
            "  AND tc.table_schema = kcu.table_schema "
            "WHERE tc.constraint_type = 'PRIMARY KEY' "
            "  AND tc.table_name = 'athlete_duration_curves' "
            "  AND kcu.column_name = 'user_id'"
        )).scalar()
    assert count == 1, "user_id is not the PK of athlete_duration_curves"


def test_endpoint_returns_404_for_nonexistent_athlete():
    """AC7: GET /api/athletes/{id}/duration-curve returns 404 for unknown ID."""
    import httpx, os
    base = os.environ.get("UAT_BASE_URL", f"http://localhost:{os.environ.get('UAT_PORT', '9001')}")
    with httpx.Client(base_url=base, timeout=10) as client:
        fake_id = str(uuid.uuid4())
        res = client.get(f"/api/athletes/{fake_id}/duration-curve")
    assert res.status_code == 404


def test_endpoint_returns_200_and_empty_curve_for_athlete_without_runs():
    """AC4: athlete with no runs → 200 with empty curve and reason field."""
    import httpx, os
    from sqlalchemy import text
    from sqlalchemy.orm import Session
    from backend.db import engine
    from backend.models import User
    base = os.environ.get("UAT_BASE_URL", f"http://localhost:{os.environ.get('UAT_PORT', '9001')}")

    # Create a temporary user with no workouts
    with Session(engine) as session:
        tmp_user = User(name=f"no_runs_user_{uuid.uuid4().hex[:8]}", password_hash="x")
        session.add(tmp_user)
        session.commit()
        tmp_id = str(tmp_user.id)

    try:
        with httpx.Client(base_url=base, timeout=10) as client:
            res = client.get(f"/api/athletes/{tmp_id}/duration-curve")
        assert res.status_code == 200
        body = res.json()
        assert "athleteId" in body
        assert "curve" in body
        assert body["curve"] == [] or body["curve"] == {}
        assert "reason" in body
        assert isinstance(body["reason"], str) and len(body["reason"]) > 0
        assert "debug" in body
    finally:
        with Session(engine) as session:
            session.execute(text("DELETE FROM users WHERE id = :id"), {"id": tmp_id})
            session.commit()


def test_endpoint_returns_required_fields_for_athlete_with_curve():
    """AC6: endpoint returns athleteId, curve, debug fields with correct shape."""
    import httpx, os
    from sqlalchemy.orm import Session
    from sqlalchemy import text
    from backend.db import engine
    from backend.models import User, AthleteDurationCurve
    base = os.environ.get("UAT_BASE_URL", f"http://localhost:{os.environ.get('UAT_PORT', '9001')}")

    # Create a user and insert a pre-computed curve
    with Session(engine) as session:
        tmp_user = User(name=f"curve_user_{uuid.uuid4().hex[:8]}", password_hash="x")
        session.add(tmp_user)
        session.flush()
        tmp_id = str(tmp_user.id)

        wid = str(uuid.uuid4())
        curve_data = {
            "60": {"best_value": 270.0, "workout_id": wid, "date": "2026-01-10", "confidence": "measured"},
            "300": {"best_value": 255.0, "workout_id": wid, "date": "2026-01-10", "confidence": "measured"},
        }
        record = AthleteDurationCurve(user_id=tmp_user.id, curve_data=curve_data)
        session.add(record)
        session.commit()

    try:
        with httpx.Client(base_url=base, timeout=10) as client:
            res = client.get(f"/api/athletes/{tmp_id}/duration-curve")
        assert res.status_code == 200
        body = res.json()
        assert body["athleteId"] == tmp_id
        assert isinstance(body["curve"], (list, dict))
        assert isinstance(body["debug"], (list, dict))

        # If list, check entries have required fields
        if isinstance(body["curve"], list) and len(body["curve"]) > 0:
            entry = body["curve"][0]
            for field in ("duration", "bestValue", "workoutId", "date"):
                assert field in entry, f"Missing field '{field}' in curve entry"
    finally:
        with Session(engine) as session:
            session.execute(text("DELETE FROM users WHERE id = :id"), {"id": tmp_id})
            session.commit()
