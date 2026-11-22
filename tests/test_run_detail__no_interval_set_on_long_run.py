"""#1902: Interval Set card must not appear on a long run with auto km splits.

Aid-station walk km trip buildLapMeta.anomaly; the old extractIntervalSet
fallback then treated the whole marathon as work reps. Option A: drop that
fallback. Keep manual-lap and confident backend work-role paths.
"""
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_RD_JS = _ROOT / "frontend" / "js" / "lib" / "run-detail-view.js"


def _src() -> str:
    assert _RD_JS.exists(), f"missing {_RD_JS}"
    return _RD_JS.read_text()


def test_extract_interval_set_helper_is_gone():
    src = _src()
    assert "function extractIntervalSet" not in src
    assert "extractIntervalSet(" not in src


def test_interval_set_still_uses_manual_work_laps():
    src = _src()
    assert "manualWorkLapsForInterval" in src
    assert "5b Interval set" in src


def test_confident_backend_work_roles_still_qualify():
    src = _src()
    assert "detected.confident" in src
    assert 'role === "work"' in src
    # Fallback is gated on the detected profile, not auto km anomalies.
    assert "detected &&" in src
    assert "detected.confident" in src
