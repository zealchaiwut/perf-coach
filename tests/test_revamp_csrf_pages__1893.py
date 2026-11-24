"""Issue #1893 — revamp pages that mutate load the shared CSRF helper."""
from pathlib import Path
import re

PAGES = Path("frontend/pages")
MUTATING = re.compile(r"""method\s*:\s*['"](POST|PATCH|PUT|DELETE)['"]""")
SCRIPT = re.compile(r"""src=["'](/js/[^"']+)["']""")


def _js_for(html: Path) -> str:
    src = html.read_text(encoding="utf-8")
    blobs = [src]
    for path in SCRIPT.findall(src):
        f = Path("frontend" + path)
        if f.exists():
            blobs.append(f.read_text(encoding="utf-8"))
    return "\n".join(blobs)


def test_mutating_revamp_pages_load_csrf_helper():
    missing = []
    for html in sorted(PAGES.glob("v2-*.html")):
        if html.name in ("v2-forbidden.html", "v2-components.html"):
            continue
        src = html.read_text(encoding="utf-8")
        js = _js_for(html)
        if not (MUTATING.search(js) or "sendJSON(" in js):
            continue
        if "/js/lib/csrf-fetch.js" not in src:
            missing.append(html.name)
    assert missing == []


def test_csrf_helper_patches_fetch_and_exposes_send_json():
    src = Path("frontend/js/lib/csrf-fetch.js").read_text(encoding="utf-8")
    assert "X-CSRF-Token" in src
    assert "window.sendJSON" in src
    assert "POST" in src and "PATCH" in src
