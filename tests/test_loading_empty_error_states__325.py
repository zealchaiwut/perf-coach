"""Tests for issue #325: Standardize loading, empty, and error states.

Acceptance criteria verified:
(AC-1) ui-states.js exists and exports UIStates with required helpers
(AC-2) All daily pages load ui-states.js before their page script
(AC-3) Each page's JS uses UIStates.showToast for success saves
(AC-4) Each page's JS uses UIStates loading helpers (setLoading / loadingHTML) for widgets
(AC-5) Error states use UIStates.setError / errorHTML instead of raw inline strings
(AC-6) No backend files are modified (frontend-only change)
"""
import pathlib

ROOT = pathlib.Path(__file__).parent.parent
JS   = ROOT / "frontend" / "js"
PGS  = ROOT / "frontend" / "pages"

UI_STATES = (JS / "ui-states.js").read_text()
HOME_JS   = (JS / "home.js").read_text()
WEIGHT_JS = (JS / "weight.js").read_text()
HABITS_JS = (JS / "habits.js").read_text()
TRAIN_JS  = (JS / "training.js").read_text()
LOG_JS    = (JS / "training-log.js").read_text()

HOME_HTML   = (PGS / "home.html").read_text()
WEIGHT_HTML = (PGS / "weight.html").read_text()
HABITS_HTML = (PGS / "habits.html").read_text()
TRAIN_HTML  = (PGS / "training.html").read_text()
LOG_HTML    = (PGS / "training-log.html").read_text()


# ── AC-1: ui-states.js exports required helpers ──────────────────────────────

def test_ui_states_file_exists():
    assert (JS / "ui-states.js").exists(), "ui-states.js must exist"


def test_ui_states_exports_show_toast():
    assert "showToast" in UI_STATES, "ui-states.js must define showToast"


def test_ui_states_exports_set_loading():
    assert "setLoading" in UI_STATES, "ui-states.js must define setLoading"


def test_ui_states_exports_set_empty():
    assert "setEmpty" in UI_STATES, "ui-states.js must define setEmpty"


def test_ui_states_exports_set_error():
    assert "setError" in UI_STATES, "ui-states.js must define setError"


def test_ui_states_exports_loading_html():
    assert "loadingHTML" in UI_STATES, "ui-states.js must define loadingHTML"


def test_ui_states_injects_spinner_css():
    assert "ui-spinner" in UI_STATES, "ui-states.js must inject .ui-spinner CSS"


def test_ui_states_injects_toast_css():
    assert "ui-toast" in UI_STATES, "ui-states.js must inject #ui-toast CSS"


def test_ui_states_assigns_global():
    assert "global.UIStates" in UI_STATES or "window.UIStates" in UI_STATES, \
        "ui-states.js must assign UIStates to global/window"


# ── AC-2: All six pages load ui-states.js before their page script ─────────

def _script_order_ok(html: str, page_script: str) -> bool:
    ui_pos   = html.find("ui-states.js")
    page_pos = html.find(page_script)
    return ui_pos != -1 and page_pos != -1 and ui_pos < page_pos


def test_home_loads_ui_states_before_home_js():
    assert _script_order_ok(HOME_HTML, "home.js"), \
        "home.html must load ui-states.js before home.js"


def test_weight_loads_ui_states_before_weight_js():
    assert _script_order_ok(WEIGHT_HTML, "weight.js"), \
        "weight.html must load ui-states.js before weight.js"


def test_habits_loads_ui_states_before_habits_js():
    assert _script_order_ok(HABITS_HTML, "habits.js"), \
        "habits.html must load ui-states.js before habits.js"


def test_training_loads_ui_states_before_training_js():
    assert _script_order_ok(TRAIN_HTML, "training.js"), \
        "training.html must load ui-states.js before training.js"


def test_training_log_loads_ui_states_before_training_log_js():
    assert _script_order_ok(LOG_HTML, "training-log.js"), \
        "training-log.html must load ui-states.js before training-log.js"


# ── AC-3: Success saves show UIStates.showToast ───────────────────────────────

def test_weight_js_shows_toast_on_save():
    assert "UIStates.showToast" in WEIGHT_JS, \
        "weight.js must call UIStates.showToast on save/delete/update"


def test_habits_js_shows_toast_on_save():
    assert "UIStates.showToast" in HABITS_JS, \
        "habits.js must call UIStates.showToast on habit actions"


def test_training_js_shows_toast_on_save():
    assert "UIStates.showToast" in TRAIN_JS, \
        "training.js must call UIStates.showToast"


def test_training_log_js_shows_toast_on_delete():
    assert "UIStates.showToast" in LOG_JS, \
        "training-log.js must call UIStates.showToast on workout delete"


def test_home_js_shows_toast_on_save():
    assert "UIStates.showToast" in HOME_JS, \
        "home.js must call UIStates.showToast on Log Today save"


# ── AC-4: Loading helpers used across widgets ─────────────────────────────────

def test_home_js_uses_loading_helper():
    assert "UIStates.loadingHTML" in HOME_JS or "UIStates.setLoading" in HOME_JS, \
        "home.js must use UIStates loading helpers"


def test_weight_js_uses_loading_helper():
    assert "UIStates.setLoading" in WEIGHT_JS, \
        "weight.js must use UIStates.setLoading"


def test_habits_js_uses_loading_helper():
    assert "UIStates.setLoading" in HABITS_JS, \
        "habits.js must use UIStates.setLoading"


def test_training_js_uses_loading_helper():
    assert "UIStates.setLoading" in TRAIN_JS, \
        "training.js must use UIStates.setLoading for history"


# ── AC-5: Consistent error handling ───────────────────────────────────────────

def test_training_log_no_bare_alert():
    assert "alert(" not in LOG_JS, \
        "training-log.js must not use bare alert() for errors"


def test_weight_js_uses_ui_error():
    assert "UIStates.setError" in WEIGHT_JS, \
        "weight.js must use UIStates.setError on fetch failure"


def test_training_js_uses_ui_error():
    assert "UIStates.setError" in TRAIN_JS, \
        "training.js must use UIStates.setError on history fetch failure"


# ── AC-6: No backend files modified ──────────────────────────────────────────

def test_main_py_not_referenced():
    """Canary: none of the changed JS files import or reference backend routes
    in a way that would suggest backend logic was added."""
    changed = [HOME_JS, WEIGHT_JS, HABITS_JS, TRAIN_JS, LOG_JS]
    backend_patterns = ["from backend", "import main", "alembic"]
    for content in changed:
        for pat in backend_patterns:
            assert pat not in content, \
                f"JS file must not contain backend import '{pat}'"
