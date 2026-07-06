"""Tests for issue #551: Add SRI hash to Chart.js CDN script in training-log.html (runs against UAT)"""
import re
from pathlib import Path
from html.parser import HTMLParser


# HTML file path — read directly since it's static content
_HTML_FILE = Path(__file__).parent.parent / "frontend" / "pages" / "training-log.html"


class ScriptExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.script_tags = []

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self.script_tags.append(dict(attrs))


def extract_chartjs_script(html_content):
    """Extract the Chart.js script tag from HTML."""
    parser = ScriptExtractor()
    parser.feed(html_content)
    for tag in parser.script_tags:
        if "src" in tag and "chart.js" in tag["src"]:
            return tag
    return None


def test_sri_chartjs__integrity_attribute_present():
    # AC: The Chart.js <script> tag in frontend/pages/training-log.html
    # includes an `integrity` attribute containing a valid SHA-384 (or stronger) SRI hash.
    with open(_HTML_FILE) as f:
        html = f.read()

    script_tag = extract_chartjs_script(html)
    assert script_tag is not None, "Chart.js script tag not found in training-log.html"
    assert "integrity" in script_tag, "integrity attribute missing from Chart.js script tag"

    integrity = script_tag["integrity"]
    assert integrity.startswith("sha384-"), f"Expected SHA-384 hash, got: {integrity}"
    assert len(integrity) > 20, "SRI hash appears too short"


def test_sri_chartjs__crossorigin_anonymous():
    # AC: The <script> tag includes `crossorigin="anonymous"`.
    with open(_HTML_FILE) as f:
        html = f.read()

    script_tag = extract_chartjs_script(html)
    assert script_tag is not None, "Chart.js script tag not found"
    assert "crossorigin" in script_tag, "crossorigin attribute missing from Chart.js script tag"
    assert script_tag["crossorigin"] == "anonymous", (
        f"Expected crossorigin='anonymous', got: {script_tag.get('crossorigin')}"
    )


def test_sri_chartjs__version_pinned_to_patch():
    # AC: The Chart.js URL is pinned to a specific patch version (e.g. `chart.js@4.x.y`)
    # rather than the floating `@4` major tag.
    with open(_HTML_FILE) as f:
        html = f.read()

    script_tag = extract_chartjs_script(html)
    assert script_tag is not None, "Chart.js script tag not found"

    src = script_tag["src"]
    version_match = re.search(r'@(\d+\.\d+\.\d+)', src)
    assert version_match is not None, (
        f"Chart.js URL not pinned to specific patch version. Found: {src}"
    )

    version = version_match.group(1)
    parts = version.split(".")
    assert len(parts) == 3, f"Expected X.Y.Z version format, got: {version}"


def test_sri_chartjs__page_contains_chart_reference():
    # AC: The training log page loads without console errors and charts render correctly
    # with the pinned version.
    with open(_HTML_FILE) as f:
        html = f.read()

    assert "chart" in html.lower(), "No chart references found in training log HTML"

    script_tag = extract_chartjs_script(html)
    assert script_tag is not None, "Chart.js script tag not found"
    assert "integrity" in script_tag, "SRI validation will not occur"
