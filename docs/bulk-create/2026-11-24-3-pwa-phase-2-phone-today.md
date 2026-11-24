# PWA phase 2: phone Today

**Date:** 2026-11-24
**Sprint label:** sprint-152
**Default labels:** pwa, pwa-phase-2, manual
**Status:** posted

## Context

Phase 2 is the 30-second daily glance on the phone: the Today screen at /m/today, built only from the downloaded bundle. It also gets deep links that the Hermes morning brief can open directly. Builds on Phases 0 and 1.

Mocks: `docs/pwa/mocks/source/` (390x844).

**Implementation note:** issues are implemented manually in Cursor, not by Commander agents. Each issue body is the Cursor prompt. The `manual` label marks them as hand-implemented; Commander only dispatches tickets passed to it explicitly, so do not include them in a dispatch call.

**Conventions:**
- The mock owns layout; the issue owns rules. Numbers in mocks are illustrative.
- Stack: vanilla JS, rendering only from the IndexedDB bundle (PWA P1-3). Never wait on the server.
- No double-quote characters inside issue bodies.

**Names checked against the repo before posting** (notes added in the issue bodies where reality differs):
- P2-1: `Main.dc.html` exists. `/m/today` and the bundle do not exist yet (Phases 0 and 1). The Osaka block label in the header is illustrative; the plan phase and block come from the bundle `today` fields.
- P2-2: there is no `/api/mobile/ping` or `/api/mobile/today-link` yet. The existing today endpoints are `GET /api/home/revamp` and `GET /api/training/today-recommendation`. The existing API-token mechanism is the `APIToken` model with `Authorization: Bearer <token>` handled in `backend/auth.py` (issue #1759 path). `docs/pwa/hermes.md` does not exist yet.

## Issues

### PWA2-1

```
Title: [PWA P2-1] Phone Today screen at /m/today

Mock
docs/pwa/mocks/source/Main.dc.html.

Scope
- Layout: 16 px screen edges, 14 px between cards, 20 px card padding, gradient header (#4a7ae6 to #1f3b8a). Title Today, with the date plus plan phase and block (e.g. Tue 24 Nov · Osaka block, build wk 1), and the status pill from PWA P1-4.
- Today card (dark ink):
  - kind label (TODAY · STRENGTH, TODAY · RUN, or TODAY · REST);
  - session name;
  - mono summary (exercises, sets, minutes, estimated TSS);
  - exercise chips (first 3 plus +N);
  - a Ready offline badge when the session is fully in the bundle;
  - a primary lime action: Start session (opens /m/gym/{session_id}) for strength, Details for a run;
  - a rest-day variant.
- Last run card: name, day, duration and distance bold, pace, and TSS large on the right.
- Body card: placeholder until Phase 5. Hide it when bundle.body is null.
- Next days: the next 6 days as rows (date, session, TSS). Strength rows show a ✓ offline mark when downloaded.
- Pull to refresh calls refreshBundle(). While the server wakes, keep the stored data on screen and let the pill show Waking.
- Note: /m/today and the bundle do not exist yet (Phases 0 and 1). The plan phase and block in the header come from the bundle today fields; Osaka block is illustrative.

Acceptance criteria
- Renders in airplane mode from a stored bundle in under 1 second.
- Each Today card variant (strength, run, rest, nothing planned) comes from fixtures.
- No network call blocks first paint.
- Values equal the bundle (no client recomputation).

Depends on: PWA1-3, PWA1-4
```

### PWA2-2

```
Title: [PWA P2-2] Deep links and a server wake hook for the morning brief

Why
The Hermes morning brief is the daily entry point. It should wake the sleeping server and open the app on the right screen.

Scope
- Stable deep links handled by the installed app:
  - /m/today;
  - /m/gym/{session_id} (opens the gym overview, or the session player if a session is already in progress);
  - /m/body/weigh-in.
- GET /api/mobile/ping: a cheap endpoint that returns 204 with no database work, used to wake the server.
- docs/pwa/hermes.md: the contract for the Hermes side.
  - Call /api/mobile/ping about 10 minutes before the brief is sent.
  - Include links: Start {session name} → /m/gym/{id} when today is strength, and Weigh in → /m/body/weigh-in.
  - The perf-coach endpoint that gives Hermes today's session id and name: reuse the existing home or today endpoint, or add GET /api/mobile/today-link, authenticated with the existing API-token mechanism.
- The Hermes change itself lives in the Hermes repo and is out of scope here. This issue ships the perf-coach side and the doc.
- Note: the existing today endpoints are GET /api/home/revamp and GET /api/training/today-recommendation. The existing API-token mechanism is the APIToken model with Authorization: Bearer <token>, handled in backend/auth.py. Neither /api/mobile/ping nor docs/pwa/hermes.md exists yet.

Acceptance criteria
- Opening each deep link in the installed app lands on the right screen offline (from the bundle).
- Ping returns 204 without touching the database (test asserts no queries).
- The doc lists the exact URLs and the auth.

Depends on: PWA2-1
```
