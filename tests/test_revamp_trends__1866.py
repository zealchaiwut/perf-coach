"""P5-4 Training Trends lower half: decoupling, form, zone mix."""
from __future__ import annotations

import inspect
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.services import revamp_trends as rt

TODAY = date(2026, 11, 12)
UID = uuid.uuid4()


def test_decoupling_imports_qualifier_from_axis_durability():
    src = inspect.getsource(rt.build_decoupling_panel)
    assert "axis_durability.is_qualifying_run" in src
    assert "axis_durability.fetch_runs" in src


def test_form_tiles_import_easy_pool():
    src = inspect.getsource(rt.build_form_tiles)
    assert "axis_economy.easy_pool" in src


@patch.object(rt.axis_durability, "fetch_runs")
def test_decoupling_outlier_note(mock_fetch):
    runs = [
        SimpleNamespace(workout_date=date(2026, 8, 1), duration_seconds=6000, decoupling_percent=24.6, zone2_minutes=70, name="Hot long"),
        SimpleNamespace(workout_date=date(2026, 10, 1), duration_seconds=6000, decoupling_percent=9.0, zone2_minutes=70, name="Long"),
        SimpleNamespace(workout_date=date(2026, 10, 20), duration_seconds=6000, decoupling_percent=8.5, zone2_minutes=70, name="Long 2"),
    ]
    mock_fetch.return_value = runs
    out = rt.build_decoupling_panel(MagicMock(), UID, date(2026, 7, 1), TODAY, today=TODAY)
    assert out["median_last_4_pct"] == 9.0
    assert out["note"] and "August" in out["note"]


@patch.object(rt, "fetch_easy_form_rows", return_value=[])
@patch.object(rt.axis_strength, "fetch_trend_mass", return_value=(70.0, 3))
def test_form_tiles_six_metrics(_mass, _rows):
    out = rt.build_form_tiles(MagicMock(), UID, TODAY, TODAY, today=TODAY)
    assert len(out["tiles"]) == 6
    assert out["tiles"][0]["pool"] == "axis_economy.easy_pool"


def test_zone_mix_month_buckets():
    session = MagicMock()
    wd = date(2026, 10, 15)
    pz = {"seconds_in_zones": [600, 3000, 500, 100, 0]}
    session.query.return_value.join.return_value.filter.return_value.all.return_value = [(wd, pz)]
    out = rt.build_zone_mix(session, UID, date(2026, 10, 1), TODAY, today=TODAY)
    assert out["months"] and out["months"][0]["total_hours"] > 0


@patch.object(rt, "build_zone_mix", return_value={"months": []})
@patch.object(rt, "build_form_tiles", return_value={"tiles": []})
@patch.object(rt, "build_decoupling_panel", return_value={"points": []})
@patch.object(rt, "build_weekly_load", return_value=([], {"week_count": 0}))
@patch.object(rt, "build_phase_spans", return_value=[])
@patch.object(rt, "build_fitness_series", return_value=[])
def test_trends_payload_includes_lower_panels(*_mocks):
    out = rt.trends_payload(MagicMock(), UID, range_key="3m", today=TODAY)
    assert "decoupling" in out and "form_tiles" in out and "zone_mix" in out