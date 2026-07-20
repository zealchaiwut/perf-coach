"""Tests for issue #1412: phase chip shown even when auto_periodize is off.

AC: When auto_periodize=False, the API payload must return week_phase='base'
regardless of race proximity, so the frontend chip never shows misleading
modulation copy while the budget is unmodulated.

All tests are pure-function or mock-backed — no live DB required.
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from backend.services.fuel import compute_effective_deficit


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fake_settings_row(auto_periodize: bool, deficit_kcal: int = 300):
    """Return a minimal FuelSettings-like object for mocking."""
    return SimpleNamespace(
        weight_kg=70.0,
        lean_mass_kg=None,
        base_kcal=2400,
        maintenance_source="estimated",
        deficit_kcal=deficit_kcal,
        protein_g_per_kg=2.0,
        fat_g=70,
        ea_floor=30.0,
        run_kcal_per_kg_per_km=1.0,
        auto_periodize=auto_periodize,
    )


def _fake_burn_info():
    return {"burn": 0, "day_type": "rest", "is_actual": False, "session_status": None}


def _fake_lean_info():
    return {"lean_mass_kg": 53.2, "source": "estimated"}


# ── AC1: get_today_payload suppresses phase chip when auto_periodize is off ───

def test_get_today_payload_auto_periodize_off_returns_base_phase_even_with_race():
    """Payload must report week_phase='base' when toggle is off, even when the
    DB-resolved phase is 'race' (A/B race within 7 days)."""
    fake_settings = _fake_settings_row(auto_periodize=False)
    mock_db = MagicMock()
    today = date.today()

    with (
        patch("backend.services.fuel.get_or_create_settings", return_value=fake_settings),
        patch("backend.services.fuel._resolve_week_phase_from_db",
              return_value=("race", "Race week — maintenance", 300.0)),
        patch("backend.services.fuel._fetch_lean_mass", return_value=_fake_lean_info()),
        patch("backend.services.fuel.training_burn_kcal", return_value=_fake_burn_info()),
        patch("backend.services.fuel.get_entry", return_value=None),
    ):
        from backend.services.fuel import get_today_payload
        payload = get_today_payload(user_id=None, target_date=today, db=mock_db)

    assert payload["week_phase"] == "base", (
        f"Expected 'base' but got {payload['week_phase']!r} — "
        "chip would show misleading race-week copy while budget is unmodulated"
    )


def test_get_today_payload_auto_periodize_off_effective_deficit_equals_target():
    """When auto_periodize=False, effective_deficit_kcal must equal deficit_target
    regardless of what phase the DB resolves."""
    fake_settings = _fake_settings_row(auto_periodize=False, deficit_kcal=300)
    mock_db = MagicMock()
    today = date.today()

    with (
        patch("backend.services.fuel.get_or_create_settings", return_value=fake_settings),
        patch("backend.services.fuel._resolve_week_phase_from_db",
              return_value=("race", "Race week — maintenance", 300.0)),
        patch("backend.services.fuel._fetch_lean_mass", return_value=_fake_lean_info()),
        patch("backend.services.fuel.training_burn_kcal", return_value=_fake_burn_info()),
        patch("backend.services.fuel.get_entry", return_value=None),
    ):
        from backend.services.fuel import get_today_payload
        payload = get_today_payload(user_id=None, target_date=today, db=mock_db)

    assert payload["effective_deficit_kcal"] == payload["deficit_target"], (
        f"effective_deficit_kcal ({payload['effective_deficit_kcal']}) must equal "
        f"deficit_target ({payload['deficit_target']}) when auto_periodize is off"
    )


# ── AC2: get_week_payload suppresses phase chip when auto_periodize is off ────

def test_get_week_payload_auto_periodize_off_returns_base_phase_even_with_race():
    """Week payload must also report week_phase='base' when toggle is off,
    even when the resolved phase is 'race'."""
    fake_settings = _fake_settings_row(auto_periodize=False)
    mock_db = MagicMock()
    week_start = date.today() - timedelta(days=date.today().weekday())

    with (
        patch("backend.services.fuel.get_or_create_settings", return_value=fake_settings),
        patch("backend.services.fuel._resolve_week_phase_from_db",
              return_value=("race", "Race week — maintenance", 300.0)),
        patch("backend.services.fuel.training_burn_kcal", return_value=_fake_burn_info()),
        patch("backend.services.fuel.get_entry", return_value=None),
    ):
        from backend.services.fuel import get_week_payload
        payload = get_week_payload(user_id=None, week_start=week_start, db=mock_db)

    assert payload["week_phase"] == "base", (
        f"Expected 'base' but got {payload['week_phase']!r} — "
        "week note would show misleading phase copy while budget is unmodulated"
    )


# ── AC3: Regression — race phase is preserved when auto_periodize is on ──────

def test_get_today_payload_auto_periodize_on_race_returns_race_phase():
    """When auto_periodize=True and DB resolves 'race', payload must keep
    week_phase='race' (regression guard for the fix)."""
    fake_settings = _fake_settings_row(auto_periodize=True)
    mock_db = MagicMock()
    today = date.today()

    with (
        patch("backend.services.fuel.get_or_create_settings", return_value=fake_settings),
        patch("backend.services.fuel._resolve_week_phase_from_db",
              return_value=("race", "Race week — maintenance", 300.0)),
        patch("backend.services.fuel._fetch_lean_mass", return_value=_fake_lean_info()),
        patch("backend.services.fuel.training_burn_kcal", return_value=_fake_burn_info()),
        patch("backend.services.fuel.get_entry", return_value=None),
    ):
        from backend.services.fuel import get_today_payload
        payload = get_today_payload(user_id=None, target_date=today, db=mock_db)

    assert payload["week_phase"] == "race", (
        f"Expected 'race' but got {payload['week_phase']!r} — "
        "auto_periodize=True should preserve race phase modulation"
    )
    assert payload["effective_deficit_kcal"] == 0, (
        "Race week with auto_periodize=True must zero the deficit (maintenance)"
    )


# ── AC4: Pure-function guard — compute_effective_deficit ignores phase ────────

def test_compute_effective_deficit_auto_periodize_off_ignores_race_phase():
    """compute_effective_deficit with auto_periodize=False must return the
    configured deficit regardless of week_phase."""
    result = compute_effective_deficit(
        auto_periodize=False,
        configured_deficit_kcal=300,
        week_phase="race",
    )
    assert result == 300, (
        "With auto_periodize=False, effective deficit must equal configured deficit"
    )


def test_compute_effective_deficit_auto_periodize_off_ignores_taper_phase():
    """compute_effective_deficit with auto_periodize=False ignores taper phase too."""
    result = compute_effective_deficit(
        auto_periodize=False,
        configured_deficit_kcal=250,
        week_phase="taper",
    )
    assert result == 250
