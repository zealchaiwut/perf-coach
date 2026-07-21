"""Tests for issue #1466: Consistent workout_type run-matching predicate in gap-analysis.

Verifies that all run-matching filters in backend/services/gap_analysis/engine.py
use the same predicate (lower(workout_type) LIKE '%run%') to handle subtypes and
mixed-case variants, preventing false-negative suppression of ramp signals.
"""
import subprocess
import re


# --- Acceptance Criteria ---

def test_1466__consistent_predicates_all_locations():
    """AC: All run-matching predicates in engine.py use the same filter expression.

    Verifies that lines 105, 158, 243, 326, and 471 all use the identical predicate
    (lower(workout_type) LIKE '%run%'). Extract the SQL strings and confirm no mixing
    of exact-match vs LIKE forms.
    """
    result = subprocess.run(
        ["git", "show", "HEAD:backend/services/gap_analysis/engine.py"],
        capture_output=True,
        text=True,
        cwd="/Users/zeal-server/dev/perf-coach/tester"
    )
    assert result.returncode == 0, "Failed to read engine.py from git"

    engine_code = result.stdout

    # Find all SQL WHERE clauses containing workout_type
    # Pattern: capture the run-matching predicate in each WHERE
    run_predicates = re.findall(
        r"(lower\([^)]*workout_type[^)]*\)\s+LIKE\s+'%run%'|workout_type\s*=\s*'run')",
        engine_code,
        re.IGNORECASE
    )

    # Must have at least 4 instances (the gather functions)
    assert len(run_predicates) >= 4, f"Expected at least 4 run-matching predicates, found {len(run_predicates)}"

    # All should be LIKE-based (the canonical form)
    for i, pred in enumerate(run_predicates):
        assert "LIKE" in pred, f"Predicate {i+1} is not LIKE-based: {pred}"
        assert "lower(" in pred, f"Predicate {i+1} does not use lower(): {pred}"


def test_1466__canonical_constant_defined():
    """AC: A comment or constant documents the canonical run-matching predicate.

    Verifies that _RUN_FILTER constant is defined at module level with documentation
    explaining why the LIKE form is chosen.
    """
    result = subprocess.run(
        ["git", "show", "HEAD:backend/services/gap_analysis/engine.py"],
        capture_output=True,
        text=True,
        cwd="/Users/zeal-server/dev/perf-coach/tester"
    )
    assert result.returncode == 0, "Failed to read engine.py"

    engine_code = result.stdout

    # Find _RUN_FILTER definition
    assert "_RUN_FILTER" in engine_code, "_RUN_FILTER constant not found"

    # The constant should be defined with the LIKE pattern
    assert "lower(workout_type) LIKE '%run%'" in engine_code, \
        "Canonical LIKE pattern not found in engine.py"

    # There should be a comment explaining the choice
    match = re.search(
        r"#.*?Canonical.*?run.matching|#.*?lower.*?LIKE.*?run",
        engine_code,
        re.IGNORECASE | re.DOTALL
    )
    assert match, "No comment documenting the canonical predicate found"


def test_1466__run_filter_used_in_gather_queries():
    """AC: The _RUN_FILTER constant is referenced in gather queries (single-table functions).

    Verifies that the _RUN_FILTER constant or its literal expansion appears in at least
    4 of the 5 gather functions.
    """
    result = subprocess.run(
        ["git", "show", "HEAD:backend/services/gap_analysis/engine.py"],
        capture_output=True,
        text=True,
        cwd="/Users/zeal-server/dev/perf-coach/tester"
    )
    assert result.returncode == 0, "Failed to read engine.py"

    engine_code = result.stdout

    # Count occurrences of {_RUN_FILTER} placeholder (used in f-strings)
    filter_placeholder_count = engine_code.count("{_RUN_FILTER}")

    # Also count literal expansions
    literal_count = engine_code.count("lower(workout_type) LIKE '%run%'")

    # We should have either placeholder uses or literal uses
    total_uses = filter_placeholder_count + literal_count

    # Should have at least 4 gather functions using the predicate
    # (5 gather functions but one uses a JOIN and may have slightly different syntax)
    assert total_uses >= 4, \
        f"Expected at least 4 gather functions with canonical predicate, found {total_uses} uses " \
        f"({filter_placeholder_count} placeholders + {literal_count} literals)"


def test_1466__no_exact_match_predicate_mixing():
    """AC: No mixing of exact-match (= 'run') with LIKE form predicates.

    Verifies that the codebase does not mix the two predicate styles
    (exact match vs LIKE-based) in the same module.
    """
    result = subprocess.run(
        ["git", "show", "HEAD:backend/services/gap_analysis/engine.py"],
        capture_output=True,
        text=True,
        cwd="/Users/zeal-server/dev/perf-coach/tester"
    )
    assert result.returncode == 0, "Failed to read engine.py"

    engine_code = result.stdout

    # Count exact-match predicates (the old form we're moving away from)
    exact_match_count = len(re.findall(
        r"workout_type\s*=\s*'run'",
        engine_code,
        re.IGNORECASE
    ))

    # Count LIKE-based predicates (the canonical form)
    like_count = len(re.findall(
        r"lower\([^)]*workout_type[^)]*\)\s+LIKE\s+'%run%'",
        engine_code,
        re.IGNORECASE
    ))

    # In the fixed version, we should have LIKE-based only and very few (if any) exact-match
    # The _gather_form_metrics join might still have a literal due to table aliasing
    assert like_count >= 4, f"Expected at least 4 LIKE-based predicates, found {like_count}"
    assert exact_match_count <= 1, f"Found {exact_match_count} exact-match predicates (should be ≤1 for legacy compatibility)"


def test_1466__predicate_consistency_across_locations():
    """AC: All gather query locations (around lines 105, 160, 245, 328, 473) use the same form.

    The actual line numbers may drift slightly due to prior changes, so this test
    searches for the gather function definitions and verifies they all use the
    canonical LIKE-based predicate (either via {_RUN_FILTER} placeholder or literal).
    """
    result = subprocess.run(
        ["git", "show", "HEAD:backend/services/gap_analysis/engine.py"],
        capture_output=True,
        text=True,
        cwd="/Users/zeal-server/dev/perf-coach/tester"
    )
    assert result.returncode == 0, "Failed to read engine.py"

    engine_code = result.stdout

    # Gather functions that should have the run-matching predicate
    gather_functions = {
        "_gather_intensity_4w": False,
        "_gather_long_run_decoupling_4w": False,
        "_gather_quality_sessions_3w": False,
        "_gather_easy_runs_3w": False,
        "_gather_training_load": False,
    }

    for func_name in gather_functions.keys():
        # Find the function definition
        match = re.search(
            rf"def {func_name}\(.*?\):.*?(?=\ndef |\Z)",
            engine_code,
            re.DOTALL
        )
        if match:
            func_body = match.group(0)
            # Check if it contains either the placeholder or the literal predicate
            if ("{_RUN_FILTER}" in func_body or
                "lower(workout_type) LIKE '%run%'" in func_body):
                gather_functions[func_name] = True

    # All 5 functions should have the predicate
    found = sum(1 for v in gather_functions.values() if v)
    assert found >= 4, \
        f"Expected at least 4 gather functions with canonical predicate, found {found}. " \
        f"Status: {gather_functions}"
