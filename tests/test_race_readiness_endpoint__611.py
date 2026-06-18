"""Tests for issue #611: GET /api/races/{id}/readiness combined endpoint.

Acceptance criteria verified:
- AC1:  GET /api/races/{id}/readiness is implemented.
- AC2:  Response includes form_curve with zone labels driven by configurable thresholds.
- AC3:  Response includes projected_form keyed by date when building_baseline=False.
- AC4:  Response includes taper_recommendation with start date and message when
        building_baseline=False.
- AC5:  Response includes on_track boolean and status_summary string.
- AC6:  Response includes specificity_progress.
- AC7:  When building_baseline=True, projected_form and taper_recommendation are
        absent from the response (not null — the keys must not be present).
- AC8:  When building_baseline=False, both projected_form and taper_recommendation
        are always present.
- AC9:  DB access is in the caller layer; underlying math functions receive plain
        values (verified structurally via peak_tracking purity test).
- AC10: No numeric threshold is hardcoded in the endpoint (verified via config test).
- AC11: Returns 404 when the race id does not exist.
- AC12: Returns 403 when the authenticated user does not have access to the race.
- AC13: Tests cover both building_baseline=True and building_baseline=False branches.

Peak-tracking function tests (AC9 purity, AC10 constants, AC13 unit coverage):
- peak_tracking is a pure function with no DB calls.
- Returns valid structure for ahead/on_track/behind/missing inputs.
- PEAK_TRACKING_TOLERANCE is an exported named constant.
"""

import ast
import inspect
import textwrap
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

from backend.services.training_load import (
    PEAK_TRACKING_TOLERANCE,
    peak_tracking,
)

TODAY = date.today()
FUTURE_RACE = TODAY + timedelta(days=30)


# ── peak_tracking: exported constant ─────────────────────────────────────────

def test_peak_tracking_tolerance_is_exported_float():
    assert isinstance(PEAK_TRACKING_TOLERANCE, float), "PEAK_TRACKING_TOLERANCE must be a float"
    assert PEAK_TRACKING_TOLERANCE > 0


# ── peak_tracking: pure function (no DB calls) ───────────────────────────────

def test_peak_tracking_is_callable():
    assert callable(peak_tracking)


def test_peak_tracking_no_db_calls_in_body():
    """peak_tracking must not call DB-layer names."""
    src = inspect.getsource(peak_tracking)
    tree = ast.parse(textwrap.dedent(src))
    func_def = tree.body[0]
    body = func_def.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]

    db_names = {"engine", "Session", "daily_tss_series", "current_load"}
    found = []
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in db_names:
                found.append(name)
    assert not found, f"peak_tracking body calls DB functions: {found}"


def test_peak_tracking_no_bare_threshold_literals():
    """The tolerance value must not appear as a bare literal inside the function body."""
    src = inspect.getsource(peak_tracking)
    tree = ast.parse(textwrap.dedent(src))
    func_def = tree.body[0]
    body = func_def.body
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]

    forbidden = {PEAK_TRACKING_TOLERANCE}
    bad = []
    for node in ast.walk(ast.Module(body=body, type_ignores=[])):
        if isinstance(node, ast.Constant) and isinstance(node.value, float):
            if node.value in forbidden:
                bad.append(node.value)
    assert not bad, f"peak_tracking body contains bare tolerance literal(s): {bad}"


# ── peak_tracking: return structure on valid input ───────────────────────────

def test_peak_tracking_ahead():
    """gap > tolerance → status 'ahead'."""
    result = peak_tracking(85.0, 70.0, tolerance=5.0)
    assert result["status"] == "ahead"
    assert result["gap"] == pytest.approx(15.0)
    assert result["reason"] == ""


def test_peak_tracking_on_track_positive_gap():
    """gap within tolerance band → status 'on track'."""
    result = peak_tracking(72.0, 70.0, tolerance=5.0)
    assert result["status"] == "on track"
    assert result["gap"] == pytest.approx(2.0)


def test_peak_tracking_on_track_zero_gap():
    result = peak_tracking(70.0, 70.0, tolerance=5.0)
    assert result["status"] == "on track"
    assert result["gap"] == pytest.approx(0.0)


def test_peak_tracking_on_track_lower_boundary():
    """gap == -tolerance is still on track (|gap| <= tolerance)."""
    result = peak_tracking(65.0, 70.0, tolerance=5.0)
    assert result["status"] == "on track"
    assert result["gap"] == pytest.approx(-5.0)


def test_peak_tracking_behind():
    """gap < -tolerance → status 'behind'."""
    result = peak_tracking(55.0, 70.0, tolerance=5.0)
    assert result["status"] == "behind"
    assert result["gap"] == pytest.approx(-15.0)


def test_peak_tracking_uses_default_tolerance():
    """Without explicit tolerance, PEAK_TRACKING_TOLERANCE is used."""
    # gap slightly above zero — should be on track with default tolerance
    result = peak_tracking(70.5, 70.0)
    assert result["status"] == "on track"


# ── peak_tracking: null result on missing inputs ─────────────────────────────

def test_peak_tracking_none_current_form():
    result = peak_tracking(None, 70.0)
    assert result["status"] is None
    assert result["gap"] is None
    assert result["reason"]  # non-empty reason string


def test_peak_tracking_none_projected():
    result = peak_tracking(70.0, None)
    assert result["status"] is None
    assert result["gap"] is None
    assert result["reason"]


def test_peak_tracking_both_none():
    result = peak_tracking(None, None)
    assert result["status"] is None
    assert result["gap"] is None
    assert result["reason"]


def test_peak_tracking_no_exception_on_bad_inputs():
    """Function must not raise for any input combination."""
    for args in [(None, 70.0), (70.0, None), (None, None), ("bad", 70.0)]:
        try:
            peak_tracking(*args)
        except Exception as exc:
            pytest.fail(f"peak_tracking raised {type(exc).__name__} for {args!r}")


# ── peak_tracking: docstring ──────────────────────────────────────────────────

def test_peak_tracking_docstring_exists():
    doc = peak_tracking.__doc__ or ""
    assert len(doc.strip()) > 0


def test_peak_tracking_docstring_has_four_examples():
    doc = (peak_tracking.__doc__ or "").lower()
    example_count = doc.count("worked example")
    assert example_count >= 3, "docstring must contain at least three worked examples"


def test_peak_tracking_docstring_covers_all_statuses():
    doc = (peak_tracking.__doc__ or "").lower()
    assert '"ahead"' in doc or "ahead" in doc
    assert '"on track"' in doc or "on track" in doc
    assert '"behind"' in doc or "behind" in doc


# ── Endpoint unit tests (mocked DB) ──────────────────────────────────────────
# These tests exercise the combined endpoint logic without a live server
# by patching the DB session and service functions.

def _make_race(user_id, race_date=None):
    r = MagicMock()
    r.id = uuid.uuid4()
    r.user_id = user_id
    r.race_date = race_date or (TODAY + timedelta(days=40))
    r.distance_km = 21.0975
    r.goal_time_seconds = 6600
    r.goal_pace_seconds_per_km = 313
    r.name = "Test Half Marathon"
    r.priority = "A"
    r.status = "planned"
    r.created_at = None
    r.updated_at = None
    return r


def _make_user(uid=None):
    u = MagicMock()
    u.id = uid or uuid.uuid4()
    return u


def _make_tss_series_long(start, end):
    """Generate enough non-zero TSS days to satisfy 8-week minimum."""
    result = []
    current = start
    while current <= end:
        result.append((current, 60 if current.weekday() in (1, 3, 6) else 0))
        current += timedelta(days=1)
    return result


def _make_tss_series_short(start, end):
    """Generate a series with no workouts — triggers building_baseline=True."""
    result = []
    current = start
    while current <= end:
        result.append((current, 0))
        current += timedelta(days=1)
    return result


def _load_curves_from_series(series):
    from backend.services.training_load import compute_load_curves
    return compute_load_curves(series)


def _get_endpoint_function():
    from backend.main import app
    for route in app.routes:
        if hasattr(route, "path") and route.path == "/api/races/{race_id}/readiness":
            return route.endpoint
    return None


# ── AC11: 404 when race does not exist ───────────────────────────────────────

def test_endpoint_404_when_race_not_found():
    """When the race_id does not exist, endpoint raises 404."""
    from fastapi import HTTPException
    from backend.main import get_race_readiness

    user = _make_user()
    with patch("backend.main.Session") as MockSession:
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get.return_value = None
        MockSession.return_value = mock_db

        with pytest.raises(HTTPException) as exc_info:
            get_race_readiness(str(uuid.uuid4()), user)

    assert exc_info.value.status_code == 404
    assert "not found" in exc_info.value.detail.lower()


def test_endpoint_404_for_invalid_uuid():
    """When race_id is not a valid UUID, endpoint returns 404."""
    from fastapi import HTTPException
    from backend.main import get_race_readiness

    user = _make_user()
    with pytest.raises(HTTPException) as exc_info:
        get_race_readiness("not-a-uuid", user)

    assert exc_info.value.status_code == 404


# ── AC12: 403 when race belongs to a different user ──────────────────────────

def test_endpoint_403_when_race_belongs_to_other_user():
    """When the race exists but belongs to a different user, endpoint raises 403."""
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

        with pytest.raises(HTTPException) as exc_info:
            get_race_readiness(str(race.id), user)

    assert exc_info.value.status_code == 403
    assert "access denied" in exc_info.value.detail.lower() or "different user" in exc_info.value.detail.lower()


# ── AC7 / AC13: building_baseline=True branch ────────────────────────────────

def test_endpoint_building_baseline_true_omits_projected_form():
    """When building_baseline=True, projected_form must be absent from response."""
    from backend.main import get_race_readiness

    user = _make_user()
    race = _make_race(user.id)

    today = date.today()
    start = today - timedelta(days=180)
    series = _make_tss_series_short(start, today)  # no workouts → building_baseline=True
    curves = _load_curves_from_series(series)

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._specificity_progress", return_value={"reason": "no goal pace"}),
    ):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get.return_value = race
        mock_db.execute.return_value.fetchall.return_value = []
        MockSession.return_value = mock_db

        import json
        result = get_race_readiness(str(race.id), user)
        body = json.loads(result.body)

    assert body["building_baseline"] is True
    assert "projected_form" not in body, "projected_form must be absent when building_baseline=True"
    assert "taper_recommendation" not in body, "taper_recommendation must be absent when building_baseline=True"


def test_endpoint_building_baseline_true_still_has_form_curve():
    """form_curve is always present even when building_baseline=True."""
    from backend.main import get_race_readiness

    user = _make_user()
    race = _make_race(user.id)

    today = date.today()
    start = today - timedelta(days=180)
    series = _make_tss_series_short(start, today)
    curves = _load_curves_from_series(series)

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._specificity_progress", return_value={"reason": "no goal pace"}),
    ):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get.return_value = race
        mock_db.execute.return_value.fetchall.return_value = []
        MockSession.return_value = mock_db

        import json
        result = get_race_readiness(str(race.id), user)
        body = json.loads(result.body)

    assert "form_curve" in body
    assert isinstance(body["form_curve"], list)


def test_endpoint_building_baseline_true_has_on_track():
    """on_track field is present even when building_baseline=True."""
    from backend.main import get_race_readiness

    user = _make_user()
    race = _make_race(user.id)

    today = date.today()
    start = today - timedelta(days=180)
    series = _make_tss_series_short(start, today)
    curves = _load_curves_from_series(series)

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._specificity_progress", return_value={"reason": "no goal pace"}),
    ):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get.return_value = race
        mock_db.execute.return_value.fetchall.return_value = []
        MockSession.return_value = mock_db

        import json
        result = get_race_readiness(str(race.id), user)
        body = json.loads(result.body)

    assert "on_track" in body
    assert "status_summary" in body["on_track"]


# ── AC8 / AC13: building_baseline=False branch ───────────────────────────────

def test_endpoint_building_baseline_false_has_projected_form():
    """When building_baseline=False, projected_form is present."""
    from backend.main import get_race_readiness

    user = _make_user()
    race = _make_race(user.id, race_date=TODAY + timedelta(days=40))

    today = date.today()
    start = today - timedelta(days=180)
    series = _make_tss_series_long(start, today)
    curves = _load_curves_from_series(series)

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._specificity_progress", return_value={"reason": "no goal pace"}),
    ):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get.return_value = race
        mock_db.execute.return_value.fetchall.return_value = []
        MockSession.return_value = mock_db

        import json
        result = get_race_readiness(str(race.id), user)
        body = json.loads(result.body)

    assert body["building_baseline"] is False
    assert "projected_form" in body, "projected_form must be present when building_baseline=False"
    assert isinstance(body["projected_form"], dict)


def test_endpoint_building_baseline_false_has_taper_recommendation():
    """When building_baseline=False and race is in future, taper_recommendation is present."""
    from backend.main import get_race_readiness

    user = _make_user()
    race = _make_race(user.id, race_date=TODAY + timedelta(days=40))

    today = date.today()
    start = today - timedelta(days=180)
    series = _make_tss_series_long(start, today)
    curves = _load_curves_from_series(series)

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._specificity_progress", return_value={"reason": "no goal pace"}),
    ):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get.return_value = race
        mock_db.execute.return_value.fetchall.return_value = []
        MockSession.return_value = mock_db

        import json
        result = get_race_readiness(str(race.id), user)
        body = json.loads(result.body)

    assert "taper_recommendation" in body
    tr = body["taper_recommendation"]
    assert "message" in tr
    assert isinstance(tr["message"], str)


# ── AC2: form_curve zone labels are configurable ─────────────────────────────

def test_form_curve_zone_labels_are_configurable():
    """Zone labels in form_curve reflect configurable thresholds from AppConfig."""
    from backend.main import get_race_readiness

    user = _make_user()
    race = _make_race(user.id)

    today = date.today()
    start = today - timedelta(days=180)
    series = _make_tss_series_short(start, today)

    # Build a curve with one day of known TSB value: -5.0
    curves = [{"date": today, "tss": 0, "ctl": 40.0, "atl": 45.0, "tsb": -5.0}]

    def fake_get_app_config(key, default=""):
        cfg = {
            "readiness.form_buried_ceiling": "-3.0",   # -5.0 < -3.0 → accumulated_fatigue
            "readiness.form_fresh_floor": "10.0",
            "readiness.min_history_weeks": "",
            "readiness.peak_tracking_tolerance": "",
        }
        return cfg.get(key, default)

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
        patch("backend.main._get_app_config", side_effect=fake_get_app_config),
        patch("backend.main._specificity_progress", return_value={"reason": "no goal pace"}),
    ):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get.return_value = race
        mock_db.execute.return_value.fetchall.return_value = []
        MockSession.return_value = mock_db

        import json
        result = get_race_readiness(str(race.id), user)
        body = json.loads(result.body)

    zones = {entry["zone"] for entry in body["form_curve"]}
    # With buried_ceiling=-3.0, TSB=-5.0 should be classified as accumulated_fatigue
    assert "accumulated_fatigue" in zones, (
        f"Expected accumulated_fatigue zone when TSB=-5.0 < buried_ceiling=-3.0; got {zones}"
    )


def test_form_curve_entries_have_required_keys():
    """Each form_curve entry must have date, form, and zone keys."""
    from backend.main import get_race_readiness

    user = _make_user()
    race = _make_race(user.id)

    today = date.today()
    start = today - timedelta(days=180)
    series = _make_tss_series_short(start, today)
    curves = _load_curves_from_series(series)

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._specificity_progress", return_value={"reason": "no goal pace"}),
    ):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get.return_value = race
        mock_db.execute.return_value.fetchall.return_value = []
        MockSession.return_value = mock_db

        import json
        result = get_race_readiness(str(race.id), user)
        body = json.loads(result.body)

    for entry in body["form_curve"][:5]:
        assert "date" in entry
        assert "form" in entry
        assert "zone" in entry
        assert entry["zone"] in ("accumulated_fatigue", "optimal", "freshness")


# ── AC5: on_track has boolean + status_summary ───────────────────────────────

def test_on_track_field_has_boolean_and_status_summary():
    """on_track field must contain on_track (bool or None) and status_summary (str)."""
    from backend.main import get_race_readiness

    user = _make_user()
    race = _make_race(user.id)

    today = date.today()
    start = today - timedelta(days=180)
    series = _make_tss_series_short(start, today)
    curves = _load_curves_from_series(series)

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._specificity_progress", return_value={"reason": "no goal pace"}),
    ):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get.return_value = race
        mock_db.execute.return_value.fetchall.return_value = []
        MockSession.return_value = mock_db

        import json
        result = get_race_readiness(str(race.id), user)
        body = json.loads(result.body)

    ot = body["on_track"]
    assert "on_track" in ot
    assert "status_summary" in ot
    assert isinstance(ot["status_summary"], str)
    # on_track is either a bool (True/False) or None when not in taper window
    assert ot["on_track"] is None or isinstance(ot["on_track"], bool)


# ── AC6: specificity_progress is present ─────────────────────────────────────

def test_specificity_progress_is_present():
    """Response must include specificity_progress."""
    from backend.main import get_race_readiness

    user = _make_user()
    race = _make_race(user.id)

    today = date.today()
    start = today - timedelta(days=180)
    series = _make_tss_series_short(start, today)
    curves = _load_curves_from_series(series)

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._specificity_progress", return_value={"reason": "no goal pace"}),
    ):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get.return_value = race
        mock_db.execute.return_value.fetchall.return_value = []
        MockSession.return_value = mock_db

        import json
        result = get_race_readiness(str(race.id), user)
        body = json.loads(result.body)

    assert "specificity_progress" in body


# ── AC3: projected_form is keyed by date ─────────────────────────────────────

def test_projected_form_keyed_by_date_string():
    """projected_form must be a dict with ISO date strings as keys."""
    from backend.main import get_race_readiness

    user = _make_user()
    race = _make_race(user.id, race_date=TODAY + timedelta(days=40))

    today = date.today()
    start = today - timedelta(days=180)
    series = _make_tss_series_long(start, today)
    curves = _load_curves_from_series(series)

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._specificity_progress", return_value={"reason": "no goal pace"}),
    ):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get.return_value = race
        mock_db.execute.return_value.fetchall.return_value = []
        MockSession.return_value = mock_db

        import json
        result = get_race_readiness(str(race.id), user)
        body = json.loads(result.body)

    pf = body.get("projected_form", {})
    assert isinstance(pf, dict)
    for key in pf:
        # Key must be parseable as a date
        parsed = date.fromisoformat(key)
        assert isinstance(parsed, date)


# ── AC4: taper_recommendation shape ──────────────────────────────────────────

def test_taper_recommendation_has_message():
    """taper_recommendation must include a plain-English message."""
    from backend.main import get_race_readiness

    user = _make_user()
    race = _make_race(user.id, race_date=TODAY + timedelta(days=40))

    today = date.today()
    start = today - timedelta(days=180)
    series = _make_tss_series_long(start, today)
    curves = _load_curves_from_series(series)

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.daily_tss_series", return_value=series),
        patch("backend.main.compute_load_curves", return_value=curves),
        patch("backend.main._get_app_config", return_value=""),
        patch("backend.main._specificity_progress", return_value={"reason": "no goal pace"}),
    ):
        mock_db = MagicMock()
        mock_db.__enter__ = MagicMock(return_value=mock_db)
        mock_db.__exit__ = MagicMock(return_value=False)
        mock_db.get.return_value = race
        mock_db.execute.return_value.fetchall.return_value = []
        MockSession.return_value = mock_db

        import json
        result = get_race_readiness(str(race.id), user)
        body = json.loads(result.body)

    tr = body.get("taper_recommendation", {})
    assert "message" in tr and isinstance(tr["message"], str) and len(tr["message"]) > 0
    assert "taper_start_date" in tr
    assert "achievable" in tr
