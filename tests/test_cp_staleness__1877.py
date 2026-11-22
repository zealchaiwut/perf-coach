"""CP staleness check and confirmed update flow (#1877)."""
from datetime import date, datetime, timezone

from backend.services import cp_staleness as cs

TODAY = date(2026, 11, 22)
FRESH_UPDATE = datetime(2026, 11, 10, tzinfo=timezone.utc)


def _half_marathon():
    # Nov 1 half marathon: 285 W for 2:07:30
    return {"workout_id": "w1", "name": "Half", "date": date(2026, 11, 1),
            "avg_power_w": 285, "duration_seconds": 2 * 3600 + 7 * 60 + 30}


def test_nov1_half_flags_stale_and_suggests_306():
    res = cs.evaluate_cp_staleness([_half_marathon()], 280, FRESH_UPDATE, TODAY)
    assert res["stale"] is True
    assert "recent_effort_above_cp" in res["reasons"]
    assert res["suggested_cp_w"] == 306  # 285 / 0.93
    assert res["suggestion_basis"]["workout_id"] == "w1"
    assert res["never_auto_updated"] is True


def test_long_effort_below_95pct_is_fresh():
    run = {"date": date(2026, 11, 1), "avg_power_w": 260, "duration_seconds": 7200}  # 0.93 x 280
    res = cs.evaluate_cp_staleness([run], 280, FRESH_UPDATE, TODAY)
    assert res["stale"] is False and res["status"] == "fresh"
    assert res["suggested_cp_w"] is None


def test_short_effort_105pct_for_20min_flags_and_suggests_avg_power():
    run = {"date": date(2026, 11, 15), "avg_power_w": 295, "duration_seconds": 25 * 60}  # >= 294
    res = cs.evaluate_cp_staleness([run], 280, FRESH_UPDATE, TODAY)
    assert res["stale"] is True
    assert res["suggested_cp_w"] == 295


def test_short_effort_too_short_or_too_weak_ignored():
    runs = [
        {"date": date(2026, 11, 15), "avg_power_w": 320, "duration_seconds": 19 * 60},
        {"date": date(2026, 11, 15), "avg_power_w": 293, "duration_seconds": 30 * 60},
    ]
    assert cs.evaluate_cp_staleness(runs, 280, FRESH_UPDATE, TODAY)["stale"] is False


def test_runs_older_than_six_weeks_ignored():
    run = dict(_half_marathon(), date=date(2026, 10, 1))
    assert cs.evaluate_cp_staleness([run], 280, FRESH_UPDATE, TODAY)["stale"] is False


def test_age_rule_stale_without_suggestion():
    old = datetime(2026, 9, 1, tzinfo=timezone.utc)
    res = cs.evaluate_cp_staleness([], 280, old, TODAY)
    assert res["stale"] is True
    assert res["reasons"] == ["cp_not_updated_6_weeks"]
    assert res["suggested_cp_w"] is None


def test_unknown_update_date_counts_as_stale():
    assert cs.evaluate_cp_staleness([], 280, None, TODAY)["stale"] is True


def test_no_cp_on_file():
    res = cs.evaluate_cp_staleness([_half_marathon()], None, None, TODAY, stryd_cp_w=300)
    assert res["status"] == "no_cp" and res["stale"] is False and res["stryd_cp_w"] == 300


def test_stryd_cp_returned_next_to_suggestion():
    res = cs.evaluate_cp_staleness([_half_marathon()], 280, FRESH_UPDATE, TODAY, stryd_cp_w=298)
    assert res["suggested_cp_w"] == 306 and res["stryd_cp_w"] == 298


def test_over_150_min_flags_but_does_not_suggest():
    run = {"date": date(2026, 11, 1), "avg_power_w": 270, "duration_seconds": 4 * 3600}
    res = cs.evaluate_cp_staleness([run], 280, FRESH_UPDATE, TODAY)
    assert res["stale"] is True and res["suggested_cp_w"] is None


def test_highest_candidate_wins():
    runs = [_half_marathon(), {"date": date(2026, 11, 15), "avg_power_w": 300, "duration_seconds": 25 * 60}]
    assert cs.evaluate_cp_staleness(runs, 280, FRESH_UPDATE, TODAY)["suggested_cp_w"] == 306


def test_validate_cp():
    assert cs.validate_cp(306) is None
    for bad in (49, 601, "300", 300.5, True, None):
        assert cs.validate_cp(bad)


class _FakePrefs:
    ftp_w = 280
    ftp_w_source = None
    ftp_w_updated_at = None


class _FakeQuery:
    def __init__(self, prefs):
        self._prefs = prefs

    def filter(self, *a, **k):
        return self

    def first(self):
        return self._prefs


class _FakeSession:
    def __init__(self):
        self.prefs = _FakePrefs()
        self.added = []

    def query(self, _model):
        return _FakeQuery(self.prefs)

    def add(self, obj):
        self.added.append(obj)


def test_apply_update_writes_prefs_and_history_row():
    s = _FakeSession()
    out = cs.apply_cp_update(s, "u1", 306, "suggested", TODAY)
    assert (s.prefs.ftp_w, s.prefs.ftp_w_source) == (306, "suggested")
    assert s.prefs.ftp_w_updated_at is not None
    hist = [o for o in s.added if type(o).__name__ == "CpHistory"]
    assert len(hist) == 1
    assert (hist[0].cp_w, hist[0].previous_cp_w, hist[0].effective_date) == (306, 280, TODAY)
    assert out["previous_cp_w"] == 280


def test_staleness_is_read_only_never_mutates_cp(monkeypatch):
    s = _FakeSession()
    s.query = lambda _m: _FakeQuery(None)  # no workouts / prefs
    # get_cp_status must not call add()
    monkeypatch.setattr(cs, "load_recent_runs", lambda *_a, **_k: [_half_marathon()])
    monkeypatch.setattr(cs, "latest_stryd_cp", lambda *_a, **_k: None)
    out = cs.get_cp_status(s, "u1", TODAY)
    assert out["status"] == "no_cp" and s.added == []


def test_routes_registered_and_scores_read_current_cp():
    from backend.main import app

    paths = {(m, r.path) for r in app.routes for m in getattr(r, "methods", ())}
    assert ("GET", "/api/cp/staleness") in paths
    assert ("GET", "/api/cp/history") in paths
    assert ("POST", "/api/cp/update") in paths
    # Scores keep reading CP from user_preferences.ftp_w.
    import inspect

    from backend.services import tss

    assert "ftp_w" in inspect.getsource(tss.get_user_thresholds)
