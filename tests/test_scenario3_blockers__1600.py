"""The three things that stopped the lean program working — issue #1600.

Scenario 3 is the paste-to-Claude loop plus the lean guardrails: the reason this
app exists. Three defects made it unusable, and each has the same shape — the
mechanism was fully built and tested, and one connection was wrong.

1. The WEEKLY CUT REVIEW could never fire. `structural` was computed and then
   ignored by the gate, so a lean-program athlete needed a `WeightPlan` — which
   no UI creates, and whose only route demands a `goal_weight_kg`. That is the
   exact concept the rest of the feature set exists to eliminate, so the one
   documented way to unblock the verdict reintroduced the framing it was built
   to remove.

2. STREAK BADGES fired on the food habits. `is_food_habit()` was written for
   precisely this and had zero callers, and the softened-copy branch it should
   have reached is gated on `window.HabitVoice`, which is referenced four times
   in habits.js and defined nowhere.

3. The PROTEIN TARGET ignored body fat logged where the operator guide says to
   log it. `body_fat_pct` lives on two tables; composition read one, fuel read
   the other, and both land in the same coach export.
"""
from __future__ import annotations

import datetime
import inspect
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]

_BASE = dict(
    actual_rate_kg_per_week=-0.4,
    plan_rate_kg_per_week=-0.5,
    weekly_pct_bw_rate=-0.45,
    ea_proxy=1.0,
    logging_adherence_pct=0,
    avg_intake_vs_budget_kcal=0,
    consecutive_weeks_behind=0,
    pct_logged_days_at_or_under_budget=0,
    current_deficit_kcal=400,
    plateau_days=0,
    pct_at_or_under_budget_21d=0,
)


# ── 1. The weekly cut review fires ────────────────────────────────────────────

def test_structural_mode_needs_no_weight_plan():
    """The blocker in one assertion. This returned insufficient_data forever."""
    from backend.services.cut_review import compute_cut_recommendation

    out = compute_cut_recommendation(
        weigh_in_count_14d=6, has_active_plan=False, **_BASE
    )
    assert out["recommendation"] != "insufficient_data"


def test_structural_is_the_live_default():
    """routers/fuel.py never passes deficit_mode, so structural is what every
    real request gets — which is why this bug was total rather than partial."""
    from backend.services import cut_review

    sig = inspect.signature(cut_review.compute_cut_recommendation)
    assert sig.parameters["deficit_mode"].default == cut_review.DEFICIT_MODE_STRUCTURAL


def test_managed_mode_still_requires_a_plan():
    """The old behaviour is intact where it was correct — a managed daily-budget
    cut genuinely has a plan behind it."""
    from backend.services.cut_review import compute_cut_recommendation

    out = compute_cut_recommendation(
        weigh_in_count_14d=6, has_active_plan=False, deficit_mode="managed", **_BASE
    )
    assert out["recommendation"] == "insufficient_data"


def test_too_few_weigh_ins_still_blocks():
    """The weigh-in floor is a real data requirement, not a plan requirement."""
    from backend.services.cut_review import compute_cut_recommendation

    out = compute_cut_recommendation(
        weigh_in_count_14d=1, has_active_plan=True, **_BASE
    )
    assert out["recommendation"] == "insufficient_data"


def test_structural_copy_does_not_ask_for_a_plan():
    """Telling a structural athlete to "set an active plan" sent them to a
    target-weight flow the program is designed not to have."""
    from backend.services.cut_review import compute_cut_recommendation

    out = compute_cut_recommendation(
        weigh_in_count_14d=1, has_active_plan=False, **_BASE
    )
    assert "plan" not in out["action"].lower()
    assert "weigh-in" in out["action"].lower()


# ── 2. No streaks near food ───────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["Protein first", "protein first", "Long-run fuel", "FUEL"])
def test_food_habits_are_recognised(name):
    from backend.services.goal_habits import is_food_habit

    assert is_food_habit(type("H", (), {"name": name})())


@pytest.mark.parametrize("name", ["Morning weigh-in", "Stretch", "Zone 2 minutes"])
def test_non_food_habits_are_not(name):
    from backend.services.goal_habits import is_food_habit

    assert not is_food_habit(type("H", (), {"name": name})())


def test_is_food_habit_is_actually_called():
    """It had ZERO callers. Existing and being wired are different things — the
    distinction this whole review kept finding."""
    import backend.main as _main

    src = Path(_main.__file__).read_text()
    assert "_is_food_habit(habit)" in src


def test_both_streak_endpoints_suppress():
    """The list and the detail panel are two ways to see one habit; if only one
    suppressed, they would disagree about the same thing on the same screen."""
    src = Path(__import__("backend.main", fromlist=["x"]).__file__).read_text()
    assert src.count("_is_food_habit(habit)") >= 2
    assert src.count('"streak_suppressed"') >= 2


def test_suppression_is_server_side():
    """Zeroing the payload, not hiding the badge. A template-only guard is one
    refactor from being dropped, and the number would still be sitting in the
    response for anything else to render."""
    src = Path(__import__("backend.main", fromlist=["x"]).__file__).read_text()
    assert '0 if food else streak_data["current_streak"]' in src


def test_every_frontend_badge_render_is_guarded():
    """habits.js renders a streak badge in THREE places — the card, its
    fallback branch, and a separate table-row builder reading its own
    streaksPerHabit map. The first version of this test compared indexes and
    only proved the first one was covered; it found the third by failing."""
    js = (REPO / "frontend" / "js" / "habits.js").read_text()
    renders = [
        i for i, line in enumerate(js.splitlines(), 1)
        if "<span class=\"streak-badge\"" in line
    ]
    assert renders, "no badge renders found — did the markup change?"
    assert js.count("streak_suppressed") >= 2, (
        f"badge rendered at lines {renders} but only "
        f"{js.count('streak_suppressed')} suppression check(s) present"
    )


def test_habitvoice_is_still_undefined_so_the_fallback_branch_is_live():
    """Documents WHY the frontend guard is needed rather than assumed dead.

    habits.js gates its softened copy on window.HabitVoice, which no file in the
    repo defines — so every render has always fallen through to the raw-badge
    branch. If someone implements HabitVoice later this test will fail, and the
    guard's comment should be revisited at that point.
    """
    defined = [
        p for p in (REPO / "frontend" / "js").rglob("*.js")
        if "HabitVoice =" in p.read_text() or "window.HabitVoice=" in p.read_text()
    ]
    assert not defined, f"HabitVoice is now defined in {defined} — revisit the guard"


# ── 3. The protein target sees body fat wherever it was logged ────────────────

def test_lean_mass_reads_both_body_fat_stores():
    """weight_entries is where the operator guide (§6) tells the athlete to log;
    fuel read only body_measurements, so following the guide left the protein
    target on the 0.76 estimate."""
    from backend.services import fuel

    src = inspect.getsource(fuel._fetch_lean_mass)
    assert "BodyMeasurement" in src
    assert "WeightEntry.body_fat_pct" in src


def test_readings_are_normalised_to_one_shape():
    """The two tables spell the date differently (measure_date vs entry_date);
    current_lean_mass_kg takes one shape."""
    from backend.services.fuel import _BodyFatReading

    r = _BodyFatReading(21.0, datetime.date(2026, 7, 10), "weight_entries")
    assert r.body_fat_pct == 21.0
    assert r.measure_date == datetime.date(2026, 7, 10)


def test_newest_reading_wins_and_ties_prefer_the_guided_surface():
    """The caller takes the most recent reading, so ordering decides the answer.
    A same-day tie goes to weight_entries — the surface §6 points at."""
    from backend.services.fuel import _BodyFatReading

    day = datetime.date(2026, 7, 10)
    rows = sorted(
        [
            _BodyFatReading(20.0, datetime.date(2026, 7, 1), "body_measurements"),
            _BodyFatReading(22.0, day, "body_measurements"),
            _BodyFatReading(21.0, day, "weight_entries"),
        ],
        key=lambda r: (r.measure_date, r.source == "weight_entries"),
        reverse=True,
    )
    assert rows[0].source == "weight_entries"
    assert rows[0].body_fat_pct == 21.0


def test_union_rather_than_picking_a_winner():
    """Choosing one table would silently discard whichever readings the athlete
    had already logged. S5 (#1604) decides which store survives; until then
    every reading counts."""
    from backend.services import fuel

    src = inspect.getsource(fuel._fetch_lean_mass)
    assert "measured +=" in src, "expected both stores to be combined, not chosen between"
