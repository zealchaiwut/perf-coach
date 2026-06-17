"""Tests for issue #578: Add pure power-branch running TSS calculation.

Acceptance criteria covered:
  AC-signature   — function accepts (durationSeconds, np, ftpW) or equivalent and returns
                   {tss, method, debug}
  AC-if-formula  — intensity_factor = np / ftpW
  AC-tss-formula — tss = round(durationSeconds * IF * IF / 3600 * 100)
  AC-happy-ftp   — 3600 s at np==ftpW → tss=100, method="power"
  AC-missing-ftp — ftpW absent/null/zero/negative → {tss: null, method: "none", debug.reason present}
  AC-missing-np  — np absent/null → {tss: null, method: "none", debug.reason references normalized_power}
  AC-missing-dur — durationSeconds absent/null/zero/negative → {tss: null, method: "none", debug.reason present}
  AC-debug-keys  — debug on success exposes intensity_factor (float) and duration_hours (float)
  AC-no-db       — function file contains no ORM/SQLAlchemy/query calls
  AC-no-defaults — no substitution for missing inputs; missing always yields null
  AC-types       — tss is int or None; method is "power" or "none"
  AC-uat-1       — 3600 s, np=250, ftpW=250 → tss=100, IF=1.0, duration_hours=1.0
  AC-uat-2       — 3600 s, np=200, ftpW=250 → tss=64, IF=0.8
  AC-uat-3       — 5400 s, np=250, ftpW=250 → tss=150, duration_hours=1.5
"""
import pathlib


from backend.services.running_tss_power import calculate_running_tss_power


# ── AC-happy-ftp: 60-min at FTP → tss=100 ────────────────────────────────────


def test_60min_at_ftp_returns_tss_100():
    """AC-happy-ftp: 3600 s at np==ftpW → tss=100."""
    result = calculate_running_tss_power(duration_seconds=3600, np=250, ftp_w=250)
    assert result["tss"] == 100
    assert result["method"] == "power"


def test_method_is_power_on_success():
    """AC-happy-ftp: method must be 'power' on a successful calculation."""
    result = calculate_running_tss_power(duration_seconds=3600, np=280, ftp_w=280)
    assert result["method"] == "power"


# ── AC-tss-formula: below FTP ─────────────────────────────────────────────────


def test_below_ftp_tss_below_100():
    """AC-tss-formula: np below ftpW → tss strictly less than 100 for 1-hour run."""
    result = calculate_running_tss_power(duration_seconds=3600, np=200, ftp_w=250)
    assert result["tss"] < 100


# ── AC-uat-1: 3600 s, np=250, ftpW=250 ────────────────────────────────────────


def test_uat_1_full_values():
    """AC-uat-1: 3600 s, np=250, ftpW=250 → tss=100, IF=1.0, duration_hours=1.0."""
    result = calculate_running_tss_power(duration_seconds=3600, np=250, ftp_w=250)
    assert result["tss"] == 100
    assert result["method"] == "power"
    assert abs(result["debug"]["intensity_factor"] - 1.0) < 1e-9
    assert abs(result["debug"]["duration_hours"] - 1.0) < 1e-9


# ── AC-uat-2: 3600 s, np=200, ftpW=250 → tss=64 ─────────────────────────────


def test_uat_2_below_ftp():
    """AC-uat-2: 3600 s at np=200, ftpW=250 → tss=64, IF=0.8."""
    result = calculate_running_tss_power(duration_seconds=3600, np=200, ftp_w=250)
    # IF = 200/250 = 0.8; TSS = 3600 * 0.64 / 3600 * 100 = 64
    assert result["tss"] == 64
    assert abs(result["debug"]["intensity_factor"] - 0.8) < 1e-9


# ── AC-uat-3: 5400 s at FTP → tss=150 ───────────────────────────────────────


def test_uat_3_90min_at_ftp():
    """AC-uat-3: 5400 s at np==ftpW → tss=150, duration_hours=1.5."""
    result = calculate_running_tss_power(duration_seconds=5400, np=250, ftp_w=250)
    assert result["tss"] == 150
    assert abs(result["debug"]["duration_hours"] - 1.5) < 1e-9


# ── AC-missing-ftp: ftpW absent/null/zero/negative ───────────────────────────


def test_ftp_w_none_returns_null_tss():
    """AC-missing-ftp: ftp_w=None → tss=None."""
    result = calculate_running_tss_power(duration_seconds=3600, np=250, ftp_w=None)
    assert result["tss"] is None
    assert result["method"] == "none"


def test_ftp_w_zero_returns_null_tss():
    """AC-missing-ftp: ftp_w=0 → tss=None."""
    result = calculate_running_tss_power(duration_seconds=3600, np=250, ftp_w=0)
    assert result["tss"] is None
    assert result["method"] == "none"


def test_ftp_w_negative_returns_null_tss():
    """AC-missing-ftp: ftp_w<0 → tss=None."""
    result = calculate_running_tss_power(duration_seconds=3600, np=250, ftp_w=-10)
    assert result["tss"] is None
    assert result["method"] == "none"


def test_ftp_w_missing_debug_reason_is_human_readable():
    """AC-missing-ftp: debug.reason is a non-empty string referencing ftp_w."""
    result = calculate_running_tss_power(duration_seconds=3600, np=250, ftp_w=None)
    reason = result["debug"]["reason"]
    assert isinstance(reason, str)
    assert len(reason) > 0
    assert "ftp" in reason.lower() or "ftp_w" in reason.lower()


# ── AC-missing-np: np absent/null ─────────────────────────────────────────────


def test_np_none_returns_null_tss():
    """AC-missing-np: np=None → tss=None."""
    result = calculate_running_tss_power(duration_seconds=3600, np=None, ftp_w=250)
    assert result["tss"] is None
    assert result["method"] == "none"


def test_np_none_debug_reason_references_normalized_power():
    """AC-missing-np: debug.reason references normalized power."""
    result = calculate_running_tss_power(duration_seconds=3600, np=None, ftp_w=250)
    reason = result["debug"]["reason"]
    assert isinstance(reason, str)
    assert "normalized" in reason.lower() or "power" in reason.lower() or "np" in reason.lower()


# ── AC-missing-dur: durationSeconds absent/null/zero/negative ─────────────────


def test_duration_none_returns_null_tss():
    """AC-missing-dur: duration_seconds=None → tss=None."""
    result = calculate_running_tss_power(duration_seconds=None, np=250, ftp_w=250)
    assert result["tss"] is None
    assert result["method"] == "none"


def test_duration_zero_returns_null_tss():
    """AC-missing-dur: duration_seconds=0 → tss=None."""
    result = calculate_running_tss_power(duration_seconds=0, np=250, ftp_w=250)
    assert result["tss"] is None
    assert result["method"] == "none"


def test_duration_negative_returns_null_tss():
    """AC-missing-dur: duration_seconds<0 → tss=None."""
    result = calculate_running_tss_power(duration_seconds=-60, np=250, ftp_w=250)
    assert result["tss"] is None
    assert result["method"] == "none"


def test_duration_missing_debug_reason_references_duration():
    """AC-missing-dur: debug.reason references duration."""
    result = calculate_running_tss_power(duration_seconds=0, np=250, ftp_w=250)
    reason = result["debug"]["reason"]
    assert isinstance(reason, str)
    assert "duration" in reason.lower()


# ── AC-debug-keys: success exposes intensity_factor and duration_hours ─────────


def test_debug_exposes_intensity_factor_on_success():
    """AC-debug-keys: debug.intensity_factor is a float on success."""
    result = calculate_running_tss_power(duration_seconds=3600, np=250, ftp_w=250)
    assert "intensity_factor" in result["debug"]
    assert isinstance(result["debug"]["intensity_factor"], float)


def test_debug_exposes_duration_hours_on_success():
    """AC-debug-keys: debug.duration_hours is a float on success."""
    result = calculate_running_tss_power(duration_seconds=3600, np=250, ftp_w=250)
    assert "duration_hours" in result["debug"]
    assert isinstance(result["debug"]["duration_hours"], float)


def test_debug_intensity_factor_is_unrounded():
    """AC-debug-keys: intensity_factor in debug is the raw float, not rounded."""
    result = calculate_running_tss_power(duration_seconds=3600, np=200, ftp_w=250)
    # 200/250 = 0.8 exactly; verify it's stored as float
    assert abs(result["debug"]["intensity_factor"] - 0.8) < 1e-9


def test_debug_duration_hours_is_unrounded():
    """AC-debug-keys: duration_hours in debug is raw float (e.g. 1800 s → 0.5)."""
    result = calculate_running_tss_power(duration_seconds=1800, np=250, ftp_w=250)
    assert abs(result["debug"]["duration_hours"] - 0.5) < 1e-9


# ── AC-types: return shape ────────────────────────────────────────────────────


def test_tss_is_integer_on_success():
    """AC-types: tss is a whole integer (not float) on success."""
    result = calculate_running_tss_power(duration_seconds=3600, np=250, ftp_w=250)
    assert isinstance(result["tss"], int)


def test_result_always_has_tss_method_debug_keys():
    """AC-types: result always contains tss, method, debug."""
    for kwargs in [
        {"duration_seconds": 3600, "np": 250, "ftp_w": 250},
        {"duration_seconds": 3600, "np": 250, "ftp_w": None},
        {"duration_seconds": 3600, "np": None, "ftp_w": 250},
        {"duration_seconds": 0, "np": 250, "ftp_w": 250},
    ]:
        result = calculate_running_tss_power(**kwargs)
        assert "tss" in result
        assert "method" in result
        assert "debug" in result


# ── AC-no-db: function file must contain no ORM calls ─────────────────────────


def test_function_file_has_no_orm_imports():
    """AC-no-db: running_tss_power.py must not import SQLAlchemy or any ORM."""
    src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "services" / "running_tss_power.py"
    code = src.read_text()
    assert "sqlalchemy" not in code.lower()
    assert "from backend.db" not in code
    assert "from backend.models" not in code


def test_function_file_has_no_session_or_query_calls():
    """AC-no-db: running_tss_power.py must not call db.execute, session.query, etc."""
    src = pathlib.Path(__file__).resolve().parents[1] / "backend" / "services" / "running_tss_power.py"
    code = src.read_text()
    assert "db.execute" not in code
    assert "session.query" not in code
    assert ".fetchone" not in code
    assert ".fetchall" not in code
