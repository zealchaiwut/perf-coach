"""Tests for issue #582: Persist and expose computed running TSS on workouts.

Acceptance criteria covered:
  AC1  - thin caller persist_running_tss exists, importable, loads workout/splits/prefs
         from DB, delegates to compute_running_tss, writes result back
  AC2  - only writes computed TSS to workout.tss when field is currently null
  AC3  - when manual TSS exists, computed TSS still derived and returned alongside
  AC4  - TSS rounded to whole number before persistence or serialisation
  AC5  - tss_method persisted alongside TSS value
  AC6  - GET /api/workouts/{id}/full includes tss and tss_method in response body
  AC7  - TSS recomputed when workout metrics, splits, or user threshold values change
  AC8  - golden fixture expected-outputs updated with non-null TSS and method string
  AC9  - no hardcoded threshold literals in persist_running_tss
"""
import inspect
import json
import pathlib
import types
import uuid

import pytest

FIXTURES_DIR = pathlib.Path(__file__).parent / "fixtures"
EXPECTED_PATH = FIXTURES_DIR / "golden_run_expected.json"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _workout_ns(tss=None, np=None, avg_hr=None, distance_km=None,
                duration_seconds=2700, workout_type="Run", user_id=None):
    return types.SimpleNamespace(
        id=uuid.uuid4(),
        user_id=user_id or uuid.uuid4(),
        tss=tss,
        tss_source="manual" if tss is not None else None,
        tss_method=None,
        np=np,
        avg_hr=avg_hr,
        distance_km=distance_km,
        duration_seconds=duration_seconds,
        workout_type=workout_type,
    )


def _split_ns(duration_seconds, distance_km, avg_hr=None):
    return types.SimpleNamespace(
        duration_seconds=duration_seconds,
        distance_km=distance_km,
        avg_hr=avg_hr,
    )


def _prefs_ns(ftp_w=None, threshold_pace_seconds_per_km=None, threshold_hr=None):
    return types.SimpleNamespace(
        ftp_w=ftp_w,
        threshold_pace_seconds_per_km=threshold_pace_seconds_per_km,
        threshold_hr=threshold_hr,
    )


class _MockQuery:
    def __init__(self, results):
        self._results = results

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self._results[0] if self._results else None

    def all(self):
        return self._results


class _MockSession:
    def __init__(self, workout, splits, prefs):
        self._workout = workout
        self._splits = splits
        self._prefs = prefs

    def get(self, model, workout_id):
        return self._workout

    def query(self, model):
        model_name = getattr(model, "__name__", str(model))
        if "WorkoutSplit" in model_name or "Split" in model_name:
            return _MockQuery(self._splits)
        if "UserPreferences" in model_name or "Preferences" in model_name:
            return _MockQuery([self._prefs] if self._prefs else [])
        return _MockQuery([])


# ── AC1: persist_running_tss is importable and callable ──────────────────────

def test_persist_running_tss_is_importable():
    """AC1: persist_running_tss exists and is importable from backend.services.tss."""
    from backend.services.tss import persist_running_tss
    assert callable(persist_running_tss)


def test_persist_running_tss_accepts_workout_id_and_session():
    """AC1: function signature accepts workout_id and session parameters."""
    from backend.services.tss import persist_running_tss
    sig = inspect.signature(persist_running_tss)
    params = list(sig.parameters.keys())
    assert "workout_id" in params
    assert "session" in params


def test_persist_running_tss_returns_dict_with_four_keys():
    """AC1: function returns compute_running_tss result dict (tss, method, partial, debug)."""
    from backend.services.tss import persist_running_tss

    workout = _workout_ns(np=280, duration_seconds=3600)
    splits = []
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, splits, prefs)

    result = persist_running_tss(workout_id=workout.id, session=session)
    assert isinstance(result, dict)
    assert "tss" in result
    assert "method" in result


# ── AC2: only writes computed TSS when workout.tss is null ───────────────────

def test_writes_tss_when_workout_tss_is_null():
    """AC2: persist_running_tss sets workout.tss when it is currently null."""
    from backend.services.tss import persist_running_tss

    workout = _workout_ns(tss=None, np=280, duration_seconds=3600)
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, [], prefs)

    persist_running_tss(workout_id=workout.id, session=session)

    assert workout.tss is not None
    assert workout.tss == 100


def test_does_not_overwrite_manual_tss():
    """AC2: persist_running_tss does NOT overwrite workout.tss when already set."""
    from backend.services.tss import persist_running_tss

    workout = _workout_ns(tss=75, np=280, duration_seconds=3600)
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, [], prefs)

    persist_running_tss(workout_id=workout.id, session=session)

    assert workout.tss == 75, "manual TSS must not be overwritten"


def test_does_not_overwrite_manual_tss_even_with_different_computed():
    """AC2: manual TSS=50 stays 50 even when computation yields a different value."""
    from backend.services.tss import persist_running_tss

    workout = _workout_ns(tss=50, np=140, duration_seconds=3600)
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, [], prefs)

    persist_running_tss(workout_id=workout.id, session=session)

    assert workout.tss == 50


# ── AC3: computed TSS returned even when manual TSS exists ───────────────────

def test_returns_computed_tss_when_manual_tss_set():
    """AC3: return value includes computed tss even when workout.tss is manually set."""
    from backend.services.tss import persist_running_tss

    workout = _workout_ns(tss=75, np=280, duration_seconds=3600)
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, [], prefs)

    result = persist_running_tss(workout_id=workout.id, session=session)

    assert result["tss"] == 100, "computed tss=100 returned for comparison"


def test_returns_computed_method_when_manual_tss_set():
    """AC3: return value includes computed method even when workout.tss is manually set."""
    from backend.services.tss import persist_running_tss

    workout = _workout_ns(tss=75, np=280, duration_seconds=3600)
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, [], prefs)

    result = persist_running_tss(workout_id=workout.id, session=session)

    assert result["method"] == "power"


# ── AC4: TSS rounded to whole number ─────────────────────────────────────────

def test_persisted_tss_is_integer():
    """AC4: workout.tss is set to a whole integer."""
    from backend.services.tss import persist_running_tss

    workout = _workout_ns(tss=None, np=268, duration_seconds=2700)
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, [], prefs)

    persist_running_tss(workout_id=workout.id, session=session)

    assert isinstance(workout.tss, int), f"expected int, got {type(workout.tss)}"


def test_returned_tss_is_integer():
    """AC4: returned tss is a whole integer."""
    from backend.services.tss import persist_running_tss

    workout = _workout_ns(tss=None, np=280, duration_seconds=3600)
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, [], prefs)

    result = persist_running_tss(workout_id=workout.id, session=session)

    assert isinstance(result["tss"], int)


# ── AC5: tss_method persisted alongside TSS ──────────────────────────────────

def test_tss_method_written_when_no_manual_tss():
    """AC5: workout.tss_method is set when computed TSS is written."""
    from backend.services.tss import persist_running_tss

    workout = _workout_ns(tss=None, np=280, duration_seconds=3600)
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, [], prefs)

    persist_running_tss(workout_id=workout.id, session=session)

    assert workout.tss_method == "power"


def test_tss_method_written_even_when_manual_tss_set():
    """AC5: workout.tss_method is also set when manual TSS protects workout.tss."""
    from backend.services.tss import persist_running_tss

    workout = _workout_ns(tss=75, np=280, duration_seconds=3600)
    prefs = _prefs_ns(ftp_w=280)
    session = _MockSession(workout, [], prefs)

    persist_running_tss(workout_id=workout.id, session=session)

    assert workout.tss_method == "power"


def test_tss_method_reflects_pace_when_no_power():
    """AC5: tss_method is 'pace' when computation falls through to pace method."""
    from backend.services.tss import persist_running_tss

    splits = [_split_ns(duration_seconds=3600, distance_km=12.0)]
    workout = _workout_ns(tss=None, duration_seconds=3600, distance_km=12.0)
    prefs = _prefs_ns(threshold_pace_seconds_per_km=300)
    session = _MockSession(workout, splits, prefs)

    persist_running_tss(workout_id=workout.id, session=session)

    assert workout.tss_method == "pace"


def test_tss_method_reflects_hr_when_only_hr_prefs():
    """AC5: tss_method is 'hr' when only HR threshold is available."""
    from backend.services.tss import persist_running_tss

    workout = _workout_ns(tss=None, avg_hr=170, duration_seconds=3600)
    prefs = _prefs_ns(threshold_hr=170)
    session = _MockSession(workout, [], prefs)

    persist_running_tss(workout_id=workout.id, session=session)

    assert workout.tss_method == "hr"


# ── AC6: GET /api/workouts/{id}/full response includes tss and tss_method ────

def test_full_endpoint_source_includes_tss_fields():
    """AC6: main.py get_workout_full response dict must include tss and tss_method."""
    src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
    code = src.read_text()

    assert '"tss_method"' in code, "response must include tss_method"
    assert '"tss"' in code, "response must include tss"

    assert "get_workout_full" in code, "get_workout_full endpoint must exist"


def test_full_endpoint_returns_authoritative_tss():
    """AC6: get_workout_full uses workout.tss (manual if set) as authoritative value."""
    src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
    code = src.read_text()
    func_start = code.find("def get_workout_full")
    func_body = code[func_start:func_start + 6000]
    assert "workout.tss" in func_body, (
        "get_workout_full must reference workout.tss for the authoritative value"
    )


# ── AC7: recomputation on change ─────────────────────────────────────────────

def test_persist_running_tss_called_after_workout_create():
    """AC7: main.py post_workout must call persist_running_tss or equivalent after commit."""
    src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
    code = src.read_text()
    func_start = code.find("def post_workout")
    # Slice to the next top-level def, not a fixed character window. A window
    # silently truncates the moment anyone adds a field to the handler, turning
    # an unrelated change into a false failure here.
    func_end = code.find("\ndef ", func_start + 1)
    func_body = code[func_start:func_end if func_end != -1 else None]
    assert "persist_running_tss" in func_body or "_persist_running_tss" in func_body, (
        "post_workout must call persist_running_tss to recompute TSS on creation"
    )


def test_persist_running_tss_called_after_workout_patch():
    """AC7: main.py patch_workout must call persist_running_tss after metric changes."""
    src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
    code = src.read_text()
    func_start = code.find("def patch_workout")
    func_end = code.find("\ndef ", func_start + 1)
    func_body = code[func_start:func_end if func_end != -1 else None]
    assert "persist_running_tss" in func_body or "_persist_running_tss" in func_body, (
        "patch_workout must call persist_running_tss to recompute TSS on metrics change"
    )


def test_persist_running_tss_called_after_splits_update():
    """AC7: main.py replace_splits must call persist_running_tss after splits change."""
    src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
    code = src.read_text()
    func_start = code.find("def replace_splits")
    func_end = code.find("\ndef ", func_start + 1)
    func_body = code[func_start:func_end if func_end != -1 else None]
    assert "persist_running_tss" in func_body or "_persist_running_tss" in func_body, (
        "replace_splits must call persist_running_tss to recompute TSS when splits change"
    )


def test_user_running_tss_recomputed_after_threshold_change():
    """AC7: patch_user_preferences calls recompute function when threshold fields change."""
    src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "main.py"
    code = src.read_text()
    func_start = code.find("def patch_user_preferences")
    func_body = code[func_start:func_start + 10000]
    assert "recompute_user_running_tss" in func_body or "_recompute_user_running_tss" in func_body, (
        "patch_user_preferences must recompute running TSS for all user workouts "
        "when threshold values change"
    )


# ── AC8: golden fixture updated with TSS value ────────────────────────────────

def test_golden_expected_tss_is_not_placeholder():
    """AC8: golden_run_expected.json tss.value must not be null (placeholder removed)."""
    with EXPECTED_PATH.open() as f:
        expected = json.load(f)

    tss_section = expected.get("tss", {})
    assert tss_section.get("value") is not None, (
        "golden_run_expected.json tss.value must not be null — "
        "implement and verify the expected TSS value for the golden fixture"
    )


def test_golden_expected_tss_is_integer():
    """AC8: golden_run_expected.json tss.value must be a whole integer."""
    with EXPECTED_PATH.open() as f:
        expected = json.load(f)

    tss_val = expected.get("tss", {}).get("value")
    assert isinstance(tss_val, int), (
        f"golden_run_expected.json tss.value must be an integer, got {type(tss_val)}"
    )


def test_golden_expected_tss_method_is_valid():
    """AC8: golden_run_expected.json tss.method must be a valid method string."""
    with EXPECTED_PATH.open() as f:
        expected = json.load(f)

    method = expected.get("tss", {}).get("method")
    assert method in {"power", "pace", "hr"}, (
        f"golden_run_expected.json tss.method must be 'power', 'pace', or 'hr'; got {method!r}"
    )


def test_golden_tss_matches_expected_value():
    """AC8: compute_running_tss on the golden fixture matches the expected value."""
    from backend.services.tss import compute_running_tss

    with (FIXTURES_DIR / "golden_run.json").open() as f:
        fixture = json.load(f)

    with EXPECTED_PATH.open() as f:
        expected = json.load(f)

    tss_expected = expected.get("tss", {})
    expected_value = tss_expected.get("value")
    expected_method = tss_expected.get("method")
    fixture_prefs = tss_expected.get("fixture_prefs", {})

    if expected_value is None:
        pytest.skip("tss.value is still a placeholder — implement AC8 first")

    prefs = types.SimpleNamespace(
        ftp_w=fixture_prefs.get("ftp_w"),
        threshold_pace_seconds_per_km=fixture_prefs.get("threshold_pace_seconds_per_km"),
        threshold_hr=fixture_prefs.get("threshold_hr"),
    )

    laps = fixture.get("laps", [])
    splits = [
        types.SimpleNamespace(
            duration_seconds=lap["duration_seconds"],
            distance_km=lap["distance_km"],
            avg_hr=round(lap["avg_hr_bpm"]) if "avg_hr_bpm" in lap else None,
        )
        for lap in laps
    ]

    from backend.services.normalized_power import compute_normalized_power
    power_stream = fixture["streams"]["power_w"]
    sample_interval = fixture["metadata"]["sample_interval_seconds"]
    np_val, _ = compute_normalized_power(power_stream, sample_interval)

    workout = types.SimpleNamespace(
        np=np_val,
        avg_hr=None,
        distance_km=fixture["metadata"]["total_distance_km"],
        duration_seconds=fixture["metadata"]["duration_seconds"],
    )

    result = compute_running_tss(workout, splits, prefs)

    assert result["tss"] == expected_value, (
        f"golden fixture TSS mismatch: computed {result['tss']}, expected {expected_value}"
    )
    assert result["method"] == expected_method, (
        f"golden fixture method mismatch: computed {result['method']}, expected {expected_method!r}"
    )


# ── AC9: no hardcoded thresholds in persist_running_tss ──────────────────────

def test_no_hardcoded_thresholds_in_persist_running_tss():
    """AC9: persist_running_tss source must not contain numeric threshold literals."""
    import ast
    src_path = pathlib.Path(__file__).resolve().parents[1] / "backend" / "services" / "tss.py"
    src = src_path.read_text()

    tree = ast.parse(src)

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "persist_running_tss":
            for child in ast.walk(node):
                if isinstance(child, ast.Constant) and isinstance(child.value, (int, float)):
                    # Allow 0 and None-equivalent checks
                    assert child.value in (0, 0.0, 1, None), (
                        f"persist_running_tss contains hardcoded numeric literal {child.value!r} "
                        "— all thresholds must come from user preferences"
                    )
            break
