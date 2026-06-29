"""Tests for issue #1060: Surface guardrail warning in summary cards.

AC items tested:
  AC1 - When guardrail_state is warn, both weekly and monthly summary endpoints
        include guardrail_state and guardrail_message fields in the response.
  AC2 - Warning text is sourced from guardrail_message (backend field); never
        hardcoded in the frontend.
  AC3 - Warning line is styled as caution (amber/yellow), not destructive (red).
  AC4 - When guardrail_state is ok, no warning line is rendered.
  AC5 - Warning appears consistently in both weekly and monthly card renders.
  AC6 - If guardrail_message is empty/absent while guardrail_state is warn,
        a safe fallback message is shown.
"""

import json
import os
import re
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

import pytest


# ── Fixtures ────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def training_log_js():
    js_path = os.path.join(os.path.dirname(__file__), "../frontend/js/training-log.js")
    with open(js_path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def training_log_html():
    html_path = os.path.join(os.path.dirname(__file__), "../frontend/pages/training-log.html")
    with open(html_path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def inline_styles(training_log_html):
    blocks = re.findall(r'<style[^>]*>(.*?)</style>', training_log_html, re.DOTALL)
    return "\n".join(blocks)


# ── Helpers for unit tests ───────────────────────────────────────────────────────

def _make_user(uid=None):
    u = MagicMock()
    u.id = uid or uuid.uuid4()
    return u


def _make_workout(user_id, workout_date, tss=60.0, distance_km=10.0):
    w = MagicMock()
    w.id = uuid.uuid4()
    w.user_id = user_id
    w.workout_date = workout_date
    w.tss = tss
    w.distance_km = distance_km
    w.endurance_signal = None
    w.speed_signal = None
    return w


def _make_fitness_series(tsb_end=5.0, ctl_start=35.0, ctl_end=42.0, days=30, ref_date=None):
    today = date.today()
    ref = ref_date or today.replace(day=1)
    result = []
    for i in range(days):
        day = ref + timedelta(days=i)
        ctl = ctl_start + (ctl_end - ctl_start) * i / max(days - 1, 1)
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


_WARN_GUARDRAIL = {
    "guardrail_state": "warn",
    "guardrail_message": "Multiple stressors are ramping simultaneously — ease off.",
    "acwr": 1.6,
    "acwr_state": "high_risk",
    "stressors_ramping": 2,
}

_OK_GUARDRAIL = {
    "guardrail_state": "ok",
    "guardrail_message": "",
    "acwr": 1.1,
    "acwr_state": "productive",
    "stressors_ramping": 0,
}

_WARN_EMPTY_MSG_GUARDRAIL = {
    "guardrail_state": "warn",
    "guardrail_message": "",
    "acwr": 1.6,
    "acwr_state": "high_risk",
    "stressors_ramping": 2,
}


def _call_weekly_endpoint(user, guardrail_result=None):
    """Call get_athlete_weekly_summary with mocked dependencies."""
    from backend.main import get_athlete_weekly_summary

    if guardrail_result is None:
        guardrail_result = _WARN_GUARDRAIL

    uid = user.id
    today = date.today()
    ws = today - timedelta(days=today.weekday())

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.get.return_value = MagicMock(id=uid)

    def _query_side_effect(model_cls):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        q.first.return_value = None
        model_name = getattr(model_cls, "__name__", str(model_cls))
        if "Workout" in model_name:
            q.all.return_value = []
        elif "WeightEntry" in model_name:
            q.all.return_value = []
        else:
            q.all.return_value = []
        return q

    mock_db.query.side_effect = _query_side_effect

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.compute_fitness_series", return_value=[]),
        patch("backend.main.get_guardrail_result", return_value=guardrail_result),
    ):
        MockSession.return_value = mock_db
        result = get_athlete_weekly_summary(user)

    return json.loads(result.body)


def _call_monthly_endpoint(user, workouts, guardrail_result=None):
    """Call get_athlete_monthly_summary with mocked dependencies."""
    from backend.main import get_athlete_monthly_summary

    if guardrail_result is None:
        guardrail_result = _WARN_GUARDRAIL

    today = date.today()
    month_start = today.replace(day=1)

    fitness_series = _make_fitness_series()

    mock_db = MagicMock()
    mock_db.__enter__ = MagicMock(return_value=mock_db)
    mock_db.__exit__ = MagicMock(return_value=False)
    mock_db.get.return_value = MagicMock(id=user.id)

    def _query_side_effect(model_cls):
        q = MagicMock()
        q.filter.return_value = q
        q.order_by.return_value = q
        model_name = getattr(model_cls, "__name__", str(model_cls))
        if "Workout" in model_name:
            q.all.return_value = workouts
        elif "WeightEntry" in model_name:
            q.all.return_value = []
        elif "Race" in model_name:
            q.all.return_value = []
        else:
            q.all.return_value = []
        return q

    mock_db.query.side_effect = _query_side_effect

    with (
        patch("backend.main.Session") as MockSession,
        patch("backend.main.compute_fitness_series", return_value=fitness_series),
        patch("backend.main._get_app_config", side_effect=lambda key, default="": default),
        patch("backend.main.get_guardrail_result", return_value=guardrail_result),
    ):
        MockSession.return_value = mock_db
        result = get_athlete_monthly_summary(str(user.id), user, None)

    return json.loads(result.body)


# ── AC1: Backend weekly summary includes guardrail fields ────────────────────────

def test_weekly_summary_includes_guardrail_state_when_warn():
    """AC1: weekly endpoint returns guardrail_state when guardrail is warn."""
    user = _make_user()
    body = _call_weekly_endpoint(user, guardrail_result=_WARN_GUARDRAIL)
    assert "guardrail_state" in body, "guardrail_state must be in weekly summary response"
    assert body["guardrail_state"] == "warn"


def test_weekly_summary_includes_guardrail_message_when_warn():
    """AC1: weekly endpoint returns guardrail_message when guardrail is warn."""
    user = _make_user()
    body = _call_weekly_endpoint(user, guardrail_result=_WARN_GUARDRAIL)
    assert "guardrail_message" in body, "guardrail_message must be in weekly summary response"
    assert body["guardrail_message"] == _WARN_GUARDRAIL["guardrail_message"]


def test_weekly_summary_includes_guardrail_state_when_ok():
    """AC4: weekly endpoint returns guardrail_state=ok when guardrail is ok."""
    user = _make_user()
    body = _call_weekly_endpoint(user, guardrail_result=_OK_GUARDRAIL)
    assert "guardrail_state" in body
    assert body["guardrail_state"] == "ok"
    assert body["guardrail_message"] == ""


# ── AC1: Backend monthly summary includes guardrail fields ───────────────────────

def test_monthly_summary_includes_guardrail_state_when_warn():
    """AC1: monthly endpoint returns guardrail_state when guardrail is warn."""
    user = _make_user()
    today = date.today()
    month_start = today.replace(day=1)
    workouts = [_make_workout(user.id, month_start + timedelta(days=i)) for i in range(3)]
    body = _call_monthly_endpoint(user, workouts, guardrail_result=_WARN_GUARDRAIL)
    assert "guardrail_state" in body, "guardrail_state must be in monthly summary response"
    assert body["guardrail_state"] == "warn"


def test_monthly_summary_includes_guardrail_message_when_warn():
    """AC1: monthly endpoint returns guardrail_message when guardrail is warn."""
    user = _make_user()
    today = date.today()
    month_start = today.replace(day=1)
    workouts = [_make_workout(user.id, month_start + timedelta(days=i)) for i in range(3)]
    body = _call_monthly_endpoint(user, workouts, guardrail_result=_WARN_GUARDRAIL)
    assert "guardrail_message" in body, "guardrail_message must be in monthly summary response"
    assert body["guardrail_message"] == _WARN_GUARDRAIL["guardrail_message"]


def test_monthly_summary_includes_guardrail_state_when_ok():
    """AC4: monthly endpoint returns guardrail_state=ok when guardrail is ok."""
    user = _make_user()
    today = date.today()
    month_start = today.replace(day=1)
    workouts = [_make_workout(user.id, month_start + timedelta(days=i)) for i in range(3)]
    body = _call_monthly_endpoint(user, workouts, guardrail_result=_OK_GUARDRAIL)
    assert "guardrail_state" in body
    assert body["guardrail_state"] == "ok"
    assert body["guardrail_message"] == ""


# ── AC2: Warning text sourced from guardrail_message (not hardcoded) ────────────

def test_js_renders_guardrail_message_from_data_field(training_log_js):
    """AC2: JS reads guardrail_message from data object, not a hardcoded string."""
    assert "guardrail_message" in training_log_js, (
        "JS must reference data.guardrail_message to source the warning text"
    )


def test_js_does_not_hardcode_guardrail_warning_text(training_log_js):
    """AC2: JS does not contain any hardcoded guardrail warning text."""
    hardcoded_patterns = [
        "Multiple stressors",
        "acute:chronic workload ratio",
        "high-risk zone",
        "training stressors are increasing",
    ]
    for phrase in hardcoded_patterns:
        assert phrase not in training_log_js, (
            f"JS must not hardcode guardrail warning text: found '{phrase}'"
        )


# ── AC3: Warning styled as caution (amber/yellow), not error (red) ───────────────

def test_css_defines_guardrail_warn_class(inline_styles):
    """AC3: CSS defines a caution-styled class for the guardrail warning."""
    has_warn_class = (
        "sd-guardrail" in inline_styles or
        "guardrail-warn" in inline_styles or
        "sd-warn" in inline_styles
    )
    assert has_warn_class, (
        "CSS must define a guardrail warning class (e.g. .sd-guardrail-warn)"
    )


def test_css_guardrail_warn_uses_amber_not_red(inline_styles):
    """AC3: Guardrail warning CSS uses amber/yellow tone, not red."""
    # Extract the full .sd-guardrail-warn block (multi-line)
    guardrail_block_match = re.search(
        r'\.sd-guardrail-warn\s*\{[^}]+\}',
        inline_styles,
        re.DOTALL
    )
    assert guardrail_block_match, (
        "CSS must define a .sd-guardrail-warn class with caution styling"
    )
    block_text = guardrail_block_match.group(0)

    # The block should reference amber/yellow colors (not pure red)
    # Amber CSS variable names, hex amber/yellow codes, or literal keywords
    has_amber_or_yellow = bool(re.search(
        r'amber|yellow|gold|'
        r'#[fF][fF][fF0][0-9a-fA-F]{2}|'   # #fff0c4-style
        r'#[fF][bB][bB][fF]|'
        r'#[fF][5-9a-fA-F][0-9a-fA-F]{4}',
        block_text
    ))
    # Verify no pure red color value appears as a background or color
    has_pure_red = bool(re.search(
        r'(?:background|color)\s*:\s*(?:red\b|#[fF]{2}0{4}|#[eE][0-9a-fA-F]{4}[0-9a-fA-F])',
        block_text
    ))
    assert has_amber_or_yellow, (
        "Guardrail warning CSS must use an amber/yellow color (not red). "
        f"Block found:\n{block_text}"
    )
    assert not has_pure_red, (
        "Guardrail warning CSS must not use a pure red color — use amber/yellow caution styling."
    )


# ── AC4: No warning rendered when guardrail_state is ok ─────────────────────────

def test_js_conditionally_renders_warning_only_when_warn(training_log_js):
    """AC4: JS checks guardrail_state before rendering the warning line."""
    has_state_check = bool(re.search(
        r'guardrail_state\s*[=!]=+\s*[\'"]warn[\'"]|'
        r'[\'"]warn[\'"]\s*[=!]=+\s*guardrail_state',
        training_log_js
    ))
    assert has_state_check, (
        "JS must check data.guardrail_state === 'warn' before rendering the warning line"
    )


def test_js_does_not_render_warning_block_when_ok(training_log_js):
    """AC4: JS renders empty string or nothing when guardrail_state is not warn."""
    # The rendering logic must be conditional — look for a pattern like:
    # guardrail_state === 'warn' ? <warning html> : ''
    # or if (guardrail_state === 'warn') { ... }
    has_conditional = bool(re.search(
        r'guardrail_state.*[?:]|'
        r'if\s*\([^)]*guardrail_state',
        training_log_js
    ))
    assert has_conditional, (
        "JS must conditionally render (or suppress) the guardrail warning block "
        "based on guardrail_state"
    )


# ── AC5: Warning appears in both weekly and monthly card renders ─────────────────

def test_weekly_render_function_references_guardrail(training_log_js):
    """AC5: The weekly render function (_renderWeek) references guardrail fields."""
    week_match = re.search(
        r'function\s+_renderWeek\s*\([^)]*\)\s*\{(.*?)(?=\n\s*(?:function|//\s*──))',
        training_log_js,
        re.DOTALL
    )
    assert week_match, "_renderWeek function not found in training-log.js"
    week_body = week_match.group(1)
    # Case-insensitive: function may call _renderGuardrailWarn (capital G)
    assert "guardrail" in week_body.lower(), (
        "_renderWeek must reference guardrail fields (e.g. call _renderGuardrailWarn) "
        "to show the warning in the weekly card"
    )


def test_monthly_render_function_references_guardrail(training_log_js):
    """AC5: The monthly render function (_renderMonth) references guardrail fields."""
    month_match = re.search(
        r'function\s+_renderMonth\s*\([^)]*\)\s*\{(.*?)(?=\n\s*(?:function|//\s*──))',
        training_log_js,
        re.DOTALL
    )
    assert month_match, "_renderMonth function not found in training-log.js"
    month_body = month_match.group(1)
    assert "guardrail" in month_body.lower(), (
        "_renderMonth must reference guardrail fields (e.g. call _renderGuardrailWarn) "
        "to show the warning in the monthly card"
    )


# ── AC6: Fallback message when guardrail_message is empty ───────────────────────

def test_js_has_fallback_when_guardrail_message_empty(training_log_js):
    """AC6: JS provides a fallback message when guardrail_message is empty/absent."""
    # Look for a pattern that handles empty/null guardrail_message
    has_fallback = bool(re.search(
        r'guardrail_message\s*\|\|[^;|]+|'
        r'guardrail_message\s*\?\s*[^:]+:[^;]+|'
        r'if\s*\([^)]*guardrail_message',
        training_log_js
    ))
    assert has_fallback, (
        "JS must provide a fallback message when guardrail_message is empty or absent "
        "(AC6: no blank warning block should appear)"
    )


def test_weekly_summary_guardrail_message_is_empty_when_ok():
    """AC6 boundary: guardrail_message is empty string when guardrail_state is ok."""
    user = _make_user()
    body = _call_weekly_endpoint(user, guardrail_result=_OK_GUARDRAIL)
    assert body.get("guardrail_message") == "", (
        "guardrail_message must be empty string when guardrail_state is ok"
    )


def test_monthly_summary_guardrail_message_is_empty_when_ok():
    """AC6 boundary: guardrail_message is empty string when guardrail_state is ok."""
    user = _make_user()
    today = date.today()
    month_start = today.replace(day=1)
    workouts = [_make_workout(user.id, month_start + timedelta(days=i)) for i in range(3)]
    body = _call_monthly_endpoint(user, workouts, guardrail_result=_OK_GUARDRAIL)
    assert body.get("guardrail_message") == "", (
        "guardrail_message must be empty string when guardrail_state is ok"
    )


# ── AC5 + AC6: Both cards get warning in warn state ─────────────────────────────

def test_weekly_and_monthly_both_get_guardrail_fields_in_warn():
    """AC5: Both weekly and monthly endpoints include guardrail fields when warn."""
    user = _make_user()
    today = date.today()
    month_start = today.replace(day=1)
    workouts = [_make_workout(user.id, month_start + timedelta(days=i)) for i in range(3)]

    weekly_body = _call_weekly_endpoint(user, guardrail_result=_WARN_GUARDRAIL)
    monthly_body = _call_monthly_endpoint(user, workouts, guardrail_result=_WARN_GUARDRAIL)

    for label, body in [("weekly", weekly_body), ("monthly", monthly_body)]:
        assert "guardrail_state" in body, f"{label} must include guardrail_state"
        assert "guardrail_message" in body, f"{label} must include guardrail_message"
        assert body["guardrail_state"] == "warn", f"{label} guardrail_state must be warn"
        assert body["guardrail_message"] != "", f"{label} guardrail_message must not be empty when warn"
