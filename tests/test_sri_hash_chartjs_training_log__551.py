"""
Tests for issue #551: SRI hash on Chart.js CDN script in training-log.html.
AC:
  1. <script> tag includes integrity attribute with SHA-384 (or stronger) hash.
  2. <script> tag includes crossorigin="anonymous".
  3. URL is pinned to a specific patch version (not floating @4).
  4. SRI hash matches the pinned version's actual file content.
"""
import re
import base64
import hashlib
import urllib.request
from pathlib import Path

HTML_PATH = Path(__file__).parent.parent / "frontend" / "pages" / "training-log.html"

CHARTJS_RE = re.compile(
    r'<script\s[^>]*src="https://cdn\.jsdelivr\.net/npm/chart\.js[^"]*"[^>]*>',
    re.IGNORECASE,
)

SRI_RE = re.compile(r'\bintegrity="(sha(?:256|384|512)-[^"]+)"')
CROSSORIGIN_RE = re.compile(r'\bcrossorigin="anonymous"')
PINNED_VERSION_RE = re.compile(r'chart\.js@(\d+\.\d+\.\d+)/')


def _get_script_tag():
    html = HTML_PATH.read_text(encoding="utf-8")
    match = CHARTJS_RE.search(html)
    assert match, "No Chart.js <script> tag found in training-log.html"
    return match.group(0)


def test_ac1_integrity_attribute_present_with_sha384():
    """AC1: integrity attribute with SHA-384 (or stronger) is present."""
    tag = _get_script_tag()
    m = SRI_RE.search(tag)
    assert m, f"No integrity attribute found in Chart.js <script> tag: {tag}"
    algo = m.group(1).split("-")[0]
    assert algo in ("sha384", "sha512"), (
        f"integrity must use sha384 or sha512, got {algo}"
    )


def test_ac2_crossorigin_anonymous():
    """AC2: crossorigin="anonymous" is present."""
    tag = _get_script_tag()
    assert CROSSORIGIN_RE.search(tag), (
        f'crossorigin="anonymous" missing from Chart.js <script> tag: {tag}'
    )


def test_ac3_pinned_to_specific_patch_version():
    """AC3: URL is pinned to a full semver (x.y.z), not a floating tag like @4."""
    tag = _get_script_tag()
    m = PINNED_VERSION_RE.search(tag)
    assert m, (
        f"Chart.js URL must include a full semver version (e.g. @4.5.1), got: {tag}"
    )


def test_ac4_sri_hash_matches_pinned_file():
    """AC4: SRI hash matches the actual file served for the pinned version."""
    tag = _get_script_tag()

    version_m = PINNED_VERSION_RE.search(tag)
    assert version_m, "Cannot extract pinned version from tag"
    version = version_m.group(1)

    sri_m = SRI_RE.search(tag)
    assert sri_m, "No integrity value to verify"
    algo, encoded_hash = sri_m.group(1).split("-", 1)

    url = f"https://cdn.jsdelivr.net/npm/chart.js@{version}/dist/chart.umd.min.js"
    with urllib.request.urlopen(url, timeout=15) as resp:
        content = resp.read()

    if algo == "sha384":
        digest = hashlib.sha384(content).digest()
    elif algo == "sha512":
        digest = hashlib.sha512(content).digest()
    else:
        raise AssertionError(f"Unsupported algo: {algo}")

    computed = base64.b64encode(digest).decode()
    assert computed == encoded_hash, (
        f"SRI hash mismatch for chart.js@{version}:\n"
        f"  tag has:    {encoded_hash}\n"
        f"  computed:   {computed}"
    )
