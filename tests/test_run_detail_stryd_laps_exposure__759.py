"""Run detail option B: Stryd manual laps exposed on /full sources.stryd.laps."""
import pathlib

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MAIN = _ROOT / "backend" / "main.py"
_RD_JS = _ROOT / "frontend" / "js" / "lib" / "run-detail-view.js"


def test_stryd_source_dict_exposes_laps_from_raw_payload():
    src = _MAIN.read_text()
    assert '"laps":' in src
    assert "raw_payload" in src
    assert 'get("laps")' in src or "['laps']" in src


def test_run_detail_view_has_lap_mode_toggle():
    src = _RD_JS.read_text()
    assert "rd4-lapmode-toggle" in src
    assert "collectManualLapSplits" in src
    assert 'data-lap-mode="manual"' in src


def test_run_detail_view_defaults_tss_to_computed():
    src = _RD_JS.read_text()
    assert "pickDefaultTssId" in src
    assert 'id === "computed"' in src
    assert "rd4-tss-menu" in src
