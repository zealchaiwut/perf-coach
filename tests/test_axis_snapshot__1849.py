"""P4-2 (#1849) — shared snapshot table extension, reader and worker wiring."""
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from backend.models import PerformanceScoreHistory
from backend.services import axis_snapshot, score_reader

AS_OF = date(2026, 11, 20)


def test_history_model_has_phase4_columns():
    cols = PerformanceScoreHistory.__table__.columns.keys()
    for c in ("endurance", "speed", "durability", "economy", "strength", "mobility", "power_to_weight"):
        assert c in cols


def test_snapshot_axes_cover_all_new_axes():
    assert set(axis_snapshot.SNAPSHOT_AXES) == {
        "durability", "economy", "strength", "mobility", "power_to_weight"}


def test_snapshot_values_none_for_never_measured():
    vals = axis_snapshot.snapshot_values({
        "durability": {"score": 84}, "economy": {"score": None}})
    assert vals == {"durability": 84.0, "economy": None}


def test_compute_axes_isolates_failures():
    def boom(*a):
        raise RuntimeError("x")
    with patch.dict(axis_snapshot.AXIS_COMPUTERS, {}, clear=False):
        with patch.object(axis_snapshot, "_load_computers", lambda: None):
            axis_snapshot.AXIS_COMPUTERS["durability"] = lambda *a: {"score": 70}
            axis_snapshot.AXIS_COMPUTERS["economy"] = boom
            out = axis_snapshot.compute_axes(None, "u", AS_OF)
    assert out == {"durability": {"score": 70}}


def test_reader_adds_delta_from_snapshot():
    block = {"score": 80, "stale": False, "never_measured": False}
    with patch.object(axis_snapshot, "compute_axes", return_value={"durability": dict(block)}):
        with patch.object(axis_snapshot, "score_n_days_ago", return_value=70.0):
            out = score_reader.get_axis_scores(object(), "u", AS_OF)
    assert out["axes"]["durability"]["delta_28d"] == 10.0
    with patch.object(axis_snapshot, "compute_axes", return_value={"durability": dict(block)}):
        with patch.object(axis_snapshot, "score_n_days_ago", return_value=None):
            out = score_reader.get_axis_scores(object(), "u", AS_OF)
    assert out["axes"]["durability"]["delta_28d"] is None


def test_migration_is_single_head_with_downgrade():
    src = Path("alembic/versions/27d247208ac6_performance_score_history_phase4_axes.py").read_text()
    assert "def downgrade" in src and "drop_column" in src and "column_exists" in src


def test_worker_registers_axis_snapshot_job():
    src = Path("backend/worker_app.py").read_text()
    assert '"axis_snapshot": _h_axis_snapshot' in src
    assert "axis_snapshot:" in src  # scheduler dedupe key
