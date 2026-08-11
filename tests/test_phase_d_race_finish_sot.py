"""Phase D — single race-finish SoT; park CTL√ / coach_projection race path."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXPORT = (REPO / "backend" / "services" / "coach_export.py").read_text(encoding="utf-8")
PROJECTION = (REPO / "backend" / "services" / "coach_projection.py").read_text(
    encoding="utf-8"
)
WEEKLY = (REPO / "backend" / "services" / "weekly_coach_message.py").read_text(
    encoding="utf-8"
)
GATE = (REPO / "tests" / "test_reachability_gate__1602.py").read_text(encoding="utf-8")
MAIN = (REPO / "backend" / "main.py").read_text(encoding="utf-8")


def test_coach_export_race_estimate_uses_performance_sot():
    i = EXPORT.find("def _race_estimate")
    assert i >= 0
    chunk = EXPORT[i : i + 2500]
    assert "estimate_race_finish" in chunk
    assert "_race_readiness_impl" not in chunk
    assert "race_readiness_projection" not in chunk


def test_coach_projection_race_path_is_parked():
    assert "ponytail: parked for race finish SoT (Phase D)" in PROJECTION
    i = PROJECTION.find("def race_projection")
    assert i >= 0
    chunk = PROJECTION[i : i + 800]
    assert "ponytail: parked" in chunk
    assert "estimate_race_finish" in chunk


def test_ctl_sqrt_trend_helpers_are_parked():
    assert "ponytail: parked — Coach Dream / export use" in WEEKLY
    assert "def build_projection_info" in WEEKLY
    i = WEEKLY.find("def build_projection_info")
    chunk = WEEKLY[i : i + 600]
    assert "ponytail: parked" in chunk
    assert "estimate_race_finish" in chunk


def test_projection_endpoint_is_permanent_exempt_not_baseline_orphan():
    assert '"/api/projection":' in GATE
    assert "_compute_plan_bundle" in GATE
    # Permanent-exempt entry only — not also listed under baseline orphans.
    after_baseline = GATE.split("_BASELINE_ORPHANS_API: dict[str, str] = {", 1)[1]
    baseline_body = after_baseline.split("}", 1)[0]
    assert '"/api/projection"' not in baseline_body


def test_flat_races_noted_for_phase_e_not_deleted():
    assert "Phase E migrates" in MAIN
    assert '@app.post("/api/races"' in MAIN
    assert '@app.get("/api/races"' in MAIN
