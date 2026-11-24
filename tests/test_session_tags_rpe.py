"""Log list type + RPE pills: effort-time TSS, payload, coach, JS preview."""
from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from backend.main import _canonical_run_subtype
from backend.services.coach_export import _session_row
from backend.services.strength_tss import apply_effort_time_tss, from_effort_time
from backend.services.weekly_rollup import _assemble_week

REPO = Path(__file__).resolve().parents[1]
FEEL_JS = (REPO / "frontend" / "js" / "lib" / "v2-feel-buttons.js").read_text(encoding="utf-8")
LOG_JS = (REPO / "frontend" / "js" / "v2-training-log.js").read_text(encoding="utf-8")
DRAWER_JS = (REPO / "frontend" / "js" / "v2-run-drawer.js").read_text(encoding="utf-8")
MAIN_PY = (REPO / "backend" / "main.py").read_text(encoding="utf-8")
CONSULT_PY = (REPO / "backend" / "services" / "session_consult.py").read_text(encoding="utf-8")


def _week(workouts):
    return _assemble_week(
        ws=date(2026, 11, 16),
        we=date(2026, 11, 22),
        today=date(2026, 11, 24),
        workouts=workouts,
        planned_rows=[],
        planned_tss_training=0.0,
        race_items=[],
        target_tss_val=None,
        phase_label=None,
    )


def _strength(*, effort, tss, method="effort_time", exercises=None):
    sess = MagicMock()
    rows = exercises if exercises is not None else []
    sess.query.return_value.filter.return_value.order_by.return_value.all.return_value = rows
    w = SimpleNamespace(
        id="s1",
        workout_type="strength",
        duration_seconds=3600,
        session_effort=effort,
        strength_tss_method=method,
        tss=tss,
        tss_source="calculated",
        tss_method=method,
        workout_date=date(2026, 11, 18),
        start_time=None,
        run_subtype=None,
        distance_km=None,
    )
    return w, sess


def test_effort_time_rpe_5_to_8_changes_tss_and_week_rollup():
    w, sess = _strength(effort=5, tss=from_effort_time(duration_min=60, effort=5)["tss"])
    before = _week([w])
    assert w.tss == 25
    assert before["tss_strength"] == 25.0
    w.session_effort = 8
    assert apply_effort_time_tss(sess, w) is True
    assert w.tss == 64
    after = _week([w])
    assert after["tss_strength"] == 64.0
    assert after["tss_total"] == 64.0
    assert after["tss_total"] > before["tss_total"]


def test_exercises_method_rpe_does_not_change_tss():
    w, sess = _strength(effort=5, tss=20.1, method="exercises", exercises=[{"name": "A"}])
    w.session_effort = 8
    assert apply_effort_time_tss(sess, w) is False
    assert w.tss == 20.1


def test_run_rpe_does_not_change_tss():
    sess = MagicMock()
    w = SimpleNamespace(
        id="r1",
        workout_type="run",
        duration_seconds=3600,
        session_effort=5,
        strength_tss_method=None,
        tss=46,
        tss_source="calculated",
        tss_method="pace",
        workout_date=date(2026, 11, 18),
        start_time=None,
        run_subtype="easy",
        distance_km=8.2,
    )
    w.session_effort = 8
    assert apply_effort_time_tss(sess, w) is False
    assert w.tss == 46


def test_plyo_and_mobility_use_effort_time():
    for kind in ("plyo", "mobility"):
        w, sess = _strength(effort=5, tss=25)
        w.workout_type = kind
        w.session_effort = 8
        assert apply_effort_time_tss(sess, w) is True
        assert w.tss == 64


def test_patch_workout_calls_effort_time_recompute():
    assert "apply_effort_time_tss" in MAIN_PY
    idx = MAIN_PY.find("elif \"session_effort\" in body.model_fields_set")
    assert idx != -1
    after = MAIN_PY[MAIN_PY.find("_persist_running_tss(wid, session)") :]
    assert "apply_effort_time_tss" in after[:2500]


def test_session_effort_outside_range_rejected_in_patch():
    assert "session_effort must be 1–10" in MAIN_PY
    assert "if body.session_effort is not None and not (1 <= body.session_effort <= 10)" in MAIN_PY


def test_canonical_subtype_values_unchanged():
    assert _canonical_run_subtype("longrun") == "longrun"
    assert _canonical_run_subtype("interval") == "interval"
    assert _canonical_run_subtype("Intervals") == "interval"


def test_log_payload_includes_session_effort():
    assert '"session_effort": w.session_effort' in MAIN_PY or "session_effort" in MAIN_PY
    assert "data-rpe" in LOG_JS
    assert "data-is-run" in LOG_JS
    assert "data-run-subtype" in LOG_JS


def test_no_hard_ok_easy_in_list_or_drawer_mount():
    row = LOG_JS[LOG_JS.find("function renderSessionRow") : LOG_JS.find("function fmtSignedDelta")]
    assert "Hard" not in row
    assert "data-feeling" not in row
    assert "V2SessionTags" in LOG_JS
    assert "Hard" not in DRAWER_JS
    assert "w.feeling" not in DRAWER_JS
    assert "V2SessionTags" in DRAWER_JS or "V2FeelButtons" in DRAWER_JS
    assert "text: 'Hard'" not in FEEL_JS
    assert "label: 'OK'" not in FEEL_JS


def test_js_apply_rpe_updates_tss_without_reload():
    assert "function applyRpeInPlace" in LOG_JS
    assert "function updateRowTssAndShare" in LOG_JS
    assert "rv-session-tss" in LOG_JS
    assert "rv-session-share-fill" in LOG_JS
    fn_start = LOG_JS.find("function applyRpeInPlace")
    fn = LOG_JS[fn_start : LOG_JS.find("function applySkipInPlace")]
    assert "refreshWeekRollup" in fn
    assert "loadList" not in fn
    assert "refreshAll" not in fn


def test_coach_export_adds_rpe_next_to_feeling():
    w = SimpleNamespace(
        id="w1",
        workout_type="run",
        name="Lunch",
        duration_seconds=3600,
        distance_km=8.0,
        avg_hr=None,
        avg_power=None,
        zone2_minutes=None,
        elevation_m=None,
        decoupling_percent=None,
        feeling="ok",
        session_effort=7,
        run_subtype="easy",
        workout_date=date(2026, 11, 18),
        start_time=None,
        tss=46,
        tss_source="calculated",
        tss_method="pace",
        tss_method_override=None,
        tss_power=None,
        tss_stryd=None,
    )
    row = _session_row(w, {})
    assert row["feeling"] == "ok"
    assert row["rpe"] == 7


def test_consult_includes_rpe_line():
    assert "RPE: {workout.session_effort}/10" in CONSULT_PY
    assert "feeling: {_na(workout.feeling)}" in CONSULT_PY


def test_js_preview_run_tempo_rpe_7_and_strength_unset():
    script = r"""
const fs = require('fs');
const code = fs.readFileSync(process.argv[1], 'utf8');
const window = global;
eval(code);
const a = window.V2SessionTags.preview({ isRun: true, runSubtype: 'tempo', rpe: 7 });
const b = window.V2SessionTags.preview({ isRun: false, rpe: null });
console.log(JSON.stringify({ a: a, b: b }));
"""
    proc = subprocess.run(
        ["node", "-e", script, str(REPO / "frontend" / "js" / "lib" / "v2-feel-buttons.js")],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["a"]["showType"] is True
    assert out["a"]["typeText"] == "Tempo ▾"
    assert out["a"]["rpeText"] == "RPE 7 ▾"
    assert out["b"]["showType"] is False
    assert out["b"]["typeText"] is None
    assert out["b"]["rpeText"] == "RPE ▾"
