"""Sprint 149 #1952 — honest estimate colour, status chips, completed limit."""
from datetime import date
from pathlib import Path
from unittest.mock import patch

from backend.services import race_list as rl
from tests.test_race_list__1858 import TODAY, UID, fake_session, race


def test_upcoming_status_chip_faster_and_slower():
    slow = race(name="Half", race_date=date(2026, 12, 20), distance_km=21.0975,
                goal_time_seconds=6600, priority="B", role="pb")
    fast = race(name="Park", race_date=date(2026, 11, 30), distance_km=5.0,
                goal_time_seconds=1500, priority="C", role="fun")
    with patch.object(rl, "estimate_race_finish", side_effect=[
            {"unavailable": False, "est_sec": 6782, "band_sec": 176},
            {"unavailable": False, "est_sec": 1400, "band_sec": 30},
        ]), patch("backend.services.score_reader.get_race_scores", return_value={}):
        srow = rl.upcoming_row(None, UID, slow, TODAY, None)
        frow = rl.upcoming_row(None, UID, fast, TODAY, None)
    assert srow["estimate_vs_goal"] == "slower"
    assert srow["status_chip"]["tone"] == "bad"
    assert srow["status_chip"]["text"] == "+3:02"
    assert srow["status_chip"]["title"] == "3:02 slower than goal"
    assert srow["status_chip"]["aria_label"] == "3:02 slower than goal"
    assert frow["estimate_vs_goal"] == "faster"
    assert frow["status_chip"]["tone"] == "good"
    assert frow["status_chip"]["text"] == "\u22121:40"
    assert "faster than goal" in frow["status_chip"]["title"]


def test_completed_over_and_under_goal():
    over = race(status="done", actual_time_seconds=19772, goal_time_seconds=16200,
                distance_km=42.195, role="pb")
    under = race(status="done", actual_time_seconds=3190, goal_time_seconds=3240,
                 distance_km=10.0, role="pb")
    o = rl.completed_row(over, [])
    u = rl.completed_row(under, [])
    assert o["status_chip"]["tone"] == "bad" and o["status_chip"]["text"] == "+59:32"
    assert "over goal" in o["status_chip"]["title"]
    assert u["status_chip"]["tone"] == "good" and u["status_chip"]["text"] == "\u22120:50"
    assert "under goal" in u["status_chip"]["title"]


def test_unrecorded_checkpoint_chip_and_goal_pace_uses_exact_distance():
    cp = race(name="Checkpoint", race_date=date(2026, 11, 7), distance_km=18.0,
              goal_time_seconds=5400, role="long_run", race_type="checkpoint",
              goal_pace_seconds_per_km=999)
    row = rl.needs_result_row(cp, [])
    assert row["status_chip"]["text"] == "not recorded"
    half = race(distance_km=21.0975, goal_time_seconds=6600, goal_pace_seconds_per_km=1)
    pace = rl._base(half)["goal_pace_seconds_per_km"]
    assert pace == 313  # 1:50:00 / 21.0975 km → 5:13 /km
    assert rl._base(half)["distance_label"] == "21.1"
    assert rl.format_distance_km(42.195) == "42.2"
    assert rl.format_distance_km(18.0) == "18"
    stored_half = race(distance_km=21.0, goal_time_seconds=6600, goal_pace_seconds_per_km=1)
    assert rl._base(stored_half)["goal_pace_seconds_per_km"] == 313
    assert rl._base(stored_half)["distance_label"] == "21.1"


def test_completed_shows_latest_only_until_show_all():
    rows = [
        race(name=f"C{i}", race_date=date(2026, 9, i + 1), status="done",
             actual_time_seconds=3600, goal_time_seconds=3500, role="fun")
        for i in range(3)
    ]
    db = fake_session(rows, [])
    with patch.object(rl, "next_a_race", return_value=None):
        clipped = rl.build_race_list(db, UID, TODAY)
        full = rl.build_race_list(db, UID, TODAY, show_all=True)
    assert clipped["total_completed"] == 3 and len(clipped["completed"]) == 1
    assert clipped["hidden_completed"] == 2
    assert clipped["completed"][0]["name"] == "C2"
    assert full["hidden_completed"] == 0 and len(full["completed"]) == 3


def test_race_rows_have_no_end_spd_pills():
    js = Path("frontend/js/v2-performance.js").read_text()
    assert "function scorePill" not in js
    assert "scorePill(\"End\"" not in js
    assert "data-status-chip" in js
    assert "rv-race-time--warn" in js
    assert "data-edit-race" in js and "data-delete-race" in js
    assert '"DELETE", "/api/races/"' in js
    assert "e.status === 404" in js
    assert "data-actual-pace" in js
    assert "fmtDayMonth" in js
