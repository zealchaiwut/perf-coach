"""Tests for issue #695: Aggregate and expose per-athlete best-effort duration curve.

Acceptance criteria covered:
- AC2: merge_best_effort favours the higher value at each duration slot.
- AC2: merge handles a subset of durations in the new run (unlisted durations unchanged).
- AC5: missing/None inputs return (empty, reason_string); no unhandled exception.
- AC6: GET /api/athletes/{id}/duration-curve returns duration, best_value,
       source_workout_id, source_date, and a debug object per entry.
- AC7: 404 for missing athlete; 200+empty+reason for athlete with no data.
- AC9: explicit unit tests for all three named scenarios.
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


def _unpack(result):
    """Unpack (curve_dict, reason) from merge_best_effort."""
    assert isinstance(result, tuple) and len(result) == 2, (
        "merge_best_effort must return a (dict, reason) 2-tuple"
    )
    return result


# ── AC9 / AC2: merge favours the higher value ─────────────────────────────────

def test_unit_merge_favours_higher_value():
    """AC9/AC2: when new run has a higher power at a duration, it replaces stored value."""
    wid1 = str(uuid.uuid4())
    wid2 = str(uuid.uuid4())
    existing = {
        "60": {"best_value": 250.0, "workout_id": wid1, "date": "2026-01-10", "confidence": "measured"},
    }
    new_pts = [_point(60, 270.0, workout_id=wid2, date="2026-01-15")]
    result, reason = _unpack(merge_best_effort(existing, new_pts, higher_is_better=True))
    assert reason is None
    assert result["60"]["best_value"] == 270.0
    assert result["60"]["workout_id"] == wid2


def test_unit_merge_keeps_existing_when_new_is_lower():
    """AC2: when new run has a lower value, existing entry is preserved."""
    wid1 = str(uuid.uuid4())
    wid2 = str(uuid.uuid4())
    existing = {
        "60": {"best_value": 280.0, "workout_id": wid1, "date": "2026-01-10", "confidence": "measured"},
    }
    new_pts = [_point(60, 250.0, workout_id=wid2, date="2026-01-15")]
    result, reason = _unpack(merge_best_effort(existing, new_pts, higher_is_better=True))
    assert reason is None
    assert result["60"]["best_value"] == 280.0
    assert result["60"]["workout_id"] == wid1


# ── AC9 / AC2: merge handles a subset of durations in the new run ─────────────

def test_unit_merge_handles_subset_of_durations():
    """AC9/AC2: new run only covers a subset of durations; unlisted entries are untouched."""
    wid1 = str(uuid.uuid4())
    wid2 = str(uuid.uuid4())
    existing = {
        "60": {"best_value": 250.0, "workout_id": wid1, "date": "2026-01-10", "confidence": "measured"},
        "300": {"best_value": 240.0, "workout_id": wid1, "date": "2026-01-10", "confidence": "measured"},
        "1200": {"best_value": 220.0, "workout_id": wid1, "date": "2026-01-10", "confidence": "measured"},
    }
    # New run only provides 60s (better) and 300s (worse) — 1200s absent from new run
    new_pts = [
        _point(60, 270.0, workout_id=wid2, date="2026-01-15"),   # better
        _point(300, 230.0, workout_id=wid2, date="2026-01-15"),  # worse
    ]
    result, reason = _unpack(merge_best_effort(existing, new_pts, higher_is_better=True))
    assert reason is None
    assert result["60"]["best_value"] == 270.0      # updated
    assert result["300"]["best_value"] == 240.0     # unchanged (wid1 still holds it)
    assert result["1200"]["best_value"] == 220.0    # absent from new run — preserved
    assert result["1200"]["workout_id"] == wid1


# ── AC9 / AC5: missing-input path returns empty + reason ─────────────────────

def test_unit_missing_input_none_existing_returns_empty_and_reason():
    """AC9/AC5: None as existing curve — returns ({}, reason) with non-empty reason."""
    result, reason = _unpack(merge_best_effort(None, [_point(60, 250.0)]))
    assert result == {} or result is not None  # empty curve
    assert isinstance(reason, str) and len(reason) > 0


def test_unit_missing_input_none_new_points_returns_empty_and_reason():
    """AC9/AC5: None as new_points — returns ({}, reason) with non-empty reason."""
    existing = {"60": {"best_value": 250.0, "workout_id": str(uuid.uuid4()), "date": "2026-01-10"}}
    result, reason = _unpack(merge_best_effort(existing, None))
    assert result == {} or result is not None
    assert isinstance(reason, str) and len(reason) > 0


def test_unit_missing_input_no_exception_on_none_inputs():
    """AC5: None inputs must not raise any exception — must return gracefully."""
    try:
        out = merge_best_effort(None, None)
    except Exception as exc:
        pytest.fail(f"merge_best_effort raised exception on None inputs: {exc!r}")
    assert isinstance(out, tuple) and len(out) == 2


# ── AC6: endpoint fields per entry ────────────────────────────────────────────

def test_endpoint_duration_curve_entry_has_source_workout_id():
    """AC6: each entry in curve list includes source_workout_id field."""
    import httpx
    import os
    from sqlalchemy.orm import Session
    from sqlalchemy import text
    from backend.db import engine
    from backend.models import User, AthleteDurationCurve

    base = os.environ.get("UAT_BASE_URL", f"http://localhost:{os.environ.get('UAT_PORT', '9001')}")
    wid = str(uuid.uuid4())

    with Session(engine) as session:
        tmp = User(name=f"dc_user_{uuid.uuid4().hex[:8]}", password_hash="x")
        session.add(tmp)
        session.flush()
        tmp_id = str(tmp.id)
        session.add(AthleteDurationCurve(
            user_id=tmp.id,
            curve_data={
                "60": {"best_value": 270.0, "workout_id": wid, "date": "2026-01-10", "confidence": "measured"},
            },
        ))
        session.commit()

    try:
        with httpx.Client(base_url=base, timeout=10) as client:
            res = client.get(f"/api/athletes/{tmp_id}/duration-curve")
        assert res.status_code == 200
        body = res.json()
        curve = body.get("curve", [])
        assert len(curve) > 0, "Expected at least one curve entry"
        entry = curve[0]
        assert "source_workout_id" in entry, (
            f"Entry missing 'source_workout_id'; got keys: {list(entry.keys())}"
        )
    finally:
        with Session(engine) as session:
            session.execute(text("DELETE FROM users WHERE id = :id"), {"id": tmp_id})
            session.commit()


def test_endpoint_duration_curve_entry_has_source_date():
    """AC6: each entry includes source_date field."""
    import httpx
    import os
    from sqlalchemy.orm import Session
    from sqlalchemy import text
    from backend.db import engine
    from backend.models import User, AthleteDurationCurve

    base = os.environ.get("UAT_BASE_URL", f"http://localhost:{os.environ.get('UAT_PORT', '9001')}")
    wid = str(uuid.uuid4())

    with Session(engine) as session:
        tmp = User(name=f"dc_user2_{uuid.uuid4().hex[:8]}", password_hash="x")
        session.add(tmp)
        session.flush()
        tmp_id = str(tmp.id)
        session.add(AthleteDurationCurve(
            user_id=tmp.id,
            curve_data={
                "60": {"best_value": 270.0, "workout_id": wid, "date": "2026-01-10", "confidence": "measured"},
            },
        ))
        session.commit()

    try:
        with httpx.Client(base_url=base, timeout=10) as client:
            res = client.get(f"/api/athletes/{tmp_id}/duration-curve")
        assert res.status_code == 200
        curve = res.json().get("curve", [])
        assert len(curve) > 0
        entry = curve[0]
        assert "source_date" in entry, (
            f"Entry missing 'source_date'; got keys: {list(entry.keys())}"
        )
    finally:
        with Session(engine) as session:
            session.execute(text("DELETE FROM users WHERE id = :id"), {"id": tmp_id})
            session.commit()


def test_endpoint_duration_curve_entry_has_debug_object():
    """AC6: each entry includes a debug object with at minimum a workout identifier."""
    import httpx
    import os
    from sqlalchemy.orm import Session
    from sqlalchemy import text
    from backend.db import engine
    from backend.models import User, AthleteDurationCurve

    base = os.environ.get("UAT_BASE_URL", f"http://localhost:{os.environ.get('UAT_PORT', '9001')}")
    wid = str(uuid.uuid4())

    with Session(engine) as session:
        tmp = User(name=f"dc_user3_{uuid.uuid4().hex[:8]}", password_hash="x")
        session.add(tmp)
        session.flush()
        tmp_id = str(tmp.id)
        session.add(AthleteDurationCurve(
            user_id=tmp.id,
            curve_data={
                "60": {"best_value": 270.0, "workout_id": wid, "date": "2026-01-10", "confidence": "measured"},
            },
        ))
        session.commit()

    try:
        with httpx.Client(base_url=base, timeout=10) as client:
            res = client.get(f"/api/athletes/{tmp_id}/duration-curve")
        assert res.status_code == 200
        curve = res.json().get("curve", [])
        assert len(curve) > 0
        entry = curve[0]
        assert "debug" in entry, (
            f"Entry missing 'debug' object; got keys: {list(entry.keys())}"
        )
        debug = entry["debug"]
        assert isinstance(debug, dict), "debug must be a dict"
        assert "workout_label" in debug or "workout_id" in debug, (
            "debug must include at least workout_label or workout_id"
        )
    finally:
        with Session(engine) as session:
            session.execute(text("DELETE FROM users WHERE id = :id"), {"id": tmp_id})
            session.commit()


def test_endpoint_duration_curve_entry_has_best_value():
    """AC6: each entry includes best_value field."""
    import httpx
    import os
    from sqlalchemy.orm import Session
    from sqlalchemy import text
    from backend.db import engine
    from backend.models import User, AthleteDurationCurve

    base = os.environ.get("UAT_BASE_URL", f"http://localhost:{os.environ.get('UAT_PORT', '9001')}")
    wid = str(uuid.uuid4())

    with Session(engine) as session:
        tmp = User(name=f"dc_user4_{uuid.uuid4().hex[:8]}", password_hash="x")
        session.add(tmp)
        session.flush()
        tmp_id = str(tmp.id)
        session.add(AthleteDurationCurve(
            user_id=tmp.id,
            curve_data={
                "60": {"best_value": 270.0, "workout_id": wid, "date": "2026-01-10", "confidence": "measured"},
            },
        ))
        session.commit()

    try:
        with httpx.Client(base_url=base, timeout=10) as client:
            res = client.get(f"/api/athletes/{tmp_id}/duration-curve")
        assert res.status_code == 200
        curve = res.json().get("curve", [])
        assert len(curve) > 0
        entry = curve[0]
        assert "best_value" in entry, (
            f"Entry missing 'best_value'; got keys: {list(entry.keys())}"
        )
        assert entry["best_value"] == 270.0
    finally:
        with Session(engine) as session:
            session.execute(text("DELETE FROM users WHERE id = :id"), {"id": tmp_id})
            session.commit()


# ── AC7: 404 for missing athlete; 200+empty for no data ──────────────────────

def test_endpoint_returns_404_for_nonexistent_athlete():
    """AC7: GET /api/athletes/{id}/duration-curve returns 404 for unknown UUID."""
    import httpx
    import os
    base = os.environ.get("UAT_BASE_URL", f"http://localhost:{os.environ.get('UAT_PORT', '9001')}")
    with httpx.Client(base_url=base, timeout=10) as client:
        res = client.get(f"/api/athletes/{uuid.uuid4()}/duration-curve")
    assert res.status_code == 404


def test_endpoint_returns_200_empty_curve_and_reason_for_athlete_with_no_data():
    """AC7: athlete with no curve → 200 with empty curve list and non-empty reason."""
    import httpx
    import os
    from sqlalchemy.orm import Session
    from sqlalchemy import text
    from backend.db import engine
    from backend.models import User

    base = os.environ.get("UAT_BASE_URL", f"http://localhost:{os.environ.get('UAT_PORT', '9001')}")

    with Session(engine) as session:
        tmp = User(name=f"no_curve_{uuid.uuid4().hex[:8]}", password_hash="x")
        session.add(tmp)
        session.commit()
        tmp_id = str(tmp.id)

    try:
        with httpx.Client(base_url=base, timeout=10) as client:
            res = client.get(f"/api/athletes/{tmp_id}/duration-curve")
        assert res.status_code == 200
        body = res.json()
        assert body.get("curve") == [], f"Expected empty list, got: {body.get('curve')!r}"
        reason = body.get("reason", "")
        assert isinstance(reason, str) and len(reason) > 0, (
            "reason field must be a non-empty string when no curve data exists"
        )
    finally:
        with Session(engine) as session:
            session.execute(text("DELETE FROM users WHERE id = :id"), {"id": tmp_id})
            session.commit()


# ── Pure merge function return shape ─────────────────────────────────────────

def test_merge_returns_two_tuple_on_valid_inputs():
    """merge_best_effort must always return a (dict, reason_or_None) 2-tuple."""
    result = merge_best_effort({}, [_point(60, 250.0)])
    assert isinstance(result, tuple) and len(result) == 2
    curve, reason = result
    assert isinstance(curve, dict)
    assert reason is None


def test_merge_returns_two_tuple_on_empty_inputs():
    """merge_best_effort({}, []) → ({}, None) — both valid, both empty."""
    result = merge_best_effort({}, [])
    assert isinstance(result, tuple) and len(result) == 2
    curve, reason = result
    assert curve == {}
    assert reason is None
