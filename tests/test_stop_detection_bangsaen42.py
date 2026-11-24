"""Stop detection / sensor glitch / race result on a Bangsaen42-shaped fixture (#1876).

Engineered fixture (real lap export unavailable): 42 x 1 km laps + a 0.195 km
tail, median moving lap 460 s (7:40/km). Lap 8 is a toilet stop (+330 s elapsed),
lap 29 is a stop with a cadence glitch (moving 560 s/km, 220 spm, +262 s elapsed).
"""
from backend.services.stop_detection import (
    detect_stops_and_glitches,
    laps_from_strava,
    race_result_time,
)


def _lap(moving=460, elapsed=None, dist=1.0, hr=150, cad=170):
    return {
        "moving_time_seconds": moving,
        "elapsed_time_seconds": elapsed if elapsed is not None else moving,
        "distance_km": dist,
        "avg_hr": hr,
        "cadence_spm": cad,
    }


def _bangsaen42():
    laps = [_lap(moving=460 + (i % 3 - 1) * 4 if i % 5 else 460) for i in range(42)]
    laps.append(_lap(moving=90, dist=0.195))
    laps[7] = _lap(moving=460, elapsed=790)  # lap 8: 330 s stop
    laps[28] = _lap(moving=560, elapsed=822, cad=220)  # lap 29: 362 s excess + glitch
    return laps


def test_laps_8_and_29_are_stops_with_about_11_minutes_stopped():
    res = detect_stops_and_glitches(_bangsaen42())
    assert res["stop_laps"] == [8, 29]
    assert res["stopped_time_seconds"] == 330 + 362
    assert 10 * 60 <= res["stopped_time_seconds"] <= 12 * 60


def test_lap_29_cadence_flagged_as_glitch():
    res = detect_stops_and_glitches(_bangsaen42())
    assert res["glitch_laps"] == [29]
    assert res["laps"][28]["glitch_reasons"] == ["cadence"]
    assert res["laps"][28]["sensor_glitch"] is True


def test_slow_pace_alone_is_a_stop_lap():
    laps = [_lap() for _ in range(10)]
    laps[4] = _lap(moving=800)  # > 1.6 x 460 = 736, no elapsed gap
    res = detect_stops_and_glitches(laps)
    assert res["stop_laps"] == [5]
    assert res["stopped_time_seconds"] == 340


def test_hr_spike_from_both_neighbours_is_glitch_but_step_is_not():
    spike = [_lap(hr=h) for h in (140, 141, 170, 142, 143)]
    assert detect_stops_and_glitches(spike)["glitch_laps"] == [3]
    step = [_lap(hr=h) for h in (120, 140, 160, 161, 162)]
    assert detect_stops_and_glitches(step)["glitch_laps"] == []


def test_fast_cadence_at_normal_pace_is_not_glitch():
    laps = [_lap() for _ in range(5)]
    laps[2] = _lap(cad=210)
    assert detect_stops_and_glitches(laps)["glitch_laps"] == []


def test_empty_laps():
    assert detect_stops_and_glitches([])["stopped_time_seconds"] == 0


def test_race_result_prefers_chip_then_elapsed_never_moving():
    r = race_result_time(20400, 20464, 19772)
    assert (r["result_seconds"], r["result_source"], r["moving_time_seconds"]) == (20400, "chip", 19772)
    r = race_result_time(None, 20464, 19772)
    assert (r["result_seconds"], r["result_source"]) == (20464, "elapsed")
    r = race_result_time(None, None, 19772)
    assert r["result_seconds"] is None and r["moving_time_seconds"] == 19772


def test_laps_from_strava_converts_units():
    laps = laps_from_strava([
        {"moving_time": 460, "elapsed_time": 790, "distance": 1000.0, "average_cadence": 110.0, "average_heartrate": 150.4},
    ])
    assert laps == [{
        "moving_time_seconds": 460, "elapsed_time_seconds": 790, "distance_km": 1.0,
        "cadence_spm": 220, "avg_hr": 150,
    }]
