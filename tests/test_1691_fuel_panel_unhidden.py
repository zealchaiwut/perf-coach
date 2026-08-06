"""
Issue #1691 — Fuel food-logging panel wrapped in hidden markup.

Acceptance criteria verified here:
AC1. The <div hidden aria-hidden="true"> wrapper that was hiding the entire fuel
     settings/food-log section is removed; those elements must NOT have a hidden
     ancestor inside #fuel-today-card.
AC2. The interactive fuel elements (#fuel-settings-toggle, #fuel-calibrate-btn,
     .fuel-stepper-btn, .fuel-stepper-input, #fuel-calibrate-btn) are present in
     the markup AND are not inside any element with the `hidden` attribute.
AC3. cut_review coaching copy continues to reference "Calibrate from history" —
     it now points to a reachable control, so the text stays correct.
"""

import pathlib
import re
from html.parser import HTMLParser


WEIGHT_HTML = (
    pathlib.Path(__file__).parent.parent / "frontend" / "pages" / "weight.html"
)


class _PermanentlyHiddenChecker(HTMLParser):
    """Walk the HTML tree; collect ids/classes inside a *permanently* hidden
    ancestor — defined as an element with BOTH `hidden` AND `aria-hidden="true"`.

    Elements inside togglable panels (which carry only `hidden`, no
    `aria-hidden`) are intentionally excluded: `#fuel-settings-panel` is hidden
    by default and opened by the cog button, which is the correct pattern.
    """

    def __init__(self):
        super().__init__()
        self._stack = []
        self.hidden_ids = set()
        self.hidden_classes = set()
        self._void = {
            "area", "base", "br", "col", "embed", "hr", "img", "input",
            "link", "meta", "param", "source", "track", "wbr",
        }

    def _is_permanently_hidden_ancestor(self):
        return any(flags == {"perm_hidden"} for _, flags in self._stack)

    def handle_starttag(self, tag, attrs):
        attr_dict = {k: (v or "") for k, v in attrs}
        has_hidden = "hidden" in attr_dict
        has_aria_hidden = attr_dict.get("aria-hidden") == "true"
        is_perm_hidden = has_hidden and has_aria_hidden
        if tag not in self._void:
            self._stack.append((tag, {"perm_hidden"} if is_perm_hidden else set()))

        if self._is_permanently_hidden_ancestor():
            eid = attr_dict.get("id", "")
            if eid:
                self.hidden_ids.add(eid)
            for cls in attr_dict.get("class", "").split():
                self.hidden_classes.add(cls)

    def handle_endtag(self, tag):
        if tag in self._void:
            return
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i][0] == tag:
                self._stack.pop(i)
                break


def _parse_weight_html():
    checker = _PermanentlyHiddenChecker()
    checker.feed(WEIGHT_HTML.read_text(encoding="utf-8"))
    return checker


# ---------------------------------------------------------------------------
# AC1 — no broad hidden wrapper swallowing the fuel section
# ---------------------------------------------------------------------------

def test_fuel_settings_toggle_not_inside_hidden_ancestor():
    """AC1/AC2: #fuel-settings-toggle must not be inside a hidden element."""
    c = _parse_weight_html()
    assert "fuel-settings-toggle" not in c.hidden_ids, (
        "#fuel-settings-toggle is inside a hidden ancestor — the cog button "
        "is inaccessible to users"
    )


def test_fuel_calibrate_btn_not_inside_hidden_ancestor():
    """AC1/AC2: #fuel-calibrate-btn (Calibrate from history) must be accessible."""
    c = _parse_weight_html()
    assert "fuel-calibrate-btn" not in c.hidden_ids, (
        "#fuel-calibrate-btn is inside a hidden ancestor — users cannot "
        "trigger 'Calibrate from history'"
    )


def test_fuel_stepper_inputs_not_inside_hidden_ancestor():
    """AC2: .fuel-stepper-input elements must not be inside a hidden ancestor."""
    c = _parse_weight_html()
    assert "fuel-stepper-input" not in c.hidden_classes, (
        ".fuel-stepper-input is inside a hidden ancestor — food quantity "
        "steppers are inaccessible"
    )


def test_fuel_stepper_btns_not_inside_hidden_ancestor():
    """AC2: .fuel-stepper-btn elements must not be inside a hidden ancestor."""
    c = _parse_weight_html()
    assert "fuel-stepper-btn" not in c.hidden_classes, (
        ".fuel-stepper-btn is inside a hidden ancestor"
    )


def test_fuel_meat_g_input_present_and_accessible():
    """AC2: #fuel-meat_g must exist and not be inside a hidden wrapper."""
    c = _parse_weight_html()
    assert "fuel-meat_g" not in c.hidden_ids


def test_fuel_rice_g_input_present_and_accessible():
    """AC2: #fuel-rice_g must exist and not be inside a hidden wrapper."""
    c = _parse_weight_html()
    assert "fuel-rice_g" not in c.hidden_ids


def test_fuel_eggs_input_present_and_accessible():
    """AC2: #fuel-eggs must exist and not be inside a hidden wrapper."""
    c = _parse_weight_html()
    assert "fuel-eggs" not in c.hidden_ids


def test_fuel_fruit_g_input_present_and_accessible():
    """AC2: #fuel-fruit_g must exist and not be inside a hidden wrapper."""
    c = _parse_weight_html()
    assert "fuel-fruit_g" not in c.hidden_ids


def test_fuel_oil_tsp_input_present_and_accessible():
    """AC2: #fuel-oil_tsp must exist and not be inside a hidden wrapper."""
    c = _parse_weight_html()
    assert "fuel-oil_tsp" not in c.hidden_ids


# ---------------------------------------------------------------------------
# AC3 — coaching copy still references the (now reachable) Calibrate control
# ---------------------------------------------------------------------------

def _cut_review_call(**overrides):
    from backend.services.cut_review import compute_cut_recommendation

    defaults = dict(
        weigh_in_count_14d=10,
        has_active_plan=True,
        actual_rate_kg_per_week=0.0,
        plan_rate_kg_per_week=-0.5,
        weekly_pct_bw_rate=0.0,
        ea_proxy=0.8,
        logging_adherence_pct=0.9,
        avg_intake_vs_budget_kcal=-50.0,
        pct_logged_days_at_or_under_budget=0.9,
        consecutive_weeks_behind=0,
        current_deficit_kcal=300,
        plateau_days=0,
    )
    defaults.update(overrides)
    return compute_cut_recommendation(**defaults)


def test_cut_review_plateau_action_references_calibrate():
    """AC3: plateau action text references 'Calibrate from history'."""
    result = _cut_review_call(plateau_days=21)
    assert result["recommendation"] == "plateau"
    assert "Calibrate from history" in result["action"], (
        "Plateau coaching copy must still mention 'Calibrate from history' "
        "now that the control is accessible"
    )


def test_cut_review_recalibrate_action_references_calibrate():
    """AC3: recalibrate_maintenance action text references 'Calibrate from history'."""
    result = _cut_review_call(consecutive_weeks_behind=4)
    assert result["recommendation"] == "recalibrate_maintenance"
    assert "Calibrate from history" in result["action"], (
        "recalibrate_maintenance coaching copy must still mention "
        "'Calibrate from history' now that the control is accessible"
    )
