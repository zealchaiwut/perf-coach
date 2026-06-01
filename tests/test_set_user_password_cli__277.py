"""Tests for issue #277: CLI script to set user password by username."""
import importlib.util
import pathlib
import sys
from unittest.mock import MagicMock, patch

import pytest

REPO = pathlib.Path(__file__).parent.parent
SCRIPT = REPO / "scripts" / "set_user_password.py"
README = REPO / "scripts" / "README.md"

SCRIPT_TEXT = SCRIPT.read_text() if SCRIPT.exists() else ""
README_TEXT = README.read_text() if README.exists() else ""


def _load_module():
    spec = importlib.util.spec_from_file_location("set_user_password", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_fake_session(user_result):
    fake_session = MagicMock()
    fake_session.__enter__.return_value = fake_session
    fake_session.execute.return_value.scalar_one_or_none.return_value = user_result
    return fake_session


# ── AC-1: script exists ───────────────────────────────────────────────────────

def test_ac1_script_exists():
    assert SCRIPT.exists(), "scripts/set_user_password.py must exist"


def test_ac1_script_has_docstring():
    assert '"""' in SCRIPT_TEXT or "'''" in SCRIPT_TEXT, \
        "script must have a docstring with usage documentation"


def test_ac1_script_documents_usage():
    assert "set_user_password.py" in SCRIPT_TEXT, \
        "script docstring must reference its own name"
    assert "<username>" in SCRIPT_TEXT or "username" in SCRIPT_TEXT.lower(), \
        "script docstring must document the username argument"


# ── AC-2: getpass — no plaintext echo ─────────────────────────────────────────

def test_ac2_uses_getpass():
    assert "getpass" in SCRIPT_TEXT, \
        "script must use getpass to prompt for password (no echo)"


def test_ac2_imports_getpass_module():
    assert "import getpass" in SCRIPT_TEXT, \
        "script must import the getpass module"


def test_ac2_never_prints_plaintext():
    lower = SCRIPT_TEXT.lower()
    assert "print(plain" not in lower and 'print(password' not in lower, \
        "script must never print the plaintext password"


# ── AC-3: empty password rejection ───────────────────────────────────────────

def test_ac3_checks_empty_password():
    assert "not plain" in SCRIPT_TEXT or 'plain == ""' in SCRIPT_TEXT or \
           "if plain" in SCRIPT_TEXT, \
        "script must check for empty password"


def test_ac3_exits_nonzero_on_empty():
    assert "sys.exit(1)" in SCRIPT_TEXT, \
        "script must call sys.exit(1) on validation failure"


def test_ac3_empty_password_error_message():
    lower = SCRIPT_TEXT.lower()
    assert "empty" in lower or "must not be empty" in lower or \
           "password must" in lower, \
        "script must print a clear error when password is empty"


# ── AC-4: minimum length rejection ───────────────────────────────────────────

def test_ac4_imports_min_password_length():
    assert "MIN_PASSWORD_LENGTH" in SCRIPT_TEXT, \
        "script must import and use MIN_PASSWORD_LENGTH from backend.auth"


def test_ac4_checks_min_length():
    assert "len(plain)" in SCRIPT_TEXT or "len(password)" in SCRIPT_TEXT, \
        "script must check password length against MIN_PASSWORD_LENGTH"


def test_ac4_min_length_error_message():
    lower = SCRIPT_TEXT.lower()
    assert "at least" in lower or "minimum" in lower or "too short" in lower or \
           "characters" in lower, \
        "script must print a clear error when password is too short"


# ── AC-5: hashing via backend.auth only ──────────────────────────────────────

def test_ac5_imports_hash_password_from_auth():
    assert "from backend.auth import" in SCRIPT_TEXT and \
           "hash_password" in SCRIPT_TEXT, \
        "script must import hash_password from backend.auth"


def test_ac5_no_inline_hashing():
    forbidden = ["hashlib", "bcrypt", "argon2", "scrypt(", "pbkdf2"]
    for kw in forbidden:
        assert kw not in SCRIPT_TEXT, \
            f"script must not contain inline hashing logic ({kw!r}); use backend.auth"


def test_ac5_calls_hash_password():
    assert "hash_password(" in SCRIPT_TEXT, \
        "script must call hash_password() from backend.auth"


# ── AC-6: ENVIRONMENT-based DB selection ─────────────────────────────────────

def test_ac6_imports_engine_from_db():
    assert "from backend.db import" in SCRIPT_TEXT and "engine" in SCRIPT_TEXT, \
        "script must import engine from backend.db (same as other scripts)"


def test_ac6_references_environment():
    assert "environment" in SCRIPT_TEXT.lower(), \
        "script must reference the environment (uat/prd) for error reporting"


def test_ac6_no_hardcoded_db_url():
    lower = SCRIPT_TEXT.lower()
    assert "postgresql://" not in lower and "postgres://" not in lower, \
        "script must not hardcode a database URL"


# ── AC-7: success exit code and message ──────────────────────────────────────

def test_ac7_prints_success_message():
    assert "Password updated for user" in SCRIPT_TEXT, \
        "script must print 'Password updated for user ...' on success"


def test_ac7_success_message_goes_to_stdout():
    assert 'print(f"Password updated' in SCRIPT_TEXT or \
           "print(f'Password updated" in SCRIPT_TEXT or \
           'print("Password updated' in SCRIPT_TEXT, \
        "success message must be printed to stdout (not stderr)"


def test_ac7_main_function_defined():
    assert "def main(" in SCRIPT_TEXT, "script must define a main() function"


# ── AC-8: unknown username → non-zero exit ───────────────────────────────────

def test_ac8_checks_user_not_found():
    assert "is None" in SCRIPT_TEXT or "not found" in SCRIPT_TEXT.lower() or \
           "scalar_one_or_none" in SCRIPT_TEXT, \
        "script must handle the case when username is not found"


def test_ac8_user_not_found_error_message():
    lower = SCRIPT_TEXT.lower()
    assert "not found" in lower or "does not exist" in lower or \
           "error: user" in lower, \
        "script must print a descriptive error when user is not found"


# ── AC-9: no new dependencies ─────────────────────────────────────────────────

def test_ac9_no_new_dependencies():
    stdlib_or_allowed = [
        "getpass", "sys", "pathlib", "os", "sqlalchemy", "backend.",
        "from sqlalchemy", "import sqlalchemy",
    ]
    lines = [l.strip() for l in SCRIPT_TEXT.splitlines()
             if l.strip().startswith(("import ", "from "))]
    for line in lines:
        allowed = any(kw in line for kw in stdlib_or_allowed)
        assert allowed, f"Unexpected dependency in script: {line!r}"


# ── AC-10: scripts/README.md documents script ────────────────────────────────

def test_ac10_readme_exists():
    assert README.exists(), "scripts/README.md must exist"


def test_ac10_readme_documents_set_user_password():
    assert "set_user_password.py" in README_TEXT, \
        "scripts/README.md must document set_user_password.py"


def test_ac10_readme_shows_usage_command():
    assert "set_user_password.py" in README_TEXT and \
           ("<username>" in README_TEXT or "Admin" in README_TEXT), \
        "scripts/README.md must show the usage command with <username>"


def test_ac10_readme_documents_exit_codes():
    assert "exit" in README_TEXT.lower() or "Exit" in README_TEXT, \
        "scripts/README.md must document exit codes"


# ── Functional: script logic via mocks ───────────────────────────────────────

@pytest.mark.skipif(not SCRIPT.exists(), reason="script not present")
def test_func_success_path(monkeypatch, capsys):
    """Happy path: valid user + password → stdout confirmation, returns normally."""
    monkeypatch.setattr(sys, "argv", ["set_user_password.py", "Admin"])
    fake_user = MagicMock()
    fake_session = _make_fake_session(fake_user)
    mod = _load_module()

    with patch("getpass.getpass", return_value="validpassword123"), \
         patch.object(mod, "Session", return_value=fake_session):
        mod.main()  # success path returns normally — no sys.exit

    captured = capsys.readouterr()
    assert "Admin" in captured.out, "success message must include username"
    assert "Password updated" in captured.out
    assert "validpassword123" not in captured.out, "plaintext password must not appear"


@pytest.mark.skipif(not SCRIPT.exists(), reason="script not present")
def test_func_empty_password_exits_1(monkeypatch, capsys):
    """Empty password → stderr error, exit 1."""
    monkeypatch.setattr(sys, "argv", ["set_user_password.py", "Admin"])
    mod = _load_module()

    with patch("getpass.getpass", return_value=""):
        with pytest.raises(SystemExit) as exc_info:
            mod.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.strip(), "empty password error must go to stderr"


@pytest.mark.skipif(not SCRIPT.exists(), reason="script not present")
def test_func_short_password_exits_1(monkeypatch, capsys):
    """Password shorter than MIN_PASSWORD_LENGTH → stderr error, exit 1."""
    monkeypatch.setattr(sys, "argv", ["set_user_password.py", "Admin"])
    mod = _load_module()
    from backend.auth import MIN_PASSWORD_LENGTH
    short = "x" * (MIN_PASSWORD_LENGTH - 1)

    with patch("getpass.getpass", return_value=short):
        with pytest.raises(SystemExit) as exc_info:
            mod.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.strip(), "short password error must go to stderr"
    assert short not in captured.err, "short plaintext password must not appear in stderr"


@pytest.mark.skipif(not SCRIPT.exists(), reason="script not present")
def test_func_unknown_user_exits_1(monkeypatch, capsys):
    """Unknown username → stderr error, exit 1, no DB write."""
    monkeypatch.setattr(sys, "argv", ["set_user_password.py", "nonexistent_user"])
    fake_session = _make_fake_session(None)  # user not found
    mod = _load_module()

    with patch("getpass.getpass", return_value="validpassword123"), \
         patch.object(mod, "Session", return_value=fake_session):
        with pytest.raises(SystemExit) as exc_info:
            mod.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert captured.err.strip(), "user-not-found error must go to stderr"
    fake_session.commit.assert_not_called()


@pytest.mark.skipif(not SCRIPT.exists(), reason="script not present")
def test_func_idempotent_two_runs(monkeypatch):
    """Running twice with same username must both succeed without error."""
    fake_user = MagicMock()
    mod = _load_module()

    for _ in range(2):
        monkeypatch.setattr(sys, "argv", ["set_user_password.py", "Admin"])
        fake_session = _make_fake_session(fake_user)
        with patch("getpass.getpass", return_value="validpassword123"), \
             patch.object(mod, "Session", return_value=fake_session):
            mod.main()  # must not raise


@pytest.mark.skipif(not SCRIPT.exists(), reason="script not present")
def test_func_hashes_password_via_auth(monkeypatch):
    """password_hash on user is set by calling hash_password, not inline logic."""
    monkeypatch.setattr(sys, "argv", ["set_user_password.py", "Admin"])
    fake_user = MagicMock()
    fake_session = _make_fake_session(fake_user)
    mod = _load_module()

    with patch("getpass.getpass", return_value="validpassword123"), \
         patch.object(mod, "Session", return_value=fake_session), \
         patch.object(mod, "hash_password", wraps=mod.hash_password) as mock_hash:
        mod.main()

    mock_hash.assert_called_once_with("validpassword123")
    assert fake_user.password_hash is not None


@pytest.mark.skipif(not SCRIPT.exists(), reason="script not present")
def test_func_no_args_exits_1(monkeypatch, capsys):
    """Called with no username argument → usage message to stderr, exit 1."""
    monkeypatch.setattr(sys, "argv", ["set_user_password.py"])
    mod = _load_module()

    with pytest.raises(SystemExit) as exc_info:
        mod.main()

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "usage" in captured.err.lower() or "set_user_password" in captured.err.lower(), \
        "no-arg invocation must print usage to stderr"


@pytest.mark.skipif(not SCRIPT.exists(), reason="script not present")
def test_func_min_password_length_constant():
    """MIN_PASSWORD_LENGTH imported from backend.auth must be >= 8."""
    from backend.auth import MIN_PASSWORD_LENGTH
    assert isinstance(MIN_PASSWORD_LENGTH, int), "MIN_PASSWORD_LENGTH must be an int"
    assert MIN_PASSWORD_LENGTH >= 8, "MIN_PASSWORD_LENGTH must be at least 8"
