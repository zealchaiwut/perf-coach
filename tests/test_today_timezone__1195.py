"""Tests for issue #1195: sessions.js today() uses UTC date, off-by-one in Bangkok timezone"""
import os
import re


# --- Acceptance Criteria ---

def test_today_timezone__today_function_uses_local_date():
    # AC: today() function uses local date, not UTC (not toISOString().slice(0,10))
    sessions_js_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "frontend",
        "js",
        "sessions.js"
    )

    with open(sessions_js_path, "r") as f:
        code = f.read()

    # Verify today() function exists
    assert "function today()" in code, "today() function not found in sessions.js"

    # Extract the today() function body
    match = re.search(r"function today\(\)\s*\{([^}]+)\}", code, re.DOTALL)
    assert match is not None, "Could not parse today() function"

    func_body = match.group(1)

    # Verify the buggy toISOString().slice(0,10) is NOT present
    assert "toISOString()" not in func_body, \
        "Bug still present: today() uses toISOString() (UTC-based)"

    # Verify the fix is in place: local date methods
    has_local_date_fix = (
        "toLocaleDateString" in func_body or
        "getFullYear" in func_body or
        "getMonth" in func_body or
        "getDate" in func_body
    )
    assert has_local_date_fix, \
        "Fix not found: today() should use local date methods (toLocaleDateString, getFullYear/getMonth/getDate, etc.)"


def test_today_timezone__date_input_element_present():
    # AC: Form has a date input element with id="se-date"
    sessions_html_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "frontend",
        "pages",
        "sessions.html"
    )

    with open(sessions_html_path, "r") as f:
        html = f.read()

    # Verify the date input exists
    assert 'id="se-date"' in html, "Session date input (id=se-date) not found"
    assert 'type="date"' in html, "Date input with type=date not found"

    # Verify the input element is properly formed
    match = re.search(r'<input[^>]*id="se-date"[^>]*>', html)
    assert match is not None, "Date input element not properly structured"


def test_today_timezone__form_uses_today_for_default():
    # AC: Form default date is set via today() function (not hardcoded UTC)
    sessions_js_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "frontend",
        "js",
        "sessions.js"
    )

    with open(sessions_js_path, "r") as f:
        code = f.read()

    # Verify that today() is called when showing the form (showForm function)
    # Look for places where today() is used to set the date
    assert re.search(r"\.value\s*=\s*today\(\)", code), \
        "today() function is not being used to set the date input value"

    # Verify the submission also uses the correct format
    assert "session_date" in code, "Submission should include session_date field"
    # Should send date in YYYY-MM-DD format (from the input)
    assert "dateVal" in code or "document.getElementById.*se-date" in code, \
        "Form should read the date from the se-date input element"
