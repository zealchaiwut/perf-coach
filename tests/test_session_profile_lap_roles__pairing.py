"""Tests for the per-lap interval role map (lap_roles) on detected_profile.

Surfaces the existing detect_intervals/detect_sets output as a per-lap
work/recovery pairing map (Set 1..N) plus reps_per_set, so the run-detail lap
view can number pairs (e.g. 8×400m → 8 numbered work+rest pairs).
"""
import types

from backend.services.session_profile import detect_session_profile


_PREFS = {"ftp_w": 279, "threshold_hr": 170, "threshold_pace_seconds_per_km": 330}


def _ns(**kw):
    return types.SimpleNamespace(**kw)


def _eight_x_400():
    """warm-up + 8 hard reps (each followed by a recovery) + cool-down."""
    laps = [_ns(avg_power=150, duration_seconds=600, distance_km=2.0, avg_hr=130, lap_type="manual")]
    for _ in range(8):
        laps.append(_ns(avg_power=280, duration_seconds=90, distance_km=0.4, avg_hr=175, lap_type="manual"))
        laps.append(_ns(avg_power=140, duration_seconds=60, distance_km=0.15, avg_hr=140, lap_type="manual"))
    laps.append(_ns(avg_power=145, duration_seconds=500, distance_km=1.6, avg_hr=128, lap_type="manual"))
    return types.SimpleNamespace(laps=laps, lap_type="manual")


def test_lap_roles_present_and_pairs_work_recovery():
    r = detect_session_profile(_eight_x_400(), _PREFS)
    assert r["confident"] is True
    assert r["reps_detected"] == 8
    assert r["reps_per_set"] == [8]
    lr = r["lap_roles"]
    assert lr is not None

    work = {k: v for k, v in lr.items() if v["role"] == "work"}
    rec = {k: v for k, v in lr.items() if v["role"] == "recovery"}
    assert len(work) == 8
    assert len(rec) == 8

    # Rep numbers run 1..8 across the block.
    rep_numbers = sorted(v["rep"] for v in work.values())
    assert rep_numbers == list(range(1, 9))

    # Every rep is set 1 (single set), and each recovery pairs to a work rep's
    # (set, rep). Work lap idx k → recovery at idx k+1 with the same rep.
    for k, v in work.items():
        assert v["set"] == 1
        rec_key = str(int(k) + 1)
        assert lr.get(rec_key, {}).get("role") == "recovery"
        assert lr[rec_key]["rep"] == v["rep"]
        assert lr[rec_key]["set"] == v["set"]


def test_lap_roles_excludes_warmup_cooldown():
    r = detect_session_profile(_eight_x_400(), _PREFS)
    lr = r["lap_roles"]
    # warm-up is index 0, cool-down is the last index (17) — neither annotated.
    assert "0" not in lr
    assert "17" not in lr


def test_lap_roles_multi_set_numbering():
    """Two sets of 4×400 with a long recovery between: reps 1–4 → set 1, 5–8 → set 2."""
    laps = []
    for s in range(2):
        for i in range(4):
            laps.append(_ns(avg_power=280, duration_seconds=90, distance_km=0.4, avg_hr=175, lap_type="manual"))
            rec = 300 if (s == 0 and i == 3) else 60  # long recovery ends set 1
            laps.append(_ns(avg_power=140, duration_seconds=rec, distance_km=0.15, avg_hr=140, lap_type="manual"))
    r = detect_session_profile(types.SimpleNamespace(laps=laps, lap_type="manual"), _PREFS)
    assert r["reps_per_set"] == [4, 4]
    assert r["sets_detected"] == 2
    lr = r["lap_roles"]
    work = sorted(((int(k), v) for k, v in lr.items() if v["role"] == "work"))
    sets = [v["set"] for _, v in work]
    assert sets == [1, 1, 1, 1, 2, 2, 2, 2]


def test_non_interval_run_has_no_lap_roles():
    """A steady auto-split run degrades: no lap_roles, not confident."""
    laps = [_ns(avg_power=150, duration_seconds=360, distance_km=1.0, avg_hr=135, lap_type="auto_1km")
            for _ in range(6)]
    r = detect_session_profile(types.SimpleNamespace(laps=laps, lap_type="auto_1km"), _PREFS)
    assert r["confident"] is False
    assert r.get("lap_roles") is None


def test_lap_roles_keys_are_string_indexes():
    r = detect_session_profile(_eight_x_400(), _PREFS)
    for k in r["lap_roles"]:
        assert isinstance(k, str)
        int(k)  # parses as an int index
