"""Tests for issue #557: Add exc_info=True to autofill recompute warning in duplicate_workout (runs against UAT)"""
import os
import re


# --- Acceptance Criteria ---

def test_autofill_exc_info__logging_includes_exc_info_true():
    """AC: The except block in _recompute_autofill inside duplicate_workout includes exc_info=True in its warning() call"""
    # This is a static code inspection test.
    # We verify by reading backend/main.py directly and checking the logging call.

    with open(os.path.join(os.path.dirname(__file__), "..", "backend", "main.py"), "r") as f:
        content = f.read()

    # Find the duplicate_workout function
    match = re.search(r"def duplicate_workout\(.*?\n(.*?)(?=\ndef |\Z)", content, re.DOTALL)
    assert match, "Could not find duplicate_workout function"
    func_body = match.group(1)

    # Find the _recompute_autofill except block
    # Look for: except Exception as _af_exc: followed by logging.getLogger...warning
    except_pattern = r"except Exception as _af_exc:.*?_logging\.getLogger\(__name__\)\.warning\((.*?)\)"
    except_match = re.search(except_pattern, func_body, re.DOTALL)
    assert except_match, "Could not find _recompute_autofill except block with warning call"

    warning_args = except_match.group(1)

    # Check that exc_info=True is present in the warning call
    assert "exc_info=True" in warning_args, (
        f"exc_info=True not found in _recompute_autofill warning call. "
        f"Found: {warning_args}"
    )


def test_autofill_exc_info__matches_daily_update_pattern():
    """AC: The exc_info=True parameter placement matches the style used at daily_update warning call"""
    with open(os.path.join(os.path.dirname(__file__), "..", "backend", "main.py"), "r") as f:
        content = f.read()

    # Find the duplicate_workout function
    match = re.search(r"def duplicate_workout\(.*?\n(.*?)(?=\ndef |\Z)", content, re.DOTALL)
    assert match, "Could not find duplicate_workout function"
    func_body = match.group(1)

    # Check that both warning calls in duplicate_workout have exc_info=True
    # Look for the pattern: except block followed by .warning(..., exc_info=True)

    # 1. Check daily_update warning has exc_info=True
    daily_pattern = r"except Exception as _exc:.*?\.warning\(\s*\"daily_update failed.*?exc_info=True"
    assert re.search(daily_pattern, func_body, re.DOTALL), (
        "daily_update warning call does not have exc_info=True parameter"
    )

    # 2. Check autofill warning has exc_info=True
    autofill_pattern = r"except Exception as _af_exc:.*?\.warning\(\s*\"autofill recompute failed.*?exc_info=True"
    assert re.search(autofill_pattern, func_body, re.DOTALL), (
        "autofill warning call does not have exc_info=True parameter"
    )


def test_autofill_exc_info__no_other_changes():
    """AC: No other changes are made to the function beyond adding the exc_info=True argument"""
    # This is a verification that the change is minimal.
    # We check that the except block for _recompute_autofill only differs in the exc_info=True addition.

    with open(os.path.join(os.path.dirname(__file__), "..", "backend", "main.py"), "r") as f:
        content = f.read()

    # Verify the except block structure is intact (message format, variable names, etc.)
    match = re.search(
        r"except Exception as _af_exc:.*?_logging\.getLogger\(__name__\)\.warning\(\s*\"autofill recompute failed for user %s week %s: %s\", user\.id, new_date, _af_exc(?:, exc_info=True)?\s*\)",
        content,
        re.DOTALL
    )
    assert match, (
        "Except block structure does not match expected pattern. "
        "The message, variable names, or structure may have changed unexpectedly."
    )
