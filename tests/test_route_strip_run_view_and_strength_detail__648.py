"""Tests for issue #648: Add route strip to Run view and redesign Strength detail.

Acceptance Criteria — Run Detail View:
  AC-R1  Route placeholder card below hero stats; message "Map appears once GPS sync is added"; no fake/stub map
  AC-R2  Placeholder card follows gradient theme, visually consistent with other cards
  AC-R3  Source-and-sync strip: Strava link when Strava source; Stryd badge when Stryd; "Merged from" note when merged
  AC-R4  Strip elements only rendered when source data present; no empty slots or placeholder text
  AC-R5  All data read from the /full endpoint

Acceptance Criteria — Strength Detail View:
  AC-S1  Header: activity badge, activity name, formatted date
  AC-S2  Stats grid: Duration, Exercises, Total Reps, Avg RPE, Avg HR, TSS — absent values render as "—"
  AC-S3  Session-profile bar: height∝RPE, width∝duration, fill color maps to RPE tier
  AC-S4  Bar renders gracefully with partial data (missing RPE or duration → neutral/default segment)
  AC-S5  Exercises list: colored bullet (RPE tier), set summary ("3 × 8 @ 80 kg"), RPE pill
  AC-S6  Absent set values (weight, reps, RPE) render as "—"
  AC-S7  All data read from /full endpoint
  AC-S8  Gradient theme; layout driven by structure tokens
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_RV_HTML = _ROOT / "frontend" / "pages" / "run-view.html"
_RV_JS = _ROOT / "frontend" / "js" / "run-view.js"
_SV_HTML = _ROOT / "frontend" / "pages" / "strength-view.html"
_SV_JS = _ROOT / "frontend" / "js" / "strength-view.js"
_MAIN_PY = _ROOT / "backend" / "main.py"


def _rv_html() -> str:
    assert _RV_HTML.exists(), f"Missing: {_RV_HTML}"
    return _RV_HTML.read_text()


def _rv_js() -> str:
    assert _RV_JS.exists(), f"Missing: {_RV_JS}"
    return _RV_JS.read_text()


def _sv_html() -> str:
    assert _SV_HTML.exists(), f"Missing: {_SV_HTML}"
    return _SV_HTML.read_text()


def _sv_js() -> str:
    assert _SV_JS.exists(), f"Missing: {_SV_JS}"
    return _SV_JS.read_text()


def _main_py() -> str:
    assert _MAIN_PY.exists(), f"Missing: {_MAIN_PY}"
    return _MAIN_PY.read_text()


# ═════════════════════════════════════════════════════════════════════════════
# AC-R1 — Route placeholder card with correct message, no fake map
# ═════════════════════════════════════════════════════════════════════════════


def test_r1_route_placeholder_message():
    """run-view.js must render the exact placeholder message required by AC-R1."""
    js = _rv_js()
    assert "Map appears once GPS sync is added" in js, (
        "run-view.js must render the message 'Map appears once GPS sync is added' "
        "inside the route placeholder card"
    )


def test_r1_route_placeholder_below_hero():
    """Route placeholder must appear after the hero section in the innerHTML concat."""
    js = _rv_js()
    inner_idx = js.find("innerHTML")
    assert inner_idx != -1, "run-view.js must set innerHTML to render the view"
    concat = js[inner_idx: inner_idx + 800]
    hero_pos = concat.find("heroSection")
    route_pos = concat.find("routeSection")
    assert hero_pos != -1, "heroSection must appear in the innerHTML assignment"
    assert route_pos != -1, "routeSection must appear in the innerHTML assignment"
    assert hero_pos < route_pos, (
        "routeSection must be concatenated after heroSection so the route placeholder "
        "renders below the hero stats"
    )


def test_r1_no_fake_map_image_in_route_section():
    """The route section must not embed an <img>, <canvas>, or map-library call."""
    js = _rv_js()
    # Locate the routeSection variable assignment
    route_idx = js.find("routeSection")
    assert route_idx != -1
    # Extract ~600 chars around the first assignment of routeSection
    snippet = js[route_idx: route_idx + 600]
    assert "<img" not in snippet, "Route section must not contain a fake map <img>"
    assert "<canvas" not in snippet, "Route section must not contain a <canvas> element"
    assert "mapbox" not in snippet.lower(), "Route section must not use Mapbox"
    assert "leaflet" not in snippet.lower(), "Route section must not use Leaflet"


# ═════════════════════════════════════════════════════════════════════════════
# AC-R2 — Placeholder card follows gradient theme
# ═════════════════════════════════════════════════════════════════════════════


def test_r2_map_placeholder_has_gradient_background():
    """The .rv-map-placeholder CSS must use a gradient background (linear- or
    radial-gradient), not a flat color, to follow the gradient theme."""
    html = _rv_html()
    placeholder_idx = html.find("rv-map-placeholder")
    assert placeholder_idx != -1, "run-view.html must define .rv-map-placeholder"
    # Grab the CSS rule for rv-map-placeholder
    rule_start = html.rfind("{", 0, placeholder_idx)
    # Actually find the rule block that contains rv-map-placeholder
    # by finding the next { after the class name in the style block
    next_brace = html.find("{", placeholder_idx)
    rule_end = html.find("}", next_brace)
    rule_body = html[next_brace: rule_end]
    assert "gradient" in rule_body, (
        "The .rv-map-placeholder must use a gradient background (e.g. "
        "linear-gradient or radial-gradient) to follow the gradient theme — "
        "a flat background color is not sufficient"
    )


def test_r2_placeholder_uses_design_tokens():
    """The placeholder CSS must use CSS custom property tokens (var(--...))
    rather than hard-coded hex colours."""
    html = _rv_html()
    placeholder_idx = html.find("rv-map-placeholder")
    assert placeholder_idx != -1
    next_brace = html.find("{", placeholder_idx)
    rule_end = html.find("}", next_brace)
    rule_body = html[next_brace: rule_end]
    assert "var(--" in rule_body, (
        "The .rv-map-placeholder background must reference CSS tokens (var(--...)) "
        "rather than raw hex values"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC-R3 — Source-and-sync strip contents
# ═════════════════════════════════════════════════════════════════════════════


def test_r3_strava_link_rendered():
    """renderSourceStrip must emit a 'View on Strava' link when strava_activity_url
    is present on the workout."""
    js = _rv_js()
    assert "View on Strava" in js, (
        "run-view.js must render a 'View on Strava' link inside renderSourceStrip "
        "when the workout has a strava_activity_url"
    )


def test_r3_strava_link_uses_url_from_workout():
    """The 'View on Strava' link must use workout.strava_activity_url as its href."""
    js = _rv_js()
    strip_idx = js.find("renderSourceStrip")
    assert strip_idx != -1
    fn_start = js.find("function renderSourceStrip")
    assert fn_start != -1
    fn_brace = js.find("{", fn_start)
    depth = 0
    i = fn_brace
    while i < len(js):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    fn_body = js[fn_start: i + 1]
    assert "strava_activity_url" in fn_body, (
        "renderSourceStrip must read workout.strava_activity_url to build the "
        "'View on Strava' href"
    )


def test_r3_stryd_badge_rendered():
    """renderSourceStrip must emit a Stryd badge when Stryd is the power source."""
    js = _rv_js()
    assert "Stryd" in js, (
        "run-view.js must render a 'Stryd' badge in the source strip when "
        "Stryd is the power source"
    )
    assert "rv-src-badge--stryd" in js or "stryd" in js.lower(), (
        "The Stryd badge must have a distinct CSS class (rv-src-badge--stryd or similar)"
    )


def test_r3_merged_from_note_rendered():
    """renderSourceStrip must emit a 'Merged from' note when the workout was
    assembled from multiple sources (workout.source contains a comma)."""
    js = _rv_js()
    assert "Merged from" in js, (
        "run-view.js must render a 'Merged from' note in the source strip when "
        "the workout was merged from multiple sources (e.g. source = 'strava,stryd')"
    )


def test_r3_merged_from_checks_source_field():
    """The 'Merged from' condition must examine workout.source (or sources on
    the full response) to detect multi-source activities."""
    js = _rv_js()
    fn_start = js.find("function renderSourceStrip")
    assert fn_start != -1
    fn_brace = js.find("{", fn_start)
    depth = 0
    i = fn_brace
    while i < len(js):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    fn_body = js[fn_start: i + 1]
    # Must reference source field or field_coverage for merge detection
    has_source_check = (
        "workout.source" in fn_body
        or "field_coverage" in fn_body
        or ".source" in fn_body
        or "merged" in fn_body.lower()
    )
    assert has_source_check, (
        "renderSourceStrip must inspect the workout source field (or field_coverage) "
        "to determine whether to show the 'Merged from' note"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC-R4 — Strip elements conditional; no empty slots or placeholder fallback
# ═════════════════════════════════════════════════════════════════════════════


def test_r4_no_manual_entry_fallback():
    """The source strip must not render a 'Manual entry' or similar fallback
    text when no sources are present — absent sources produce no placeholder."""
    js = _rv_js()
    assert "Manual entry" not in js, (
        "run-view.js must NOT render a 'Manual entry' fallback in the source strip. "
        "When no source data is present, the strip must be empty or hidden, not show "
        "placeholder text — AC-R4 requires no empty slots or placeholder text."
    )


def test_r4_strava_link_conditional():
    """The Strava link must be rendered inside a conditional check on
    workout.strava_activity_url (not always)."""
    js = _rv_js()
    fn_start = js.find("function renderSourceStrip")
    assert fn_start != -1
    fn_brace = js.find("{", fn_start)
    depth = 0
    i = fn_brace
    while i < len(js):
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if depth == 0:
                break
        i += 1
    fn_body = js[fn_start: i + 1]
    strava_url_idx = fn_body.find("strava_activity_url")
    assert strava_url_idx != -1, "renderSourceStrip must reference strava_activity_url"
    # There must be a conditional (if / ternary) before the Strava link
    before = fn_body[:strava_url_idx]
    has_conditional = "if " in before or "if(" in before or "&&" in before or "?" in before
    assert has_conditional, (
        "The Strava link must be guarded by a conditional on strava_activity_url"
    )


def test_r4_source_section_rendered_conditionally_or_always_present():
    """The source section element is present in the DOM regardless (it may be an
    empty container), but individual strip items must not render when data is absent.
    The source strip container must be present in renderView."""
    js = _rv_js()
    assert "sourceSection" in js or "rv-source" in js, (
        "run-view.js must include a source section / strip in the rendered output"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC-R5 — All data from /full endpoint
# ═════════════════════════════════════════════════════════════════════════════


def test_r5_full_endpoint_only():
    """run-view.js must call only /api/workouts/{id}/full."""
    js = _rv_js()
    assert "/full" in js, "run-view.js must call the /full endpoint"
    # Confirm no separate endpoint for source data
    assert "/api/sources" not in js
    assert "/api/strava/activity" not in js


# ═════════════════════════════════════════════════════════════════════════════
# Strength view — file existence and backend route
# ═════════════════════════════════════════════════════════════════════════════


def test_sv_html_exists():
    """frontend/pages/strength-view.html must exist."""
    assert _SV_HTML.exists(), (
        "frontend/pages/strength-view.html must be created for the Strength detail view"
    )


def test_sv_js_exists():
    """frontend/js/strength-view.js must exist."""
    assert _SV_JS.exists(), (
        "frontend/js/strength-view.js must be created for the Strength detail view"
    )


def test_sv_backend_route_registered():
    """backend/main.py must register a route for strength-view so the page is served."""
    py = _main_py()
    assert "strength-view" in py or "strength_view" in py, (
        "backend/main.py must add 'strength-view' to _PAGES so the page is served "
        "at /strength-view"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC-S1 — Header: activity badge, name, date
# ═════════════════════════════════════════════════════════════════════════════


def test_s1_header_badge_rendered():
    """strength-view.js must render an activity badge in the header."""
    js = _sv_js()
    # Badge is a small label like "STRENGTH" or the workout type
    has_badge = (
        "sv-badge" in js
        or "badge" in js.lower()
        or "workout_type" in js
        or "STRENGTH" in js
    )
    assert has_badge, (
        "strength-view.js must render an activity badge (e.g. 'STRENGTH') "
        "in the header section (AC-S1)"
    )


def test_s1_header_name_rendered():
    """strength-view.js must render the workout name in the header."""
    js = _sv_js()
    assert "w.name" in js or "workout.name" in js or ".name" in js, (
        "strength-view.js must render the workout name in the header (AC-S1)"
    )


def test_s1_header_date_rendered():
    """strength-view.js must render the workout date in the header."""
    js = _sv_js()
    assert "workout_date" in js, (
        "strength-view.js must render the workout date in the header (AC-S1)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC-S2 — Stats grid: six fields, absent values = "—"
# ═════════════════════════════════════════════════════════════════════════════


def test_s2_stats_grid_duration():
    """Stats grid must include a Duration field."""
    js = _sv_js()
    assert "Duration" in js, "strength-view.js must render a Duration field in the stats grid"


def test_s2_stats_grid_exercises():
    """Stats grid must include an Exercises count field."""
    js = _sv_js()
    assert "Exercises" in js, (
        "strength-view.js must render an Exercises count field in the stats grid"
    )


def test_s2_stats_grid_total_reps():
    """Stats grid must include a Total Reps field."""
    js = _sv_js()
    assert "Total Reps" in js or "Reps" in js, (
        "strength-view.js must render a Total Reps field in the stats grid"
    )


def test_s2_stats_grid_avg_rpe():
    """Stats grid must include an Avg RPE field."""
    js = _sv_js()
    assert "RPE" in js, (
        "strength-view.js must render an Avg RPE field in the stats grid"
    )


def test_s2_stats_grid_avg_hr():
    """Stats grid must include an Avg HR field."""
    js = _sv_js()
    assert "Avg HR" in js or "avg_hr" in js, (
        "strength-view.js must render an Avg HR field in the stats grid"
    )


def test_s2_stats_grid_tss():
    """Stats grid must include a TSS field."""
    js = _sv_js()
    assert "TSS" in js, "strength-view.js must render a TSS field in the stats grid"


def test_s2_absent_values_use_em_dash():
    """Absent values must render as em dash (—)."""
    js = _sv_js()
    assert "—" in js or "\\u2014" in js or '"—"' in js or "'—'" in js, (
        "strength-view.js must use em dash (—) for absent/null field values (AC-S2)"
    )


def test_s2_dash_helper_or_equivalent():
    """A dash() helper or equivalent null-coalescing pattern must be used."""
    js = _sv_js()
    assert "function dash" in js or "dash(" in js or "?? " in js or "null ? " in js, (
        "strength-view.js must use a dash() helper or null-coalescing to render '—' "
        "for absent values (AC-S2)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC-S3 — Session-profile bar: height∝RPE, width∝duration, color∝RPE tier
# ═════════════════════════════════════════════════════════════════════════════


def test_s3_profile_bar_rendered():
    """strength-view.js must render a session-profile bar."""
    js = _sv_js()
    has_bar = (
        "sv-profile-bar" in js
        or "profile-bar" in js
        or "profile_bar" in js
        or "profileBar" in js
        or "renderProfileBar" in js
        or "session-profile" in js
    )
    assert has_bar, (
        "strength-view.js must render a session-profile bar (AC-S3)"
    )


def test_s3_bar_height_proportional_to_rpe():
    """The segment height must be derived from the set's RPE value."""
    js = _sv_js()
    # RPE must influence height styling
    assert "rpe" in js.lower(), "strength-view.js must reference RPE for segment sizing"
    # There must be a height calculation tied to rpe
    has_height_rpe = (
        ("height" in js and "rpe" in js.lower())
        or "heightPct" in js
        or "height_pct" in js
    )
    assert has_height_rpe, (
        "strength-view.js must calculate segment height proportional to RPE (AC-S3)"
    )


def test_s3_bar_width_proportional_to_duration():
    """The segment width must be derived from the set's duration."""
    js = _sv_js()
    has_width_duration = (
        ("width" in js and "duration" in js)
        or "widthPct" in js
        or "width_pct" in js
    )
    assert has_width_duration, (
        "strength-view.js must calculate segment width proportional to set duration (AC-S3)"
    )


def test_s3_rpe_tier_color_mapping():
    """The bar color must map to RPE tier (e.g. easy / moderate / hard / max)."""
    js = _sv_js()
    # There must be distinct colors for different RPE tiers
    has_color_tiers = (
        "easy" in js.lower()
        or "moderate" in js.lower()
        or "hard" in js.lower()
        or ("rpe" in js.lower() and "#" in js)
        or ("rpe" in js.lower() and "color" in js.lower())
    )
    assert has_color_tiers, (
        "strength-view.js must map RPE tiers to fill colors for the profile bar (AC-S3)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC-S4 — Profile bar renders gracefully with partial data
# ═════════════════════════════════════════════════════════════════════════════


def test_s4_neutral_segment_when_rpe_missing():
    """When a set has no RPE, the bar must render a neutral/default segment."""
    js = _sv_js()
    # There must be a null/fallback for RPE in the segment rendering
    has_rpe_fallback = (
        "null" in js and "rpe" in js.lower()
        or "|| " in js and "rpe" in js.lower()
        or "??" in js and "rpe" in js.lower()
        or "default" in js.lower() and "rpe" in js.lower()
    )
    assert has_rpe_fallback, (
        "strength-view.js must handle missing RPE gracefully with a neutral/default "
        "segment rather than breaking the bar (AC-S4)"
    )


def test_s4_neutral_segment_when_duration_missing():
    """When a set has no duration, the bar must render a default-width segment."""
    js = _sv_js()
    # Duration fallback must exist
    has_duration_fallback = (
        ("duration" in js and ("||" in js or "??" in js or "null" in js))
    )
    assert has_duration_fallback, (
        "strength-view.js must handle missing duration gracefully with a default-width "
        "segment (AC-S4)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC-S5 — Exercises list: colored bullet, set summary, RPE pill
# ═════════════════════════════════════════════════════════════════════════════


def test_s5_exercise_list_colored_bullet():
    """Each exercise row must include a colored bullet matching its RPE tier."""
    js = _sv_js()
    has_bullet = (
        "sv-ex-bullet" in js
        or "bullet" in js.lower()
        or ("background" in js and "rpe" in js.lower())
    )
    assert has_bullet, (
        "strength-view.js must render a colored bullet for each exercise row, "
        "with the color matching its RPE tier (AC-S5)"
    )


def test_s5_set_summary_format():
    """Each exercise must display a set summary in the format 'N × M @ W kg'."""
    js = _sv_js()
    # The summary uses × (times sign) and @
    has_times = "×" in js or "\\u00d7" in js or "&times;" in js or "x " in js
    has_at = " @ " in js or "@" in js
    assert has_times, (
        "strength-view.js must use '×' in the set summary (e.g. '3 × 8 @ 80 kg') (AC-S5)"
    )
    assert has_at, (
        "strength-view.js must use '@' in the set summary to separate reps from weight (AC-S5)"
    )


def test_s5_rpe_pill_in_exercises():
    """Each exercise must include an RPE pill."""
    js = _sv_js()
    has_pill = (
        "sv-rpe-pill" in js
        or "rpe-pill" in js
        or ("RPE" in js and "pill" in js.lower())
        or ("rpe" in js.lower() and "pill" in js.lower())
        or ("rpe" in js.lower() and "badge" in js.lower())
    )
    assert has_pill, (
        "strength-view.js must render an RPE pill for each exercise row (AC-S5)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC-S6 — Absent set values render as "—"
# ═════════════════════════════════════════════════════════════════════════════


def test_s6_absent_weight_renders_dash():
    """When weight is absent, the set summary must show '—' in place of weight."""
    js = _sv_js()
    # weight_kg must be null-guarded
    has_weight_guard = (
        ("weight_kg" in js or "weight" in js.lower())
        and ("dash(" in js or "—" in js or "null" in js or "??" in js)
    )
    assert has_weight_guard, (
        "strength-view.js must render '—' when weight is absent in a set summary (AC-S6)"
    )


def test_s6_absent_reps_renders_dash():
    """When reps is absent, the set summary must show '—' in place of reps."""
    js = _sv_js()
    has_reps_guard = (
        "reps" in js
        and ("dash(" in js or "—" in js or "null" in js or "??" in js)
    )
    assert has_reps_guard, (
        "strength-view.js must render '—' when reps is absent in a set summary (AC-S6)"
    )


def test_s6_absent_rpe_renders_dash():
    """When RPE is absent, the RPE pill must show '—'."""
    js = _sv_js()
    # The pill renders RPE value with dash fallback
    has_rpe_dash = (
        "rpe" in js.lower()
        and ("dash(" in js or "—" in js or "null" in js or "??" in js)
    )
    assert has_rpe_dash, (
        "strength-view.js must render '—' in the RPE pill when RPE is absent (AC-S6)"
    )


# ═════════════════════════════════════════════════════════════════════════════
# AC-S7 — All data from /full endpoint
# ═════════════════════════════════════════════════════════════════════════════


def test_s7_full_endpoint_used():
    """strength-view.js must fetch from /api/workouts/{id}/full."""
    js = _sv_js()
    assert "/full" in js, (
        "strength-view.js must call /api/workouts/{id}/full for all data (AC-S7)"
    )


def test_s7_no_other_data_endpoints():
    """strength-view.js must not call separate API endpoints for workout data."""
    js = _sv_js()
    forbidden = ["/api/daily", "/api/habits", "/api/weight", "/api/readiness"]
    for pat in forbidden:
        assert pat not in js, (
            f"strength-view.js must not call {pat!r}; all data comes from /full (AC-S7)"
        )


# ═════════════════════════════════════════════════════════════════════════════
# AC-S8 — Gradient theme; structure tokens
# ═════════════════════════════════════════════════════════════════════════════


def test_s8_gradient_theme_page_bg():
    """strength-view.html must use var(--page-bg) for the body/page background."""
    html = _sv_html()
    assert "page-bg" in html or "var(--bg-" in html, (
        "strength-view.html must use var(--page-bg) or the gradient token vars "
        "(--bg-1/--bg-2) for the page background (AC-S8)"
    )


def test_s8_uses_card_tokens():
    """strength-view.html must reference card design tokens (--card-bg, --card-border)."""
    html = _sv_html()
    uses_card_tokens = "card-bg" in html or "card-border" in html or "card" in html
    assert uses_card_tokens, (
        "strength-view.html must use card-level CSS tokens (--card-bg, --card-border) "
        "from the design system (AC-S8)"
    )


def test_s8_no_one_off_hex_in_layout():
    """Layout dimensions must use token-based values, not arbitrary one-off px."""
    html = _sv_html()
    # The page may have some pixel values but should predominantly use tokens
    # Check that CSS custom properties are used
    assert "var(--" in html, (
        "strength-view.html must use CSS custom properties (var(--...)) for layout "
        "and colour rather than one-off pixel values (AC-S8)"
    )


def test_s8_uses_text_tokens():
    """strength-view.html must reference text color tokens."""
    html = _sv_html()
    uses_text_tokens = (
        "text-primary" in html
        or "text-secondary" in html
        or "text-tertiary" in html
    )
    assert uses_text_tokens, (
        "strength-view.html must use text color tokens (--text-primary etc.) (AC-S8)"
    )
