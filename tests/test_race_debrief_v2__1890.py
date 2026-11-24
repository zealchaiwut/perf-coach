"""P6-16 (#1890) — race-debrief prompt v2."""
from backend.services.session_consult import PROMPT_VERSION_RACE
from tests.test_stop_detection_bangsaen42 import _bangsaen42
from backend.services.stop_detection import detect_stops_and_glitches


def test_prompt_version_is_v2():
    assert PROMPT_VERSION_RACE == "race-debrief-v2"


def test_bangsaen_fixture_two_stop_laps_for_prompt():
    res = detect_stops_and_glitches(_bangsaen42())
    assert res["stop_laps"] == [8, 29]
    assert res["stopped_time_seconds"] >= 600