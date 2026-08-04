"""Tests for issue #1483: Hermes brief exporter — scripts/export_brief.py

AC coverage:
- AC1: Script at scripts/export_brief.py with argparse entry point, __main__ guard,
        non-zero sys.exit on unhandled failure.
- AC2: Atomic write — tempfile in the same directory promoted via os.replace.
- AC3: File-based lock acquired before writing; concurrent run exits with error rather
        than corrupting the output.
- AC4: --dry-run prints JSON to stdout, exits 0, does not touch output file or lock.
- AC5: Top-level envelope has schema_version (int), for_date (ISO-8601 date string,
        +07:00), and generated_at (ISO-8601 datetime with +07:00 offset).
- AC6: today/tomorrow objects contain date, session_type, planned, intensity,
        duration_min, notes; data sourced from worker /api/plan/today.
- AC7: form object contains ctl, atl, tsb, ramp, flags, interpretation.
- AC8: recent_wrap object contains window_days, sessions_planned, sessions_completed,
        adherence (float 0–1), load_trend, highlights_md (non-empty string).
- AC9: advisories is a list; each item has key, severity ("info" or "warn"), and text.
- AC10: actions is present as an empty list [].
- AC11: Script exits non-zero and prints human-readable error to stderr when data
        source is unavailable.
- AC12: --date argument generates brief for an arbitrary date.
"""
import importlib
import json
import os
import pathlib
import sys
import tempfile
from datetime import date
from unittest.mock import patch

import pytest

import backend.services.daily_brief as _svc_mod

# ── path to the script under test ─────────────────────────────────────────────
_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPT = _ROOT / "scripts" / "export_brief.py"


# ── import the module under test (without executing __main__) ─────────────────
def _import_module():
    spec = importlib.util.spec_from_file_location("export_brief", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def m():
    return _import_module()


# ── AC1: File exists, has argparse, has __main__ guard ───────────────────────

def test_script_file_exists():
    """AC1: scripts/export_brief.py exists."""
    assert _SCRIPT.exists(), f"Script not found at {_SCRIPT}"


def test_script_has_argparse(m):
    """AC1: main() is callable and takes no required positional args."""
    assert callable(m.main)


def test_script_has_main_guard():
    """AC1: Script contains if __name__ == '__main__' guard."""
    src = _SCRIPT.read_text()
    assert '__name__ == "__main__"' in src or "__name__ == '__main__'" in src


def test_main_exit_code_on_db_failure(m):
    """AC1/AC11: main() returns non-zero when database is unavailable."""
    with patch.object(sys, "argv", ["export_brief.py", "--env", "uat"]):
        with patch.dict(os.environ, {}, clear=True):
            # No DATABASE_URL or DATABASE_URL_UAT → must return non-zero
            rc = m.main()
    assert rc != 0


# ── AC2: Atomic write ─────────────────────────────────────────────────────────

def test_write_atomic_creates_file(m, tmp_path):
    """AC2: _write_atomic writes valid JSON to the target path."""
    target = tmp_path / "brief.json"
    data = {"schema_version": 1, "for_date": "2026-07-14"}
    m._write_atomic(str(target), data)
    assert target.exists()
    assert json.loads(target.read_text()) == data


def test_write_atomic_uses_tempfile_in_same_dir(m, tmp_path):
    """AC2: Tempfile is created in the same directory before promotion."""
    target = tmp_path / "brief.json"
    seen_temps = []

    real_mkstemp = tempfile.mkstemp

    def spy_mkstemp(**kwargs):
        result = real_mkstemp(**kwargs)
        seen_temps.append(result[1])
        return result

    import tempfile as _tempfile_mod
    with patch.object(_tempfile_mod, "mkstemp", side_effect=spy_mkstemp):
        m._write_atomic(str(target), {"x": 1})

    assert len(seen_temps) >= 1
    for tmp in seen_temps:
        assert os.path.dirname(tmp) == str(tmp_path)


def test_write_atomic_is_idempotent(m, tmp_path):
    """AC2: Calling _write_atomic twice overwrites the file correctly."""
    target = tmp_path / "brief.json"
    m._write_atomic(str(target), {"v": 1})
    m._write_atomic(str(target), {"v": 2})
    assert json.loads(target.read_text()) == {"v": 2}


def test_write_atomic_no_partial_on_error(m, tmp_path):
    """AC2: A failed write leaves no temp file behind."""
    target = tmp_path / "brief.json"

    with patch("json.dump", side_effect=RuntimeError("disk error")):
        with pytest.raises(RuntimeError):
            m._write_atomic(str(target), {"v": 1})

    temps = list(tmp_path.glob("*.tmp"))
    assert temps == [], "Temp file left behind after failure"
    assert not target.exists()


# ── AC3: File-based lock ──────────────────────────────────────────────────────

def test_lock_prevents_concurrent_write(m, tmp_path):
    """AC3: Second invocation with lock already held exits non-zero."""
    import fcntl

    output = tmp_path / "brief.json"
    lock = tmp_path / "perfcoach_brief.lock"

    # Hold the lock externally
    lock_fd = open(str(lock), "w")
    fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with patch.object(sys, "argv", [
            "export_brief.py",
            "--output", str(output),
            "--env", "uat",
        ]):
            with patch.dict(os.environ, {"DATABASE_URL": "postgresql://fake"}):
                with patch.object(m, "_resolve_user", return_value="00000000-0000-0000-0000-000000000001"):
                    rc = m.main()
        assert rc != 0, "Expected non-zero exit when lock is held"
    finally:
        fcntl.flock(lock_fd, fcntl.LOCK_UN)
        lock_fd.close()


# ── AC4: --dry-run ────────────────────────────────────────────────────────────

def _make_brief_payload(for_date: str = "2026-07-14") -> dict:
    return {
        "schema_version": 1,
        "for_date": for_date,
        "generated_at": f"{for_date}T08:00:00+07:00",
        "today": {
            "date": for_date,
            "session_type": "run",
            "planned": True,
            "intensity": "easy",
            "duration_min": 50,
            "notes": None,
        },
        "tomorrow": {
            "date": "2026-07-15",
            "session_type": None,
            "planned": False,
            "intensity": None,
            "duration_min": None,
            "notes": None,
        },
        "form": {
            "ctl": 42.0, "atl": 35.0, "tsb": 7.0,
            "ramp": 1.2, "flags": {"guardrail_state": "ok"},
            "interpretation": "Fresh",
        },
        "recent_wrap": {
            "window_days": 14, "sessions_planned": 10, "sessions_completed": 8,
            "adherence": 0.8, "load_trend": 1.2, "highlights_md": "Good week.",
        },
        "advisories": [],
        "actions": [],
    }


def test_dry_run_prints_json_stdout(m, tmp_path, capsys):
    """AC4: --dry-run prints valid JSON to stdout."""
    output = tmp_path / "brief.json"
    payload = _make_brief_payload()

    with patch.object(sys, "argv", [
        "export_brief.py",
        "--dry-run",
        "--output", str(output),
        "--env", "uat",
    ]):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://fake"}):
            with patch.object(m, "_resolve_user", return_value="abc"):
                with patch.object(m, "_build_brief", return_value=payload):
                    rc = m.main()

    assert rc == 0
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["schema_version"] == 1


def test_dry_run_does_not_write_file(m, tmp_path, capsys):
    """AC4: --dry-run must not create or modify the output file."""
    output = tmp_path / "brief.json"
    payload = _make_brief_payload()

    with patch.object(sys, "argv", [
        "export_brief.py",
        "--dry-run",
        "--output", str(output),
        "--env", "uat",
    ]):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://fake"}):
            with patch.object(m, "_resolve_user", return_value="abc"):
                with patch.object(m, "_build_brief", return_value=payload):
                    m.main()

    assert not output.exists(), "--dry-run must not write the output file"


def test_dry_run_does_not_acquire_lock(m, tmp_path):
    """AC4: --dry-run must not create or touch the lock file."""
    output = tmp_path / "brief.json"
    lock = tmp_path / "perfcoach_brief.lock"
    payload = _make_brief_payload()

    with patch.object(sys, "argv", [
        "export_brief.py",
        "--dry-run",
        "--output", str(output),
        "--env", "uat",
    ]):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://fake"}):
            with patch.object(m, "_resolve_user", return_value="abc"):
                with patch.object(m, "_build_brief", return_value=payload):
                    m.main()

    assert not lock.exists(), "--dry-run must not create the lock file"


# ── AC5: Top-level envelope ───────────────────────────────────────────────────

def test_envelope_schema_version(m):
    """AC5/v3: schema_version is integer (bumped to 3 by issue #1497 — acwr +
    week_plan addition to the brief contract; the #1505 coach-block addition
    is additive and does not bump it further)."""
    assert m.SCHEMA_VERSION == 3


def test_build_brief_envelope_keys(m):
    """AC5: _build_brief returns all required top-level keys."""
    fake_plan = {"planned": False, "sessions": [], "plan_date": "2026-07-14"}
    fake_form = {
        "ctl": 40.0, "atl": 38.0, "tsb": 2.0,
        "ramp": 0.5, "flags": {}, "interpretation": "Neutral",
    }
    fake_wrap = {
        "window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
        "adherence": 0.0, "load_trend": 0.0, "highlights_md": "Rest week.",
    }

    with patch.object(_svc_mod, "_get_plan_for_date", return_value=fake_plan), \
         patch.object(_svc_mod, "_assemble_form", return_value=fake_form), \
         patch.object(_svc_mod, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(_svc_mod, "_assemble_weight", return_value={}), \
         patch.object(_svc_mod, "_assemble_advisories", return_value=[]), \
         patch.object(_svc_mod, "_assemble_week_plan", return_value=[]), \
         patch.object(_svc_mod, "_assemble_coach", return_value=None):

        brief = m._build_brief(
            date(2026, 7, 14), "http://localhost:9100", "user-id-1", None
        )

    assert brief["schema_version"] == 3
    assert brief["for_date"] == "2026-07-14"
    assert "+07:00" in brief["generated_at"]
    assert "today" in brief
    assert "tomorrow" in brief
    assert "form" in brief
    assert "recent_wrap" in brief
    assert "advisories" in brief
    assert "actions" in brief
    assert "week_plan" in brief


def test_generated_at_has_bangkok_offset(m):
    """AC5: generated_at contains +07:00 offset."""
    fake_plan = {"planned": False, "sessions": [], "plan_date": "2026-07-14"}
    fake_form = {"ctl": 1.0, "atl": 1.0, "tsb": 0.0, "ramp": 0.0, "flags": {}, "interpretation": "Neutral"}
    fake_wrap = {"window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
                 "adherence": 0.0, "load_trend": 0.0, "highlights_md": "ok"}

    with patch.object(_svc_mod, "_get_plan_for_date", return_value=fake_plan), \
         patch.object(_svc_mod, "_assemble_form", return_value=fake_form), \
         patch.object(_svc_mod, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(_svc_mod, "_assemble_weight", return_value={}), \
         patch.object(_svc_mod, "_assemble_advisories", return_value=[]), \
         patch.object(_svc_mod, "_assemble_week_plan", return_value=[]), \
         patch.object(_svc_mod, "_assemble_coach", return_value=None):

        brief = m._build_brief(date(2026, 7, 14), "http://localhost:9100", "u", None)

    assert "+07:00" in brief["generated_at"]


# ── AC6: today / tomorrow objects ─────────────────────────────────────────────

def test_plan_to_session_with_session(m):
    """AC6: _plan_to_session extracts correct keys from a planned-session response."""
    resp = {
        "planned": True,
        "sessions": [
            {
                "session_type": "run",
                "name": "Easy run",
                "note": "Zone 2",
                "status": "planned",
                "target": {"intensity": "easy", "duration_min": 50, "distance_km": 8.0},
            }
        ],
    }
    result = m._plan_to_session(resp, date(2026, 7, 14))
    assert result["date"] == "2026-07-14"
    assert result["session_type"] == "run"
    assert result["planned"] is True
    assert result["intensity"] == "easy"
    assert result["duration_min"] == 50
    assert result["notes"] == "Zone 2"


def test_plan_to_session_no_sessions(m):
    """AC6: _plan_to_session handles planned:false with empty sessions."""
    resp = {"planned": False, "sessions": []}
    result = m._plan_to_session(resp, date(2026, 7, 14))
    assert result["date"] == "2026-07-14"
    assert result["planned"] is False
    assert result["session_type"] is None
    assert result["intensity"] is None
    assert result["duration_min"] is None
    assert result["notes"] is None


def test_today_tomorrow_correct_dates(m):
    """AC6: today uses for_date, tomorrow uses for_date + 1 day."""
    calls_made = []

    def fake_get_plan(user_id, for_date):
        calls_made.append(for_date.isoformat())
        return {"planned": False, "sessions": []}

    fake_form = {"ctl": 1.0, "atl": 1.0, "tsb": 0.0, "ramp": 0.0, "flags": {}, "interpretation": "Neutral"}
    fake_wrap = {"window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
                 "adherence": 0.0, "load_trend": 0.0, "highlights_md": "ok"}

    with patch.object(_svc_mod, "_get_plan_for_date", side_effect=fake_get_plan), \
         patch.object(_svc_mod, "_assemble_form", return_value=fake_form), \
         patch.object(_svc_mod, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(_svc_mod, "_assemble_weight", return_value={}), \
         patch.object(_svc_mod, "_assemble_advisories", return_value=[]), \
         patch.object(_svc_mod, "_assemble_week_plan", return_value=[]), \
         patch.object(_svc_mod, "_assemble_coach", return_value=None):

        brief = m._build_brief(date(2026, 7, 14), "http://w:9100", "u", None)

    assert calls_made == ["2026-07-14", "2026-07-15"]
    assert brief["today"]["date"] == "2026-07-14"
    assert brief["tomorrow"]["date"] == "2026-07-15"


SESSION_KEYS = {"date", "session_type", "planned", "intensity", "duration_min", "notes"}


def test_today_has_required_keys(m):
    """AC6: today object has all required keys."""
    fake_plan = {"planned": False, "sessions": []}
    fake_form = {"ctl": 1.0, "atl": 1.0, "tsb": 0.0, "ramp": 0.0, "flags": {}, "interpretation": "ok"}
    fake_wrap = {"window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
                 "adherence": 0.0, "load_trend": 0.0, "highlights_md": "x"}

    with patch.object(_svc_mod, "_get_plan_for_date", return_value=fake_plan), \
         patch.object(_svc_mod, "_assemble_form", return_value=fake_form), \
         patch.object(_svc_mod, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(_svc_mod, "_assemble_weight", return_value={}), \
         patch.object(_svc_mod, "_assemble_advisories", return_value=[]), \
         patch.object(_svc_mod, "_assemble_week_plan", return_value=[]), \
         patch.object(_svc_mod, "_assemble_coach", return_value=None):

        brief = m._build_brief(date(2026, 7, 14), "http://w:9100", "u", None)

    assert SESSION_KEYS.issubset(set(brief["today"].keys()))
    assert SESSION_KEYS.issubset(set(brief["tomorrow"].keys()))


# ── AC7: form object ──────────────────────────────────────────────────────────

FORM_KEYS = {"ctl", "atl", "tsb", "ramp", "flags", "interpretation"}


def test_form_has_required_keys(m):
    """AC7: form object has all required keys."""
    fake_plan = {"planned": False, "sessions": []}
    fake_form = {
        "ctl": 42.0, "atl": 38.0, "tsb": 4.0,
        "ramp": 1.5, "flags": {"guardrail_state": "ok"},
        "interpretation": "Neutral",
    }
    fake_wrap = {"window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
                 "adherence": 0.0, "load_trend": 0.0, "highlights_md": "x"}

    with patch.object(_svc_mod, "_get_plan_for_date", return_value=fake_plan), \
         patch.object(_svc_mod, "_assemble_form", return_value=fake_form), \
         patch.object(_svc_mod, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(_svc_mod, "_assemble_weight", return_value={}), \
         patch.object(_svc_mod, "_assemble_advisories", return_value=[]), \
         patch.object(_svc_mod, "_assemble_week_plan", return_value=[]), \
         patch.object(_svc_mod, "_assemble_coach", return_value=None):

        brief = m._build_brief(date(2026, 7, 14), "http://w:9100", "u", None)

    assert FORM_KEYS.issubset(set(brief["form"].keys()))


def test_load_interpretation_fresh(m):
    """AC7: _load_interpretation returns 'Fresh' for positive TSB."""
    assert "Fresh" in m._load_interpretation(50.0, 40.0, 10.0)


def test_load_interpretation_overreached(m):
    """AC7: _load_interpretation returns overreached label for very negative TSB."""
    assert "Overreached" in m._load_interpretation(50.0, 70.0, -20.0)


def test_load_interpretation_well_trained(m):
    """AC7: _load_interpretation appends 'well-trained' when CTL > 60."""
    result = m._load_interpretation(65.0, 60.0, 5.0)
    assert "well-trained" in result


def test_load_interpretation_undertrained(m):
    """AC7: _load_interpretation appends 'undertrained' when CTL < 30."""
    result = m._load_interpretation(20.0, 15.0, 5.0)
    assert "undertrained" in result


# ── AC8: recent_wrap object ───────────────────────────────────────────────────

RECENT_WRAP_KEYS = {
    "window_days", "sessions_planned", "sessions_completed",
    "adherence", "load_trend", "highlights_md",
}


def test_recent_wrap_has_required_keys(m):
    """AC8: recent_wrap object has all required keys."""
    fake_plan = {"planned": False, "sessions": []}
    fake_form = {"ctl": 1.0, "atl": 1.0, "tsb": 0.0, "ramp": 0.0, "flags": {}, "interpretation": "ok"}
    fake_wrap = {
        "window_days": 14,
        "sessions_planned": 10,
        "sessions_completed": 8,
        "adherence": 0.8,
        "load_trend": 1.2,
        "highlights_md": "Strong week.",
    }

    with patch.object(_svc_mod, "_get_plan_for_date", return_value=fake_plan), \
         patch.object(_svc_mod, "_assemble_form", return_value=fake_form), \
         patch.object(_svc_mod, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(_svc_mod, "_assemble_weight", return_value={}), \
         patch.object(_svc_mod, "_assemble_advisories", return_value=[]), \
         patch.object(_svc_mod, "_assemble_week_plan", return_value=[]), \
         patch.object(_svc_mod, "_assemble_coach", return_value=None):

        brief = m._build_brief(date(2026, 7, 14), "http://w:9100", "u", None)

    assert RECENT_WRAP_KEYS.issubset(set(brief["recent_wrap"].keys()))


def test_adherence_is_between_0_and_1(m):
    """AC8: adherence value is clamped to [0, 1]."""
    fake_plan = {"planned": False, "sessions": []}
    fake_form = {"ctl": 1.0, "atl": 1.0, "tsb": 0.0, "ramp": 0.0, "flags": {}, "interpretation": "ok"}
    fake_wrap = {
        "window_days": 14, "sessions_planned": 5, "sessions_completed": 3,
        "adherence": 0.6, "load_trend": 0.0, "highlights_md": "ok",
    }

    with patch.object(_svc_mod, "_get_plan_for_date", return_value=fake_plan), \
         patch.object(_svc_mod, "_assemble_form", return_value=fake_form), \
         patch.object(_svc_mod, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(_svc_mod, "_assemble_weight", return_value={}), \
         patch.object(_svc_mod, "_assemble_advisories", return_value=[]), \
         patch.object(_svc_mod, "_assemble_week_plan", return_value=[]), \
         patch.object(_svc_mod, "_assemble_coach", return_value=None):

        brief = m._build_brief(date(2026, 7, 14), "http://w:9100", "u", None)

    adherence = brief["recent_wrap"]["adherence"]
    assert 0.0 <= adherence <= 1.0


# ── AC9: advisories list ──────────────────────────────────────────────────────

def test_advisories_is_list(m):
    """AC9: advisories is always a list."""
    fake_plan = {"planned": False, "sessions": []}
    fake_form = {"ctl": 1.0, "atl": 1.0, "tsb": 0.0, "ramp": 0.0, "flags": {}, "interpretation": "ok"}
    fake_wrap = {"window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
                 "adherence": 0.0, "load_trend": 0.0, "highlights_md": "ok"}

    with patch.object(_svc_mod, "_get_plan_for_date", return_value=fake_plan), \
         patch.object(_svc_mod, "_assemble_form", return_value=fake_form), \
         patch.object(_svc_mod, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(_svc_mod, "_assemble_weight", return_value={}), \
         patch.object(_svc_mod, "_assemble_advisories", return_value=[]), \
         patch.object(_svc_mod, "_assemble_week_plan", return_value=[]), \
         patch.object(_svc_mod, "_assemble_coach", return_value=None):

        brief = m._build_brief(date(2026, 7, 14), "http://w:9100", "u", None)

    assert isinstance(brief["advisories"], list)


def test_advisories_item_keys(m):
    """AC9: each advisory has key, severity, and text."""
    advisories = [
        {"key": "no_recent_plyo", "severity": "warn", "text": "Add plyometrics."},
        {"key": "low_run_volume", "severity": "info", "text": "Consider more easy mileage."},
    ]
    fake_plan = {"planned": False, "sessions": []}
    fake_form = {"ctl": 1.0, "atl": 1.0, "tsb": 0.0, "ramp": 0.0, "flags": {}, "interpretation": "ok"}
    fake_wrap = {"window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
                 "adherence": 0.0, "load_trend": 0.0, "highlights_md": "ok"}

    with patch.object(_svc_mod, "_get_plan_for_date", return_value=fake_plan), \
         patch.object(_svc_mod, "_assemble_form", return_value=fake_form), \
         patch.object(_svc_mod, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(_svc_mod, "_assemble_weight", return_value={}), \
         patch.object(_svc_mod, "_assemble_advisories", return_value=advisories), \
         patch.object(_svc_mod, "_assemble_week_plan", return_value=[]), \
         patch.object(_svc_mod, "_assemble_coach", return_value=None):

        brief = m._build_brief(date(2026, 7, 14), "http://w:9100", "u", None)

    for item in brief["advisories"]:
        assert "key" in item
        assert "severity" in item
        assert "text" in item
        assert item["severity"] in ("info", "warn")


def test_advisories_severity_mapping(m):
    """AC9: gap-analysis severity int 1 maps to 'info', 2+ maps to 'warn'."""
    # _assemble_advisories maps severity
    findings_list = [
        {"code": "a", "severity": 1, "recommendation": "mild"},
        {"code": "b", "severity": 2, "recommendation": "moderate"},
        {"code": "c", "severity": 3, "recommendation": "critical"},
    ]

    mock_result = {"findings": findings_list}

    with patch("backend.services.gap_analysis.engine.run_gap_analysis", return_value=mock_result), \
         patch("backend.services.gap_analysis.engine._gather_training_verdict", return_value=None):

        mod = _import_module()
        # _assemble_advisories grew a required 3rd positional "weight" param
        # (see tests/test_weight_hermes_brief_block.py for the weight-block
        # coverage); {} here is a no-target weight block, keeping this test
        # scoped to gap-analysis severity mapping only, unaffected by the
        # weight advisory branch.
        result = mod._assemble_advisories("00000000-0000-0000-0000-000000000001", date(2026, 7, 14), {})

    severities = {item["key"]: item["severity"] for item in result}
    assert severities.get("a") == "info"
    assert severities.get("b") == "warn"
    assert severities.get("c") == "warn"


# ── AC10: actions is empty list ───────────────────────────────────────────────

def test_actions_is_empty_list(m):
    """AC10: actions is always an empty list []."""
    fake_plan = {"planned": False, "sessions": []}
    fake_form = {"ctl": 1.0, "atl": 1.0, "tsb": 0.0, "ramp": 0.0, "flags": {}, "interpretation": "ok"}
    fake_wrap = {"window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
                 "adherence": 0.0, "load_trend": 0.0, "highlights_md": "ok"}

    with patch.object(_svc_mod, "_get_plan_for_date", return_value=fake_plan), \
         patch.object(_svc_mod, "_assemble_form", return_value=fake_form), \
         patch.object(_svc_mod, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(_svc_mod, "_assemble_weight", return_value={}), \
         patch.object(_svc_mod, "_assemble_advisories", return_value=[]), \
         patch.object(_svc_mod, "_assemble_week_plan", return_value=[]), \
         patch.object(_svc_mod, "_assemble_coach", return_value=None):

        brief = m._build_brief(date(2026, 7, 14), "http://w:9100", "u", None)

    assert brief["actions"] == []


# ── AC11: Non-zero exit on failure ────────────────────────────────────────────

def test_worker_unreachable_exits_nonzero(m, tmp_path):
    """AC11: RuntimeError from _fetch_plan causes non-zero exit."""
    output = tmp_path / "brief.json"

    def raise_unreachable(*args, **kwargs):
        raise RuntimeError("Worker unreachable")

    with patch.object(sys, "argv", [
        "export_brief.py",
        "--output", str(output),
        "--env", "uat",
    ]):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://fake"}):
            with patch.object(m, "_resolve_user", return_value="uid"):
                with patch.object(m, "_build_brief", side_effect=raise_unreachable):
                    rc = m.main()

    assert rc != 0
    assert not output.exists()


def test_stderr_message_on_failure(m, tmp_path, capsys):
    """AC11: Error message printed to stderr on failure."""
    output = tmp_path / "brief.json"

    with patch.object(sys, "argv", [
        "export_brief.py",
        "--output", str(output),
        "--env", "uat",
    ]):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://fake"}):
            with patch.object(m, "_resolve_user", return_value="uid"):
                with patch.object(m, "_build_brief", side_effect=RuntimeError("db gone")):
                    m.main()

    captured = capsys.readouterr()
    assert "ERROR" in captured.err or "error" in captured.err.lower()


# ── AC12: --date argument ─────────────────────────────────────────────────────

def test_date_arg_sets_for_date(m):
    """AC12: --date sets for_date in the brief envelope."""
    fake_plan = {"planned": False, "sessions": []}
    fake_form = {"ctl": 1.0, "atl": 1.0, "tsb": 0.0, "ramp": 0.0, "flags": {}, "interpretation": "ok"}
    fake_wrap = {"window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
                 "adherence": 0.0, "load_trend": 0.0, "highlights_md": "ok"}
    built = []

    def capture_build(for_date, worker_url, user_id, username):
        built.append(for_date)
        return {
            "schema_version": 1,
            "for_date": for_date.isoformat(),
            "generated_at": "2026-07-20T08:00:00+07:00",
            "today": m._plan_to_session(fake_plan, for_date),
            "tomorrow": m._plan_to_session(fake_plan, for_date),
            "form": fake_form,
            "recent_wrap": fake_wrap,
            "advisories": [],
            "actions": [],
        }

    with patch.object(sys, "argv", [
        "export_brief.py",
        "--date", "2026-07-20",
        "--dry-run",
        "--env", "uat",
    ]):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://fake"}):
            with patch.object(m, "_resolve_user", return_value="uid"):
                with patch.object(m, "_build_brief", side_effect=capture_build):
                    rc = m.main()

    assert rc == 0
    assert built == [date(2026, 7, 20)]


def test_date_arg_invalid_exits_nonzero(m, capsys):
    """AC12: Invalid --date format causes non-zero exit and error message."""
    with patch.object(sys, "argv", [
        "export_brief.py",
        "--date", "not-a-date",
        "--dry-run",
        "--env", "uat",
    ]):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://fake"}):
            rc = m.main()

    assert rc != 0
    captured = capsys.readouterr()
    assert "ERROR" in captured.err


def test_date_arg_in_brief_output_for_date(m):
    """AC12: for_date in envelope matches --date argument."""
    fake_plan = {"planned": False, "sessions": []}
    fake_form = {"ctl": 1.0, "atl": 1.0, "tsb": 0.0, "ramp": 0.0, "flags": {}, "interpretation": "ok"}
    fake_wrap = {"window_days": 14, "sessions_planned": 0, "sessions_completed": 0,
                 "adherence": 0.0, "load_trend": 0.0, "highlights_md": "ok"}

    with patch.object(_svc_mod, "_get_plan_for_date", return_value=fake_plan), \
         patch.object(_svc_mod, "_assemble_form", return_value=fake_form), \
         patch.object(_svc_mod, "_assemble_recent_wrap", return_value=fake_wrap), \
         patch.object(_svc_mod, "_assemble_weight", return_value={}), \
         patch.object(_svc_mod, "_assemble_advisories", return_value=[]), \
         patch.object(_svc_mod, "_assemble_week_plan", return_value=[]), \
         patch.object(_svc_mod, "_assemble_coach", return_value=None):

        brief = m._build_brief(date(2026, 7, 20), "http://w:9100", "u", None)

    assert brief["for_date"] == "2026-07-20"
    assert brief["today"]["date"] == "2026-07-20"
    assert brief["tomorrow"]["date"] == "2026-07-21"


# ── AC2: Atomic write uses os.replace ─────────────────────────────────────────

def test_write_atomic_uses_os_replace(m, tmp_path):
    """AC2: _write_atomic promotes via os.replace, not rename or copyfile."""
    target = tmp_path / "brief.json"
    replaced = []

    real_replace = os.replace

    def spy_replace(src, dst):
        replaced.append((src, dst))
        return real_replace(src, dst)

    with patch("os.replace", side_effect=spy_replace):
        m._write_atomic(str(target), {"ok": True})

    assert len(replaced) == 1
    assert replaced[0][1] == str(target)


# ── Normal write flow (integration-style, no live DB) ─────────────────────────

def test_normal_mode_writes_file(m, tmp_path, capsys):
    """Integration: normal mode writes valid JSON to the output file."""
    output = tmp_path / "brief.json"
    payload = _make_brief_payload()

    with patch.object(sys, "argv", [
        "export_brief.py",
        "--output", str(output),
        "--env", "uat",
    ]):
        with patch.dict(os.environ, {"DATABASE_URL": "postgresql://fake"}):
            with patch.object(m, "_resolve_user", return_value="uid"):
                with patch.object(m, "_build_brief", return_value=payload):
                    rc = m.main()

    assert rc == 0
    assert output.exists()
    parsed = json.loads(output.read_text())
    assert parsed["schema_version"] == 1
