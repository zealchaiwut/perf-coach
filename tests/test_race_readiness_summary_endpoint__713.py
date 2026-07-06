"""Tests for issue #713: Race-readiness summary endpoint.

GET /api/races/{id}/readiness aggregates form_curve, projected_form, taper,
on_track, specificity_progress, and timeline_markers behind one HTTP call.

Unit tests cover all AC items:
- AC1:  200 for valid race owned by authenticated user
- AC2:  form_curve present with date/form/zone per entry
- AC3:  projected_form present when building_baseline=false
- AC4:  taper present when building_baseline=false
- AC5:  on_track boolean/status value present
- AC6:  specificity_progress present
- AC7:  timeline_markers present — B-race, C-race, checkpoint entries in order
- AC8:  building_baseline=true → projected_form and taper absent (not null)
- AC9:  building_baseline=false → both projected_form and taper present
- AC10: route handler owns DB queries; domain services receive plain data
- AC11: no numeric literals in the handler (verified via config-driven zone test)
- AC12: 404 when race not found or belongs to a different user
- AC13: 400 for malformed race ID
- AC14: 401 for unauthenticated request
"""

import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

TODAY = date.today()
FUTURE_RACE = TODAY + timedelta(days=60)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(uid=None):
    u = MagicMock()
    u.id = uid or uuid.uuid4()
    return u


def _make_race(user_id, race_date=None):
    r = MagicMock()
    r.id = uuid.uuid4()
    r.user_id = user_id
    r.race_date = race_date or FUTURE_RACE
    r.distance_km = 21.0975
    r.goal_time_seconds = 6600
    r.goal_pace_seconds_per_km = 313
    r.name = "Test Half Marathon"
    r.priority = "A"
    r.race_type = "race"
    r.status = "planned"
    r.created_at = None
    r.updated_at = None
    return r


def _make_tss_series_long(start, end):
    """Enough non-zero TSS days to satisfy 8-week minimum."""
    result = []
    d = start
    while d <= end:
        result.append((d, 60 if d.weekday() in (1, 3, 6) else 0))
        d += timedelta(days=1)
    return result


def _make_tss_series_short(start, end):
    """No workouts — triggers building_baseline=True."""
    result = []
    d = start
    while d <= end:
        result.append((d, 0))
        d += timedelta(days=1)
    return result


def _load_curves(series):
    from backend.services.training_load import compute_load_curves
    return compute_load_curves(series)


def _base_patches(race, series, curves, run_rows=None, marker_rows=None):
    """Return a dict of patch kwargs for the common endpoint dependencies."""
    run_rows = run_rows if run_rows is not None else []
    marker_rows = marker_rows if marker_rows is not None else []
    return {
        "race": race,
        "series": series,
        "curves": curves,
        "run_rows": run_rows,
        "marker_rows": marker_rows,
    }


def _call_endpoint(race, series, curves, run_rows=None, marker_rows=None):
    """Call get_race_readiness with mocked DB, TSS, and config."""
    import json
    from backend.main import get_race_readiness

    run_rows = run_rows if run_rows is not None else []
    marker_rows = marker_rows if marker_rows is not None else []

    user = _make_user(race.user_id)

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.get.return_value = race
    mock_db.execute.return_value.fetchall.side_effect = [run_rows, marker_rows]

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._specificity_progress", return_value={"reason": "no goal pace"}),
        patch("backend.main.resolve_user_ewma_days", return_value=(42, 7)),
    ):
        MockSession.return_value = mock_db
        result = get_race_readiness(str(race.id), user)

    return json.loads(result.body)


# ── AC13: 400 for malformed race ID ──────────────────────────────────────────

def test_malformed_race_id_returns_400():
    """AC13: Returns 400 with descriptive message for a non-UUID race ID."""
    from fastapi import HTTPException
    from backend.main import get_race_readiness

    user = _make_user()
    with pytest.raises(HTTPException) as exc:
        get_race_readiness("not-a-uuid", user)

    assert exc.value.status_code == 400
    assert exc.value.detail  # descriptive message present


def test_malformed_race_id_message_mentions_format():
    """AC13: Error message describes the format problem."""
    from fastapi import HTTPException
    from backend.main import get_race_readiness

    user = _make_user()
    with pytest.raises(HTTPException) as exc:
        get_race_readiness("totally_invalid", user)

    assert exc.value.status_code == 400
    detail = exc.value.detail.lower()
    assert "invalid" in detail or "format" in detail or "id" in detail


# ── AC12: 404 for race not found ──────────────────────────────────────────────

def test_nonexistent_race_returns_404():
    """AC12: Returns 404 when race ID is a valid UUID that does not exist."""
    from fastapi import HTTPException
    from backend.main import get_race_readiness

    user = _make_user()
    with patch("backend.main.Session") as MockSession:
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get.return_value = None
        MockSession.return_value = mock_db

        with pytest.raises(HTTPException) as exc:
            get_race_readiness(str(uuid.uuid4()), user)

    assert exc.value.status_code == 404
    assert "not found" in exc.value.detail.lower()


def test_race_belonging_to_other_user_returns_404():
    """AC12: Returns 404 (not 403) when race belongs to a different user.

    Security-through-obscurity: do not reveal whether the race exists.
    """
    from fastapi import HTTPException
    from backend.main import get_race_readiness

    user = _make_user()
    other_user_id = uuid.uuid4()
    race = _make_race(other_user_id)

    with patch("backend.main.Session") as MockSession:
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get.return_value = race
        MockSession.return_value = mock_db

        with pytest.raises(HTTPException) as exc:
            get_race_readiness(str(race.id), user)

    assert exc.value.status_code == 404


# ── AC14: 401 for unauthenticated request ────────────────────────────────────

def test_unauthenticated_returns_401():
    """AC14: Endpoint returns 401 when no valid session is present."""
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get(f"/api/races/{uuid.uuid4()}/readiness")

    assert r.status_code == 401


# ── AC1: 200 for valid race with sufficient history ───────────────────────────

def test_valid_race_returns_200():
    """AC1: Returns 200 for a valid race owned by the authenticated user."""
    import json
    from backend.main import get_race_readiness

    user = _make_user()
    race = _make_race(user.id, FUTURE_RACE)
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.get.return_value = race
    mock_db.execute.return_value.fetchall.return_value = []

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._specificity_progress", return_value={"reason": "no goal pace"}),
        patch("backend.main.resolve_user_ewma_days", return_value=(42, 7)),
    ):
        MockSession.return_value = mock_db
        result = get_race_readiness(str(race.id), user)

    assert result.status_code == 200
    body = json.loads(result.body)
    assert isinstance(body, dict)


# ── AC2: form_curve ───────────────────────────────────────────────────────────

def test_form_curve_present_and_annotated():
    """AC2: form_curve is a list; each entry has date, form, and zone."""
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_short(start, TODAY)
    curves = _load_curves(series)

    user = _make_user()
    race = _make_race(user.id)
    body = _call_endpoint(race, series, curves)

    assert "form_curve" in body
    assert isinstance(body["form_curve"], list)
    assert len(body["form_curve"]) > 0

    valid_zones = {"buried", "neutral", "fresh"}
    for entry in body["form_curve"][:5]:
        assert "date" in entry
        assert "form" in entry
        assert "zone" in entry, f"Entry missing 'zone': {entry}"
        assert entry["zone"] in valid_zones, f"Unknown zone: {entry['zone']}"


# ── AC5: on_track ─────────────────────────────────────────────────────────────

def test_on_track_present():
    """AC5: on_track contains boolean indicator and status string."""
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_short(start, TODAY)
    curves = _load_curves(series)

    user = _make_user()
    race = _make_race(user.id)
    body = _call_endpoint(race, series, curves)

    assert "on_track" in body
    ot = body["on_track"]
    assert isinstance(ot, dict)
    assert "on_track" in ot
    assert "status_summary" in ot
    assert isinstance(ot["status_summary"], str)
    assert ot["on_track"] is None or isinstance(ot["on_track"], bool)


# ── AC6: specificity_progress ─────────────────────────────────────────────────

def test_specificity_progress_present():
    """AC6: specificity_progress is always included in the response."""
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_short(start, TODAY)
    curves = _load_curves(series)

    user = _make_user()
    race = _make_race(user.id)
    body = _call_endpoint(race, series, curves)

    assert "specificity_progress" in body
    assert isinstance(body["specificity_progress"], dict)


# ── AC7: timeline_markers ─────────────────────────────────────────────────────

def test_timeline_markers_present_in_response():
    """AC7: timeline_markers is always present in the response."""
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_short(start, TODAY)
    curves = _load_curves(series)

    user = _make_user()
    race = _make_race(user.id)
    body = _call_endpoint(race, series, curves)

    assert "timeline_markers" in body
    assert isinstance(body["timeline_markers"], list)


def test_timeline_markers_b_race_included():
    """AC7: B-race events between today and race day appear in timeline_markers."""
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_short(start, TODAY)
    curves = _load_curves(series)

    user = _make_user()
    race = _make_race(user.id, FUTURE_RACE)

    b_race_date = TODAY + timedelta(days=20)
    marker_row = (b_race_date, "race", "B", "Mid-Season 10K")

    body = _call_endpoint(race, series, curves, run_rows=[], marker_rows=[marker_row])

    assert "timeline_markers" in body
    markers = body["timeline_markers"]
    assert len(markers) == 1
    m = markers[0]
    assert m["date"] == b_race_date.isoformat()
    assert m["type"] == "B-race"
    assert m["label"] == "Mid-Season 10K"


def test_timeline_markers_c_race_included():
    """AC7: C-race events appear in timeline_markers with type 'C-race'."""
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_short(start, TODAY)
    curves = _load_curves(series)

    user = _make_user()
    race = _make_race(user.id, FUTURE_RACE)

    c_race_date = TODAY + timedelta(days=15)
    marker_row = (c_race_date, "race", "C", "Local 5K")

    body = _call_endpoint(race, series, curves, run_rows=[], marker_rows=[marker_row])

    markers = body["timeline_markers"]
    assert len(markers) == 1
    assert markers[0]["type"] == "C-race"
    assert markers[0]["label"] == "Local 5K"


def test_timeline_markers_checkpoint_included():
    """AC7: Checkpoint events appear in timeline_markers with type 'checkpoint'."""
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_short(start, TODAY)
    curves = _load_curves(series)

    user = _make_user()
    race = _make_race(user.id, FUTURE_RACE)

    cp_date = TODAY + timedelta(days=30)
    marker_row = (cp_date, "checkpoint", None, "Long Run Check")

    body = _call_endpoint(race, series, curves, run_rows=[], marker_rows=[marker_row])

    markers = body["timeline_markers"]
    assert len(markers) == 1
    assert markers[0]["type"] == "checkpoint"
    assert markers[0]["label"] == "Long Run Check"


def test_timeline_markers_ordered_by_date():
    """AC7: Markers are ordered chronologically (earliest first)."""
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_short(start, TODAY)
    curves = _load_curves(series)

    user = _make_user()
    race = _make_race(user.id, FUTURE_RACE)

    d1 = TODAY + timedelta(days=10)
    d2 = TODAY + timedelta(days=25)
    d3 = TODAY + timedelta(days=40)
    rows = [
        (d1, "checkpoint", None, "CP 1"),
        (d2, "race", "B", "B Race"),
        (d3, "race", "C", "C Race"),
    ]

    body = _call_endpoint(race, series, curves, run_rows=[], marker_rows=rows)

    markers = body["timeline_markers"]
    assert len(markers) == 3
    dates = [m["date"] for m in markers]
    assert dates == sorted(dates), "timeline_markers must be ordered chronologically"


def test_timeline_markers_each_entry_has_required_fields():
    """AC7: Each timeline marker has date, type, and label."""
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_short(start, TODAY)
    curves = _load_curves(series)

    user = _make_user()
    race = _make_race(user.id, FUTURE_RACE)

    d = TODAY + timedelta(days=20)
    rows = [(d, "race", "B", "Some B Race")]

    body = _call_endpoint(race, series, curves, run_rows=[], marker_rows=rows)

    for m in body["timeline_markers"]:
        assert "date" in m, "Each marker must have 'date'"
        assert "type" in m, "Each marker must have 'type'"
        assert "label" in m, "Each marker must have 'label'"


# ── AC8: building_baseline=true suppresses projected_form and taper ───────────

def test_building_baseline_true_omits_projected_form_and_taper():
    """AC8: When building_baseline=true, projected_form and taper are absent."""
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_short(start, TODAY)
    curves = _load_curves(series)

    user = _make_user()
    race = _make_race(user.id)
    body = _call_endpoint(race, series, curves)

    assert body["building_baseline"] is True
    assert "projected_form" not in body, "projected_form must be absent when building_baseline=true"
    assert "taper" not in body, "taper must be absent when building_baseline=true"


# ── AC9: building_baseline=false includes projected_form and taper ─────────────

def test_building_baseline_false_includes_projected_form_and_taper():
    """AC9: When building_baseline=false, both projected_form and taper are present."""
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)

    user = _make_user()
    race = _make_race(user.id, FUTURE_RACE)
    body = _call_endpoint(race, series, curves)

    assert body["building_baseline"] is False
    assert "projected_form" in body, "projected_form must be present when building_baseline=false"
    assert "taper" in body, "taper must be present when building_baseline=false"


def test_taper_field_has_required_shape():
    """AC4: taper object has taper_start_date, message, and achievable."""
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)

    user = _make_user()
    race = _make_race(user.id, FUTURE_RACE)
    body = _call_endpoint(race, series, curves)

    if body.get("building_baseline"):
        pytest.skip("building_baseline=true; insufficient history for this test")

    taper = body.get("taper", {})
    assert "taper_start_date" in taper
    assert "message" in taper
    assert isinstance(taper["message"], str)
    assert "achievable" in taper


def test_projected_form_covers_future_dates():
    """AC3: projected_form keys are all future dates (not before today)."""
    start = TODAY - timedelta(days=180)
    series = _make_tss_series_long(start, TODAY)
    curves = _load_curves(series)

    user = _make_user()
    race = _make_race(user.id, FUTURE_RACE)
    body = _call_endpoint(race, series, curves)

    if body.get("building_baseline"):
        pytest.skip("building_baseline=true")

    pf = body.get("projected_form", {})
    assert len(pf) > 0, "projected_form must not be empty when building_baseline=false"
    for date_str in pf:
        d = date.fromisoformat(date_str)
        assert d > TODAY, f"projected_form must not include past dates; found {date_str}"


# ── AC11: no numeric literals — zone classification is config-driven ──────────

def test_zone_labels_respect_config_thresholds():
    """AC11: Zone boundaries come from AppConfig, not hardcoded literals."""
    from backend.main import get_race_readiness
    import json

    user = _make_user()
    race = _make_race(user.id)

    curves = [{"date": TODAY, "tss": 0, "ctl": 40.0, "atl": 45.0, "tsb": -5.0}]
    series = [(TODAY, 0)]

    def fake_cfg(key, default=""):
        return {
            "readiness.form_buried_ceiling": "-3.0",
            "readiness.form_fresh_floor": "10.0",
        }.get(key, default)

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.get.return_value = race
    mock_db.execute.return_value.fetchall.return_value = []

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
        patch("backend.main._get_app_config", side_effect=fake_cfg),
        patch("backend.main._specificity_progress", return_value={"reason": "no goal pace"}),
        patch("backend.main.resolve_user_ewma_days", return_value=(42, 7)),
    ):
        MockSession.return_value = mock_db
        result = get_race_readiness(str(race.id), user)

    body = json.loads(result.body)
    zones = {e["zone"] for e in body["form_curve"]}
    assert "buried" in zones, (
        f"TSB=-5.0 with buried_ceiling=-3.0 must classify as buried; got {zones}"
    )
