"""Tests for issue #531: Extract shared JS module for training format helpers.

Each test is anchored to a specific acceptance criterion:

AC1  frontend/js/lib/training-format.js exists and exports normalizeType,
     formatPace, formatDuration, and mapSegmentsToExercises.
AC2  training-log.js and training.js consume the shared helpers from
     training-format.js; no local copies of those functions remain.
AC3  A dedicated endpoint GET /api/exercises/names returns exercise names
     only; loadSuggestions calls it instead of fetching full workout details.
AC4  Page load fires <=1 request for exercise autocomplete data (not ~11):
     loadSuggestions no longer loops full /api/workouts/<id> detail fetches.
AC5  Structured-run detection is identical on both pages — both run the same
     shared normalizeType (e.g. "Race" and "Running" both normalize to "run").
AC6  Source attribution stays consistent across both views (single
     isStravaWorkout helper used by list and detail).
AC7  No regression in pace/duration display — the shared formatters reproduce
     the previously displayed strings.

The behavioral JS assertions (AC1/AC5/AC7) execute the actual module under
node, so they verify real behavior, not just source text.
"""
import json
import os
import pathlib
import subprocess
import uuid
from datetime import date

import httpx
import pytest

REPO = pathlib.Path(__file__).resolve().parents[1]
LIB = REPO / "frontend" / "js" / "lib" / "training-format.js"
TRAINING_JS = REPO / "frontend" / "js" / "training.js"
TRAINING_LOG_JS = REPO / "frontend" / "js" / "training-log.js"
TRAINING_HTML = REPO / "frontend" / "pages" / "training.html"
TRAINING_LOG_HTML = REPO / "frontend" / "pages" / "training-log.html"

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")


# ── node harness: load the IIFE module and evaluate an expression ────────────

def _node_eval(expr: str):
    """Load training-format.js under a fake `window` and return JSON(expr)."""
    script = (
        "const fs=require('fs');"
        "global.window={};"
        "eval(fs.readFileSync(%r,'utf8'));"
        "const TF=global.window.TrainingFormat;"
        "process.stdout.write(JSON.stringify(%s));"
    ) % (str(LIB), expr)
    out = subprocess.run(
        ["node", "-e", script],
        capture_output=True, text=True, timeout=20,
    )
    assert out.returncode == 0, f"node failed: {out.stderr}"
    return json.loads(out.stdout)


# ── AC1: shared module exists and exports the four named helpers ─────────────

def test_ac1_module_file_exists():
    assert LIB.exists(), "frontend/js/lib/training-format.js must exist"


@pytest.mark.parametrize("name", [
    "normalizeType", "formatPace", "formatDuration", "mapSegmentsToExercises",
])
def test_ac1_exports_named_helper(name):
    typ = _node_eval(f"typeof TF.{name}")
    assert typ == "function", f"TF.{name} must be an exported function"


# ── AC2: both pages consume shared helpers; no local copies remain ───────────

def test_ac2_pages_load_shared_module_before_page_script():
    for html, page in (
        (TRAINING_HTML, "training.js"),
        (TRAINING_LOG_HTML, "training-log.js"),
    ):
        text = html.read_text()
        assert "lib/training-format.js" in text, (
            f"{html.name} must load the shared training-format.js module"
        )
        assert text.index("lib/training-format.js") < text.index(page), (
            f"training-format.js must load before {page} in {html.name}"
        )


def test_ac2_both_files_reference_shared_module():
    assert "TrainingFormat" in TRAINING_JS.read_text(), (
        "training.js must use window.TrainingFormat helpers"
    )
    assert "TrainingFormat" in TRAINING_LOG_JS.read_text(), (
        "training-log.js must use window.TrainingFormat helpers"
    )


def test_ac2_no_local_pace_formatter_copy_in_training_js():
    # The editor's local fmtPace m:ss formatter is gone; pace formatting now
    # lives only in the shared module.
    assert "function fmtPace(" not in TRAINING_JS.read_text(), (
        "training.js must not keep a local fmtPace() copy"
    )


def test_ac2_no_local_type_normalizer_copy_in_training_log_js():
    # training-log.js must not redefine the type-normalization table; it
    # consumes the shared normalizeType instead.
    assert "function normalizeTypeKey(" not in TRAINING_LOG_JS.read_text(), (
        "training-log.js must not keep a local normalizeTypeKey() copy"
    )


# ── AC3: loadSuggestions uses the dedicated endpoint, not detail loops ───────

def test_ac3_loadSuggestions_calls_exercise_names_endpoint():
    js = TRAINING_JS.read_text()
    idx = js.index("function loadSuggestions")
    body = js[idx: idx + 2500]
    assert "/api/exercises/names" in body, (
        "loadSuggestions must fetch the dedicated /api/exercises/names endpoint"
    )


# ── AC4: <=1 exercise-autocomplete request; no per-workout detail loop ───────

def test_ac4_loadSuggestions_no_workout_detail_loop():
    js = TRAINING_JS.read_text()
    idx = js.index("function loadSuggestions")
    body = js[idx: idx + 2500]
    assert "/api/workouts/' +" not in body and "/api/workouts/\" +" not in body, (
        "loadSuggestions must not fetch full workout details per workout"
    )
    assert "Promise.all" not in body, (
        "loadSuggestions must not fan out N detail requests via Promise.all"
    )


def test_ac4_single_exercise_names_request():
    js = TRAINING_JS.read_text()
    idx = js.index("function loadSuggestions")
    body = js[idx: idx + 2500]
    assert body.count("/api/exercises/names") == 1, (
        "Exactly one request should populate exercise autocomplete data"
    )


# ── AC5: identical structured-run detection via shared normalizeType ─────────

def test_ac5_normalizeType_unifies_run_aliases():
    assert _node_eval("TF.normalizeType('Running')") == "run"
    assert _node_eval("TF.normalizeType('run')") == "run"
    assert _node_eval("TF.normalizeType('Race')") == "run"


def test_ac5_normalizeType_other_types():
    assert _node_eval("TF.normalizeType('Strength')") == "lift"
    assert _node_eval("TF.normalizeType('Bike')") == "bike"


def test_ac5_both_pages_use_shared_normalizeType_for_detection():
    # training.js run detection routes through the shared helper.
    tj = TRAINING_JS.read_text()
    idx = tj.index("function isRunType")
    assert "normalizeType" in tj[idx: idx + 200], (
        "training.js isRunType must use the shared normalizeType"
    )
    # training-log.js routes its normalizeTypeKey alias through the shared helper.
    tl = TRAINING_LOG_JS.read_text()
    assert "TrainingFormat.normalizeType" in tl or "TF.normalizeType" in tl, (
        "training-log.js must derive type normalization from the shared helper"
    )


# ── AC6: single source-attribution helper used by both views ─────────────────

def test_ac6_single_isStravaWorkout_helper_used_by_both_views():
    import re
    js = TRAINING_LOG_JS.read_text()
    assert len(re.findall(r"function\s+isStravaWorkout\s*\(", js)) == 1, (
        "Exactly one isStravaWorkout helper must back source attribution"
    )
    assert re.search(r"isStravaWorkout\s*\(\s*w\s*\)", js), "list view must use it"
    assert re.search(r"isStravaWorkout\s*\(\s*workout\s*\)", js), "detail view must use it"


# ── AC7: no regression — shared formatters reproduce prior display strings ───

def test_ac7_formatPace_matches_prior_output():
    # 3600s over 10km -> 360 s/km -> "6:00" (matches the old fmtPace/fmtPaceFromSec core)
    assert _node_eval("TF.formatPace(3600, 10)") == "6:00"
    # seconds-per-km passed directly with distKm=1
    assert _node_eval("TF.formatPace(330, 1)") == "5:30"
    # invalid inputs -> null (callers add their own placeholder)
    assert _node_eval("TF.formatPace(0, 10)") is None
    assert _node_eval("TF.formatPace(3600, 0)") is None


def test_ac7_formatDuration_matches_prior_output():
    assert _node_eval("TF.formatDuration(125)") == "2:05"      # under an hour -> m:ss
    assert _node_eval("TF.formatDuration(3661)") == "1:01:01"  # over an hour -> h:mm:ss
    assert _node_eval("TF.formatDuration(null)") is None


def test_ac7_training_log_pace_formula_preserved():
    # issue #118 contract still holds: fmtPaceFromSec computes secPerKm.
    js = TRAINING_LOG_JS.read_text()
    assert "fmtPaceFromSec" in js
    assert "durSeconds / distKm" in js


# ── AC1/AC5/AC7: mapSegmentsToExercises behavior ─────────────────────────────

def test_mapSegmentsToExercises_builds_exercise_rows():
    segs = "[{type:'warmup',value:1,unit:'km'},{type:'intervals',sets:4,value:0.4,unit:'km',paceSec:240}]"
    rows = _node_eval(f"TF.mapSegmentsToExercises({segs})")
    assert [r["name"] for r in rows] == ["Warm-up", "Intervals"]
    assert rows[0]["distance_km"] == 1
    assert rows[1]["sets"] == 4
    assert rows[1]["distance_km"] == 0.4
    # pace (240 s/km) over 0.4 km -> 96 s per rep
    assert rows[1]["duration_seconds"] == 96


def test_mapSegmentsToExercises_skips_empty_rows():
    rows = _node_eval("TF.mapSegmentsToExercises([{type:'easy'}])")
    assert rows == []


# ── AC3: backend endpoint (integration) ──────────────────────────────────────

@pytest.fixture(scope="module")
def auth_client():
    """Create a user, set a password, log in, return an authed httpx client."""
    import sys
    sys.path.insert(0, str(REPO))
    from dotenv import dotenv_values
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session as DBSession
    from backend.auth import CSRF_COOKIE_NAME, generate_csrf_token, hash_password
    from backend.models import User

    run = uuid.uuid4().hex[:8]
    name = f"Fmt531_{run}"
    password = "fmt-531-pw"

    base_client = httpx.Client(base_url=BASE, timeout=10)
    res = base_client.post("/api/users", json={"name": name})
    if res.status_code not in (201, 200):
        pytest.skip(f"server at {BASE} unavailable for integration test: {res.status_code}")
    user_id = res.json()["id"]

    env_vals = dotenv_values(REPO / ".env")
    engine = create_engine(env_vals.get("DATABASE_URL_UAT"), pool_pre_ping=True)
    with DBSession(engine) as session:
        user = session.get(User, uuid.UUID(user_id))
        user.password_hash = hash_password(password)
        session.commit()

    login = base_client.post("/api/auth/login", json={"username": name, "password": password})
    assert login.status_code == 200, login.text
    session_cookie = login.cookies.get("session")
    csrf = generate_csrf_token()
    authed = httpx.Client(
        base_url=BASE, timeout=10,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf},
        headers={"X-CSRF-Token": csrf},
    )
    yield {"client": authed, "id": user_id, "run": run}
    authed.close()
    base_client.delete(f"/api/users/{user_id}")
    base_client.close()


def test_ac3_exercise_names_requires_auth():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        r = c.get("/api/exercises/names")
        if r.status_code == 404:
            pytest.fail("AC3: GET /api/exercises/names is not implemented")
        assert r.status_code == 401, "anonymous request must get 401"


def test_ac3_exercise_names_returns_names_only(auth_client):
    ac = auth_client["client"]
    run = auth_client["run"]
    payload = {
        "name": f"Wkt531_{run}",
        "workout_date": str(date.today()),
        "workout_type": "Strength",
        "exercises": [
            {"name": f"Squat531_{run}", "sets": 3, "reps": 5, "display_order": 0},
            {"name": f"Bench531_{run}", "sets": 3, "reps": 5, "display_order": 1},
        ],
    }
    create = ac.post("/api/workouts", json=payload)
    assert create.status_code == 201, create.text
    wid = create.json()["id"]
    try:
        r = ac.get("/api/exercises/names")
        assert r.status_code == 200, r.text
        names = r.json()
        assert isinstance(names, list)
        assert all(isinstance(n, str) for n in names), "endpoint returns names only (strings)"
        assert f"Squat531_{run}" in names
        assert f"Bench531_{run}" in names
    finally:
        ac.delete(f"/api/workouts/{wid}")


def test_ac3_exercise_names_distinct(auth_client):
    ac = auth_client["client"]
    run = auth_client["run"]
    dup = f"Plank531_{run}"
    ids = []
    for i in range(2):
        res = ac.post("/api/workouts", json={
            "name": f"DupWkt531_{run}_{i}",
            "workout_date": str(date.today()),
            "workout_type": "Strength",
            "exercises": [{"name": dup, "sets": 1, "reps": 1, "display_order": 0}],
        })
        assert res.status_code == 201, res.text
        ids.append(res.json()["id"])
    try:
        names = ac.get("/api/exercises/names").json()
        assert names.count(dup) == 1, "exercise names must be distinct"
    finally:
        for wid in ids:
            ac.delete(f"/api/workouts/{wid}")
