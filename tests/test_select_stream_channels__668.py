"""Tests for issue #668: Select stream channels when workout merges two sources.

Each test is anchored to a specific acceptance criterion.

AC1  — pure function documented with worked example, accepts sourceAMeta/sourceBMeta
AC2  — returns (merged, sourceMap) dict pair
AC3  — returns null + reason when either channel set is missing or empty
AC4  — power channel always from configured power source (Stryd); driven by config
AC5  — GPS channels from GPS-capable source; GPS identification configurable
AC6  — single-source channel passes through with no error
AC7  — chosen channels and sourceMap persisted by thin caller (apply_channel_selection)
AC8  — dependency check documented: both source streams must exist before running
AC9  — no magic values in function bodies: power_source and gps_channels from config
AC10 — unit tests cover all scenarios listed in the issue
"""

from backend.services.channel_select import select_channels, DEFAULT_CHANNEL_CONFIG


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _garmin_meta():
    return {"name": "garmin"}


def _stryd_meta():
    return {"name": "stryd"}


def _garmin_channels():
    return {
        "time_offset_seconds": [0, 1, 2, 3],
        "heart_rate_bpm": [145.0, 147.0, 146.0, 148.0],
        "cadence_spm": [178.0, 180.0, 179.0, 181.0],
        "altitude_m": [50.0, 51.0, 52.0, 51.0],
        "latitude": [1.23, 1.2301, 1.2302, 1.2303],
        "longitude": [103.8, 103.8001, 103.8002, 103.8003],
    }


def _stryd_channels():
    return {
        "time_offset_seconds": [0, 1, 2],
        "heart_rate_bpm": [144.0, 146.0, 147.0],
        "power_w": [255.0, 260.0, 258.0],
        "cadence_spm": [180.0, 182.0, 181.0],
    }


# ── AC1: Function signature and documentation ─────────────────────────────────

def test_function_accepts_meta_dicts():
    """AC1: select_channels accepts sourceAMeta and sourceBMeta as dicts."""
    merged, source_map, reason = select_channels(
        _garmin_channels(), _stryd_channels(),
        _garmin_meta(), _stryd_meta(),
    )
    assert merged is not None
    assert source_map is not None


def test_function_has_docstring_with_worked_example():
    """AC1: select_channels is fully documented with a worked example."""
    doc = select_channels.__doc__ or ""
    assert len(doc) > 50
    assert ">>" in doc or "Example" in doc or "example" in doc


def test_no_db_access_in_function_body():
    """AC1: select_channels is pure — no DB imports at module top level."""
    import importlib.util
    src = importlib.util.find_spec("backend.services.channel_select").origin
    with open(src) as fh:
        lines = fh.readlines()

    in_function = False
    top_level_imports = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("def ") or stripped.startswith("class "):
            in_function = True
        if not in_function and (stripped.startswith("import ") or stripped.startswith("from ")):
            top_level_imports.append(stripped)

    db_keywords = ("sqlalchemy", "backend.db", "backend.models", "psycopg")
    for imp in top_level_imports:
        for kw in db_keywords:
            assert kw not in imp, f"DB import '{imp}' at module top level"


# ── AC2: Returns mergedChannels + sourceMap ───────────────────────────────────

def test_returns_three_tuple():
    """AC2: Return value is a 3-tuple (merged, source_map, reason)."""
    result = select_channels(
        _garmin_channels(), _stryd_channels(),
        _garmin_meta(), _stryd_meta(),
    )
    assert len(result) == 3


def test_merged_and_source_map_are_dicts_on_success():
    """AC2: On success, merged and source_map are both dicts."""
    merged, source_map, reason = select_channels(
        _garmin_channels(), _stryd_channels(),
        _garmin_meta(), _stryd_meta(),
    )
    assert isinstance(merged, dict)
    assert isinstance(source_map, dict)


def test_source_map_keys_match_merged_keys():
    """AC2: Every channel in merged has a corresponding entry in source_map."""
    merged, source_map, _ = select_channels(
        _garmin_channels(), _stryd_channels(),
        _garmin_meta(), _stryd_meta(),
    )
    for ch in merged:
        assert ch in source_map, f"'{ch}' in merged but missing from source_map"


def test_source_map_values_are_source_names():
    """AC2: source_map values are the source name strings from the meta dicts."""
    merged, source_map, _ = select_channels(
        _garmin_channels(), _stryd_channels(),
        _garmin_meta(), _stryd_meta(),
    )
    valid = {"garmin", "stryd", None}
    for ch, src in source_map.items():
        assert src in valid, f"source_map['{ch}'] = {src!r} is not a recognised source name"


# ── AC3: Null + reason when either channel set is missing or empty ─────────────

def test_null_when_source_a_none():
    """AC3: None channel set A → (None, None, reason)."""
    merged, source_map, reason = select_channels(
        None, _stryd_channels(), _garmin_meta(), _stryd_meta()
    )
    assert merged is None
    assert source_map is None
    assert isinstance(reason, str) and len(reason) > 0


def test_null_when_source_b_none():
    """AC3: None channel set B → (None, None, reason)."""
    merged, source_map, reason = select_channels(
        _garmin_channels(), None, _garmin_meta(), _stryd_meta()
    )
    assert merged is None
    assert source_map is None
    assert isinstance(reason, str) and len(reason) > 0


def test_null_when_source_a_empty():
    """AC3: Empty dict channel set A → (None, None, reason)."""
    merged, source_map, reason = select_channels(
        {}, _stryd_channels(), _garmin_meta(), _stryd_meta()
    )
    assert merged is None
    assert source_map is None
    assert isinstance(reason, str) and len(reason) > 0


def test_null_when_source_b_empty():
    """AC3: Empty dict channel set B → (None, None, reason)."""
    merged, source_map, reason = select_channels(
        _garmin_channels(), {}, _garmin_meta(), _stryd_meta()
    )
    assert merged is None
    assert source_map is None
    assert isinstance(reason, str) and len(reason) > 0


# ── AC4: Power channel from configured power source ───────────────────────────

def test_power_from_stryd_when_stryd_is_source_b():
    """AC4: power_w taken from Stryd (source B) by default config."""
    merged, source_map, _ = select_channels(
        _garmin_channels(), _stryd_channels(),
        _garmin_meta(), _stryd_meta(),
    )
    assert merged is not None
    assert "power_w" in merged
    assert merged["power_w"] == _stryd_channels()["power_w"]
    assert source_map["power_w"] == "stryd"


def test_power_from_stryd_when_stryd_is_source_a():
    """AC4: power_w taken from Stryd even when Stryd is source A."""
    merged, source_map, _ = select_channels(
        _stryd_channels(), _garmin_channels(),
        _stryd_meta(), _garmin_meta(),
    )
    assert merged is not None
    assert "power_w" in merged
    assert source_map["power_w"] == "stryd"


def test_power_source_configurable_via_channel_config():
    """AC4: Renaming the power source in channel_config reroutes power selection."""
    # Replace "stryd" with "footpod" as the configured power source
    config = {**DEFAULT_CHANNEL_CONFIG, "power_source": "footpod"}
    footpod_meta = {"name": "footpod"}
    footpod_channels = {
        "time_offset_seconds": [0, 1, 2],
        "power_w": [300.0, 305.0, 302.0],
        "cadence_spm": [180.0, 182.0, 181.0],
    }
    merged, source_map, _ = select_channels(
        _garmin_channels(), footpod_channels,
        _garmin_meta(), footpod_meta,
        channel_config=config,
    )
    assert merged is not None
    assert "power_w" in merged
    assert source_map["power_w"] == "footpod"


def test_power_absent_with_reason_when_no_power_source():
    """AC4: When neither source matches power_source, power_w absent + reason returned."""
    polar_channels = {
        "time_offset_seconds": [0, 1, 2],
        "heart_rate_bpm": [140.0, 142.0, 141.0],
        "cadence_spm": [176.0, 178.0, 177.0],
        "latitude": [1.1, 1.2, 1.3],
        "longitude": [103.0, 103.1, 103.2],
    }
    merged, source_map, reason = select_channels(
        _garmin_channels(), polar_channels,
        {"name": "garmin"}, {"name": "polar"},
    )
    assert merged is not None
    assert "power_w" not in merged
    assert source_map.get("power_w") is None
    assert reason is not None and len(reason) > 0


# ── AC5: GPS channels from configurable GPS source ────────────────────────────

def test_gps_channels_from_garmin():
    """AC5: latitude/longitude/altitude_m taken from the GPS-bearing source (garmin)."""
    merged, source_map, _ = select_channels(
        _garmin_channels(), _stryd_channels(),
        _garmin_meta(), _stryd_meta(),
    )
    assert merged is not None
    assert "latitude" in merged
    assert "longitude" in merged
    assert "altitude_m" in merged
    assert source_map["latitude"] == "garmin"
    assert source_map["longitude"] == "garmin"
    assert source_map["altitude_m"] == "garmin"


def test_gps_channels_configurable_via_channel_config():
    """AC5: GPS channel list can be overridden via channel_config."""
    # Rename GPS channels: altitude is now "elevation_m" instead of "altitude_m"
    config = {**DEFAULT_CHANNEL_CONFIG, "gps_channels": frozenset({"latitude", "longitude", "elevation_m"})}
    garmin_alt = {**_garmin_channels(), "elevation_m": [100.0, 101.0, 102.0, 103.0]}
    del garmin_alt["altitude_m"]
    merged, source_map, _ = select_channels(
        garmin_alt, _stryd_channels(),
        _garmin_meta(), _stryd_meta(),
        channel_config=config,
    )
    assert merged is not None
    assert "elevation_m" in merged
    assert source_map.get("elevation_m") == "garmin"


def test_gps_channels_omitted_when_neither_source_has_gps():
    """AC5: Neither source has GPS → GPS channels absent from merged, no error."""
    stryd_a = _stryd_channels()
    stryd_b = {
        "time_offset_seconds": [0, 1, 2, 3],
        "heart_rate_bpm": [150.0, 152.0, 151.0, 153.0],
        "power_w": [270.0, 275.0, 268.0, 272.0],
    }
    merged, source_map, _ = select_channels(
        stryd_a, stryd_b, _stryd_meta(), {"name": "polar"}
    )
    assert merged is not None
    assert "latitude" not in merged
    assert "longitude" not in merged
    assert "altitude_m" not in merged


def test_gps_detector_channel_configurable():
    """AC5: The channel used to detect GPS presence is configurable, not hardcoded."""
    # Use a non-standard GPS detector: "lon" instead of "latitude"
    config = {**DEFAULT_CHANNEL_CONFIG, "gps_detector": "lon", "gps_channels": frozenset({"lat", "lon"})}
    source_a = {
        "time_offset_seconds": [0, 1, 2],
        "heart_rate_bpm": [140.0, 141.0, 142.0],
        "lat": [1.1, 1.2, 1.3],
        "lon": [103.0, 103.1, 103.2],
    }
    source_b = {
        "time_offset_seconds": [0, 1, 2],
        "power_w": [250.0, 255.0, 252.0],
    }
    merged, source_map, _ = select_channels(
        source_a, source_b,
        {"name": "custom_gps"}, {"name": "stryd"},
        channel_config=config,
    )
    assert merged is not None
    assert "lat" in merged
    assert "lon" in merged
    assert source_map["lat"] == "custom_gps"
    assert source_map["lon"] == "custom_gps"


# ── AC6: Single-source channel passes through ─────────────────────────────────

def test_channel_only_in_source_a_passes_through():
    """AC6: A channel exclusive to source A is included in merged without error."""
    garmin = {
        "time_offset_seconds": [0, 1, 2],
        "heart_rate_bpm": [145.0, 146.0, 147.0],
        "temperature_c": [22.0, 22.1, 22.2],  # only in garmin
        "latitude": [1.23, 1.24, 1.25],
        "longitude": [103.8, 103.81, 103.82],
    }
    merged, source_map, _ = select_channels(
        garmin, _stryd_channels(), _garmin_meta(), _stryd_meta()
    )
    assert "temperature_c" in merged
    assert source_map["temperature_c"] == "garmin"


def test_channel_only_in_source_b_passes_through():
    """AC6: A channel exclusive to source B is included in merged without error."""
    merged, source_map, _ = select_channels(
        _garmin_channels(), _stryd_channels(),
        _garmin_meta(), _stryd_meta(),
    )
    # cadence_spm appears in both, but power_w is only in stryd's power_w channel
    assert "power_w" in merged
    assert source_map["power_w"] == "stryd"


def test_both_sources_missing_a_channel_omits_it():
    """AC6: A channel absent from both sources is simply omitted — no error raised."""
    garmin = {"time_offset_seconds": [0, 1], "heart_rate_bpm": [140.0, 141.0]}
    stryd = {"time_offset_seconds": [0, 1], "power_w": [250.0, 255.0]}
    merged, source_map, reason = select_channels(
        garmin, stryd, _garmin_meta(), _stryd_meta()
    )
    assert merged is not None
    assert "temperature_c" not in merged
    assert "latitude" not in merged


# ── AC9: No magic values — config drives all identifiers ──────────────────────

def test_default_channel_config_is_exported():
    """AC9: DEFAULT_CHANNEL_CONFIG is importable so callers can extend it."""
    from backend.services.channel_select import DEFAULT_CHANNEL_CONFIG as cfg
    assert "power_source" in cfg
    assert "gps_channels" in cfg


def test_no_hardcoded_stryd_in_function_body():
    """AC9: The string 'stryd' does not appear as a literal inside select_channels body."""
    import inspect
    from backend.services.channel_select import select_channels as fn
    src = inspect.getsource(fn)
    # Allow "stryd" in comments/docstrings but not as a standalone string literal
    import ast
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value != "stryd", (
                "The literal 'stryd' must not appear in select_channels body — "
                "use channel_config['power_source'] instead"
            )


def test_no_hardcoded_gps_channel_names_in_function_body():
    """AC9: GPS channel names ('latitude', 'longitude', 'altitude_m') not hardcoded in select_channels."""
    import inspect
    import ast
    from backend.services.channel_select import select_channels as fn
    src = inspect.getsource(fn)
    tree = ast.parse(src)
    gps_literals = {"latitude", "longitude", "altitude_m"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            assert node.value not in gps_literals, (
                f"GPS channel name '{node.value}' must not be hardcoded in "
                f"select_channels — use channel_config['gps_channels'] instead"
            )


# ── AC10: Scenario matrix ─────────────────────────────────────────────────────

def test_scenario_both_sources_present_overlapping():
    """AC10: Both sources present with overlapping channels — each resolved to one source."""
    merged, source_map, reason = select_channels(
        _garmin_channels(), _stryd_channels(),
        _garmin_meta(), _stryd_meta(),
    )
    assert merged is not None
    all_keys = set(_garmin_channels()) | set(_stryd_channels())
    for ch in all_keys:
        if ch in ("latitude", "longitude", "altitude_m"):
            assert ch in merged
            assert source_map[ch] == "garmin"
        elif ch == "power_w":
            assert ch in merged
            assert source_map[ch] == "stryd"
        else:
            assert ch in merged, f"channel '{ch}' missing from merged"


def test_scenario_one_source_missing_a_channel():
    """AC10: One source missing a channel — the other source's value wins."""
    garmin = {
        "time_offset_seconds": [0, 1, 2, 3],
        "heart_rate_bpm": [145.0, 146.0, 147.0, 148.0],
        "latitude": [1.23, 1.24, 1.25, 1.26],
        "longitude": [103.8, 103.81, 103.82, 103.83],
    }
    stryd = {
        "time_offset_seconds": [0, 1, 2],
        "power_w": [255.0, 260.0, 258.0],
        "cadence_spm": [180.0, 182.0, 181.0],
    }
    merged, source_map, _ = select_channels(
        garmin, stryd, _garmin_meta(), _stryd_meta()
    )
    assert merged is not None
    assert "cadence_spm" in merged
    assert source_map["cadence_spm"] == "stryd"
    assert "heart_rate_bpm" in merged
    assert source_map["heart_rate_bpm"] == "garmin"


def test_scenario_both_sources_missing_a_channel():
    """AC10: Both sources missing a channel — omitted without error."""
    garmin = {"time_offset_seconds": [0, 1], "heart_rate_bpm": [140.0, 141.0]}
    stryd = {"time_offset_seconds": [0, 1], "power_w": [250.0, 255.0]}
    merged, source_map, reason = select_channels(
        garmin, stryd, _garmin_meta(), _stryd_meta()
    )
    assert merged is not None
    assert "cadence_spm" not in merged


def test_scenario_missing_input_returns_null_and_reason():
    """AC10: Missing input (None channel set) → (None, None, reason)."""
    merged, source_map, reason = select_channels(
        None, _stryd_channels(), _garmin_meta(), _stryd_meta()
    )
    assert merged is None
    assert source_map is None
    assert isinstance(reason, str) and len(reason) > 0


def test_scenario_all_gps_channels_to_correct_source():
    """AC10: All three GPS channels (latitude, longitude, altitude_m) go to GPS source."""
    merged, source_map, _ = select_channels(
        _garmin_channels(), _stryd_channels(),
        _garmin_meta(), _stryd_meta(),
    )
    for gps_ch in ("latitude", "longitude", "altitude_m"):
        assert gps_ch in merged, f"GPS channel '{gps_ch}' missing from merged"
        assert source_map[gps_ch] == "garmin", f"GPS channel '{gps_ch}' not attributed to garmin"


def test_scenario_power_channel_resolved_to_stryd():
    """AC10: Power channel always resolved to the Stryd source."""
    merged, source_map, _ = select_channels(
        _garmin_channels(), _stryd_channels(),
        _garmin_meta(), _stryd_meta(),
    )
    assert "power_w" in merged
    assert source_map["power_w"] == "stryd"
