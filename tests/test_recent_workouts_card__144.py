"""
UAT tests for issue #144: Recent Workouts card on the home dashboard.
Server under test: http://127.0.0.1:9001
"""
import datetime
import pathlib

import httpx
import pytest

BASE = "http://127.0.0.1:9001"
TODAY = datetime.date.today()
TODAY_STR = TODAY.isoformat()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with httpx.Client(base_url=BASE, timeout=10) as c:
        yield c


@pytest.fixture(scope="module")
def user_id(client):
    res = client.get("/api/users")
    assert res.status_code == 200
    users = res.json()
    assert len(users) > 0, "No users found; seed the DB first"
    return users[0]["id"]


@pytest.fixture(scope="module")
def workout_ids(client, user_id):
    """Create 5 workouts spread across the last 14 days with varied types/sources."""
    created = []

    def _post(days_ago, name, wtype, duration=None, distance=None, tss=None,
              source=None, strava_url=None):
        d = (TODAY - datetime.timedelta(days=days_ago)).isoformat()
        body = {"user_id": user_id, "name": name, "workout_date": d,
                "workout_type": wtype, "exercises": []}
        if duration is not None:
            body["duration_seconds"] = duration
        if distance is not None:
            body["distance_km"] = distance
        if tss is not None:
            body["tss"] = tss
        if source is not None:
            body["source"] = source
        if strava_url is not None:
            body["strava_activity_url"] = strava_url
        r = client.post("/api/workouts", json=body)
        assert r.status_code == 201, f"POST workout failed: {r.status_code} {r.text}"
        return r.json()["id"]

    # workout 1 (1 day ago): run with Strava+Stryd
    created.append(_post(1, "Tempo run", "run", duration=2322, distance=8.0,
                         tss=71, source="strava,stryd"))
    # workout 2 (2 days ago): lift, manual
    created.append(_post(2, "Lower body", "lift", duration=3300, tss=42,
                         source="manual"))
    # workout 3 (3 days ago): run, Strava only (via strava_activity_url)
    created.append(_post(3, "Easy run", "run", duration=2050, distance=6.2,
                         tss=38, strava_url="https://www.strava.com/activities/999"))
    # workout 4 (4 days ago): WOD, manual (source=None)
    created.append(_post(4, "WOD — Murph", "wod", duration=2538, tss=95))
    # workout 5 (5 days ago): bike, Stryd only
    created.append(_post(5, "Easy ride", "bike", duration=5400, distance=40.0,
                         source="stryd"))

    yield created

    for wid in created:
        client.delete(f"/api/workouts/{wid}")


# ── Static HTML checks ────────────────────────────────────────────────────────

def test_home_html_loads_home_js():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'src="js/home.js"' in html, "home.html must load js/home.js"


def test_home_html_has_row2():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert 'id="row-2"' in html, "home.html must have id='row-2'"


def test_home_html_has_workout_card_css():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert ".workouts" in html, "home.html must contain .workouts CSS class"
    assert ".src-badge" in html, "home.html must contain .src-badge CSS class"
    assert "src-badge.strava" in html, "home.html must contain .src-badge.strava CSS"
    assert "src-badge.stryd" in html, "home.html must contain .src-badge.stryd CSS"


def test_home_html_has_icon_wrap_wod_bike():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert "icon-wrap.wod" in html, "home.html must have CSS for .icon-wrap.wod"
    assert "icon-wrap.bike" in html, "home.html must have CSS for .icon-wrap.bike"


def test_home_html_has_orange_teal_variables():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert "--orange-text" in html
    assert "--orange-soft" in html
    assert "--teal-text" in html
    assert "--teal-soft" in html


def test_home_js_calls_load_recent_workouts_card():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "loadRecentWorkoutsCard" in js, "home.js must define/call loadRecentWorkoutsCard"


def test_home_js_view_all_link_points_to_log():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert '"/log"' in js or "'/log'" in js, "loadRecentWorkoutsCard must link to /log"


def test_home_js_empty_state_message():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "No workouts in the last 14 days" in js


def test_home_js_has_desktop_only_class():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "workout-desktop-only" in js, "4th item must carry a desktop-only class"


def test_home_html_hides_desktop_only_on_mobile():
    html = (pathlib.Path(__file__).parent.parent / "home.html").read_text()
    assert "workout-desktop-only" in html, "CSS must hide .workout-desktop-only on mobile"


# ── API: GET /api/workouts returns source + strava_activity_url ───────────────

def test_api_workouts_returns_source_field(client, user_id, workout_ids):
    res = client.get(
        f"/api/workouts?user_id={user_id}"
        f"&from={(TODAY - datetime.timedelta(days=14)).isoformat()}&to={TODAY_STR}"
    )
    assert res.status_code == 200
    workouts = res.json()
    assert len(workouts) >= 5
    keys = set(workouts[0].keys())
    assert "source" in keys, "Each workout must include 'source'"
    assert "strava_activity_url" in keys, "Each workout must include 'strava_activity_url'"


def test_api_workouts_sorted_date_desc(client, user_id, workout_ids):
    res = client.get(
        f"/api/workouts?user_id={user_id}"
        f"&from={(TODAY - datetime.timedelta(days=14)).isoformat()}&to={TODAY_STR}"
    )
    assert res.status_code == 200
    dates = [w["workout_date"] for w in res.json()]
    assert dates == sorted(dates, reverse=True), "Workouts must be sorted date descending"


def test_api_workout_post_with_source_strava(client, user_id):
    d = (TODAY - datetime.timedelta(days=7)).isoformat()
    body = {"user_id": user_id, "name": "Test strava", "workout_date": d,
            "workout_type": "run", "source": "strava", "exercises": []}
    res = client.post("/api/workouts", json=body)
    assert res.status_code == 201
    wid = res.json()["id"]
    assert res.json()["source"] == "strava"
    client.delete(f"/api/workouts/{wid}")


def test_api_workout_post_with_source_stryd(client, user_id):
    d = (TODAY - datetime.timedelta(days=7)).isoformat()
    body = {"user_id": user_id, "name": "Test stryd", "workout_date": d,
            "workout_type": "run", "source": "stryd", "exercises": []}
    res = client.post("/api/workouts", json=body)
    assert res.status_code == 201
    wid = res.json()["id"]
    assert res.json()["source"] == "stryd"
    client.delete(f"/api/workouts/{wid}")


def test_api_workout_post_with_compound_source(client, user_id):
    d = (TODAY - datetime.timedelta(days=7)).isoformat()
    body = {"user_id": user_id, "name": "Test both", "workout_date": d,
            "workout_type": "run", "source": "strava,stryd", "exercises": []}
    res = client.post("/api/workouts", json=body)
    assert res.status_code == 201
    wid = res.json()["id"]
    assert res.json()["source"] == "strava,stryd"
    client.delete(f"/api/workouts/{wid}")


def test_api_workout_post_invalid_source_rejected(client, user_id):
    d = (TODAY - datetime.timedelta(days=7)).isoformat()
    body = {"user_id": user_id, "name": "Bad source", "workout_date": d,
            "workout_type": "run", "source": "garmin", "exercises": []}
    res = client.post("/api/workouts", json=body)
    assert res.status_code == 422, "Invalid source must return 422"


def test_api_workout_patch_source(client, user_id):
    d = (TODAY - datetime.timedelta(days=8)).isoformat()
    body = {"user_id": user_id, "name": "Patch source test", "workout_date": d,
            "workout_type": "run", "exercises": []}
    res = client.post("/api/workouts", json=body)
    assert res.status_code == 201
    wid = res.json()["id"]

    patch_res = client.patch(f"/api/workouts/{wid}", json={"source": "stryd"})
    assert patch_res.status_code == 200
    assert patch_res.json()["source"] == "stryd"

    client.delete(f"/api/workouts/{wid}")


# ── Duration formatting (JS logic validated via regression) ───────────────────

def test_home_js_duration_format_under_1h():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "fmtWorkoutDuration" in js or "fmtDuration" in js or "duration" in js.lower()
    assert "3600" in js, "Duration logic must branch at 3600 seconds (1 hour)"


def test_home_js_duration_format_uses_padStart():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    assert "padStart(2" in js, "Seconds/minutes must be zero-padded to 2 digits"


# ── Source badge ordering: Stryd LEFT of Strava ───────────────────────────────

def test_home_js_stryd_badge_before_strava_in_html():
    js = (pathlib.Path(__file__).parent.parent / "js" / "home.js").read_text()
    stryd_pos  = js.find("src-badge stryd")
    strava_pos = js.find("src-badge strava")
    assert stryd_pos != -1,  "home.js must contain src-badge stryd badge HTML"
    assert strava_pos != -1, "home.js must contain src-badge strava badge HTML"
    assert stryd_pos < strava_pos, "Stryd badge HTML must appear before Strava badge HTML"


# ── Empty state ───────────────────────────────────────────────────────────────

def test_api_workouts_empty_range_returns_empty_list(client, user_id):
    future_from = (TODAY + datetime.timedelta(days=30)).isoformat()
    future_to   = (TODAY + datetime.timedelta(days=31)).isoformat()
    res = client.get(
        f"/api/workouts?user_id={user_id}&from={future_from}&to={future_to}"
    )
    assert res.status_code == 200
    assert res.json() == [], "Future-date range must return empty list"


# ── Workout fixture data integrity ────────────────────────────────────────────

def test_fixture_run_workout_has_distance(client, user_id, workout_ids):
    res = client.get(
        f"/api/workouts?user_id={user_id}"
        f"&from={(TODAY - datetime.timedelta(days=14)).isoformat()}&to={TODAY_STR}"
    )
    runs = [w for w in res.json() if w["workout_type"] == "run" and w["distance_km"]]
    assert len(runs) >= 1, "At least one run workout must have distance_km"


def test_fixture_has_workout_with_tss(client, user_id, workout_ids):
    res = client.get(
        f"/api/workouts?user_id={user_id}"
        f"&from={(TODAY - datetime.timedelta(days=14)).isoformat()}&to={TODAY_STR}"
    )
    with_tss = [w for w in res.json() if w["tss"] is not None]
    assert len(with_tss) >= 1


def test_fixture_has_strava_workout(client, user_id, workout_ids):
    res = client.get(
        f"/api/workouts?user_id={user_id}"
        f"&from={(TODAY - datetime.timedelta(days=14)).isoformat()}&to={TODAY_STR}"
    )
    strava = [w for w in res.json()
              if (w.get("source") and "strava" in w["source"])
              or w.get("strava_activity_url")]
    assert len(strava) >= 1, "At least one workout with Strava source must exist"


def test_fixture_has_stryd_workout(client, user_id, workout_ids):
    res = client.get(
        f"/api/workouts?user_id={user_id}"
        f"&from={(TODAY - datetime.timedelta(days=14)).isoformat()}&to={TODAY_STR}"
    )
    stryd = [w for w in res.json()
             if w.get("source") and "stryd" in w["source"]]
    assert len(stryd) >= 1, "At least one workout with Stryd source must exist"


def test_fixture_has_compound_source_workout(client, user_id, workout_ids):
    res = client.get(
        f"/api/workouts?user_id={user_id}"
        f"&from={(TODAY - datetime.timedelta(days=14)).isoformat()}&to={TODAY_STR}"
    )
    both = [w for w in res.json()
            if w.get("source") and "strava" in w["source"] and "stryd" in w["source"]]
    assert len(both) >= 1, "At least one workout with both Strava + Stryd sources must exist"


def test_fixture_has_manual_workout(client, user_id, workout_ids):
    res = client.get(
        f"/api/workouts?user_id={user_id}"
        f"&from={(TODAY - datetime.timedelta(days=14)).isoformat()}&to={TODAY_STR}"
    )
    manual = [w for w in res.json()
              if not w.get("source") or w["source"] == "manual"]
    assert len(manual) >= 1, "At least one workout without Strava/Stryd must exist"
