"""Rule registry for the gap analyzer (issue #1370).

Each rule is a pure function ``(inputs: dict) -> GapAnalysisFinding | None``
decorated with ``@registry.register(requires=[...])``.

The engine calls ``registry.run_all(inputs, week_start)`` which:
- Skips any rule whose required input key is absent from ``inputs``.
- Catches any exception raised by a rule and adds it to ``skipped_rules``.
- Returns ``{"findings": [...], "skipped_rules": [...]}``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable

_log = logging.getLogger(__name__)


@dataclass
class _RuleEntry:
    fn: Callable
    requires: list[str]


class RuleRegistry:
    def __init__(self) -> None:
        self._rules: list[_RuleEntry] = []

    def register(self, requires: list[str] = ()):
        """Decorator that registers a rule function with its input requirements."""
        def decorator(fn: Callable) -> Callable:
            self._rules.append(_RuleEntry(fn=fn, requires=list(requires)))
            return fn
        return decorator

    def run_all(self, inputs: dict[str, Any], week_start) -> dict:
        findings = []
        skipped_rules = []

        # Inject live list of fired codes so later rules can suppress themselves.
        # Each rule sees the codes of all findings that have fired *before* it.
        fired_codes: list[str] = []
        inputs = dict(inputs)  # shallow copy — don't mutate caller's dict
        inputs["other_findings_codes"] = fired_codes

        for entry in self._rules:
            fn_name = entry.fn.__name__
            missing = [k for k in entry.requires if k not in inputs]
            if missing:
                _log.debug("Skipping rule %s: missing inputs %s", fn_name, missing)
                skipped_rules.append(fn_name)
                continue
            try:
                result = entry.fn(inputs)
                if result is not None:
                    findings.append(result)
                    fired_codes.append(result.code)
            except Exception:
                _log.warning("Rule %s raised an exception; skipping", fn_name, exc_info=True)
                skipped_rules.append(fn_name)

        return {"findings": findings, "skipped_rules": skipped_rules}
