"""Tests for issue #584: Add phase grouping for session profile detection.

Acceptance criteria covered:
  AC1  — group_laps_into_phases exists and is importable
  AC2  — accepts classified_laps list and config with TEMPO_MIN_DURATION_SECONDS
          and TEMPO_MIN_DISTANCE_KM; no hardcoded numeric thresholds in logic
  AC3  — low-intensity block (easy/steady) at position 0 → label "Warm-up"
  AC4  — low-intensity block (easy/steady) at last position → label "Cool-down"
  AC5  — single tempo/threshold block meeting duration OR distance threshold → "Tempo"
  AC6  — all other contiguous same-band blocks → labeled by band name
  AC7  — interval detection excluded; laps that would form intervals are generic
  AC8  — each phase contains: label, lap_indexes, distance_km, duration_seconds,
          avg_pace_seconds_per_km, avg_hr (or null), avg_power (or null), band
  AC9  — phases returned in ascending lap order
  AC10 — null/empty/missing-required-fields input → (None, reason_str); no raise
  AC11 — no database access in the pure function
  AC12 — unit tests: (a) warm-up + tempo + cool-down golden path,
                     (b) no warm-up or cool-down,
                     (c) tempo meets only duration threshold,
                     (d) tempo meets only distance threshold,
                     (e) tempo below both thresholds → generic,
                     (f) null/empty input → (None, reason)
"""

import pytest

from backend.services.lap_phase_grouper import group_laps_into_phases, LapPhaseConfig


# ── Helpers ───────────────────────────────────────────────────────────────────

def _lap(band, distance_km, duration_seconds, avg_hr=None, avg_power=None):
    """Build a classified-lap dict as the caller would construct it."""
    return {
        "band": band,
        "distance_km": distance_km,
        "duration_seconds": duration_seconds,
        "avg_hr": avg_hr,
        "avg_power": avg_power,
    }


class _Cfg:
    """Minimal config stub matching the AC contract."""
    TEMPO_MIN_DURATION_SECONDS = 480  # about 8 minutes
    TEMPO_MIN_DISTANCE_KM = 2.0       # about 2 km


CFG = _Cfg()


# ── AC1: importable ──────────────────────────────────────────────────────────

def test_import():
    """AC1: group_laps_into_phases is importable from lap_phase_grouper."""
    assert callable(group_laps_into_phases)


def test_default_config_class_importable():
    """AC1/AC2: LapPhaseConfig with correct default constants is importable."""
    assert hasattr(LapPhaseConfig, "TEMPO_MIN_DURATION_SECONDS")
    assert hasattr(LapPhaseConfig, "TEMPO_MIN_DISTANCE_KM")
    assert LapPhaseConfig.TEMPO_MIN_DURATION_SECONDS > 0
    assert LapPhaseConfig.TEMPO_MIN_DISTANCE_KM > 0


# ── AC2: config-driven thresholds ─────────────────────────────────────────────

def test_tempo_threshold_from_config_not_hardcoded():
    """AC2/AC5: a very high TEMPO_MIN_DURATION_SECONDS causes tempo block to
    fall through to generic labeling, proving thresholds are config-driven."""

    class HighThresholdCfg:
        TEMPO_MIN_DURATION_SECONDS = 9999
        TEMPO_MIN_DISTANCE_KM = 9999.0

    laps = [
        _lap("easy",      1.0, 360),
        _lap("tempo",     3.0, 600),  # 600 s and 3 km — below 9999/9999
        _lap("easy",      1.0, 300),
    ]
    phases, reason = group_laps_into_phases(laps, HighThresholdCfg())
    assert reason is None
    middle = phases[1]
    assert middle["label"] == "tempo"  # generic, not "Tempo"


# ── AC12(a): golden path — warm-up + tempo + cool-down ────────────────────────

def test_golden_path_three_phases():
    """AC12(a): warm-up → tempo → cool-down session returns exactly 3 phases."""
    laps = [
        _lap("easy",      1.5,  450, avg_hr=130),
        _lap("tempo",     2.0,  480, avg_hr=155),
        _lap("easy",      1.0,  360, avg_hr=128),
    ]
    phases, reason = group_laps_into_phases(laps, CFG)
    assert reason is None
    assert len(phases) == 3


def test_golden_path_labels():
    """AC12(a): first easy→Warm-up, middle tempo→Tempo, last easy→Cool-down."""
    laps = [
        _lap("easy",  1.5, 450),
        _lap("tempo", 2.0, 480),
        _lap("easy",  1.0, 360),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    assert phases[0]["label"] == "Warm-up"
    assert phases[1]["label"] == "Tempo"
    assert phases[2]["label"] == "Cool-down"


def test_golden_path_lap_indexes():
    """AC8/AC12(a): lap_indexes are correct per phase."""
    laps = [
        _lap("easy",  1.5, 450),
        _lap("tempo", 2.0, 480),
        _lap("easy",  1.0, 360),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    assert phases[0]["lap_indexes"] == [0]
    assert phases[1]["lap_indexes"] == [1]
    assert phases[2]["lap_indexes"] == [2]


def test_golden_path_aggregations():
    """AC8/AC12(a): distance_km, duration_seconds, avg_pace aggregated correctly."""
    laps = [
        _lap("easy",  1.5, 450),
        _lap("tempo", 2.0, 480),
        _lap("easy",  1.0, 360),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    warmup = phases[0]
    assert warmup["distance_km"] == pytest.approx(1.5)
    assert warmup["duration_seconds"] == pytest.approx(450)
    # avg_pace = 450 / 1.5 = 300 s/km
    assert warmup["avg_pace_seconds_per_km"] == pytest.approx(300.0)


def test_golden_path_band_field():
    """AC8: each phase carries the band field matching its laps."""
    laps = [
        _lap("easy",  1.5, 450),
        _lap("tempo", 2.0, 480),
        _lap("easy",  1.0, 360),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    assert phases[0]["band"] == "easy"
    assert phases[1]["band"] == "tempo"
    assert phases[2]["band"] == "easy"


def test_golden_path_avg_hr():
    """AC8: avg_hr is the average of lap avg_hr values in the phase."""
    laps = [
        _lap("easy",  1.5, 450, avg_hr=130),
        _lap("tempo", 2.0, 480, avg_hr=155),
        _lap("easy",  1.0, 360, avg_hr=128),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    assert phases[0]["avg_hr"] == pytest.approx(130.0)
    assert phases[1]["avg_hr"] == pytest.approx(155.0)
    assert phases[2]["avg_hr"] == pytest.approx(128.0)


def test_golden_path_avg_hr_null_when_absent():
    """AC8: avg_hr is None when all laps in the phase have no HR data."""
    laps = [
        _lap("easy",  1.5, 450, avg_hr=None),
        _lap("tempo", 2.0, 480, avg_hr=None),
        _lap("easy",  1.0, 360, avg_hr=None),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    for phase in phases:
        assert phase["avg_hr"] is None


def test_golden_path_avg_power_null():
    """AC8: avg_power is None when no lap has power data."""
    laps = [
        _lap("easy",  1.5, 450),
        _lap("tempo", 2.0, 480),
        _lap("easy",  1.0, 360),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    for phase in phases:
        assert phase["avg_power"] is None


# ── AC9: ascending order ──────────────────────────────────────────────────────

def test_phases_in_ascending_order():
    """AC9: lap_indexes are ascending across phases."""
    laps = [
        _lap("easy",      1.0, 300),
        _lap("easy",      1.0, 300),
        _lap("threshold", 2.5, 600),
        _lap("easy",      1.0, 300),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    all_indexes = [i for p in phases for i in p["lap_indexes"]]
    assert all_indexes == sorted(all_indexes)


# ── AC12(b): no warm-up or cool-down ─────────────────────────────────────────

def test_no_warmup_cooldown_when_starts_at_tempo():
    """AC12(b): session starting immediately at tempo has no Warm-up phase."""
    laps = [
        _lap("tempo", 2.0, 480),
        _lap("tempo", 2.0, 480),
        _lap("easy",  1.0, 360),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    labels = [p["label"] for p in phases]
    assert "Warm-up" not in labels


def test_no_warmup_cooldown_when_all_tempo():
    """AC12(b): an all-tempo session has neither Warm-up nor Cool-down."""
    laps = [_lap("tempo", 2.0, 500)] * 3
    phases, _ = group_laps_into_phases(laps, CFG)
    labels = [p["label"] for p in phases]
    assert "Warm-up" not in labels
    assert "Cool-down" not in labels


def test_no_cooldown_when_ends_at_tempo():
    """AC12(b): session ending at high intensity has no Cool-down phase."""
    laps = [
        _lap("easy",  1.0, 300),
        _lap("tempo", 2.0, 480),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    labels = [p["label"] for p in phases]
    assert "Cool-down" not in labels


# ── AC12(c): tempo meets only duration threshold ──────────────────────────────

def test_tempo_labeled_when_duration_meets_threshold():
    """AC12(c): block with duration >= TEMPO_MIN_DURATION but distance < threshold
    is still labeled Tempo (duration threshold alone is sufficient)."""
    laps = [
        _lap("easy",  0.5, 200),
        _lap("tempo", 1.5, 500),  # 1.5 km < 2.0 km, 500 s >= 480 s
        _lap("easy",  0.5, 200),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    middle = next(p for p in phases if p["band"] in ("tempo", "threshold"))
    assert middle["label"] == "Tempo"


# ── AC12(d): tempo meets only distance threshold ──────────────────────────────

def test_tempo_labeled_when_distance_meets_threshold():
    """AC12(d): block with distance >= TEMPO_MIN_DISTANCE but duration < threshold
    is still labeled Tempo (distance threshold alone is sufficient)."""
    laps = [
        _lap("easy",  0.5,  200),
        _lap("tempo", 2.5,  400),  # 2.5 km >= 2.0 km, 400 s < 480 s
        _lap("easy",  0.5,  200),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    middle = next(p for p in phases if p["band"] in ("tempo", "threshold"))
    assert middle["label"] == "Tempo"


# ── AC12(e): tempo below both thresholds → generic ───────────────────────────

def test_short_tempo_block_falls_to_generic():
    """AC12(e): tempo block below both thresholds is labeled by band name, not Tempo."""
    laps = [
        _lap("easy",  0.5, 200),
        _lap("tempo", 1.2, 300),  # 300 s < 480 s, 1.2 km < 2.0 km
        _lap("easy",  0.5, 200),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    middle = next(p for p in phases if p["band"] in ("tempo", "threshold"))
    assert middle["label"] == "tempo"


def test_threshold_band_below_both_thresholds_generic():
    """AC6: threshold band not meeting size thresholds → labeled 'threshold'."""
    laps = [
        _lap("easy",      0.5, 200),
        _lap("threshold", 1.0, 300),  # below both thresholds
        _lap("easy",      0.5, 200),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    middle = next(p for p in phases if p["band"] == "threshold")
    assert middle["label"] == "threshold"


# ── AC12(f): null/empty input ─────────────────────────────────────────────────

def test_null_input_returns_none():
    """AC12(f)/AC10: None input → first element is None."""
    result, reason = group_laps_into_phases(None, CFG)
    assert result is None


def test_null_input_returns_reason_string():
    """AC12(f)/AC10: None input → reason is a non-empty string."""
    _, reason = group_laps_into_phases(None, CFG)
    assert isinstance(reason, str)
    assert len(reason) > 0


def test_empty_input_returns_none():
    """AC12(f)/AC10: empty list → first element is None."""
    result, reason = group_laps_into_phases([], CFG)
    assert result is None


def test_empty_input_returns_reason_string():
    """AC12(f)/AC10: empty list → reason is a non-empty string."""
    _, reason = group_laps_into_phases([], CFG)
    assert isinstance(reason, str)
    assert len(reason) > 0


def test_missing_band_field_returns_none():
    """AC10: lap missing 'band' field → returns (None, reason) without raising."""
    laps = [{"distance_km": 1.0, "duration_seconds": 300}]
    result, reason = group_laps_into_phases(laps, CFG)
    assert result is None
    assert isinstance(reason, str)


def test_missing_distance_field_returns_none():
    """AC10: lap missing 'distance_km' field → returns (None, reason) without raising."""
    laps = [{"band": "easy", "duration_seconds": 300}]
    result, reason = group_laps_into_phases(laps, CFG)
    assert result is None
    assert isinstance(reason, str)


def test_missing_duration_field_returns_none():
    """AC10: lap missing 'duration_seconds' field → returns (None, reason) without raising."""
    laps = [{"band": "easy", "distance_km": 1.0}]
    result, reason = group_laps_into_phases(laps, CFG)
    assert result is None
    assert isinstance(reason, str)


def test_does_not_raise_on_null():
    """AC10: None input does not raise any exception."""
    try:
        group_laps_into_phases(None, CFG)
    except Exception as exc:
        pytest.fail(f"group_laps_into_phases raised on None input: {exc}")


# ── AC3: warm-up from steady band ─────────────────────────────────────────────

def test_steady_band_at_start_is_warmup():
    """AC3: a 'steady' band block at position 0 is labeled Warm-up (not just easy)."""
    laps = [
        _lap("steady", 1.5, 450),
        _lap("tempo",  2.0, 480),
        _lap("easy",   1.0, 360),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    assert phases[0]["label"] == "Warm-up"


# ── AC4: cool-down from steady band ──────────────────────────────────────────

def test_steady_band_at_end_is_cooldown():
    """AC4: a 'steady' band block at the last position is labeled Cool-down."""
    laps = [
        _lap("easy",   1.0, 300),
        _lap("tempo",  2.0, 480),
        _lap("steady", 1.5, 450),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    assert phases[-1]["label"] == "Cool-down"


# ── AC5: threshold band qualifies for Tempo label ─────────────────────────────

def test_threshold_band_meeting_thresholds_labeled_tempo():
    """AC5: threshold band meeting TEMPO_MIN_DURATION → labeled Tempo."""
    laps = [
        _lap("easy",      1.0, 300),
        _lap("threshold", 2.0, 500),  # 500 s >= 480 s
        _lap("easy",      1.0, 300),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    middle = next(p for p in phases if p["band"] == "threshold")
    assert middle["label"] == "Tempo"


# ── AC6: generic block labeling ──────────────────────────────────────────────

def test_hard_band_labeled_by_band_name():
    """AC6: hard band blocks not qualifying as warm-up/cool-down/tempo → 'hard'."""
    laps = [
        _lap("easy", 1.0, 300),
        _lap("hard", 0.5, 200),
        _lap("easy", 1.0, 300),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    hard_phase = next(p for p in phases if p["band"] == "hard")
    assert hard_phase["label"] == "hard"


# ── AC7: intervals pass through as generic ────────────────────────────────────

def test_alternating_bands_are_generic_not_interval():
    """AC7: alternating easy/tempo blocks are treated as separate generic phases,
    not merged into an interval phase."""
    laps = [
        _lap("easy",  0.4, 120),
        _lap("tempo", 0.4, 120),  # each block below both thresholds
        _lap("easy",  0.4, 120),
        _lap("tempo", 0.4, 120),
        _lap("easy",  0.4, 120),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    labels = [p["label"] for p in phases]
    # No "Interval" label; each block labeled generically
    assert "Interval" not in labels
    # All tempo blocks labeled as generic "tempo" (below thresholds)
    for phase in phases:
        if phase["band"] == "tempo":
            assert phase["label"] == "tempo"


# ── AC8: all required phase fields present ───────────────────────────────────

def test_all_required_phase_fields_present():
    """AC8: every returned phase dict contains all required keys."""
    required_keys = {
        "label", "lap_indexes", "distance_km", "duration_seconds",
        "avg_pace_seconds_per_km", "avg_hr", "avg_power", "band",
    }
    laps = [
        _lap("easy",  1.0, 300, avg_hr=130, avg_power=150),
        _lap("tempo", 2.0, 480, avg_hr=155, avg_power=200),
        _lap("easy",  1.0, 300, avg_hr=128, avg_power=140),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    for phase in phases:
        assert required_keys.issubset(phase.keys()), (
            f"Phase missing keys: {required_keys - phase.keys()}"
        )


# ── Multi-lap phase aggregation ───────────────────────────────────────────────

def test_multi_lap_warmup_aggregated():
    """AC8: a short multi-lap warm-up (<=25% of the run) aggregates + labels.

    The run is long enough that the two easy opening laps stay under the
    WARMUP_MAX_FRACTION size gate.
    """
    laps = [
        _lap("easy",  1.0, 300),
        _lap("easy",  1.5, 450),
        _lap("tempo", 2.0, 480),
        _lap("tempo", 2.0, 480),
        _lap("tempo", 2.0, 480),
        _lap("tempo", 2.0, 480),
        _lap("easy",  1.0, 300),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    warmup = phases[0]
    assert warmup["label"] == "Warm-up"
    assert warmup["lap_indexes"] == [0, 1]
    assert warmup["distance_km"] == pytest.approx(2.5)
    assert warmup["duration_seconds"] == pytest.approx(750)
    assert warmup["avg_pace_seconds_per_km"] == pytest.approx(750 / 2.5)


def test_long_opening_block_is_not_warmup():
    """A long opening low-intensity block (> 25% of the run) keeps its band
    name instead of being mislabelled as a multi-lap Warm-up."""
    laps = [_lap("steady", 1.0, 360) for _ in range(7)]  # 7 km steady block
    laps.append(_lap("tempo", 1.0, 300))                  # one harder lap
    phases, _ = group_laps_into_phases(laps, CFG)
    assert phases[0]["lap_indexes"] == [0, 1, 2, 3, 4, 5, 6]
    assert phases[0]["label"] != "Warm-up"  # 7/8 of the run — it's the main block


def test_multi_lap_tempo_summed():
    """AC8: tempo phase spanning multiple consecutive tempo laps sums correctly."""
    laps = [
        _lap("easy",  1.0, 300),
        _lap("tempo", 1.0, 250),
        _lap("tempo", 1.2, 300),  # combined: 2.2 km >= 2.0 km threshold
        _lap("easy",  1.0, 300),
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    tempo_phase = next(p for p in phases if p["band"] == "tempo")
    assert tempo_phase["label"] == "Tempo"
    assert tempo_phase["lap_indexes"] == [1, 2]
    assert tempo_phase["distance_km"] == pytest.approx(2.2)
    assert tempo_phase["duration_seconds"] == pytest.approx(550)


# ── avg_power aggregation ─────────────────────────────────────────────────────

def test_avg_power_averaged_across_laps():
    """AC8: avg_power is the mean of lap avg_power values within the phase."""
    laps = [
        _lap("tempo", 1.0, 250, avg_power=200),
        _lap("tempo", 1.2, 300, avg_power=220),  # 2.2 km >= 2.0 km threshold
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    tempo_phase = phases[0]
    assert tempo_phase["avg_power"] == pytest.approx(210.0)


def test_avg_hr_averaged_across_laps():
    """AC8: avg_hr is the mean of lap avg_hr values within the phase."""
    laps = [
        _lap("tempo", 1.0, 250, avg_hr=150),
        _lap("tempo", 1.2, 300, avg_hr=160),  # 2.2 km >= 2.0 km threshold
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    tempo_phase = phases[0]
    assert tempo_phase["avg_hr"] == pytest.approx(155.0)


def test_avg_hr_partial_null_excluded():
    """AC8: laps with None avg_hr are excluded from the average (not counted as 0)."""
    laps = [
        _lap("easy", 1.0, 300, avg_hr=130),
        _lap("easy", 1.0, 300, avg_hr=None),  # should not skew average
    ]
    phases, _ = group_laps_into_phases(laps, CFG)
    warmup = phases[0]
    # average of [130] only, not [130, None]
    assert warmup["avg_hr"] == pytest.approx(130.0)


# ── AC11: no database access ──────────────────────────────────────────────────

def test_no_db_parameter():
    """AC11: group_laps_into_phases signature accepts no session/db argument."""
    import inspect
    sig = inspect.signature(group_laps_into_phases)
    param_names = list(sig.parameters.keys())
    assert "session" not in param_names
    assert "db" not in param_names


# ── LapPhaseConfig defaults match AC2 ────────────────────────────────────────

def test_default_config_tempo_min_duration_approx_8_min():
    """AC2: LapPhaseConfig.TEMPO_MIN_DURATION_SECONDS should be about 480 s (8 min)."""
    # Allow ±60 s of flexibility around the 'about 8 minutes' constraint
    assert 420 <= LapPhaseConfig.TEMPO_MIN_DURATION_SECONDS <= 540


def test_default_config_tempo_min_distance_approx_2_km():
    """AC2: LapPhaseConfig.TEMPO_MIN_DISTANCE_KM should be about 2 km."""
    # Allow ±0.5 km of flexibility
    assert 1.5 <= LapPhaseConfig.TEMPO_MIN_DISTANCE_KM <= 2.5
