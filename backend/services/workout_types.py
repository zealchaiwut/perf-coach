"""Canonical workout_type string constants (issue #1369 follow-up).

`workouts.workout_type` is a free-text column. Most values pass through
verbatim from user input (see `_normalize_workout_type` in backend/main.py),
but a small set of types have case-sensitive query dependencies elsewhere
in the codebase (run-scoped queries, strength-scoped queries) and MUST be
stored using one canonical casing. Those — and only those — types get a
named constant here so the write-time normalizer and the read-time queries
share a single source of truth instead of duplicating string literals.

Do NOT add constants for types that aren't canonicalized (e.g. 'Crossfit',
'Rowing') — they intentionally pass through as typed.
"""
from __future__ import annotations

WORKOUT_TYPE_RUN: str = "run"
WORKOUT_TYPE_STRENGTH: str = "strength"
