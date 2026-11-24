"""PWA phase 5 static contracts (body / weigh-in / Zone 2)."""
from __future__ import annotations

import inspect
import subprocess
from datetime import date
from pathlib import Path

from backend.services.axis_strength import trend_mass_from_entries
from backend.services.body_log_store import patch_body_log
from backend.services.mobile_bundle import build_zone2_week
from backend.services.mobile_sync import _apply_weigh_in
from backend.services.weight_ewma import compute_ewma

REPO = Path(__file__).resolve().parents[1]


def test_trend_kg_equals_weight_ewma():
    entries = [{"date": date(2026, 1, d), "weight_kg": 70.0 - d * 0.04} for d in range(1, 20)]
    assert round(float(trend_mass_from_entries(entries)), 2) == round(compute_ewma(entries)[-1], 2)


def test_zone2_total_is_logged_easy_minutes_only():
    today = date(2026, 11, 24)  # Tuesday
    logged = {
        date(2026, 11, 24): 40,
        date(2026, 11, 23): 22,
    }
    planned = {date(2026, 11, 29): 50}
    out = build_zone2_week(today, logged, planned, target=150, hr_ceiling=155)
    assert out["total"] == 62
    assert out["target"] == 150
    assert out["hr_ceiling"] == 155
    assert out["days"][0]["label"] == "M"
    sun = out["days"][6]
    assert sun["planned_min"] == 50
    assert sun["logged_min"] == 0
    assert out["total"] == 62


def test_weigh_in_uses_upsert():
    src = inspect.getsource(patch_body_log)
    assert "on_conflict_do_update" in src
    apply_src = inspect.getsource(_apply_weigh_in)
    assert "patch_body_log" in apply_src


def test_body_and_today_surfaces():
    body = (REPO / "frontend" / "js" / "m" / "body.js").read_text(encoding="utf-8")
    today = (REPO / "frontend" / "js" / "m" / "today.js").read_text(encoding="utf-8")
    settings = (REPO / "frontend" / "js" / "settings-profile.js").read_text(encoding="utf-8")
    html = (REPO / "frontend" / "pages" / "v2-settings.html").read_text(encoding="utf-8")
    assert "Save weigh-in" in body
    assert "weigh_ins" in body
    assert "ZONE 2" in body
    assert "m-z2-bar--planned" in body
    assert "hasWeight" in today
    assert "/m/body/weigh-in" in today
    assert "weekly_zone2_target_min" in settings
    assert "profile-zone2-target" in html


def test_today_harness_hides_empty_body():
    proc = subprocess.run(
        ["node", "--test", str(REPO / "tests" / "js" / "test_m_today.mjs")],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
