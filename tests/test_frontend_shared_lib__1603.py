"""One escaper, one "today" — issue #1603 (S4).

Two helpers had been retyped on nearly every page, and the copies drifted into
real bugs rather than mere duplication.

## What was actually there

28 escaper definitions, not the 17 the ticket estimated — the extra 11 were
under names the first sweep's pattern missed (`_esc`, `_escHtml`, `escAttr`,
`escapeAttr`) plus one raw `.replace()` chain inlined at a call site.

Only 4 of them escaped the apostrophe. This codebase builds markup by string
concatenation and uses single-quoted attributes in places, so a value
containing `'` could break out of an attribute on most pages while the
identical value was safe on others. `training-plan.js` held both variants in
two separate closures — the file disagreed with itself.

Two were worse than inconsistent:

- `training.js:escapeAttr` did not escape `&` at all, so a stored value of
  `&lt;script&gt;` rendered as `<script>`.
- `home-readiness-training-sleep.js` escaped the readiness explanation with an
  inline chain covering only `& < >` — neither quote character.

## And "today" was computed in two timezones

Seven files forced Asia/Bangkok; `training-log.js` and `training-performance.js`
used browser-local time. `training-log.js`'s `todayISO()` drives the is-today
highlight, the default `to` filter, and the date picker's `max` — the "no future
dates" rule mirroring a backend constraint. On any client not set to Bangkok
those two pages disagreed with Weight, Habits and Home about the date.

This is the frontend half of #1600's root cause. It is a bug rather than a
preference: perf-coach is a single-timezone app and the backend now pins Bangkok
everywhere, so a device-local frontend can only disagree with it.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
JS = REPO / "frontend" / "js"
PAGES = REPO / "frontend" / "pages"
LIB = JS / "lib" / "app-common.js"


def _page_scripts() -> list[Path]:
    return sorted(p for p in JS.rglob("*.js") if "html2canvas" not in p.name)


# ── The lib exists and is the only implementation ─────────────────────────────

def test_the_shared_lib_exists():
    assert LIB.is_file()


@pytest.mark.parametrize("path", _page_scripts(), ids=lambda p: p.name)
def test_no_page_defines_its_own_escaper(path: Path):
    """The ratchet. A local escaper is how the apostrophe split happened.

    Delegating shims (`return window.AppCommon.escapeHtml(s)`) are fine — they
    keep the short local name at hundreds of call sites while leaving exactly
    one implementation. What must not come back is a page doing its own
    entity substitution.
    """
    if path == LIB:
        return
    src = path.read_text()
    # Match the ESCAPING pattern, not the entity. `&amp;` appears legitimately
    # in static markup ("Load &amp; Intensity") and flagging that would train
    # people to ignore this test.
    offenders = re.findall(r"\.replace\(\s*/&/g", src)
    offenders += re.findall(r"replace\(\s*/\[&<>[^\]]*\]/g", src)
    assert not offenders, (
        f"{path.name} does its own entity substitution ({len(offenders)} site(s)). "
        "Use window.AppCommon.escapeHtml() — the local copies disagreed about "
        "the apostrophe, and one omitted & entirely."
    )


@pytest.mark.parametrize("path", _page_scripts(), ids=lambda p: p.name)
def test_no_page_computes_bangkok_today_itself(path: Path):
    if path == LIB:
        return
    src = path.read_text()
    assert "timeZone: 'Asia/Bangkok'" not in src, (
        f"{path.name} computes today itself; call window.AppCommon.todayISO()"
    )


@pytest.mark.parametrize("path", _page_scripts(), ids=lambda p: p.name)
def test_no_page_computes_today_from_browser_local_time(path: Path):
    """The actual defect, distinct from duplication: asking the DEVICE what
    today is.

    Narrow on purpose. Formatting an arbitrary Date with local getters —
    `isoDate(d)`, `toLocalDateStr(d)`, `_fuelMondayOf(dateStr)` — is fine and
    common here: the Date was already derived from a Bangkok source, and local
    getters round-trip it correctly. What is a bug is `new Date()` (no
    argument, meaning *now*) feeding those getters, because that reads the
    device's calendar.
    """
    src = path.read_text()
    # `new Date()` assigned, then local date getters used on that name.
    offenders = []
    for m in re.finditer(r"(?:const|let|var)\s+(\w+)\s*=\s*new Date\(\)\s*;", src):
        name = m.group(1)
        window = src[m.end(): m.end() + 400]
        if re.search(rf"\b{name}\.get(FullYear|Month|Date)\(\)", window):
            offenders.append(f"line {src[:m.start()].count(chr(10)) + 1}")
    # …and the inline form: new Date().getFullYear()
    if re.search(r"new Date\(\)\.get(FullYear|Month|Date)\(\)", src):
        offenders.append("inline new Date().getX()")
    assert not offenders, (
        f"{path.name} asks the device what today is at {offenders}; use "
        "window.AppCommon.todayISO() so it agrees with the backend and the "
        "other pages"
    )


# ── Every page that needs the lib loads it, first ─────────────────────────────

def _pages_with_external_js() -> list[Path]:
    out = []
    for p in sorted(PAGES.glob("*.html")):
        if re.search(r'<script src="/?js/', p.read_text()):
            out.append(p)
    return out


@pytest.mark.parametrize("page", _pages_with_external_js(), ids=lambda p: p.name)
def test_page_loads_the_shared_lib(page: Path):
    assert "js/lib/app-common.js" in page.read_text(), (
        f"{page.name} loads page scripts that call window.AppCommon but never "
        "loads the lib — every escaped string on it would throw at runtime"
    )


@pytest.mark.parametrize("page", _pages_with_external_js(), ids=lambda p: p.name)
def test_the_lib_loads_before_everything_else(page: Path):
    """Order is load-bearing, not cosmetic. These are classic scripts, so a
    page script that runs first sees `window.AppCommon` undefined."""
    src = page.read_text()
    scripts = [m.start() for m in re.finditer(r'<script src="/?js/', src)]
    lib_at = src.index("js/lib/app-common.js")
    assert min(scripts) <= lib_at <= min(scripts) + 200, (
        f"{page.name} does not load app-common.js first"
    )


def test_pages_without_external_scripts_do_not_need_it():
    """Documented, so the missing tag doesn't read as an oversight: admin,
    login, admin-login, dev-mobile and preferences have inline scripts only and
    reference no escaper."""
    for name in ("admin", "admin-login", "login", "dev-mobile", "preferences"):
        src = (PAGES / f"{name}.html").read_text()
        assert not re.search(r"\besc\(|escapeHtml\(|todayISO\(|AppCommon", src), (
            f"{name}.html now uses a shared helper but loads no scripts"
        )


# ── The escaper behaves ───────────────────────────────────────────────────────

def _run_lib(expr: str) -> str:
    """Execute the lib under node and return the expression's value."""
    script = (
        "global.window = {};"
        f"require({str(LIB)!r});"
        f"process.stdout.write(String({expr}));"
    )
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_apostrophe_is_escaped():
    """The 3-way split. 24 of 28 copies left this character raw."""
    assert _run_lib("window.AppCommon.escapeHtml(\"O'Brien\")") == "O&#39;Brien"


def test_ampersand_is_escaped_first():
    """training.js's escapeAttr omitted `&`, so a stored `&lt;script&gt;`
    rendered as a live tag. It also has to be replaced BEFORE the others or the
    escaper double-escapes its own output — the character-class form gets that
    right by construction."""
    assert _run_lib("window.AppCommon.escapeHtml('&lt;script&gt;')") == "&amp;lt;script&amp;gt;"


def test_all_five_characters():
    got = _run_lib("window.AppCommon.escapeHtml('a&b<c>d\"e\\'f')")
    assert got == "a&amp;b&lt;c&gt;d&quot;e&#39;f"


def test_escape_attr_is_not_a_weaker_variant():
    """nav.js's escAttr skipped `>`, training.js's skipped `&`. Both names now
    resolve to the same full escaper."""
    a = _run_lib("window.AppCommon.escapeAttr('a&b<c>d\"e\\'f')")
    b = _run_lib("window.AppCommon.escapeHtml('a&b<c>d\"e\\'f')")
    assert a == b


@pytest.mark.parametrize("val,expected", [("null", ""), ("undefined", ""), ("42", "42")])
def test_null_and_non_strings(val, expected):
    """Several copies did `String(s)` without a null guard and rendered the
    literal text "null" into the page."""
    assert _run_lib(f"window.AppCommon.escapeHtml({val})") == expected


# ── The date helpers behave ───────────────────────────────────────────────────

def test_today_is_bangkok_not_utc():
    """Run the lib under a UTC process clock: for the last 7 hours of each
    Bangkok day the two answers differ, which is the whole bug."""
    script = (
        "global.window = {};"
        f"require({str(LIB)!r});"
        "const bkk = window.AppCommon.todayISO();"
        "const utc = new Date().toISOString().slice(0,10);"
        "process.stdout.write(bkk + ' ' + utc);"
    )
    env = dict(os.environ, TZ="UTC")
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stderr
    bkk, utc = r.stdout.split()
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", bkk)
    assert bkk >= utc, "Bangkok is UTC+7, so its date is never behind UTC's"


def test_add_days_crosses_month_and_year_boundaries():
    """Done in UTC deliberately: 'YYYY-MM-DD' parses as UTC midnight, so
    formatting the result in Bangkok would shift it back a day."""
    assert _run_lib("window.AppCommon.addDaysISO('2026-07-31', 1)") == "2026-08-01"
    assert _run_lib("window.AppCommon.addDaysISO('2026-01-01', -1)") == "2025-12-31"


def test_bad_input_returns_null_rather_than_a_wrong_date():
    assert _run_lib("window.AppCommon.addDaysISO('not-a-date', 1)") == "null"
    assert _run_lib("window.AppCommon.toISODate('not-a-date')") == "null"
