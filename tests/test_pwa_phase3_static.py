"""PWA phase 3 static contracts (gym mode + template overrides)."""
from __future__ import annotations

import inspect
import json
import subprocess
from pathlib import Path

from backend.services.session_template_overrides import apply_overrides
from backend.services.strength_tss import from_effort_time, from_exercises

REPO = Path(__file__).resolve().parents[1]
FIXTURES = json.loads((REPO / "tests" / "fixtures" / "strength_tss_sessions.json").read_text(encoding="utf-8"))


def test_js_python_tss_share_fixtures():
    for fix in FIXTURES:
        if "expect_exercises_tss" in fix:
            got = from_exercises(fix["exercises"])
            assert got["tss"] == fix["expect_exercises_tss"], fix["name"]
        if fix.get("expect_effort_tss") is not None:
            got = from_effort_time(duration_min=fix["duration_min"], effort=fix["effort"])
            assert got["tss"] == fix["expect_effort_tss"], fix["name"]


def test_overrides_swap_and_kg():
    exercises = [{"name": "Bulgarian split squat", "sets": [{"kg": 10, "reps": 8}]}]
    ovs = [{
        "exercise_key": "bulgarian split squat",
        "type": "swap",
        "replacement": "Step-up",
        "kg": 12,
    }]
    out = apply_overrides(exercises, ovs)
    assert out[0]["name"] == "Step-up"
    assert out[0]["sets"][0]["kg"] == 12


def test_overrides_swap_and_plus_two_kg():
    exercises = [{"name": "Bulgarian split squat", "sets": [{"kg": 10, "reps": 8}]}]
    ovs = [{
        "exercise_key": "bulgarian split squat",
        "type": "swap",
        "replacement": "Step-up",
        "kg_delta": 2,
    }]
    out = apply_overrides(exercises, ovs)
    assert out[0]["name"] == "Step-up"
    assert out[0]["sets"][0]["kg"] == 12


def test_no_overrides_leaves_template():
    exercises = [{"name": "Press", "sets": [{"kg": 40, "reps": 8}]}]
    assert apply_overrides(exercises, [])[0]["name"] == "Press"


def test_apply_to_future_gated():
    from backend.services.mobile_sync import _apply_session_log

    src = inspect.getsource(_apply_session_log)
    assert 'if payload.get("apply_to_future")' in src
    assert "upsert_from_edit_log" in src


def test_timer_and_tss_harnesses():
    for name in ("test_m_timer.mjs", "test_m_tss.mjs"):
        proc = subprocess.run(
            ["node", "--test", str(REPO / "tests" / "js" / name)],
            cwd=str(REPO),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert proc.returncode == 0, name + "\n" + proc.stdout + proc.stderr


def test_gym_shell_and_swap():
    gym = (REPO / "frontend" / "js" / "m" / "gym.js").read_text(encoding="utf-8")
    swap = (REPO / "frontend" / "js" / "m" / "gym-swap.js").read_text(encoding="utf-8")
    html = (REPO / "frontend" / "pages" / "m-shell.html").read_text(encoding="utf-8")
    assert "GYM MODE · OFFLINE READY" in gym
    assert "SESSION DONE" in gym
    assert "session-active" in gym
    assert "apply_to_future" in gym
    assert "USUAL" in swap
    assert "gym-swap.js" in html
    settings = (REPO / "frontend" / "js" / "v2-settings-plan.js").read_text(encoding="utf-8")
    assert "/api/plan/template-overrides" in settings


def test_migration_guards_overrides():
    src = (REPO / "alembic" / "versions" / "d95d4d98684a_pwa_session_template_overrides.py").read_text(
        encoding="utf-8"
    )
    assert "table_exists" in src
    assert "session_template_overrides" in src
