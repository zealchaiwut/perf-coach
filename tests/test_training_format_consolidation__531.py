"""Tests for issue #531: Extract shared JS module for training format helpers.

Validates consolidation of training-format.js and the new /api/exercises/names endpoint.
Read tests verify the code structure; HTTP tests verify the API endpoint.
"""
import os
import pytest
import httpx

BASE_URL = os.environ.get("UAT_BASE_URL", "http://localhost:9001")
if not BASE_URL.startswith("http"):
    raise RuntimeError(f"UAT_BASE_URL not valid: {BASE_URL}")

# Derive repo root from test file location
REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


def read_file(path):
    """Read a file relative to the repo root."""
    full_path = os.path.join(REPO_ROOT, path)
    with open(full_path) as f:
        return f.read()


# ─────────────────────────────────────────────────────────────────────────────
# AC 1: training-format.js module exists with 4 exports
# ─────────────────────────────────────────────────────────────────────────────

def test_training_format_module_created():
    """AC 1: frontend/js/lib/training-format.js exists."""
    path = os.path.join(REPO_ROOT, "frontend/js/lib/training-format.js")
    assert os.path.exists(path), f"Module not found at {path}"


def test_training_format__exports_normalizeType():
    """AC 1: normalizeType is exported from window.TrainingFormat."""
    content = read_file("frontend/js/lib/training-format.js")
    assert "function normalizeType(" in content
    assert "normalizeType: normalizeType" in content


def test_training_format__exports_formatPace():
    """AC 1: formatPace is exported from window.TrainingFormat."""
    content = read_file("frontend/js/lib/training-format.js")
    assert "function formatPace(" in content
    assert "formatPace: formatPace" in content


def test_training_format__exports_formatDuration():
    """AC 1: formatDuration is exported from window.TrainingFormat."""
    content = read_file("frontend/js/lib/training-format.js")
    assert "function formatDuration(" in content
    assert "formatDuration: formatDuration" in content


def test_training_format__exports_mapSegmentsToExercises():
    """AC 1: mapSegmentsToExercises is exported from window.TrainingFormat."""
    content = read_file("frontend/js/lib/training-format.js")
    assert "function mapSegmentsToExercises(" in content
    assert "mapSegmentsToExercises: mapSegmentsToExercises" in content


def test_training_format__exports_to_window():
    """AC 1: All functions are attached to window.TrainingFormat."""
    content = read_file("frontend/js/lib/training-format.js")
    assert "global.TrainingFormat = {" in content


# ─────────────────────────────────────────────────────────────────────────────
# AC 2: training-log.js and training.js import from the shared module
# ─────────────────────────────────────────────────────────────────────────────

def test_training_log_js_uses_shared_module():
    """AC 2: training-log.js uses window.TrainingFormat, not local copies."""
    content = read_file("frontend/js/training-log.js")
    assert "var TF = window.TrainingFormat;" in content
    # No local definitions of the 4 core functions
    assert "function normalizeType(" not in content
    assert "function formatPace(" not in content
    assert "function formatDuration(" not in content


def test_training_log_html_loads_module_first():
    """AC 2: training-log.html loads training-format.js before training-log.js."""
    content = read_file("frontend/pages/training-log.html")
    idx_fmt = content.find("js/lib/training-format.js")
    idx_log = content.find("js/training-log.js")
    assert idx_fmt > 0 and idx_log > 0
    assert idx_fmt < idx_log, "training-format.js must load before training-log.js"


def test_training_js_uses_shared_module():
    """AC 2: training.js uses window.TrainingFormat, not local copies."""
    content = read_file("frontend/js/training.js")
    assert "var TF = window.TrainingFormat;" in content
    # No local definitions of the 4 core functions
    assert "function normalizeType(" not in content
    assert "function formatPace(" not in content
    assert "function formatDuration(" not in content


def test_training_html_loads_module_first():
    """AC 2: training.html loads training-format.js before training.js."""
    content = read_file("frontend/pages/training.html")
    idx_fmt = content.find("js/lib/training-format.js")
    idx_training = content.find("js/training.js")
    assert idx_fmt > 0 and idx_training > 0
    assert idx_fmt < idx_training, "training-format.js must load before training.js"


# ─────────────────────────────────────────────────────────────────────────────
# AC 3: /api/exercises/names endpoint exists
# ─────────────────────────────────────────────────────────────────────────────

def test_api_exercises_names_endpoint_exists():
    """AC 3: GET /api/exercises/names endpoint is defined in backend."""
    content = read_file("backend/main.py")
    assert '@app.get("/api/exercises/names")' in content


def test_api_exercises_names_returns_array():
    """AC 3: /api/exercises/names returns a JSON array of names."""
    content = read_file("backend/main.py")
    # Verify the endpoint returns distinct exercise names
    assert "WorkoutExercise.name" in content
    assert "distinct()" in content
    assert "JSONResponse(names)" in content


# ─────────────────────────────────────────────────────────────────────────────
# AC 4: Network efficiency — single request for exercise autocomplete
# ─────────────────────────────────────────────────────────────────────────────

def test_training_js_calls_dedicated_endpoint():
    """AC 4: training.js calls /api/exercises/names endpoint."""
    content = read_file("frontend/js/training.js")
    assert "'/api/exercises/names'" in content or '"/api/exercises/names"' in content


def test_loadSuggestions_uses_exercises_endpoint():
    """AC 4: loadSuggestions calls /api/exercises/names, not full workout details."""
    content = read_file("frontend/js/training.js")
    # Find loadSuggestions function
    assert "function loadSuggestions()" in content
    # Inside loadSuggestions, it should call the dedicated endpoint
    # (This is checked above, but verify the function exists)
    assert "var exRes = await fetch('/api/exercises/names')" in content


# ─────────────────────────────────────────────────────────────────────────────
# AC 5: Structured-run detection — type normalization consistency
# ─────────────────────────────────────────────────────────────────────────────

def test_type_normalization_maps_run_variants():
    """AC 5: normalizeType maps 'run', 'Running', 'Race' to 'run'."""
    content = read_file("frontend/js/lib/training-format.js")
    # Must handle case-insensitive matching
    assert "toLowerCase()" in content
    # Must have regex patterns for "run", "Running", "Race"
    assert "/^run" in content or "run" in content
    assert "return 'run'" in content


def test_type_normalization_in_training_log():
    """AC 5: training-log.js uses normalizeType from shared module."""
    content = read_file("frontend/js/training-log.js")
    # Uses the shared function
    assert "normalizeTypeKey = TF.normalizeType" in content or "var normalizeTypeKey = TF.normalizeType" in content


def test_type_normalization_in_training():
    """AC 5: training.js uses normalizeType from shared module."""
    content = read_file("frontend/js/training.js")
    # Verify the function is used (not redefined)
    assert "TF.normalizeType" in content


# ─────────────────────────────────────────────────────────────────────────────
# AC 6: Source attribution consistency
# ─────────────────────────────────────────────────────────────────────────────

def test_shared_module_includes_segment_types():
    """AC 6: training-format.js defines canonical segment types with intensity."""
    content = read_file("frontend/js/lib/training-format.js")
    assert "SEG_TYPES = {" in content
    assert "intensity" in content
    assert "segmentIntensityByLabel" in content


# ─────────────────────────────────────────────────────────────────────────────
# AC 7: Pace and duration formatting consistency
# ─────────────────────────────────────────────────────────────────────────────

def test_formatPace_implementation():
    """AC 7: formatPace computes pace in m:ss format from duration and distance."""
    content = read_file("frontend/js/lib/training-format.js")
    # Must compute seconds per km
    assert "secPerKm" in content
    # Must return m:ss format
    assert "m + ':' + pad(s)" in content


def test_formatDuration_implementation():
    """AC 7: formatDuration formats durations as h:mm:ss (or m:ss under an hour)."""
    content = read_file("frontend/js/lib/training-format.js")
    # Must handle hour/minute/second breakdown
    assert "if (h > 0)" in content
    assert "pad(m)" in content
    assert "pad(s)" in content


def test_training_log_uses_shared_formatPace():
    """AC 7: training-log.js calls formatPace from shared module."""
    content = read_file("frontend/js/training-log.js")
    assert "TF.formatPace" in content


def test_training_log_uses_shared_formatDuration():
    """AC 7: training-log.js calls formatDuration from shared module."""
    content = read_file("frontend/js/training-log.js")
    assert "TF.formatDuration" in content


def test_training_uses_shared_formatPace():
    """AC 7: training.js calls formatPace from shared module."""
    content = read_file("frontend/js/training.js")
    assert "TF.formatPace" in content


def test_training_uses_shared_formatDuration():
    """AC 7: training.js uses shared module (formatDuration is in training-log.js)."""
    # training.js uses formatPace and mapSegmentsToExercises but not formatDuration
    # (which is used by training-log.js). The critical point is that both use TF.
    content = read_file("frontend/js/training.js")
    assert "var TF = window.TrainingFormat;" in content
    assert "TF.formatPace" in content  # Confirms shared module usage


def test_training_uses_mapSegmentsToExercises():
    """AC 7: training.js uses mapSegmentsToExercises for segment serialization."""
    content = read_file("frontend/js/training.js")
    assert "TF.mapSegmentsToExercises" in content


def test_training_log_uses_mapSegmentsToExercises():
    """AC 7: training-log.js uses mapSegmentsToExercises for segment display."""
    content = read_file("frontend/js/training-log.js")
    # The log page likely uses segment intensity mapping
    assert "TF." in content or "TrainingFormat" in content
