import json
import logging
import pytest

import backend.utils.log as log_mod
from backend.utils.log import get_logger, set_request_context


@pytest.fixture(autouse=True)
def reset_log_state(monkeypatch):
    monkeypatch.setattr(log_mod, "_configured", False)
    log_mod._request_context.set(None)
    root = logging.getLogger()
    before = list(root.handlers)
    root.handlers.clear()
    yield
    root.handlers.clear()
    for h in before:
        root.addHandler(h)
    log_mod._request_context.set(None)


def test_get_logger_returns_logger_instance(monkeypatch):
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    logger = get_logger("test.a")
    assert isinstance(logger, logging.Logger)


def test_extra_fields_appear_in_output(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    logger = get_logger("test.b")
    logger.info("hello", extra={"workout_id": "abc"})
    out = capsys.readouterr().err
    assert "workout_id" in out
    assert "abc" in out


def test_json_format_produces_valid_json(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    logger = get_logger("test.c")
    logger.info("hello world")
    out = capsys.readouterr().err.strip()
    data = json.loads(out)
    assert "message" in data
    assert "level" in data
    assert "timestamp" in data
    assert "logger" in data


def test_human_format_not_valid_json(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "human")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    logger = get_logger("test.d")
    logger.info("hello")
    out = capsys.readouterr().err.strip()
    assert out != ""
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


def test_debug_suppressed_at_info_level(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    logger = get_logger("test.e")
    logger.debug("secret")
    out = capsys.readouterr()
    assert (out.err + out.out).strip() == ""


def test_request_context_fields_in_log(monkeypatch, capsys):
    monkeypatch.setenv("LOG_FORMAT", "json")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    set_request_context(request_id="req-123")
    logger = get_logger("test.f")
    logger.info("after context")
    out = capsys.readouterr().err.strip()
    data = json.loads(out)
    assert data.get("request_id") == "req-123"
