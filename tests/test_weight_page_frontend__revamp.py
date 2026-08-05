"""Weight tab revamp — frontend static assertions (passes 2–6)."""
from pathlib import Path
import subprocess
import json
import textwrap

ROOT = Path(__file__).resolve().parent.parent
WEIGHT_HTML = (ROOT / "frontend/pages/weight.html").read_text()
WEIGHT_JS = (ROOT / "frontend/js/weight.js").read_text()
TIMELINE_JS = (ROOT / "frontend/js/weight-timeline.js").read_text()


def test_no_compute_streak_in_weight_js():
    assert "_computeStreak" not in WEIGHT_JS


def test_gate_unlock_copy_present():
    assert "gate-card" in WEIGHT_HTML
    assert "UNLOCKS AT 70% COVERAGE" in WEIGHT_HTML
    assert "renderCoverageGating" in WEIGHT_JS


def test_progress_card_hidden():
    assert 'id="progress-card" hidden' in WEIGHT_HTML or "#progress-card" in (ROOT / "frontend/css/weight.css").read_text()


def test_legacy_chart_p2w_and_target_history_hidden():
    """Visible Basic/Advanced chart, power-to-weight, and target history are retired."""
    assert 'id="legacy-chart-card" hidden' in WEIGHT_HTML
    assert 'id="p2w-card" hidden' in WEIGHT_HTML
    assert 'id="target-history-section"' in WEIGHT_HTML
    assert " hidden" in WEIGHT_HTML[
        WEIGHT_HTML.find('id="target-history-section"'):
        WEIGHT_HTML.find('id="target-history-section"') + 90
    ]
    # Visible heading copy must not reappear outside CSS comments
    body = WEIGHT_HTML.split("<body", 1)[-1]
    assert "Target history" not in body
    assert "Power-to-weight" not in body
    assert "Your weight journey" not in body


def test_one_rate_uses_stats_rate():
    assert "stats.rate" in WEIGHT_JS or "stats && stats.rate" in WEIGHT_JS
    assert "rate.rate_kg_wk" in WEIGHT_JS or "rate_kg_wk" in WEIGHT_JS
    assert "renderRateCard" in WEIGHT_JS


def test_hypothesis_card_wired():
    assert "hypothesis-card" in WEIGHT_HTML
    assert "/api/weight-hypothesis" in WEIGHT_JS


def test_timeline_domain_helper():
    script = textwrap.dedent(f"""
        {TIMELINE_JS}
        const d = WeightTimeline.timelineDomain([89.0, 88.5, 88.0]);
        console.log(JSON.stringify(d));
    """)
    result = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    parsed = json.loads(result.stdout.strip())
    assert parsed["lo"] <= 88.0
    assert parsed["hi"] >= 89.0
