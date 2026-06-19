"""Tests for issue #644: Build STRENGTH body for Log-workout slide-over panel."""
import os
import re
import uuid
import pytest
import httpx
from sqlalchemy.orm import Session as _OrmSess
from backend.auth import hash_password as _hash_pw
from backend.db import engine as _engine
from backend.models import User as _UserModel

BASE_URL = (
    os.environ.get("UAT_BASE_URL")
    or "http://localhost:" + os.environ.get("UAT_PORT", "")
)
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

_TEST_PW = "tester644-str-pw"


@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture(scope="module")
def test_user(client):
    name = f"tester644_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    pw_hash = _hash_pw(_TEST_PW)
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(uid))
        u.password_hash = pw_hash
        db.commit()
    yield uid
    client.delete(f"/api/users/{uid}")


@pytest.fixture(scope="module")
def session_cookie(client, test_user):
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(test_user))
        name = u.name
    res = client.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, res.text
    return res.cookies.get("session")


@pytest.fixture(scope="module")
def csrf_token_and_session(client, test_user):
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(test_user))
        name = u.name
    res = client.post("/api/auth/login", json={"username": name, "password": _TEST_PW})
    assert res.status_code == 200, res.text
    session = res.cookies.get("session", "")
    csrf = ""
    for sc in res.headers.get_list("set-cookie"):
        if sc.startswith("csrf-token="):
            csrf = sc.split("=", 1)[1].split(";")[0]
            break
    return session, csrf


@pytest.fixture(scope="module")
def auth_client(session_cookie):
    with httpx.Client(base_url=BASE_URL, timeout=10.0, follow_redirects=True) as c:
        c.cookies.set("session", session_cookie)
        yield c


@pytest.fixture(scope="module")
def page_html(auth_client):
    r = auth_client.get("/log")
    assert r.status_code == 200
    return r.text


@pytest.fixture(scope="module")
def js_training(auth_client):
    r = auth_client.get("/js/training.js")
    assert r.status_code == 200, f"Could not fetch training.js: {r.status_code}"
    return r.text


# ── AC1: STRENGTH mode renders set-by-set exercise builder ─────────────────

def test_strength_body_exercises_tbody_present(page_html):
    """AC1: The exercise builder container (#exercises-tbody) is in the slide-over DOM."""
    assert "exercises-tbody" in page_html, (
        "Expected #exercises-tbody in training-log.html inside the slide-over form"
    )


def test_strength_body_exercises_section_class(page_html):
    """AC1: The exercises container has the .exercises-section class for visibility toggling."""
    assert "exercises-section" in page_html, (
        "Expected .exercises-section class on the exercises wrapper in training-log.html"
    )


def test_strength_body_type_content_area(page_html):
    """AC1: The exercises section is wrapped in a type-content-area or exercises-section for AC compatibility."""
    # Satisfies both the new AC (exercises-section) and the AC7 check from #643
    assert (
        "type-body-placeholder" in page_html
        or "workout-type-body" in page_html
        or "type-content-area" in page_html
        or "exercises-section" in page_html
    ), "Expected type-content-area, exercises-section, or workout-type-body in HTML"


def test_strength_body_exercise_name_datalist(page_html):
    """AC1 + AC5: The exercise-name-suggestions datalist is present for autocomplete."""
    assert "exercise-name-suggestions" in page_html, (
        "Expected datalist#exercise-name-suggestions inside the slide-over form"
    )


def test_strength_body_type_select_wiring_in_js(js_training):
    """AC1: JS wires the #workout-type select to show/hide the exercises section."""
    # The select change should trigger updateRunVisibility or similar
    assert "workout-type" in js_training, "Expected workout-type referenced in training.js"
    # Either by change event or by select element handling
    assert (
        "change" in js_training and "workout-type" in js_training
    ) or "getSelectedType" in js_training, (
        "Expected change event or getSelectedType for #workout-type in training.js"
    )


# ── AC2: Colored RPE bullet per exercise card ──────────────────────────────

def test_strength_body_rpe_bullet_in_js(js_training):
    """AC2: Each exercise card renders a colored RPE-tier bullet."""
    assert "ex-rpe-bullet" in js_training, (
        "Expected 'ex-rpe-bullet' class in training.js for the RPE-tier colored bullet"
    )


def test_strength_body_rpe_tier_colors_in_js(js_training):
    """AC2: RPE bullet color classes implement ≤6=green, 7-8=amber, 9-10=red tiers."""
    assert "ex-rpe-green" in js_training, "Expected ex-rpe-green class in training.js"
    assert "ex-rpe-amber" in js_training, "Expected ex-rpe-amber class in training.js"
    assert "ex-rpe-red" in js_training, "Expected ex-rpe-red class in training.js"
    # Check the boundary at 6 for green/amber split
    assert "<= 6" in js_training or "<= 6.0" in js_training or "<= 6)" in js_training or "maxRpe <= 6" in js_training, (
        "Expected RPE ≤6 boundary for green tier in training.js"
    )
    # Check the boundary at 8 for amber/red split
    assert "<= 8" in js_training or "maxRpe <= 8" in js_training, (
        "Expected RPE ≤8 boundary for amber tier in training.js"
    )


def test_strength_body_rpe_bullet_css(page_html):
    """AC2: CSS defines the three RPE bullet tier colors using design system tokens."""
    assert "ex-rpe-bullet" in page_html, "Expected .ex-rpe-bullet CSS in training-log.html or training-form.css"
    assert "ex-rpe-green" in page_html, "Expected .ex-rpe-green CSS"
    assert "ex-rpe-amber" in page_html, "Expected .ex-rpe-amber CSS"
    assert "ex-rpe-red" in page_html, "Expected .ex-rpe-red CSS"


# ── AC3: Set rows with weight, reps, RPE, rest ─────────────────────────────

def test_strength_body_set_row_fields_in_js(js_training):
    """AC3: Each set row captures weight, reps, RPE (1-10), and rest."""
    assert "set-weight" in js_training, "Expected .set-weight input class in training.js"
    assert "set-reps" in js_training, "Expected .set-reps input class in training.js"
    assert "set-rpe" in js_training, "Expected .set-rpe input class in training.js"
    assert "set-rest" in js_training, "Expected .set-rest input class in training.js"


def test_strength_body_rpe_range_validation_in_js(js_training):
    """AC3: RPE field is bounded 1–10."""
    # The input has min/max attributes set to 1 and 10
    assert 'min="1"' in js_training and 'max="10"' in js_training, (
        "Expected min=1 max=10 on RPE input in training.js"
    )


# ── AC4: Add Set / remove (×) per row ─────────────────────────────────────

def test_strength_body_add_set_button_in_js(js_training):
    """AC4: An Add Set button appends a new blank set row to the exercise."""
    assert "add-set" in js_training, "Expected 'add-set' class/text in training.js"
    assert "Add set" in js_training, "Expected 'Add set' label text in training.js"


def test_strength_body_remove_set_button_in_js(js_training):
    """AC4: A remove (×) control on each row deletes that set."""
    assert "set-x" in js_training, "Expected .set-x remove button in training.js"


def test_strength_body_set_x_disabled_when_one_set(js_training):
    """AC4: Remove (×) is disabled when only one set remains."""
    # Check for the guard pattern: disabled when rows.length <= 1
    assert "rows.length <= 1" in js_training or "length <= 1" in js_training or "length < 2" in js_training, (
        "Expected set-x disable guard when only 1 set remains in training.js"
    )
    assert "disabled" in js_training, "Expected .disabled property set on set-x when 1 set"


# ── AC5: Add Exercise uses existing exercise persistence layer ─────────────

def test_strength_body_add_exercise_button_present(page_html):
    """AC5: An Add Exercise button is present in the slide-over."""
    assert "add-exercise-btn" in page_html, (
        "Expected #add-exercise-btn inside the slide-over form in training-log.html"
    )
    assert "Add exercise" in page_html, "Expected 'Add exercise' label text"


def test_strength_body_exercise_names_api(auth_client):
    """AC5: GET /api/exercises/names returns a list for the exercise autocomplete."""
    r = auth_client.get("/api/exercises/names")
    assert r.status_code == 200, f"Expected 200 from /api/exercises/names: {r.text}"
    assert isinstance(r.json(), list), "Expected list from /api/exercises/names"


# ── AC6: Remove exercise card with confirmation ────────────────────────────

def test_strength_body_exercise_remove_in_js(js_training):
    """AC6: A remove control on the exercise card deletes the entire exercise."""
    assert "ex-remove" in js_training, "Expected .ex-remove button in training.js"


def test_strength_body_exercise_remove_confirmation_in_js(js_training):
    """AC6: Confirmation is shown before removing an exercise card with data."""
    assert "confirm(" in js_training, (
        "Expected confirm() dialog before removing exercise card with set data"
    )
    # The confirmation should guard the exercise remove
    remove_idx = js_training.find("ex-remove")
    confirm_idx = js_training.find("confirm(")
    assert confirm_idx != -1 and abs(confirm_idx - remove_idx) < 800, (
        "Expected confirm() near the ex-remove handler in training.js"
    )


# ── AC7: Auto-totals bar ──────────────────────────────────────────────────

def test_strength_body_total_volume_element(page_html):
    """AC7: Auto-totals bar shows Total Volume (sum of weight × reps)."""
    assert "str-volume" in page_html, "Expected #str-volume in training-log.html"


def test_strength_body_total_sets_element(page_html):
    """AC7: Auto-totals bar shows Total Sets."""
    assert "str-sets" in page_html, "Expected #str-sets in training-log.html"


def test_strength_body_estimated_1rm_element(page_html):
    """AC7: Auto-totals bar shows Estimated 1RM."""
    assert "str-e1rm" in page_html, "Expected #str-e1rm in training-log.html"


def test_strength_body_epley_formula_in_js(js_training):
    """AC7: Estimated 1RM uses the Epley formula (weight × (1 + reps / 30))."""
    # Epley: e1RM = weight * (1 + reps/30)
    assert "1 + topReps / 30" in js_training or "1 + reps / 30" in js_training or "reps/30" in js_training, (
        "Expected Epley 1RM formula (1 + reps/30) in training.js"
    )


def test_strength_body_volume_formula_in_js(js_training):
    """AC7: Total Volume is computed as sum of weight × reps across all sets."""
    assert "w * reps" in js_training or "weight * reps" in js_training, (
        "Expected weight × reps multiplication for volume in training.js"
    )


# ── AC8: Read-only session-profile bar ────────────────────────────────────

def test_strength_body_profile_bar_element(page_html):
    """AC8: A read-only session-profile bar (#str-profile) is present."""
    assert "str-profile" in page_html, (
        "Expected #str-profile element in training-log.html"
    )


def test_strength_body_profile_bar_in_js(js_training):
    """AC8: renderStrengthProfile() renders the profile bar from JS."""
    assert "renderStrengthProfile" in js_training, (
        "Expected renderStrengthProfile function in training.js"
    )
    assert "str-profile" in js_training, "Expected getElementById('str-profile') in training.js"


def test_strength_body_profile_bar_width_encodes_duration(js_training):
    """AC8: Block width encodes cumulative set duration (reps × TUT heuristic + rest)."""
    # The profile block width computation: reps * TUT + rest
    assert "reps * " in js_training or "reps ×" in js_training, (
        "Expected reps-based duration calculation for profile bar block width in training.js"
    )


# ── AC9: Profile bar blocks colored by RPE tier ──────────────────────────

def test_strength_body_profile_rpe_classes_in_js(js_training):
    """AC9: Profile bar blocks use RPE-tier CSS classes (rpe-low/mid/high/max)."""
    assert "rpe-low" in js_training, "Expected 'rpe-low' class in training.js profile bar"
    assert "rpe-mid" in js_training, "Expected 'rpe-mid' class in training.js profile bar"
    assert "rpe-high" in js_training, "Expected 'rpe-high' class in training.js profile bar"
    assert "rpe-max" in js_training, "Expected 'rpe-max' class in training.js profile bar"


def test_strength_body_profile_rpe_css(page_html):
    """AC9: CSS defines the RPE profile bar segment classes."""
    # These are in training-form.css which is included by training-log.html
    assert "rpe-low" in page_html or "rpe-mid" in page_html, (
        "Expected RPE tier CSS classes in training-log.html (via training-form.css)"
    )


# ── AC10: Styling follows gradient theme ──────────────────────────────────

def test_strength_body_uses_design_tokens(page_html):
    """AC10: Styling uses design system tokens (no hard-coded pixel values for colours)."""
    # Design tokens used in the exercises section
    gradient_tokens = [
        "var(--card-border", "var(--card-bg", "var(--text-primary",
        "var(--rl-tile", "var(--card-shadow", "var(--text-tertiary",
    ]
    assert any(tok in page_html for tok in gradient_tokens), (
        "Expected gradient/card design tokens in training-log.html for the strength body"
    )


# ── AC11: Exercise data saved through existing persistence service ─────────

def test_strength_body_save_workout_with_exercises(csrf_token_and_session):
    """AC11: Exercise data is saved through the existing workout + exercises endpoint."""
    session, csrf = csrf_token_and_session
    headers = {"X-CSRF-Token": csrf}

    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        c.cookies.set("session", session)
        c.cookies.set("csrf-token", csrf)

        payload = {
            "name": "Test Strength 644",
            "workout_date": "2026-06-19",
            "workout_type": "Strength",
            "exercises": [
                {
                    "name": "Barbell Back Squat",
                    "sets": 2,
                    "reps": 5,
                    "weight_kg": 100,
                    "rpe": 8,
                    "sets_json": '[{"type":"working","weight":100,"reps":5,"rpe":8,"rest":180},'
                                 '{"type":"working","weight":100,"reps":5,"rpe":9,"rest":180}]',
                }
            ],
        }
        r = c.post("/api/workouts", json=payload, headers=headers)
        assert r.status_code == 201, f"Create workout with exercises failed: {r.text}"
        data = r.json()
        wid = data["id"]

        assert data.get("name") == "Test Strength 644"
        exercises = data.get("exercises", [])
        assert len(exercises) == 1, f"Expected 1 exercise, got {len(exercises)}"
        assert exercises[0]["name"] == "Barbell Back Squat"
        assert exercises[0]["weight_kg"] == 100

        # Verify it can be retrieved
        r2 = c.get(f"/api/workouts/{wid}")
        assert r2.status_code == 200, f"Retrieve workout failed: {r2.text}"
        exs = r2.json().get("exercises", [])
        assert len(exs) == 1
        assert exs[0]["sets_json"] is not None, "Expected sets_json to be persisted"

        # Cleanup
        c.delete(f"/api/workouts/{wid}", headers=headers)


# ── AC12: Responsive on mobile ≥ 320px ────────────────────────────────────

def test_strength_body_responsive_css(page_html):
    """AC12: The exercise builder is responsive — CSS includes mobile breakpoints."""
    # Check that a mobile media query exists for the set rows
    assert "@media" in page_html, "Expected @media queries for responsiveness"
    # Check 320px or 560px breakpoint for the exercise grid
    assert (
        "320px" in page_html or "560px" in page_html or "599px" in page_html or "767px" in page_html
    ), "Expected a mobile breakpoint (320, 560, 599, or 767px) in training-log.html"


def test_strength_body_set_cols_responsive(page_html):
    """AC12: Set row grid adapts on small screens — max-width 560px media query present."""
    # training-form.css defines @media (max-width: 560px) { .set-cols, .set-row { ... } }
    assert "set-cols" in page_html or "set-row" in page_html, (
        "Expected .set-cols / .set-row in training-form.css (included by training-log.html)"
    )


# ── AC13: Incomplete rows visually flagged ────────────────────────────────

def test_strength_body_incomplete_row_flagging_in_js(js_training):
    """AC13: Incomplete rows (weight XOR reps) are visually flagged with a CSS class."""
    assert "is-incomplete" in js_training, (
        "Expected 'is-incomplete' class toggled on incomplete set rows in training.js"
    )


def test_strength_body_incomplete_row_excluded_from_totals(js_training):
    """AC13: Incomplete rows are excluded from volume/sets/1RM calculations."""
    # The recomputeStrengthTotals should only count rows where both weight AND reps are present
    # Evidence: the flag check guards the accumulation
    assert "is-incomplete" in js_training and (
        "hasW" in js_training or "hasR" in js_training or "isFinite" in js_training
    ), (
        "Expected both incomplete-row flagging and finite-value guarding in training.js"
    )


def test_strength_body_incomplete_css(page_html):
    """AC13: CSS defines the visual style for .is-incomplete rows."""
    assert "is-incomplete" in page_html, (
        "Expected .is-incomplete CSS in training-form.css (included by training-log.html)"
    )


# ── Regression: slide-over panel still works for existing AC from #643 ────

def test_strength_body_panel_still_has_basics(page_html):
    """Regression: workout basics (name, date, type, remarks) still render in the panel."""
    assert 'id="workout-name"' in page_html, "workout-name must remain"
    assert 'id="workout-date"' in page_html, "workout-date must remain"
    assert 'id="workout-type"' in page_html, "workout-type must remain"
    assert 'id="workout-remarks"' in page_html, "workout-remarks must remain"


def test_strength_body_save_cancel_still_present(page_html):
    """Regression: Save/Cancel action buttons are still present."""
    assert "dp-save-btn" in page_html
    assert "dp-cancel-btn" in page_html


def test_strength_body_exercises_names_endpoint_returns_list(auth_client):
    """Regression: /api/exercises/names still works after implementation."""
    r = auth_client.get("/api/exercises/names")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
