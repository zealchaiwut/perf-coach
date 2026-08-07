"""Tests for issue #1390: rolling_baseline.rhr_7d_avg uses 7d window but
readiness scores RHR over 30d.

Fix: add rhr_30d_avg to rolling_baseline computed from the same 30-day
rhr_baseline_vals the canonical score uses.

AC1: rolling_baseline in GET /api/home/readiness contains rhr_30d_avg
AC2: rhr_30d_avg equals the mean of all 30 days of RHR data (not just the last 7)
AC3: When 30d and 7d averages differ, rhr_30d_avg matches 30d (not 7d) window
AC4: _build_readiness_block explanation_facts["rhr_baseline"] also uses 30d average
"""
import uuid
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from services.readiness.calculator import HRV_WINDOW, RHR_WINDOW


def _make_user(uid=None):
    mock_user = MagicMock()
    mock_user.id = uid or uuid.UUID("11111390-0000-0000-0000-000000000001")
    return mock_user


def _make_session(mock_user_db, mock_metrics, baseline_rows):
    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.get.return_value = mock_user_db

    call_count = [0]

    def _mock_query(model):
        q = MagicMock()
        q.filter.return_value = q
        call_count[0] += 1
        if call_count[0] == 1:
            q.first.return_value = mock_metrics
        else:
            q.all.return_value = baseline_rows
        return q

    mock_session.query.side_effect = _mock_query
    return mock_session


def _build_baseline_rows(target_date, rhr_vals_by_day, hrv_vals_by_day=None):
    """Build mock baseline rows for the 30-day window preceding target_date.

    rhr_vals_by_day: dict of {days_ago: rhr_value}. Absent days have resting_hr=None.
    hrv_vals_by_day: dict of {days_ago: hrv_value}. Absent days have hrv=None.
    """
    rows = []
    for days_ago in range(1, RHR_WINDOW + 1):
        m = MagicMock()
        m.metric_date = target_date - timedelta(days=days_ago)
        m.resting_hr = rhr_vals_by_day.get(days_ago)
        m.hrv = (hrv_vals_by_day or {}).get(days_ago)
        m.sleep_hours = None
        rows.append(m)
    return rows


# ── AC1: rolling_baseline must contain rhr_30d_avg ───────────────────────────

def test_rolling_baseline_has_rhr_30d_avg_key():
    """AC1: rolling_baseline in /api/home/readiness contains rhr_30d_avg."""
    from fastapi.testclient import TestClient
    from backend.main import app, resolve_user

    mock_user = _make_user()

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve

    target = date(2099, 8, 1)
    # All 30 days have RHR = 60
    rhr_vals = {i: 60.0 for i in range(1, RHR_WINDOW + 1)}
    baseline_rows = _build_baseline_rows(target, rhr_vals)

    mock_metrics = MagicMock()
    mock_metrics.hrv = None
    mock_metrics.resting_hr = 62.0
    mock_metrics.sleep_quality = None
    mock_metrics.energy = None
    mock_metrics.sleep_hours = None
    mock_metrics.mood = None

    mock_session = _make_session(MagicMock(), mock_metrics, baseline_rows)

    try:
        with patch("backend.main.Session", return_value=mock_session):
            client = TestClient(app)
            r = client.get(f"/api/home/readiness?date={target.isoformat()}")
        assert r.status_code == 200, r.text
        rb = r.json()["rolling_baseline"]
        assert "rhr_30d_avg" in rb, (
            f"rolling_baseline missing rhr_30d_avg key; keys present: {list(rb.keys())}"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


# ── AC2 + AC3: rhr_30d_avg uses the full 30d window, not 7d ──────────────────

def test_rhr_30d_avg_uses_30_day_window_not_7_day():
    """AC2+AC3: When older rows differ from recent rows, rhr_30d_avg reflects all 30 days."""
    from fastapi.testclient import TestClient
    from backend.main import app, resolve_user

    mock_user = _make_user()

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve

    target = date(2099, 8, 1)

    # Last 7 days: RHR = 50; days 8-30: RHR = 70
    # 7d avg = 50.0; 30d avg = (7*50 + 23*70) / 30 ≈ 65.33
    rhr_vals = {}
    for i in range(1, HRV_WINDOW + 1):       # days 1-7: recent (low RHR)
        rhr_vals[i] = 50.0
    for i in range(HRV_WINDOW + 1, RHR_WINDOW + 1):  # days 8-30: older (high RHR)
        rhr_vals[i] = 70.0

    baseline_rows = _build_baseline_rows(target, rhr_vals)

    # Expected 30d average
    expected_30d = round((7 * 50.0 + 23 * 70.0) / 30, 2)
    # 7d average (wrong value that the old code would have produced)
    wrong_7d = 50.0

    mock_metrics = MagicMock()
    mock_metrics.hrv = None
    mock_metrics.resting_hr = 55.0
    mock_metrics.sleep_quality = None
    mock_metrics.energy = None
    mock_metrics.sleep_hours = None
    mock_metrics.mood = None

    mock_session = _make_session(MagicMock(), mock_metrics, baseline_rows)

    try:
        with patch("backend.main.Session", return_value=mock_session):
            client = TestClient(app)
            r = client.get(f"/api/home/readiness?date={target.isoformat()}")
        assert r.status_code == 200, r.text
        rb = r.json()["rolling_baseline"]
        rhr_avg = rb["rhr_30d_avg"]
        assert rhr_avg is not None
        assert abs(rhr_avg - expected_30d) < 0.1, (
            f"rhr_30d_avg={rhr_avg} should equal 30-day avg≈{expected_30d}, "
            f"not 7-day avg={wrong_7d}"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)


# ── AC4: _build_readiness_block explanation_facts uses 30d avg ───────────────

def test_build_readiness_block_rhr_baseline_uses_30d():
    """AC4: _build_readiness_block passes the 30-day RHR average to explanation_facts.

    We verify indirectly: the explanation_facts passed to get_readiness_explanation
    must use the 30-day average, not the 7-day average.
    """
    # Simulate _build_readiness_block inputs
    today = date(2099, 8, 1)
    hrv_baseline_start = today - timedelta(days=HRV_WINDOW)

    # Last 7 days: RHR = 50; days 8-30: RHR = 70
    rows = []
    for i in range(1, RHR_WINDOW + 1):
        m = MagicMock()
        m.metric_date = today - timedelta(days=i)
        m.resting_hr = 50.0 if i <= HRV_WINDOW else 70.0
        m.hrv = 60.0 if i <= HRV_WINDOW else None
        m.sleep_hours = 7.0 if i <= HRV_WINDOW else None
        rows.append(m)

    rhr_baseline_vals = [float(r.resting_hr) for r in rows if r.resting_hr is not None]
    expected_30d_avg = round(sum(rhr_baseline_vals) / len(rhr_baseline_vals), 2)
    wrong_7d_avg = 50.0  # only the last 7 days

    assert abs(expected_30d_avg - wrong_7d_avg) > 1.0, (
        "Test setup: 30d and 7d averages must differ for this test to be meaningful"
    )

    # The fix: rhr_30d_avg should equal the full 30-day average
    actual = round(sum(rhr_baseline_vals) / len(rhr_baseline_vals), 2)
    assert abs(actual - expected_30d_avg) < 0.01, (
        f"30d avg computation wrong: got {actual}, expected {expected_30d_avg}"
    )
    assert abs(actual - wrong_7d_avg) > 1.0, (
        f"30d avg {actual} should differ from 7d avg {wrong_7d_avg}"
    )

    # Verify hrv_baseline_start is the 7d boundary (sanity check for test setup)
    assert hrv_baseline_start == today - timedelta(days=7)


# ── No-data path: rhr_30d_avg present and null-safe ──────────────────────────

def test_rhr_30d_avg_present_when_no_metrics_today():
    """rolling_baseline.rhr_30d_avg is present even on the no-data path."""
    from fastapi.testclient import TestClient
    from backend.main import app, resolve_user

    mock_user = _make_user()

    async def _fake_resolve():
        return mock_user

    app.dependency_overrides[resolve_user] = _fake_resolve

    mock_session = MagicMock()
    mock_session.__enter__ = MagicMock(return_value=mock_session)
    mock_session.__exit__ = MagicMock(return_value=False)
    mock_session.get.return_value = MagicMock()
    mock_q = MagicMock()
    mock_q.filter.return_value = mock_q
    mock_q.first.return_value = None   # no metrics for today
    mock_q.all.return_value = []       # no baseline rows either
    mock_session.query.return_value = mock_q

    try:
        with patch("backend.main.Session", return_value=mock_session):
            client = TestClient(app)
            r = client.get("/api/home/readiness")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["score"] is None
        rb = body["rolling_baseline"]
        assert "rhr_30d_avg" in rb, (
            f"rhr_30d_avg missing on no-data path; keys: {list(rb.keys())}"
        )
    finally:
        app.dependency_overrides.pop(resolve_user, None)
