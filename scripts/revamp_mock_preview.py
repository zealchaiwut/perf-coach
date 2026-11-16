#!/usr/bin/env python3
"""Build standalone previews of the revamp design mocks.

A ``.dc.html`` mock only renders inside the claude.ai design canvas: it loads
``./support.js`` and wraps its markup in ``<x-dc>`` with a ``<helmet>`` holding
the font link and styles. The screens are static, so a preview is the same
markup with that wrapper removed:

- ``<helmet>`` contents move into ``<head>``
- the ``<x-dc>`` element is unwrapped
- the ``support.js`` script and the ``text/x-dc`` script are dropped
- links to other ``*.dc.html`` mocks point at their preview ``*.html``

Usage (from the repo root)::

    python scripts/revamp_mock_preview.py            # build previews
    python scripts/revamp_mock_preview.py --screenshots   # also take PNGs

Source files in ``docs/revamp/mocks/source/`` are never modified. The build
stops with an error if a mock contains ``{{...}}`` holes or ``<sc-for>`` /
``<sc-if>`` logic, because those need data the preview cannot supply.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOCKS = ROOT / "docs" / "revamp" / "mocks"
SOURCE = MOCKS / "source"
PREVIEW = MOCKS / "preview"
SHOTS = MOCKS / "screenshots"

# Merged into TrainingLog; obsolete.
SKIP = {"TrainingCalendar.dc.html"}

DYNAMIC = re.compile(r"\{\{|<sc-for\b|<sc-if\b")
HELMET = re.compile(r"<helmet>(.*?)</helmet>\s*", re.S)
SUPPORT_JS = re.compile(r'[ \t]*<script src="\./support\.js"></script>\n?')
DC_SCRIPT = re.compile(r'[ \t]*<script type="text/x-dc"[^>]*>.*?</script>\n?', re.S)
X_DC_TAG = re.compile(r"[ \t]*</?x-dc>\n?")
DC_LINK = re.compile(r'href="([A-Za-z0-9_-]+)\.dc\.html"')
LEFTOVER = re.compile(r"<x-dc|<helmet|\{\{")


def to_preview(html: str) -> str:
    helmet = HELMET.search(html)
    if not helmet:
        raise ValueError("no <helmet> block")
    out = HELMET.sub("", html, count=1)
    out = SUPPORT_JS.sub("", out)
    out = DC_SCRIPT.sub("", out)
    out = X_DC_TAG.sub("", out)
    out = out.replace("</head>", helmet.group(1).strip() + "\n</head>", 1)
    out = DC_LINK.sub(r'href="\1.html"', out)
    return out


def build() -> list[Path]:
    PREVIEW.mkdir(parents=True, exist_ok=True)
    sources = sorted(p for p in SOURCE.glob("*.dc.html") if p.name not in SKIP)
    dynamic = [p.name for p in sources if DYNAMIC.search(p.read_text(encoding="utf-8"))]
    if dynamic:
        sys.exit("Mocks with template holes or <sc-for>/<sc-if> (need a decision): "
                 + ", ".join(dynamic))

    written = []
    for src in sources:
        dest = PREVIEW / src.name.replace(".dc.html", ".html")
        html = to_preview(src.read_text(encoding="utf-8"))
        if LEFTOVER.search(html):
            sys.exit(f"{dest.name}: wrapper markup left after conversion")
        dest.write_text(html, encoding="utf-8")
        written.append(dest)
        print(f"preview  {dest.relative_to(ROOT)}")
    return written


def screenshots(previews: list[Path]) -> None:
    from playwright.sync_api import sync_playwright

    SHOTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 900}, device_scale_factor=2)
        for preview in previews:
            page.goto(preview.as_uri(), wait_until="networkidle")
            page.evaluate("document.fonts.ready")
            dest = SHOTS / preview.name.replace(".html", ".png")
            page.screenshot(path=str(dest), full_page=True)
            print(f"shot     {dest.relative_to(ROOT)}")
        browser.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--screenshots", action="store_true",
                        help="also take 1440px-wide @2x full-page PNGs with Playwright")
    args = parser.parse_args()
    previews = build()
    if args.screenshots:
        screenshots(previews)


if __name__ == "__main__":
    main()
