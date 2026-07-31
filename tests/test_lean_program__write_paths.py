"""The lean program's three columns had readers but no writers.

Phases 0–4 (PRs #1593/#1594) shipped three columns whose consumers were fully
built and fully tested, but which nothing in the API could ever set:

1. ``ensure_goal_habits`` created the three goal habits and had ZERO callers, so
   the habits never existed and ``export.habits.goal_habits`` stayed ``[]``.
2. ``weight_entries.body_fat_pct`` was read by ``body_composition`` but absent
   from every weight-entry input model, so the composition block could never
   fill.
3. ``workouts.fuelled`` was read by ``habit_autofill`` but absent from every
   workout input model, so the long-run-fuel habit could never tick.

A fourth fell out of fixing the first: ``main.py``'s weight writes never
recomputed habit autofill (only the worker's Discord path did), so logging a
weigh-in in the app left the weigh-in habit unticked.

These tests pin the CONNECTIONS. The components behind them have their own
suites — the point here is only that a write path exists and reaches storage.
"""
from __future__ import annotations

import inspect

import pytest

import backend.main as _main


# ═════════════════════════════════════════════════════════════════════════════
# 1. The three goal habits get created
# ═════════════════════════════════════════════════════════════════════════════

def test_get_habits_bootstraps_the_goal_habits():
    """Opening the Habits page is the documented bootstrap. It has to do it."""
    src = inspect.getsource(_main.get_habits)
    assert "ensure_goal_habits" in src, (
        "GET /api/habits does not call ensure_goal_habits — the weigh-in, "
        "protein-first and long-run-fuel habits would never be created."
    )


def test_goal_habit_bootstrap_is_committed():
    """Creating them in a session that never commits is the same as not creating
    them at all."""
    src = inspect.getsource(_main.get_habits)
    bootstrap = src.index("ensure_goal_habits(")
    assert "session.commit()" in src[bootstrap:], (
        "ensure_goal_habits runs but nothing commits afterwards."
    )


# ═════════════════════════════════════════════════════════════════════════════
# 2. body_fat_pct — the weekly composition reading
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "model_name",
    ["WeightEntriesCreateIn", "WeightEntryByDateIn", "WeightEntriesPatchIn"],
)
def test_every_weight_entry_input_model_accepts_body_fat_pct(model_name):
    model = getattr(_main, model_name)
    assert "body_fat_pct" in model.model_fields, (
        f"{model_name} drops body_fat_pct, so pydantic silently discards the "
        "reading before the handler ever sees it."
    )


@pytest.mark.parametrize("value", [3, 25.4, 70, None])
def test_valid_body_fat_readings_pass(value):
    _main._validate_body_fat_pct(value)  # must not raise


@pytest.mark.parametrize("value", [2.9, 70.1, -1, 200, "25", True])
def test_out_of_range_body_fat_is_422_not_an_integrity_error(value):
    """Bounds mirror the CHECK constraint, so the API answers with a field
    message rather than letting Postgres raise."""
    with pytest.raises(_main.HTTPException) as exc:
        _main._validate_body_fat_pct(value)
    assert exc.value.status_code == 422


@pytest.mark.parametrize(
    "handler",
    ["create_weight_entry", "upsert_weight_entry_by_date", "patch_weight_entry"],
)
def test_weight_write_handlers_persist_body_fat_pct(handler):
    src = inspect.getsource(getattr(_main, handler))
    assert "body_fat_pct" in src, (
        f"{handler} accepts body_fat_pct on the model but never writes it."
    )


def test_weight_write_handlers_validate_body_fat_pct():
    for handler in ("create_weight_entry", "upsert_weight_entry_by_date", "patch_weight_entry"):
        src = inspect.getsource(getattr(_main, handler))
        assert "_validate_body_fat_pct" in src, (
            f"{handler} writes body_fat_pct without validating it."
        )


def test_upsert_does_not_wipe_an_existing_reading():
    """The daily weigh-in omits body fat. An upsert that always wrote the field
    would erase the week's reading on the next morning's number."""
    src = inspect.getsource(_main.upsert_weight_entry_by_date)
    assert "if body.body_fat_pct is not None:" in src, (
        "by-date upsert must only update body_fat_pct when one was sent."
    )


def test_weight_entry_response_exposes_body_fat_pct():
    src = inspect.getsource(_main._weight_entry_dict)
    assert '"body_fat_pct"' in src, (
        "a value you can write but not read back is not a round trip."
    )


# ═════════════════════════════════════════════════════════════════════════════
# 3. workouts.fuelled — the long-run-fuel habit's only input
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("model_name", ["WorkoutIn", "WorkoutPatch"])
def test_workout_input_models_accept_fuelled(model_name):
    model = getattr(_main, model_name)
    assert "fuelled" in model.model_fields, (
        f"{model_name} drops fuelled, so the long-run-fuel habit can never tick."
    )


@pytest.mark.parametrize("model_name", ["WorkoutIn", "WorkoutPatch"])
def test_fuelled_stays_tri_state(model_name):
    """None means UNKNOWN, not "no". A non-optional bool would default every
    historical run to unfuelled and make the habit lie."""
    field = getattr(_main, model_name).model_fields["fuelled"]
    assert field.default is None
    assert not field.is_required()


def test_post_workout_persists_fuelled():
    src = inspect.getsource(_main.post_workout)
    assert "fuelled=body.fuelled" in src


def test_patch_workout_persists_fuelled_and_can_clear_it():
    src = inspect.getsource(_main.patch_workout)
    assert "'fuelled' in body.model_fields_set" in src, (
        "patch must key off model_fields_set so an explicit null clears the "
        "flag back to unknown instead of being ignored."
    )
    assert "workout.fuelled = body.fuelled" in src


def test_workout_response_exposes_fuelled():
    src = inspect.getsource(_main._workout_dict)
    assert '"fuelled"' in src


def test_workout_writes_recompute_autofill():
    """fuelled only matters because autofill reads it — a write that doesn't
    trigger the recompute leaves the habit stale until the next workout edit."""
    for handler in ("post_workout", "patch_workout"):
        src = inspect.getsource(getattr(_main, handler))
        assert "_recompute_autofill" in src, f"{handler} never recomputes autofill"


# ═════════════════════════════════════════════════════════════════════════════
# 4. Weight writes tick the weigh-in habit
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "handler",
    ["create_weight_entry", "upsert_weight_entry_by_date", "delete_weight_entry"],
)
def test_weight_writes_recompute_the_weigh_in_habit(handler):
    """The weigh-in habit autofills from the entry — no tap. Before this, only
    the worker's Discord path recomputed, so logging in the app left the habit
    unticked."""
    src = inspect.getsource(getattr(_main, handler))
    assert "_recompute_weigh_in_autofill" in src, (
        f"{handler} changes whether the day has a weigh-in but never "
        "recomputes the habit."
    )


def test_weigh_in_autofill_helper_is_best_effort():
    """A habit that failed to recompute must never cost the athlete the
    weigh-in itself — same contract as the workout write paths."""
    src = inspect.getsource(_main._recompute_weigh_in_autofill)
    assert "try:" in src and "except Exception" in src


def test_autofill_runs_outside_the_write_session():
    """recompute opens its own Session; calling it inside the write's `with`
    block risks a nested-session lock on the row just written."""
    for handler in ("create_weight_entry", "upsert_weight_entry_by_date"):
        src = inspect.getsource(getattr(_main, handler))
        recompute_col = src.index("_recompute_weigh_in_autofill(")
        line_start = src.rindex("\n", 0, recompute_col) + 1
        indent = len(src[line_start:recompute_col]) - len(src[line_start:recompute_col].lstrip())
        assert indent == 4, (
            f"{handler} calls the recompute at indent {indent}; it must sit at "
            "function level, outside the `with Session(...)` block."
        )
