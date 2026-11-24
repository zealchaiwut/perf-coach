# PWA phase 1: installable app shell

**Date:** 2026-11-24
**Sprint label:** sprint-151
**Default labels:** pwa, pwa-phase-1, manual
**Status:** posted

## Context

Phase 1 makes perf-coach installable on the phone and able to open instantly with no server:

- a manifest and icons;
- a service worker that caches the app shell;
- on-phone storage for the bundle and an outbox of pending changes;
- a flusher that sends the outbox when the server wakes;
- a status pill and a Waiting to sync sheet.

Builds on Phase 0 (bundle, sync, device session).

Mocks: `docs/pwa/mocks/source/` (phone frames, 390x844).

**Implementation note:** issues are implemented manually in Cursor, not by Commander agents. Each issue body is the Cursor prompt. The `manual` label marks them as hand-implemented; Commander only dispatches tickets passed to it explicitly, so do not include them in a dispatch call.

**Conventions:**
- The mock owns layout; the issue owns rules.
- Stack: vanilla JS only, no framework and no build step. A hand-written service worker; IndexedDB through a tiny wrapper of our own (no library), or an idb-keyval-sized helper written in-repo.
- Free-tier rule: never block the UI on the server. Render from IndexedDB first, refresh in the background.
- No double-quote characters inside issue bodies.

**Names checked against the repo before posting** (notes added in the issue bodies where reality differs):
- P1-1: there is no `frontend/manifest.webmanifest`, no `frontend/icons/` directory, no `/m/` route and no `frontend/js/m/` directory yet (all new, expected). Pages are served by FileResponse routes in `backend/main.py` from `frontend/pages/`. The revamp gate is `_revamp_ui_enabled` plus the `_revamp_cutover_redirect` middleware. v2 pages are `frontend/pages/v2-*.html`.
- P1-2: there is no service worker today. `VERSION` exists at the repo root (currently `v0.1.0`). Scripts are cache-busted with `?v=` query strings, and a cache-bust contract test exists, so new files need to follow that. A service worker with scope `/` must be served from `/sw.js`, so it needs its own route.
- P1-3: there is no `package.json` and no JS test harness in the repo. Existing JS checks are Python tests that read the files (for example `tests/test_sessions_js_today_local_date__1195.py`).
- P1-4: `AppShell.dc.html` and `Main.dc.html` both exist. The status pill is new. Today the nav is `frontend/js/nav.js` and `frontend/js/v2-nav.js`; neither is used on `/m/` pages.

## Issues

### PWA1-1

```
Title: [PWA P1-1] Web app manifest, icons and install

Mock
docs/pwa/mocks/source/Main.dc.html (theme and header colours).

Scope
- frontend/manifest.webmanifest:
  - name perf-coach, short_name Coach;
  - start_url /m/today, scope /, display standalone;
  - background_color #1f3b8a, theme_color #1f3b8a;
  - icons at 192, 512 and 512 maskable.
- Icons: a simple monogram on #1f3b8a with a lime #e4ff52 mark, as PNG files in frontend/icons.
- Link the manifest and theme-color meta from every v2 page and the new /m/ pages. Add an apple-touch-icon for iOS.
- Add a /m/ route group in FastAPI serving the mobile pages (shell HTML), reachable without the revamp flag check.
- Note: none of frontend/manifest.webmanifest, frontend/icons or any /m/ route exists yet. Pages are served by FileResponse routes in backend/main.py from frontend/pages/. The revamp gate is _revamp_ui_enabled plus the _revamp_cutover_redirect middleware.

Acceptance criteria
- Chrome on Android offers Install. The installed app opens /m/today in standalone mode with the theme colour.
- A Lighthouse PWA installability check passes on /m/today.

Depends on: none
```

### PWA1-2

```
Title: [PWA P1-2] Service worker: cache the app shell, update safely

Scope
- frontend/sw.js, registered from /m/ pages with scope /.
- Precache a versioned list of shell files (HTML for /m/today, /m/gym, /m/body, the CSS, the JS modules, fonts and icons). The cache name includes a build version (from VERSION).
- Fetch strategy:
  - shell files: cache first;
  - GET /api/mobile/bundle: network with a 4-second timeout, falling back to no response (the app reads IndexedDB itself);
  - all other /api: network only;
  - Google Fonts: stale while revalidate.
- On a new version: the new worker waits; the page shows a New version ready toast with Refresh. Never auto-reload, and never during an active gym session (check a session-active flag in IndexedDB).
- Delete old caches on activate.
- Note: no service worker exists today. VERSION at the repo root is currently v0.1.0. To get scope /, the worker must be served from /sw.js, so add a route for it. Scripts are cache-busted with ?v= query strings and a cache-bust contract test exists, so keep the precache list in step with it.

Acceptance criteria
- In airplane mode, the installed app opens /m/today from cache in under 1 second.
- Deploying a new VERSION shows the toast and Refresh activates it. An active gym session suppresses the toast until it finishes.

Depends on: PWA1-1
```

### PWA1-3

```
Title: [PWA P1-3] On-phone store and outbox flusher

Scope
- frontend/js/m/store.js: a small IndexedDB wrapper with these stores:
  - bundle: the last bundle, its ETag and fetched_at;
  - outbox: queued ops, with client_mutation_id, op_type, created_at, base_version, payload, attempts and last_error;
  - session_state: in-progress gym session state, written on every tap;
  - meta.
- frontend/js/m/sync.js:
  - enqueue(op) writes to the outbox at once.
  - flush() sends batches to POST /api/mobile/sync with exponential backoff (2, 4, 8 … up to 60 s). It runs on app open, on going online, on visibilitychange and after enqueue.
  - It handles applied and duplicate (remove from the outbox) and conflict (keep the op, mark it, surface it in the sheet).
- Server wake detection: if the first request takes over 3 s or fails with a network error, mark the server waking. Keep retrying for up to 90 s, and expose the state to the UI.
- refreshBundle(): GET the bundle with If-None-Match. On 200, store it and broadcast an update event.
- Note: there is no package.json and no JS test harness in the repo today. The existing JS checks are Python tests that read the files (for example tests/test_sessions_js_today_local_date__1195.py), so the unit tests below need a small harness added (for example node --test, or Playwright). frontend/js/m/ does not exist yet.

Acceptance criteria
- Enqueue then kill the app: the op survives and flushes on next open.
- A duplicate response clears the op.
- A conflict stays and is shown.
- Unit tests in a small JS test harness (or Playwright) for enqueue, flush retry and a duplicate.

Depends on: PWA0-3, PWA0-4, PWA0-5
```

### PWA1-4

```
Title: [PWA P1-4] Status pill and Waiting to sync sheet

Mock
docs/pwa/mocks/source/AppShell.dc.html and the pill in Main.dc.html.

Scope
- A header pill on every /m/ page showing one of:
  - Synced HH:MM (green dot);
  - Offline · N (amber, with a wifi-off icon), where N is the outbox count;
  - Waking the server… (blue);
  - Sync problem (red, when an op is in conflict or has failed 5 times).
- Tapping it opens a bottom sheet:
  - the outbox list (one row per op with a human label, e.g. Strength A · 16 sets logged, Weigh-in · 67.8 kg, and its time);
  - a waking-the-server panel with an elapsed counter and the line Free tier sleeps; this takes up to a minute;
  - a primary Keep using the app button;
  - conflicts listed with Keep phone version / Use server version.
- The New version ready toast from PWA1-2 sits under the header.
- Note: the pill is new. The existing navs (frontend/js/nav.js and frontend/js/v2-nav.js) are not used on /m/ pages.

Acceptance criteria
- Each pill state renders from store and sync state.
- The sheet lists queued ops and conflicts.
- Resolving a conflict re-enqueues or drops the op accordingly.
- Touch targets are at least 44 px.

Depends on: PWA1-3
```
