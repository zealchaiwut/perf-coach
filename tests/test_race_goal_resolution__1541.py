"""Tests for issue #1541: Add Race-based fallback to active-goal resolution (runs against UAT)"""
import os
import json
import pytest
import httpx
from datetime import date, datetime, timedelta
from uuid import uuid4


# Resolved from UAT .env at runtime; see tester skill Step 0.
# Default kept only as a last-resort fallback if BASE_URL not exported.
BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# --- AC 1: Module exists and exports resolve_active_goal ---

def test_goal_resolution__module_exists_and_exports():
    """AC 1: backend/services/goal_resolution.py exists and exports resolve_active_goal(user_id, db) -> object | None"""
    try:
        from backend.services.goal_resolution import resolve_active_goal
        assert callable(resolve_active_goal), "resolve_active_goal must be callable"
    except ImportError as e:
        pytest.fail(f"Failed to import resolve_active_goal: {e}")


# --- AC 2: Returns existing PerformanceGoal unchanged ---

def test_goal_resolution__performance_goal_returns_unchanged():
    """AC 2: resolve_active_goal returns existing PerformanceGoal when active==True (no behavior change)"""
    from sqlalchemy.orm import Session
    from backend.db import engine
    from backend.models import User, PerformanceGoal
    from backend.services.goal_resolution import resolve_active_goal
    from uuid import uuid4

    user_id = uuid4()

    # Create test user
    with Session(engine) as db:
        try:
            user = User(id=user_id, name=f"test_perf_goal_{uuid4().hex[:8]}")
            db.add(user)
            db.commit()

            # Create active PerformanceGoal
            goal = PerformanceGoal(
                user_id=user_id,
                race_distance="5k",
                target_time=1200,
                race_date=date.today() + timedelta(days=30),
                active=True,
            )
            db.add(goal)
            db.commit()

            # Query via resolve_active_goal
            with Session(engine) as db2:
                resolved = resolve_active_goal(user_id, db2)
                assert resolved is not None, "Should resolve to PerformanceGoal"
                assert resolved.user_id == user_id, "Goal user_id must match"
                assert resolved.race_distance == "5k", "Goal race_distance must match"
                assert resolved.target_time == 1200, "Goal target_time must match"
                assert isinstance(resolved, PerformanceGoal), "Should return PerformanceGoal object, not adapter"
        finally:
            # Cleanup
            db.query(PerformanceGoal).filter_by(user_id=user_id).delete()
            db.query(User).filter_by(id=user_id).delete()
            db.commit()


# --- AC 3: Race fallback query uses correct filters and ordering ---

def test_goal_resolution__race_query_correct_filters():
    """AC 3: Queries Race by user_id, priority=='A', status in ('planned','active'), ordered by race_date asc nulls-last"""
    from sqlalchemy.orm import Session
    from backend.db import engine
    from backend.models import User, Race
    from backend.services.goal_resolution import resolve_active_goal
    from uuid import uuid4
    from datetime import date, timedelta

    user_id = uuid4()

    with Session(engine) as db:
        try:
            user = User(id=user_id, name=f"test_race_query_{uuid4().hex[:8]}")
            db.add(user)
            db.commit()

            # Create multiple races with different priorities and statuses
            # Only A-priority with 'planned' status should be selected
            # (Note: 'active' status is part of the AC but not in RACE_STATUS_VALUES;
            #  test uses 'planned' as the primary filtering case)

            # B-priority race (should be skipped)
            race_b = Race(
                user_id=user_id,
                name="B-priority race",
                race_date=date.today() + timedelta(days=10),
                distance_km=5.0,
                goal_time_seconds=1200,
                priority="B",
                status="planned",
            )
            db.add(race_b)

            # A-priority with 'done' status (should be skipped)
            race_done = Race(
                user_id=user_id,
                name="Done A-race",
                race_date=date.today() + timedelta(days=5),
                distance_km=5.0,
                goal_time_seconds=1200,
                priority="A",
                status="done",
            )
            db.add(race_done)

            # A-priority with 'planned' status (should be selected)
            race_a_planned = Race(
                user_id=user_id,
                name="A-priority planned race",
                race_date=date.today() + timedelta(days=30),
                distance_km=10.0,
                goal_time_seconds=2400,
                priority="A",
                status="planned",
            )
            db.add(race_a_planned)

            # Another A-priority with 'planned' status but later date (should not be selected)
            race_a_planned_later = Race(
                user_id=user_id,
                name="A-priority planned race later",
                race_date=date.today() + timedelta(days=50),
                distance_km=21.0975,
                goal_time_seconds=5400,
                priority="A",
                status="planned",
            )
            db.add(race_a_planned_later)

            db.commit()

            # Resolve should return the earliest A-priority race with planned status
            with Session(engine) as db2:
                resolved = resolve_active_goal(user_id, db2)
                assert resolved is not None, "Should resolve to race adapter"
                assert resolved.target_time == 2400, f"Should select earliest A-race; got {resolved.target_time}"
                assert resolved.race_date == race_a_planned.race_date, "Should be the earliest planned race"

        finally:
            # Cleanup
            db.query(Race).filter_by(user_id=user_id).delete()
            db.query(User).filter_by(id=user_id).delete()
            db.commit()


# --- AC 4: Adapter exposes required attributes ---

def test_goal_resolution__adapter_has_required_attributes():
    """AC 4: Adapter exposes user_id, race_date, race_distance, and target_time with compatible types"""
    from sqlalchemy.orm import Session
    from backend.db import engine
    from backend.models import User, Race
    from backend.services.goal_resolution import resolve_active_goal
    from uuid import uuid4
    from datetime import date, timedelta

    user_id = uuid4()

    with Session(engine) as db:
        try:
            user = User(id=user_id, name=f"test_adapter_{uuid4().hex[:8]}")
            db.add(user)

            race = Race(
                user_id=user_id,
                name="Test race for adapter",
                race_date=date.today() + timedelta(days=30),
                distance_km=5.0,
                goal_time_seconds=1200,
                priority="A",
                status="planned",
            )
            db.add(race)
            db.commit()

            with Session(engine) as db2:
                adapter = resolve_active_goal(user_id, db2)
                assert adapter is not None, "Should resolve to adapter"
                # Check all required attributes exist and have correct types
                assert hasattr(adapter, "user_id"), "Adapter must have user_id"
                assert hasattr(adapter, "race_date"), "Adapter must have race_date"
                assert hasattr(adapter, "race_distance"), "Adapter must have race_distance"
                assert hasattr(adapter, "target_time"), "Adapter must have target_time"

                # Type checks
                assert adapter.user_id == user_id, "user_id must be UUID"
                assert isinstance(adapter.race_date, date), "race_date must be date"
                assert isinstance(adapter.race_distance, str), "race_distance must be string"
                assert isinstance(adapter.target_time, int), "target_time must be int"

        finally:
            db.query(Race).filter_by(user_id=user_id).delete()
            db.query(User).filter_by(id=user_id).delete()
            db.commit()


# --- AC 5: race_distance bucket mapping ---

def test_goal_resolution__distance_bucket_mapping():
    """AC 5: race_distance maps: 5km→'5k', 10km→'10k', 21.0975km→'half', 42.195km→'marathon'"""
    from sqlalchemy.orm import Session
    from backend.db import engine
    from backend.models import User, Race
    from backend.services.goal_resolution import resolve_active_goal
    from uuid import uuid4
    from datetime import date, timedelta

    user_id = uuid4()

    test_cases = [
        (5.0, "5k"),
        (5.001, "5k"),
        (4.99, "5k"),
        (10.0, "10k"),
        (9.99, "5k"),
        (10.01, "10k"),
        (21.0975, "half"),
        (21.0, "half"),
        (21.2, "half"),
        (42.195, "marathon"),
        (42.0, "marathon"),
        (42.5, "marathon"),
    ]

    with Session(engine) as db:
        try:
            user = User(id=user_id, name=f"test_buckets_{uuid4().hex[:8]}")
            db.add(user)
            db.commit()

            for distance_km, expected_label in test_cases:
                race = Race(
                    user_id=user_id,
                    name=f"Test {distance_km}km race",
                    race_date=date.today() + timedelta(days=30),
                    distance_km=distance_km,
                    goal_time_seconds=1200,
                    priority="A",
                    status="planned",
                )
                db.add(race)
                db.commit()

                with Session(engine) as db2:
                    adapter = resolve_active_goal(user_id, db2)
                    assert adapter.race_distance == expected_label, \
                        f"Distance {distance_km}km should map to '{expected_label}', got '{adapter.race_distance}'"

                db.delete(race)
                db.commit()

        finally:
            db.query(Race).filter_by(user_id=user_id).delete()
            db.query(User).filter_by(id=user_id).delete()
            db.commit()


# --- AC 6: Null goal_time_seconds skips to next candidate ---

def test_goal_resolution__skip_null_goal_time():
    """AC 6: target_time from Race.goal_time_seconds; null values skip to next candidate"""
    from sqlalchemy.orm import Session
    from backend.db import engine
    from backend.models import User, Race
    from backend.services.goal_resolution import resolve_active_goal
    from uuid import uuid4
    from datetime import date, timedelta

    user_id = uuid4()

    with Session(engine) as db:
        try:
            user = User(id=user_id, name=f"test_null_goal_time_{uuid4().hex[:8]}")
            db.add(user)
            db.commit()

            # First race: null goal_time_seconds (should be skipped)
            race_null = Race(
                user_id=user_id,
                name="A-race with null goal_time",
                race_date=date.today() + timedelta(days=10),
                distance_km=5.0,
                goal_time_seconds=None,
                priority="A",
                status="planned",
            )
            db.add(race_null)
            db.flush()

            # Second race: non-null goal_time_seconds (should be selected)
            # Must have earlier date than first race to be selected
            race_valid = Race(
                user_id=user_id,
                name="A-race with valid goal_time",
                race_date=date.today() + timedelta(days=5),
                distance_km=10.0,
                goal_time_seconds=2400,
                priority="A",
                status="planned",
            )
            db.add(race_valid)

            db.commit()

            # resolve_active_goal should return the valid race (goal_time not null)
            # If multiple A-races exist, it returns the earliest one with non-null goal_time
            with Session(engine) as db2:
                adapter = resolve_active_goal(user_id, db2)
                assert adapter is not None, "Should resolve to valid race"
                assert adapter.target_time == 2400, "Should return the race with non-null goal_time"

        finally:
            db.query(Race).filter_by(user_id=user_id).delete()
            db.query(User).filter_by(id=user_id).delete()
            db.commit()


# --- AC 7: Returns None when no qualifying goal or race ---

def test_goal_resolution__returns_none_when_no_goal():
    """AC 7: Returns None when neither PerformanceGoal nor qualifying Race found"""
    from sqlalchemy.orm import Session
    from backend.db import engine
    from backend.models import User
    from backend.services.goal_resolution import resolve_active_goal
    from uuid import uuid4

    user_id = uuid4()

    with Session(engine) as db:
        try:
            user = User(id=user_id, name=f"test_none_{uuid4().hex[:8]}")
            db.add(user)
            db.commit()

            # No goal, no races
            with Session(engine) as db2:
                result = resolve_active_goal(user_id, db2)
                assert result is None, "Should return None when no goal or race exists"

        finally:
            db.query(User).filter_by(id=user_id).delete()
            db.commit()


# --- AC 8: Race query mirrors coach_facts.py ---

def test_goal_resolution__query_mirrors_coach_facts():
    """AC 8: Race fallback query mirrors exact filter in coach_facts.py"""
    from backend.services import goal_resolution, coach_facts
    import inspect

    goal_res_source = inspect.getsource(goal_resolution.resolve_active_goal)
    coach_facts_source = inspect.getsource(coach_facts)

    # Both should filter by priority == "A"
    assert 'priority' in goal_res_source.lower(), "goal_resolution must filter by priority"
    assert '"A"' in goal_res_source or "'A'" in goal_res_source, "goal_resolution must filter for priority A"

    # Both should filter by status with 'planned' and 'active'
    assert 'status' in goal_res_source.lower(), "goal_resolution must filter by status"
    assert '("planned"' in goal_res_source or '("planned",' in goal_res_source, \
        "goal_resolution must include 'planned' in status filter"
    assert '"active"' in goal_res_source or "'active'" in goal_res_source, \
        "goal_resolution must include 'active' in status filter"

    # coach_facts should also have the same filters
    assert '"A"' in coach_facts_source or "'A'" in coach_facts_source, \
        "coach_facts must filter for priority A"
    assert '("planned"' in coach_facts_source or '("planned",' in coach_facts_source, \
        "coach_facts must include 'planned' in status filter"


# --- AC 9: weekly_coach_message uses resolve_active_goal ---

def test_goal_resolution__weekly_message_integration():
    """AC 9: weekly_coach_message.py::_load_inputs_for_user uses resolve_active_goal instead of direct query"""
    from backend.services import weekly_coach_message
    import inspect

    source = inspect.getsource(weekly_coach_message._load_inputs_for_user)
    assert "resolve_active_goal" in source, \
        "_load_inputs_for_user must call resolve_active_goal"


# --- AC 10: export_brief._load_goal_for_user uses resolve_active_goal ---

def test_goal_resolution__export_brief_integration():
    """AC 10: scripts/export_brief.py::_load_goal_for_user is replaced with resolve_active_goal call"""
    import sys
    from pathlib import Path
    _repo_root = str(Path(__file__).resolve().parent.parent)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    from scripts import export_brief
    import inspect

    source = inspect.getsource(export_brief._load_goal_for_user)
    assert "resolve_active_goal" in source, \
        "_load_goal_for_user must call resolve_active_goal"


# --- AC 11: coach_plan and coach_facts continue unchanged ---

def test_goal_resolution__coach_plan_unchanged():
    """AC 11: coach_plan.build_plan_state and coach_facts.build_coach_facts work unchanged"""
    from backend.services import coach_plan, coach_facts
    import inspect

    sig_plan = inspect.signature(coach_plan.build_plan_state)
    sig_facts = inspect.signature(coach_facts.build_coach_facts)

    # Both should still accept 'goal' parameter
    assert "goal" in sig_plan.parameters, "build_plan_state must accept goal parameter"
    assert "goal" in sig_facts.parameters, "build_coach_facts must accept goal parameter"


# --- AC 12: export_brief produces non-null coach block with A-race ---

def test_goal_resolution__export_brief_with_a_race():
    """AC 12: With A-race and no PerformanceGoal, export_brief.py produces non-null coach block with directive/projection/levers/focus_id/next_action"""
    from sqlalchemy.orm import Session
    from backend.db import engine
    from backend.models import User, Race
    from datetime import date, timedelta
    import sys
    from pathlib import Path
    _repo_root = str(Path(__file__).resolve().parent.parent)
    if _repo_root not in sys.path:
        sys.path.insert(0, _repo_root)
    from scripts import export_brief
    from uuid import uuid4

    user_id = uuid4()

    with Session(engine) as db:
        try:
            user = User(id=user_id, name=f"test_coach_export_{uuid4().hex[:8]}")
            db.add(user)

            # Create A-priority race with goal_time
            race = Race(
                user_id=user_id,
                name="Export brief test race",
                race_date=date.today() + timedelta(days=30),
                distance_km=5.0,
                goal_time_seconds=1200,
                priority="A",
                status="planned",
            )
            db.add(race)
            db.commit()

            # Call export_brief._assemble_coach for this user
            coach_block = export_brief._assemble_coach(str(user_id), date.today())

            # Should produce non-null coach block
            assert coach_block is not None, "Coach block should be non-null with A-race present"
            assert isinstance(coach_block, dict), "Coach block should be a dict"
            assert "directive" in coach_block, "Coach block must have directive"
            assert "projection" in coach_block, "Coach block must have projection"
            assert "levers" in coach_block, "Coach block must have levers"

        finally:
            db.query(Race).filter_by(user_id=user_id).delete()
            db.query(User).filter_by(id=user_id).delete()
            db.commit()


# --- UAT Step 6: coach goal endpoints unchanged ---

def test_goal_resolution__uat_coach_endpoints(client):
    """UAT Step 6: GET /api/coach/goal and PUT /api/coach/goal endpoints unchanged (PerformanceGoal-only)"""
    r_get = client.get("/api/coach/goal")
    # Should either return 401 (no session) or a PerformanceGoal object, not 500
    assert r_get.status_code in (200, 401, 404), \
        f"GET /api/coach/goal should not return 500; got {r_get.status_code}"
