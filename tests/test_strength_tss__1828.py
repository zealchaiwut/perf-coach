"""Issue #1828 — revamp strength TSS (exercises vs effort × time)."""
from types import SimpleNamespace

from backend.services.strength_tss import (
    STRENGTH_SET_TSS,
    default_strength_method,
    from_effort_time,
    from_exercises,
    resolve_strength_method,
)
from backend.services.session_tss import session_tss


def test_effort_time_52_min_at_7():
    r = from_effort_time(duration_min=52, effort=7)
    assert r["tss"] == 42


def test_from_exercises_two_multipliers():
    exercises = [
        {"name": "A", "sets": [{}, {}, {}]},
        {"name": "B", "sets": [{}, {}, {}, {}]},
    ]
    mult = {"a": 1.1, "b": 0.7}
    r = from_exercises(exercises, multipliers=mult)
    assert r["per_exercise"][0]["tss"] == round(3 * STRENGTH_SET_TSS * 1.1, 1)
    assert r["per_exercise"][1]["tss"] == round(4 * STRENGTH_SET_TSS * 0.7, 1)
    assert r["tss"] == round(r["per_exercise"][0]["tss"] + r["per_exercise"][1]["tss"], 1)
    # 3*3.3*1.1=10.9, 4*3.3*0.7=9.2 → 20.1
    assert r["tss"] == 20.1


def test_default_method_prefers_exercises():
    assert default_strength_method([{"name": "X", "sets": [{}]}]) == "exercises"
    assert default_strength_method([]) == "effort_time"
    assert default_strength_method(None) == "effort_time"


def test_stored_method_override():
    w = SimpleNamespace(strength_tss_method="effort_time")
    assert resolve_strength_method(w, [{"name": "X", "sets": [{}]}]) == "effort_time"


def test_session_tss_strength_returns_chosen_method():
    w = SimpleNamespace(
        workout_type="strength",
        tss_source="calculated",
        tss=None,
        duration_seconds=52 * 60,
        session_effort=7,
        strength_tss_method="effort_time",
        id=None,
    )
    r = session_tss(w, exercises=[])
    assert r["tss"] == 42
    assert r["method"] == "effort_time"
    assert r["tss_effort_time"] == 42