"""Static checks for session modal view/edit UX (feature/session-modal-ux)."""
from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TP = (REPO / "frontend" / "js" / "training-plan.js").read_text()
PAGE = (REPO / "frontend" / "pages" / "training-log.html").read_text()


def test_mode_defaults_to_view_and_has_edit_chrome():
    assert "mode: 'view'" in TP or 'mode: "view"' in TP
    assert "pl-sm-enter-edit" in TP
    assert "pl-sm-done-edit" in TP
    assert 'data-sm-mode="' in TP
    assert "is-view" in TP and "is-edit" in TP


def test_subtype_select_wired_for_strength():
    assert "pl-sm-subtype" in TP
    assert "_smUiSubtype" in TP
    assert "out.subtype" in TP


def test_edit_has_delete_and_view_has_checkmark():
    assert 'data-ex-del="' in TP
    assert "pl-sm-delx" in TP
    assert 'data-ex-skip="' in TP
    assert "pl-sm-chk" in TP
    assert "completed" in TP  # gym checklist state
    # Edit path uses delete; view path keeps checkbox — both present, gated by edit flag
    assert "_smIsEdit()" in TP


def test_block_edit_controls_present():
    assert "data-blk-rename" in TP
    assert "data-blk-del" in TP
    assert "data-blk-up" in TP
    assert "data-ex-up" in TP
    assert "data-blk-add" in TP
    assert "data-blk-sets" in TP
    assert "_smAddBlock" in TP
    assert "_smApplyBlockSets" in TP
    assert "_SM_BLOCK_OPTIONS" in TP
    assert "EMOM" in TP and "40/20" in TP
    assert "Heavy compound" in TP


def test_swap_search_has_no_filters():
    assert "Search exercises…" in TP or 'Search exercises' in TP
    assert "pl-sm-pick-filters" not in TP.split("function _smMountSwapPicker")[1].split("function _smFetchSwapCandidates")[0]
    assert "searchAll: true" in TP
    assert "swap.avoid = []" in TP


def test_pin_label_and_spend_units():
    assert "pl-sm-pinbtn" in TP
    assert "Pinned" in TP
    assert "'Pin')" in TP or '"Pin"' in TP
    assert " min'" in TP or ' min"' in TP or "+ ' min'" in TP
    assert " TSS'" in TP or ' TSS"' in TP or "+ ' TSS'" in TP


def test_simple_view_hides_row_spend_and_swap_strike():
    # View rows omit per-exercise min/TSS (block header keeps them)
    assert "Math.round(mins * 10)" in TP  # block meta still uses mins
    # replaced_name strike only when edit
    assert "edit && ex.replaced_name" in TP
    assert 'font-size:15.5px' in TP  # larger exercise name in view


def test_session_export_json_button():
    assert "pl-sm-export-json" in TP
    assert "_smExportSessionPayload" in TP
    assert "_smDownloadSessionJson" in TP
    assert "Export JSON" in TP


def test_cache_bust_updated():
    assert "training-plan.js?v=20260807planv3g" in PAGE
