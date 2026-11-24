"""Issue #1830 — session version snapshots and summary lines."""

from backend.services.session_versions import summary_line


def test_initial_summary_line():
    line = summary_line(
        None,
        exercises=[{"name": "Squat", "sets": [{}, {}]}],
        duration_seconds=3600,
        session_effort=7,
    )
    assert "Initial save" in line
    assert "1 exercises" in line


def test_set_count_change_summary():
    prev = {"exercises_json": [{"name": "A", "sets": [{}]}], "duration_seconds": 100, "session_effort": 5}
    line = summary_line(
        prev,
        exercises=[{"name": "A", "sets": [{}, {}, {}]}],
        duration_seconds=100,
        session_effort=5,
    )
    assert "sets" in line.lower()