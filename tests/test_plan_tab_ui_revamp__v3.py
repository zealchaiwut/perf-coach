"""Plan tab UI revamp (Next-up / gutter / compact meta) — static contract tests."""
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
JS = (REPO / "frontend" / "js" / "training-plan.js").read_text(encoding="utf-8")
PAGE = (REPO / "frontend" / "pages" / "training-log.html").read_text(encoding="utf-8")


def test_session_display_name_never_untitled():
    assert "function _sessionDisplayName" in JS
    assert "p.name || '(untitled)'" not in JS
    # Card uses display-name helper, not raw empty name.
    card = JS[JS.find("function _plannedCardHtml") : JS.find("function _confirmDeleteSession")]
    assert "_sessionDisplayName(p)" in card
    assert "(untitled)" not in card


def test_session_compact_meta_collapses_tss_noise():
    assert "function _sessionCompactMeta" in JS
    assert "planned " in JS and " → " in JS
    card = JS[JS.find("function _plannedCardHtml") : JS.find("function _confirmDeleteSession")]
    assert "_sessionCompactMeta(p)" in card
    assert "→ Actual" not in card
    assert "_sessionTssBadge(p)" not in card


def test_next_up_hero_host_and_render():
    assert 'id="plan-next-up"' in PAGE
    assert "function _renderNextUp" in JS
    assert "function _pickNextUp" in JS
    assert "function _loadNextUpRange" in JS


def test_responsive_grid_single_template():
    assert "pl-v3-grid" in PAGE
    assert "pl-v3-chart" in PAGE
    assert "pl-v3-side" in PAGE
    assert "pl-v3-week" in PAGE
    # Single column stack (no desktop sidebar grid).
    assert "flex-direction:column" in JS
    assert 'grid-template-areas:\\"chart side\\"' not in JS
    # One plan panel — not a forked mobile page.
    assert PAGE.count('id="training-panel-plan"') == 1


def test_week_list_gutter_dates():
    assert "pl-gut" in JS
    assert "pl-gut-dw" in JS
    assert "pl-gut-dn" in JS
    assert "rest day" in JS
    assert "pl-daylabel" not in JS[JS.find("function _renderWeekList") : JS.find("function _sessionTss")]


def test_mobile_chart_window_helpers():
    assert "function _isMobilePlanLayout" in JS
    assert "is-windowed" in JS
    assert "function _mobileAheadChips" in JS
    assert "Full season chart" in JS
    assert "function _phaseStripHtml" in JS


def test_cache_bust_bumped():
    assert "training-plan.js?v=20260810phaseb1" in PAGE
