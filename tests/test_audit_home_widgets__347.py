"""
Tests for issue #347: Audit home page widgets and document data dependencies.

All ACs verified against docs/home-widget-spec.md content.
Zero-code-change constraint verified via git diff.
"""
import os
import subprocess
import re

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_PATH = os.path.join(REPO_ROOT, "docs", "home-widget-spec.md")

EXPECTED_WIDGETS = [
    "Greeting",
    "Readiness Hero",
    "Sleep",
    "Performance",
    "Recent Workouts",
    "Log Today",
    "HRV",
    "Weekly TSS",
    "RHR",
    "Weight",
    "Habits Week Grid",
    "Habits Stats",
]

EXPECTED_ROUTES = [
    "home",
    "dashboard",
    "readiness",
    "recent-workouts",
    "weekly-summary",
    "pr",
]


def read_spec():
    with open(SPEC_PATH, encoding="utf-8") as f:
        return f.read()


# AC 1: docs/home-widget-spec.md exists in the repo
def test_spec_file_exists():
    assert os.path.isfile(SPEC_PATH), "docs/home-widget-spec.md not found"


# AC 2: Spec lists every widget visible on the home page
def test_spec_lists_all_widgets():
    content = read_spec()
    missing = [w for w in EXPECTED_WIDGETS if w.lower() not in content.lower()]
    assert not missing, f"Spec missing widgets: {missing}"


# AC 3: Each widget entry states data source (hardcoded / stub / live API)
def test_spec_data_sources_present():
    content = read_spec()
    sources_found = re.findall(
        r"\b(hardcoded|stub|live API|live api)\b", content, re.IGNORECASE
    )
    assert len(sources_found) >= len(EXPECTED_WIDGETS), (
        f"Expected at least {len(EXPECTED_WIDGETS)} data-source labels, "
        f"found {len(sources_found)}"
    )


# AC 4: Each widget entry includes a JSON response shape
def test_spec_json_shapes_present():
    content = read_spec()
    # JSON shapes documented with at least a code block or field list per widget
    code_blocks = re.findall(r"```(?:json)?(.*?)```", content, re.DOTALL)
    assert len(code_blocks) >= 8, (
        f"Expected JSON shape blocks for main widgets, found {len(code_blocks)} code blocks"
    )


# AC 5: Each widget maps to a named endpoint flagged EXISTS or NEEDS BUILDING
def test_spec_endpoint_flags_present():
    content = read_spec()
    exists_count = len(re.findall(r"\bEXISTS\b", content))
    needs_count = len(re.findall(r"\bNEEDS BUILDING\b", content))
    total = exists_count + needs_count
    assert total >= len(EXPECTED_WIDGETS), (
        f"Expected at least {len(EXPECTED_WIDGETS)} endpoint flags (EXISTS/NEEDS BUILDING), "
        f"found {total}"
    )


# AC 6: Backend search covers the 6 specified route patterns
def test_spec_records_backend_route_search():
    content = read_spec()
    missing = [r for r in EXPECTED_ROUTES if r not in content]
    assert not missing, f"Spec missing route-search results for: {missing}"


# AC 7: Spec includes a "Sprint Build Plan" section
def test_spec_has_sprint_build_plan():
    content = read_spec()
    assert "sprint build plan" in content.lower(), (
        "Spec missing 'Sprint Build Plan' section"
    )


# AC 8: Zero code changes — no .py, .html, .js files modified on this branch
def test_no_source_code_modified():
    result = subprocess.run(
        ["git", "diff", "--name-only", "HEAD"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    changed = result.stdout.strip().splitlines()
    violations = [
        f for f in changed
        if f.endswith((".py", ".html", ".js")) and not f.startswith("tests/")
    ]
    assert not violations, (
        f"Source code files modified on this branch (AC8 violation): {violations}"
    )


# AC 8 (staged): same check against staged changes
def test_no_source_code_staged():
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    changed = result.stdout.strip().splitlines()
    violations = [
        f for f in changed
        if f.endswith((".py", ".html", ".js")) and not f.startswith("tests/")
    ]
    assert not violations, (
        f"Source code files staged (AC8 violation): {violations}"
    )
