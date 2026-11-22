"""Issue #1883 — body log model + API + averages (P6-9)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from backend.models import User
from backend.services.body_log import seven_day_avg, weekly_body_rollup, weekly_rate_kg


def _rows():
    start = date(2026, 1, 1)
    return [(start + timedelta(days=i), 80.0 + i * 0.1) for i in range(10)]


def test_seven_day_avg_requires_three_samples():
    rows = [(date(2026, 1, 1), 80.0), (date(2026, 1, 2), 80.2)]
    assert seven_day_avg(rows, date(2026, 1, 7)) is None
    rows.append((date(2026, 1, 3), 80.1))
    assert seven_day_avg(rows, date(2026, 1, 7)) == 80.1


def test_weekly_rate_with_gap():
    rows = [
        (date(2026, 1, 1), 80.0),
        (date(2026, 1, 2), 80.0),
        (date(2026, 1, 3), 80.0),
        (date(2026, 1, 8), 79.0),
        (date(2026, 1, 9), 79.0),
        (date(2026, 1, 10), 79.0),
    ]
    rate = weekly_rate_kg(rows, date(2026, 1, 10))
    assert rate == -1.0


def test_weekly_rollup_partial_days():
    ws = date(2026, 2, 2)
    rollup = weekly_body_rollup(
        week_start=ws,
        week_end=ws + timedelta(days=6),
        lunch_by_date={ws: True, ws + timedelta(days=1): False, ws + timedelta(days=2): None},
        steps_by_date={ws: 8000, ws + timedelta(days=1): 10000},
        feet_by_date={ws: 1, ws + timedelta(days=2): 3},
    )
    assert rollup["lunch_rule_yes_count"] == 1
    assert rollup["lunch_rule_logged_days"] == 2
    assert rollup["steps_avg"] == 9000.0
    assert rollup["feet_max"] == 3


@pytest.fixture
def client():
    from backend.main import app

    return TestClient(app)


def test_body_log_routes_require_auth(client):
    assert client.get("/api/body-log").status_code == 401
    assert client.patch("/api/body-log", json={"lunch_rule": True}).status_code == 401
    assert client.get("/api/body-log/weekly-rollup").status_code == 401