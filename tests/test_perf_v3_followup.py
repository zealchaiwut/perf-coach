"""Performance v3 follow-ups: estimate history, radar tag, work-on, C badge."""
from __future__ import annotations

import uuid
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from backend.services import projection_view as pv
from backend.services import race_calibration as rc
from backend.services import race_roles as rr
from backend.services import radar_svg as rs
from backend.services.season_road import _status_chip

JS = Path("frontend/js/v2-performance.js").read_text(encoding="utf-8")
COMMON = Path("frontend/js/lib/app-common.js").read_text(encoding="utf-8")
SR_JS = Path("frontend/js/v2-season-road.js").read_text(encoding="utf-8")
FIX = Path("tests/fixtures")
TODAY = date(2026, 11, 24)
UID = uuid.uuid4()
RACE_ID = uuid.uuid4()


def _race(**kw):
    base = dict(
        id=RACE_ID,
        name="Osaka",
        race_date=date(2027, 2, 28),
        distance_km=42.195,
        goal_time_seconds=16200,
        goal_band_low_seconds=None,
        goal_band_high_seconds=None,
        priority="A",
        role="a_race",
        race_type="race",
        status="planned",
        actual_time_seconds=None,
        power_cap_w=None,
        addon_distance_km=None,
        addon_workout_id=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_est_on_day_never_falls_back_to_today():
    hist = {TODAY.isoformat(): 16133, "2026-11-20": 16500}
    assert pv._est_on_day(hist, "2026-11-20") == 16500
    assert pv._est_on_day(hist, "2026-11-22") == 16500  # within 3 days
    assert pv._est_on_day(hist, "2026-10-25") is None
    assert pv._est_on_day(hist, "2026-09-01") is None


def test_build_chart_gap_skips_missing_history():
    race = _race()
    est = {"unavailable": False, "est_sec": 16133, "band_sec": 790}
    ch = pv.build_chart(
        start=date(2026, 9, 1),
        today=TODAY,
        race=race,
        est=est,
        goal_sec=16200,
        history=[(TODAY, 16133)],
        recalibrations=[{
            "date": date(2026, 11, 15), "race_id": "r1", "name": "Bangsaen42", "role": "a_race",
            "converted_sec": 19772, "actual_sec": 19772, "distance_km": 42.2,
            "distance_label": "42.2K", "date_label": "15 Nov",
        }],
        ticks=[],
        pending=[],
    )
    bang = ch["recalibrations"][0]
    assert bang["est_on_day_sec"] is None
    assert bang.get("gap_sec") is None


def test_dist_tag_has_no_cp_suffix_for_long_run():
    assert "CP" not in pv._dist_tag(21.1, "long_run")
    assert pv._dist_tag(42.195) == "42.2K"


def test_backfill_sixty_day_snapshots_not_flat():
    race = _race()
    start = TODAY - timedelta(days=59)
    recorded = []

    def fake_est(db, user_id, r, as_of):
        return {
            "unavailable": False,
            "est_sec": 15000 + (TODAY - as_of).days,
            "band_sec": 400,
        }

    def fake_snap(db, user_id, d, **kw):
        skip = {start + timedelta(days=i) for i in (2, 11, 19, 33, 48)}
        return object() if d not in skip else None

    def fake_record(user_id, race_id, seconds, band, db, prediction_date=None):
        recorded.append((prediction_date, seconds, band))

    session = MagicMock()
    race_q = MagicMock()
    race_q.filter.return_value = race_q
    race_q.all.return_value = [race]
    pred_q = MagicMock()
    pred_q.filter.return_value = pred_q
    pred_q.all.return_value = []
    pred_q.count.return_value = 0
    pred_q.delete.return_value = 0

    def query_side(model):
        from backend.models import Race, RacePrediction
        if model is Race:
            return race_q
        if model is RacePrediction or model is RacePrediction.prediction_date:
            return pred_q
        q = MagicMock()
        q.filter.return_value = q
        q.all.return_value = []
        q.count.return_value = 0
        return q

    session.query.side_effect = query_side
    with patch("backend.services.race_finish_estimate.estimate_on", side_effect=fake_est), \
            patch("backend.services.axis_snapshot.snapshot_row_on_or_before", side_effect=fake_snap), \
            patch.object(rc, "record_prediction", side_effect=fake_record), \
            patch("backend.services.projection_view._chart_window_start", return_value=start):
        n = rc.backfill_race_prediction_history(session, UID, TODAY, race_id=race.id)
    assert n >= 55
    assert len(recorded) >= 55
    secs = [s for _, s, _ in recorded]
    assert len(set(secs)) > 1
    today_rows = [s for d, s, _ in recorded if d == TODAY]
    assert today_rows
    live = fake_est(None, UID, race, TODAY)
    assert abs(today_rows[0] - live["est_sec"]) <= 1
    assert all(b == 400 for _, _, b in recorded)


def test_estimate_on_matches_compute():
    src = Path("backend/services/race_finish_estimate.py").read_text(encoding="utf-8")
    assert "def estimate_on(" in src
    assert "record_todays_predictions" in Path("backend/services/race_calibration.py").read_text()
    cal = Path("backend/services/race_calibration.py").read_text(encoding="utf-8")
    assert "estimate_on" in cal
    assert "ensure_prediction_history" in cal
    assert "force_from" in cal


def test_js_no_flat_history_line_and_caption():
    assert 'svgLine(PX_L, yNow, nowX, yNow' not in JS
    assert 'data-chart="history-caption"' in JS
    assert "History builds from today" in JS
    assert "rawHist.length < 2" in JS
    assert "m.est_on_day_sec != null ? m.est_on_day_sec : estAtX" not in JS


def test_js_c_priority_long_run_is_letter_c():
    assert "function raceBadgeKind" in COMMON
    assert 'r.race_type === "checkpoint"' in COMMON
    assert "role === \"long_run\"" not in COMMON.split("function raceBadgeKind")[1].split("function ")[0]
    assert "racePriorityBadge" in JS
    assert "racePriorityBadge" in SR_JS


def _flagged(axes, weights):
    out = [a for a in axes if a.get("never_measured") or a.get("stale")]
    out.sort(key=lambda a: (
        -weights.get(a["axis"], 0),
        0 if a.get("stale") and not a.get("never_measured") else 1,
    ))
    return out


def test_js_work_on_card_counts():
    assert "function flaggedWorkOnAxes" in JS
    assert "data-work-on-empty" in JS
    assert "All 7 axes are measured and fresh" in JS
    assert "data-work-on-focus" in JS
    assert "data-work-on-row" in JS
    assert "data-flagged-count" in JS
    weights = {
        "durability": 0.25, "economy": 0.20, "endurance": 0.20,
        "power_to_weight": 0.15, "strength": 0.10, "speed": 0.05, "mobility": 0.05,
    }
    none = [
        {"axis": "economy", "stale": False, "never_measured": False},
        {"axis": "endurance", "stale": False, "never_measured": False},
    ]
    one = none + [{"axis": "power_to_weight", "stale": True, "never_measured": False}]
    three = one + [
        {"axis": "durability", "stale": False, "never_measured": True},
        {"axis": "strength", "stale": True, "never_measured": False},
    ]
    six = three + [
        {"axis": "mobility", "stale": False, "never_measured": True},
        {"axis": "speed", "stale": True, "never_measured": False},
        {"axis": "endurance", "stale": True, "never_measured": False},
    ]
    assert len(_flagged(none, weights)) == 0
    assert len(_flagged(one, weights)) == 1
    assert len(_flagged(three, weights)) == 3
    assert len(_flagged(six, weights)) == 6
    assert _flagged(six, weights)[0]["axis"] == "durability"


def test_role_result_a_race_goal_time_only():
    r = _race(actual_time_seconds=19772, goal_time_seconds=16200)
    out = rr.compute_role_result(r)
    assert out["status"] == "slow"
    assert "unknown" not in out["status"]


def test_role_target_summary_has_no_target_prefix():
    r = _race()
    s = rr.role_target_summary(r)
    assert not s.startswith("Target:")
    assert "4:30:00" in s


def test_status_chip_upcoming_completed_needs_result():
    upcoming = _race(race_date=TODAY + timedelta(days=19))
    chip = _status_chip(upcoming, TODAY, None, None, 16200)
    assert chip["tone"] == "neutral"
    assert "19" in chip["text"]
    assert "unknown" not in chip["text"]

    done = _race(race_date=date(2026, 11, 15), actual_time_seconds=19772, goal_time_seconds=16200, status="done")
    chip = _status_chip(done, TODAY, None, 19772, 16200)
    assert chip["tone"] == "bad"
    assert chip["text"].startswith("+")

    past = _race(race_date=date(2026, 11, 10), actual_time_seconds=None)
    chip = _status_chip(past, TODAY, None, None, 16200)
    assert chip["tone"] == "warn"
    assert "needs a result" in chip["text"]

    long_ok = _race(role="long_run", race_date=date(2026, 11, 8), actual_time_seconds=None)
    chip = _status_chip(long_ok, TODAY, {"status": "pass"}, None, None)
    assert chip["tone"] == "good"


def test_radar_selected_fixtures():
    payload = __import__("json").loads((FIX / "radar_payload__1853.json").read_text())
    measured = rs.render_radar_svg(payload, "large", selected_axis="economy")
    unmeasured = rs.render_radar_svg(payload, "large", selected_axis="mobility")
    assert measured == (FIX / "radar_large__selected_economy.svg").read_text()
    assert unmeasured == (FIX / "radar_large__selected_mobility.svg").read_text()
    assert "perf-radar-label-tag" in measured
    assert "perf-radar-spoke--selected" in measured
    assert "perf-radar-halo" in measured
    assert "perf-radar-spoke--selected" not in unmeasured
    assert "not measured" in unmeasured
    assert "Log a test" not in unmeasured
