"""Tests for issue #1380: per-muscle acute/chronic load, ACWR, and classification.

Acceptance criteria covered:
  AC1 — Service: acute_7d and chronic_28d match acwr.py's uncoupled rolling convention
  AC2 — Classification bands: overused, elevated, balanced, detraining, untrained, inactive
  AC3 — chronic floor: ACWR is null when chronic < CHRONIC_FLOOR
  AC4 — Injured tagging: active injury body_area → group tagged injured in payload
  AC5 — Payload shape: endpoint returns expected top-level keys and per-group structure
  AC6 — Per-source breakdown in payload
"""
from __future__ import annotations

import datetime
import os
import pathlib
import uuid
from typing import Optional

import pytest

from backend.services.muscle_load_acwr import (
    ALL_GROUPS,
    BODY_AREA_TO_GROUP,
    CHRONIC_FLOOR,
    DETRAINING_BOUND,
    ELEVATED_BOUND,
    OVERUSED_BOUND,
    PRIORITY_GROUPS,
    body_area_to_group,
    classify_group,
    compute_acute_chronic,
)

# ── Live-server integration setup ─────────────────────────────────────────────

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
_TEST_PW = "test1380pw!"

_root = pathlib.Path(__file__).resolve().parents[1]
_env_file = _root / ".env"
if _env_file.exists():
    from dotenv import dotenv_values
    _env = dotenv_values(_env_file)
    _uat_url = _env.get("DATABASE_URL_UAT")
else:
    _uat_url = os.environ.get("DATABASE_URL_UAT")

_engine = None
if _uat_url:
    from sqlalchemy import create_engine as _ce
    _engine = _ce(_uat_url, pool_pre_ping=True)


# ── AC1: Acute/chronic math matches acwr.py convention ───────────────────────

class TestComputeAcuteChronic:
    def test_acute_is_last_7_days(self):
        # 35-element series: last 7 each = 10, prior 28 each = 0
        series = [0.0] * 28 + [10.0] * 7
        acute, chronic = compute_acute_chronic(series)
        assert acute == pytest.approx(70.0)
        assert chronic == pytest.approx(0.0)

    def test_chronic_is_mean_of_4_prior_windows(self):
        # Four prior weeks of 100, 200, 300, 400; acute week = 0
        # Expected chronic = (100 + 200 + 300 + 400) / 4 = 250
        week1 = [100.0 / 7] * 7   # oldest
        week2 = [200.0 / 7] * 7
        week3 = [300.0 / 7] * 7
        week4 = [400.0 / 7] * 7
        acute_week = [0.0] * 7
        series = week1 + week2 + week3 + week4 + acute_week
        assert len(series) == 35
        acute, chronic = compute_acute_chronic(series)
        assert acute == pytest.approx(0.0)
        assert chronic == pytest.approx(250.0, rel=1e-9)

    def test_acute_window_excluded_from_chronic(self):
        # Spike only in the acute window — chronic must see prior weeks only
        series = [0.0] * 28 + [100.0] * 7
        acute, chronic = compute_acute_chronic(series)
        assert acute == pytest.approx(700.0)
        # prior weeks all zeros
        assert chronic == pytest.approx(0.0)

    def test_short_series_zero_padded(self):
        # Shorter than 35 elements padded with zeros on the left
        series_short = [10.0] * 7   # only 7 elements = only the acute window
        acute, chronic = compute_acute_chronic(series_short)
        assert acute == pytest.approx(70.0)
        assert chronic == pytest.approx(0.0)

    def test_known_acwr_value(self):
        # acwr.py worked example: acute=350, chronic=300 → ratio≈1.167
        # Build series where each of 4 prior weeks sums to 300
        # and the acute week sums to 350
        prior_daily = 300.0 / 7
        series = [prior_daily] * 28 + [350.0 / 7] * 7
        acute, chronic = compute_acute_chronic(series)
        assert acute == pytest.approx(350.0, rel=1e-6)
        assert chronic == pytest.approx(300.0, rel=1e-6)


# ── AC2: Classification band boundaries ───────────────────────────────────────

class TestClassifyGroup:
    # overused: acwr > 1.5
    def test_overused_above_bound(self):
        assert classify_group("calf", 50.0, 1.51) == "overused"

    def test_overused_exactly_above(self):
        assert classify_group("back", 50.0, OVERUSED_BOUND + 0.001) == "overused"

    # elevated: 1.3 < acwr <= 1.5
    def test_elevated_just_above_elevated_bound(self):
        assert classify_group("quad", 50.0, 1.31) == "elevated"

    def test_elevated_at_overused_bound(self):
        assert classify_group("quad", 50.0, OVERUSED_BOUND) == "elevated"

    def test_elevated_mid_range(self):
        assert classify_group("glute", 50.0, 1.4) == "elevated"

    # balanced: 0.8 <= acwr <= 1.3
    def test_balanced_at_elevated_bound(self):
        assert classify_group("calf", 50.0, ELEVATED_BOUND) == "balanced"

    def test_balanced_at_detraining_bound(self):
        assert classify_group("calf", 50.0, DETRAINING_BOUND) == "balanced"

    def test_balanced_mid_range(self):
        assert classify_group("shoulder", 50.0, 1.0) == "balanced"

    # detraining: acwr < 0.8 with nonzero chronic
    def test_detraining_just_below_bound(self):
        assert classify_group("calf", 50.0, 0.79) == "detraining"

    def test_detraining_zero_acute(self):
        assert classify_group("back", 50.0, 0.0) == "detraining"

    # untrained: chronic near-zero AND group is a priority group
    def test_untrained_priority_calf(self):
        assert classify_group("calf", 0.0, None) == "untrained"

    def test_untrained_priority_hamstring(self):
        assert classify_group("hamstring", 0.0, None) == "untrained"

    def test_untrained_priority_glute(self):
        assert classify_group("glute", 0.0, None) == "untrained"

    def test_untrained_priority_hip(self):
        assert classify_group("hip", 0.0, None) == "untrained"

    def test_untrained_below_chronic_floor(self):
        below_floor = CHRONIC_FLOOR - 0.1
        assert classify_group("calf", below_floor, None) == "untrained"

    # inactive: chronic near-zero AND non-priority group
    def test_inactive_non_priority_shoulder(self):
        assert classify_group("shoulder", 0.0, None) == "inactive"

    def test_inactive_non_priority_core(self):
        assert classify_group("core", 0.0, None) == "inactive"

    def test_inactive_non_priority_chest(self):
        assert classify_group("chest", 0.0, None) == "inactive"

    def test_inactive_non_priority_arm(self):
        assert classify_group("arm", 0.0, None) == "inactive"


# ── AC3: Chronic floor — ACWR null when chronic < CHRONIC_FLOOR ───────────────

class TestChronicFloor:
    def test_acwr_undefined_below_floor(self):
        # When chronic < CHRONIC_FLOOR the caller should pass acwr=None
        # classify_group respects that by returning untrained/inactive
        result = classify_group("quad", CHRONIC_FLOOR - 0.01, None)
        # quad is not a priority group
        assert result == "inactive"

    def test_acwr_defined_at_floor(self):
        # At exactly the floor, a real ACWR should classify normally
        result = classify_group("quad", CHRONIC_FLOOR, 1.0)
        assert result == "balanced"

    def test_constants_match_acwr_module(self):
        # Confirm our bounds mirror acwr.py exactly
        from backend.services.acwr import HIGH_BOUND, LOWER_BOUND, UPPER_BOUND
        assert OVERUSED_BOUND == HIGH_BOUND
        assert ELEVATED_BOUND == UPPER_BOUND
        assert DETRAINING_BOUND == LOWER_BOUND

    def test_chronic_floor_is_positive(self):
        assert CHRONIC_FLOOR > 0


# ── AC4: Injured tagging ───────────────────────────────────────────────────────

class TestBodyAreaMapping:
    def test_calf_maps_to_calf(self):
        assert body_area_to_group("calf") == "calf"

    def test_achilles_maps_to_calf(self):
        assert body_area_to_group("achilles") == "calf"

    def test_hamstring_maps_to_hamstring(self):
        assert body_area_to_group("hamstring") == "hamstring"

    def test_knee_maps_to_quad(self):
        assert body_area_to_group("knee") == "quad"

    def test_glute_maps_to_glute(self):
        assert body_area_to_group("glute") == "glute"

    def test_hip_maps_to_hip(self):
        assert body_area_to_group("hip") == "hip"

    def test_lower_back_maps_to_back(self):
        assert body_area_to_group("lower back") == "back"

    def test_shoulder_maps_to_shoulder(self):
        assert body_area_to_group("shoulder") == "shoulder"

    def test_unknown_area_returns_none(self):
        assert body_area_to_group("toenail") is None

    def test_case_insensitive(self):
        assert body_area_to_group("CALF") == "calf"
        assert body_area_to_group("Hamstring") == "hamstring"

    def test_strips_whitespace(self):
        assert body_area_to_group("  hip  ") == "hip"


# ── Live-server integration tests ─────────────────────────────────────────────

def _skip_no_uat():
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set — skipping live server tests")


def _create_and_login(client):
    import httpx
    from sqlalchemy.orm import Session as _OrmSess

    from backend.auth import CSRF_COOKIE_NAME, hash_password as _hp
    from backend.models import User as _UserModel
    from tests._admin_helpers import admin_cookies

    user_name = f"ml_acwr_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": user_name}, cookies=admin_cookies())
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]

    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hp(_TEST_PW)
        db.commit()

    bare = __import__("httpx").Client(base_url=BASE_URL, timeout=10.0)
    r2 = bare.post("/api/auth/login", json={"username": user_name, "password": _TEST_PW})
    bare.close()
    assert r2.status_code == 200, r2.text

    session_cookie = r2.cookies.get("session")
    csrf_token = r2.cookies.get(CSRF_COOKIE_NAME)
    auth = __import__("httpx").Client(
        base_url=BASE_URL,
        timeout=30.0,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return auth, user_id


def _delete_user(user_id: str) -> None:
    from sqlalchemy.orm import Session as _OrmSess
    from backend.models import User as _UserModel
    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        if u:
            db.delete(u)
            db.commit()


# ── AC5: Payload shape ───────────────────────────────────────────────────────

class TestEndpointPayloadShape:
    def test_endpoint_returns_expected_keys(self):
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            assert "as_of" in data
            assert "groups" in data
            assert "weekly_series" in data
            assert "unclassified" in data
        finally:
            auth.close()
            _delete_user(user_id)

    def test_groups_contain_all_canonical_groups(self):
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            for group in ALL_GROUPS:
                assert group in data["groups"], f"Missing group: {group}"
        finally:
            auth.close()
            _delete_user(user_id)

    def test_each_group_has_required_fields(self):
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            required = {"acute_7d", "chronic_28d", "acwr", "classification",
                        "injured", "source_breakdown"}
            for group, stats in data["groups"].items():
                assert required <= stats.keys(), (
                    f"Group {group} missing keys: {required - stats.keys()}"
                )
        finally:
            auth.close()
            _delete_user(user_id)

    def test_weekly_series_length_matches_weeks_param(self):
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load?weeks=4")
            assert r.status_code == 200, r.text
            data = r.json()
            assert len(data["weekly_series"]) == 4
        finally:
            auth.close()
            _delete_user(user_id)

    def test_weekly_series_entries_have_required_fields(self):
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load?weeks=2")
            assert r.status_code == 200, r.text
            data = r.json()
            for entry in data["weekly_series"]:
                assert "week_start" in entry
                assert "week_end" in entry
                assert "groups" in entry
        finally:
            auth.close()
            _delete_user(user_id)

    def test_unclassified_is_a_list(self):
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            assert isinstance(data["unclassified"], list)
        finally:
            auth.close()
            _delete_user(user_id)

    def test_unauthenticated_returns_401(self):
        import httpx
        _skip_no_uat()
        r = httpx.get(f"{BASE_URL}/api/training/muscle-load", timeout=10.0)
        assert r.status_code == 401

    def test_default_weeks_is_8(self):
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200
            data = r.json()
            assert len(data["weekly_series"]) == 8
        finally:
            auth.close()
            _delete_user(user_id)


# ── AC4 + AC6: Injured tagging and source breakdown (via seeded DB data) ──────

class TestInjuredTaggingAndSourceBreakdown:
    def test_active_injury_tags_group(self):
        """Seed a calf injury (active) and verify calf is tagged injured."""
        import httpx
        _skip_no_uat()
        from datetime import date
        from sqlalchemy.orm import Session as _OrmSess
        from backend.models import InjuryLog

        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        uid = uuid.UUID(user_id)
        try:
            # Insert active calf injury directly into DB
            with _OrmSess(_engine) as db:
                inj = InjuryLog(
                    user_id=uid,
                    kind="injury",
                    body_area="calf",
                    severity=2,
                    started_on=date.today(),
                    ended_on=None,
                )
                db.add(inj)
                db.commit()

            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["groups"]["calf"]["injured"] is True
            # non-injured groups not tagged
            assert data["groups"]["quad"]["injured"] is False
        finally:
            auth.close()
            _delete_user(user_id)

    def test_ended_injury_not_tagged(self):
        """An injury with ended_on in the past must not tag the group."""
        import httpx
        _skip_no_uat()
        from datetime import date, timedelta
        from sqlalchemy.orm import Session as _OrmSess
        from backend.models import InjuryLog

        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        uid = uuid.UUID(user_id)
        try:
            yesterday = date.today() - timedelta(days=1)
            with _OrmSess(_engine) as db:
                inj = InjuryLog(
                    user_id=uid,
                    kind="injury",
                    body_area="calf",
                    severity=1,
                    started_on=yesterday - timedelta(days=7),
                    ended_on=yesterday,
                )
                db.add(inj)
                db.commit()

            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["groups"]["calf"]["injured"] is False
        finally:
            auth.close()
            _delete_user(user_id)

    def test_source_breakdown_sums_to_one(self):
        """When source_breakdown is non-empty all fractions must sum to 1."""
        import httpx
        _skip_no_uat()
        from datetime import date, timedelta
        from decimal import Decimal
        from sqlalchemy.orm import Session as _OrmSess
        from backend.models import MuscleLoadDaily

        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        uid = uuid.UUID(user_id)
        try:
            # Seed mixed-source data so breakdown is non-trivial
            today = date.today()
            with _OrmSess(_engine) as db:
                db.add(MuscleLoadDaily(
                    user_id=uid, load_date=today - timedelta(days=10),
                    muscle_group="calf", load=Decimal("30"), source="run",
                ))
                db.add(MuscleLoadDaily(
                    user_id=uid, load_date=today - timedelta(days=10),
                    muscle_group="calf", load=Decimal("20"), source="strength",
                ))
                db.commit()

            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            breakdown = data["groups"]["calf"]["source_breakdown"]
            if breakdown:
                total = sum(breakdown.values())
                assert total == pytest.approx(1.0, abs=1e-3)
        finally:
            auth.close()
            _delete_user(user_id)

    def test_seeded_high_acwr_classifies_overused(self):
        """Seed heavy recent load on low chronic → calf classified overused."""
        import httpx
        _skip_no_uat()
        from datetime import date, timedelta
        from decimal import Decimal
        from sqlalchemy.orm import Session as _OrmSess
        from backend.models import MuscleLoadDaily

        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        uid = uuid.UUID(user_id)
        try:
            today = date.today()
            with _OrmSess(_engine) as db:
                # Low chronic: 10 TSS/week for 4 prior weeks
                for week_back in range(1, 5):
                    for day_offset in range(7):
                        d = today - timedelta(days=week_back * 7 + day_offset)
                        db.add(MuscleLoadDaily(
                            user_id=uid, load_date=d,
                            muscle_group="calf",
                            load=Decimal("10") / 7,
                            source="run",
                        ))
                # High acute: 100 TSS in the past 7 days
                for day_offset in range(7):
                    d = today - timedelta(days=day_offset)
                    db.add(MuscleLoadDaily(
                        user_id=uid, load_date=d,
                        muscle_group="calf",
                        load=Decimal("100") / 7,
                        source="run",
                    ))
                db.commit()

            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            calf = data["groups"]["calf"]
            # chronic ≈ 10, acute ≈ 100 → acwr ≈ 10 >> 1.5 → overused
            assert calf["classification"] == "overused"
        finally:
            auth.close()
            _delete_user(user_id)
