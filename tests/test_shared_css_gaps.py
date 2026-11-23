"""Prompt 0 — shared revamp.css classes used by Admin / drawers / Performance."""
from pathlib import Path

CSS = Path("frontend/css/revamp.css").read_text(encoding="utf-8")


def test_muted_token_defined():
    assert "--rv-muted: #56627f" in CSS


def test_missing_form_and_drawer_classes_exist():
    for cls in (
        ".rv-input",
        ".rv-field",
        ".rv-card-title",
        ".rv-part-row",
        ".rv-drawer-head",
        ".rv-strength-tiles",
        ".rv-table",
        ".rv-drawer-foot",
        ".rv-effort-row",
        ".rv-form-set",
        ".rv-notes",
        ".rv-btn--small",
        ".rv-chip--due",
        ".rv-chip--muted",
        ".rv-why-stale",
    ):
        assert cls in CSS, cls


def test_small_buttons_are_44px():
    assert ".rv-btn--sm" in CSS
    assert ".rv-btn--small" in CSS
    idx = CSS.find("body.rv-page .rv-btn--small")
    assert idx >= 0
    assert "min-height: 44px" in CSS[idx : idx + 80]


def test_plan_load_bar_defined_once_at_mock_height():
    assert CSS.count("body.rv-page .rv-plan-load-bar {") == 1
    block = CSS.split("body.rv-page .rv-plan-load-bar {")[1].split("}")[0]
    assert "height: 22px" in block
    assert "overflow: visible" in block
