"""Tests for issue #530: Normalize Strava source attribution across list and detail.

One test (or group) per Acceptance Criterion. The frontend ACs are verified by
source-inspecting frontend/js/training-log.js (the same pattern used by
test_fix_empty_catch_block_home__397.py); the backend AC is verified by
source-inspecting backend/main.py, asserting the training-log list payload both
declares the `strava_activity_url` key and maps it to the workout's own
`strava_activity_url` column.

ACs:
1. A single `isStravaWorkout(workout)` helper returns true if
   `source === 'strava'` OR `strava_activity_url` is non-empty.
2. The workout list uses this helper to decide the source badge.
3. The workout detail uses the same helper.
4. Both views show a Strava badge for any workout where `strava_activity_url`
   is set, regardless of `source` value.
5. Both views show a manual badge only when `source !== 'strava'` AND
   `strava_activity_url` is absent.
6. No regression: workouts with `source === 'strava'` and no URL still show a
   Strava badge in both views.
7. Backend field `strava_activity_url` is included in the list response payload.
"""
import pathlib
import re

REPO = pathlib.Path(__file__).parents[1]
TRAINING_LOG_JS = REPO / "frontend" / "js" / "training-log.js"
MAIN_PY = REPO / "backend" / "main.py"


def _js():
    return TRAINING_LOG_JS.read_text()


def _helper_body():
    """Return the body of the isStravaWorkout function (best-effort brace match)."""
    text = _js()
    m = re.search(r"function\s+isStravaWorkout\s*\([^)]*\)\s*\{", text)
    assert m, "isStravaWorkout function declaration not found"
    start = m.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
        i += 1
    return text[start : i - 1]


# ── AC1: single helper, OR semantics ───────────────────────────────────────
def test_ac1_helper_defined():
    assert re.search(r"function\s+isStravaWorkout\s*\(", _js()), (
        "AC1: expected a single `isStravaWorkout(workout)` helper function."
    )


def test_ac1_helper_checks_source_strava():
    body = _helper_body()
    assert re.search(r"source\s*===\s*['\"]strava['\"]", body), (
        "AC1: helper must return true when source === 'strava'."
    )


def test_ac1_helper_checks_strava_activity_url():
    body = _helper_body()
    assert "strava_activity_url" in body, (
        "AC1: helper must consider strava_activity_url being non-empty."
    )


def test_ac1_helper_uses_or():
    body = _helper_body()
    assert "||" in body, (
        "AC1: helper must OR the two conditions (source === 'strava' OR "
        "strava_activity_url non-empty)."
    )


# ── AC2: list badge uses the helper ─────────────────────────────────────────
def test_ac2_list_badge_uses_helper():
    assert re.search(r"isStravaWorkout\s*\(\s*w\s*\)", _js()), (
        "AC2: the workout list must call isStravaWorkout(w) to decide the badge."
    )


def test_ac2_list_no_bare_source_check():
    assert "var isStrava = (w.source === 'strava');" not in _js(), (
        "AC2: the list must not decide the Strava badge with a bare "
        "`w.source === 'strava'` check — use isStravaWorkout(w)."
    )


# ── AC3: detail badge uses the same helper ──────────────────────────────────
def test_ac3_detail_badge_uses_helper():
    assert re.search(r"isStravaWorkout\s*\(\s*workout\s*\)", _js()), (
        "AC3: the workout detail must call isStravaWorkout(workout)."
    )


def test_ac3_detail_no_bare_source_check():
    assert "var dpIsStrava = (workout.source === 'strava');" not in _js(), (
        "AC3: the detail badge must not use a bare `workout.source === 'strava'` "
        "check — use isStravaWorkout(workout)."
    )


# ── AC4/5/6: badge selection semantics are centralized in one helper ────────
# These behavioral ACs are guaranteed structurally: both views route through the
# single helper (AC2/AC3) whose OR/AND semantics are pinned by AC1. The helper
# returning true on URL-only workouts (AC4) and false only when neither holds
# (AC5/manual), while still true for source-only Strava (AC6), follows directly.
def test_ac4_ac6_both_views_share_one_helper():
    js = _js()
    assert len(re.findall(r"function\s+isStravaWorkout\s*\(", js)) == 1, (
        "Expected exactly one isStravaWorkout helper shared by both views."
    )
    assert re.search(r"isStravaWorkout\s*\(\s*w\s*\)", js), "list must use helper"
    assert re.search(r"isStravaWorkout\s*\(\s*workout\s*\)", js), "detail must use helper"


# ── AC7: backend list payload includes strava_activity_url ──────────────────
def _workout_entries_block():
    """Return the source of the `workout_entries = [...]` list-comprehension."""
    text = MAIN_PY.read_text()
    m = re.search(r"workout_entries\s*=\s*\[", text)
    assert m, "workout_entries list-comprehension not found in backend/main.py"
    # Walk to the matching close bracket of the comprehension.
    start = m.end()
    depth = 1
    i = start
    while i < len(text) and depth > 0:
        if text[i] == "[":
            depth += 1
        elif text[i] == "]":
            depth -= 1
        i += 1
    return text[start : i - 1]


def test_ac7_list_payload_declares_strava_url_key():
    block = _workout_entries_block()
    assert '"strava_activity_url"' in block, (
        "AC7: the training-log list payload must include a strava_activity_url key."
    )


def test_ac7_list_payload_maps_strava_url_value():
    block = _workout_entries_block()
    assert re.search(
        r'"strava_activity_url"\s*:\s*w\.strava_activity_url', block
    ), (
        "AC7: strava_activity_url in the list payload must map to the workout's "
        "own w.strava_activity_url column (so url-only Strava workouts surface it)."
    )
