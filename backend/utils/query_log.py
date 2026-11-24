"""Per-request SQL query count + duration for Log/Plan/Performance endpoints
(#1912, #1923, #1935).

Off unless ``PERF_QUERY_LOG=1`` (or ``enable()`` in tests). When off, no
SQLAlchemy listener is registered.
"""
from __future__ import annotations

import contextvars
import inspect
import logging
import os
import resource
import sys
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional

_log = logging.getLogger("backend.query_log")

_query_count: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "perf_query_count", default=None
)
_write_count: contextvars.ContextVar[Optional[int]] = contextvars.ContextVar(
    "perf_write_count", default=None
)
_radar_cache: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "perf_radar_cache", default=None
)

_WRITE_VERBS = frozenset({"INSERT", "UPDATE", "DELETE"})
_DERIVED_RADAR_KEY = "derived:radar:v3"


def _rss_kb() -> int:
    rss = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    if sys.platform == "darwin":
        rss //= 1024
    return rss


def note_radar_cache(*, hit: bool, key: str = _DERIVED_RADAR_KEY) -> None:
    """Record derived:radar hit/miss on the active request span (#1935)."""
    if key != _DERIVED_RADAR_KEY or _query_count.get() is None:
        return
    if _radar_cache.get() is None:
        _radar_cache.set("hit" if hit else "miss")

_enabled = False
_installed_ids: set[int] = set()


def _env_on() -> bool:
    return os.getenv("PERF_QUERY_LOG") == "1"


def _statement_verb(statement: Any) -> str:
    if not statement:
        return ""
    return str(statement).lstrip().split(None, 1)[0].upper()


def _on_before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    n = _query_count.get()
    if n is None:
        return
    _query_count.set(n + 1)
    w = _write_count.get()
    if w is not None and _statement_verb(statement) in _WRITE_VERBS:
        _write_count.set(w + 1)


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
    wtoken = _write_count.set(0)
    rtoken = _radar_cache.set(None)
    t0 = time.perf_counter()
    rss0 = _rss_kb()
    try:
        yield
    finally:
        duration_ms = round((time.perf_counter() - t0) * 1000.0, 1)
        count = _query_count.get() or 0
        writes = _write_count.get() or 0
        radar = _radar_cache.get()
        rss_delta_kb = max(0, _rss_kb() - rss0)
        _query_count.reset(token)
        _write_count.reset(wtoken)
        _radar_cache.reset(rtoken)
        extra = {
            "path": path,
            "user_id": str(user_id) if user_id is not None else None,
            "query_count": int(count),
            "write_count": int(writes),
            "duration_ms": duration_ms,
            "rss_delta_kb": int(rss_delta_kb),
        }
        if radar is not None:
            extra["radar_cache"] = radar
        _log.info("query_log", extra=extra)


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
