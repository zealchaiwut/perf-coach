"""Static contracts: readiness used_signals copy + Log Today scored vs logged."""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOME_HTML = (ROOT / "frontend" / "pages" / "home.html").read_text()
RD_JS = (ROOT / "frontend" / "js" / "home-readiness-training-sleep.js").read_text()
MAIN = (ROOT / "backend" / "main.py").read_text()


def test_readiness_block_exposes_used_signals():
    assert '"used_signals"' in MAIN
    assert "sorted(raw.keys())" in MAIN


def test_tile_renders_partial_signal_note():
    assert "_rdUsedSignalsNote" in RD_JS
    assert "HRV needs 2 prior days" in RD_JS
    assert "rd-tile-signals" in RD_JS


def test_fast_log_states_what_is_scored():
    assert "Score uses HRV, RHR, sleep quality, and energy" in HOME_HTML
    assert "(in score)" in HOME_HTML
    assert "(logged, not scored)" in HOME_HTML
