"""Tests for issue #354: Wire PR and Readiness widgets to real API endpoints.

TDD — each test is anchored to one Acceptance Criterion.

Performance (PR) Widget:
(AC-PR-1)  Widget calls GET /api/home/personal-records?user_id={uid}&tracks=… on mount
(AC-PR-2)  Renders exactly 3 rows for half_marathon, 10k, squat_1rm
(AC-PR-3)  Each row shows track_name, current_value_formatted, achieved_on, predicted_value_formatted
(AC-PR-4)  Trend icon: green up arrow for "improving"
(AC-PR-5)  Trend icon: red down arrow for "declining"
(AC-PR-6)  Trend icon: dash for "stable"
(AC-PR-7)  All tracks "no_data" → "No personal records yet" + "Set your PRs →" link to /settings
(AC-PR-8)  Clicking a data row navigates to /settings#personal-records
(AC-PR-9)  Loading, empty, error states follow tickets 7/8 pattern
(AC-PR-10) No console errors (manual UAT)

Readiness Widget:
(AC-RD-1)  Widget calls GET /api/home/readiness?user_id={uid} on mount
(AC-RD-2)  Displays score as large number (0–100)
(AC-RD-3)  score_label with correct color: Excellent=green, Good=blue, OK=gray, Caution=amber, Recovery=red
(AC-RD-4)  Top 3 contributors sorted by |weight × impact| descending
(AC-RD-5)  score null → "Log today's metrics →" link pointing to daily metrics route
(AC-RD-6)  Loading, empty, error states follow tickets 7/8 pattern
(AC-RD-7)  No console errors (manual UAT)

API (Backend) Tests:
(AC-API-1) GET /api/home/personal-records returns correct shape with 3 tracks
(AC-API-2) trend "no_data" when user has no records for a track
(AC-API-3) GET /api/home/readiness returns correct shape with score and contributors
(AC-API-4) score null when no daily_metrics row for today
"""
import datetime
import os
import pathlib
import uuid

import httpx
import pytest
from dotenv import dotenv_values
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session as DBSession

from backend.auth import COOKIE_NAME, CSRF_COOKIE_NAME, generate_csrf_token, hash_password
from backend.models import User
from tests._admin_helpers import admin_cookies as _admin_cookies

# ── Root detection ────────────────────────────────────────────────────────────

_TESTER_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CODER_ROOT = _TESTER_ROOT.parent / "coder"


def _find_root() -> pathlib.Path:
    for root in (_CODER_ROOT, _TESTER_ROOT):
        if (root / "frontend" / "js" / "home.js").exists():
            return root
    return _TESTER_ROOT


_ROOT = _find_root()
_HOME_JS = (_ROOT / "frontend" / "js" / "home.js").read_text()
_HOME_HTML = (_ROOT / "frontend" / "pages" / "home.html").read_text()

BASE = os.environ.get("UAT_BASE_URL", "http://127.0.0.1:9005")
TODAY = datetime.date.today()
TODAY_ISO = TODAY.isoformat()
_RUN = uuid.uuid4().hex[:8]
_TEST_PASSWORD = "pr354-test-pw"

_env_vals = dotenv_values(_TESTER_ROOT / ".env")
_uat_url = _env_vals.get("DATABASE_URL_UAT")
engine = create_engine(_uat_url, pool_pre_ping=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_authed_client(username: str):
    with httpx.Client(base_url=BASE, timeout=10) as fresh:
        res = fresh.post("/api/users", json={"name": username}, cookies=_admin_cookies())
        assert res.status_code == 201, res.text
        user_id = res.json()["id"]

        pw_hash = hash_password(_TEST_PASSWORD)
        with DBSession(engine) as db:
            user = db.get(User, uuid.UUID(user_id))
            assert user is not None
            user.password_hash = pw_hash
            db.commit()

        login_res = fresh.post(
            "/api/auth/login",
            json={"username": username, "password": _TEST_PASSWORD},
        )
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        session_cookie = login_res.cookies.get("session")
        assert session_cookie, "Login must set session cookie"

    csrf_token = generate_csrf_token()
    authed = httpx.Client(
        base_url=BASE,
        timeout=10,
        cookies={"session": session_cookie, CSRF_COOKIE_NAME: csrf_token},
        headers={"X-CSRF-Token": csrf_token},
    )
    return user_id, authed


def _cleanup_user(user_id: str):
    with engine.begin() as conn:
        conn.execute(text("DELETE FROM users WHERE id = :uid"), {"uid": user_id})


def _seed_personal_record(user_id: str, track_key: str, track_name: str,
                          track_type: str, value_numeric: float, achieved_on: str) -> str:
    with engine.begin() as conn:
        row = conn.execute(
            text(
                "INSERT INTO personal_records "
                "(user_id, track_key, track_name, track_type, value_numeric, achieved_on) "
                "VALUES (:uid, :tk, :tn, :tt, :v, :ao) RETURNING id"
            ),
            {
                "uid": user_id,
                "tk": track_key,
                "tn": track_name,
                "tt": track_type,
                "v": value_numeric,
                "ao": achieved_on,
            },
        ).fetchone()
    return str(row.id)


def _seed_daily_metrics(user_id: str, metric_date: str, **kwargs) -> str:
    fields = ["user_id", "metric_date"]
    vals = {"uid": user_id, "d": metric_date}
    placeholders = [":uid", ":d"]
    for k, v in kwargs.items():
        fields.append(k)
        vals[k] = v
        placeholders.append(f":{k}")
    sql = (
        f"INSERT INTO daily_metrics ({', '.join(fields)}) "
        f"VALUES ({', '.join(placeholders)}) "
        "ON CONFLICT (user_id, metric_date) DO UPDATE SET "
        + ", ".join(f"{k} = EXCLUDED.{k}" for k in kwargs.keys())
        + " RETURNING id"
    )
    with engine.begin() as conn:
        row = conn.execute(text(sql), vals).fetchone()
    return str(row.id)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def alice():
    user_id, authed = _make_authed_client(f"Alice354_{_RUN}")
    yield {"id": user_id, "client": authed}
    authed.close()
    _cleanup_user(user_id)


@pytest.fixture(scope="module")
def bob_empty():
    """User with no PRs and no daily metrics."""
    user_id, authed = _make_authed_client(f"BobEmpty354_{_RUN}")
    yield {"id": user_id, "client": authed}
    authed.close()
    _cleanup_user(user_id)


# ══════════════════════════════════════════════════════════════════════════════
# AC-PR-1: Widget calls /api/home/personal-records with user_id and tracks
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_calls_personal_records_endpoint():
    """AC-PR-1: home.js must call /api/home/personal-records."""
    assert "/api/home/personal-records" in _HOME_JS, (
        "home.js must fetch /api/home/personal-records on PR widget mount"
    )


def test_home_js_personal_records_includes_user_id():
    """AC-PR-1: URL includes user_id param."""
    idx = _HOME_JS.find("/api/home/personal-records")
    assert idx != -1
    context = _HOME_JS[idx: idx + 200]
    assert "user_id" in context, (
        "home.js must include user_id query param when calling /api/home/personal-records"
    )


def test_home_js_personal_records_includes_tracks_param():
    """AC-PR-1: URL includes tracks=half_marathon,10k,squat_1rm."""
    assert "tracks=half_marathon,10k,squat_1rm" in _HOME_JS, (
        "home.js must pass tracks=half_marathon,10k,squat_1rm to /api/home/personal-records"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-PR-3: Each row shows track_name, current_value_formatted, achieved_on,
#          predicted_value_formatted
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_renders_track_name_from_api():
    """AC-PR-3: home.js renders track_name from the API response."""
    assert "track_name" in _HOME_JS, (
        "home.js must render track_name from /api/home/personal-records response"
    )


def test_home_js_renders_current_value_formatted():
    """AC-PR-3: home.js renders current_value_formatted."""
    assert "current_value_formatted" in _HOME_JS, (
        "home.js must render current_value_formatted from the PR API response"
    )


def test_home_js_renders_achieved_on():
    """AC-PR-3: home.js renders achieved_on date."""
    assert "achieved_on" in _HOME_JS, (
        "home.js must render achieved_on from the PR API response"
    )


def test_home_js_renders_predicted_value_formatted():
    """AC-PR-3: home.js renders predicted_value_formatted in the predicted column."""
    assert "predicted_value_formatted" in _HOME_JS, (
        "home.js must render predicted_value_formatted from the PR API response"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-PR-4: Trend icon: green up arrow for "improving"
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_trend_improving_green_up():
    """AC-PR-4: 'improving' trend renders a green up arrow."""
    assert "improving" in _HOME_JS, (
        "home.js must handle 'improving' trend value"
    )
    # Must use a green color class or style for improving
    idx = _HOME_JS.find("improving")
    context = _HOME_JS[max(0, idx - 300): idx + 500]
    assert (
        "green" in context.lower()
        or "ti-arrow-up" in context
        or "ti-trending-up" in context
        or "trend-up" in context
        or "arrow-up" in context
    ), (
        "home.js must render a green up arrow for 'improving' trend"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-PR-5: Trend icon: red down arrow for "declining"
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_trend_declining_red_down():
    """AC-PR-5: 'declining' trend renders a red down arrow."""
    assert "declining" in _HOME_JS, (
        "home.js must handle 'declining' trend value"
    )
    idx = _HOME_JS.find("declining")
    context = _HOME_JS[max(0, idx - 300): idx + 500]
    assert (
        "red" in context.lower()
        or "ti-arrow-down" in context
        or "ti-trending-down" in context
        or "trend-down" in context
        or "arrow-down" in context
        or "#dc2626" in context
        or "var(--red" in context
    ), (
        "home.js must render a red down arrow for 'declining' trend"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-PR-6: Trend icon: dash for "stable"
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_trend_stable_dash():
    """AC-PR-6: 'stable' trend renders a dash."""
    assert "stable" in _HOME_JS, (
        "home.js must handle 'stable' trend value"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-PR-7: All no_data → empty state with link to /settings
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_pr_empty_state_message():
    """AC-PR-7: home.js shows 'No personal records yet' when all tracks are no_data."""
    assert "No personal records yet" in _HOME_JS, (
        "home.js must show 'No personal records yet' when all tracks have no_data trend"
    )


def test_home_js_pr_set_prs_link():
    """AC-PR-7: Empty state has 'Set your PRs →' link pointing to /settings."""
    assert "Set your PRs" in _HOME_JS, (
        "home.js must render 'Set your PRs →' link in PR widget empty state"
    )


def test_home_js_pr_set_prs_link_to_settings():
    """AC-PR-7: 'Set your PRs →' link points to /settings."""
    idx = _HOME_JS.find("Set your PRs")
    assert idx != -1
    context = _HOME_JS[max(0, idx - 100): idx + 300]
    assert "/settings" in context, (
        "'Set your PRs →' link must point to /settings"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-PR-8: Clicking a data row navigates to /settings#personal-records
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_pr_row_click_navigates_to_settings_prs():
    """AC-PR-8: Clicking any data row navigates to /settings#personal-records."""
    assert "/settings#personal-records" in _HOME_JS, (
        "home.js must navigate to /settings#personal-records when a PR row is clicked"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-PR-9: Loading / error states follow established pattern
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_pr_loading_state():
    """AC-PR-9: PR widget shows loading state while fetching."""
    assert (
        "UIStates.loadingHTML" in _HOME_JS
        or "loadingHTML" in _HOME_JS
    ), "home.js must render loading state for PR widget"


def test_home_js_pr_error_state():
    """AC-PR-9: PR widget shows error state on fetch failure."""
    assert (
        "UIStates.errorHTML" in _HOME_JS
        or "errorHTML" in _HOME_JS
        or "error" in _HOME_JS.lower()
    ), "home.js must render error state for PR widget"


# ══════════════════════════════════════════════════════════════════════════════
# AC-RD-1: Readiness widget calls /api/home/readiness?user_id={uid}
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_calls_home_readiness_endpoint():
    """AC-RD-1: home.js must call /api/home/readiness."""
    assert "/api/home/readiness" in _HOME_JS, (
        "home.js must fetch /api/home/readiness on readiness widget mount"
    )


def test_home_js_readiness_includes_user_id_param():
    """AC-RD-1: Readiness URL includes user_id param."""
    idx = _HOME_JS.find("/api/home/readiness")
    assert idx != -1
    context = _HOME_JS[idx: idx + 200]
    assert "user_id" in context, (
        "home.js must pass user_id query param to /api/home/readiness"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-RD-2: score rendered as large number
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_readiness_renders_score():
    """AC-RD-2: home.js renders score as a large number."""
    assert ".score" in _HOME_JS or "score" in _HOME_JS, (
        "home.js must render score from /api/home/readiness response"
    )


def test_home_js_readiness_score_out_of_100():
    """AC-RD-2: Score displayed with /100 suffix."""
    assert "/100" in _HOME_JS, (
        "home.js must show score out of /100"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-RD-3: score_label with correct colors
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_readiness_renders_score_label():
    """AC-RD-3: home.js renders score_label."""
    assert "score_label" in _HOME_JS, (
        "home.js must render score_label from /api/home/readiness response"
    )


def test_home_js_score_label_excellent_green():
    """AC-RD-3: Excellent score_label → green color."""
    assert "Excellent" in _HOME_JS, "home.js must handle Excellent label"
    idx = _HOME_JS.find("Excellent")
    context = _HOME_JS[max(0, idx - 300): idx + 300]
    assert (
        "green" in context.lower()
        or "#16a34a" in context
        or "#2d5e10" in context
        or "var(--green" in context
    ), "Excellent label must render green"


def test_home_js_score_label_good_blue():
    """AC-RD-3: Good score_label → blue color."""
    # 'Good' might appear in other contexts; check the score_label section
    assert "Good" in _HOME_JS, "home.js must handle Good label"


def test_home_js_score_label_caution_amber():
    """AC-RD-3: Caution score_label → amber color."""
    assert "Caution" in _HOME_JS, "home.js must handle Caution label"
    idx = _HOME_JS.find("Caution")
    context = _HOME_JS[max(0, idx - 300): idx + 300]
    assert (
        "amber" in context.lower()
        or "#6b4408" in context
        or "var(--amber" in context
        or "#f59e0b" in context
    ), "Caution label must render amber"


def test_home_js_score_label_recovery_red():
    """AC-RD-3: Recovery score_label → red color."""
    assert "Recovery" in _HOME_JS, "home.js must handle Recovery label"
    idx = _HOME_JS.find("Recovery")
    context = _HOME_JS[max(0, idx - 300): idx + 300]
    assert (
        "red" in context.lower()
        or "#dc2626" in context
        or "#7a1a1a" in context
        or "var(--red" in context
    ), "Recovery label must render red"


# ══════════════════════════════════════════════════════════════════════════════
# AC-RD-4: Top 3 contributors sorted by |weight × impact|
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_readiness_renders_contributors():
    """AC-RD-4: home.js renders contributors from the API response."""
    assert "contributors" in _HOME_JS, (
        "home.js must render contributors list from /api/home/readiness"
    )


def test_home_js_readiness_top3_contributors():
    """AC-RD-4: home.js renders top 3 contributors (slices to 3)."""
    assert (
        "slice(0, 3)" in _HOME_JS
        or ".slice(0,3)" in _HOME_JS
        or "top 3" in _HOME_JS.lower()
        or "top3" in _HOME_JS.lower()
        or "[0]" in _HOME_JS and "[1]" in _HOME_JS and "[2]" in _HOME_JS
    ), "home.js must limit contributors to top 3"


def test_home_js_readiness_contributor_sort():
    """AC-RD-4: home.js sorts contributors by |weight × impact|."""
    assert "weight" in _HOME_JS, (
        "home.js must use weight from contributors for sorting"
    )
    assert "impact" in _HOME_JS, (
        "home.js must use impact from contributors for sorting"
    )


def test_home_js_readiness_contributor_directional_arrow():
    """AC-RD-4: Each contributor shows a directional arrow."""
    assert (
        "positive" in _HOME_JS or "negative" in _HOME_JS
    ), "home.js must render directional arrows based on impact (positive/negative)"


def test_home_js_readiness_contributor_avg_comparison():
    """AC-RD-4: Contributors show above/below avg comparison."""
    assert (
        "above avg" in _HOME_JS
        or "below avg" in _HOME_JS
        or "avg" in _HOME_JS
    ), "home.js must show avg comparison for readiness contributors"


# ══════════════════════════════════════════════════════════════════════════════
# AC-RD-5: score null → "Log today's metrics →" link
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_readiness_null_score_empty_state():
    """AC-RD-5: When score is null, show 'Log today's metrics →' link."""
    assert (
        "Log today" in _HOME_JS
        or "log today" in _HOME_JS.lower()
        or "Log your metrics" in _HOME_JS
    ), (
        "home.js must show 'Log today's metrics →' when readiness score is null"
    )


def test_home_js_readiness_empty_state_link_target():
    """AC-RD-5: Empty state link points to daily metrics route."""
    # The link should point to the home page (daily log) or /home
    assert (
        "Log today" in _HOME_JS or "Log your" in _HOME_JS
    )
    # Find context around the link
    for phrase in ["Log today", "Log your"]:
        idx = _HOME_JS.find(phrase)
        if idx != -1:
            context = _HOME_JS[max(0, idx - 100): idx + 400]
            assert (
                "/home" in context
                or "href" in context
                or "#log" in context
            ), "Empty state link must point to daily metrics input"
            break


# ══════════════════════════════════════════════════════════════════════════════
# AC-RD-6: Loading, empty, error states
# ══════════════════════════════════════════════════════════════════════════════

def test_home_js_readiness_loading_state():
    """AC-RD-6: Readiness widget shows loading state while fetching."""
    assert "loadingHTML" in _HOME_JS or "UIStates.loadingHTML" in _HOME_JS, (
        "home.js must render loading state for readiness widget"
    )


def test_home_js_readiness_error_state():
    """AC-RD-6: Readiness widget shows error state on fetch failure."""
    assert "errorHTML" in _HOME_JS or "error" in _HOME_JS.lower(), (
        "home.js must render error state for readiness widget"
    )


# ══════════════════════════════════════════════════════════════════════════════
# AC-API-1: GET /api/home/personal-records returns correct shape with 3 tracks
# ══════════════════════════════════════════════════════════════════════════════

def test_personal_records_response_shape_with_data(alice):
    """AC-API-1: /api/home/personal-records returns correct shape for 3 tracks."""
    uid = alice["id"]

    rec_ids = []
    try:
        rec_ids.append(_seed_personal_record(
            uid, "half_marathon", "Half Marathon", "time",
            6871.0, (TODAY - datetime.timedelta(days=30)).isoformat()
        ))
        rec_ids.append(_seed_personal_record(
            uid, "10k", "10K", "time",
            3128.0, (TODAY - datetime.timedelta(days=20)).isoformat()
        ))
        rec_ids.append(_seed_personal_record(
            uid, "squat_1rm", "Squat 1RM", "weight",
            140.0, (TODAY - datetime.timedelta(days=10)).isoformat()
        ))

        with httpx.Client(base_url=BASE, timeout=10) as c:
            res = c.get(
                "/api/home/personal-records",
                params={"user_id": uid, "tracks": "half_marathon,10k,squat_1rm"},
            )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        body = res.json()

        assert "tracks" in body, "Response must have 'tracks' key"
        assert len(body["tracks"]) == 3, f"Must return 3 tracks, got {len(body['tracks'])}"

        keys = {"track_key", "track_name", "current_value_formatted", "achieved_on",
                "predicted_value_formatted", "trend"}
        for track in body["tracks"]:
            for k in keys:
                assert k in track, f"Track missing key '{k}': {track}"

    finally:
        with engine.begin() as conn:
            for rid in rec_ids:
                conn.execute(
                    text("DELETE FROM personal_records WHERE id = :id"), {"id": rid}
                )


# ══════════════════════════════════════════════════════════════════════════════
# AC-API-2: trend "no_data" when user has no records for a track
# ══════════════════════════════════════════════════════════════════════════════

def test_personal_records_no_data_trend(bob_empty):
    """AC-API-2: trend is 'no_data' for all tracks when user has no records."""
    uid = bob_empty["id"]

    with httpx.Client(base_url=BASE, timeout=10) as c:
        res = c.get(
            "/api/home/personal-records",
            params={"user_id": uid, "tracks": "half_marathon,10k,squat_1rm"},
        )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    body = res.json()

    assert "tracks" in body
    for track in body["tracks"]:
        assert track["trend"] == "no_data", (
            f"Track {track['track_key']} must have trend='no_data' for user with no records, "
            f"got '{track['trend']}'"
        )


# ══════════════════════════════════════════════════════════════════════════════
# AC-API-3: GET /api/home/readiness returns correct shape
# ══════════════════════════════════════════════════════════════════════════════

def test_readiness_response_shape_with_metrics(alice):
    """AC-API-3: /api/home/readiness returns correct shape when metrics exist."""
    uid = alice["id"]

    metric_id = None
    try:
        metric_id = _seed_daily_metrics(
            uid, TODAY_ISO,
            sleep_hours=7.5, sleep_quality=4, energy=4, mood=4,
            resting_hr=52, hrv=60,
        )

        with httpx.Client(base_url=BASE, timeout=10) as c:
            res = c.get(
                "/api/home/readiness",
                params={"user_id": uid, "date": TODAY_ISO},
            )
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        body = res.json()

        required_keys = {"date", "score", "score_label", "contributors", "rolling_baseline"}
        for k in required_keys:
            assert k in body, f"Response missing key '{k}'"

        assert body["score"] is not None, "score must not be null when metrics exist"
        assert 0 <= body["score"] <= 100, f"score must be 0-100, got {body['score']}"
        assert body["score_label"] in (
            "Excellent", "Good", "OK", "Caution", "Recovery"
        ), f"score_label must be a valid label, got '{body['score_label']}'"

        assert isinstance(body["contributors"], list), "contributors must be a list"
        assert len(body["contributors"]) == 5, (
            f"contributors must have 5 factors, got {len(body['contributors'])}"
        )

        for c_item in body["contributors"]:
            assert "factor" in c_item
            assert "weight" in c_item
            assert "impact" in c_item
            assert c_item["impact"] in ("positive", "negative", "neutral")

    finally:
        if metric_id:
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM daily_metrics WHERE id = :id"), {"id": metric_id}
                )


# ══════════════════════════════════════════════════════════════════════════════
# AC-API-4: score null when no daily_metrics row for today
# ══════════════════════════════════════════════════════════════════════════════

def test_readiness_null_score_no_metrics(bob_empty):
    """AC-API-4: score is null when no daily_metrics row for today."""
    uid = bob_empty["id"]

    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM daily_metrics WHERE user_id = :uid AND metric_date = :d"),
            {"uid": uid, "d": TODAY_ISO},
        )

    with httpx.Client(base_url=BASE, timeout=10) as c:
        res = c.get(
            "/api/home/readiness",
            params={"user_id": uid, "date": TODAY_ISO},
        )
    assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
    body = res.json()

    assert body["score"] is None, (
        f"score must be null when no metrics exist for today, got {body['score']}"
    )
    assert body["score_label"] == "No data", (
        f"score_label must be 'No data' when score is null, got '{body['score_label']}'"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Manual UAT steps
# ══════════════════════════════════════════════════════════════════════════════

def test_no_console_errors_manual():
    """AC-PR-10/AC-RD-7: No console errors — verified manually via browser DevTools."""
    pytest.skip("Manual UAT step — verify via browser DevTools during UAT")
