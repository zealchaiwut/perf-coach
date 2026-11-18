"""Issue #1826 — Phase 0 reader modules present for data-agreement checkpoint."""
from pathlib import Path


def test_p0_reader_modules_exist():
    assert Path("backend/services/session_tss.py").is_file()
    assert Path("backend/services/weekly_rollup.py").is_file()
    assert Path("backend/services/score_reader.py").is_file()
    assert Path("docs/revamp/SPEC.md").is_file()


def test_weekly_rollup_referenced_in_export():
    text = Path("backend/services/coach_export.py").read_text(encoding="utf-8")
    assert "weekly_rollups" in text
    assert "from backend.services.weekly_rollup import" in text