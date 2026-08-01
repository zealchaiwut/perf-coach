// Shared escaping and date helpers (issue #1603).
//
// Two helpers were retyped on nearly every page, and the copies drifted:
//
//   escapeHtml — 28 separate definitions under six names (esc, _esc, _escHtml,
//     escapeHtml, escapeAttr, escAttr) plus one .replace() chain inlined at a
//     call site. Only 4 escaped the apostrophe, so a string
//     containing ' could break out of a single-quoted HTML attribute on most
//     pages while the identical content was safe on others. training-plan.js
//     held both variants in two closures — the file disagreed with itself.
//     training.js's escapeAttr did not escape & at all, which means data
//     containing "&lt;" rendered as "<".
//
//   todayISO — 11 files asked the DEVICE what day it is, not 2 as first
//     thought: some via local getters on `new Date()`, some via
//     `toISOString()`, which is UTC and therefore reports YESTERDAY during
//     Bangkok mornings. training-log.js's copy drives the is-today highlight,
//     the default `to` filter and the date picker's max — the "no future dates"
//     rule mirroring a backend constraint. This is the frontend half of the
//     same root cause as #1600, and it is a bug rather than a preference:
//     perf-coach is a single-timezone app and the backend now pins Bangkok
//     everywhere, so a device-local frontend can only disagree with it.
//
// No build step in this project (plain <script> tags served as FileResponse),
// so this attaches its API to `window.AppCommon` and must be loaded as a
// classic script BEFORE the page scripts. Page-level helpers keep their short
// local names and delegate here, so call sites are untouched and there is still
// exactly one implementation.
(function (global) {
  'use strict';

  var BANGKOK = 'Asia/Bangkok';

  // ── Escaping ──────────────────────────────────────────────────────────────

  var HTML_ENTITIES = {
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  };

  // Escapes all five characters. The apostrophe is included deliberately: this
  // codebase builds markup by string concatenation and uses single-quoted
  // attributes in places, so omitting it leaves an attribute-injection hole
  // that varies page to page.
  //
  // `&` must be replaced first, which the character-class approach gets right
  // for free — a sequence of .replace() calls that escapes & last will double
  // escape the entities it just produced.
  function escapeHtml(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return HTML_ENTITIES[c];
    });
  }

  // Attribute values need exactly the same treatment as text content here.
  // Kept as a distinct name only because call sites use it; it is not a
  // weaker variant, which is what the old training.js/nav.js copies were.
  function escapeAttr(s) {
    return escapeHtml(s);
  }

  // ── Dates ─────────────────────────────────────────────────────────────────

  // Today in Bangkok, as YYYY-MM-DD. 'en-CA' is the locale trick that yields
  // ISO order; the timeZone option is what makes it independent of the device.
  function todayISO() {
    return new Date().toLocaleDateString('en-CA', { timeZone: BANGKOK });
  }

  // A Date whose LOCAL getters read Bangkok wall-clock time.
  //
  // Most call sites here don't want a string — they want to do arithmetic
  // (`d.setMonth(d.getMonth() - 3)`, `d.getDay()`, "90 days ago") and then
  // format. Handing them this lets that code stay exactly as written while
  // reading the right clock.
  //
  // The object is deliberately a lie about its own timezone: it holds Bangkok
  // wall time labelled as local. `getFullYear/getMonth/getDate/getDay/getHours`
  // are correct on it; **`toISOString()` and `getTime()` are not** — they would
  // re-apply the device offset. Use todayISO()/toISODate() to serialize.
  function nowBangkok() {
    return new Date(new Date().toLocaleString('en-US', { timeZone: BANGKOK }));
  }

  // Any Date rendered as a Bangkok YYYY-MM-DD.
  function toISODate(d) {
    var date = d instanceof Date ? d : new Date(d);
    if (isNaN(date.getTime())) return null;
    return date.toLocaleDateString('en-CA', { timeZone: BANGKOK });
  }

  // Shift an ISO date string by whole days without going through local time.
  // Parsing 'YYYY-MM-DD' with `new Date()` yields UTC midnight, so adding days
  // in UTC and formatting in UTC keeps the arithmetic exact — using the
  // Bangkok formatter here would shift the result back by a day.
  function addDaysISO(iso, n) {
    var d = new Date(iso + 'T00:00:00Z');
    if (isNaN(d.getTime())) return null;
    d.setUTCDate(d.getUTCDate() + Number(n || 0));
    return d.toISOString().slice(0, 10);
  }

  global.AppCommon = {
    escapeHtml: escapeHtml,
    escapeAttr: escapeAttr,
    todayISO: todayISO,
    nowBangkok: nowBangkok,
    toISODate: toISODate,
    addDaysISO: addDaysISO,
    TIMEZONE: BANGKOK
  };
})(typeof window !== 'undefined' ? window : this);
