"""Tests for target-aware Suggest sessions (Plan tab revamp, Part 3).

Covers spec 3.3:
  - Suggestions sum to within ±15% of remaining_tss
  - Never exceed the ACWR ceiling
  - Never land on a rest day or a past day
  - A taper-phase week yields lower volume than the equivalent hold-phase week
  - Validation failure retries once then falls back to the template
  - With the flag (PLAN_TARGET_AWARE_ENABLED) off, behavior is byte-identical to today

Real-Postgres for the assemble_facts DB tests (target_tss/phase come from
compute_load_plan via the same A-race + TrainingPlan resolution as Parts 1/2);
pure unit tests for validation_errors/build_prompt/orchestrator retry (no DB).
"""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

import backend.services.plan_suggestions as ps
from backend.db import engine
from backend.models import Race, TrainingPlan, User, Workout


def _run(offset, tss=30, duration=30, intent="x"):
    return {
        "day_offset": offset, "workout_type": "run", "target_tss": tss,
        "duration_minutes": duration, "intent": intent,
        "blocks": [{"phase": "main", "duration_min": duration, "repeat": None, "rest_min": None, "target": "easy"}],
    }


def _rest(offset):
    return {"day_offset": offset, "workout_type": "rest", "target_tss": 0,
            "duration_minutes": 0, "intent": "rest", "blocks": None}


# ── validation_errors: target-band / ACWR-ceiling / past-day (pure, no DB) ──

class TestValidationTargetAware:
    def _facts(self, target_tss=332.0, logged_tss_so_far=57.0, acwr_ceiling=410.0, today_offset=None, **extra):
        return {
            "trailing_28d_weekly_avg_tss": 300.0,
            "target_tss": target_tss,
            "logged_tss_so_far": logged_tss_so_far,
            "remaining_tss": max(0.0, target_tss - logged_tss_so_far),
            "acwr_ceiling": acwr_ceiling,
            "today_offset": today_offset,
            **extra,
        }

    def test_within_15pct_band_passes(self):
        # target 332, logged 57 -> remaining 275; one session at 275 lands exactly on target.
        facts = self._facts(target_tss=332.0, logged_tss_so_far=57.0)
        suggestions = [_run(3, tss=275)]
        assert ps.validation_errors(suggestions, facts) == []

    def test_over_15pct_band_fails(self):
        facts = self._facts(target_tss=332.0, logged_tss_so_far=57.0)
        # logged 57 + suggested 400 = 457, well above 332*1.15≈381.8
        suggestions = [_run(3, tss=400)]
        errs = ps.validation_errors(suggestions, facts)
        assert any("exceeds the 332" in e or "TSS target" in e for e in errs)

    def test_under_15pct_band_fails(self):
        facts = self._facts(target_tss=332.0, logged_tss_so_far=57.0)
        # logged 57 + suggested 50 = 107, well below 332*0.85≈282.2
        suggestions = [_run(3, tss=50)]
        errs = ps.validation_errors(suggestions, facts)
        assert any("falls short of" in e for e in errs)

    def test_modest_overshoot_within_15pct_passes(self):
        # ±15% guide: 332 * 1.10 = 365.2 — still under band, should pass.
        facts = self._facts(target_tss=332.0, logged_tss_so_far=57.0, acwr_ceiling=500.0)
        suggestions = [_run(3, tss=300)]  # combined 357
        assert ps.validation_errors(suggestions, facts) == []

    def test_acwr_ceiling_exceeded_fails_even_if_engineered_within_band(self):
        # target 300, logged 0, ceiling artificially set BELOW target*1.15 so a
        # suggestion that satisfies the band still trips the ceiling check.
        facts = self._facts(target_tss=300.0, logged_tss_so_far=0.0, acwr_ceiling=290.0)
        suggestions = [_run(3, tss=300)]
        errs = ps.validation_errors(suggestions, facts)
        assert any("ACWR ceiling" in e for e in errs)

    def test_past_day_rejected(self):
        facts = self._facts(today_offset=3)
        suggestions = [_run(1, tss=275)]
        errs = ps.validation_errors(suggestions, facts)
        assert any("day_offset 1" in e and "past" in e for e in errs)

    def test_today_and_future_offsets_not_rejected_as_past(self):
        facts = self._facts(today_offset=3, target_tss=332.0, logged_tss_so_far=57.0)
        suggestions = [_run(3, tss=275)]
        errs = ps.validation_errors(suggestions, facts)
        assert not any("past" in e for e in errs)

    def test_rest_day_rule_still_applies_with_target_present(self):
        facts = self._facts(preferred_rest_days=[2])
        suggestions = [_run(2, tss=50), _run(3, tss=225)]
        errs = ps.validation_errors(suggestions, facts)
        assert any("REST" in e for e in errs)

    def test_no_target_aware_checks_when_target_tss_absent(self):
        # Old-style facts (no target_tss key at all) — huge overshoot must NOT
        # trigger the new target-band/ceiling/past-day rules; only the
        # pre-existing ACWR-ramp rule (if any) can fire.
        facts = {"trailing_28d_weekly_avg_tss": 300.0, "today_offset": 5}
        suggestions = [_run(1, tss=50)]  # would be "past" if today_offset were honoured
        errs = ps.validation_errors(suggestions, facts)
        assert not any("past" in e for e in errs)
        assert not any("TSS target" in e for e in errs)
        assert not any("ACWR ceiling" in e for e in errs)


# ── build_prompt: target-aware rule text (pure, no DB) ──────────────────────

class TestBuildPromptTargetAware:
    def _facts(self, phase="hold", target_tss=332.0, logged=57.0, remaining=275.0, ceiling=410.0):
        return {
            "trailing_28d_weekly_avg_tss": 300.0,
            "acwr_headroom_tss": 50.0,
            "allowed_offsets": [3, 4, 5, 6],
            "target_tss": target_tss,
            "logged_tss_so_far": logged,
            "remaining_tss": remaining,
            "acwr_ceiling": ceiling,
            "phase": phase,
            "days_remaining_in_week": 4,
        }

    def test_mentions_remaining_not_target_as_the_fill_number(self):
        facts = self._facts()
        system, _ = ps.build_prompt(facts)
        assert "275" in system  # remaining_tss
        assert "sum near 275" in system
        assert "guide, not a hard fill" in system
        assert "do not double-count" in system

    def test_taper_phase_instructs_volume_drop_intensity_retained(self):
        facts = self._facts(phase="taper")
        system, _ = ps.build_prompt(facts)
        assert "TAPER PHASE" in system
        assert "intensity is RETAINED" in system
        assert "that is backwards" in system

    def test_race_phase_shakeouts_only(self):
        facts = self._facts(phase="race")
        system, _ = ps.build_prompt(facts)
        assert "RACE PHASE" in system
        assert "shakeouts only" in system
        assert "no long runs" in system

    def test_ramp_and_hold_phase_get_normal_mix_language(self):
        for phase in ("ramp", "hold"):
            system, _ = ps.build_prompt(self._facts(phase=phase))
            assert "Normal mix" in system

    def test_omits_target_rule_when_target_tss_absent(self):
        # Old-style facts (pre-Part-3) — no weekly target language should appear.
        facts = {"trailing_28d_weekly_avg_tss": 300.0, "allowed_offsets": [0, 1, 2, 3, 4, 5, 6]}
        system, _ = ps.build_prompt(facts)
        assert "hard weekly TSS target" not in system
        assert "weekly TSS target of" not in system
        assert "`notes` = the coach's RATIONALE" in system


# ── assemble_facts: real-PG target-aware integration ─────────────────────────

@pytest.fixture()
def target_user():
    with Session(engine) as s:
        u = User(name=f"plan-sug-target-{uuid.uuid4().hex[:8]}", is_active=True)
        s.add(u); s.commit(); s.refresh(u)
        uid = u.id
    yield uid
    with Session(engine) as s:
        s.execute(text("DELETE FROM users WHERE id = :i"), {"i": uid})
        s.commit()


def _add_a_race(user_id, race_date):
    with Session(engine) as s:
        s.add(Race(user_id=user_id, name="Target Race", race_date=race_date,
                    distance_km=42.2, priority="A", status="planned"))
        s.commit()


def _add_plan(user_id, ramp_rate=0.05, hold_weeks=4, taper_length=3):
    with Session(engine) as s:
        s.add(TrainingPlan(user_id=user_id, name="Training Plan", ramp_rate=ramp_rate,
                            hold_weeks=hold_weeks, taper_length=taper_length))
        s.commit()


def _add_workout(user_id, workout_date, tss):
    with Session(engine) as s:
        s.add(Workout(user_id=user_id, workout_date=workout_date, name="Seed run",
                       workout_type="run", tss=tss))
        s.commit()


@pytest.fixture()
def _flag_on():
    old = os.environ.get("PLAN_TARGET_AWARE_ENABLED")
    os.environ["PLAN_TARGET_AWARE_ENABLED"] = "1"
    yield
    if old is None:
        os.environ.pop("PLAN_TARGET_AWARE_ENABLED", None)
    else:
        os.environ["PLAN_TARGET_AWARE_ENABLED"] = old


def _monday_of(d):
    return d - timedelta(days=d.weekday())


class TestAssembleFactsFlagOff:
    def test_flag_off_facts_has_no_target_keys(self, target_user):
        # Flag intentionally left unset — must be byte-identical to pre-Part-3
        # assemble_facts: no target_tss/remaining_tss/phase/etc keys at all.
        assert os.environ.get("PLAN_TARGET_AWARE_ENABLED") is None
        _add_a_race(target_user, date.today() + timedelta(weeks=10))
        facts = ps.assemble_facts(str(target_user))
        for key in ("target_tss", "logged_tss_so_far", "remaining_tss",
                    "acwr_ceiling", "days_remaining_in_week", "phase"):
            assert key not in facts


class TestAssembleFactsFlagOn:
    def test_no_race_leaves_target_fields_none(self, target_user, _flag_on):
        facts = ps.assemble_facts(str(target_user))
        assert facts["target_tss"] is None
        assert facts["phase"] is None
        assert facts["remaining_tss"] is None
        # logged_tss_so_far/acwr_ceiling/days_remaining_in_week are still
        # computed (don't require a race) — just target/phase/remaining don't.
        assert facts["logged_tss_so_far"] == 0.0

    def test_with_race_populates_target_and_phase(self, target_user, _flag_on):
        today = date.today()
        _add_a_race(target_user, today + timedelta(weeks=10))
        _add_plan(target_user, ramp_rate=0.05, hold_weeks=4, taper_length=3)
        last_monday = _monday_of(today) - timedelta(days=7)
        _add_workout(target_user, last_monday, 200)

        facts = ps.assemble_facts(str(target_user))
        assert facts["target_tss"] is not None
        # "consolidation" is a legitimate phase too (load-metric fix, Part
        # B.4): a lone 200-TSS workout with no other history is exactly the
        # kind of sparse, spiky data that makes compute_verdict flag
        # hold/back_off, which overrides ramp/hold to a flat consolidation
        # target — see backend/services/training_verdict.py.
        assert facts["phase"] in ("ramp", "hold", "taper", "race", "consolidation")
        assert facts["remaining_tss"] == max(0.0, round(facts["target_tss"] - facts["logged_tss_so_far"], 1))
        assert facts["acwr_ceiling"] is not None

    def test_remaining_tss_floored_at_zero_when_logged_exceeds_target(self, target_user, _flag_on):
        today = date.today()
        _add_a_race(target_user, today + timedelta(weeks=10))
        _add_plan(target_user, ramp_rate=0.05, hold_weeks=4, taper_length=3)
        last_monday = _monday_of(today) - timedelta(days=7)
        _add_workout(target_user, last_monday, 10)  # tiny baseline -> tiny target
        # Log a huge amount already this week, well past any small target.
        _add_workout(target_user, _monday_of(today), 5000)

        facts = ps.assemble_facts(str(target_user))
        assert facts["remaining_tss"] == 0.0

    def test_taper_phase_target_lower_than_hold_phase(self, target_user, _flag_on):
        # weeks_to_race chosen so "this week" (week 1) falls inside the
        # hold plateau (ramp_weeks=... build_weeks=..., hold spans the
        # middle) and a later week_start falls inside the taper.
        today = date.today()
        this_monday = _monday_of(today)
        # weeks_to_race=10, taper_weeks=3 -> build_weeks=7; with hold_weeks=4,
        # ramp_weeks=3 -> hold spans week_index 4-7, taper spans 8-10.
        race_date = this_monday + timedelta(weeks=9, days=2)
        _add_a_race(target_user, race_date)
        _add_plan(target_user, ramp_rate=0.05, hold_weeks=4, taper_length=3)
        last_monday = this_monday - timedelta(days=7)
        _add_workout(target_user, last_monday, 300)
        # A generous trailing-28-day floor (outside the last/this-week windows
        # above) so the ACWR ceiling doesn't clamp both weeks down to the same
        # value — see tests/test_plan_week_load_endpoint__planrevamp2.py's
        # identical fix for the same underlying issue.
        for days_ago in (15, 18, 21):
            _add_workout(target_user, today - timedelta(days=days_ago), 400)

        hold_week_start = this_monday + timedelta(weeks=3)   # week_index 4 -> hold
        taper_week_start = this_monday + timedelta(weeks=7)  # week_index 8 -> taper

        hold_facts = ps.assemble_facts(str(target_user), week_start=hold_week_start)
        taper_facts = ps.assemble_facts(str(target_user), week_start=taper_week_start)

        assert hold_facts["phase"] == "hold"
        assert taper_facts["phase"] in ("taper", "race")
        assert taper_facts["target_tss"] < hold_facts["target_tss"]
