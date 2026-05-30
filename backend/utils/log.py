"""
Structured JSON logger for perf-coach backend.

Usage:
    from backend.utils.log import get_logger, set_request_context

    logger = get_logger(__name__)
    logger.info("workout created", extra={"workout_id": str(id)})

    set_request_context(request_id="req-123")
    logger.info("after context")
"""

import contextvars
import datetime as _dt
import json
import logging
import os
from typing import Any

_request_context: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "_request_context", default=None
)

_configured = False

_STANDARD_LOG_ATTRS = frozenset({
    "args", "asctime", "created", "exc_info", "exc_text", "filename",
    "funcName", "levelname", "levelno", "lineno", "message", "module",
    "msecs", "msg", "name", "pathname", "process", "processName",
    "relativeCreated", "stack_info", "thread", "threadName", "taskName",
})


def set_request_context(**fields: Any) -> None:
    current = _request_context.get(None) or {}
    _request_context.set({**current, **fields})


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _request_context.get(None)
        if ctx:
            for key, val in ctx.items():
                if not hasattr(record, key):
                    setattr(record, key, val)
        return True


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        data: dict[str, Any] = {
            "timestamp": _dt.datetime.fromtimestamp(
                record.created, _dt.timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%S.%f")
            + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.message,
        }
        for key, val in record.__dict__.items():
            if key not in _STANDARD_LOG_ATTRS and not key.startswith("_") and key not in data:
                data[key] = val
        return json.dumps(data)


def _configure_root_logger() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    fmt = os.getenv("LOG_FORMAT", "json").lower()

    handler = logging.StreamHandler()
    handler.addFilter(_ContextFilter())

    if fmt == "human":
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)s  [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S",
            )
        )
    else:
        handler.setFormatter(_JsonFormatter())

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)


def get_logger(name: str) -> logging.Logger:
    _configure_root_logger()
    return logging.getLogger(name)
