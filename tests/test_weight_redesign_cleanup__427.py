"""Tests for issue #427: Weight redesign — docs, dead-code removal, purge script, smoke.

AC anchors verified:
  (ac1)  docs/mockups/weight-redesign-v6.html exists
  (ac2)  docs/mockups/README.md marks pre-v6 weight mockups as superseded by weight-redesign-v6
  (ac3a) docs/features/weight-tracking.md has plan_at derivation formula with worked numeric example
  (ac3b) docs/features/weight-tracking.md has gap basis selection rules (avg_7d →
         avg_wide → no_data — unified onto _weight_rollup's rule per issue #1601's
         S2 remainder; avg_wide replaced the old latest_entry fallback)
  (ac3c) docs/features/weight-tracking.md has gap_direction thresholds: on_plan band is ±0.2 kg
  (ac3d) docs/features/weight-tracking.md has milestone generation: thirds, month-start rounding, dedup
  (ac3e) docs/features/weight-tracking.md has coach strip state table
  (ac3f) docs/features/weight-tracking.md states Chart.js was dropped and SVG is used for this page
  (ac4)  scripts/purge_weight_entries.py exists with --before, --below, --dry-run flags
  (ac5)  scripts/purge_weight_entries.py --dry-run exits 0, prints row count, no DB writes
  (ac6)  docs/features/weight-tracking.md has "Data Maintenance" section with purge script usage
  (ac7)  No Chart.js CDN script tag in weight.html
  (ac8)  No orphaned old-hero/progress CSS selectors remain in weight.html
  (ac9)  weight.js does not render status_label to the DOM
  (ac10) CHANGELOG.md has weight-redesign entry
  (ac11) docs/weight-redesign-investigation.md has Post-ship verification section
"""

import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
MOCKUPS = DOCS / "mockups"
FEATURES = DOCS / "features"
SCRIPTS = ROOT / "scripts"
PAGES_DIR = ROOT / "frontend" / "pages"
JS_DIR = ROOT / "frontend" / "js"
CHANGELOG = ROOT / "CHANGELOG.md"
INVESTIGATION = DOCS / "weight-redesign-investigation.md"
WEIGHT_TRACKING_DOC = FEATURES / "weight-tracking.md"
MOCKUPS_README = MOCKUPS / "README.md"
WEIGHT_HTML = PAGES_DIR / "weight.html"
WEIGHT_JS = JS_DIR / "weight.js"
PURGE_SCRIPT = SCRIPTS / "purge_weight_entries.py"


# ── AC1: v6 mockup exists ──────────────────────────────────────────────────────

def test_ac1_weight_redesign_v6_mockup_exists():
    assert (MOCKUPS / "weight-redesign-v6.html").exists(), (
        "docs/mockups/weight-redesign-v6.html is missing"
    )


# ── AC2: README marks pre-v6 mockups as superseded ───────────────────────────

def test_ac2_mockups_readme_marks_pre_v6_superseded():
    text = MOCKUPS_README.read_text()
    assert "superseded" in text.lower(), (
        "docs/mockups/README.md must contain 'superseded' marking pre-v6 weight mockups"
    )
    assert "weight-redesign-v6" in text, (
        "docs/mockups/README.md must reference weight-redesign-v6 as the current mockup"
    )


# ── AC3a: plan_at formula with worked numeric example ─────────────────────────

def test_ac3a_weight_tracking_doc_has_plan_at_formula():
    text = WEIGHT_TRACKING_DOC.read_text()
    assert "plan_at" in text, (
        "docs/features/weight-tracking.md must document the plan_at derivation formula"
    )
    # Worked example: must contain actual numbers showing the interpolation
    # e.g. fractions or "= X.X" style output
    assert re.search(r"plan_at|plan at|linear interp", text, re.IGNORECASE), (
        "weight-tracking.md must explain plan_at derivation"
    )
    # Must have a worked numeric example (numbers with decimal points in a formula context)
    assert re.search(r"\d+\.\d+\s*kg", text), (
        "weight-tracking.md plan_at section must include a worked numeric example with kg values"
    )


# ── AC3b: gap basis selection rules ──────────────────────────────────────────

def test_ac3b_weight_tracking_doc_has_gap_basis_rules():
    """compute_gap is unified onto _weight_rollup's rule (issue #1601's S2
    remainder / pre-production-review §3.3): avg_7d -> avg_wide ->
    single_entry -> no_data. The old latest_entry fallback is retired; the
    doc keeps a historical note naming it, so this only asserts presence,
    not absence."""
    text = WEIGHT_TRACKING_DOC.read_text()
    assert "avg_7d" in text or "7-day" in text.lower() or "7 day" in text.lower(), (
        "weight-tracking.md must document 7-day rolling average as first gap basis"
    )
    assert "avg_wide" in text, (
        "weight-tracking.md must document avg_wide as a fallback gap "
        "basis (unified onto _weight_rollup's rule)"
    )
    assert "single_entry" in text, (
        "weight-tracking.md must document single_entry as the honest label "
        "for the case where only one weigh-in exists in the whole lookback "
        "(must not be mislabeled avg_wide)"
    )
    assert "no_data" in text, (
        "weight-tracking.md must document no_data as the final fallback gap basis"
    )


# ── AC3c: gap_direction thresholds ────────────────────────────────────────────

def test_ac3c_weight_tracking_doc_has_gap_direction_thresholds():
    text = WEIGHT_TRACKING_DOC.read_text()
    assert "on_plan" in text or "on plan" in text.lower(), (
        "weight-tracking.md must document the on_plan gap_direction state"
    )
    # ±0.2 kg band
    assert "0.2" in text, (
        "weight-tracking.md must state the ±0.2 kg on_plan band threshold"
    )
    assert "ahead" in text.lower() and "behind" in text.lower(), (
        "weight-tracking.md must document ahead and behind gap_direction values"
    )


# ── AC3d: milestone generation logic ──────────────────────────────────────────

def test_ac3d_weight_tracking_doc_has_milestone_logic():
    text = WEIGHT_TRACKING_DOC.read_text()
    assert re.search(r"1/3|one.third|thirds", text, re.IGNORECASE), (
        "weight-tracking.md must explain thirds-of-remaining-time milestone placement"
    )
    assert re.search(r"month.start|1st.of.month|snap.*month|month.*round", text, re.IGNORECASE), (
        "weight-tracking.md must explain month-start rounding for milestones"
    )
    assert re.search(r"dedup|deduplic|collision", text, re.IGNORECASE), (
        "weight-tracking.md must explain deduplication of milestone dates"
    )


# ── AC3e: coach strip state table ─────────────────────────────────────────────

def test_ac3e_weight_tracking_doc_has_coach_strip_states():
    text = WEIGHT_TRACKING_DOC.read_text()
    assert re.search(r"coach.strip|coach strip", text, re.IGNORECASE), (
        "weight-tracking.md must contain a Coach Strip section"
    )
    # Must cover the states: no entry, on-pace, behind
    assert re.search(r"no.*entry|not.*logged|no.*log", text, re.IGNORECASE), (
        "weight-tracking.md coach strip must document the no-entry state"
    )


# ── AC3f: Custom SVG + explicit Chart.js drop statement ───────────────────────

def test_ac3f_weight_tracking_doc_states_chartjs_dropped():
    text = WEIGHT_TRACKING_DOC.read_text()
    assert re.search(r"chart\.js.*drop|drop.*chart\.js|svg.*chart|custom.*svg|chart\.js.*replaced", text, re.IGNORECASE), (
        "weight-tracking.md must state Chart.js was dropped and custom SVG is used for the weight chart"
    )


# ── AC4: purge script exists with correct flags ───────────────────────────────

def test_ac4_purge_script_exists():
    assert PURGE_SCRIPT.exists(), "scripts/purge_weight_entries.py must exist"


def test_ac4_purge_script_has_before_flag():
    text = PURGE_SCRIPT.read_text()
    assert "--before" in text, "purge_weight_entries.py must have a --before DATE flag"


def test_ac4_purge_script_has_below_flag():
    text = PURGE_SCRIPT.read_text()
    assert "--below" in text, "purge_weight_entries.py must have a --below KG flag"


def test_ac4_purge_script_has_dry_run_flag():
    text = PURGE_SCRIPT.read_text()
    assert "--dry-run" in text or "dry_run" in text, (
        "purge_weight_entries.py must have a --dry-run flag"
    )


def test_ac4_purge_script_has_confirmation_prompt():
    text = PURGE_SCRIPT.read_text()
    assert re.search(r"input\(|confirm|proceed|yes/no|y/n", text, re.IGNORECASE), (
        "purge_weight_entries.py must prompt for confirmation when not in dry-run mode"
    )


# ── AC5: dry-run exits 0 and prints row count without DB writes ───────────────

def test_ac5_dry_run_exits_zero_and_prints_count():
    """Run the script in dry-run mode with a date far in the future to catch all rows.

    Uses --before 2099-01-01 --below 9999 so any entries in the test DB are included,
    but --dry-run prevents any deletion.  We only verify exit code + output shape.
    """
    result = subprocess.run(
        [
            sys.executable,
            str(PURGE_SCRIPT),
            "--before", "2099-01-01",
            "--below", "9999",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
        timeout=30,
        cwd=str(ROOT),
    )
    assert result.returncode == 0, (
        f"purge_weight_entries.py --dry-run exited {result.returncode}.\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # Output must mention a count (e.g. "0 rows" or "N rows")
    combined = result.stdout + result.stderr
    assert re.search(r"\d+\s+row|\d+\s+entr|would delete\s+\d+|dry.run", combined, re.IGNORECASE), (
        f"dry-run output must print affected row count.\nOutput: {combined}"
    )


# ── AC6: Data Maintenance section with purge script usage ─────────────────────

def test_ac6_weight_tracking_doc_has_data_maintenance_section():
    text = WEIGHT_TRACKING_DOC.read_text()
    assert re.search(r"##\s+Data Maintenance|data.maintenance", text, re.IGNORECASE), (
        "weight-tracking.md must have a 'Data Maintenance' section"
    )
    assert "purge_weight_entries" in text, (
        "weight-tracking.md Data Maintenance section must document purge_weight_entries.py usage"
    )
    assert "--dry-run" in text, (
        "weight-tracking.md Data Maintenance section must show the --dry-run flag"
    )


# ── AC7: No Chart.js CDN script in weight.html ────────────────────────────────

def test_ac7_no_chartjs_cdn_in_weight_html():
    text = WEIGHT_HTML.read_text()
    assert "cdn.jsdelivr.net/npm/chart.js" not in text, (
        "weight.html must not load the Chart.js CDN script — Chart.js was dropped for this page"
    )


# ── AC8: No orphaned old CSS selectors ────────────────────────────────────────

def test_ac8_no_orphaned_old_hero_css_in_weight_html():
    """The old Chart.js-era chart markup used canvas#weight-chart and a chart container.
    Post-redesign these should be gone or the div#weight-chart should be SVG-driven only.
    The test checks that no <canvas> element is present (SVG chart replaced it).
    """
    text = WEIGHT_HTML.read_text()
    assert "<canvas" not in text.lower(), (
        "weight.html must not have a <canvas> element — the chart is SVG-based post-redesign"
    )


# ── AC9: status_label not rendered in weight-page UI ─────────────────────────

def test_ac9_status_label_not_rendered_in_weight_js():
    """weight.js must not write status_label value to the DOM.
    The field may be READ (for backward-compat) but must not be rendered.
    A comment mentioning it is fine; what's forbidden is setting element text/class from it.
    """
    text = WEIGHT_JS.read_text()
    # Check that there's no active render call based on status_label (t.status_label → DOM)
    # Pattern: assignement of textContent/className/innerHTML from t.status_label
    assert not re.search(
        r"t\.status_label\s*\)",  # direct use as a truthy value for rendering
        text
    ) or re.search(r"//.*status_label", text), (
        "weight.js must not render status_label to the DOM — gap_direction supersedes it"
    )
    # More specific: no DOM write based on status_label value
    # We check that status_label doesn't appear as part of a textContent or className assignment
    # outside of comments
    lines = text.splitlines()
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("//") or stripped.startswith("*"):
            continue
        if "status_label" in line and re.search(r"textContent|className|innerHTML|innerText", line):
            raise AssertionError(
                f"weight.js renders status_label to DOM at: {line.strip()!r}\n"
                "gap_direction supersedes status_label in the weight page UI"
            )


# ── AC10: CHANGELOG entry for weight redesign ─────────────────────────────────

def test_ac10_changelog_has_weight_redesign_entry():
    text = CHANGELOG.read_text()
    assert re.search(
        r"weight.page.redesign|weight.*redesign|weight.*plan.vs.actual|coach.strip",
        text,
        re.IGNORECASE,
    ), (
        "CHANGELOG.md must contain an entry for the weight page redesign "
        "(plan-vs-actual, milestone chart, stepper quick-log, coach strip)"
    )


# ── AC11: Post-ship verification section in investigation doc ─────────────────

def test_ac11_investigation_doc_has_post_ship_verification():
    text = INVESTIGATION.read_text()
    assert re.search(r"post.ship|post ship", text, re.IGNORECASE), (
        "docs/weight-redesign-investigation.md must have a 'Post-ship verification' section"
    )
    # Must cover the 5 UAT scenarios
    assert re.search(r"fresh.user|no.data|no data", text, re.IGNORECASE), (
        "Post-ship verification must record fresh-user (no data) results"
    )
    assert re.search(r"active.*flow|hero.*log|backfill", text, re.IGNORECASE), (
        "Post-ship verification must record active flow (hero log + backfill) results"
    )
    assert re.search(r"behind.plan|behind plan", text, re.IGNORECASE), (
        "Post-ship verification must record behind-plan render results"
    )
    assert re.search(r"ahead.of.plan|ahead of plan|ahead.plan", text, re.IGNORECASE), (
        "Post-ship verification must record ahead-of-plan render results"
    )
    assert re.search(r"no.target|no target", text, re.IGNORECASE), (
        "Post-ship verification must record no-target render results"
    )
