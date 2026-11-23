"""Per-request SQL query count + duration for Log-tab endpoints (#1912).

Off unless ``PERF_QUERY_LOG=1`` (or ``enable()`` in tests). When off, no
SQLAlchemy listener is registered.
"""
from __future__ import annotations

import contextvars
import inspect
import logging
import os
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional

_log = logging.getLogger("backend.query_log")

_query_count: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "perf_query_count", default=None
)

_enabled = False
_installed_ids: set[int] = set()


def _env_on() -> bool:
    return os.getenv("PERF_QUERY_LOG") == "1"


def _on_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    n = _query_count.get()
    if n is None:
        return
    _query_count.set(n + 1)


def install(engine: Any = None) -> None:
    """Register ``before_cursor_execute`` on ``engine`` (once per engine)."""
    if engine is None:
        from backend.db import engine as default_engine

        engine = default_engine
    ident = id(engine)
    if ident in _installed_ids:
        return
    from sqlalchemy import event

    event.listen(engine, "before_cursor_execute", _on_before_cursor_execute)
    _installed_ids.add(ident)


def enable(*, engine: Any = None) -> None:
    """Turn instrumentation on and register the listener."""
    global _enabled
    _enabled = True
    install(engine)


def disable() -> None:
    """Stop counting/logging. Listener stays; it no-ops when no span is active."""
    global _enabled
    _enabled = False


def is_enabled() -> bool:
    return _enabled or _env_on()


@contextmanager
def request_span(path: str, user_id: Any = None) -> Iterator[None]:
    if not is_enabled():
        yield
        return
    install()
    token = _query_count.set(0)
    t0 = time.perf_counter()
    try:
        yield
    finally:
        duration_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        count = _query_count.get() or 0
        _query_count.reset(token)
        _log.info(
            "query_log",
            extra={
                "path": path,
                "user_id": str(user_id) if user_id is not None else None,
                "query_count": int(count),
                "duration_ms": duration_ms,
            },
        )


def logged(path: str) -> Callable:
    """FastAPI-safe decorator: do not set ``__wrapped__`` (FastAPI would skip us)."""

    def deco(fn: Callable) -> Callable:
        sig = inspect.signature(fn)

        def wrapped(*args: Any, **kwargs: Any) -> Any:
            if not is_enabled():
                return fn(*args, **kwargs)
            user = kwargs.get("user")
            uid = getattr(user, "id", None)
            with request_span(path, uid):
                return fn(*args, **kwargs)

        wrapped.__signature__ = sig  # type: ignore[attr-defined]
        wrapped.__name__ = fn.__name__
        wrapped.__qualname__ = getattr(fn, "__qualname__", fn.__name__)
        wrapped.__doc__ = fn.__doc__
        wrapped.__module__ = fn.__module__
        wrapped.__annotations__ = dict(getattr(fn, "__annotations__", {}))
        return wrapped

    return deco


if _env_on():
    enable()
