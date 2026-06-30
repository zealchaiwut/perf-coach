"""Tests for issue #1059: Show monthly review panel on Plan tab.

AC items tested:
  AC1 - Plan tab displays a "This Month" review panel fetching from the monthly summary endpoint.
  AC2 - Panel renders score changes, weight change, fitness change, form change as chips.
  AC3 - Panel displays the current supercompensation state.
  AC4 - Panel includes a call-to-action matching the Log digest.
  AC5 - Panel reads the athlete's upcoming race/checkpoint and shows name in heading/subheading.
  AC6 - Panel contains a note about being the same review shown in the Log digest, with a
        tappable link that navigates to the Log tab.
  AC7 - Panel does not appear if no monthly summary data is available (hidden by default).
  AC8 - Panel does not appear if no upcoming checkpoint or race is found (hidden by JS).
"""
import os
import re
import pytest


@pytest.fixture(scope="module")
def html():
    p = os.path.join(os.path.dirname(__file__), "../frontend/pages/training-log.html")
    with open(p, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def plan_js():
    p = os.path.join(os.path.dirname(__file__), "../frontend/js/training-plan.js")
    with open(p, encoding="utf-8") as f:
        return f.read()


def _plan_panel(html):
    """Extract Plan panel HTML."""
    start = html.find('id="training-panel-plan"')
    assert start != -1, "training-panel-plan must exist in the page"
    perf_start = html.find('id="training-panel-performance"', start)
    end = perf_start if perf_start != -1 else start + 40000
    return html[start:end]


# ── AC1: Monthly review panel element exists in Plan tab ──────────────────────

def test_monthly_review_panel_exists_in_plan_tab(html):
    """AC1: A monthly review panel element is present inside the Plan tab panel."""
    panel = _plan_panel(html)
    assert "plan-monthly-review" in panel, \
        "plan-monthly-review element must be present in the Plan tab panel"


def test_monthly_review_panel_has_this_month_heading(html):
    """AC1: The monthly review panel has a 'This Month' heading or label."""
    panel = _plan_panel(html)
    assert "This Month" in panel, \
        "Plan monthly review panel must contain 'This Month' heading/label"


def test_js_fetches_monthly_summary_endpoint(plan_js):
    """AC1: training-plan.js fetches from the monthly summary API endpoint."""
    assert "summary/monthly" in plan_js, \
        "training-plan.js must fetch from /summary/monthly endpoint"


# ── AC2: Score change chips ───────────────────────────────────────────────────

def test_js_renders_endurance_score_chip(plan_js):
    """AC2: JS renders an endurance score change chip."""
    assert "endurance_score_change" in plan_js, \
        "JS must reference endurance_score_change from the monthly summary response"


def test_js_renders_speed_score_chip(plan_js):
    """AC2: JS renders a speed score change chip."""
    assert "speed_score_change" in plan_js, \
        "JS must reference speed_score_change from the monthly summary response"


def test_js_renders_weight_change_chip(plan_js):
    """AC2: JS renders a weight change chip."""
    assert "weight_change_kg" in plan_js, \
        "JS must reference weight_change_kg from the monthly summary response"


def test_js_renders_fitness_change_chip(plan_js):
    """AC2: JS renders a fitness (CTL) change chip."""
    assert "fitness_ctl_change" in plan_js, \
        "JS must reference fitness_ctl_change from the monthly summary response"


def test_js_renders_form_change_chip(plan_js):
    """AC2: JS renders a form change (form_recovered) chip."""
    assert "form_recovered" in plan_js, \
        "JS must reference form_recovered from the monthly summary response"


def test_plan_monthly_review_has_chip_container(html):
    """AC2: The monthly review panel has a chip container for metric deltas."""
    panel = _plan_panel(html)
    assert "plan-month-chips" in panel or "month-chip" in panel or "plan-monthly-chips" in panel, \
        "Plan monthly review panel must have a chip container element"


# ── AC3: Supercompensation state ──────────────────────────────────────────────

def test_js_renders_supercompensation_state(plan_js):
    """AC3: JS renders the supercompensation_state from the monthly summary."""
    assert "supercompensation_state" in plan_js, \
        "JS must reference supercompensation_state from the monthly summary response"


def test_plan_monthly_review_has_supercomp_element(html):
    """AC3: The monthly review panel has an element for the supercompensation state."""
    panel = _plan_panel(html)
    assert "plan-month-supercomp" in panel or "supercomp" in panel, \
        "Plan monthly review panel must have a supercompensation state element"


# ── AC4: Call-to-action ───────────────────────────────────────────────────────

def test_js_renders_call_to_action(plan_js):
    """AC4: JS renders the call_to_action from the monthly summary response."""
    assert "call_to_action" in plan_js, \
        "JS must reference call_to_action from the monthly summary response"


def test_plan_monthly_review_has_cta_element(html):
    """AC4: The monthly review panel has a CTA element."""
    panel = _plan_panel(html)
    assert "plan-month-cta" in panel or "month-cta" in panel, \
        "Plan monthly review panel must have a CTA element"


# ── AC5: Checkpoint name in heading ──────────────────────────────────────────

def test_js_reads_next_checkpoint_name(plan_js):
    """AC5: JS reads the next_checkpoint name from the monthly summary response."""
    assert "next_checkpoint" in plan_js, \
        "JS must reference next_checkpoint from the monthly summary response"


def test_plan_monthly_review_has_checkpoint_name_element(html):
    """AC5: A element in the monthly review panel is populated with the checkpoint name."""
    panel = _plan_panel(html)
    assert "plan-month-checkpoint" in panel or "plan-month-heading" in panel, \
        "Plan monthly review panel must have an element for the checkpoint/race name"


# ── AC6: Link to Log tab ─────────────────────────────────────────────────────

def test_js_has_log_tab_link(plan_js):
    """AC6: JS renders a link or button that navigates to the Log tab."""
    # Should reference 'log' tab navigation
    assert (
        "data-tab=\"log\"" in plan_js
        or 'data-tab=\'log\'' in plan_js
        or "switchToLog" in plan_js
        or '"log"' in plan_js
    ), "JS must include a link or action that navigates to the Log tab"


def test_plan_monthly_review_has_log_link_element(html):
    """AC6: The monthly review panel contains a note referencing the Log digest with a link."""
    panel = _plan_panel(html)
    assert "plan-month-log-link" in panel or "log-digest" in panel or "plan-month-note" in panel, \
        "Plan monthly review panel must contain a note/link element referencing the Log tab"


def test_plan_monthly_review_log_link_triggers_log_tab(plan_js):
    """AC6: JS wires the log-link element to navigate to the Log tab."""
    assert "log" in plan_js and (
        "data-tab" in plan_js or "click" in plan_js
    ), "JS must wire a click handler to navigate to the Log tab"


# ── AC7: Panel hidden by default ─────────────────────────────────────────────

def test_monthly_review_panel_hidden_by_default(html):
    """AC7: The monthly review panel is hidden by default (not shown without data)."""
    panel = _plan_panel(html)
    # Find the monthly review container and check it has hidden or display:none
    idx = panel.find("plan-monthly-review")
    assert idx != -1, "plan-monthly-review element must exist"
    surrounding = panel[max(0, idx - 50):idx + 200]
    assert "hidden" in surrounding or "display:none" in surrounding or 'display: none' in surrounding, \
        "plan-monthly-review must be hidden by default (hidden attr or display:none)"


# ── AC8: Panel hidden when no checkpoint found ────────────────────────────────

def test_js_hides_panel_when_no_next_checkpoint(plan_js):
    """AC8: JS hides the monthly review panel when next_checkpoint is null/absent."""
    assert (
        "next_checkpoint" in plan_js
        and ("hidden" in plan_js or "display" in plan_js or "style" in plan_js)
    ), "JS must check next_checkpoint and hide the panel when it is null"


def test_js_hides_panel_on_424_or_error(plan_js):
    """AC7/AC8: JS hides the monthly review panel when the API returns an error (no data)."""
    # JS should catch errors / non-ok responses and keep the panel hidden
    assert (
        "424" in plan_js
        or ("catch" in plan_js and "monthly" in plan_js)
        or ("!r.ok" in plan_js and "monthly" in plan_js)
        or ("null" in plan_js and "summary/monthly" in plan_js)
    ), "JS must handle 424/error response and keep the monthly review panel hidden"
