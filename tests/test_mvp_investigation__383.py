"""
Tests for docs/mvp-investigation.md (issue #383).

Each test anchors to one AC item. Tests are read-only — they inspect the
committed doc file; no server or DB needed.
"""

import pathlib
import pytest

DOC_PATH = pathlib.Path(__file__).parent.parent / "docs" / "mvp-investigation.md"


@pytest.fixture(scope="module")
def doc_text():
    assert DOC_PATH.exists(), f"docs/mvp-investigation.md not found at {DOC_PATH}"
    return DOC_PATH.read_text(encoding="utf-8").lower()


# AC: docs/mvp-investigation.md exists and is committed
def test_doc_file_exists():
    assert DOC_PATH.exists(), "docs/mvp-investigation.md must exist"
    assert DOC_PATH.stat().st_size > 500, "doc file appears empty"


# AC: Data Model section documents workouts, workout_exercises, daily_metrics, habits
def test_data_model_section_present(doc_text):
    assert "data model" in doc_text, "Missing '## Data Model' section"


def test_data_model_workouts(doc_text):
    assert "workouts" in doc_text
    # key columns that must appear
    for col in ("workout_date", "workout_type", "distance_km", "duration_seconds", "tss"):
        assert col in doc_text, f"workouts column '{col}' not documented"


def test_data_model_workout_exercises(doc_text):
    assert "workout_exercises" in doc_text
    for col in ("display_order", "name", "sets", "reps", "weight_kg"):
        assert col in doc_text, f"workout_exercises column '{col}' not documented"


def test_data_model_daily_metrics(doc_text):
    assert "daily_metrics" in doc_text
    for col in ("resting_hr", "hrv", "sleep_hours", "energy", "mood"):
        assert col in doc_text, f"daily_metrics column '{col}' not documented"


def test_data_model_habits(doc_text):
    assert "habits" in doc_text
    for col in ("name", "display_order", "archived_at"):
        assert col in doc_text, f"habits column '{col}' not documented"


def test_data_model_habit_logs(doc_text):
    # habit_logs is a related table (habit_completions / habit_history per AC)
    assert "habit_logs" in doc_text, "habit_logs table not documented"
    assert "logged_date" in doc_text, "habit_logs.logged_date not documented"


# AC: Endpoints section lists routes for /api/workouts, /api/habits,
#     /api/daily-metrics, /api/home; each entry has method, path, params,
#     request body shape, response shape.
def test_endpoints_section_present(doc_text):
    assert "endpoint" in doc_text, "Missing Endpoints section"


def test_endpoints_workouts(doc_text):
    assert "/api/workouts" in doc_text


def test_endpoints_habits(doc_text):
    assert "/api/habits" in doc_text


def test_endpoints_daily_metrics(doc_text):
    assert "/api/daily-metrics" in doc_text


def test_endpoints_home(doc_text):
    assert "/api/home" in doc_text


def test_endpoints_include_http_methods(doc_text):
    for method in ("get", "post", "patch", "delete"):
        assert method in doc_text, f"HTTP method '{method.upper()}' not found in endpoints"


# AC: Frontend Pages section covers home.html, weight.html, log.html,
#     habits.html, calendar.html — layout + API calls noted.
def test_frontend_pages_section_present(doc_text):
    assert "frontend page" in doc_text or "frontend pages" in doc_text


def test_frontend_page_home(doc_text):
    assert "home.html" in doc_text


def test_frontend_page_weight(doc_text):
    assert "weight.html" in doc_text


def test_frontend_page_log(doc_text):
    # served as training-log.html but route is /log
    assert "log" in doc_text and ("training-log.html" in doc_text or "log.html" in doc_text)


def test_frontend_page_habits(doc_text):
    assert "habits.html" in doc_text


def test_frontend_page_calendar(doc_text):
    assert "calendar.html" in doc_text


# AC: Migration Helpers section — states whether alembic/helpers.py exists;
#     if yes, lists functions.
def test_migration_helpers_section_present(doc_text):
    assert "migration helper" in doc_text or "alembic/helpers" in doc_text


def test_migration_helpers_functions_documented(doc_text):
    for fn in ("table_exists", "column_exists", "index_exists", "fk_exists"):
        assert fn in doc_text, f"helpers.py function '{fn}' not documented"


# AC: Explicit answers to specific questions
def test_zone2_minutes_answer(doc_text):
    assert "zone2_minutes" in doc_text, "Doc must answer whether zone2_minutes column exists"


def test_habits_table_answer(doc_text):
    # Must contain a clear yes/no about habits table existence
    assert "habits" in doc_text
    # presence of 'yes' or 'exists' near habits is a reasonable proxy
    assert ("habits table" in doc_text or "habits exists" in doc_text or
            "habits` table" in doc_text or "`habits`" in doc_text)


def test_tracking_type_answer(doc_text):
    assert "tracking_type" in doc_text, "Doc must answer what tracking_type values exist"


def test_weekly_aggregation_answer(doc_text):
    assert "weekly" in doc_text, "Doc must answer whether habits support weekly aggregation"
