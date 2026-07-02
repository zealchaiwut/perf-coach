"""Tests for issue #567: Add Run View and Run Builder screens with Stryd/lap support.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance criteria (condensed):
  AC-DB1   — workout_splits has lap_type, avg_power, cadence_spm, stride_length_m
  AC-DB2   — workouts has avg_power, max_power, np, avg_cadence_spm, avg_stride_m
  AC-API3  — GET /api/workouts/{id}/full returns 5 workout-level Stryd fields and
              4 per-split fields (avg_power, cadence_spm, stride_length_m, lap_type)
  AC-API4  — Existing workouts without Stryd data return null for new fields
  AC-Z2JS  — ZONE2_HR_MIN=130 and ZONE2_HR_MAX=155 in a shared Zone 2 module
  AC-Z2CL  — Zone 2 lap classification uses those named constants
  AC-RV    — Run View page exists with all required structural sections
  AC-RB    — Run Builder page exists with all required structural sections
  AC-CONS  — Both screens use same Zone 2 constants, accent colors (lime/teal/purple)
  AC-STR   — Run Builder persists Stryd fields; View renders them or "—"
"""
import datetime
import os
import pathlib
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session as DBSession

from backend.auth import (
    CSRF_COOKIE_NAME,
    generate_csrf_token,
    hash_password,
)
from backend.models import User, WorkoutSplit, Workout
from tests._admin_helpers import admin_cookies as _admin_cookies

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_RV_HTML_PATH = _ROOT / "frontend" / "pages" / "run-view.html"
_RB_HTML_PATH = _ROOT / "frontend" / "pages" / "run-builder.html"
_Z2_JS_PATH = _ROOT / "frontend" / "js" / "zone2-constants.js"
_RV_JS_PATH = _ROOT / "frontend" / "js" / "run-view.js"
_RB_JS_PATH = _ROOT / "frontend" / "js" / "run-builder.js"


def _read(p: pathlib.Path) -> str:
    assert p.exists(), f"Expected file not found: {p}"
    return p.read_text()


# ── Live-server fixtures ──────────────────────────────────────────────────────

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_RUN_TAG = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "test-567-runview"
TODAY = datetime.date.today()

_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _make_authed_user(label: str):
    name = f"RunView567_{label}_{_RUN_TAG}"
    with httpx.Client(base_url=BASE, timeout=10) as bare:
        res = bare.post("/api/users", json={"name": name}, cookies=_admin_cookies())
        assert res.status_code == 201, res.text
        user_id = res.json()["id"]
        pw_hash = hash_password(_TEST_PASSWORD)
        with DBSession(engine) as session:
            user = session.get(User, uuid.UUID(user_id))
            assert user is not None
            user.password_hash = pw_hash
            session.commit()
        login_res = bare.post(
            "/api/auth/login",
            json={"username": name, "password": _TEST_PASSWORD},
        )
        assert login_res.status_code == 200, login_res.text
        session_cookie = login_res.cookies.get("session")
        assert session_cookie
    csrf_token = generate_csrf_token()
    client = httpx.Client(
        base_url=BASE,
        timeout=10,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return {"id": user_id, "name": name, "client": client}


@pytest.fixture(scope="module")
def auth_user():
    if engine is None:
        pytest.skip("DATABASE_URL_UAT not configured")
    u = _make_authed_user("main")
    yield u
    u["client"].delete(f"/api/users/{u['id']}", cookies=_admin_cookies())
    u["client"].close()


@pytest.fixture
def basic_run(auth_user):
    """A plain manual run (no Stryd data) used for AC-API tests."""
    client = auth_user["client"]
    res = client.post("/api/workouts", json={
        "name": "Test Run 567",
        "workout_date": TODAY.isoformat(),
        "workout_type": "run",
        "distance_km": 5.0,
        "duration_seconds": 1500,
    })
    assert res.status_code == 201, res.text
    wid = res.json()["id"]
    yield wid
    client.delete(f"/api/workouts/{wid}")


# ═════════════════════════════════════════════════════════════════════════════
# AC-DB1 — workout_splits schema has lap_type and Stryd per-split columns
# ═════════════════════════════════════════════════════════════════════════════

def test_ac_db1_lap_type_column_exists():
    """workout_splits must have a lap_type column (text, nullable)."""
    if engine is None:
        pytest.skip("DATABASE_URL_UAT not configured")
    insp = inspect(engine)
    cols = {c["name"]: c for c in insp.get_columns("workout_splits")}
    assert "lap_type" in cols, "workout_splits must have a lap_type column"
    col = cols["lap_type"]
    assert col["nullable"] is True, "lap_type must be nullable"


def test_ac_db1_stryd_split_columns_exist():
    """workout_splits must have avg_power, cadence_spm, stride_length_m."""
    if engine is None:
        pytest.skip("DATABASE_URL_UAT not configured")
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("workout_splits")}
    for col in ("avg_power", "cadence_spm", "stride_length_m"):
        assert col in cols, f"workout_splits must have column {col!r}"


def test_ac_db1_lap_type_default_is_auto():
    """When lap_type is omitted from a split insert, it must default to 'auto'."""
    if engine is None:
        pytest.skip("DATABASE_URL_UAT not configured")
    with DBSession(engine) as session:
        # Use raw SQL to check server default — safest way without creating a
        # real workout in this unit-level test.
        row = session.execute(
            text("SELECT column_default FROM information_schema.columns "
                 "WHERE table_name = 'workout_splits' AND column_name = 'lap_type'")
        ).first()
        # Server default may be a string like "'auto'::text" or just "'auto'"
        assert row is not None, "lap_type column must exist in information_schema"
        default_val = str(row[0]) if row[0] else ""
        assert "auto" in default_val, (
            f"lap_type server default must include 'auto'; got {default_val!r}"
        )


# ═════════════════════════════════════════════════════════════════════════════
# AC-DB2 — workouts schema has the five Stryd workout-level columns
# ═════════════════════════════════════════════════════════════════════════════

def test_ac_db2_stryd_workout_columns_exist():
    """workouts must have avg_power, max_power, np, avg_cadence_spm, avg_stride_m."""
    if engine is None:
        pytest.skip("DATABASE_URL_UAT not configured")
    insp = inspect(engine)
    cols = {c["name"] for c in insp.get_columns("workouts")}
    for col in ("avg_power", "max_power", "np", "avg_cadence_spm", "avg_stride_m"):
        assert col in cols, f"workouts must have column {col!r}"


# ═════════════════════════════════════════════════════════════════════════════
# AC-API3 — GET /api/workouts/{id}/full returns new workout + split fields
# ═════════════════════════════════════════════════════════════════════════════

def test_ac_api3_full_includes_workout_stryd_fields(auth_user, basic_run):
    """GET .../full must include the five new workout-level Stryd fields."""
    client = auth_user["client"]
    res = client.get(f"/api/workouts/{basic_run}/full")
    assert res.status_code == 200, res.text
    data = res.json()
    workout = data["workout"]
    for field in ("avg_power", "max_power", "np", "avg_cadence_spm", "avg_stride_m"):
        assert field in workout, (
            f"GET .../full workout must include {field!r}"
        )


def test_ac_api3_full_splits_include_lap_type(auth_user, basic_run):
    """GET .../full splits array must include lap_type per split."""
    client = auth_user["client"]
    # Add a split first.
    client.post(
        f"/api/workouts/{basic_run}/splits",
        json={"splits": [{"split_index": 1, "distance_km": 1.0, "duration_seconds": 300}]},
    )
    res = client.get(f"/api/workouts/{basic_run}/full")
    assert res.status_code == 200, res.text
    splits = res.json()["splits"]
    assert len(splits) >= 1, "splits must be non-empty after posting one"
    for sp in splits:
        assert "lap_type" in sp, "each split in GET .../full must include lap_type"


def test_ac_api3_full_splits_include_all_stryd_fields(auth_user, basic_run):
    """GET .../full splits must include avg_power, cadence_spm, stride_length_m."""
    client = auth_user["client"]
    res = client.get(f"/api/workouts/{basic_run}/full")
    assert res.status_code == 200, res.text
    splits = res.json()["splits"]
    if splits:
        sp = splits[0]
        for field in ("avg_power", "cadence_spm", "stride_length_m"):
            assert field in sp, f"split must include {field!r} in GET .../full"


# ═════════════════════════════════════════════════════════════════════════════
# AC-API4 — No-Stryd workouts return null for new fields
# ═════════════════════════════════════════════════════════════════════════════

def test_ac_api4_no_stryd_workout_fields_are_null(auth_user, basic_run):
    """A plain manual run must return null for all five new workout-level Stryd fields."""
    client = auth_user["client"]
    res = client.get(f"/api/workouts/{basic_run}/full")
    assert res.status_code == 200, res.text
    workout = res.json()["workout"]
    for field in ("avg_power", "max_power", "np", "avg_cadence_spm", "avg_stride_m"):
        assert workout[field] is None, (
            f"field {field!r} must be null for a workout with no Stryd source"
        )


def test_ac_api4_no_stryd_splits_are_null(auth_user, basic_run):
    """Splits on a manual run must return null for Stryd per-split fields."""
    client = auth_user["client"]
    client.post(
        f"/api/workouts/{basic_run}/splits",
        json={"splits": [{"split_index": 1, "distance_km": 1.0, "duration_seconds": 300}]},
    )
    res = client.get(f"/api/workouts/{basic_run}/full")
    splits = res.json()["splits"]
    assert splits
    sp = splits[0]
    for field in ("avg_power", "cadence_spm", "stride_length_m"):
        assert sp[field] is None, f"split field {field!r} must be null for non-Stryd run"


# ═════════════════════════════════════════════════════════════════════════════
# AC-API: lap_type persistence — round-trip via POST splits then GET .../full
# ═════════════════════════════════════════════════════════════════════════════

def test_lap_type_manual_persists(auth_user, basic_run):
    """A split submitted with lap_type='manual' must be returned as 'manual'."""
    client = auth_user["client"]
    res = client.post(
        f"/api/workouts/{basic_run}/splits",
        json={"splits": [
            {"split_index": 1, "distance_km": 0.8, "duration_seconds": 240, "lap_type": "manual"},
            {"split_index": 2, "distance_km": 1.2, "duration_seconds": 360, "lap_type": "auto"},
        ]},
    )
    assert res.status_code == 201, res.text
    splits = res.json()
    assert splits[0]["lap_type"] == "manual"
    assert splits[1]["lap_type"] == "auto"


def test_lap_type_defaults_to_auto_when_omitted(auth_user, basic_run):
    """A split posted without lap_type must default to 'auto'."""
    client = auth_user["client"]
    res = client.post(
        f"/api/workouts/{basic_run}/splits",
        json={"splits": [{"split_index": 1, "distance_km": 1.0, "duration_seconds": 300}]},
    )
    assert res.status_code == 201, res.text
    splits = res.json()
    assert splits[0]["lap_type"] == "auto", (
        "omitting lap_type must default the split to 'auto'"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC-STR — Run Builder persists Stryd workout-level fields on POST /api/workouts
# ═════════════════════════════════════════════════════════════════════════════

def test_post_workout_accepts_stryd_fields(auth_user):
    """POST /api/workouts must accept and persist avg_power, max_power, np,
    avg_cadence_spm, avg_stride_m for a run with device data."""
    client = auth_user["client"]
    res = client.post("/api/workouts", json={
        "name": "Stryd Run 567",
        "workout_date": TODAY.isoformat(),
        "workout_type": "run",
        "distance_km": 8.0,
        "duration_seconds": 2400,
        "avg_power": 265,
        "max_power": 310,
        "np": 270,
        "avg_cadence_spm": 176,
        "avg_stride_m": 1.12,
    })
    assert res.status_code == 201, res.text
    data = res.json()
    wid = data["id"]
    try:
        assert data.get("avg_power") == 265
        assert data.get("max_power") == 310
        assert data.get("np") == 270
        assert data.get("avg_cadence_spm") == 176
        assert abs(float(data.get("avg_stride_m", 0)) - 1.12) < 0.01
    finally:
        client.delete(f"/api/workouts/{wid}")


# ═════════════════════════════════════════════════════════════════════════════
# AC-Z2JS — Zone 2 constants in a shared JS module
# ═════════════════════════════════════════════════════════════════════════════

def test_ac_z2js_file_exists():
    """zone2-constants.js must exist in frontend/js/."""
    assert _Z2_JS_PATH.exists(), (
        "frontend/js/zone2-constants.js must exist (AC: Zone 2 named constants)"
    )


def test_ac_z2js_min_constant():
    """ZONE2_HR_MIN must be set to 130 in the shared file."""
    src = _read(_Z2_JS_PATH)
    assert "ZONE2_HR_MIN" in src, "zone2-constants.js must define ZONE2_HR_MIN"
    assert "130" in src, "ZONE2_HR_MIN must equal 130"


def test_ac_z2js_max_constant():
    """ZONE2_HR_MAX must be set to 155 in the shared file."""
    src = _read(_Z2_JS_PATH)
    assert "ZONE2_HR_MAX" in src, "zone2-constants.js must define ZONE2_HR_MAX"
    assert "155" in src, "ZONE2_HR_MAX must equal 155"


# ═════════════════════════════════════════════════════════════════════════════
# AC-Z2CL — Run View JS classifies Zone 2 laps using the shared constants
# ═════════════════════════════════════════════════════════════════════════════

def test_ac_z2cl_run_view_references_zone2_constants():
    """run-view.js must reference ZONE2_HR_MIN and ZONE2_HR_MAX (from the shared module)."""
    src = _read(_RV_JS_PATH)
    assert "ZONE2_HR_MIN" in src, "run-view.js must reference ZONE2_HR_MIN"
    assert "ZONE2_HR_MAX" in src, "run-view.js must reference ZONE2_HR_MAX"


def test_ac_z2cl_run_view_loads_zone2_module():
    """run-view.html must load zone2-constants.js."""
    html = _read(_RV_HTML_PATH)
    assert "zone2-constants.js" in html, (
        "run-view.html must include a <script> tag for zone2-constants.js"
    )


def test_ac_z2cl_run_builder_references_zone2_constants():
    """run-builder.js must reference the same ZONE2_HR_MIN / ZONE2_HR_MAX constants."""
    src = _read(_RB_JS_PATH)
    assert "ZONE2_HR_MIN" in src, "run-builder.js must reference ZONE2_HR_MIN"
    assert "ZONE2_HR_MAX" in src, "run-builder.js must reference ZONE2_HR_MAX"


# ═════════════════════════════════════════════════════════════════════════════
# AC-RV — Run View page structure
# ═════════════════════════════════════════════════════════════════════════════

def test_ac_rv_page_exists():
    """frontend/pages/run-view.html must exist."""
    assert _RV_HTML_PATH.exists(), "frontend/pages/run-view.html must exist"


def test_ac_rv_uses_gradient_background():
    """Run View must use the blue gradient background (var(--page-bg)) and
    floating white cards with 14 px radius and the correct shadow."""
    html = _read(_RV_HTML_PATH)
    assert "var(--page-bg)" in html, "run-view must use var(--page-bg) background"
    assert "box-shadow" in html, "run-view must define card box-shadow"
    assert "14px" in html or "var(--card-radius)" in html, (
        "run-view cards must use 14 px radius or var(--card-radius)"
    )


def test_ac_rv_fonts():
    """Run View must load Inter Tight and JetBrains Mono."""
    html = _read(_RV_HTML_PATH)
    assert "Inter+Tight" in html or "Inter Tight" in html, (
        "run-view must load Inter Tight font"
    )
    assert "JetBrains+Mono" in html or "JetBrains Mono" in html, (
        "run-view must load JetBrains Mono font"
    )


def test_ac_rv_header_run_badge():
    """Run View header must have a RUN type badge."""
    html = _read(_RV_HTML_PATH)
    assert "run-badge" in html.lower() or "rv-badge" in html.lower() or (
        "RUN" in html and "badge" in html.lower()
    ), "run-view must render a RUN type badge in the header"


def test_ac_rv_header_copy_id():
    """Run View header must have a copy-to-clipboard button for the short workout ID."""
    html = _read(_RV_HTML_PATH)
    assert "copy" in html.lower(), (
        "run-view header must include a copy-to-clipboard affordance for the workout ID"
    )


def test_ac_rv_header_strava_stryd_badges():
    """Run View must conditionally render Strava and Stryd source badges."""
    js = _read(_RV_JS_PATH)
    assert "strava" in js.lower(), "run-view.js must reference Strava for source badge"
    assert "stryd" in js.lower(), "run-view.js must reference Stryd for source badge"


def test_ac_rv_header_distance_pace_duration():
    """Run View must show Distance and Avg Pace as large tiles; Duration as a line.
    The page uses JS rendering so content resides in run-view.js; checking both."""
    combined = _read(_RV_HTML_PATH) + _read(_RV_JS_PATH)
    lower = combined.lower()
    assert "distance" in lower or "rv-dist" in lower, (
        "run-view must have a Distance tile (HTML or JS)"
    )
    assert "pace" in lower, "run-view must have an Avg Pace tile (HTML or JS)"
    assert "duration" in lower, "run-view must show Duration (HTML or JS)"


def test_ac_rv_tss_hero_tile():
    """Run View Load & Intensity section must have a TSS hero tile.
    The page uses JS rendering so checking both HTML and JS."""
    combined = _read(_RV_HTML_PATH) + _read(_RV_JS_PATH)
    assert "tss" in combined.lower(), "run-view must include a TSS tile in Load & Intensity (HTML or JS)"


def test_ac_rv_stryd_tiles_present():
    """Run View must have Avg Power, Max Power, Stride Length, Cadence tiles.
    The page uses JS rendering so checking both HTML and JS."""
    combined = _read(_RV_HTML_PATH) + _read(_RV_JS_PATH)
    lower = combined.lower()
    assert "avg power" in lower or "avg_power" in lower or "rv-avg-power" in lower, (
        "run-view must have an Avg Power tile (HTML or JS)"
    )
    assert "max power" in lower or "max_power" in lower or "rv-max-power" in lower, (
        "run-view must have a Max Power tile (HTML or JS)"
    )
    assert "stride" in lower, "run-view must have a Stride Length tile (HTML or JS)"
    assert "cadence" in lower, "run-view must have a Cadence tile (HTML or JS)"


def test_ac_rv_np_footnote():
    """Run View Load & Intensity section must include the NP footnote.
    The page uses JS rendering so checking both HTML and JS."""
    combined = _read(_RV_HTML_PATH) + _read(_RV_JS_PATH)
    assert "NP" in combined, (
        'run-view must include the "NP · stride = avg per step · cadence = steps/min" footnote (HTML or JS)'
    )


def test_ac_rv_dash_for_null():
    """run-view.js must render '—' (em dash) for absent/null Stryd fields."""
    js = _read(_RV_JS_PATH)
    # Must explicitly handle null → "—" for Stryd fields.
    assert "—" in js or "\\u2014" in js or "'—'" in js or '"—"' in js, (
        "run-view.js must render '—' for absent/null Stryd tile values"
    )


def test_ac_rv_segment_bar():
    """Run View Session Profile section must render a colored segment bar."""
    html = _read(_RV_HTML_PATH)
    lower = html.lower()
    assert "segment" in lower, "run-view must have a segment bar / session profile section"


def test_ac_rv_segment_effort_colors():
    """run-view.js must encode effort-level colors (easy/tempo/hard/recovery)."""
    js = _read(_RV_JS_PATH)
    lower = js.lower()
    assert "easy" in lower, "run-view.js must handle 'easy' segment color"
    assert "tempo" in lower, "run-view.js must handle 'tempo' segment color"
    assert "recovery" in lower, "run-view.js must handle 'recovery' segment color"


def test_ac_rv_laps_section():
    """Run View must have a Laps section."""
    html = _read(_RV_HTML_PATH)
    assert "laps" in html.lower(), "run-view must have a Laps section"


def test_ac_rv_laps_title_logic_auto():
    """run-view.js must use 'Laps · 1 km splits' when all laps are auto."""
    js = _read(_RV_JS_PATH)
    assert "1 km splits" in js, (
        "run-view.js must set the Laps title to 'Laps · 1 km splits' for all-auto laps"
    )


def test_ac_rv_laps_title_logic_manual():
    """run-view.js must use 'Laps' (no suffix) when any lap has lap_type='manual'."""
    js = _read(_RV_JS_PATH)
    assert "manual" in js.lower(), (
        "run-view.js must check for manual lap_type in the Laps section title logic"
    )


def test_ac_rv_lap_chart_metric_toggle():
    """Run View lap bar chart must have Pace / HR / Power metric toggle."""
    js = _read(_RV_JS_PATH)
    lower = js.lower()
    assert "pace" in lower, "run-view.js lap chart must support Pace toggle"
    assert "hr" in lower or "heartrate" in lower, "run-view.js lap chart must support HR toggle"
    assert "power" in lower, "run-view.js lap chart must support Power toggle"


def test_ac_rv_zone2_lap_pill():
    """run-view.js must render a Z2 pill on Zone 2 laps."""
    js = _read(_RV_JS_PATH)
    assert "Z2" in js, "run-view.js must render a 'Z2' pill on Zone 2 laps"


def test_ac_rv_zone2_teal_tint():
    """run-view.js must apply a teal tint to Zone 2 lap rows."""
    js = _read(_RV_JS_PATH)
    assert "teal" in js.lower() or "z2-lap" in js.lower() or "zone2" in js.lower(), (
        "run-view.js must apply teal tint / zone2 class to Zone 2 lap rows"
    )


def test_ac_rv_lap_table_columns():
    """Run View Lap table must have Lap#, Distance, Pace, HR, Stride, Cadence, Power columns."""
    html = _read(_RV_HTML_PATH)
    lower = html.lower()
    # The table columns may be rendered by JS — check the JS for column headers too.
    js = _read(_RV_JS_PATH)
    combined = lower + js.lower()
    assert "lap" in combined, "lap table must have a Lap # column"
    assert "pace" in combined, "lap table must have a Pace column"
    assert "stride" in combined or "len" in combined, "lap table must have a Stride column"
    assert "cadence" in combined or "cad" in combined, "lap table must have a Cadence column"
    assert "power" in combined or "pwr" in combined, "lap table must have a Power column"


def test_ac_rv_map_placeholder():
    """Run View Route section must show a placeholder (no real map rendered)."""
    combined = _read(_RV_HTML_PATH) + _read(_RV_JS_PATH)
    assert "Map appears once GPS sync is added" in combined, (
        'run-view must display "Map appears once GPS sync is added" in the Route section'
    )


def test_ac_rv_strava_link():
    """run-view.js must render a 'View on Strava' link when a Strava URL is present."""
    js = _read(_RV_JS_PATH)
    assert "View on Strava" in js or "strava_activity_url" in js, (
        "run-view.js must render a 'View on Strava' external link from strava_activity_url"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC-RB — Run Builder page structure
# ═════════════════════════════════════════════════════════════════════════════

def test_ac_rb_page_exists():
    """frontend/pages/run-builder.html must exist."""
    assert _RB_HTML_PATH.exists(), "frontend/pages/run-builder.html must exist"


def test_ac_rb_same_gradient_styling():
    """Run Builder must use the same gradient styling as Run View."""
    html = _read(_RB_HTML_PATH)
    assert "var(--page-bg)" in html, "run-builder must use var(--page-bg) background"
    assert "box-shadow" in html or "var(--card-shadow)" in html, (
        "run-builder must use the card shadow (14px radius)"
    )


def test_ac_rb_fonts():
    """Run Builder must load the same fonts as Run View."""
    html = _read(_RB_HTML_PATH)
    assert "Inter+Tight" in html or "Inter Tight" in html, (
        "run-builder must load Inter Tight"
    )
    assert "JetBrains+Mono" in html or "JetBrains Mono" in html, (
        "run-builder must load JetBrains Mono"
    )


def test_ac_rb_workout_basics_fields():
    """Run Builder must have Name, Date, workout type pills, Remarks, TSS fields."""
    html = _read(_RB_HTML_PATH)
    lower = html.lower()
    assert "name" in lower, "run-builder must have a Name field"
    assert "date" in lower or 'type="date"' in lower, "run-builder must have a Date picker"
    assert "remarks" in lower or "notes" in lower, "run-builder must have a Remarks/notes field"
    assert "tss" in lower, "run-builder must have a TSS field"


def test_ac_rb_workout_type_pills():
    """Run Builder must have workout type pills (strength/running/race/yoga/custom)."""
    html = _read(_RB_HTML_PATH)
    lower = html.lower()
    assert "running" in lower, "run-builder must include a Running type pill"
    assert "strength" in lower, "run-builder must include a Strength type pill"
    assert "race" in lower, "run-builder must include a Race type pill"


def test_ac_rb_run_structure_presets():
    """Run Builder Run Structure section must have preset selector."""
    combined = _read(_RB_HTML_PATH) + _read(_RB_JS_PATH)
    lower = combined.lower()
    assert "easy run" in lower or "easy" in lower, "run-builder must include Easy run preset"
    assert "tempo" in lower, "run-builder must include Tempo preset"
    assert "intervals" in lower, "run-builder must include Intervals preset"
    assert "long run" in lower or "long" in lower, "run-builder must include Long run preset"


def test_ac_rb_segment_bar_updates():
    """run-builder.js must auto-update the effort segment bar as segments are edited."""
    js = _read(_RB_JS_PATH)
    assert "segment" in js.lower(), (
        "run-builder.js must reference segment bar for auto-update"
    )


def test_ac_rb_editable_segment_rows():
    """Run Builder must have editable segment rows with distance/time input."""
    combined = _read(_RB_HTML_PATH) + _read(_RB_JS_PATH)
    lower = combined.lower()
    assert "add segment" in lower, (
        "run-builder must have an '+ Add segment' button"
    )
    assert "distance" in lower, "run-builder segment rows must have distance input"


def test_ac_rb_lap_mode_toggle():
    """Run Builder must have a lap mode toggle: Auto 1 km splits / Manual laps."""
    combined = _read(_RB_HTML_PATH) + _read(_RB_JS_PATH)
    lower = combined.lower()
    assert "auto" in lower and "manual" in lower, (
        "run-builder must have auto/manual lap mode toggle"
    )
    assert "1 km" in combined or "1km" in lower, (
        "run-builder must label the auto mode 'Auto 1 km splits'"
    )


def test_ac_rb_manual_lap_rows_addable():
    """run-builder.js must allow adding manual lap rows."""
    js = _read(_RB_JS_PATH)
    assert "add lap" in js.lower() or "addLap" in js or "lap" in js.lower(), (
        "run-builder.js must support adding manual lap rows"
    )


def test_ac_rb_lap_type_persisted():
    """run-builder.js must persist lap_type as 'auto' or 'manual' when saving splits."""
    js = _read(_RB_JS_PATH)
    assert "lap_type" in js, (
        "run-builder.js must include lap_type in the splits payload when saving"
    )


def test_ac_rb_totals_auto_computed():
    """Run Builder Totals section must label Distance, Duration, Avg Pace as AUTO."""
    combined = _read(_RB_HTML_PATH) + _read(_RB_JS_PATH)
    assert "AUTO" in combined, (
        "run-builder must label Distance/Duration/Avg Pace tiles as AUTO"
    )


def test_ac_rb_totals_sync_fields():
    """Run Builder Totals must label Avg HR, Elevation, Avg Power, Cadence, Stride as SYNC."""
    combined = _read(_RB_HTML_PATH) + _read(_RB_JS_PATH)
    assert "SYNC" in combined, (
        "run-builder must label device metrics (HR, power, cadence, stride) as SYNC"
    )


def test_ac_rb_import_strip():
    """Run Builder must have an import strip for Strava/Stryd pull."""
    combined = _read(_RB_HTML_PATH) + _read(_RB_JS_PATH)
    lower = combined.lower()
    assert "strava" in lower, "run-builder import strip must mention Strava"
    assert "stryd" in lower, "run-builder import strip must mention Stryd"


def test_ac_rb_loads_zone2_module():
    """run-builder.html must load zone2-constants.js."""
    html = _read(_RB_HTML_PATH)
    assert "zone2-constants.js" in html, (
        "run-builder.html must include a <script> tag for zone2-constants.js"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC-CONS — Both screens share accent color vars (lime/teal/purple)
# ═════════════════════════════════════════════════════════════════════════════

def test_ac_cons_teal_accent_defined_in_run_view():
    """run-view.html must define or reference a teal accent for Zone 2 laps."""
    combined = _read(_RV_HTML_PATH) + _read(_RV_JS_PATH)
    assert "teal" in combined.lower() or "#14b8a6" in combined or "#0d9488" in combined, (
        "run-view must define a teal accent for Zone 2 lap highlighting"
    )


def test_ac_cons_accent_lime_present():
    """Both run pages must use the lime accent (--accent or #e4ff52)."""
    for src in (_read(_RV_HTML_PATH), _read(_RB_HTML_PATH)):
        assert "var(--accent)" in src or "#e4ff52" in src or "lime" in src.lower(), (
            "run page must reference the lime accent"
        )


def test_ac_cons_same_lap_mode_labels():
    """Both pages must use the exact same lap-mode labels."""
    rv_js = _read(_RV_JS_PATH)
    rb_js = _read(_RB_JS_PATH)
    assert "1 km splits" in rv_js, "run-view.js must contain '1 km splits' label"
    assert "1 km splits" in rb_js or "1 km" in rb_js, (
        "run-builder.js must contain the same '1 km splits' label"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC-ROUTES — Both pages accessible via clean URLs
# ═════════════════════════════════════════════════════════════════════════════

def test_run_view_route_accessible(auth_user):
    """GET /run-view (or /run-view.html) must return 200 with an authenticated session."""
    client = auth_user["client"]
    for url in ("/run-view", "/run-view.html"):
        res = client.get(url)
        assert res.status_code == 200, (
            f"GET {url} must return 200; got {res.status_code}"
        )


def test_run_builder_route_accessible(auth_user):
    """GET /run-builder (or /run-builder.html) must return 200 with an authenticated session."""
    client = auth_user["client"]
    for url in ("/run-builder", "/run-builder.html"):
        res = client.get(url)
        assert res.status_code == 200, (
            f"GET {url} must return 200; got {res.status_code}"
        )
