"""Tests for issue #1307: defer / promote detail_payload in _strava_source_dict.

ACs derived from the issue body (follow-up to #1295 AC2):
  AC1 – StravaActivity.detail_payload is declared with deferred() in models.py.
  AC2 – StravaActivity.raw_payload is declared with deferred() in models.py.
  AC3 – StravaActivity has four promoted scalar columns:
          laps, splits_metric, best_efforts (each JSONB, deferred)
          and calories (Integer, nullable).
  AC4 – strava_sync._map_fields extracts the promoted scalars from the detail
         blob when detail is provided.
  AC5 – _strava_source_dict reads laps from sa.laps when it is not None,
         bypassing detail_payload for that field.
  AC6 – Same fall-through for splits_metric, best_efforts, and calories.
  AC7 – When all four promoted columns are populated, detail_payload is not
         accessed by _strava_source_dict (no attribute access on sa).
"""
import pathlib
import re
import types
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

REPO = pathlib.Path(__file__).parents[1]


# ── helpers ────────────────────────────────────────────────────────────────

def _main_src() -> str:
    return (REPO / "backend" / "main.py").read_text()


def _models_src() -> str:
    return (REPO / "backend" / "models.py").read_text()


def _strava_sync_src() -> str:
    return (REPO / "backend" / "services" / "strava_sync.py").read_text()


# ── AC1: detail_payload deferred ───────────────────────────────────────────

def test_ac1_detail_payload_deferred():
    src = _models_src()
    m = re.search(r"detail_payload\s*=\s*deferred\s*\(", src)
    assert m, (
        "AC1: StravaActivity.detail_payload must be declared with deferred() "
        "in backend/models.py."
    )


# ── AC2: raw_payload deferred ──────────────────────────────────────────────

def test_ac2_raw_payload_deferred_strava():
    src = _models_src()
    # Find the StravaActivity class block and confirm raw_payload is deferred there.
    strava_block_match = re.search(
        r"class StravaActivity\(Base\):(.*?)class \w+\(Base\):",
        src,
        re.DOTALL,
    )
    assert strava_block_match, "StravaActivity class not found in models.py"
    block = strava_block_match.group(1)
    assert re.search(r"raw_payload\s*=\s*deferred\s*\(", block), (
        "AC2: StravaActivity.raw_payload must be declared with deferred() "
        "inside the StravaActivity class block."
    )


# ── AC3: promoted scalar columns exist ────────────────────────────────────

def _strava_activity_block(src: str) -> str:
    m = re.search(
        r"class StravaActivity\(Base\):(.*?)(?=\nclass |\Z)",
        src,
        re.DOTALL,
    )
    assert m, "StravaActivity class not found in models.py"
    return m.group(1)


def test_ac3_laps_column_exists():
    block = _strava_activity_block(_models_src())
    assert re.search(r"\blaps\s*=\s*deferred\s*\(", block), (
        "AC3: StravaActivity must have a `laps = deferred(Column(JSONB, ...))` column."
    )


def test_ac3_splits_metric_column_exists():
    block = _strava_activity_block(_models_src())
    assert re.search(r"\bsplits_metric\s*=\s*deferred\s*\(", block), (
        "AC3: StravaActivity must have a `splits_metric = deferred(Column(JSONB, ...))` column."
    )


def test_ac3_best_efforts_column_exists():
    block = _strava_activity_block(_models_src())
    assert re.search(r"\bbest_efforts\s*=\s*deferred\s*\(", block), (
        "AC3: StravaActivity must have a `best_efforts = deferred(Column(JSONB, ...))` column."
    )


def test_ac3_calories_column_exists():
    block = _strava_activity_block(_models_src())
    # calories can be deferred or not; must be an Integer or Numeric column.
    assert re.search(r"\bcalories\s*=\s*(deferred\s*\()?Column\s*\(", block), (
        "AC3: StravaActivity must have a `calories` column (Integer, nullable)."
    )


# ── AC4: _map_fields extracts promoted scalars from detail ─────────────────

def test_ac4_map_fields_sets_laps():
    src = _strava_sync_src()
    # Match either dict-literal `"laps":` or assignment `fields["laps"] =`.
    assert re.search(r'["\[]laps["]\]?\s*[=:]', src), (
        "AC4: strava_sync must set 'laps' from the detail blob."
    )


def test_ac4_map_fields_sets_splits_metric():
    src = _strava_sync_src()
    assert re.search(r'["\[]splits_metric["]\]?\s*[=:]', src), (
        "AC4: strava_sync must set 'splits_metric' from the detail blob."
    )


def test_ac4_map_fields_sets_best_efforts():
    src = _strava_sync_src()
    assert re.search(r'["\[]best_efforts["]\]?\s*[=:]', src), (
        "AC4: strava_sync must set 'best_efforts' from the detail blob."
    )


def test_ac4_map_fields_sets_calories():
    src = _strava_sync_src()
    assert re.search(r'["\[]calories["]\]?\s*[=:]', src), (
        "AC4: strava_sync must set 'calories' from the detail blob."
    )


# ── AC5/AC6: _strava_source_dict reads from promoted columns ───────────────

def _make_sa(
    laps=None, splits_metric=None, best_efforts=None, calories=None,
    detail_payload=None,
):
    """Return a minimal mock StravaActivity-like object."""
    sa = MagicMock()
    sa.laps = laps
    sa.splits_metric = splits_metric
    sa.best_efforts = best_efforts
    sa.calories = calories
    sa.detail_payload = detail_payload
    sa.raw_payload = {}
    sa.streams_payload = {}
    sa.strava_activity_id = 1
    sa.name = "Test"
    sa.activity_type = "Run"
    sa.start_time = None
    sa.distance_km = None
    sa.duration_seconds = None
    sa.avg_hr = None
    sa.max_hr = None
    sa.elevation_m = None
    sa.avg_power_w = None
    sa.max_power_w = None
    sa.avg_cadence = None
    sa.suffer_score = None
    sa.device_name = None
    sa.external_id = None
    sa.is_stryd_synced = False
    return sa


def _call_strava_source_dict(sa, **kwargs):
    from backend.main import _strava_source_dict
    return _strava_source_dict(sa, **kwargs)


def test_ac5_laps_from_promoted_column():
    laps_data = [{"distance": 1000}]
    sa = _make_sa(laps=laps_data, splits_metric=[], best_efforts=[], calories=None)
    result = _call_strava_source_dict(sa)
    assert result["laps"] == laps_data, (
        "AC5: _strava_source_dict must return sa.laps when it is not None."
    )


def test_ac5_splits_from_promoted_column():
    splits_data = [{"distance": 1000, "elapsed_time": 300}]
    sa = _make_sa(laps=[], splits_metric=splits_data, best_efforts=[], calories=None)
    result = _call_strava_source_dict(sa)
    assert result["splits_metric"] == splits_data, (
        "AC6: _strava_source_dict must return sa.splits_metric when it is not None."
    )


def test_ac6_best_efforts_from_promoted_column():
    be_data = [{"name": "1 mile", "elapsed_time": 360}]
    sa = _make_sa(laps=[], splits_metric=[], best_efforts=be_data, calories=None)
    result = _call_strava_source_dict(sa)
    assert result["best_efforts"] == be_data, (
        "AC6: _strava_source_dict must return sa.best_efforts when it is not None."
    )


def test_ac6_calories_from_promoted_column():
    sa = _make_sa(laps=[], splits_metric=[], best_efforts=[], calories=500)
    result = _call_strava_source_dict(sa)
    assert result["calories"] == 500, (
        "AC6: _strava_source_dict must return sa.calories when it is not None."
    )


# ── AC7: detail_payload not accessed when promoted columns are all set ──────

def test_ac7_no_detail_payload_access_when_promoted():
    """When all four promoted columns are non-None, detail_payload must not be
    accessed (no lazy-load triggered for those four fields).
    """
    sa = MagicMock(spec=[
        "laps", "splits_metric", "best_efforts", "calories",
        "strava_activity_id", "name", "activity_type", "start_time",
        "distance_km", "duration_seconds", "avg_hr", "max_hr",
        "elevation_m", "avg_power_w", "max_power_w", "avg_cadence",
        "suffer_score", "device_name", "external_id", "is_stryd_synced",
        "raw_payload", "streams_payload", "detail_payload",
    ])
    sa.laps = [{"distance": 1000}]
    sa.splits_metric = []
    sa.best_efforts = []
    sa.calories = 300
    sa.raw_payload = {}
    sa.streams_payload = {}
    sa.strava_activity_id = 42
    sa.name = "Morning Run"
    sa.activity_type = "Run"
    sa.start_time = None
    sa.distance_km = None
    sa.duration_seconds = None
    sa.avg_hr = None
    sa.max_hr = None
    sa.elevation_m = None
    sa.avg_power_w = None
    sa.max_power_w = None
    sa.avg_cadence = None
    sa.suffer_score = None
    sa.device_name = None
    sa.external_id = None
    sa.is_stryd_synced = False

    # Set up detail_payload as a property-mock that records accesses.
    accessed = []
    type(sa).detail_payload = PropertyMock(
        side_effect=lambda: accessed.append(True) or {}
    )

    from backend.main import _strava_source_dict
    result = _strava_source_dict(sa)

    assert result["laps"] == [{"distance": 1000}]
    assert result["calories"] == 300
    assert not accessed, (
        "AC7: detail_payload must NOT be accessed when all four promoted "
        "columns (laps, splits_metric, best_efforts, calories) are non-None. "
        f"detail_payload was accessed {len(accessed)} time(s)."
    )


# ── fallback: old rows without promoted columns still work ─────────────────

def test_fallback_uses_detail_payload_when_promoted_columns_are_none():
    """Rows synced before the column addition have promoted columns = None;
    _strava_source_dict must fall back to detail_payload for those fields.
    """
    detail = {
        "laps": [{"distance": 500}],
        "splits_metric": [{"elapsed_time": 60}],
        "best_efforts": [{"name": "400m"}],
        "calories": 250,
    }
    # All promoted cols are None → simulate old row.
    sa = _make_sa(
        laps=None, splits_metric=None, best_efforts=None, calories=None,
        detail_payload=detail,
    )
    result = _call_strava_source_dict(sa)
    assert result["laps"] == [{"distance": 500}], "fallback laps from detail_payload"
    assert result["calories"] == 250, "fallback calories from detail_payload"
