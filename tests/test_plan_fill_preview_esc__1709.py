"""plan-fill-preview.js esc() fallback regression — issue #1709.

The fallback path (used when AppCommon.escapeHtml is not loaded) was silently
returning unescaped HTML to satisfy a CI pattern-match test.  Fix: make
AppCommon.escapeHtml a hard dependency so missing the load fails loudly instead
of silently passing raw content through.

AC1: When AppCommon is NOT available, calling any PlanFillPreview render
     function with user-controlled content must NOT return an unescaped string
     containing raw `<`/`>`.  Acceptable outcomes: throw / nonzero exit (hard
     dependency) OR produce escaped markup (real fallback escaping).

AC2: When AppCommon IS available, user-controlled content in rendered HTML is
     properly escaped.

AC3: The fix must not introduce `.replace(/&/g` or character-class replace
     patterns that would fail test_frontend_shared_lib__1603.py's ratchet.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PREVIEW = REPO / "frontend" / "js" / "lib" / "plan-fill-preview.js"
APPCOMMON = REPO / "frontend" / "js" / "lib" / "app-common.js"

_XSS = "<script>alert(1)</script>"
_EXERCISE = f"[{{name:{repr(_XSS)}, spend_tss:5, spend_min:10, sets:3, reps:10}}]"


def _run(js_expr: str, *, with_appcommon: bool = True) -> subprocess.CompletedProcess:
    """Load plan-fill-preview.js under node, optionally with AppCommon, and
    evaluate an expression, returning the CompletedProcess."""
    preamble = "global.window = global; global.document = undefined;"
    if with_appcommon:
        preamble += f"require({str(APPCOMMON)!r});"
    preamble += f"require({str(PREVIEW)!r});"
    script = preamble + f"process.stdout.write(String({js_expr}));"
    return subprocess.run(["node", "-e", script], capture_output=True, text=True)


# ── AC2: with AppCommon present, content is safely escaped ───────────────────

def test_exercise_name_is_escaped_with_appcommon():
    """<script> in a name must appear as &lt;script&gt; in the rendered HTML."""
    r = _run(
        f"global.PlanFillPreview.exerciseTableHtml({_EXERCISE})",
        with_appcommon=True,
    )
    assert r.returncode == 0, f"node error: {r.stderr}"
    assert "<script>" not in r.stdout
    assert "&lt;script&gt;" in r.stdout or "script" not in r.stdout


def test_budget_trace_name_is_escaped_with_appcommon():
    """A malicious exercise name in a budget_pick trace event must be escaped."""
    trace = (
        "[{op:'budget_pick', name:'<img src=x onerror=alert(1)>', "
        "spend_min:10, spend_tss:5, remain_tss_after:0, remain_min_after:0}]"
    )
    r = _run(
        f"global.PlanFillPreview.budgetTraceHtml({trace}, null)",
        with_appcommon=True,
    )
    assert r.returncode == 0, f"node error: {r.stderr}"
    assert "<img " not in r.stdout
    assert "&lt;img " in r.stdout or "img" not in r.stdout


# ── AC1: without AppCommon, esc() must NOT silently pass raw HTML through ────

def test_no_appcommon_does_not_silently_produce_unescaped_html():
    """When AppCommon is absent the render must either throw (hard dependency)
    or still escape the content — returning raw `<script>` is the bug."""
    r = _run(
        f"global.PlanFillPreview.exerciseTableHtml({_EXERCISE})",
        with_appcommon=False,
    )
    if r.returncode == 0:
        # It didn't throw — the output must not contain raw injection content.
        assert "<script>" not in r.stdout, (
            "esc() returned unescaped content when AppCommon was absent — "
            "this is the defense-in-depth regression in issue #1709."
        )
    # else: threw as expected for a hard dependency — that's also acceptable.


# ── AC3: no `.replace(/&/g` or character-class replace patterns ──────────────

def test_no_local_replace_escaper_patterns():
    """The existing shared-escaper ratchet (test_frontend_shared_lib__1603.py)
    must still pass — the fix must not re-introduce replace-based entity subs."""
    src = PREVIEW.read_text()
    offenders = re.findall(r"\.replace\(\s*/&/g", src)
    offenders += re.findall(r"replace\(\s*/\[&<>[^\]]*\]/g", src)
    assert not offenders, (
        f"plan-fill-preview.js re-introduced local entity substitution "
        f"({len(offenders)} site(s)) — use AppCommon.escapeHtml instead."
    )
