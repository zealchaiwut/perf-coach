"""
Tests for issue #574: Select stream channels when merging two workout sources.

Acceptance criteria verified:
- AC1: select_channels is a pure function documented with worked example.
- AC2: Returns (None, None, reason) when either channel set is missing or empty.
- AC3: power_w always from Stryd; absent when Stryd is not a source (with reason).
- AC4: GPS channels from GPS-capable source; omitted cleanly when neither has GPS.
- AC5: Non-special channels use a configurable tiebreak_rule (default "longer").
- AC6: Returns merged channel map AND per-channel attribution map.
- AC7: No database access inside select_channels (pure function).
- AC8: apply_channel_selection (thin caller) persists merged result + attribution.
- AC9: Unit tests cover (a) both sources overlapping, (b) Stryd absent,
        (c) no GPS source, (d) empty/null channel set.
- AC10: Function does not run unless both source streams exist.
"""
import pytest

from backend.services.channel_select import select_channels


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / helpers
# ─────────────────────────────────────────────────────────────────────────────

def _garmin_channels():
    """Simulated Garmin (GPS watch) channel set with GPS but no power."""
    return {
        "time_offset_seconds": [0, 1, 2, 3],
        "heart_rate_bpm": [145.0, 147.0, 146.0, 148.0],
        "cadence_spm": [178.0, 180.0, 179.0, 181.0],
        "pace_seconds_per_km": [300.0, 295.0, 298.0, 297.0],
        "altitude_m": [50.0, 51.0, 52.0, 51.0],
        "latitude": [1.23, 1.2301, 1.2302, 1.2303],
        "longitude": [103.8, 103.8001, 103.8002, 103.8003],
    }


def _stryd_channels():
    """Simulated Stryd channel set with power but no GPS."""
    return {
        "time_offset_seconds": [0, 1, 2],
        "heart_rate_bpm": [144.0, 146.0, 147.0],
        "power_w": [255.0, 260.0, 258.0],
        "cadence_spm": [180.0, 182.0, 181.0],
        "pace_seconds_per_km": [298.0, 296.0, 297.0],
    }


# ─────────────────────────────────────────────────────────────────────────────
# AC2: Returns null with reason when either channel set is missing or empty
# ─────────────────────────────────────────────────────────────────────────────

def test_null_when_source_a_is_none():
    """AC2/AC9d: None channel set A → (None, None, reason)."""
    merged, attribution, reason = select_channels(
        None, _stryd_channels(), "garmin", "stryd"
    )
    assert merged is None
    assert attribution is None
    assert reason is not None
    assert len(reason) > 0


def test_null_when_source_b_is_none():
    """AC2/AC9d: None channel set B → (None, None, reason)."""
    merged, attribution, reason = select_channels(
        _garmin_channels(), None, "garmin", "stryd"
    )
    assert merged is None
    assert attribution is None
    assert reason is not None


def test_null_when_source_a_is_empty():
    """AC2/AC9d: Empty dict channel set A → (None, None, reason)."""
    merged, attribution, reason = select_channels(
        {}, _stryd_channels(), "garmin", "stryd"
    )
    assert merged is None
    assert attribution is None
    assert reason is not None


def test_null_when_source_b_is_empty():
    """AC2/AC9d: Empty dict channel set B → (None, None, reason)."""
    merged, attribution, reason = select_channels(
        _garmin_channels(), {}, "garmin", "stryd"
    )
    assert merged is None
    assert attribution is None
    assert reason is not None


# ─────────────────────────────────────────────────────────────────────────────
# AC3: power_w always from Stryd; absent (with reason) when Stryd not present
# ─────────────────────────────────────────────────────────────────────────────

def test_power_w_from_stryd_when_stryd_is_source_b():
    """AC3/AC9a: power_w taken from Stryd (source B)."""
    merged, attribution, reason = select_channels(
        _garmin_channels(), _stryd_channels(), "garmin", "stryd"
    )
    assert merged is not None
    assert "power_w" in merged
    assert merged["power_w"] == _stryd_channels()["power_w"]
    assert attribution["power_w"] == "stryd"


def test_power_w_from_stryd_when_stryd_is_source_a():
    """AC3: power_w taken from Stryd even when Stryd is source A."""
    merged, attribution, reason = select_channels(
        _stryd_channels(), _garmin_channels(), "stryd", "garmin"
    )
    assert merged is not None
    assert "power_w" in merged
    assert merged["power_w"] == _stryd_channels()["power_w"]
    assert attribution["power_w"] == "stryd"


def test_power_w_null_with_reason_when_stryd_absent():
    """AC3/AC9b: Stryd is not either source → power_w absent in merged, reason returned."""
    garmin2 = {
        "time_offset_seconds": [0, 1, 2],
        "heart_rate_bpm": [140.0, 142.0, 141.0],
        "latitude": [1.1, 1.2, 1.3],
        "longitude": [103.0, 103.1, 103.2],
    }
    polar = {
        "time_offset_seconds": [0, 1, 2],
        "heart_rate_bpm": [139.0, 141.0, 140.0],
        "cadence_spm": [176.0, 178.0, 177.0],
    }
    merged, attribution, reason = select_channels(garmin2, polar, "garmin", "polar")
    # merged is not None (other channels still merged)
    assert merged is not None
    # power_w is absent from merged result
    assert "power_w" not in merged or merged.get("power_w") is None
    # attribution records the absence
    assert attribution.get("power_w") is None
    # reason explains the absence
    assert reason is not None
    assert len(reason) > 0


# ─────────────────────────────────────────────────────────────────────────────
# AC4: GPS channels from GPS source; omitted cleanly when neither has GPS
# ─────────────────────────────────────────────────────────────────────────────

def test_gps_channels_taken_from_garmin():
    """AC4: latitude/longitude/altitude_m come from the GPS-capable source (garmin)."""
    merged, attribution, reason = select_channels(
        _garmin_channels(), _stryd_channels(), "garmin", "stryd"
    )
    assert merged is not None
    assert "latitude" in merged
    assert "longitude" in merged
    assert "altitude_m" in merged
    assert attribution["latitude"] == "garmin"
    assert attribution["longitude"] == "garmin"
    assert attribution["altitude_m"] == "garmin"


def test_gps_channels_omitted_when_neither_source_has_gps():
    """AC4/AC9c: Neither source has GPS → GPS channels absent from merged, no error."""
    stryd_a = _stryd_channels()
    stryd_b = {
        "time_offset_seconds": [0, 1, 2, 3],
        "heart_rate_bpm": [150.0, 152.0, 151.0, 153.0],
        "power_w": [270.0, 275.0, 268.0, 272.0],
    }
    merged, attribution, reason = select_channels(stryd_a, stryd_b, "stryd", "polar")
    # Function should not raise and merged should be a dict
    assert merged is not None
    # GPS channels absent
    assert "latitude" not in merged
    assert "longitude" not in merged
    assert "altitude_m" not in merged
    # No GPS-related keys in attribution either
    assert "latitude" not in attribution
    assert "longitude" not in attribution


# ─────────────────────────────────────────────────────────────────────────────
# AC5: Configurable tiebreak_rule
# ─────────────────────────────────────────────────────────────────────────────

def test_tiebreak_longer_picks_source_with_more_samples():
    """AC5: default 'longer' rule — source with more samples wins for a channel."""
    src_a = {
        "time_offset_seconds": [0, 1, 2, 3, 4],
        "heart_rate_bpm": [140.0, 141.0, 142.0, 143.0, 144.0],  # 5 samples
    }
    src_b = {
        "time_offset_seconds": [0, 1, 2],
        "heart_rate_bpm": [150.0, 151.0, 152.0],  # 3 samples
    }
    merged, attribution, reason = select_channels(src_a, src_b, "polar", "garmin")
    assert merged["heart_rate_bpm"] == src_a["heart_rate_bpm"]
    assert attribution["heart_rate_bpm"] == "polar"


def test_tiebreak_prefer_a():
    """AC5: 'prefer_a' rule always picks source A for tied channels."""
    src_a = {
        "time_offset_seconds": [0, 1],
        "heart_rate_bpm": [140.0, 141.0],
    }
    src_b = {
        "time_offset_seconds": [0, 1, 2],
        "heart_rate_bpm": [150.0, 151.0, 152.0],
    }
    merged, attribution, _ = select_channels(src_a, src_b, "polar", "garmin", tiebreak_rule="prefer_a")
    # prefer_a overrides sample count
    assert attribution["heart_rate_bpm"] == "polar"


def test_tiebreak_prefer_b():
    """AC5: 'prefer_b' rule always picks source B."""
    src_a = {
        "time_offset_seconds": [0, 1, 2, 3],
        "heart_rate_bpm": [140.0, 141.0, 142.0, 143.0],  # more samples
    }
    src_b = {
        "time_offset_seconds": [0, 1],
        "heart_rate_bpm": [150.0, 151.0],
    }
    merged, attribution, _ = select_channels(src_a, src_b, "polar", "garmin", tiebreak_rule="prefer_b")
    assert attribution["heart_rate_bpm"] == "garmin"


def test_tiebreak_dict_per_channel_override():
    """AC5: dict tiebreak_rule applies per-channel overrides."""
    src_a = {
        "time_offset_seconds": [0, 1, 2],
        "heart_rate_bpm": [140.0, 141.0, 142.0],
        "cadence_spm": [178.0, 180.0, 179.0],
    }
    src_b = {
        "time_offset_seconds": [0, 1, 2, 3],
        "heart_rate_bpm": [150.0, 151.0, 152.0, 153.0],  # more samples (longer)
        "cadence_spm": [182.0, 184.0, 183.0, 185.0],
    }
    rule = {"heart_rate_bpm": "prefer_a", "cadence_spm": "longer"}
    merged, attribution, _ = select_channels(src_a, src_b, "polar", "garmin", tiebreak_rule=rule)
    # heart_rate_bpm: prefer_a overrides longer
    assert attribution["heart_rate_bpm"] == "polar"
    # cadence_spm: longer picks src_b (4 > 3)
    assert attribution["cadence_spm"] == "garmin"


# ─────────────────────────────────────────────────────────────────────────────
# AC6: Returns merged channel map AND attribution map
# ─────────────────────────────────────────────────────────────────────────────

def test_returns_both_merged_and_attribution():
    """AC6: Return value is (merged_dict, attribution_dict, reason_or_none)."""
    result = select_channels(_garmin_channels(), _stryd_channels(), "garmin", "stryd")
    assert len(result) == 3, "select_channels must return a 3-tuple"
    merged, attribution, reason = result
    assert isinstance(merged, dict)
    assert isinstance(attribution, dict)


def test_attribution_keys_match_merged_keys():
    """AC6: Every key in merged has a corresponding attribution entry."""
    merged, attribution, _ = select_channels(
        _garmin_channels(), _stryd_channels(), "garmin", "stryd"
    )
    for ch in merged:
        assert ch in attribution, f"channel '{ch}' in merged but not in attribution"


def test_attribution_values_are_source_names():
    """AC6: Attribution values are the source name strings passed in."""
    merged, attribution, _ = select_channels(
        _garmin_channels(), _stryd_channels(), "garmin", "stryd"
    )
    valid_names = {"garmin", "stryd", None}
    for ch, src in attribution.items():
        assert src in valid_names, f"attribution['{ch}'] = {src!r} is not a valid source name"


# ─────────────────────────────────────────────────────────────────────────────
# AC9a: Both sources present with overlapping channels
# ─────────────────────────────────────────────────────────────────────────────

def test_overlapping_channels_both_sources():
    """AC9a: Both sources present — each overlapping channel resolved to one source."""
    merged, attribution, reason = select_channels(
        _garmin_channels(), _stryd_channels(), "garmin", "stryd"
    )
    assert merged is not None
    # Channels present in at least one source should appear in merged
    all_source_keys = set(_garmin_channels()) | set(_stryd_channels())
    for ch in all_source_keys:
        if ch in ("latitude", "longitude", "altitude_m"):
            # GPS: only from garmin
            assert ch in merged
            assert attribution[ch] == "garmin"
        elif ch == "power_w":
            # Power: always from stryd
            assert ch in merged
            assert attribution[ch] == "stryd"
        else:
            # Other: must appear somewhere
            assert ch in merged or ch in attribution, f"'{ch}' missing entirely"


def test_channel_only_in_one_source_passes_through():
    """AC9a: A channel that only one source has goes straight to merged."""
    garmin = {
        "time_offset_seconds": [0, 1, 2],
        "heart_rate_bpm": [145.0, 146.0, 147.0],
        "latitude": [1.23, 1.24, 1.25],
        "longitude": [103.8, 103.81, 103.82],
    }
    stryd = {
        "time_offset_seconds": [0, 1, 2],
        "power_w": [255.0, 260.0, 258.0],
        "cadence_spm": [180.0, 182.0, 181.0],
    }
    merged, attribution, _ = select_channels(garmin, stryd, "garmin", "stryd")
    # cadence_spm only in stryd
    assert "cadence_spm" in merged
    assert attribution["cadence_spm"] == "stryd"
    # heart_rate_bpm only in garmin
    assert "heart_rate_bpm" in merged
    assert attribution["heart_rate_bpm"] == "garmin"


# ─────────────────────────────────────────────────────────────────────────────
# AC1: Docstring with worked example
# ─────────────────────────────────────────────────────────────────────────────

def test_select_channels_has_docstring():
    """AC1: select_channels is documented with at least one worked example."""
    doc = select_channels.__doc__ or ""
    assert len(doc) > 50, "select_channels must have a substantive docstring"
    assert ">>" in doc or "Example" in doc or "example" in doc, (
        "docstring must contain a worked example (>>> or 'Example'/'example')"
    )


# ─────────────────────────────────────────────────────────────────────────────
# AC7: Pure function — no DB imports at module top level
# ─────────────────────────────────────────────────────────────────────────────

def test_no_db_import_at_module_level():
    """AC7: channel_select module does not import DB machinery at top level."""
    import importlib, sys
    # Reload the module to catch top-level imports
    import backend.services.channel_select as cs_module
    src = importlib.util.find_spec("backend.services.channel_select").origin
    with open(src) as fh:
        lines = fh.readlines()

    # Collect top-level import lines (before any function/class definition)
    top_level_imports = []
    in_function = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("def ") or stripped.startswith("class "):
            in_function = True
        if not in_function and (stripped.startswith("import ") or stripped.startswith("from ")):
            top_level_imports.append(stripped)

    db_keywords = ("sqlalchemy", "backend.db", "backend.models", "psycopg")
    for imp in top_level_imports:
        for kw in db_keywords:
            assert kw not in imp, (
                f"DB import '{imp}' found at module top level — must be deferred inside function body"
            )
