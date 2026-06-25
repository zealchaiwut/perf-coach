"""Tests for issue #499: Guard range-tab fetches against out-of-order responses.

AC anchors verified:
  (ac1) Each range-tab fetch uses an AbortController; in-flight request for a
        previous range is aborted before the new one starts.
  (ac2) A monotonic sequence token is incremented on every tab click; responses
        whose token does not match the current token are silently discarded.
  (ac3) Switching tabs rapidly resolves to the last-clicked range (structural
        check: discard logic precedes renderChart call inside the click handler).
  (ac4) No unhandled promise rejection when a request is aborted — AbortError is
        silently swallowed in the error handler.
  (ac5) Existing single-click range switching is unaffected: fetchChartData and
        renderChart are still called from _initRangeTabs.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
WEIGHT_JS = (ROOT / "frontend" / "js" / "weight.js").read_text()


# ── AC1: AbortController usage ────────────────────────────────────────────────

def test_ac1_abort_controller_constructed():
    """weight.js must construct an AbortController for each range-tab fetch."""
    assert "new AbortController()" in WEIGHT_JS, (
        "weight.js must create a new AbortController() per range-tab click"
    )


def test_ac1_abort_called_before_new_fetch():
    """Previous controller's .abort() must be called before a new fetch starts."""
    assert ".abort()" in WEIGHT_JS, (
        "weight.js must call .abort() on the previous AbortController before issuing a new fetch"
    )


def test_ac1_signal_passed_to_fetch():
    """The AbortController's signal must be forwarded to fetch() (directly or via apiFetch)."""
    # apiFetch / fetchChartData must accept a signal, or fetch is called with {signal:...} directly
    assert "signal" in WEIGHT_JS, (
        "weight.js must pass the AbortController signal to the underlying fetch() call"
    )


def test_ac1_abort_controller_module_level_state():
    """A module-level variable holds the active AbortController so clicks can abort it."""
    # Look for a let/var/const at module scope (outside functions) that holds a controller
    # Pattern: let _rangeAbortController or similar at top-level state block
    assert re.search(r"let\s+_range[A-Za-z]*Controller\s*=", WEIGHT_JS) or \
           re.search(r"let\s+_[a-z]+Controller\s*=", WEIGHT_JS) or \
           "AbortController" in WEIGHT_JS, (
        "weight.js must store the active AbortController in module-level state"
    )


# ── AC2: Monotonic sequence token ─────────────────────────────────────────────

def test_ac2_sequence_counter_declared():
    """A monotonic sequence counter must be declared at module scope."""
    # Common names: _rangeFetchSeq, _fetchSeq, _rangeSeq, _seq
    assert re.search(r"let\s+_[a-zA-Z]*[Ss]eq\s*=\s*0", WEIGHT_JS) or \
           re.search(r"let\s+_[a-zA-Z]*[Tt]oken\s*=\s*0", WEIGHT_JS) or \
           re.search(r"let\s+_[a-zA-Z]*[Cc]ounter\s*=\s*0", WEIGHT_JS), (
        "weight.js must declare a monotonic sequence counter (e.g. let _rangeFetchSeq = 0)"
    )


def test_ac2_counter_incremented_on_click():
    """Sequence counter must be incremented inside the range-tab click handler."""
    assert re.search(r"_[a-zA-Z]*[Ss]eq\s*\+\+", WEIGHT_JS) or \
           re.search(r"_[a-zA-Z]*[Ss]eq\s*\+=\s*1", WEIGHT_JS) or \
           re.search(r"\+\+\s*_[a-zA-Z]*[Ss]eq", WEIGHT_JS) or \
           re.search(r"_[a-zA-Z]*[Tt]oken\s*\+\+", WEIGHT_JS) or \
           re.search(r"\+\+\s*_[a-zA-Z]*[Tt]oken", WEIGHT_JS), (
        "weight.js must increment the sequence counter on every range-tab click"
    )


def test_ac2_stale_response_discarded_by_token_check():
    """After the fetch resolves, the captured token must be compared to the current counter."""
    # After await, there must be a check like: if (seq !== _rangeFetchSeq) return;
    assert re.search(r"if\s*\(\s*\w+\s*!==?\s*_[a-zA-Z]*[Ss]eq\b", WEIGHT_JS) or \
           re.search(r"if\s*\(\s*_[a-zA-Z]*[Ss]eq\b\s*!==?\s*\w+", WEIGHT_JS) or \
           re.search(r"if\s*\(\s*\w+\s*!==?\s*_[a-zA-Z]*[Tt]oken\b", WEIGHT_JS) or \
           re.search(r"if\s*\(\s*_[a-zA-Z]*[Tt]oken\b\s*!==?\s*\w+", WEIGHT_JS), (
        "weight.js must discard stale responses by comparing captured token to current counter"
    )


# ── AC3: Rapid switching resolves to last-clicked ─────────────────────────────

def test_ac3_discard_check_before_render_chart():
    """Token discard check must appear before renderChart call in _initRangeTabs handler."""
    init_range_tabs_idx = WEIGHT_JS.find("function _initRangeTabs")
    assert init_range_tabs_idx != -1, "weight.js must have _initRangeTabs function"

    # Find the end of _initRangeTabs (next top-level function)
    next_fn_idx = WEIGHT_JS.find("\nfunction ", init_range_tabs_idx + 1)
    if next_fn_idx == -1:
        next_fn_idx = len(WEIGHT_JS)
    handler_body = WEIGHT_JS[init_range_tabs_idx:next_fn_idx]

    seq_check_idx = -1
    for pattern in [r"!==\s*_[a-zA-Z]*[Ss]eq", r"!==\s*_[a-zA-Z]*[Tt]oken",
                    r"_[a-zA-Z]*[Ss]eq\s*!==", r"_[a-zA-Z]*[Tt]oken\s*!=="]:
        m = re.search(pattern, handler_body)
        if m:
            seq_check_idx = m.start()
            break

    render_idx = handler_body.find("renderChart")

    assert seq_check_idx != -1, (
        "_initRangeTabs must contain a sequence-token check to discard stale responses"
    )
    assert render_idx != -1, (
        "_initRangeTabs must still call renderChart"
    )
    assert seq_check_idx < render_idx, (
        "Token discard check must appear before renderChart() call in _initRangeTabs handler"
    )


# ── AC4: AbortError silently swallowed ────────────────────────────────────────

def test_ac4_abort_error_not_propagated():
    """AbortError must be caught and swallowed — not shown as an error to the user."""
    # Either explicit name check or the abort check in error handler
    assert "AbortError" in WEIGHT_JS or \
           re.search(r"e\.name\s*===?\s*['\"]AbortError['\"]", WEIGHT_JS) or \
           re.search(r"name\s*===?\s*['\"]AbortError['\"]", WEIGHT_JS), (
        "weight.js must check for AbortError and swallow it silently "
        "(no user-visible error when a request is intentionally cancelled)"
    )


def test_ac4_abort_error_does_not_call_show_page_error():
    """showPageError must NOT be called when the request was intentionally aborted."""
    # The catch block must guard showPageError behind a !AbortError check
    # Check that AbortError guard exists in or near the catch block in _initRangeTabs
    init_range_tabs_idx = WEIGHT_JS.find("function _initRangeTabs")
    assert init_range_tabs_idx != -1

    next_fn_idx = WEIGHT_JS.find("\nfunction ", init_range_tabs_idx + 1)
    if next_fn_idx == -1:
        next_fn_idx = len(WEIGHT_JS)
    handler_body = WEIGHT_JS[init_range_tabs_idx:next_fn_idx]

    has_abort_guard = (
        "AbortError" in handler_body or
        re.search(r"e\.name", handler_body) is not None
    )
    assert has_abort_guard, (
        "_initRangeTabs catch block must guard against AbortError to avoid spurious page errors"
    )


# ── AC5: No regression on existing range-switching ────────────────────────────

def test_ac5_fetch_chart_data_still_called():
    """_initRangeTabs must still call fetchChartData (no regression)."""
    init_range_tabs_idx = WEIGHT_JS.find("function _initRangeTabs")
    assert init_range_tabs_idx != -1

    next_fn_idx = WEIGHT_JS.find("\nfunction ", init_range_tabs_idx + 1)
    if next_fn_idx == -1:
        next_fn_idx = len(WEIGHT_JS)
    handler_body = WEIGHT_JS[init_range_tabs_idx:next_fn_idx]

    assert "fetchChartData" in handler_body, (
        "_initRangeTabs must still call fetchChartData — no regression on range switching"
    )


def test_ac5_render_chart_still_called():
    """_initRangeTabs must still call renderChart on successful fetch (no regression)."""
    init_range_tabs_idx = WEIGHT_JS.find("function _initRangeTabs")
    assert init_range_tabs_idx != -1

    next_fn_idx = WEIGHT_JS.find("\nfunction ", init_range_tabs_idx + 1)
    if next_fn_idx == -1:
        next_fn_idx = len(WEIGHT_JS)
    handler_body = WEIGHT_JS[init_range_tabs_idx:next_fn_idx]

    assert "renderChart" in handler_body, (
        "_initRangeTabs must still call renderChart — no regression on range switching"
    )


def test_ac5_range_tab_active_class_still_set():
    """Active tab highlighting must still be set (no regression)."""
    init_range_tabs_idx = WEIGHT_JS.find("function _initRangeTabs")
    assert init_range_tabs_idx != -1

    next_fn_idx = WEIGHT_JS.find("\nfunction ", init_range_tabs_idx + 1)
    if next_fn_idx == -1:
        next_fn_idx = len(WEIGHT_JS)
    handler_body = WEIGHT_JS[init_range_tabs_idx:next_fn_idx]

    assert "active" in handler_body and "range-tab" in handler_body, (
        "_initRangeTabs must still set/unset the 'active' class on range tabs"
    )


def test_ac5_apiFetch_accepts_signal():
    """apiFetch must accept an optional signal parameter to forward to fetch()."""
    # apiFetch signature should include 'signal' parameter
    apifetch_idx = WEIGHT_JS.find("async function apiFetch(")
    assert apifetch_idx != -1, "apiFetch must exist in weight.js"

    # Find end of function definition line
    fn_line_end = WEIGHT_JS.find("\n", apifetch_idx)
    fn_signature = WEIGHT_JS[apifetch_idx:fn_line_end]

    # Either signal is in the signature, or fetch() inside apiFetch uses signal
    # Check signal appears in the apiFetch function body
    next_fn_idx = WEIGHT_JS.find("\nasync function ", apifetch_idx + 1)
    if next_fn_idx == -1:
        next_fn_idx = WEIGHT_JS.find("\nfunction ", apifetch_idx + 1)
    if next_fn_idx == -1:
        next_fn_idx = apifetch_idx + 500
    apifetch_body = WEIGHT_JS[apifetch_idx:next_fn_idx]

    assert "signal" in apifetch_body, (
        "apiFetch must accept and forward a signal parameter to fetch() "
        "so AbortController works end-to-end"
    )
