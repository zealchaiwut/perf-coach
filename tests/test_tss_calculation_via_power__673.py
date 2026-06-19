"""Tests for issue #673: Add pure function for TSS calculation via power.

Acceptance criteria covered:
  AC1  — ftp_w comes from user_preferences; pure function has no hardcoded FTP default
  AC2  — function accepts ftp_w, np (normalized power), duration_seconds
  AC3  — intensity_factor = np / ftp_w
  AC4  — tss = (duration_seconds × IF²) / 3600 × 100
  AC5  — 60-min at exactly FTP → tss=100
  AC6  — returns tss (whole int), method="power", debug with intensity_factor and duration_hours
  AC7  — ftp_w missing/null → tss=None, method="none", reason identifies ftp_w
  AC8  — np missing/null → tss=None, method="none", reason identifies np
  AC9  — duration_seconds missing/null → tss=None, method="none", reason identifies duration_seconds
  AC10 — pure function: no DB access, no side effects
  AC11 — docstring includes worked example showing 60-min at FTP → TSS 100
  AC12 — DB access (user_preferences) lives in a separate thin caller function
"""
import inspect
import pathlib
from unittest.mock import MagicMock

from backend.services.running_tss_power import calculate_running_tss_power
from backend.services.running_tss_power_caller import calculate_running_tss_power_for_user


# ── AC5: 60-min at exactly FTP → tss=100 ────────────────────────────────────


def test_ac5_sixty_min_at_ftp_returns_tss_100():
    """AC5: 3600 s at np==ftp_w must return tss=100."""
    result = calculate_running_tss_power(ftp_w=250, np=250, duration_seconds=3600)
    assert result["tss"] == 100


def test_ac5_method_is_power():
    """AC5: method must be 'power' on success."""
    result = calculate_running_tss_power(ftp_w=250, np=250, duration_seconds=3600)
    assert result["method"] == "power"


# ── AC3/AC4: formula verification ───────────────────────────────────────────


def test_ac3_intensity_factor_in_debug():
    """AC3: debug.intensity_factor must equal np / ftp_w."""
    result = calculate_running_tss_power(ftp_w=250, np=200, duration_seconds=3600)
    assert abs(result["debug"]["intensity_factor"] - 0.8) < 1e-9


def test_ac4_tss_formula_below_ftp():
    """AC4: tss = round((duration_seconds × IF²) / 3600 × 100).
    3600 s, np=200, ftp_w=250 → IF=0.8 → tss=round(0.64×100)=64.
    """
    result = calculate_running_tss_power(ftp_w=250, np=200, duration_seconds=3600)
    assert result["tss"] == 64


def test_ac4_tss_formula_above_ftp():
    """AC4: 90-min at FTP → tss=150."""
    result = calculate_running_tss_power(ftp_w=250, np=250, duration_seconds=5400)
    assert result["tss"] == 150


# ── AC6: return shape on success ─────────────────────────────────────────────


def test_ac6_tss_is_whole_integer():
    """AC6: tss is an int (not float) on success."""
    result = calculate_running_tss_power(ftp_w=250, np=250, duration_seconds=3600)
    assert isinstance(result["tss"], int)


def test_ac6_debug_has_intensity_factor_and_duration_hours():
    """AC6: debug exposes intensity_factor and duration_hours."""
    result = calculate_running_tss_power(ftp_w=250, np=250, duration_seconds=3600)
    assert "intensity_factor" in result["debug"]
    assert "duration_hours" in result["debug"]
    assert isinstance(result["debug"]["intensity_factor"], float)
    assert isinstance(result["debug"]["duration_hours"], float)


def test_ac6_duration_hours_correct():
    """AC6: duration_hours = duration_seconds / 3600."""
    result = calculate_running_tss_power(ftp_w=250, np=250, duration_seconds=5400)
    assert abs(result["debug"]["duration_hours"] - 1.5) < 1e-9


# ── UAT step 1 ───────────────────────────────────────────────────────────────


def test_uat1_full_values():
    """UAT-1: ftp_w=250, np=250, duration=3600 → tss=100, IF=1.0, hours=1.0."""
    result = calculate_running_tss_power(ftp_w=250, np=250, duration_seconds=3600)
    assert result["tss"] == 100
    assert result["method"] == "power"
    assert abs(result["debug"]["intensity_factor"] - 1.0) < 1e-9
    assert abs(result["debug"]["duration_hours"] - 1.0) < 1e-9


# ── UAT step 2 ───────────────────────────────────────────────────────────────


def test_uat2_below_ftp():
    """UAT-2: ftp_w=250, np=200, duration=3600 → tss=64, IF=0.8."""
    result = calculate_running_tss_power(ftp_w=250, np=200, duration_seconds=3600)
    assert result["tss"] == 64
    assert abs(result["debug"]["intensity_factor"] - 0.8) < 1e-9


# ── UAT step 3 ───────────────────────────────────────────────────────────────


def test_uat3_90min_at_ftp():
    """UAT-3: ftp_w=250, np=250, duration=5400 → tss=150, hours=1.5."""
    result = calculate_running_tss_power(ftp_w=250, np=250, duration_seconds=5400)
    assert result["tss"] == 150
    assert abs(result["debug"]["duration_hours"] - 1.5) < 1e-9


# ── AC7: ftp_w missing/null ──────────────────────────────────────────────────


def test_ac7_ftp_w_none_returns_null_tss():
    """AC7: ftp_w=None → tss=None, method='none'."""
    result = calculate_running_tss_power(ftp_w=None, np=250, duration_seconds=3600)
    assert result["tss"] is None
    assert result["method"] == "none"


def test_ac7_ftp_w_none_response_has_reason():
    """AC7: missing ftp_w → response contains a non-empty reason string."""
    result = calculate_running_tss_power(ftp_w=None, np=250, duration_seconds=3600)
    reason = result.get("reason") or result.get("debug", {}).get("reason", "")
    assert isinstance(reason, str) and len(reason) > 0


def test_ac7_reason_identifies_ftp_w():
    """AC7: reason string identifies ftp_w as the missing input."""
    result = calculate_running_tss_power(ftp_w=None, np=250, duration_seconds=3600)
    reason = result.get("reason") or result.get("debug", {}).get("reason", "")
    assert "ftp" in reason.lower()


# ── AC8: np missing/null ─────────────────────────────────────────────────────


def test_ac8_np_none_returns_null_tss():
    """AC8: np=None → tss=None, method='none'."""
    result = calculate_running_tss_power(ftp_w=250, np=None, duration_seconds=3600)
    assert result["tss"] is None
    assert result["method"] == "none"


def test_ac8_np_none_response_has_reason():
    """AC8: missing np → response contains a non-empty reason string."""
    result = calculate_running_tss_power(ftp_w=250, np=None, duration_seconds=3600)
    reason = result.get("reason") or result.get("debug", {}).get("reason", "")
    assert isinstance(reason, str) and len(reason) > 0


def test_ac8_reason_identifies_np():
    """AC8: reason string identifies np as the missing input."""
    result = calculate_running_tss_power(ftp_w=250, np=None, duration_seconds=3600)
    reason = result.get("reason") or result.get("debug", {}).get("reason", "")
    assert "np" in reason.lower() or "normalized" in reason.lower() or "power" in reason.lower()


# ── AC9: duration_seconds missing/null ───────────────────────────────────────


def test_ac9_duration_none_returns_null_tss():
    """AC9: duration_seconds=None → tss=None, method='none'."""
    result = calculate_running_tss_power(ftp_w=250, np=250, duration_seconds=None)
    assert result["tss"] is None
    assert result["method"] == "none"


def test_ac9_duration_none_response_has_reason():
    """AC9: missing duration_seconds → response contains a non-empty reason string."""
    result = calculate_running_tss_power(ftp_w=250, np=250, duration_seconds=None)
    reason = result.get("reason") or result.get("debug", {}).get("reason", "")
    assert isinstance(reason, str) and len(reason) > 0


def test_ac9_reason_identifies_duration():
    """AC9: reason string identifies duration_seconds as the missing input."""
    result = calculate_running_tss_power(ftp_w=250, np=250, duration_seconds=None)
    reason = result.get("reason") or result.get("debug", {}).get("reason", "")
    assert "duration" in reason.lower()


# ── AC1: no hardcoded FTP in pure function ───────────────────────────────────


def test_ac1_no_hardcoded_ftp_in_pure_function():
    """AC1: the pure function file must not hardcode a numeric FTP default."""
    src = (
        pathlib.Path(__file__).resolve().parents[1]
        / "backend"
        / "services"
        / "running_tss_power.py"
    )
    code = src.read_text()
    # The guard: FTP_W = <number> as a module-level default is forbidden
    assert "FTP_W = " not in code, "running_tss_power.py must not define FTP_W as a constant"


# ── AC10: no DB access in pure function ──────────────────────────────────────


def test_ac10_no_orm_imports_in_pure_function():
    """AC10: the pure calculate_running_tss_power function must not access the DB.

    The module may have a thin caller with a local import, but the pure function
    itself must contain no ORM or session calls.
    """
    func_src = inspect.getsource(calculate_running_tss_power)
    assert "sqlalchemy" not in func_src.lower()
    assert "from backend.models" not in func_src
    assert "UserPreferences" not in func_src


def test_ac10_pure_function_body_has_no_db_calls():
    """AC10: calculate_running_tss_power body must not query the DB."""
    src = (
        pathlib.Path(__file__).resolve().parents[1]
        / "backend"
        / "services"
        / "running_tss_power.py"
    )
    code = src.read_text()
    # Confirm the pure function's source has no session/query patterns
    func_src = inspect.getsource(calculate_running_tss_power)
    assert "session" not in func_src
    assert ".query(" not in func_src
    assert "UserPreferences" not in func_src


# ── AC11: docstring has worked example ───────────────────────────────────────


def test_ac11_docstring_contains_worked_example():
    """AC11: calculate_running_tss_power docstring includes a worked example."""
    doc = calculate_running_tss_power.__doc__ or ""
    assert len(doc) > 0, "docstring must not be empty"
    # The worked example must show that 60 min at FTP → TSS 100
    assert "100" in doc
    assert "3600" in doc or "60" in doc


# ── AC12: thin caller function exists and reads from user_preferences ─────────


def test_ac12_caller_function_is_callable():
    """AC12: calculate_running_tss_power_for_user must be importable and callable."""
    assert callable(calculate_running_tss_power_for_user)


def test_ac12_caller_queries_user_preferences():
    """AC12: caller must call session.query(UserPreferences) to fetch ftp_w."""
    mock_session = MagicMock()
    mock_prefs = MagicMock()
    mock_prefs.ftp_w = 250
    mock_session.query.return_value.filter.return_value.first.return_value = mock_prefs

    calculate_running_tss_power_for_user(
        session=mock_session,
        user_id=1,
        np=250,
        duration_seconds=3600,
    )

    mock_session.query.assert_called_once()


def test_ac12_caller_passes_ftp_w_from_prefs_to_pure_function():
    """AC12: caller passes the DB-fetched ftp_w to the pure function."""
    mock_session = MagicMock()
    mock_prefs = MagicMock()
    mock_prefs.ftp_w = 250
    mock_session.query.return_value.filter.return_value.first.return_value = mock_prefs

    result = calculate_running_tss_power_for_user(
        session=mock_session,
        user_id=1,
        np=250,
        duration_seconds=3600,
    )

    assert result["tss"] == 100
    assert result["method"] == "power"


def test_ac12_caller_returns_none_tss_when_prefs_missing():
    """AC12: caller returns tss=None when user_preferences row does not exist."""
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.first.return_value = None

    result = calculate_running_tss_power_for_user(
        session=mock_session,
        user_id=1,
        np=250,
        duration_seconds=3600,
    )

    assert result["tss"] is None
    assert result["method"] == "none"


def test_ac12_caller_returns_none_tss_when_ftp_w_null_in_prefs():
    """AC12: caller returns tss=None when ftp_w is null in user_preferences."""
    mock_session = MagicMock()
    mock_prefs = MagicMock()
    mock_prefs.ftp_w = None
    mock_session.query.return_value.filter.return_value.first.return_value = mock_prefs

    result = calculate_running_tss_power_for_user(
        session=mock_session,
        user_id=1,
        np=250,
        duration_seconds=3600,
    )

    assert result["tss"] is None
    assert result["method"] == "none"


def test_ac12_caller_db_access_not_in_pure_function():
    """AC12: the pure function must not import or call the caller's DB logic."""
    func_src = inspect.getsource(calculate_running_tss_power)
    assert "calculate_running_tss_power_for_user" not in func_src
    assert "UserPreferences" not in func_src
    assert "session" not in func_src
