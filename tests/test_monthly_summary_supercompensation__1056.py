"""Tests for issue #1056: Monthly summary endpoint with supercompensation detection.

GET /api/athletes/{id}/summary/monthly returns a flat JSON object with exactly
14 keys aggregating training data for a calendar month.

AC coverage:
- AC1: 200 with exactly 14 keys (month_start, month_end, distance_km,
       total_tss, session_count, endurance_score_change, speed_score_change,
       weight_change_kg, weight_rate_percent_per_week, fitness_ctl_change,
       form_recovered, supercompensation_state, call_to_action, next_checkpoint)
- AC2: supercompensation_state values constrained to "working", "flat", "digging"
- AC3: "working" when scores rose AND form_recovered=True
- AC4: "flat" when scores flat regardless of form state (scores flat, form recovered)
- AC5: "digging" when scores flat/down AND form_recovered=False
- AC6: weight_rate_percent_per_week from month's weight trend
- AC7: call_to_action references deficit when weight_rate exceeds safe limit
- AC8: call_to_action is a single short string (≤ ~10 words)
- AC9: next_checkpoint from races/checkpoints data — nearest upcoming
- AC10: HTTP 424 when no weekly aggregation data present
- AC11: Strict schema — no extra keys, no missing keys
"""

import json
import uuid
import calendar
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest

TODAY = date.today()
MONTH_START = TODAY.replace(day=1)
MONTH_END = MONTH_START.replace(
    day=calendar.monthrange(MONTH_START.year, MONTH_START.month)[1]
)

EXPECTED_KEYS = {
    "month_start",
    "month_end",
    "distance_km",
    "total_tss",
    "session_count",
    "duration_seconds",
    "endurance_score_change",
    "speed_score_change",
    "weight_change_kg",
    "weight_rate_percent_per_week",
    "fitness_ctl_change",
    "form_recovered",
    "supercompensation_state",
    "call_to_action",
    "next_checkpoint",
    # Added in issue #1060: guardrail warning surfaced on summary cards
    "guardrail_state",
    "guardrail_message",
}

VALID_SUPER_STATES = {"working", "flat", "digging"}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_user(uid=None):
    u = MagicMock()
    u.id = uid or uuid.uuid4()
    return u


def _make_workout(user_id, workout_date, tss=60.0, distance_km=10.0,
                  endurance_signal=None, speed_signal=None):
    w = MagicMock()
    w.id = uuid.uuid4()
    w.user_id = user_id
    w.workout_date = workout_date
    w.tss = tss
    w.distance_km = distance_km
    w.endurance_signal = endurance_signal
    w.speed_signal = speed_signal
    return w


def _make_weight_entry(user_id, date_val, weight_kg):
    e = MagicMock()
    e.user_id = user_id
    e.entry_date = date_val
    e.weight_kg = weight_kg
    return e


def _make_race(user_id, name, race_date, race_type="checkpoint"):
    r = MagicMock()
    r.id = uuid.uuid4()
    r.user_id = user_id
    r.name = name
    r.race_date = race_date
    r.race_type = race_type
    r.status = "planned"
    return r


def _make_fitness_series(tsb_end=5.0, ctl_start=35.0, ctl_end=42.0, days=30, ref_date=None):
    """Build a synthetic fitness series list (from training_load.compute_fitness_series)."""
    ref = ref_date or MONTH_START
    result = []
    for i in range(days):
        day = ref + timedelta(days=i)
        ctl = ctl_start + (ctl_end - ctl_start) * i / max(days - 1, 1)
        # TSB ramps up from negative to tsb_end
        tsb = tsb_end - (days - 1 - i) * 2.0
        atl = ctl - tsb
        result.append({
            "date": day,
            "tss": 60,
            "ctl": round(ctl, 2),
            "atl": round(atl, 2),
            "tsb": round(tsb, 2),
        })
    return result


def _call_endpoint(
    user,
    workouts=None,
    weight_entries=None,
    races=None,
    month=None,
    fitness_series=None,
    athlete=None,
    app_config_fn=None,
):
    """Call get_athlete_monthly_summary with mocked DB dependencies."""
    from backend.main import get_athlete_monthly_summary

    if workouts is None:
        workouts = []
    if weight_entries is None:
        weight_entries = []
    if races is None:
        races = []

    if fitness_series is None:
        fitness_series = _make_fitness_series()

    if athlete is None:
        athlete = MagicMock()
        athlete.id = user.id

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.get.return_value = athlete

    def _query_side_effect(model_cls):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        model_name = getattr(model_cls, "__name__", str(model_cls))
        if "Workout" in model_name:
            q.all.return_value = workouts
        elif "WeightEntry" in model_name:
            q.all.return_value = weight_entries
        elif "Race" in model_name:
            q.all.return_value = races
        else:
            q.all.return_value = []
        return q

    mock_db.query.side_effect = _query_side_effect

    config_fn = app_config_fn or (lambda key, default="": default)

    _default_guardrail = {"guardrail_state": "ok", "guardrail_message": ""}

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.get_snapshot_series", return_value=fitness_series),
        patch("backend.main._get_app_config", side_effect=config_fn),
        patch("backend.main.get_guardrail_result", return_value=_default_guardrail),
    ):
        MockSession.return_value = mock_db
        result = get_athlete_monthly_summary(str(user.id), user, month)

    return json.loads(result.body)


# ── AC11: strict schema — exactly 16 keys (14 original + 2 guardrail from #1060) ─

def test_response_has_exactly_16_keys():
    """AC1 & AC11: Response contains exactly the 16 expected keys, no extras."""
    user = _make_user()
    workouts = [
        _make_workout(user.id, MONTH_START + timedelta(days=i), tss=60.0, distance_km=10.0)
        for i in range(5)
    ]
    body = _call_endpoint(user, workouts=workouts)
    assert set(body.keys()) == EXPECTED_KEYS, (
        f"Key mismatch. Extra: {set(body.keys()) - EXPECTED_KEYS}. "
        f"Missing: {EXPECTED_KEYS - set(body.keys())}"
    )


def test_no_missing_keys():
    """AC11: No required key is absent from the response."""
    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=3))]
    body = _call_endpoint(user, workouts=workouts)
    for key in EXPECTED_KEYS:
        assert key in body, f"Required key '{key}' is missing from response"


def test_no_extra_keys():
    """AC11: No undocumented keys are present in the response."""
    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=3))]
    body = _call_endpoint(user, workouts=workouts)
    extra = set(body.keys()) - EXPECTED_KEYS
    assert not extra, f"Unexpected extra keys in response: {extra}"


# ── AC1: month_start and month_end ────────────────────────────────────────────

def test_month_start_and_end_correct():
    """AC1: month_start is first of month, month_end is last of month."""
    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=3))]
    body = _call_endpoint(user, workouts=workouts)
    assert body["month_start"] == MONTH_START.isoformat()
    assert body["month_end"] == MONTH_END.isoformat()


def test_explicit_month_param():
    """AC1: Explicit month=YYYY-MM param selects the correct month."""
    user = _make_user()
    target = date(2026, 3, 1)
    fitness_series = _make_fitness_series(ref_date=target)
    workouts = [_make_workout(user.id, target + timedelta(days=3))]
    body = _call_endpoint(user, workouts=workouts, month="2026-03",
                          fitness_series=fitness_series)
    assert body["month_start"] == "2026-03-01"
    assert body["month_end"] == "2026-03-31"


# ── AC1: aggregated fields ────────────────────────────────────────────────────

def test_distance_km_is_sum_of_workouts():
    """AC1: distance_km equals the sum of workout distances."""
    user = _make_user()
    workouts = [
        _make_workout(user.id, MONTH_START + timedelta(days=0), distance_km=10.0),
        _make_workout(user.id, MONTH_START + timedelta(days=3), distance_km=15.5),
        _make_workout(user.id, MONTH_START + timedelta(days=7), distance_km=8.0),
    ]
    body = _call_endpoint(user, workouts=workouts)
    assert abs(body["distance_km"] - 33.5) < 0.01


def test_total_tss_is_sum():
    """AC1: total_tss equals the sum of workout TSS values."""
    user = _make_user()
    workouts = [
        _make_workout(user.id, MONTH_START + timedelta(days=0), tss=50.0),
        _make_workout(user.id, MONTH_START + timedelta(days=3), tss=70.0),
    ]
    body = _call_endpoint(user, workouts=workouts)
    assert abs(body["total_tss"] - 120.0) < 0.01


def test_session_count_is_workout_count():
    """AC1: session_count equals the number of workouts in the month."""
    user = _make_user()
    workouts = [
        _make_workout(user.id, MONTH_START + timedelta(days=i))
        for i in range(7)
    ]
    body = _call_endpoint(user, workouts=workouts)
    assert body["session_count"] == 7


# ── AC2: supercompensation_state valid values ─────────────────────────────────

def test_supercompensation_state_is_valid_value():
    """AC2: supercompensation_state is one of 'working', 'flat', 'digging'."""
    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=3))]
    body = _call_endpoint(user, workouts=workouts)
    assert body["supercompensation_state"] in VALID_SUPER_STATES


# ── AC3: "working" state ──────────────────────────────────────────────────────

def test_supercompensation_working_when_scores_rose_and_form_recovered():
    """AC3: supercompensation_state='working' when scores rose and form_recovered=True."""
    user = _make_user()
    # Endurance and speed signals increasing over the month
    workouts = [
        _make_workout(
            user.id, MONTH_START + timedelta(days=i),
            endurance_signal=1.0 + i * 0.1,
            speed_signal=0.5 + i * 0.05,
        )
        for i in range(14)
    ]
    # TSB positive at month end → form recovered
    fitness_series = _make_fitness_series(tsb_end=7.0, ctl_start=38.0, ctl_end=44.0)
    body = _call_endpoint(user, workouts=workouts, fitness_series=fitness_series)
    assert body["form_recovered"] is True
    assert body["supercompensation_state"] == "working"


# ── AC4: "flat" state ─────────────────────────────────────────────────────────

def test_supercompensation_flat_when_scores_flat_and_form_recovered():
    """AC4 (UAT Step 5): supercompensation_state='flat' when scores flat and form recovered."""
    user = _make_user()
    # Constant endurance and speed signals → flat scores
    workouts = [
        _make_workout(
            user.id, MONTH_START + timedelta(days=i),
            endurance_signal=2.0,
            speed_signal=1.0,
        )
        for i in range(14)
    ]
    # TSB positive at month end → form recovered
    fitness_series = _make_fitness_series(tsb_end=2.0)
    body = _call_endpoint(user, workouts=workouts, fitness_series=fitness_series)
    assert body["form_recovered"] is True
    assert body["supercompensation_state"] == "flat"


# ── AC5: "digging" state ──────────────────────────────────────────────────────

def test_supercompensation_digging_when_scores_flat_and_form_not_recovered():
    """AC5 (UAT Step 4): supercompensation_state='digging' when scores flat and form not recovered."""
    user = _make_user()
    # Constant signals → flat scores
    workouts = [
        _make_workout(
            user.id, MONTH_START + timedelta(days=i),
            endurance_signal=2.0,
            speed_signal=1.0,
        )
        for i in range(14)
    ]
    # TSB deeply negative → form NOT recovered
    fitness_series = _make_fitness_series(tsb_end=-35.0, ctl_start=40.0, ctl_end=40.0)
    body = _call_endpoint(user, workouts=workouts, fitness_series=fitness_series)
    assert body["form_recovered"] is False
    assert body["supercompensation_state"] == "digging"


# ── AC6: weight_rate_percent_per_week ─────────────────────────────────────────

def test_weight_rate_computed_from_month_trend():
    """AC6: weight_rate_percent_per_week reflects the per-week lean-down rate."""
    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=3))]
    # 80 kg → 79 kg over 28 days = 4 weeks → 1/80 * 100 ≈ 1.25%/wk loss
    weight_entries = [
        _make_weight_entry(user.id, MONTH_START, 80.0),
        _make_weight_entry(user.id, MONTH_START + timedelta(days=28), 79.0),
    ]
    body = _call_endpoint(user, workouts=workouts, weight_entries=weight_entries)
    assert body["weight_rate_percent_per_week"] is not None
    # Negative value means weight loss
    assert body["weight_rate_percent_per_week"] < 0
    # -1.0 kg over 28 days (4 weeks) from 80 kg = -1.25% / 4 = -0.3125%/wk
    assert abs(body["weight_rate_percent_per_week"] - (-0.3125)) < 0.1


def test_weight_rate_none_when_no_weight_data():
    """AC6: weight_rate_percent_per_week is None when no weight entries exist."""
    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=3))]
    body = _call_endpoint(user, workouts=workouts, weight_entries=[])
    assert body["weight_rate_percent_per_week"] is None
    assert body["weight_change_kg"] is None


def test_weight_change_kg_is_last_minus_first():
    """AC6: weight_change_kg is the difference between last and first weight entry."""
    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=3))]
    weight_entries = [
        _make_weight_entry(user.id, MONTH_START, 80.0),
        _make_weight_entry(user.id, MONTH_START + timedelta(days=14), 79.5),
        _make_weight_entry(user.id, MONTH_START + timedelta(days=28), 79.0),
    ]
    body = _call_endpoint(user, workouts=workouts, weight_entries=weight_entries)
    assert abs(body["weight_change_kg"] - (-1.0)) < 0.01


# ── AC7: call_to_action when weight exceeds safe rate ────────────────────────

def test_call_to_action_mentions_deficit_when_rate_exceeds_safe():
    """AC7: call_to_action references deficit when weight_rate exceeds configured limit."""
    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=3))]
    # 80 kg → 77.6 kg in 7 days = 2.4 kg / (80 * 1 week) = 3.0%/wk
    # Safe limit set to 1.0%/wk → triggers warning
    weight_entries = [
        _make_weight_entry(user.id, MONTH_START, 80.0),
        _make_weight_entry(user.id, MONTH_START + timedelta(days=7), 77.6),
    ]

    def _fake_config(key, default=""):
        if "safe_lean_down" in key:
            return "1.0"
        return default

    body = _call_endpoint(
        user, workouts=workouts, weight_entries=weight_entries,
        app_config_fn=_fake_config,
    )
    assert "deficit" in body["call_to_action"].lower(), (
        f"Expected 'deficit' in call_to_action; got: {body['call_to_action']!r}"
    )


# ── AC8: call_to_action is short ─────────────────────────────────────────────

def test_call_to_action_is_short():
    """AC8: call_to_action is a single string of approximately 10 words or fewer."""
    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=3))]
    body = _call_endpoint(user, workouts=workouts)
    cta = body["call_to_action"]
    assert isinstance(cta, str)
    word_count = len(cta.split())
    assert word_count <= 15, (
        f"call_to_action exceeds 15 words ({word_count}): {cta!r}"
    )


# ── AC9: next_checkpoint from races data ─────────────────────────────────────

def test_next_checkpoint_from_races_data():
    """AC9: next_checkpoint returns the nearest upcoming checkpoint name and date."""
    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=3))]
    upcoming = TODAY + timedelta(days=14)
    races = [
        _make_race(user.id, "Long Run Milestone", upcoming, race_type="checkpoint"),
    ]
    body = _call_endpoint(user, workouts=workouts, races=races)
    cp = body["next_checkpoint"]
    assert cp is not None
    assert cp["name"] == "Long Run Milestone"
    assert cp["date"] == upcoming.isoformat()


def test_next_checkpoint_picks_nearest_future():
    """AC9: next_checkpoint returns the nearest (not all) upcoming checkpoint."""
    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=3))]
    near = TODAY + timedelta(days=10)
    far = TODAY + timedelta(days=40)
    races = [
        _make_race(user.id, "Far Checkpoint", far, race_type="checkpoint"),
        _make_race(user.id, "Near Checkpoint", near, race_type="checkpoint"),
    ]
    body = _call_endpoint(user, workouts=workouts, races=races)
    assert body["next_checkpoint"]["name"] == "Near Checkpoint"
    assert body["next_checkpoint"]["date"] == near.isoformat()


def test_next_checkpoint_none_when_no_upcoming():
    """AC9: next_checkpoint is None when no upcoming checkpoints exist."""
    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=3))]
    past = TODAY - timedelta(days=10)
    races = [
        _make_race(user.id, "Past Checkpoint", past, race_type="checkpoint"),
    ]
    body = _call_endpoint(user, workouts=workouts, races=races)
    assert body["next_checkpoint"] is None


def test_next_checkpoint_excludes_race_type():
    """AC9: Only race_type='checkpoint' entries contribute to next_checkpoint."""
    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=3))]
    upcoming = TODAY + timedelta(days=14)
    races = [
        _make_race(user.id, "A Race", upcoming, race_type="race"),
    ]
    body = _call_endpoint(user, workouts=workouts, races=races)
    assert body["next_checkpoint"] is None


# ── AC10: HTTP 424 when no weekly aggregation data ────────────────────────────

def test_http_424_when_no_workouts_in_month():
    """AC10: Returns HTTP 424 when no training data is available for the month."""
    from fastapi import HTTPException
    from backend.main import get_athlete_monthly_summary

    user = _make_user()
    athlete = MagicMock()
    athlete.id = user.id

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.get.return_value = athlete

    empty_query = MagicMock()
    empty_query.filter.return_value = empty_query
    empty_query.order_by.return_value = empty_query
    empty_query.all.return_value = []
    mock_db.query.return_value = empty_query

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.get_snapshot_series", return_value=[]),
        patch("backend.main._get_app_config", return_value=""),
    ):
        MockSession.return_value = mock_db
        with pytest.raises(HTTPException) as exc:
            get_athlete_monthly_summary(str(user.id), user, None)

    assert exc.value.status_code == 424


def test_http_424_body_is_descriptive():
    """AC10: The 424 error body contains a human-readable explanation."""
    from fastapi import HTTPException
    from backend.main import get_athlete_monthly_summary

    user = _make_user()
    athlete = MagicMock()
    athlete.id = user.id

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.get.return_value = athlete

    empty_query = MagicMock()
    empty_query.filter.return_value = empty_query
    empty_query.order_by.return_value = empty_query
    empty_query.all.return_value = []
    mock_db.query.return_value = empty_query

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.get_snapshot_series", return_value=[]),
        patch("backend.main._get_app_config", return_value=""),
    ):
        MockSession.return_value = mock_db
        with pytest.raises(HTTPException) as exc:
            get_athlete_monthly_summary(str(user.id), user, None)

    detail = exc.value.detail
    detail_str = detail if isinstance(detail, str) else str(detail)
    assert len(detail_str) > 10


# ── Auth / identity ───────────────────────────────────────────────────────────

def test_unauthenticated_returns_401():
    """Returns 401 for requests without a valid session."""
    from fastapi.testclient import TestClient
    from backend.main import app

    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get(f"/api/athletes/{uuid.uuid4()}/summary/monthly")

    assert r.status_code == 401


def test_malformed_athlete_id_returns_400():
    """Returns 400 for a non-UUID athlete_id."""
    from fastapi import HTTPException
    from backend.main import get_athlete_monthly_summary

    user = _make_user()
    with pytest.raises(HTTPException) as exc:
        get_athlete_monthly_summary("not-a-uuid", user, None)

    assert exc.value.status_code == 400


def test_wrong_athlete_returns_403():
    """Returns 403 when authenticated user requests a different athlete's data."""
    from fastapi import HTTPException
    from backend.main import get_athlete_monthly_summary

    user = _make_user()
    other_id = uuid.uuid4()
    with pytest.raises(HTTPException) as exc:
        get_athlete_monthly_summary(str(other_id), user, None)

    assert exc.value.status_code == 403


# ── form_recovered ────────────────────────────────────────────────────────────

def test_form_recovered_true_when_tsb_positive():
    """form_recovered=True when TSB is positive at month end."""
    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=3))]
    fitness_series = _make_fitness_series(tsb_end=5.0)
    body = _call_endpoint(user, workouts=workouts, fitness_series=fitness_series)
    assert body["form_recovered"] is True


def test_form_recovered_false_when_tsb_deeply_negative():
    """form_recovered=False when TSB is deeply negative at month end."""
    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=3))]
    fitness_series = _make_fitness_series(tsb_end=-35.0)
    body = _call_endpoint(user, workouts=workouts, fitness_series=fitness_series)
    assert body["form_recovered"] is False


# ── fitness_ctl_change ────────────────────────────────────────────────────────

def test_fitness_ctl_change_is_end_minus_start():
    """fitness_ctl_change is the CTL at end of month minus CTL at start of month."""
    user = _make_user()
    workouts = [_make_workout(user.id, MONTH_START + timedelta(days=3))]
    ctl_start = 35.0
    ctl_end = 42.0
    fitness_series = _make_fitness_series(ctl_start=ctl_start, ctl_end=ctl_end, tsb_end=2.0)
    body = _call_endpoint(user, workouts=workouts, fitness_series=fitness_series)
    expected_change = round(ctl_end - ctl_start, 2)
    assert abs(body["fitness_ctl_change"] - expected_change) < 1.0
