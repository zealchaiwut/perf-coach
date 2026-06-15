"""Tests for issue #526: Add manual split authoring to training log detail panel.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance criteria:
  AC1 — Detail panel for a manual run shows an **Add Split** control when no
        splits exist.
  AC2 — User can enter distance, duration, and pace per split row; fields
        validate against the existing splits endpoint contract (non-zero
        distance, valid duration format, splits sum <= total workout distance).
  AC3 — Submitting valid splits calls POST /api/workouts/{id}/splits and the
        response is reflected immediately without a full page reload.
  AC4 — Saved splits render in the same table component used for synced runs
        (no separate UI path).
  AC5 — Existing split rows can be edited in-place and re-saved.
  AC6 — An individual split row can be deleted.
  AC7 — Validation errors surface inline (field-level) with a message matching
        the API error response.
  AC8 — Synced-run splits remain read-only (no edit/delete controls rendered).

This is a frontend-only ticket (the splits endpoint contract and schema are
explicitly out of scope). Frontend wiring ACs are verified by static analysis
of the page/JS source (same style as #525/#522/#130). AC2/AC3 are additionally
backed by a live-server round-trip against the existing splits endpoint, since
the manual editor's persistence path is exactly POST .../splits (full replace).
"""
import datetime
import os
import pathlib
import re
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine
from sqlalchemy.orm import Session as DBSession

from backend.auth import (
    CSRF_COOKIE_NAME,
    generate_csrf_token,
    hash_password,
)
from backend.models import User

# ── Source under test ────────────────────────────────────────────────────────
_ROOT = pathlib.Path(__file__).resolve().parents[1]
_LOG_HTML = (_ROOT / "frontend" / "pages" / "training-log.html").read_text()
_LOG_JS = (_ROOT / "frontend" / "js" / "training-log.js").read_text()


def _js_func(src, name):
    """Return exactly one JS function body (brace-matched), so assertions never
    bleed into the following function."""
    sig = "function " + name
    start = src.find(sig)
    assert start != -1, f"{sig!r} not found"
    brace = src.find("{", start)
    depth = 0
    for i in range(brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start: i + 1]
    return src[start:]


# ═════════════════════════════════════════════════════════════════════════════
# Static analysis — frontend wiring
# ═════════════════════════════════════════════════════════════════════════════

# ─────────────────────────────────────────────────────────────────────────────
# AC1 — Add Split control shown for a manual run when no splits exist
# ─────────────────────────────────────────────────────────────────────────────

def test_ac1_splits_editor_mounts_for_manual_cardio():
    """renderDetailContent must mount the editable splits editor for a manual
    run/bike (not just when splits already exist)."""
    body = _js_func(_LOG_JS, "renderDetailContent")
    # Manual = not strava and not stryd.
    assert "dpIsManual" in body, (
        "renderDetailContent must distinguish manual workouts (dpIsManual)"
    )
    assert "mountSplitsEditor" in body, (
        "renderDetailContent must call mountSplitsEditor for editable splits"
    )


def test_ac1_add_split_control_present_with_no_splits():
    """The editor must render an Add Split control even when there are zero
    splits (the empty-state entry point)."""
    editor = _js_func(_LOG_JS, "mountSplitsEditor")
    assert "dp-split-add" in editor, (
        "editor must render a dp-split-add control as the Add Split entry point"
    )
    assert re.search(r"Add\s+[Ss]plit", editor), (
        "editor must label the entry-point control 'Add Split'"
    )


def test_ac1_editor_only_for_manual_not_synced():
    """The editable mount must be gated so synced runs never get the editor."""
    body = _js_func(_LOG_JS, "renderDetailContent")
    assert re.search(r"splitsEditable\s*=", body), (
        "renderDetailContent must compute a splitsEditable gate"
    )
    # The gate must require manual (dpIsManual) — synced workouts excluded.
    gate_idx = body.find("splitsEditable")
    snippet = body[gate_idx: gate_idx + 200]
    assert "dpIsManual" in snippet, (
        "splitsEditable gate must require dpIsManual (synced excluded)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC2 — Enter distance/duration/pace; client-side validation
# ─────────────────────────────────────────────────────────────────────────────

def test_ac2_editor_has_distance_and_duration_inputs():
    editor = _js_func(_LOG_JS, "mountSplitsEditor")
    assert "dp-split-dist-input" in editor, (
        "editor must render a distance input per editable row"
    )
    assert "dp-split-dur-input" in editor, (
        "editor must render a duration input per editable row"
    )


def test_ac2_duration_parsed_from_mmss_format():
    """A valid duration format (m:ss) must be parsed to seconds before submit."""
    assert "function parseDurationStr" in _LOG_JS, (
        "training-log.js must define parseDurationStr to validate the m:ss format"
    )
    parse = _js_func(_LOG_JS, "parseDurationStr")
    # Rejects malformed input by returning null; accepts colon-separated m:ss.
    assert "null" in parse and ":" in parse, (
        "parseDurationStr must reject malformed durations (null) and split on ':'"
    )


def test_ac2_validates_nonzero_distance():
    editor = _js_func(_LOG_JS, "mountSplitsEditor")
    # A non-zero distance guard must exist (distance must be > 0).
    assert re.search(r"distance[^\n]*<=\s*0|<=\s*0[^\n]*distance|dist[A-Za-z]*\s*<=\s*0", editor), (
        "editor must reject a zero/negative distance (non-zero distance rule)"
    )


def test_ac2_validates_sum_not_exceeding_total_distance():
    """The sum of split distances must not exceed the workout's total distance."""
    editor = _js_func(_LOG_JS, "mountSplitsEditor")
    assert "totalKm" in editor, (
        "editor must reference the workout total distance (totalKm) for the sum rule"
    )
    # There must be a comparison of accumulated split distance against the total.
    assert re.search(r">\s*totalKm", editor), (
        "editor must reject splits whose sum exceeds totalKm"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC3 — Submitting valid splits POSTs and reflects immediately (no reload)
# ─────────────────────────────────────────────────────────────────────────────

def test_ac3_editor_posts_to_splits_endpoint():
    editor = _js_func(_LOG_JS, "mountSplitsEditor")
    assert "/splits" in editor and "POST" in editor, (
        "editor must POST to the workout splits endpoint"
    )
    assert "workout.id" in editor, (
        "editor must target POST /api/workouts/{workout.id}/splits"
    )


def test_ac3_no_full_page_reload_on_save():
    """Save must update in place — never window.location reload."""
    editor = _js_func(_LOG_JS, "mountSplitsEditor")
    assert "location.reload" not in editor, (
        "editor must not trigger a full page reload on save"
    )
    # It re-renders the editor in place after a successful save.
    assert "render(" in editor, (
        "editor must re-render in place after a successful save"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC4 — Saved splits render in the same table component as synced runs
# ─────────────────────────────────────────────────────────────────────────────

def test_ac4_reuses_synced_split_table_classes():
    """The editor must reuse the synced table component classes (dp-splits /
    dp-split-row), not a separate UI path."""
    editor = _js_func(_LOG_JS, "mountSplitsEditor")
    assert "dp-split-row" in editor, (
        "editor must render rows with the shared dp-split-row class"
    )
    assert "dp-splits" in editor, (
        "editor must use the shared dp-splits table container"
    )


def test_ac4_editor_css_present():
    """The editable variant must have supporting CSS in the page."""
    assert "dp-splits--editable" in _LOG_HTML, (
        "training-log.html must style the editable splits variant"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC5 — Existing rows edit in-place and re-save
# ─────────────────────────────────────────────────────────────────────────────

def test_ac5_rows_have_edit_control():
    editor = _js_func(_LOG_JS, "mountSplitsEditor")
    assert "dp-split-edit" in editor, (
        "editor must render an in-place edit control per saved row"
    )


def test_ac5_edit_state_tracked():
    """Editing must be tracked so a row can switch to an editable form in place."""
    editor = _js_func(_LOG_JS, "mountSplitsEditor")
    assert "editing" in editor, (
        "editor must track an editing index for in-place row editing"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC6 — A split row can be deleted
# ─────────────────────────────────────────────────────────────────────────────

def test_ac6_rows_have_delete_control():
    editor = _js_func(_LOG_JS, "mountSplitsEditor")
    assert "dp-split-delete" in editor, (
        "editor must render a delete control per saved row"
    )


def test_ac6_delete_removes_row_and_persists():
    """Delete must remove the row from the working set and persist the result."""
    editor = _js_func(_LOG_JS, "mountSplitsEditor")
    # splice out the row, then persist the new set.
    assert "splice" in editor, (
        "editor delete must splice the row out of the working set"
    )
    assert "persist" in editor, (
        "editor must persist after a delete (POST the remaining splits)"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC7 — Validation errors surface inline (field-level), matching API message
# ─────────────────────────────────────────────────────────────────────────────

def test_ac7_inline_error_element_rendered():
    editor = _js_func(_LOG_JS, "mountSplitsEditor")
    assert "dp-split-error" in editor, (
        "editor must render an inline field-level error element"
    )


def test_ac7_surfaces_api_detail_on_rejection():
    """A server rejection must surface the API's detail message inline (not a
    generic string), matching the API error response."""
    editor = _js_func(_LOG_JS, "mountSplitsEditor")
    assert ".detail" in editor, (
        "editor must surface the API error response detail inline on rejection"
    )


def test_ac7_error_css_present():
    assert "dp-split-error" in _LOG_HTML, (
        "training-log.html must style the inline split error element"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC8 — Synced-run splits remain read-only (no edit/delete controls)
# ─────────────────────────────────────────────────────────────────────────────

def test_ac8_synced_path_has_no_edit_delete_controls():
    """The synced (read-only) render path must not emit edit/delete controls.
    Those live only behind the splitsEditable (manual) gate."""
    body = _js_func(_LOG_JS, "renderDetailContent")
    # Locate the read-only branch: the legacy splitRows builder.
    assert "splitRows" in body, "read-only synced split render must remain"
    # The read-only branch must not include the manual control classes.
    ro_idx = body.find("splitRows +=")
    ro_end = body.find("splitsHtml =", ro_idx)
    ro_snippet = body[ro_idx:ro_end] if ro_idx != -1 and ro_end != -1 else ""
    assert ro_snippet, "could not isolate read-only synced split render branch"
    assert "dp-split-edit" not in ro_snippet, (
        "synced read-only rows must not render an edit control"
    )
    assert "dp-split-delete" not in ro_snippet, (
        "synced read-only rows must not render a delete control"
    )


# ═════════════════════════════════════════════════════════════════════════════
# Live server — round-trip backing the editor's persistence path (AC2/AC3)
# ═════════════════════════════════════════════════════════════════════════════

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9001")
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "manual-splits-526-pw"
TODAY = datetime.date.today()

_env_vals = dotenv_values(_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True) if _uat_url else None


def _make_authed_user(label):
    name = f"ManualSplits526_{label}_{_RUN}"
    with httpx.Client(base_url=BASE, timeout=10) as bare:
        res = bare.post("/api/users", json={"name": name})
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
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        session_cookie = login_res.cookies.get("session")
        assert session_cookie, "Login must set session cookie"

    csrf_token = generate_csrf_token()
    authed = httpx.Client(
        base_url=BASE,
        timeout=10,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return {"id": user_id, "name": name, "client": authed}


@pytest.fixture(scope="module")
def auth_user():
    if engine is None:
        pytest.skip("DATABASE_URL_UAT not configured")
    u = _make_authed_user("main")
    yield u
    u["client"].delete(f"/api/users/{u['id']}")
    u["client"].close()


@pytest.fixture
def manual_run(auth_user):
    """A manual run with a known total distance, used as the splits target."""
    authed = auth_user["client"]
    body = {
        "name": "Manual Splits Run 526",
        "workout_date": TODAY.isoformat(),
        "workout_type": "run",
        "distance_km": 3.0,
        "duration_seconds": 900,
    }
    res = authed.post("/api/workouts", json=body)
    assert res.status_code == 201, res.text
    wid = res.json()["id"]
    yield wid
    authed.delete(f"/api/workouts/{wid}")


def test_ac3_manual_split_roundtrip_persists(auth_user, manual_run):
    """AC3 + UAT step 7: posting splits to a manual run persists and is reflected
    on a subsequent GET (the editor's save/persist path)."""
    authed = auth_user["client"]
    payload = {
        "splits": [
            {"split_index": 1, "distance_km": 1.0, "duration_seconds": 270},
            {"split_index": 2, "distance_km": 1.0, "duration_seconds": 280},
        ]
    }
    res = authed.post(f"/api/workouts/{manual_run}/splits", json=payload)
    assert res.status_code == 201, res.text

    got = authed.get(f"/api/workouts/{manual_run}/splits")
    assert got.status_code == 200, got.text
    rows = got.json()
    assert len(rows) == 2, "both splits must persist"
    assert [r["split_index"] for r in rows] == [1, 2], "ordered by split_index"
    assert int(rows[0]["duration_seconds"]) == 270


def test_ac6_delete_via_full_replace(auth_user, manual_run):
    """AC6: deleting a row is a full-replace POST of the remaining splits — the
    deleted row must be gone on the next GET."""
    authed = auth_user["client"]
    authed.post(
        f"/api/workouts/{manual_run}/splits",
        json={"splits": [
            {"split_index": 1, "distance_km": 1.0, "duration_seconds": 270},
            {"split_index": 2, "distance_km": 1.0, "duration_seconds": 280},
        ]},
    )
    # Re-post with the second split removed (the editor's delete path).
    res = authed.post(
        f"/api/workouts/{manual_run}/splits",
        json={"splits": [
            {"split_index": 1, "distance_km": 1.0, "duration_seconds": 270},
        ]},
    )
    assert res.status_code == 201, res.text
    rows = authed.get(f"/api/workouts/{manual_run}/splits").json()
    assert len(rows) == 1, "deleted split must not persist after full-replace"
