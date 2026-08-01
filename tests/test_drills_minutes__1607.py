"""Running drills as a duration on the workout — issue #1607.

Drills (form drills, strides, A/B skips) ride alongside a session. The operator's
spec: *"a real field like strength training but make it simple — like 10 mins of
running drills, no need to go into details."*

Two shape decisions this file pins:

1. **A field, not a workout_type.** A type would claim a slot in the week
   skeleton and carry a TSS budget, which is wrong for ten minutes of strides
   after an easy run. Drills cost nothing against the load model.
2. **A duration only.** No exercise breakdown, no structure. Structured enough
   to count later ("how many drill sessions last month?"), nothing more.

Nullable is *unknown*, which is distinct from 0 (*"logged the session, did no
drills"*) — the same tri-state reasoning as ``workouts.fuelled``.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import backend.main as _main
from backend.models import Workout

REPO = Path(__file__).resolve().parents[1]


# ── The column ────────────────────────────────────────────────────────────────

def test_workout_has_a_drills_minutes_column():
    assert hasattr(Workout, "drills_minutes")


def test_drills_is_not_a_workout_type():
    """A type would get a skeleton slot and a TSS budget. Drills must not."""
    src = (REPO / "backend" / "routers" / "projection.py").read_text()
    assert "workout_type must be run, strength, plyo, stretch, or rest" in src, (
        "the accepted workout_type list changed — if 'drills' was added as a "
        "type, that contradicts the no-TSS decision in #1607"
    )


def test_migration_has_a_single_head():
    """A second head blocks every PR via the CI gate."""
    versions = REPO / "alembic" / "versions"
    migration = versions / "8cefa13354c8_add_drills_minutes_to_workouts.py"
    assert migration.exists()
    src = migration.read_text()
    assert "down_revision: Union[str, Sequence[str], None] = '13f189e87eec'" in src


def test_migration_is_idempotent():
    """Re-running must not fail — the repo's migration convention."""
    src = (
        REPO / "alembic" / "versions" / "8cefa13354c8_add_drills_minutes_to_workouts.py"
    ).read_text()
    assert "ADD COLUMN IF NOT EXISTS" in src
    assert "DROP COLUMN IF EXISTS" in src
    assert "WHERE conname = 'ck_workouts_drills_minutes_range'" in src


# ── Validation ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("value", [0, 10, 45, 120, None])
def test_valid_drills_values_pass(value):
    _main._validate_drills_minutes(value)  # must not raise


@pytest.mark.parametrize("value", [-1, 121, 500, "10", 10.5, True])
def test_invalid_drills_values_are_422(value):
    """Bounds mirror the CHECK constraint, so the API answers with a field
    message rather than letting Postgres raise an IntegrityError."""
    with pytest.raises(_main.HTTPException) as exc:
        _main._validate_drills_minutes(value)
    assert exc.value.status_code == 422


def test_bounds_match_the_check_constraint():
    models_src = (REPO / "backend" / "models.py").read_text()
    assert "drills_minutes >= 0 AND drills_minutes <= 120" in models_src
    assert _main._DRILLS_MIN_MINUTES == 0
    assert _main._DRILLS_MAX_MINUTES == 120


# ── The write path ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("model_name", ["WorkoutIn", "WorkoutPatch"])
def test_input_models_accept_drills_minutes(model_name):
    model = getattr(_main, model_name)
    assert "drills_minutes" in model.model_fields


@pytest.mark.parametrize("model_name", ["WorkoutIn", "WorkoutPatch"])
def test_drills_is_optional_and_defaults_to_none(model_name):
    """None means not recorded. A required field would force a value onto every
    workout, and a 0 default would claim the athlete did no drills."""
    field = getattr(_main, model_name).model_fields["drills_minutes"]
    assert field.default is None
    assert not field.is_required()


def test_post_workout_persists_and_validates_drills():
    src = inspect.getsource(_main.post_workout)
    assert "drills_minutes=body.drills_minutes" in src
    assert "_validate_drills_minutes" in src


def test_patch_workout_persists_drills_and_can_clear_it():
    src = inspect.getsource(_main.patch_workout)
    assert "'drills_minutes' in body.model_fields_set" in src, (
        "patch must key off model_fields_set so an explicit null clears the "
        "value back to unknown instead of being ignored"
    )
    assert "workout.drills_minutes = body.drills_minutes" in src
    assert "_validate_drills_minutes" in src


def test_response_exposes_drills_minutes():
    """A value you can write but not read back is not a round trip."""
    detail = inspect.getsource(_main._workout_dict)
    assert '"drills_minutes"' in detail


# ── No TSS contribution ───────────────────────────────────────────────────────

def test_drills_do_not_feed_tss():
    """The whole point: drills are light and cost nothing against the load
    model. If a TSS path ever reads this column, that decision was reversed."""
    tss_src = (REPO / "backend" / "services" / "tss.py").read_text()
    assert "drills_minutes" not in tss_src

    load_src = (REPO / "backend" / "services" / "training_load.py").read_text()
    assert "drills_minutes" not in load_src


# ── The form ──────────────────────────────────────────────────────────────────

def test_form_has_a_drills_input():
    html = (REPO / "frontend" / "pages" / "training.html").read_text()
    assert 'id="workout-drills"' in html
    assert 'max="120"' in html


def test_form_sends_drills_on_save():
    js = (REPO / "frontend" / "js" / "training.js").read_text()
    assert "drills_minutes: intFieldVal('workout-drills')" in js


def test_form_repopulates_drills_when_editing():
    """Rendered but never populated would silently drop the value on every
    edit — the field would look optional and behave destructively."""
    js = (REPO / "frontend" / "js" / "training.js").read_text()
    assert js.count("workout-drills") >= 4, (
        "expected clear + populate-on-edit + populate-on-duplicate + save"
    )
