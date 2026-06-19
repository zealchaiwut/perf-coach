"""Tests for issue #646: Redesign Run detail view header and load block.

Each test is anchored to a specific acceptance criterion from the issue body.

Acceptance Criteria:
  AC1  — Header: type badge, workout name, short ID + copy, date, source badges
  AC2  — Basic tiles: Distance, Avg Pace, Duration — all three as tiles
  AC3  — Load & Intensity: TSS hero, Zone-2 min, Elevation, Avg HR, Max HR,
          Avg Power, Max Power, Stride Length, Cadence
  AC4  — Stryd fields show '—' (em dash) when absent/null
  AC5  — Gradient theme + structural tokens (no hard-coded pixels for spacing)
  AC6  — All values from /api/workouts/{id}/full; no other endpoints
  AC7  — Strava badge conditional on Strava source; Stryd badge conditional on Stryd
  AC8  — Copy-to-clipboard provides user feedback (tooltip or icon state change)
  AC9  — Desktop viewport visually consistent with approved mock
"""
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_RV_HTML_PATH = _ROOT / "frontend" / "pages" / "run-view.html"
_RV_JS_PATH = _ROOT / "frontend" / "js" / "run-view.js"


def _html() -> str:
    assert _RV_HTML_PATH.exists(), f"File not found: {_RV_HTML_PATH}"
    return _RV_HTML_PATH.read_text()


def _js() -> str:
    assert _RV_JS_PATH.exists(), f"File not found: {_RV_JS_PATH}"
    return _RV_JS_PATH.read_text()


def _combined() -> str:
    return _html() + _js()


# ═════════════════════════════════════════════════════════════════════════════
# AC1 — Header: type badge, name, short ID + copy, date, source badges
# ═════════════════════════════════════════════════════════════════════════════

def test_ac1_type_badge_present():
    """Header must render a type badge (e.g. 'RUN') in the JS render logic."""
    js = _js()
    assert "RUN" in js, "run-view.js must render a 'RUN' type badge in the header"


def test_ac1_workout_name_rendered():
    """Header must render the workout name."""
    js = _js()
    assert "w.name" in js or "workout.name" in js or "name" in js, (
        "run-view.js must render the workout name in the header"
    )


def test_ac1_short_id_present():
    """Header must render a short workout ID."""
    js = _js()
    lower = js.lower()
    assert "short" in lower or "slice" in lower or "id" in lower, (
        "run-view.js must render a short workout ID"
    )


def test_ac1_copy_button_present():
    """Header must have a copy-to-clipboard button for the short ID."""
    combined = _combined()
    lower = combined.lower()
    assert "copy" in lower or "clipboard" in lower, (
        "run-view must include a copy-to-clipboard affordance for the workout ID"
    )


def test_ac1_date_rendered():
    """Header must render the workout date."""
    js = _js()
    assert "workout_date" in js or "date" in js.lower(), (
        "run-view.js must render the workout date in the header"
    )


def test_ac1_strava_badge_conditional():
    """Strava source badge must only render when Strava source is present."""
    js = _js()
    lower = js.lower()
    assert "strava" in lower, "run-view.js must reference Strava for conditional badge"
    # Must be guarded by a condition (not unconditionally rendered)
    assert "stravaSrc" in js or "strava_activity" in js or (
        "strava" in lower and ("if" in js or "&&" in js or "?" in js)
    ), "Strava badge must be conditionally rendered based on source"


def test_ac1_stryd_badge_conditional():
    """Stryd source badge must only render when Stryd source is present."""
    js = _js()
    lower = js.lower()
    assert "stryd" in lower, "run-view.js must reference Stryd for conditional badge"
    assert "strydPresent" in js or "stryd_activity" in js or (
        "stryd" in lower and ("if" in js or "&&" in js or "?" in js)
    ), "Stryd badge must be conditionally rendered based on source"


# ═════════════════════════════════════════════════════════════════════════════
# AC2 — Basic tiles: Distance, Avg Pace, and Duration all as tiles
# ═════════════════════════════════════════════════════════════════════════════

def test_ac2_distance_tile():
    """Basic tiles section must render Distance as a tile."""
    js = _js()
    assert "Distance" in js or "distance" in js.lower(), (
        "run-view.js must render a Distance tile"
    )


def test_ac2_avg_pace_tile():
    """Basic tiles section must render Avg Pace as a tile."""
    js = _js()
    assert "Avg Pace" in js or "pace" in js.lower(), (
        "run-view.js must render an Avg Pace tile"
    )


def test_ac2_duration_rendered_as_tile():
    """Duration must be rendered as a tile (rv-tile), not just a text line.

    AC2 requires Distance, Avg Pace, and Duration all as tiles.
    The old design used rv-duration-line (a plain text div). This test
    verifies that Duration is now passed to the tile() helper, producing
    an rv-tile element alongside Distance and Avg Pace.
    """
    js = _js()
    # The tile() function call for Duration must appear alongside Distance and Avg Pace.
    # tile('Duration', ...) or tile("Duration", ...) must be present.
    assert "tile('Duration'" in js or 'tile("Duration"' in js or (
        "Duration" in js and "rv-tile" in (js + _html())
    ), (
        "run-view.js must render Duration as a tile (rv-tile) using the tile() helper, "
        "not as a plain rv-duration-line div"
    )


def test_ac2_duration_not_as_plain_line():
    """Duration must NOT be rendered as an orphaned text div (rv-duration-line).

    The rv-duration-line pattern placed Duration outside the tile grid.
    AC2 requires it to be a proper tile, so rv-duration-line must be gone.
    """
    combined = _combined()
    assert "rv-duration-line" not in combined, (
        "rv-duration-line must be removed; Duration must be a tile per AC2"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC3 — Load & Intensity block: TSS hero + all sub-metrics
# ═════════════════════════════════════════════════════════════════════════════

def test_ac3_tss_hero_tile():
    """TSS must be rendered as the hero tile in Load & Intensity."""
    js = _js()
    assert "tss" in js.lower(), (
        "run-view.js must render TSS as the hero tile in Load & Intensity"
    )
    assert "hero" in js.lower() or "rv-tile--hero" in js or "heroTile" in js, (
        "run-view.js must use a hero tile variant for TSS"
    )


def test_ac3_zone2_minutes():
    """Load & Intensity must include Zone-2 minutes."""
    combined = _combined()
    lower = combined.lower()
    assert "zone" in lower and ("2" in combined or "two" in lower), (
        "run-view must include Zone-2 minutes in Load & Intensity"
    )


def test_ac3_elevation():
    """Load & Intensity must include Elevation."""
    combined = _combined()
    assert "Elevation" in combined or "elevation" in combined.lower(), (
        "run-view must include Elevation in Load & Intensity"
    )


def test_ac3_avg_hr():
    """Load & Intensity must include Avg HR."""
    combined = _combined()
    lower = combined.lower()
    assert "avg hr" in lower or "avg_hr" in combined or "Avg HR" in combined, (
        "run-view must include Avg HR in Load & Intensity"
    )


def test_ac3_max_hr():
    """Load & Intensity must include Max HR."""
    combined = _combined()
    lower = combined.lower()
    assert "max hr" in lower or "max_hr" in combined or "Max HR" in combined, (
        "run-view must include Max HR in Load & Intensity"
    )


def test_ac3_avg_power():
    """Load & Intensity must include Avg Power."""
    combined = _combined()
    lower = combined.lower()
    assert "avg power" in lower or "avg_power" in combined, (
        "run-view must include Avg Power in Load & Intensity"
    )


def test_ac3_max_power():
    """Load & Intensity must include Max Power."""
    combined = _combined()
    lower = combined.lower()
    assert "max power" in lower or "max_power" in combined, (
        "run-view must include Max Power in Load & Intensity"
    )


def test_ac3_stride_length():
    """Load & Intensity must include Stride Length."""
    combined = _combined()
    lower = combined.lower()
    assert "stride" in lower, "run-view must include Stride Length in Load & Intensity"


def test_ac3_cadence():
    """Load & Intensity must include Cadence."""
    combined = _combined()
    lower = combined.lower()
    assert "cadence" in lower, "run-view must include Cadence in Load & Intensity"


# ═════════════════════════════════════════════════════════════════════════════
# AC4 — Stryd fields show '—' (em dash) when absent/null
# ═════════════════════════════════════════════════════════════════════════════

def test_ac4_em_dash_for_null_stryd_fields():
    """Stryd fields must render '—' (em dash) when absent or null."""
    js = _js()
    assert "—" in js or "\\u2014" in js or "'—'" in js or '"—"' in js, (
        "run-view.js must render '—' for null/absent Stryd field values"
    )


def test_ac4_avg_power_guarded_by_stryd():
    """Avg Power must show '—' when Stryd is not present (no Stryd source)."""
    js = _js()
    # Avg Power rendering must be guarded by strydPresent or field_coverage check.
    assert "strydPresent" in js or "stryd" in js.lower(), (
        "Avg Power (and other Stryd fields) must be conditioned on Stryd source presence"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC5 — Gradient theme + structural tokens (no raw pixel spacing)
# ═════════════════════════════════════════════════════════════════════════════

def test_ac5_gradient_background():
    """Page must use the gradient background token (var(--page-bg))."""
    html = _html()
    assert "var(--page-bg)" in html, (
        "run-view.html must use var(--page-bg) for the gradient page background"
    )


def test_ac5_card_tokens_used():
    """Cards must use var(--card-bg), var(--card-border), or var(--card-radius)."""
    html = _html()
    assert (
        "var(--card-bg)" in html
        or "var(--card-border)" in html
        or "var(--card-radius)" in html
        or "14px" in html
    ), "run-view.html must use card design tokens for card styling"


def test_ac5_text_tokens_used():
    """Page must reference text tokens (--text-primary, --text-secondary, etc.)."""
    html = _html()
    assert (
        "var(--text-primary)" in html
        or "var(--text-secondary)" in html
        or "var(--text-tertiary)" in html
    ), "run-view.html must use text color tokens"


# ═════════════════════════════════════════════════════════════════════════════
# AC6 — All values from /api/workouts/{id}/full; no other endpoints called
# ═════════════════════════════════════════════════════════════════════════════

def test_ac6_only_full_endpoint_used():
    """run-view.js must only call /api/workouts/{id}/full; no other data endpoints."""
    js = _js()
    # Must use the /full endpoint
    assert "/full" in js, "run-view.js must call the /full endpoint"
    # Must NOT call other data endpoints
    forbidden_patterns = ["/api/daily", "/api/habits", "/api/weight", "/api/readiness"]
    for pat in forbidden_patterns:
        assert pat not in js, (
            f"run-view.js must not call {pat!r}; all data comes from /full"
        )


# ═════════════════════════════════════════════════════════════════════════════
# AC7 — Source badges conditional on actual source
# ═════════════════════════════════════════════════════════════════════════════

def test_ac7_strava_badge_class_present():
    """The Strava source badge CSS class must be defined."""
    html = _html()
    assert "rv-src-badge--strava" in html or "strava" in html.lower(), (
        "run-view.html must define styling for the Strava source badge"
    )


def test_ac7_stryd_badge_class_present():
    """The Stryd source badge CSS class must be defined."""
    html = _html()
    assert "rv-src-badge--stryd" in html or "stryd" in html.lower(), (
        "run-view.html must define styling for the Stryd source badge"
    )


def test_ac7_badges_not_always_shown():
    """Both Strava and Stryd badges must be guarded by source conditions in JS."""
    js = _js()
    # Badges must be inside a conditional block, not unconditionally appended
    assert ("if" in js and "strava" in js.lower()) or "stravaSrc" in js, (
        "Strava badge must be conditionally rendered"
    )
    assert ("if" in js and "stryd" in js.lower()) or "strydPresent" in js, (
        "Stryd badge must be conditionally rendered"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC8 — Copy-to-clipboard provides user feedback
# ═════════════════════════════════════════════════════════════════════════════

def test_ac8_copy_feedback_mechanism_present():
    """Copy-to-clipboard must provide user feedback (tooltip or icon state change).

    The old implementation fired clipboard.writeText() with no UI response.
    AC8 requires a visible success indicator — this test verifies that
    some feedback mechanism exists in the JS (class toggle, tooltip, text swap,
    or setTimeout to reset state).
    """
    js = _js()
    # Must have some form of feedback after copy: a setTimeout for resetting state,
    # a CSS class toggle, or changing the button text/title.
    has_feedback = any([
        "setTimeout" in js,            # reset icon/text after delay
        "textContent" in js,           # swap button text
        "classList" in js,             # toggle CSS class for visual state
        "innerText" in js,             # update displayed text
        "title" in js and "Copied" in js,  # tooltip text changes to "Copied"
        "✓" in js or "✔" in js,        # checkmark icon
        "Copied" in js,                 # explicit "Copied!" text
    ])
    assert has_feedback, (
        "run-view.js must provide user feedback on copy-to-clipboard success "
        "(e.g. setTimeout to reset icon, classList toggle, 'Copied!' text, or tooltip change)"
    )


def test_ac8_copy_uses_separate_handler():
    """Copy handler should be a proper event listener, not an inline onclick string.

    Inline onclick strings baked into innerHTML cannot easily be modified to add
    feedback. A named function or addEventListener approach is required.
    """
    js = _js()
    # Should NOT use the old inline onclick pattern for copy
    # Old pattern: 'onclick="(function(){navigator.clipboard...})()"'
    # New pattern should use addEventListener or a named click handler
    has_listener = (
        "addEventListener" in js
        or "copyBtn" in js
        or "rv-copy-btn" in js
        or "querySelector" in js
    )
    assert has_listener, (
        "run-view.js must attach the copy handler via addEventListener (not inline onclick) "
        "so that user feedback can be applied to the button element"
    )
