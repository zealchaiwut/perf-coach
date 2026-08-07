"""AC: fill_strength dedup is case-insensitive (issue #1712).

Pinned exercises whose names differ only in case from pool candidates must not
produce duplicate exercises in the generated session.
"""
from __future__ import annotations

import random

from backend.services.plan_pattern_fill import fill_strength, match_exercises_for_tags
from backend.services.plan_pattern_seeds import default_exercises, default_strength_patterns


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _strength_lower_pattern() -> dict:
    return next(
        p for p in default_strength_patterns() if p["subtype"] == "strength_lower"
    )


def _make_minimal_pool(canonical_name: str, alt_name: str = "Plank") -> list[dict]:
    """Pool with two exercises — the canonical one and an alternate.

    This ensures the fill always has a non-duplicate candidate so it never
    hits the 'no candidates → use full pool' fallback, keeping the test focused
    on the case-dedup guard rather than the intentional fallback path.
    """
    return [
        {
            "name": canonical_name,
            "groups": ["lower", "upper", "full", "core"],
            "primary_muscles": ["quads"],
            "default_sets": 3,
            "tss_weight": 1.0,
        },
        {
            "name": alt_name,
            "groups": ["lower", "upper", "full", "core"],
            "primary_muscles": ["core"],
            "default_sets": 3,
            "tss_weight": 1.0,
        },
    ]


# ---------------------------------------------------------------------------
# AC1: fill_strength dedup is case-insensitive for pre-placed exercises
#
# A pre-placed row whose name is UPPERCASE must prevent the same exercise
# (stored in title-case in the pool) from being picked again.
# ---------------------------------------------------------------------------

def test_no_duplicate_when_pinned_name_differs_in_case():
    # "Back squat" is in the default pool with that exact title-case.
    canonical = "Back squat"
    pool = default_exercises()

    # Pre-place the exercise under an ALL-CAPS variant.  Before the fix the
    # used set contained "BACK SQUAT" (no .lower()), so "Back squat" from the
    # pool would pass the 'not in used' check and be picked again.
    pre_placed = [
        {
            "name": canonical.upper(),  # "BACK SQUAT"
            "sets": 4,
            "reps": "8",
            "block": None,
            "spend_tss": 5.0,
            "spend_min": 10.0,
        }
    ]
    pat = _strength_lower_pattern()
    content = fill_strength(
        pat,
        {"duration_minutes": 60, "target_tss": 45, "subtype": "strength_lower"},
        pool,
        rng=random.Random(0),
        pre_placed=pre_placed,
    )
    # Index 0 is the pre-placed exercise; the rest are generated.
    generated = content["exercises"][1:]
    generated_lower = [e["name"].lower() for e in generated]
    assert canonical.lower() not in generated_lower, (
        f"'{canonical}' was picked again despite being pre-placed as '{canonical.upper()}': "
        f"generated={[e['name'] for e in generated]}"
    )


# ---------------------------------------------------------------------------
# AC2: match_exercises_for_tags filters case-insensitively
#
# When the used_names set contains a name in any case, the pool exercise
# whose name differs only in case must be excluded from candidates.
# ---------------------------------------------------------------------------

def test_match_exercises_for_tags_excludes_case_variants():
    pool = [
        {"name": "Squat", "groups": ["lower"], "tss_weight": 1.0, "default_sets": 3},
        {"name": "Lunge", "groups": ["lower"], "tss_weight": 1.0, "default_sets": 3},
    ]
    # used_names built from a pre-placed row that stored the name in lowercase
    used = {"squat"}  # lowercase — pool has "Squat" (title-case)
    candidates = match_exercises_for_tags(pool, ["lower"], used_names=used)
    candidate_names_lower = [c["name"].lower() for c in candidates]
    assert "squat" not in candidate_names_lower, (
        "match_exercises_for_tags must exclude 'Squat' when 'squat' is in used_names"
    )
    assert "lunge" in candidate_names_lower, "Lunge should still be a candidate"


# ---------------------------------------------------------------------------
# AC3: no duplicate exercises across any random seed (regression guard)
# ---------------------------------------------------------------------------

def test_fill_strength_no_duplicate_all_seeds():
    """fill_strength never emits the same exercise twice across random seeds."""
    pool = default_exercises()
    pat = _strength_lower_pattern()
    for seed in range(20):
        content = fill_strength(
            pat,
            {"duration_minutes": 60, "target_tss": 45, "subtype": "strength_lower"},
            pool,
            rng=random.Random(seed),
        )
        names_lower = [e["name"].lower() for e in content["exercises"]]
        assert len(names_lower) == len(set(names_lower)), (
            f"Seed {seed}: duplicate exercise detected: {names_lower}"
        )
