"""P4 follow-ups #1893–#1898 — static contracts."""
from pathlib import Path

HTML = Path("frontend/pages/v2-performance.html").read_text(encoding="utf-8")
JS = Path("frontend/js/v2-performance.js").read_text(encoding="utf-8")
WORKER = Path("backend/worker_app.py").read_text(encoding="utf-8")
PV = Path("backend/services/projection_view.py").read_text(encoding="utf-8")
RC = Path("backend/services/race_calibration.py").read_text(encoding="utf-8")
ROLES = Path("backend/services/race_roles.py").read_text(encoding="utf-8")


def test_1893_performance_loads_csrf_lib():
    assert "/js/lib/csrf-fetch.js" in HTML
    assert "/js/lib/copy-for-claude.js" in HTML


def test_1894_role_column_is_source_no_legacy_derivation():
    assert "_derive_role_from_legacy" not in ROLES
    assert 'return "fun"' in ROLES
    assert 'name="role"' in JS
    assert "Role is independent of priority" in JS


def test_1895_form_power_from_vertical_power_list():
    extractor = Path("backend/services/form_metrics_extractor.py").read_text(encoding="utf-8")
    assert "vertical_power_list" in extractor
    assert "form_power_w_from_streams" in extractor
    assert Path("tests/fixtures/stryd_activity_form_power.json").exists()


def test_1897_first_gel_and_checkin_record():
    models = Path("backend/models.py").read_text(encoding="utf-8")
    coach = Path("backend/services/coach_block.py").read_text(encoding="utf-8")
    training = Path("frontend/pages/training.html").read_text(encoding="utf-8")
    training_js = Path("frontend/js/training.js").read_text(encoding="utf-8")
    assert "first_gel_minute" in models
    assert "is_week_checkin_done" in coach
    assert "id=\"workout-first-gel\"" in training
    assert "first_gel_minute" in training_js


def test_1896_worker_records_predictions_get_does_not():
    assert "def _run_race_predictions_batch" in WORKER
    assert "record_todays_predictions" in RC
    assert "record_prediction(" not in PV
    assert "ensure_calibrations" not in PV
    assert "_history(session" in PV


def test_1898_all_races_and_page_smoke_ids():
    assert "data-show-all-races" in JS
    assert "/api/performance/races?all=1" in JS
    for eid in (
        "v2-perf-hero",
        "v2-perf-radar",
        "v2-perf-focus",
        "v2-perf-score-cards",
        "v2-perf-projection",
        "v2-perf-races",
        "v2-perf-coach",
        "v2-perf-drawer",
    ):
        assert f'id="{eid}"' in HTML
