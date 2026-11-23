"""Issue #1847 — Phase 3 checkpoint static contracts."""

from pathlib import Path


def test_phase3_mock_previews_exist():
    root = Path("docs/revamp/mocks/preview")
    assert (root / "TrainingWeek.html").is_file()
    assert (root / "TrainingPlanEdit.html").is_file()


def test_phase3_plan_routes_registered():
    src = Path("backend/main.py").read_text(encoding="utf-8")
    routes = [
        "/api/plan/revamp-week",
        "/api/plan/coach-week-import/parse",
        "/api/plan/coach-week-import/photo-capabilities",
        "/api/plan/revamp-suggest/preview",
        "/api/plan/rule-evaluate",
        "/api/plan/revamp-planned-editor/context",
        '"/v2/settings/plan"',
    ]
    for r in routes:
        assert r in src, f"missing route {r}"


def test_phase3_v2_plan_page_wires_phase3_js():
    html = Path("frontend/pages/v2-training-plan.html").read_text(encoding="utf-8")
    for needle in (
        "v2-plan-week-board.js",
        "v2-session-editor.js",
        "v2-coach-import",
    ):
        assert needle in html
    board = Path("frontend/js/v2-plan-week-board.js").read_text(encoding="utf-8")
    assert "revamp-suggest" in board
    assert "V2SessionEditor" in board


def test_phase3_checkpoint_doc_present():
    assert Path("docs/revamp/phase3-checkpoint.md").is_file()
    body = Path("docs/revamp/phase3-checkpoint.md").read_text(encoding="utf-8")
    assert "Suggest sessions" in body
    assert "phase3-followups" in body