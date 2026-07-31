"""The reachability gate — issue #1602, the S3 ratchet.

## Why this is a bug class and not a style nit

The pre-production review (`docs/pre-production-review-status.md` §3.1) found
a route built, tested, and reviewed — `/api/weight-targets/{goal_id}/what-if`
— sitting behind a button that LOOKS like it calls it
(`weight.js:401`'s `#whatif-open-btn`) but actually just unhides the ordinary
edit-goal form. The user clicks something labelled for a simulation and
silently gets the wrong feature. Two more endpoints
(`/api/weight-targets/arrival-projection`, `/api/adherence-nudges`) and two
pages (`/projection`, `/strength-view`) had zero frontend callers at all —
fully built, fully tested, unreachable from the app. §3.1 named a third page,
`/weight/targets`, in the same breath — that one turned out to be a
misdiagnosis, not an orphan; see its `_PERMANENT_EXEMPT_PAGES` entry below
for why it stays unlinked on purpose.

None of that trips at review time, because a route existing and a route being
*called* look identical in a diff. The only way to catch it is to ask the
question this file automates: for every registered route, does anything
outside its own definition ever reach for its path?

## Why the app is inspected rather than statically parsed

`main.py` registers routes two ways — the `@app.get(...)` decorator family,
and `app.add_api_route(...)` (used for the `_PAGES` loop and every ad-hoc
redirect/shim route, e.g. `/weight/targets`, `/projection`). A decorator-only
AST scan misses the second kind entirely, which is exactly how `/weight/
targets` stayed invisible before. `backend/routers/*.py` adds a third
registration path (`APIRouter` + `include_router`), so the source of truth
for "what routes exist" is the assembled `FastAPI` app, not any one file.

§2 of the review doc records that #1622's OpenAPI fix (declaring
`resolve_user`'s auth as a real `APIKeyCookie` scheme) was a prerequisite for
this: before it, every authenticated route in `openapi.json` looked
unauthenticated, which would have handed this gate ~300 false positives had
it inspected the schema for auth state. This gate does not need route auth
state — only paths and methods — but it does need the *route table* to be
accurate, and that table comes from importing `backend.main.app` (as
`tests/conftest.py` already does for every test in the suite) and reading
`app.routes`. That is the same object uvicorn serves from — there is no
truer source.

## Why the frontend side is grepped, not parsed

`docs/pre-production-review-status.md` §2's dominant lesson is "greps
undercount, ratchet tests find the rest" — S1's AST-based `.today()` ratchet
found 8 sites every previous grep sweep missed. That argument does not
transfer to the frontend side of *this* gate: this is a no-bundler, vanilla-JS
codebase (CLAUDE.md), so there is no `ast`-equivalent without pulling in a JS
parser dependency this repo does not have. The honest tool here is a regex
search across `frontend/js/**/*.js` and `frontend/pages/**/*.html` for the
route's path shape (literal segments, wildcarded `{path_params}`, matching
`fetch('/api/x')`, `` apiFetch(`/api/x/${id}`) ``, `href="/x"`, and
`window.location.href = '/x'` alike). This undercounts less than it looks:
every orphan this gate's baseline documents below was independently confirmed
absent by hand (`grep -rn` for the literal path, zero hits) against the same
files this regex reads. What it CAN miss: a caller built entirely from
runtime string concatenation with no literal fragment of the path anywhere in
source (e.g. an ID-driven dispatch table) — none of that pattern exists in
this codebase today, but a route that trips the gate as a false-orphan for
that reason is exactly the kind of edge case a new `_PERMANENT_EXEMPT` entry
exists to record, with a reason.

`main.py` is also checked for the same string, but the gate is careful not to
find a route's OWN registration line and count it as a caller — see
`_backend_consumer_haystack()`.

## Scope: endpoints and pages, not columns or job handlers

CLAUDE.md's LLM-policy section is proof this codebase already knows the
difference between "cheap and useful" and "cheap and ignored" — a noisy gate
gets routed around, not fixed. Endpoints and pages are the highest-leverage
case (the review doc calls this "#1602's highest-leverage item") because a
route path is a precise, greppable string with a small, enumerable universe
(the FastAPI route table). DB columns and job handlers do not have that
property here:

- **Columns** are read via ORM attribute access (`workout.tss`,
  `row["tss"]`, `getattr(obj, name)` in a couple of generic serializer
  helpers). `tss` alone is a plausible attribute name on a dozen unrelated
  objects across a 20k-line `main.py` plus `backend/services/`; a sound
  check needs type-aware resolution of which model a given attribute access
  targets, which is a much bigger and more fragile undertaking than this
  ticket's budget, and a wrong answer here is worse than no answer — it
  trains people to ignore the gate.
- **Job handlers** are registered in far fewer places (the sync phase
  functions in `backend/services/sync_runner.py`, worker endpoints in
  `backend/worker_app.py`) and are already exercised by `docs/worker.md`'s
  manual-trigger paths and the sync integration tests — the reachability
  question is much less live there than for a page nobody clicks.

Deferring both here, explicitly, is the choice the ticket calls out as
preferable to shipping a category that produces noise everyone learns to
route around.

## The two allowlists, and why there are two

`_PERMANENT_EXEMPT_*` are routes that will never show a caller in a
frontend/backend-consumer grep BY DESIGN — an OAuth callback the identity
provider redirects to, a dev-only preview route meant to be typed by hand.
These are not orphans; they are correctly-unlinked routes, and they carry a
reason that will still be true next year.

`_BASELINE_ORPHANS_*` are the opposite: genuine orphans, known today, being
fixed on a parallel branch (`feature/1602-s3-reachability-remainder`). This
branch is cut from `develop`, where those orphans still exist, so a strict
gate would fail on its own PR. The baseline is how the two branches compose
instead of racing: **it may only shrink.** Each parametrized case for a
baseline entry asserts the route is STILL genuinely uncalled — the moment the
S3 branch wires one up, that assertion starts failing here too, which is the
signal (not a merge conflict) to delete the entry. Nothing about this file
needs to change when S3 merges; the ratchet does the work.

`/preferences`, `/run-builder` and `/run-view` are none of the above — they
DO have callers (`/preferences` from `coach-brief.js`'s card-href map;
`/run-builder` from an in-page link in `training.html`; `/run-view` from
`run-builder.js`'s post-submit redirect and another `training.html` link) but
none of the three sits in `nav.js`'s `LINKS` table, which is what the review
doc's own sweep cross-referenced first. Recorded as permanent exemptions with
their real reachability path so a future nav-only reading of this gate
doesn't misclassify them — not as ratchet items, because they are not orphans.

## §3.1 said 3 endpoints. Building this gate found 85 more.

This is the loud part. The review doc's own thesis — "greps undercount,
ratchet tests find the rest" — turned out to apply to §3.1's OWN sweep, which
was a manual grep pass run before this gate existed. Once the gate could
actually enumerate every registered route and check each one, `_BASELINE_
ORPHANS_API` ended up with 85 entries beyond the three §3.1 named — over an
order of magnitude more. None of the 85 are `feature/1602-s3-reachability-
remainder`'s problem; that branch owns exactly the three §3.1 items. These
are new findings, each with its own one-line reason in `_BASELINE_ORPHANS_
API` grouped by the pattern that explains the cluster (a home-page endpoint
consolidation left five siblings behind; a coach-message feature was parked
per CLAUDE.md's LLM policy and left five routes behind; three separate route
families — flat `/api/races`, `/api/weight-plans`, `/api/personal-records` —
were each superseded by a newer shape and never deleted; and so on).

Getting there took three real bugs in THIS gate's own matching logic, found
by hand-checking suspicious results against plain `grep` — the same
discipline the review doc credits for S1's AST ratchet finding what earlier
grep sweeps missed, applied reflexively to this file:

1. A wildcard that stopped at whitespace missed `'/x/' + id + '/y'`
   concatenation (spaces around the `+`), producing ~20 false "orphans" that
   plain `grep` immediately showed were called.
2. `_planRaceUrl()` builds `/races` and the `/` before `{race_id}` as two
   separate string literals — a param's bounding slash isn't reliably on one
   side of it, so `_path_pattern()` now strips and re-inserts that slash
   into the wildcard zone.
3. Joining every file into one search string on a single `"\n"` let a
   route's two halves match across the SEAM between two unrelated files
   (fixed with a 200-character file separator, comfortably past the
   wildcard's 120-character bound) — and, separately, backend comments and
   frontend comments each produced their own false-positive matches (a
   `cut_review.py` comment literally explaining that `/api/weight-plans` has
   no caller was, before comment-stripping was added, itself read as a
   caller of that route). Both frontend and backend text are now
   comment-stripped before searching.

Read `_path_pattern()`, `_read_all()`, and `_frontend_haystack()` /
`_backend_consumer_haystack()` for the specifics — each fix is documented
where it lives, not just here.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.routing import APIRoute

REPO = Path(__file__).resolve().parents[1]
FRONTEND_JS = REPO / "frontend" / "js"
FRONTEND_PAGES = REPO / "frontend" / "pages"
BACKEND = REPO / "backend"


# ── Route table ────────────────────────────────────────────────────────────────

def _all_routes() -> list[APIRoute]:
    from backend.main import app

    return [r for r in app.routes if isinstance(r, APIRoute)]


def _checked_paths() -> list[str]:
    """Unique route paths worth asking "does anything call this?"

    Excludes two structural, not-a-judgment-call categories:

    - `/` — the bare domain. Reachable by definition (it's what a browser
      hits with no path at all); there is no meaningful "caller" to look for.
    - `*.html` — every clean page path (`/home`) also registers a legacy
      `.html` alias (`/home.html`) mapped to the SAME handler (see `_PAGES`
      in `main.py`). Checking both would double-count one real entry point,
      and the `.html` spelling shows up constantly in code comments and
      relative same-directory hrefs (`training-log.html#performance`) that
      say nothing about whether the CLEAN path has a caller. Checking the
      clean path is the real question; the alias exists for old bookmarks.
    """
    paths = sorted({r.path for r in _all_routes()})
    return [p for p in paths if p != "/" and not p.endswith(".html")]


# ── Caller search ──────────────────────────────────────────────────────────────

_PARAM = re.compile(r"\{[^/{}]+\}")

# Matches a path segment placeholder written as a JS expression. Vanilla-JS
# callers build these three ways, all seen in this codebase:
#   template interpolation:  `/api/x/${id}/y`
#   same-line concatenation: '/api/x/' + id + '/y'
#   multi-line concatenation ('/api/athletes/' +\n  _athleteId +\n  '/summary/weekly?week=' + ...)
# The third form is common enough in training-log.js and training-performance.js
# that a whitespace-stopping wildcard produced dozens of false "orphan" hits on
# routes that are very much called — this was caught by hand-checking a first
# draft of this gate's failures against plain `grep`, which is the same
# "verify the AST/regex sweep against the thing it claims to find" discipline
# S1's ratchet used. Bounded to 120 chars (roughly four source lines) so a
# route's OWN two literal halves can bridge a realistic concatenation gap
# without the pattern being permissive enough to bridge into a DIFFERENT
# route entirely two paragraphs away.
_WILDCARD = r"[\s\S]{0,120}?"


def _path_pattern(path: str) -> re.Pattern:
    """Build a search pattern for `path`, wildcarding `{params}`.

    `/api/weight-targets/{goal_id}/what-if` splits on its one param into
    `["/api/weight-targets/", "/what-if"]`; escaping each literal piece and
    joining on the wildcard reconstructs a pattern that matches both
    `` `/api/weight-targets/${id}/what-if` `` and a hand-built
    `'/api/weight-targets/' + goalId + '/what-if'` alike.

    The slash immediately touching a param is stripped from the literal
    chunk before escaping, on both sides, and left for the wildcard to
    absorb. Real call sites do not agree on which side of a param owns that
    slash — `training-performance.js`'s `_planRaceUrl` builds
    `/api/plans/{id}/races/{race_id}` as `"/races" + (raceId ? "/" + raceId
    : "")`, i.e. the trailing slash is its OWN string literal, separated
    from `"/races"` by `" + (raceId ? "`. A chunk boundary that demands
    `/races/` as one contiguous run of source characters misses that — and
    did, in an earlier version of this file, until checking the parametrized
    failure by hand against `grep` turned up a real caller the pattern was
    wrongly missing.
    """
    chunks = _PARAM.split(path)
    trimmed = []
    for i, chunk in enumerate(chunks):
        if i > 0:
            chunk = chunk.removeprefix("/")
        if i < len(chunks) - 1:
            chunk = chunk.removesuffix("/")
        trimmed.append(chunk)
    literals = [re.escape(part) for part in trimmed]
    # Trailing (?!\.js): a page route's OWN `<script src="js/strength-view.js">`
    # tag contains the literal substring "/strength-view" one character before
    # ".js" — a real match with no bearing on whether anything LINKS to the
    # page. No route in this app legitimately ends right before a ".js", so
    # excluding that one shape costs nothing.
    return re.compile(_WILDCARD.join(literals) + r"(?!\.js)")


# Longer than `_WILDCARD`'s 120-char bound, so the wildcard can never bridge
# from the tail of one file into the head of the next. An early version of
# this file joined files on a single "\n" and produced a real false positive:
# `/api/plan/draft/ops/add`'s two halves matched across the seam between two
# unrelated files, purely because the tail of one and the head of the next
# happened to contain the right fragments within 120 characters of each
# other. Caught by a route flipping from pass to fail between two unrelated
# runs — the tell that a match's true source needed checking, not trusting.
_FILE_SEP = "\n" * 200


def _read_all(paths: list[Path]) -> str:
    return _FILE_SEP.join(p.read_text(errors="replace") for p in paths if p.is_file())


_HTML_COMMENT = re.compile(r"<!--[\s\S]*?-->")
_JS_BLOCK_COMMENT = re.compile(r"/\*[\s\S]*?\*/")
# Only a `//` that OWNS its line (nothing but whitespace before it) counts as
# a comment to strip. A blanket `//[^\n]*` would also eat the rest of any
# line containing `https://...` — this codebase loads Chart.js from a CDN,
# so that is not hypothetical. Stripping full comment-only lines is enough to
# catch the false positive that motivated this: a prose comment in
# training-performance.js reading "...race/checkpoint/projection URLs..."
# contains the literal substring `/projection` (the slash is just the
# comment's own "or" between three route kinds), and matched this gate's
# /projection page check before this was added.
_JS_LINE_COMMENT = re.compile(r"^[ \t]*//[^\n]*$", re.MULTILINE)


def _strip_comments(text: str) -> str:
    text = _HTML_COMMENT.sub("", text)
    text = _JS_BLOCK_COMMENT.sub("", text)
    text = _JS_LINE_COMMENT.sub("", text)
    return text


def _frontend_haystack() -> str:
    js_files = sorted(FRONTEND_JS.rglob("*.js"))
    html_files = sorted(FRONTEND_PAGES.glob("*.html"))
    return _strip_comments(_read_all(js_files + html_files))


def _backend_consumer_haystack() -> str:
    """Other backend PROCESSES that might call a route over HTTP.

    `backend/worker_app.py` is the one CLAUDE.md names explicitly ("never
    imports main.py") — it shares the DB directly and, if it ever called back
    into the API, would do so over HTTP like any other client. Checked: it
    doesn't today (no `requests`/`httpx` call sites at all), and neither do
    `scripts/*.py`. This haystack stays in place as a guard against that
    changing silently, not because it currently finds anything.

    Deliberately EXCLUDES `backend/main.py` and `backend/routers/*.py` —
    those are where routes are DEFINED. Including them would make every
    route trivially "call" itself via its own `@app.get("/api/x")` line,
    which defeats the whole test.
    """
    py_files = [
        p for p in BACKEND.rglob("*.py")
        if "__pycache__" not in p.parts
        and p != BACKEND / "main.py"
        and p.parent != BACKEND / "routers"
    ]
    raw = _read_all(py_files)
    # Comments and docstrings are stripped. Without this, a route mentioned
    # in prose — e.g. `cut_review.py`'s own note that "`grep -rn
    # 'weight-plans' frontend/` returns nothing" while explaining why it
    # deliberately never calls that route — reads as a caller of the very
    # route it says is uncalled. Caught by hand-checking a passing case that
    # looked suspicious, the same way the false NEGATIVES above were caught
    # by hand-checking failures.
    raw = re.sub(r'"""[\s\S]*?"""', "", raw)
    raw = re.sub(r"'''[\s\S]*?'''", "", raw)
    raw = re.sub(r"#[^\n]*", "", raw)
    return raw


_HAYSTACK: str | None = None


def _haystack() -> str:
    global _HAYSTACK
    if _HAYSTACK is None:
        _HAYSTACK = _frontend_haystack() + _FILE_SEP + _backend_consumer_haystack()
    return _HAYSTACK


def _has_caller(path: str) -> bool:
    return bool(_path_pattern(path).search(_haystack()))


# ── Permanent exemptions — correctly unlinked, not orphans ─────────────────────
#
# Every entry needs a reason that will still be true regardless of what the S3
# remainder branch does. If a reason stops being true, delete the entry — the
# route then either needs a real caller or a `_BASELINE_ORPHANS` entry.

_PERMANENT_EXEMPT_PAGES: dict[str, str] = {
    "/dev/mobile": (
        "Local/UAT-only preview frame (main.py 404s it outside those envs). "
        "Meant to be typed directly, not linked from app nav — that's the "
        "whole point of a device-preview harness."
    ),
    "/preferences": (
        "Deliberate redirect shim -> /training-log?tab=plan#prefs (review doc "
        "§3.1: 'arguably fine'). Has a real caller — coach-brief.js's "
        "CARD_HREF map — but not in nav.js's LINKS table, which is what a "
        "nav-only reachability reading would check first."
    ),
    "/run-builder": (
        "Reachable via an in-page link in training.html ('Log a workout' alt "
        "path), not from nav.js's LINKS. Absent from nav by design (§3.1: "
        "'reachable via in-page links... not orphaned despite being absent "
        "from the nav')."
    ),
    "/run-view": (
        "Reachable via run-builder.js's post-submit redirect and a second "
        "in-page link in training.html. Same nav-absence-by-design as "
        "/run-builder."
    ),
    "/weight/targets": (
        "NOT an orphan awaiting a link, despite review doc §3.1 grouping it "
        "with /projection and /strength-view — it is a superseded route "
        "that must stay unlinked. AC #461 consolidated the standalone page "
        "into weight.html's own 'Edit target' slide-in panel, and "
        "test_weight_page_frontend__412.py::test_b_manage_target_links_to_"
        "weight_targets pins the removal: `assert \"/weight/targets\" not "
        "in WEIGHT_HTML`. feature/1602-s3-reachability-remainder (PR #1629) "
        "confirmed this by hand — adding the link back is a regression, not "
        "a fix — and left it deliberately unlinked, the same treatment as "
        "/preferences: the redirect stays reachable by typing the URL, "
        "never from normal flow. This entry does not go stale when #1629 "
        "merges; it was never going to."
    ),
}

_PERMANENT_EXEMPT_API: dict[str, str] = {
    "/auth/google/callback": (
        "OAuth redirect_uri registered with Google — the identity provider "
        "sends the browser here after consent. The frontend never constructs "
        "this URL itself; that's the nature of a callback."
    ),
    "/admin": (
        "Secret-word-gated admin entry (CLAUDE.md: 'ADMIN_SECRET_UAT / "
        "ADMIN_SECRET_PRD ... behind a separate admin cookie'), reached by "
        "typing the URL, not by app navigation — deliberately absent from "
        "nav.js so it isn't discoverable by browsing. (In practice it also "
        "has a same-file caller — admin.html and admin-login.html both "
        "self-redirect to it after login/logout — but the exemption is "
        "listed on its real merits, not that grep accident.)"
    ),
    "/api/google/callback": (
        "OAuth redirect_uri — same shape as /auth/google/callback above. "
        "Google's off by default (CLAUDE.md) but the callback URL is still "
        "reached by the provider's redirect, never constructed by the app."
    ),
    "/api/strava/callback": (
        "Strava OAuth redirect_uri — the provider sends the browser here "
        "after consent; the frontend never builds this URL."
    ),
    "/api/drive-sleep/callback": (
        "Google Drive OAuth redirect_uri for the sleep-sync integration — "
        "same reasoning as the other two callbacks."
    ),
    "/api/health": (
        "render.yaml's healthCheckPath for both services — Render's own "
        "prober is the caller, not the frontend or another backend process."
    ),
    "/api/plan/draft/ops/add": (
        "Reachable: training-plan.js's _draftOp(op, body) fetches "
        "'/api/plan/draft/ops/' + op at line 452, and _draftOp('add', ...) "
        "is called ~150 lines later (line 604). Real caller, just beyond "
        "this gate's bounded-adjacency regex — confirmed by hand, the same "
        "way the module docstring's proposals example was."
    ),
    "/api/plan/draft/ops/move": (
        "Reachable via the same _draftOp(op, body) indirection as 'add' "
        "above — _draftOp('move', ...) is called at line 576."
    ),
    "/api/plan/draft/ops/remove": (
        "Reachable via the same _draftOp(op, body) indirection as 'add' "
        "above — _draftOp('remove', ...) is called at line 536."
    ),
    "/api/preferences/proposals/{proposal_id}/accept": (
        "Reachable: training-plan.js's _postProposal(id, action) fetches "
        "'/api/preferences/proposals/' + id + '/' + action at line 6089, "
        "and settle(btn, 'accept') is wired to the .pl-prop-accept button "
        "click handler ~40 lines later (line 6127). Confirmed by hand."
    ),
    "/api/preferences/proposals/{proposal_id}/adjust": (
        "Same _postProposal(id, action) indirection as 'accept' above — "
        "wired to the .pl-prop-adjust button (line 6132)."
    ),
    "/api/preferences/proposals/{proposal_id}/decline": (
        "Same _postProposal(id, action) indirection as 'accept' above — "
        "wired to the .pl-prop-decline button (line 6129)."
    ),
}


# ── Baseline — known orphans, ratchet-only, one per review-doc §3.1 item ───────
#
# Each entry names the S3 branch fixing it. When feature/1602-s3-reachability-
# remainder merges and wires up the caller, `_has_caller()` starts returning
# True for that path and the "still genuinely orphaned" assertion below FAILS
# — that failure is the instruction to delete the entry, not a merge conflict
# to resolve. The list may only shrink from here.

_BASELINE_ORPHANS_PAGES: dict[str, str] = {
    "/projection": (
        "No nav.js entry and no frontend href (review doc §3.1). Fixed by "
        "feature/1602-s3-reachability-remainder — delete this entry once "
        "that branch gives the page a real entry point."
    ),
    "/strength-view": (
        "No nav.js entry and no frontend href (review doc §3.1). Fixed by "
        "feature/1602-s3-reachability-remainder."
    ),
}

_BASELINE_ORPHANS_API: dict[str, str] = {
    "/api/weight-targets/{goal_id}/what-if": (
        "The decoy button (review doc §3.1): weight.js:401's "
        "#whatif-open-btn unhides the ordinary edit-goal form instead of "
        "calling this POST endpoint. Fixed by "
        "feature/1602-s3-reachability-remainder — delete once the button "
        "calls it for real."
    ),
    "/api/weight-targets/arrival-projection": (
        "Zero frontend callers (review doc §3.1), backed by goal_arrival.py "
        "and tested by test_arrival_projection_endpoint__878.py. Fixed by "
        "feature/1602-s3-reachability-remainder."
    ),
    "/api/adherence-nudges": (
        "Zero frontend callers (review doc §3.1), backed by "
        "habit_nudges.py + habit_adherence.py. Fixed by "
        "feature/1602-s3-reachability-remainder."
    ),

    # ── Found by this gate, NOT in review doc §3.1 ──────────────────────────
    #
    # The review doc predicted this ("greps undercount, ratchet tests find
    # the rest") but its own §3.1 sweep was itself a grep sweep, run before
    # this gate existed. Building the gate found 85 more orphaned API routes
    # — more than an order of magnitude past the 3 §3.1 named. None of these
    # are feature/1602-s3-reachability-remainder's problem; that branch owns
    # exactly the three above. These are new findings, reported here per this
    # ticket's own instructions, and grouped by the pattern that explains
    # each cluster rather than repeated one at a time.

    # home.js fetches the consolidated /api/home/summary (line 751) instead
    # of any of these five granular siblings, which predate that
    # consolidation and were never deleted.
    "/api/home/personal-records": "Superseded by /api/home/summary; no direct caller (see cluster note above).",
    "/api/home/readiness": "Superseded by /api/home/summary; no direct caller (see cluster note above).",
    "/api/home/recent-workouts": "Superseded by /api/home/summary; no direct caller (see cluster note above).",
    "/api/home/weekly-summary": "Superseded by /api/home/summary; no direct caller (see cluster note above).",
    "/api/home/weight-summary": "Superseded by /api/home/summary; no direct caller (see cluster note above).",

    # home-readiness-training-sleep.js and training-log.js both fetch the
    # bare GET /api/readiness. These three siblings — the POST CLAUDE.md
    # documents as "how readiness gets computed" among them — have no caller
    # anywhere, frontend or backend.
    "/api/readiness/compute": "No caller anywhere (frontend or backend) despite CLAUDE.md naming it as how readiness gets computed; the bare GET /api/readiness is the one live path.",
    "/api/readiness/current": "No frontend caller; the bare GET /api/readiness is what's actually fetched.",
    "/api/readiness/today": "No frontend caller; the bare GET /api/readiness is what's actually fetched.",

    # Only /api/coach/brief, /api/coach/export/paste and /api/coach/consult
    # are called anywhere. These five look like leftovers from the parked
    # coach-message producers CLAUDE.md's LLM-policy section names as
    # pending deletion (coach_narrative, coach_orch_langgraph, ...) — worth a
    # deletion pass, but that is a different ticket than this gate.
    "/api/coach/daily-message": "No frontend caller; only /api/coach/brief, export/paste and consult are used (see cluster note above).",
    "/api/coach/daily-messages": "No frontend caller (see cluster note above).",
    "/api/coach/goal": "No frontend caller (see cluster note above). 'goal' elsewhere in weight.js is an unrelated local field name (m.kind === 'goal'), not this route.",
    "/api/coach/weekly-message": "No frontend caller (see cluster note above).",
    "/api/coach/weekly-messages": "No frontend caller (see cluster note above).",

    # weight.js's export button (line 1684/2010) only builds URLs for
    # weight-targets and weight-entries — the other three CSV exports from
    # the same #414 ticket never got a button.
    "/api/exports/body-measurements": "No export button wired; only weight-targets and weight-entries exports are called (weight.js).",
    "/api/exports/daily-metrics": "No export button wired (see cluster note above).",
    "/api/exports/workouts": "No export button wired (see cluster note above).",

    # No reference to "/api/feel" in any form anywhere in frontend/js or
    # frontend/pages. workout_feel data (CLAUDE.md's schema list) appears to
    # be read/written through some other surface entirely.
    "/api/feel": "Zero references to /api/feel anywhere in frontend (see cluster note above).",
    "/api/feel/auto-link": "Zero references to /api/feel anywhere in frontend (see cluster note above).",
    "/api/feel/search": "Zero references; the one 'search' hit anywhere in frontend is an unrelated filters.search field in training-log.js.",
    "/api/feel/summary": "Zero references to /api/feel anywhere in frontend (see cluster note above).",
    "/api/feel/{feel_id}": "Zero references to /api/feel anywhere in frontend (see cluster note above).",

    "/api/garmin/status": "'Garmin' appears only as a UI label string (settings.js) and a CSS class name (training-log.html) — no fetch call to this route exists.",

    "/api/google/connect": "Google OAuth is 'off by default' (CLAUDE.md); no Settings integration card calls this connect route.",

    # CLAUDE.md's own API-convention example is 'e.g. /api/daily-metrics,
    # /api/workouts, /api/habits/logs' — the hyphenated top-level form below
    # is a legacy spelling nothing calls.
    "/api/habit-logs": "Legacy spelling; the real route is /api/habits/logs (calendar.js, habits.js — also CLAUDE.md's own convention example).",
    "/api/habits/adherence": "No frontend caller; habits.js reads /api/habits/summary and /api/habits/insights instead.",
    "/api/habits/stats": "No frontend caller (see cluster note above).",
    "/api/habits/{habit_id}/progress": "No frontend caller; the one 'progress' hit anywhere in frontend is an unrelated CSS comment in weight.html.",
    "/api/habits/{habit_id}/reorder": "No frontend caller; habits.js's per-habit action is POST /api/habits/{id}/log.",

    "/api/healthz": "Duplicate of /api/health. Its own docstring calls it 'Render health check ping' but render.yaml's healthCheckPath points at /api/health, not this one, and no frontend code calls it either.",
    "/api/environment": "Duplicate of /api/env, which is what env.js and login.html actually call.",

    "/api/imports/sleep": "No UI for manual/viewing sleep imports; settings.html's drive-sleep integration card only calls status/connect/disconnect/folder.",
    "/api/integrations/drive-sleep/sync": "No manual 'Sync now' button for Drive-sleep in settings.html, unlike Strava's strava-sync-now-btn — this manual-trigger endpoint has no caller.",

    "/api/intensity-distribution/rolling": "trends.js calls the real one, /api/workouts/intensity-distribution; this sibling is unused.",
    "/api/sessions/{session_id}/intensity-distribution": "Same — trends.js calls /api/workouts/intensity-distribution instead.",

    "/api/performance/backfill": "No frontend caller; training-performance.js reads /api/athletes/{id}/performance instead.",
    "/api/performance/score-breakdown": "No frontend caller (see cluster note above).",
    "/api/performance/score-history": "No frontend caller (see cluster note above).",

    "/api/personal-records/bulk": "home.js's own comment names the replacement directly: 'via /api/athletes/{id}/run-personal-records — NOT the old /api/personal-records'. This bulk sibling of that retired route is unused too.",

    # _draftOp() (training-plan.js) is only ever invoked with 'add', 'move'
    # and 'remove' (see the PERMANENT_EXEMPT entries above) plus a separate
    # 'regen' route. 'preview-move' and 'swap' are dead ops — the client-side
    # _swapGroups() (line 2607) reorders a local array without ever posting
    # 'swap' to the server.
    "/api/plan/draft/ops/preview-move": "_draftOp() is never called with 'preview-move' anywhere in training-plan.js.",
    "/api/plan/draft/ops/swap": "_draftOp() is never called with 'swap'; _swapGroups() (line 2607) reorders client-side only.",

    "/api/planned-sessions/reconcile": "No frontend caller; the planned-sessions actions used are mark-done/match/miss/unmatch.",

    # training-performance.js's own comments describe both of these as dead:
    # "/api/plans/{id}/projection fetch — that endpoint runs a SEPARATE,
    # less-[...] path" (line 3192), and _planRaceUrl() (line 195) only ever
    # builds .../races[/{id}], never appending /checkpoints.
    "/api/plans/{plan_id}/projection": "training-performance.js's own comment (line 3192) describes this as a separate, unused path from the projection data actually read.",
    "/api/plans/{plan_id}/races/{race_id}/checkpoints": "_planRaceUrl() (training-performance.js:195) never appends /checkpoints; the races CRUD it drives has no checkpoints caller.",
    "/api/plans/{plan_id}/races/{race_id}/checkpoints/{checkpoint_id}": "Same as the collection route above — no caller.",

    "/api/preferences/ai-template": "No frontend caller anywhere.",
    "/api/preferences/catalog": "No frontend caller anywhere.",
    "/api/preferences/confirm": "No frontend caller anywhere.",
    "/api/preferences/export": "No frontend caller anywhere.",
    "/api/preferences/import": "No frontend caller anywhere.",

    "/api/projection": "No frontend caller — distinct from the /projection PAGE route above, which redirects to /log#performance; this is the (also unused) API route of the same name.",
    "/api/projection/snapshots": "No frontend caller anywhere.",

    # The flat /api/races family (main.py ~15215-15838) is superseded by the
    # plan-scoped /api/plans/{id}/races that _planRaceUrl() actually calls
    # (see the PERMANENT_EXEMPT entry note and the checkpoints cluster
    # above). No frontend reference to the flat form survives.
    "/api/races": "Superseded by the plan-scoped /api/plans/{id}/races that _planRaceUrl() calls; no caller for the flat form.",
    "/api/races/{race_id}": "Same flat-races family as /api/races above — no caller.",
    "/api/races/{race_id}/calibrate": "No frontend caller for either calibrate verb.",
    "/api/races/{race_id}/calibrate/accept": "No frontend caller (see above).",
    "/api/races/{race_id}/checkpoints": "Same flat-races family as /api/races above — no caller.",
    "/api/races/{race_id}/checkpoints/{checkpoint_id}": "Same flat-races family as /api/races above — no caller.",
    "/api/races/{race_id}/readiness": "training-performance.js's own comment (line 1374): 'the tab needs no separate /api/races/{id}/readiness call' — deliberately unused.",

    "/api/stats/active-streak": "No frontend caller anywhere.",

    "/api/sync/strava/status": "Legacy sibling of /api/sync/status, which is the one actually polled (sync-poller.js, training-log.js, nav.js — matches CLAUDE.md's documented single sync-status endpoint).",

    # training-log.js fetches /api/training-load/weekly; these four
    # maintenance/admin verbs have no frontend caller.
    "/api/training-load/backfill": "No frontend caller; training-log.js fetches /api/training-load/weekly instead.",
    "/api/training-load/current": "No frontend caller (see cluster note above).",
    "/api/training-load/recompute": "No frontend caller (see cluster note above).",
    "/api/training-load/refresh": "No frontend caller (see cluster note above). The one 'refresh' hit anywhere in frontend is an unrelated <meta http-equiv=\"refresh\"> tag in preferences.html.",

    # training-performance.js and training-plan.js use /api/training/gap-analysis,
    # /api/training/muscle-load and /api/training/plan-check — not these five.
    "/api/training/daily-load": "No frontend caller; distinct from /api/athletes/{id}/daily-load, which IS called (training-log.js, lib/load-readiness-tiles.js).",
    "/api/training/form-metrics": "No frontend caller (see cluster note above).",
    "/api/training/structural-dose": "No frontend caller (see cluster note above).",
    "/api/training/today-recommendation": "No frontend caller (see cluster note above).",
    "/api/training/verdict-history": "No frontend caller (see cluster note above).",

    "/api/users/me/avatar": "No upload/delete UI wired in settings.html — only the read path (GET /api/users/{id}/avatar, used by nav.js for the nav avatar image) is called.",

    "/api/weekly-summary": "No frontend caller anywhere.",

    "/api/weight-hypothesis": "No frontend caller; cut_review.py's comments describe weight_hypothesis.py as internal to the deficit-mode computation, not a route the UI calls directly.",

    # cut_review.py already investigated this exact question and left the
    # answer in a comment: "No UI creates one — `grep -rn 'weight-plans'
    # frontend/` returns nothing — and the only route that does, POST
    # /api/weight-plans, requires a `goal_weight_kg`" — kept deliberately
    # unlinked while weight_hypothesis.py/body_composition.py replace the
    # target-weight concept it represents. §3.2's weight_targets-vs-
    # weight_plans merge decision covers this route's eventual fate; that is
    # a schema-consolidation ticket, not S3's.
    "/api/weight-plans": "No frontend caller — confirmed independently by cut_review.py's own comment (see cluster note above).",
    "/api/weight-plans/active": "No frontend caller (see cluster note above).",
    "/api/weight-plans/{plan_id}": "No frontend caller (see cluster note above).",

    "/api/workouts/recent-type": "No frontend caller anywhere.",
    "/api/workouts/{workout_id}/exercises/reorder": "No frontend caller; the other workout-exercises verbs (replace, the base collection) are used, but not reorder.",

    "/api/calibration-sprint": "No frontend caller; race calibration UI (training-performance.js) uses /api/races/{id}/calibrate instead (also unused — see races cluster above).",
    "/api/calibration-sprint/close": "No frontend caller (see cluster note above).",
    "/api/calibration/status": "No frontend caller (see cluster note above).",

    "/api/brief/today": "No caller — home-coach-strip.js's `brief.today` is a property read on the object /api/coach/brief already returned, not a fetch of this route. Coincidental name collision.",

    "/api/daily-metrics/trend": "No frontend caller; home.js and calendar.js fetch /api/daily-metrics/{uid}/{date} instead.",

    # The /api/athletes/{id}/... calls that exist are /performance,
    # /run-personal-records, /daily-load and /summary/monthly|weekly
    # (home-readiness-training-sleep.js, home.js, training-performance.js,
    # training-log.js, lib/load-readiness-tiles.js). These three are not
    # among them.
    "/api/athletes/{athlete_id}/detected-prs": "No frontend caller (see cluster note above).",
    "/api/athletes/{athlete_id}/duration-curve": "No frontend caller (see cluster note above).",
    "/api/athletes/{athlete_id}/races": "No frontend caller (see cluster note above).",
}

_PERMANENT_EXEMPT: dict[str, str] = {**_PERMANENT_EXEMPT_PAGES, **_PERMANENT_EXEMPT_API}
_BASELINE_ORPHANS: dict[str, str] = {**_BASELINE_ORPHANS_PAGES, **_BASELINE_ORPHANS_API}


def _routes_to_verify() -> list[str]:
    """Every checked path except the permanent exemptions.

    Baseline-orphan paths STAY in this list — they still go through the
    parametrized test below, just with the assertion inverted (see
    `test_route_reachability`).
    """
    return [p for p in _checked_paths() if p not in _PERMANENT_EXEMPT]


# ── The gate ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", _routes_to_verify())
def test_route_reachability(path: str):
    found = _has_caller(path)
    if path in _BASELINE_ORPHANS:
        assert not found, (
            f"{path} is listed in _BASELINE_ORPHANS as a known orphan "
            f"({_BASELINE_ORPHANS[path]!r}) but now HAS a caller. The "
            "baseline is a ratchet — it only shrinks. Delete this entry."
        )
        return
    assert found, (
        f"{path} is a registered route with no caller anywhere in "
        "frontend/js, frontend/pages, or the backend-consumer surface "
        "(backend/worker_app.py and friends). Either wire it up, or if it's "
        "correctly unreachable by design, add it to _PERMANENT_EXEMPT with a "
        "reason — but read this file's module docstring first: an "
        "undocumented orphan is exactly the bug class #1602 exists to catch."
    )


# ── Allowlist hygiene ────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "path", sorted(_PERMANENT_EXEMPT), ids=lambda p: p,
)
def test_permanent_exemption_is_a_real_registered_route(path: str):
    """Catches a typo'd or since-removed exemption entry going stale silently."""
    assert path in _checked_paths(), (
        f"{path} is in _PERMANENT_EXEMPT but is not a currently registered "
        "route (or was removed) — delete the stale entry."
    )


@pytest.mark.parametrize(
    "path", sorted(_BASELINE_ORPHANS), ids=lambda p: p,
)
def test_baseline_entry_is_a_real_registered_route(path: str):
    assert path in _checked_paths(), (
        f"{path} is in _BASELINE_ORPHANS but is not a currently registered "
        "route — delete the stale entry (or if the route was renamed, "
        "update it to match)."
    )


def test_every_allowlist_entry_has_a_real_reason():
    for table_name, table in (
        ("_PERMANENT_EXEMPT_PAGES", _PERMANENT_EXEMPT_PAGES),
        ("_PERMANENT_EXEMPT_API", _PERMANENT_EXEMPT_API),
        ("_BASELINE_ORPHANS_PAGES", _BASELINE_ORPHANS_PAGES),
        ("_BASELINE_ORPHANS_API", _BASELINE_ORPHANS_API),
    ):
        for path, reason in table.items():
            assert isinstance(reason, str) and len(reason) >= 20, (
                f"{table_name}[{path!r}] needs a real one-line reason, not a "
                "placeholder."
            )


# ── Scope note ───────────────────────────────────────────────────────────────

def test_columns_and_job_handlers_are_deferred_by_design():
    """Documented boundary, not an oversight — see the module docstring's
    "Scope" section for why an unsound column/job-handler check is worse than
    none. `backend/models.py` (columns) and
    `backend/services/sync_runner.py` + `backend/worker_app.py` (job
    handlers) both exist and are readable; a future ticket that finds a sound,
    low-noise way to check them should extend this file rather than start a
    second gate.
    """
    assert (BACKEND / "models.py").is_file()
    assert (BACKEND / "services" / "sync_runner.py").is_file()
    assert (BACKEND / "worker_app.py").is_file()
