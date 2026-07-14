"""Tests for issue #1382: Muscle balance view on the training tab.

AC coverage:
  AC1 — Serializer: groups ordered worst-first (overused > elevated > balanced >
         detraining > untrained > inactive); classification chip labels correct;
         inactive groups can be separated from active
  AC2 — Expand row: weekly_series present (sparkline data) + source_breakdown
         (per-source split from #1380 payload)
  AC3 — Data from GET /api/training/muscle-load; endpoint returns expected shape
         with `sorted_groups` list for frontend ordering
  AC4 — Unclassified exercises surfaced as `unclassified` list in payload
  AC5 — Empty/pre-backfill: endpoint returns 200 with empty acute/chronic for
         user with no data; graceful shape preserved
  AC6 — Mobile: no new tests (visual); ordering logic tested here
"""
from __future__ import annotations

import os
import pathlib
import uuid
from typing import Any

import pytest

from backend.services.muscle_load_acwr import (
    ALL_GROUPS,
    classify_group,
)

# ── helpers ───────────────────────────────────────────────────────────────────

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

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://127.0.0.1:9001"
_TEST_PW = "test1382pw!"


def _skip_no_uat():
    if _engine is None:
        pytest.skip("DATABASE_URL_UAT not set — skipping live server tests")


def _create_and_login(client):
    from sqlalchemy.orm import Session as _OrmSess
    from backend.auth import CSRF_COOKIE_NAME, hash_password as _hp
    from backend.models import User as _UserModel
    from tests._admin_helpers import admin_cookies

    user_name = f"mbal_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": user_name}, cookies=admin_cookies())
    assert r.status_code == 201, r.text
    user_id = r.json()["id"]

    with _OrmSess(_engine) as db:
        u = db.get(_UserModel, uuid.UUID(user_id))
        u.password_hash = _hp(_TEST_PW)
        db.commit()

    import httpx
    bare = httpx.Client(base_url=BASE_URL, timeout=10.0)
    r2 = bare.post("/api/auth/login", json={"username": user_name, "password": _TEST_PW})
    bare.close()
    assert r2.status_code == 200, r2.text

    session_cookie = r2.cookies.get("session")
    csrf_token = r2.cookies.get(CSRF_COOKIE_NAME)
    auth = httpx.Client(
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


# ── AC1: Classification ordering (worst-first) ────────────────────────────────

class TestClassificationSortKey:
    """AC1: groups must sort overused > elevated > balanced > detraining > untrained > inactive."""

    def _sort_key(self, classification: str, injured: bool = False) -> tuple:
        from backend.services.muscle_load_acwr import classification_sort_key
        return classification_sort_key(classification, injured)

    def test_overused_worst(self):
        assert self._sort_key("overused") < self._sort_key("elevated")

    def test_elevated_before_balanced(self):
        assert self._sort_key("elevated") < self._sort_key("balanced")

    def test_balanced_before_detraining(self):
        assert self._sort_key("balanced") < self._sort_key("detraining")

    def test_detraining_before_untrained(self):
        assert self._sort_key("detraining") < self._sort_key("untrained")

    def test_untrained_before_inactive(self):
        assert self._sort_key("untrained") < self._sort_key("inactive")

    def test_injured_same_classification_sorts_before_not_injured(self):
        """Within the same classification, injured groups sort first (worst)."""
        assert self._sort_key("balanced", injured=True) < self._sort_key("balanced", injured=False)

    def test_overused_injured_is_worst_overall(self):
        assert self._sort_key("overused", injured=True) < self._sort_key("overused", injured=False)
        assert self._sort_key("overused", injured=True) < self._sort_key("elevated", injured=True)

    def test_inactive_is_always_last(self):
        for cls in ("overused", "elevated", "balanced", "detraining", "untrained"):
            assert self._sort_key(cls, injured=False) < self._sort_key("inactive", injured=False)
            assert self._sort_key(cls, injured=True) < self._sort_key("inactive", injured=True)


class TestSortedGroupsList:
    """AC1: sort_groups_worst_first returns a list in expected order."""

    def _sort(self, groups_dict: dict) -> list:
        from backend.services.muscle_load_acwr import sort_groups_worst_first
        return sort_groups_worst_first(groups_dict)

    def _make_group(
        self,
        classification: str,
        injured: bool = False,
        acute: float = 20.0,
        chronic: float = 15.0,
    ) -> dict:
        return {
            "acute_7d": acute,
            "chronic_28d": chronic,
            "acwr": acute / chronic if chronic >= 5 else None,
            "classification": classification,
            "injured": injured,
            "source_breakdown": {},
        }

    def test_returns_list(self):
        g = {
            "calf": self._make_group("balanced"),
            "quad": self._make_group("overused"),
        }
        result = self._sort(g)
        assert isinstance(result, list)

    def test_each_item_has_group_key(self):
        g = {
            "calf": self._make_group("balanced"),
        }
        result = self._sort(g)
        assert len(result) == 1
        assert result[0]["group"] == "calf"

    def test_overused_first(self):
        g = {
            "calf": self._make_group("balanced"),
            "quad": self._make_group("elevated"),
            "hamstring": self._make_group("overused"),
        }
        result = self._sort(g)
        names = [r["group"] for r in result]
        assert names[0] == "hamstring"

    def test_inactive_last(self):
        g = {
            "arm": self._make_group("inactive"),
            "calf": self._make_group("balanced"),
        }
        result = self._sort(g)
        names = [r["group"] for r in result]
        assert names[-1] == "arm"

    def test_full_worst_first_ordering(self):
        g = {
            "calf": self._make_group("inactive"),
            "quad": self._make_group("detraining"),
            "hamstring": self._make_group("overused"),
            "glute": self._make_group("elevated"),
            "hip": self._make_group("balanced"),
            "core": self._make_group("untrained"),
        }
        result = self._sort(g)
        names = [r["group"] for r in result]
        expected_order = ["hamstring", "glute", "hip", "quad", "core", "calf"]
        assert names == expected_order

    def test_injured_bubbles_within_classification(self):
        g = {
            "calf": self._make_group("balanced", injured=False),
            "quad": self._make_group("balanced", injured=True),
        }
        result = self._sort(g)
        names = [r["group"] for r in result]
        assert names[0] == "quad"  # injured first

    def test_result_contains_all_fields(self):
        g = {
            "calf": self._make_group("overused"),
        }
        result = self._sort(g)
        item = result[0]
        required = {"group", "classification", "injured", "acute_7d", "chronic_28d",
                    "acwr", "source_breakdown"}
        assert required <= item.keys()


# ── AC3: API endpoint returns sorted_groups ───────────────────────────────────

class TestEndpointSortedGroups:
    """AC3: GET /api/training/muscle-load includes sorted_groups list."""

    def test_sorted_groups_present_in_response(self):
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            assert "sorted_groups" in data, "Response must include sorted_groups list"
        finally:
            auth.close()
            _delete_user(user_id)

    def test_sorted_groups_is_list(self):
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            assert isinstance(data["sorted_groups"], list)
        finally:
            auth.close()
            _delete_user(user_id)

    def test_sorted_groups_length_matches_all_groups(self):
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            assert len(data["sorted_groups"]) == len(ALL_GROUPS)
        finally:
            auth.close()
            _delete_user(user_id)

    def test_sorted_groups_items_have_group_field(self):
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            for item in data["sorted_groups"]:
                assert "group" in item
                assert "classification" in item
                assert "injured" in item
                assert "acute_7d" in item
                assert "source_breakdown" in item
        finally:
            auth.close()
            _delete_user(user_id)

    def test_sorted_groups_inactive_last(self):
        """For a user with no data, all groups are inactive/untrained; sorted list still valid."""
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            sg = data["sorted_groups"]
            inactive = [g for g in sg if g["classification"] == "inactive"]
            non_inactive = [g for g in sg if g["classification"] != "inactive"]
            # All inactive items must come after all non-inactive items
            if inactive and non_inactive:
                last_non_inactive_idx = max(sg.index(g) for g in non_inactive)
                first_inactive_idx = min(sg.index(g) for g in inactive)
                assert first_inactive_idx > last_non_inactive_idx
        finally:
            auth.close()
            _delete_user(user_id)

    def test_seeded_overused_appears_first_in_sorted_groups(self):
        """Seed calf as overused; it should be first in sorted_groups."""
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
                # Low chronic (4 prior weeks at 10 TSS each)
                for week_back in range(1, 5):
                    for day_off in range(7):
                        d = today - timedelta(days=week_back * 7 + day_off)
                        db.add(MuscleLoadDaily(
                            user_id=uid, load_date=d,
                            muscle_group="calf",
                            load=Decimal("10") / 7, source="run",
                        ))
                # High acute (100 TSS in 7 days)
                for day_off in range(7):
                    d = today - timedelta(days=day_off)
                    db.add(MuscleLoadDaily(
                        user_id=uid, load_date=d,
                        muscle_group="calf",
                        load=Decimal("100") / 7, source="run",
                    ))
                db.commit()

            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["groups"]["calf"]["classification"] == "overused"
            sg = data["sorted_groups"]
            assert sg[0]["group"] == "calf", (
                f"overused calf should be first; got {sg[0]['group']}"
            )
        finally:
            auth.close()
            _delete_user(user_id)


# ── AC4: Unclassified exercises in response ────────────────────────────────────

class TestUnclassifiedExercises:
    """AC4: unclassified exercises appear in response (existing AC from #1380, re-verified here)."""

    def test_unclassified_is_list_in_response(self):
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            assert "unclassified" in data
            assert isinstance(data["unclassified"], list)
        finally:
            auth.close()
            _delete_user(user_id)


# ── AC5: Graceful empty state (no data) ──────────────────────────────────────

class TestEmptyState:
    """AC5: user with no muscle load data gets 200 with zeroed groups."""

    def test_no_data_returns_200_with_all_groups(self):
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            # All 11 canonical groups must be present
            assert len(data["groups"]) == len(ALL_GROUPS)
        finally:
            auth.close()
            _delete_user(user_id)

    def test_no_data_groups_are_zeroed(self):
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            for group, stats in data["groups"].items():
                assert stats["acute_7d"] == 0.0, f"{group} acute should be 0 for empty user"
                assert stats["chronic_28d"] == 0.0, f"{group} chronic should be 0"
                assert stats["acwr"] is None, f"{group} acwr should be None"
        finally:
            auth.close()
            _delete_user(user_id)

    def test_no_data_sorted_groups_preserves_canonical_count(self):
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load")
            assert r.status_code == 200, r.text
            data = r.json()
            assert len(data["sorted_groups"]) == len(ALL_GROUPS)
        finally:
            auth.close()
            _delete_user(user_id)


# ── AC2: Sparkline / weekly_series present for expand row ─────────────────────

class TestSparklineData:
    """AC2: weekly_series in response carries per-group loads needed for sparkline."""

    def test_weekly_series_entries_include_groups(self):
        import httpx
        _skip_no_uat()
        client = httpx.Client(base_url=BASE_URL, timeout=10.0)
        auth, user_id = _create_and_login(client)
        client.close()
        try:
            r = auth.get("/api/training/muscle-load?weeks=8")
            assert r.status_code == 200, r.text
            data = r.json()
            assert len(data["weekly_series"]) == 8
            for entry in data["weekly_series"]:
                assert "groups" in entry
                assert "week_start" in entry
                assert "week_end" in entry
        finally:
            auth.close()
            _delete_user(user_id)

    def test_source_breakdown_present_per_group(self):
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
                assert "source_breakdown" in data["groups"][group]
                assert isinstance(data["groups"][group]["source_breakdown"], dict)
        finally:
            auth.close()
            _delete_user(user_id)


# ── Frontend HTML: card presence test ────────────────────────────────────────

class TestFrontendCardPresence:
    """AC1/AC3/AC4: training-log.html contains the muscle balance card markup."""

    def _html(self) -> str:
        path = _root / "frontend" / "pages" / "training-log.html"
        return path.read_text(encoding="utf-8")

    def test_muscle_balance_card_present(self):
        """The page has a muscle balance card with correct id."""
        html = self._html()
        assert 'id="muscle-balance-card"' in html, (
            "training-log.html must contain muscle-balance-card element"
        )

    def test_muscle_balance_loading_state_present(self):
        """Loading state element present."""
        html = self._html()
        assert 'id="muscle-balance-loading"' in html

    def test_muscle_balance_empty_state_present(self):
        """Empty state element present."""
        html = self._html()
        assert 'id="muscle-balance-empty"' in html

    def test_muscle_balance_rows_container_present(self):
        """Rows container (where group rows are rendered) is present."""
        html = self._html()
        assert 'id="muscle-balance-rows"' in html

    def test_muscle_balance_show_all_toggle_present(self):
        """'Show all' toggle for inactive groups is present."""
        html = self._html()
        assert 'id="muscle-balance-show-all"' in html

    def test_muscle_balance_unclassified_footnote_present(self):
        """Unclassified exercises footnote container is present."""
        html = self._html()
        assert 'id="muscle-balance-unclassified"' in html

    def test_muscle_balance_in_performance_panel(self):
        """The card lives inside the performance tab panel."""
        html = self._html()
        perf_panel_idx = html.find('id="training-panel-performance"')
        card_idx = html.find('id="muscle-balance-card"')
        assert perf_panel_idx != -1
        assert card_idx != -1
        assert card_idx > perf_panel_idx, (
            "muscle-balance-card must be inside training-panel-performance"
        )


# ── Unit: classification_sort_key is exported ────────────────────────────────

class TestExportsPresent:
    """Verify new symbols are importable from muscle_load_acwr."""

    def test_classification_sort_key_importable(self):
        from backend.services.muscle_load_acwr import classification_sort_key
        assert callable(classification_sort_key)

    def test_sort_groups_worst_first_importable(self):
        from backend.services.muscle_load_acwr import sort_groups_worst_first
        assert callable(sort_groups_worst_first)
