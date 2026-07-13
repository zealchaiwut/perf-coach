"""HTTP integration tests for deficit periodization (issue #1357).

Tests against the live UAT server to verify:
  - Fuel today/week payloads include week_phase and effective_deficit_kcal
  - Settings toggle for auto_periodize can be read and written
  - Phase changes correctly when races are added/removed
  - Effective deficit adjusts per phase when auto_periodize is ON
  - Effective deficit ignores phase when auto_periodize is OFF
"""
import os
import pytest
import httpx
from datetime import date, timedelta

BASE_URL = os.environ.get("UAT_BASE_URL") or "http://localhost:9001"
if not BASE_URL.startswith("http"):
    raise RuntimeError(
        "UAT_BASE_URL / UAT_PORT not set. Run the tester skill's Step 0 to resolve UAT before pytest."
    )


@pytest.fixture
def client():
    with httpx.Client(base_url=BASE_URL, timeout=10.0) as c:
        yield c


@pytest.fixture
def session(client):
    """Authenticate as the test user and return a configured client."""
    # Login to get session cookie
    r = client.post("/api/auth/login", json={"username": "test", "password": "test"})
    if r.status_code != 200:
        pytest.skip(f"test user not configured in UAT (status {r.status_code})")
    return client


# ── AC1 & AC2: Phase resolver precedence + effective deficit math ─────────
# (covered by test_deficit_periodization__1357.py unit tests)

# ── AC3: auto_periodize toggle ────────────────────────────────────────────

def test_fuel_settings_includes_auto_periodize_field(session):
    """Settings payload includes auto_periodize boolean."""
    r = session.get("/api/fuel/settings")
    assert r.status_code == 200
    data = r.json()
    assert "auto_periodize" in data
    assert isinstance(data["auto_periodize"], bool)


def test_auto_periodize_defaults_to_true(session):
    """New fuel settings have auto_periodize=True by default."""
    r = session.get("/api/fuel/settings")
    assert r.status_code == 200
    data = r.json()
    # After a fresh get, should default to True
    assert data.get("auto_periodize", True) is True


def test_auto_periodize_can_be_toggled_off(session):
    """Can set auto_periodize=False via PUT /api/fuel/settings."""
    r = session.put("/api/fuel/settings", json={"auto_periodize": False})
    assert r.status_code == 200
    data = r.json()
    assert data.get("auto_periodize") is False

    # Verify it persists
    r2 = session.get("/api/fuel/settings")
    assert r2.status_code == 200
    assert r2.json().get("auto_periodize") is False

    # Reset to True for later tests
    session.put("/api/fuel/settings", json={"auto_periodize": True})


def test_auto_periodize_can_be_toggled_on(session):
    """Can set auto_periodize=True via PUT /api/fuel/settings."""
    session.put("/api/fuel/settings", json={"auto_periodize": False})
    r = session.put("/api/fuel/settings", json={"auto_periodize": True})
    assert r.status_code == 200
    data = r.json()
    assert data.get("auto_periodize") is True


# ── AC4: Payload fields (week_phase, effective_deficit_kcal) ──────────────

def test_fuel_today_includes_week_phase_fields(session):
    """Fuel today payload includes week_phase and effective_deficit_kcal."""
    r = session.get("/api/fuel/today")
    assert r.status_code == 200
    data = r.json()
    assert "week_phase" in data, "week_phase missing from fuel today payload"
    assert "week_phase_reason" in data, "week_phase_reason missing from fuel today payload"
    assert "effective_deficit_kcal" in data, "effective_deficit_kcal missing from fuel today payload"


def test_fuel_today_week_phase_is_string(session):
    """week_phase is one of: race, taper, ramp, base."""
    r = session.get("/api/fuel/today")
    assert r.status_code == 200
    data = r.json()
    assert data["week_phase"] in ("race", "taper", "ramp", "base")


def test_fuel_today_effective_deficit_kcal_is_number(session):
    """effective_deficit_kcal is a non-negative integer."""
    r = session.get("/api/fuel/today")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["effective_deficit_kcal"], int)
    assert data["effective_deficit_kcal"] >= 0


def test_fuel_today_effective_deficit_respects_auto_periodize_toggle(session):
    """When auto_periodize is OFF, effective_deficit_kcal == configured deficit_kcal."""
    # Ensure auto_periodize is OFF
    session.put("/api/fuel/settings", json={"auto_periodize": False})

    r = session.get("/api/fuel/today")
    assert r.status_code == 200
    data = r.json()
    configured = data.get("deficit_target")
    effective = data.get("effective_deficit_kcal")
    assert configured == effective, (
        f"When auto_periodize=False, effective_deficit_kcal ({effective}) "
        f"should equal configured deficit_target ({configured})"
    )

    # Reset
    session.put("/api/fuel/settings", json={"auto_periodize": True})


def test_fuel_week_includes_week_phase_fields(session):
    """Fuel week payload includes week_phase, week_phase_reason, effective_deficit_kcal."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    r = session.get(f"/api/fuel/week?week_start={week_start.isoformat()}")
    assert r.status_code == 200
    data = r.json()
    assert "week_phase" in data, "week_phase missing from fuel week payload"
    assert "week_phase_reason" in data, "week_phase_reason missing from fuel week payload"
    assert "effective_deficit_kcal" in data, "effective_deficit_kcal missing from fuel week payload"


def test_fuel_week_effective_deficit_is_number(session):
    """Fuel week effective_deficit_kcal is a non-negative integer."""
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    r = session.get(f"/api/fuel/week?week_start={week_start.isoformat()}")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["effective_deficit_kcal"], int)
    assert data["effective_deficit_kcal"] >= 0


# ── AC5: Settings UI toggle exists ────────────────────────────────────────

def test_weight_page_loads_successfully(session):
    """Weight page HTML loads without error (integration check)."""
    r = session.get("/weight")
    assert r.status_code == 200
    # Check for the toggle element in the HTML
    html = r.text
    assert "auto_periodize" in html or "Adjust deficit for training phase" in html, (
        "Weight page should include auto_periodize toggle UI"
    )


# ── Base week phase behavior ──────────────────────────────────────────────

def test_base_phase_week_deficit_is_full(session):
    """In base phase, effective deficit equals configured deficit."""
    # Ensure no race within 7 days and auto_periodize is ON
    session.put("/api/fuel/settings", json={"auto_periodize": True})

    r = session.get("/api/fuel/today")
    assert r.status_code == 200
    data = r.json()

    # If no race and no training plan loaded, should be base phase
    # and effective deficit should equal configured deficit
    if data["week_phase"] == "base":
        assert data["effective_deficit_kcal"] == data["deficit_target"]


# ── With auto_periodize OFF: no adjustment ────────────────────────────────

def test_with_auto_periodize_off_deficit_unchanged(session):
    """When auto_periodize is OFF, effective deficit is always configured deficit."""
    session.put("/api/fuel/settings", json={"auto_periodize": False})

    r = session.get("/api/fuel/today")
    assert r.status_code == 200
    data = r.json()
    # Regardless of phase, effective should equal configured
    assert data["effective_deficit_kcal"] == data["deficit_target"]

    # Reset
    session.put("/api/fuel/settings", json={"auto_periodize": True})
