"""Tests for issue #1411: skip week-phase resolver when auto_periodize is off.

AC: When auto_periodize=False, _resolve_week_phase_from_db must NOT be called
in get_today_payload or get_week_payload — the DB/load-plan work is wasted
because compute_effective_deficit ignores the phase anyway.

These tests verify the short-circuit at the call site, complementing the
correctness tests in test_fuel_phase_chip__1412.py.
"""
from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, call


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fake_settings_row(auto_periodize: bool, deficit_kcal: int = 300):
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


# ── AC1: resolver skipped entirely in get_today_payload when off ──────────────

def test_get_today_payload_resolver_not_called_when_auto_periodize_off():
    """_resolve_week_phase_from_db must not be called at all when auto_periodize
    is False — skipping DB queries and compute_load_plan for no-op work."""
    fake_settings = _fake_settings_row(auto_periodize=False)
    mock_db = MagicMock()
    today = date.today()

    with (
        patch("backend.services.fuel.get_or_create_settings", return_value=fake_settings),
        patch("backend.services.fuel._resolve_week_phase_from_db") as mock_resolver,
        patch("backend.services.fuel._fetch_lean_mass", return_value=_fake_lean_info()),
        patch("backend.services.fuel.training_burn_kcal", return_value=_fake_burn_info()),
        patch("backend.services.fuel.get_entry", return_value=None),
    ):
        from backend.services.fuel import get_today_payload
        payload = get_today_payload(user_id=None, target_date=today, db=mock_db)

    mock_resolver.assert_not_called(), (
        "_resolve_week_phase_from_db was called but should be short-circuited "
        "when auto_periodize=False"
    )
    assert payload["week_phase"] == "base"
    assert payload["week_phase_reason"] == "Base week — full deficit"


def test_get_today_payload_resolver_called_when_auto_periodize_on():
    """Regression: _resolve_week_phase_from_db must still be called when
    auto_periodize=True."""
    fake_settings = _fake_settings_row(auto_periodize=True)
    mock_db = MagicMock()
    today = date.today()

    with (
        patch("backend.services.fuel.get_or_create_settings", return_value=fake_settings),
        patch("backend.services.fuel._resolve_week_phase_from_db",
              return_value=("base", "Base week — full deficit", None)) as mock_resolver,
        patch("backend.services.fuel._fetch_lean_mass", return_value=_fake_lean_info()),
        patch("backend.services.fuel.training_burn_kcal", return_value=_fake_burn_info()),
        patch("backend.services.fuel.get_entry", return_value=None),
    ):
        from backend.services.fuel import get_today_payload
        get_today_payload(user_id=None, target_date=today, db=mock_db)

    mock_resolver.assert_called_once()


# ── AC2: resolver skipped entirely in get_week_payload when off ───────────────

def test_get_week_payload_resolver_not_called_when_auto_periodize_off():
    """_resolve_week_phase_from_db must not be called at all in get_week_payload
    when auto_periodize is False."""
    fake_settings = _fake_settings_row(auto_periodize=False)
    mock_db = MagicMock()
    week_start = date.today() - timedelta(days=date.today().weekday())

    with (
        patch("backend.services.fuel.get_or_create_settings", return_value=fake_settings),
        patch("backend.services.fuel._resolve_week_phase_from_db") as mock_resolver,
        patch("backend.services.fuel.training_burn_kcal", return_value=_fake_burn_info()),
        patch("backend.services.fuel.get_entry", return_value=None),
    ):
        from backend.services.fuel import get_week_payload
        payload = get_week_payload(user_id=None, week_start=week_start, db=mock_db)

    mock_resolver.assert_not_called(), (
        "_resolve_week_phase_from_db was called in get_week_payload but should be "
        "short-circuited when auto_periodize=False"
    )
    assert payload["week_phase"] == "base"
    assert payload["week_phase_reason"] == "Base week — full deficit"


def test_get_week_payload_resolver_called_when_auto_periodize_on():
    """Regression: _resolve_week_phase_from_db must still be called in
    get_week_payload when auto_periodize=True."""
    fake_settings = _fake_settings_row(auto_periodize=True)
    mock_db = MagicMock()
    week_start = date.today() - timedelta(days=date.today().weekday())

    with (
        patch("backend.services.fuel.get_or_create_settings", return_value=fake_settings),
        patch("backend.services.fuel._resolve_week_phase_from_db",
              return_value=("base", "Base week — full deficit", None)) as mock_resolver,
        patch("backend.services.fuel.training_burn_kcal", return_value=_fake_burn_info()),
        patch("backend.services.fuel.get_entry", return_value=None),
    ):
        from backend.services.fuel import get_week_payload
        get_week_payload(user_id=None, week_start=week_start, db=mock_db)

    mock_resolver.assert_called_once()
