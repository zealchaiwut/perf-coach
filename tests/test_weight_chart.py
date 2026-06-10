"""Tests for issue #337: GET /api/weight-chart endpoint with moving average (runs against UAT)

9 AC anchors:
  (a) correct response structure
  (b) actuals are sparse
  (c) trend is dense with nulls for empty windows
  (d) moving average math correct for synthetic data
  (e) stats.delta_7d_kg correct
  (f) include_target=true returns target block
  (g) include_target=false omits target block (key absent)
  (h) range > 365 days returns 422
  (i) projected_path is monotonic toward target_date
"""
import os
import uuid
import datetime
import pytest
import httpx

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:" + os.environ.get("UAT_PORT", "")
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )

TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()


def _create_user(client: httpx.Client) -> str:
    name = f"wc337_{uuid.uuid4().hex[:8]}"
    r = client.post("/api/users", json={"name": name})
    assert r.status_code == 201, f"Failed to create test user: {r.text}"
    return r.json()["id"]


def _delete_user(client: httpx.Client, user_id: str) -> None:
    client.delete(f"/api/users/{user_id}")


def _log_weight(client: httpx.Client, user_id: str, weight_kg: float, entry_date: str) -> None:
    r = client.post("/api/weight-entries", json={
        "user_id": user_id,
        "entry_date": entry_date,
        "weight_kg": weight_kg,
    })
    assert r.status_code in (201, 409), f"Failed to log weight: {r.text}"


def _create_target(client: httpx.Client, user_id: str) -> dict:
    r = client.post("/api/weight-targets", json={
        "user_id": user_id,
        "start_weight_kg": 85.0,
        "start_date": (TODAY - datetime.timedelta(days=30)).isoformat(),
        "target_weight_kg": 75.0,
        "target_date": (TODAY + datetime.timedelta(days=180)).isoformat(),
    })
    assert r.status_code == 201, f"Failed to create target: {r.text}"
    return r.json()


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


# --- (a) correct response structure ---

def test_weight_chart_a_correct_response_structure(client):
    """AC (a): GET /api/weight-chart returns 200 with range, actuals, trend, target, stats keys."""
    uid = _create_user(client)
    try:
        r = client.get("/api/weight-chart", params={"user_id": uid})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "range" in data
        assert "actuals" in data
        assert "trend" in data
        assert "target" in data
        assert "stats" in data
        assert "from" in data["range"]
        assert "to" in data["range"]
        assert isinstance(data["actuals"], list)
        assert isinstance(data["trend"], list)
        # trend covers 90 days by default
        assert len(data["trend"]) == 90
        assert "current_weight_kg" in data["stats"]
        assert "current_avg_kg" in data["stats"]
        assert "delta_7d_kg" in data["stats"]
        assert "delta_30d_kg" in data["stats"]
    finally:
        _delete_user(client, uid)


# --- (b) actuals are sparse ---

def test_weight_chart_b_actuals_are_sparse(client):
    """AC (b): actuals contains exactly one object per real weight_entry row; gaps are not filled."""
    uid = _create_user(client)
    try:
        d1 = (TODAY - datetime.timedelta(days=50)).isoformat()
        d2 = (TODAY - datetime.timedelta(days=20)).isoformat()
        d3 = (TODAY - datetime.timedelta(days=5)).isoformat()
        _log_weight(client, uid, 88.0, d1)
        _log_weight(client, uid, 87.5, d2)
        _log_weight(client, uid, 87.0, d3)

        r = client.get("/api/weight-chart", params={"user_id": uid})
        assert r.status_code == 200, r.text
        data = r.json()
        assert len(data["actuals"]) == 3
        actual_dates = {a["date"] for a in data["actuals"]}
        assert actual_dates == {d1, d2, d3}
        # Verify each actual has date and weight_kg keys
        for a in data["actuals"]:
            assert "date" in a
            assert "weight_kg" in a
    finally:
        _delete_user(client, uid)


# --- (c) trend is dense with nulls for empty windows ---

def test_weight_chart_c_trend_is_dense_with_nulls(client):
    """AC (c): trend has one point per day in range; days with no entries in [D-6, D] emit null."""
    uid = _create_user(client)
    try:
        from_d = (TODAY - datetime.timedelta(days=10)).isoformat()
        to_d = TODAY_STR
        # Single entry at D-3; days D-10 through D-7 have empty 7-day windows
        entry_date = (TODAY - datetime.timedelta(days=3)).isoformat()
        _log_weight(client, uid, 88.0, entry_date)

        r = client.get("/api/weight-chart", params={
            "user_id": uid, "from": from_d, "to": to_d,
        })
        assert r.status_code == 200, r.text
        data = r.json()
        trend = data["trend"]
        # Dense: 11 days (D-10 … D)
        assert len(trend) == 11
        assert all("date" in t for t in trend)
        assert all("weight_kg" in t for t in trend)

        # Days D-10 through D-7 have no entries in their [D-6, D] window → null
        null_dates = {(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(7, 11)}
        for t in trend:
            if t["date"] in null_dates:
                assert t["weight_kg"] is None, f"Expected null for {t['date']}, got {t['weight_kg']}"
        # D-3 and later have the entry in window → non-null
        non_null_dates = {(TODAY - datetime.timedelta(days=i)).isoformat() for i in range(0, 4)}
        for t in trend:
            if t["date"] in non_null_dates:
                assert t["weight_kg"] is not None, f"Expected non-null for {t['date']}"
    finally:
        _delete_user(client, uid)


# --- (d) moving average math correct for synthetic data ---

def test_weight_chart_d_moving_average_math(client):
    """AC (d): 7 entries [88,89,88,90,88,89,88] on consecutive days → MA for last day = 88.57."""
    uid = _create_user(client)
    try:
        weights = [88, 89, 88, 90, 88, 89, 88]
        base = TODAY - datetime.timedelta(days=20)
        for i, w in enumerate(weights):
            d = (base + datetime.timedelta(days=i)).isoformat()
            _log_weight(client, uid, float(w), d)

        from_d = base.isoformat()
        to_d = (base + datetime.timedelta(days=6)).isoformat()
        r = client.get("/api/weight-chart", params={
            "user_id": uid, "from": from_d, "to": to_d,
        })
        assert r.status_code == 200, r.text
        data = r.json()
        last_trend = data["trend"][-1]
        assert last_trend["weight_kg"] is not None
        assert abs(last_trend["weight_kg"] - 88.57) < 0.01, (
            f"Expected MA ≈ 88.57, got {last_trend['weight_kg']}"
        )
    finally:
        _delete_user(client, uid)


# --- (e) stats.delta_7d_kg correct ---

def test_weight_chart_e_stats_delta_7d_correct(client):
    """AC (e): stats.delta_7d_kg is non-null and reflects weight trend direction."""
    uid = _create_user(client)
    try:
        # Cluster A: ~14-18 days ago at 90 kg
        for i in range(5):
            d = (TODAY - datetime.timedelta(days=14 + i)).isoformat()
            _log_weight(client, uid, 90.0, d)
        # Cluster B: ~1-5 days ago at 88 kg
        for i in range(5):
            d = (TODAY - datetime.timedelta(days=1 + i)).isoformat()
            _log_weight(client, uid, 88.0, d)

        r = client.get("/api/weight-chart", params={"user_id": uid})
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["stats"]["delta_7d_kg"] is not None
        # Weight dropped, so delta should be negative
        assert data["stats"]["delta_7d_kg"] < 0, (
            f"Expected negative delta_7d_kg, got {data['stats']['delta_7d_kg']}"
        )
    finally:
        _delete_user(client, uid)


# --- (f) include_target=true returns target block ---

def test_weight_chart_f_include_target_true_returns_block(client):
    """AC (f): include_target=true with active target returns target object with projected_path."""
    uid = _create_user(client)
    try:
        _create_target(client, uid)
        _log_weight(client, uid, 85.0, TODAY_STR)

        r = client.get("/api/weight-chart", params={"user_id": uid, "include_target": "true"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "target" in data
        assert data["target"] is not None
        assert "projected_path" in data["target"]
        assert isinstance(data["target"]["projected_path"], list)
        assert len(data["target"]["projected_path"]) >= 1
        for pt in data["target"]["projected_path"]:
            assert "date" in pt
            assert "weight_kg" in pt
    finally:
        _delete_user(client, uid)


# --- (g) include_target=false omits target block (key absent) ---

def test_weight_chart_g_include_target_false_omits_block(client):
    """AC (g): include_target=false means 'target' key is completely absent from the response."""
    uid = _create_user(client)
    try:
        r = client.get("/api/weight-chart", params={"user_id": uid, "include_target": "false"})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "target" not in data, f"Expected 'target' key absent, found: {data.get('target')}"
    finally:
        _delete_user(client, uid)


# --- (h) range > 365 days returns 422 ---

def test_weight_chart_h_range_exceeds_365_returns_422(client):
    """AC (h): Date range > 365 days returns 422."""
    uid = _create_user(client)
    try:
        r = client.get("/api/weight-chart", params={
            "user_id": uid,
            "from": "2020-01-01",
            "to": "2021-06-01",
        })
        assert r.status_code == 422, f"Expected 422 for >365-day range, got {r.status_code}"
    finally:
        _delete_user(client, uid)


# --- (i) projected_path is monotonic toward target_date ---

def test_weight_chart_i_projected_path_is_monotonic(client):
    """AC (i): projected_path moves monotonically from current weight toward target_weight_kg."""
    uid = _create_user(client)
    try:
        _create_target(client, uid)  # start=85, goal=75 (decreasing)
        _log_weight(client, uid, 84.0, TODAY_STR)

        r = client.get("/api/weight-chart", params={"user_id": uid, "include_target": "true"})
        assert r.status_code == 200, r.text
        data = r.json()
        path = data["target"]["projected_path"]
        assert len(path) >= 2, "Expected at least 2 projected_path points"
        weights = [p["weight_kg"] for p in path]
        # Goal is lower than start → monotonically non-increasing
        for i in range(len(weights) - 1):
            assert weights[i] >= weights[i + 1], (
                f"Not monotonically decreasing at index {i}: {weights[i]} -> {weights[i + 1]}"
            )
    finally:
        _delete_user(client, uid)


# ═══════════════ Issue #421 — Plan series, milestones, today marker ═══════════════

def _create_target_421(client: httpx.Client, user_id: str) -> dict:
    r = client.post("/api/weight-targets", json={
        "user_id": user_id,
        "start_weight_kg": 90.0,
        "start_date": (TODAY - datetime.timedelta(days=60)).isoformat(),
        "target_weight_kg": 80.0,
        "target_date": (TODAY + datetime.timedelta(days=120)).isoformat(),
    })
    assert r.status_code == 201, f"Failed to create target: {r.text}"
    return r.json()


# --- (a) plan_series spans exactly the requested date range, one point per day ---

def test_weight_chart_421_a_plan_series_spans_date_range(client):
    """AC (a): plan_series has exactly one point per day across the requested range."""
    uid = _create_user(client)
    try:
        _create_target_421(client, uid)
        from_d = (TODAY - datetime.timedelta(days=29)).isoformat()
        to_d = TODAY_STR
        r = client.get("/api/weight-chart", params={"user_id": uid, "from": from_d, "to": to_d})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "plan_series" in data, "plan_series missing from response"
        ps = data["plan_series"]
        assert ps is not None, "plan_series is null with active target"
        assert len(ps) == 30, f"Expected 30 plan_series points for 30-day range, got {len(ps)}"
        for pt in ps:
            assert "date" in pt and "plan_kg" in pt
        assert ps[0]["date"] == from_d
        assert ps[-1]["date"] == to_d
    finally:
        _delete_user(client, uid)


# --- (b) plan_series absent/null when no active target ---

def test_weight_chart_421_b_plan_series_null_when_no_target(client):
    """AC (b): plan_series is null or absent when no active target exists."""
    uid = _create_user(client)
    try:
        r = client.get("/api/weight-chart", params={"user_id": uid})
        assert r.status_code == 200, r.text
        data = r.json()
        plan_series = data.get("plan_series", None)
        assert plan_series is None, f"Expected plan_series null, got {plan_series}"
    finally:
        _delete_user(client, uid)


# --- (c) future_milestones excludes today, includes goal ---

def test_weight_chart_421_c_future_milestones_excludes_today_includes_goal(client):
    """AC (c): future_milestones has no 'today' row and includes 'goal' row."""
    uid = _create_user(client)
    try:
        _create_target_421(client, uid)
        r = client.get("/api/weight-chart", params={"user_id": uid})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "future_milestones" in data, "future_milestones missing"
        ms = data["future_milestones"]
        assert ms is not None
        kinds = [m["kind"] for m in ms]
        assert "today" not in kinds, f"today row found in future_milestones: {ms}"
        assert "goal" in kinds, f"goal row missing from future_milestones: {ms}"
    finally:
        _delete_user(client, uid)


# --- (d) today_marker.gap matches /weight-targets/active gap ---

def test_weight_chart_421_d_today_marker_gap_matches_active_target(client):
    """AC (d): today_marker.gap_kg and gap_direction match /api/weight-targets/active."""
    uid = _create_user(client)
    try:
        _create_target_421(client, uid)
        for i in range(3):
            _log_weight(client, uid, 88.0, (TODAY - datetime.timedelta(days=i)).isoformat())

        r_chart = client.get("/api/weight-chart", params={"user_id": uid})
        assert r_chart.status_code == 200, r_chart.text
        chart_data = r_chart.json()

        r_active = client.get("/api/weight-targets/active", params={"user_id": uid})
        assert r_active.status_code == 200, r_active.text
        active_data = r_active.json()["target"]

        marker = chart_data.get("today_marker")
        assert marker is not None, "today_marker missing"
        assert marker["gap_kg"] == active_data["gap_kg"], (
            f"gap_kg mismatch: chart={marker['gap_kg']} active={active_data['gap_kg']}"
        )
        assert marker["gap_direction"] == active_data["gap_direction"], (
            f"gap_direction mismatch: chart={marker['gap_direction']} active={active_data['gap_direction']}"
        )
    finally:
        _delete_user(client, uid)


# --- (e) logged_today true/false correct ---

def test_weight_chart_421_e_logged_today_correct(client):
    """AC (e): logged_today is false before logging and true after."""
    uid = _create_user(client)
    try:
        r = client.get("/api/weight-chart", params={"user_id": uid})
        assert r.status_code == 200, r.text
        assert "logged_today" in r.json(), "logged_today missing"
        assert r.json()["logged_today"] is False, "Expected False before logging"

        _log_weight(client, uid, 88.0, TODAY_STR)

        r2 = client.get("/api/weight-chart", params={"user_id": uid})
        assert r2.status_code == 200, r2.text
        assert r2.json()["logged_today"] is True, "Expected True after logging"
    finally:
        _delete_user(client, uid)


# --- (f) today_delta_kg null when yesterday entry missing ---

def test_weight_chart_421_f_today_delta_null_when_no_yesterday(client):
    """AC (f): today_delta_kg is null when yesterday's entry is missing."""
    uid = _create_user(client)
    try:
        _log_weight(client, uid, 88.0, TODAY_STR)

        r = client.get("/api/weight-chart", params={"user_id": uid})
        assert r.status_code == 200, r.text
        data = r.json()
        assert "today_delta_kg" in data, "today_delta_kg missing"
        assert data["today_delta_kg"] is None, (
            f"Expected null when no yesterday entry, got {data['today_delta_kg']}"
        )
    finally:
        _delete_user(client, uid)
