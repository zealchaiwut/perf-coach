"""Tests for the Fuel feature (Weight tab: Fuel today + Fuel week).

See docs/calculations/fuel.md. Pure-function tests need no DB; the
day_type/burn/skipped-session tests use a real Postgres session directly
(no live server) — same pattern as
tests/test_training_load_single_source__loadmetricfix1.py.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy.orm import Session

from backend.db import engine
from backend.models import FuelEntry, FuelSettings, PlannedSession, User, Workout
from backend.services import fuel


# ── Coefficients (§4) ─────────────────────────────────────────────────────────

def test_coefficients_kcal_matches_spec_worked_example():
    entry = FuelEntry(meat_g=200, rice_g=350, eggs=2, fruit_g=200, oil_tsp=1,
                       other_kcal=0, other_protein_g=0, other_carbs_g=0, other_fat_g=0)
    totals = fuel.compute_food_totals(entry)
    assert totals["kcal"] == 1090


def test_coefficients_protein_matches_the_coefficient_table_not_the_spec_typo():
    """The originating spec's own worked example says this input yields 72 g
    P, but that doesn't match its own FOOD table (200*0.31 + 350*0.027 +
    2*6.3 + 200*0.008 = 85.65, not 72) — see fuel.md's "Food coefficients"
    section for the full reconciliation. Trusting the explicit, internally
    self-consistent coefficient block over the prose example."""
    entry = FuelEntry(meat_g=200, rice_g=350, eggs=2, fruit_g=200, oil_tsp=1,
                       other_kcal=0, other_protein_g=0, other_carbs_g=0, other_fat_g=0)
    totals = fuel.compute_food_totals(entry)
    assert totals["protein_g"] == pytest.approx(85.65, abs=0.5)


# ── Budget (§4) ───────────────────────────────────────────────────────────────

def test_budget_no_floor_binding():
    result = fuel.compute_budget(
        {"base_kcal": 2400, "deficit_kcal": 300, "lean_mass_kg": 60, "ea_floor": 30}, 1300,
    )
    assert result["budget"] == 3400
    assert result["deficit_reduced"] is False


def test_ea_floor_binds_and_reduces_the_deficit():
    result = fuel.compute_budget(
        {"base_kcal": 2400, "deficit_kcal": 900, "lean_mass_kg": 67, "ea_floor": 30}, 1300,
    )
    assert result["budget"] == 3310
    assert result["deficit_reduced"] is True
    assert result["deficit_applied"] == 390


def test_protein_target_identical_rest_vs_long_run_day_carbs_differ():
    settings = {"weight_kg": 70, "protein_g_per_kg": 2.0, "fat_g": 70}
    rest_day = fuel.compute_targets(settings, budget=1700)  # base only
    long_run_day = fuel.compute_targets(settings, budget=3400)  # base + big burn
    assert rest_day["protein_g"] == long_run_day["protein_g"] == 140
    assert rest_day["carbs_g"] != long_run_day["carbs_g"]
    assert long_run_day["carbs_g"] > rest_day["carbs_g"]


def test_suggestion_never_negative_and_states_budget_spent_when_remaining_zero():
    targets = {"protein_g": 140, "carbs_g": 200}
    eaten = {"protein_g": 140, "carbs_g": 200}
    s = fuel.compute_suggestion(targets, eaten, remaining_kcal=0)
    assert s["meat_g"] == 0 and s["rice_g"] == 0
    assert s["message"] == "Budget spent — fine on a long-run day if protein is met."


# ── Settings validation (§3) ──────────────────────────────────────────────────

def test_settings_validation_rejects_deficit_kcal_1200():
    with pytest.raises(fuel.SettingsValidationError):
        fuel.validate_settings_fields({"deficit_kcal": 1200})


def test_settings_validation_rejects_protein_g_per_kg_3_0():
    with pytest.raises(fuel.SettingsValidationError):
        fuel.validate_settings_fields({"protein_g_per_kg": 3.0})


def test_settings_validation_accepts_in_range_values():
    fuel.validate_settings_fields({"deficit_kcal": 400, "protein_g_per_kg": 2.0})


# ── Calibrate (§4) ────────────────────────────────────────────────────────────

def test_calibrate_14_days_predicted_neg1kg_actual_0kg_increases_base_by_550():
    weight_entries = [(date(2026, 1, 1) + timedelta(days=i), 70.0) for i in range(14)]
    # eaten - (base+burn) = -550/day for 14 days -> predicted delta = -7700/7700 = -1.0 kg
    fuel_entries_and_burn = [
        (date(2026, 1, 1) + timedelta(days=i), 2400 - 550, 2400, 0) for i in range(14)
    ]
    result = fuel.calibrate(weight_entries, fuel_entries_and_burn)
    assert result["new_base_kcal"] == pytest.approx(2400 + 550, abs=1)
    assert result["maintenance_source"] == "measured"


def test_calibrate_needs_more_data_with_only_6_days():
    weight_entries = [(date(2026, 1, 1) + timedelta(days=i), 70.0) for i in range(6)]
    fuel_entries_and_burn = [
        (date(2026, 1, 1) + timedelta(days=i), 2400, 2400, 0) for i in range(6)
    ]
    with pytest.raises(fuel.CalibrateNeedsMoreData):
        fuel.calibrate(weight_entries, fuel_entries_and_burn)


# ── DB-backed: entry upsert, day_type/burn, skipped session ──────────────────

@pytest.fixture()
def fuel_user():
    with Session(engine) as db:
        uid = uuid.uuid4()
        db.add(User(id=uid, name=f"fueltest_{uid.hex[:8]}", password_hash="x", is_admin=False, is_active=True))
        db.commit()
        yield uid
        db.query(FuelEntry).filter(FuelEntry.user_id == uid).delete()
        db.query(FuelSettings).filter(FuelSettings.user_id == uid).delete()
        db.query(PlannedSession).filter(PlannedSession.user_id == uid).delete()
        db.query(Workout).filter(Workout.user_id == uid).delete()
        db.query(User).filter(User.id == uid).delete()
        db.commit()


def test_entry_upsert_two_puts_same_date_produce_one_row(fuel_user):
    d = date(2026, 7, 1)
    with Session(engine) as db:
        fuel.upsert_entry(fuel_user, d, db=db, meat_g=100)
        fuel.upsert_entry(fuel_user, d, db=db, rice_g=200)
        rows = db.query(FuelEntry).filter(FuelEntry.user_id == fuel_user, FuelEntry.entry_date == d).all()
        assert len(rows) == 1
        assert rows[0].meat_g == 100
        assert rows[0].rice_g == 200


def test_past_day_with_logged_workout_uses_actual_burn(fuel_user):
    d = date.today() - timedelta(days=3)
    with Session(engine) as db:
        db.add(Workout(user_id=fuel_user, workout_date=d, name="r", workout_type="run",
                        distance_km=10, duration_seconds=3000, tss=60))
        db.commit()
        info = fuel.training_burn_kcal(fuel_user, d, weight_kg=70, run_kcal_per_kg_per_km=1.0, db=db)
        assert info["is_actual"] is True
        assert info["burn"] == pytest.approx(700, abs=1)  # 70kg * 10km * 1.0
        assert info["day_type"] in ("easy_run", "long_run")


def test_past_day_skipped_planned_session_reports_skipped_and_rest_day_budget(fuel_user):
    d = date.today() - timedelta(days=3)
    with Session(engine) as db:
        db.add(PlannedSession(
            user_id=fuel_user, planned_date=d, session_type="run", status="missed",
            structure={"blocks": [{"duration_min": 60, "repeat": 1}]},
        ))
        db.commit()
        info = fuel.training_burn_kcal(fuel_user, d, weight_kg=70, run_kcal_per_kg_per_km=1.0, db=db)
        assert info["session_status"] == "skipped"
        assert info["burn"] == 0
        assert info["day_type"] == "rest"


def test_long_run_day_type_at_75_minutes_threshold(fuel_user):
    d = date.today() - timedelta(days=2)
    with Session(engine) as db:
        db.add(Workout(user_id=fuel_user, workout_date=d, name="long", workout_type="run",
                        distance_km=15, duration_seconds=75 * 60, tss=90))
        db.commit()
        info = fuel.training_burn_kcal(fuel_user, d, weight_kg=70, run_kcal_per_kg_per_km=1.0, db=db)
        assert info["day_type"] == "long_run"


def test_easy_run_day_type_under_75_minutes(fuel_user):
    d = date.today() - timedelta(days=2)
    with Session(engine) as db:
        db.add(Workout(user_id=fuel_user, workout_date=d, name="easy", workout_type="run",
                        distance_km=5, duration_seconds=30 * 60, tss=30))
        db.commit()
        info = fuel.training_burn_kcal(fuel_user, d, weight_kg=70, run_kcal_per_kg_per_km=1.0, db=db)
        assert info["day_type"] == "easy_run"
