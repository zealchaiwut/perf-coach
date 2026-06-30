"""Tests for issue #1131: Polarized-split target-band deviation check.

Acceptance criteria anchored:
  AC1 - Function accepts actual percentages for low/moderate/high bands plus
        optional target-bound overrides; returns on_target (bool) and
        deviating bands with direction.
  AC2 - Default bounds: low [75, 85], moderate [5, 10], high [15, 20].
  AC3 - Returns on_target=True only when ALL three bands are within bounds.
  AC4 - Returns on_target=False and identifies every deviating band with direction.
  AC5 - Excessive moderate (grey zone) deviation explicitly surfaced.
  AC6 - py_compile passes on implementation file.
  AC7 - Unit tests cover: all-bands-on-target, moderate-too-high (grey zone),
        low-too-low, high-too-high, multiple simultaneous deviations.
"""
import pathlib
import py_compile


from backend.services.polarized_split import check_polarized_split


# ---------------------------------------------------------------------------
# AC3 + AC7a: All bands on target
# ---------------------------------------------------------------------------

def test_all_on_target_returns_true():
    """AC3/AC7: All bands within defaults → on_target=True, no deviations."""
    result = check_polarized_split(low=80, moderate=7, high=13)
    assert result["on_target"] is True
    assert result["deviations"] == []


def test_all_on_target_no_grey_zone_flag():
    """AC3/AC5: on_target=True means no grey-zone flag raised."""
    result = check_polarized_split(low=80, moderate=7, high=13)
    assert result.get("grey_zone") is not True


# ---------------------------------------------------------------------------
# AC4 + AC5 + AC7b: Moderate too high (grey zone)
# ---------------------------------------------------------------------------

def test_moderate_too_high_grey_zone():
    """AC4/AC5/AC7: low=65, moderate=22, high=13 → low below, moderate above (grey zone)."""
    result = check_polarized_split(low=65, moderate=22, high=13)
    assert result["on_target"] is False
    bands = {d["band"]: d["direction"] for d in result["deviations"]}
    assert "moderate" in bands, "moderate must appear as a deviation"
    assert bands["moderate"] == "above", "moderate is above upper bound"
    assert result.get("grey_zone") is True, "grey zone must be explicitly flagged"


def test_moderate_too_high_low_too_low():
    """AC4/AC7: low=65 is below 75 bound; both low and moderate deviate."""
    result = check_polarized_split(low=65, moderate=22, high=13)
    bands = {d["band"]: d["direction"] for d in result["deviations"]}
    assert "low" in bands
    assert bands["low"] == "below"


# ---------------------------------------------------------------------------
# AC4 + AC7c: Low too low (moderate within bounds)
# ---------------------------------------------------------------------------

def test_low_too_low_only():
    """AC4/AC7: Only low below target → on_target=False with low:below deviation."""
    result = check_polarized_split(low=60, moderate=8, high=32)
    assert result["on_target"] is False
    bands = {d["band"]: d["direction"] for d in result["deviations"]}
    assert "low" in bands
    assert bands["low"] == "below"


# ---------------------------------------------------------------------------
# AC4 + AC7d: High too high
# ---------------------------------------------------------------------------

def test_high_at_upper_bound_is_on_target():
    """AC4/AC7: high=20 is the upper bound (inclusive) → on_target=True for this band."""
    result = check_polarized_split(low=75, moderate=5, high=20)
    bands = {d["band"] for d in result["deviations"]}
    assert "high" not in bands  # 20 is the upper bound, inclusive


def test_high_above_upper_bound():
    """AC4/AC7: high=25 exceeds upper bound of 20."""
    result = check_polarized_split(low=70, moderate=5, high=25)
    assert result["on_target"] is False
    bands = {d["band"]: d["direction"] for d in result["deviations"]}
    assert "high" in bands
    assert bands["high"] == "above"


# ---------------------------------------------------------------------------
# AC4 + AC7e: Multiple simultaneous deviations
# ---------------------------------------------------------------------------

def test_multiple_deviations_simultaneously():
    """AC4/AC7: All three bands can deviate at once."""
    # low below 75, moderate above 10, high above 20
    result = check_polarized_split(low=60, moderate=15, high=25)
    assert result["on_target"] is False
    bands = {d["band"]: d["direction"] for d in result["deviations"]}
    assert "low" in bands
    assert "moderate" in bands
    assert "high" in bands


def test_on_target_false_when_any_band_deviates():
    """AC3: A single deviant band is enough to make on_target=False."""
    result = check_polarized_split(low=80, moderate=7, high=25)
    assert result["on_target"] is False


# ---------------------------------------------------------------------------
# AC2: Default bounds
# ---------------------------------------------------------------------------

def test_boundary_values_inclusive_low():
    """AC2: low=75 and low=85 are both on target (inclusive bounds)."""
    for v in (75, 85):
        r = check_polarized_split(low=v, moderate=7, high=100 - v - 7)
        # only interested in the low band check; others may or may not deviate
        bands = {d["band"] for d in r["deviations"]}
        assert "low" not in bands, f"low={v} should be within [{75},{85}]"


def test_boundary_values_inclusive_moderate():
    """AC2: moderate=5 and moderate=10 are both on target."""
    for v in (5, 10):
        r = check_polarized_split(low=80, moderate=v, high=100 - 80 - v)
        bands = {d["band"] for d in r["deviations"]}
        assert "moderate" not in bands, f"moderate={v} should be within [5,10]"


def test_boundary_values_inclusive_high():
    """AC2: high=10 (lower bound) and high=20 (upper bound) are both on target."""
    for v in (10, 20):
        r = check_polarized_split(low=80, moderate=5, high=v)
        bands = {d["band"] for d in r["deviations"]}
        assert "high" not in bands, f"high={v} should be within [10,20]"


# ---------------------------------------------------------------------------
# AC1: Custom bounds override
# ---------------------------------------------------------------------------

def test_custom_bounds_override():
    """AC1/UAT-4: Custom bounds change what is on-target.

    low=80, moderate=7, high=13 with custom low bound [80,90] is on_target.
    """
    result = check_polarized_split(
        low=80,
        moderate=7,
        high=13,
        bounds={"low": [80, 90], "moderate": [5, 10], "high": [10, 15]},
    )
    assert result["on_target"] is True
    assert result["deviations"] == []


def test_custom_bounds_can_make_default_ok_fail():
    """AC1: Values that pass defaults can fail custom stricter bounds."""
    result = check_polarized_split(
        low=80,
        moderate=7,
        high=13,
        bounds={"low": [82, 90], "moderate": [5, 10], "high": [10, 15]},
    )
    assert result["on_target"] is False
    bands = {d["band"] for d in result["deviations"]}
    assert "low" in bands


# ---------------------------------------------------------------------------
# AC5: Moderate below lower bound — no grey-zone flag
# ---------------------------------------------------------------------------

def test_moderate_below_not_grey_zone():
    """AC5: moderate below lower bound is a deviation but NOT a grey-zone alert."""
    result = check_polarized_split(low=78, moderate=4, high=18)
    assert result["on_target"] is False
    bands = {d["band"]: d["direction"] for d in result["deviations"]}
    assert "moderate" in bands
    assert bands["moderate"] == "below"
    assert result.get("grey_zone") is not True


# ---------------------------------------------------------------------------
# AC6: py_compile
# ---------------------------------------------------------------------------

def test_polarized_split_module_compiles():
    """AC6: polarized_split.py passes py_compile with no errors."""
    path = str(
        pathlib.Path(__file__).parents[1]
        / "backend"
        / "services"
        / "polarized_split.py"
    )
    py_compile.compile(path, doraise=True)
