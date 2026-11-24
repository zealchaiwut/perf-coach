"""Manual workout edits survive Strava/Stryd reconcile."""
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from backend.services.reconcile import _apply_best
from backend.services.workout_merge import compute_best_values
from backend.services.workout_overrides import set_override


def _strava(name="Strava title", distance_km=10.0):
    return SimpleNamespace(
        name=name,
        distance_km=distance_km,
        duration_seconds=3600,
        avg_hr=150,
        avg_power_w=None,
        tss=None,
    )


def test_renamed_workout_keeps_name_on_reconcile():
    w = SimpleNamespace(
        name="My rename",
        manual_overrides={"name": "My rename"},
        distance_km=10.0,
        duration_seconds=3600,
        avg_hr=150,
        strava_activity=_strava("Strava morning"),
        stryd_activity=None,
    )
    best = compute_best_values(w)
    assert best["best_name"] == "My rename"
    w.name = "My rename"
    _apply_best(w, best)
    assert w.name == "My rename"


def test_renamed_distance_survives_reconcile():
    w = SimpleNamespace(
        name="Run",
        manual_overrides={"distance_km": 12.5},
        distance_km=12.5,
        duration_seconds=3600,
        avg_hr=150,
        strava_activity=_strava(distance_km=10.0),
        stryd_activity=None,
    )
    best = compute_best_values(w)
    assert best["best_distance_km"] == 12.5
    _apply_best(w, best)
    assert w.distance_km == 12.5


def test_unedited_workout_takes_strava_name():
    w = SimpleNamespace(
        name="Old",
        manual_overrides=None,
        distance_km=10.0,
        duration_seconds=3600,
        avg_hr=150,
        strava_activity=_strava("Fresh Strava name"),
        stryd_activity=None,
    )
    best = compute_best_values(w)
    _apply_best(w, best)
    assert w.name == "Fresh Strava name"


def test_set_override_jsonb_reassign():
    w = SimpleNamespace(manual_overrides=None, name="x")
    set_override(w, "name", "Athlete title")
    assert w.manual_overrides == {"name": "Athlete title"}
    set_override(w, "distance_km", 21.1)
    assert w.manual_overrides["name"] == "Athlete title"
    assert w.manual_overrides["distance_km"] == 21.1