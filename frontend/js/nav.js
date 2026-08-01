/*
 * nav.js — global top navigation bar.
 *
 * Single source of truth for the app's primary nav. Each page just loads this
 * script; it injects its own scoped styles, the Tabler icon font (if missing),
 * and the nav markup, then highlights the active page from the URL.
 *
 * Do NOT hand-write <nav> markup in pages — add or change links here only.
 */
(function () {
  "use strict";

  // Patch window.fetch once to auto-attach X-CSRF-Token on mutating requests.
  if (!window._csrfFetchPatched) {
    window._csrfFetchPatched = true;
    var _origFetch = window.fetch.bind(window);
    var _csrfBootstrap = null;

    function _readCsrfCookie() {
      var match = document.cookie.match(/(?:^|;\s*)csrf-token=([^;]*)/);
      return match ? decodeURIComponent(match[1]) : null;
    }

    function _writeCsrfCookie(token) {
      if (!token) return;
      var secure =
        window.location.protocol === "https:" ? "; Secure" : "";
      document.cookie =
        "csrf-token=" +
        encodeURIComponent(token) +
        "; Path=/; SameSite=Lax" +
        secure;
    }

    function _fetchCsrfToken() {
      return _origFetch("/api/csrf-token", { credentials: "same-origin" })
        .then(function (res) {
          if (!res.ok) return _readCsrfCookie();
          return res.json().then(function (body) {
            var token = (body && body.csrf_token) || _readCsrfCookie();
            if (token) _writeCsrfCookie(token);
            return _readCsrfCookie();
          });
        })
        .catch(function () {
          return _readCsrfCookie();
        });
    }

    function ensureCsrfReady() {
      var cookie = _readCsrfCookie();
      if (cookie) return Promise.resolve(cookie);
      if (!_csrfBootstrap) {
        _csrfBootstrap = _fetchCsrfToken().finally(function () {
          _csrfBootstrap = null;
        });
      }
      return _csrfBootstrap.then(function (token) {
        return token || _readCsrfCookie();
      });
    }

    function _attachCsrfHeader(opts, token) {
      if (!token) return opts;
      var headers = opts.headers || {};
      if (headers instanceof Headers) {
        headers = new Headers(headers);
        headers.set("X-CSRF-Token", token);
      } else {
        headers = Object.assign({}, headers, { "X-CSRF-Token": token });
      }
      return Object.assign({}, opts, { headers: headers, credentials: "same-origin" });
    }

    function _isCsrfForbidden(res) {
      if (!res || res.status !== 403) return Promise.resolve(false);
      return res
        .clone()
        .json()
        .then(function (body) {
          return !!(body && body.detail === "CSRF token missing or invalid");
        })
        .catch(function () {
          return false;
        });
    }

    function _mutatingFetch(url, opts, allowRetry) {
      return ensureCsrfReady().then(function (token) {
        var reqToken = token || _readCsrfCookie();
        var reqOpts = _attachCsrfHeader(opts, reqToken);
        return _origFetch(url, reqOpts).then(function (res) {
          if (!allowRetry) return res;
          return _isCsrfForbidden(res).then(function (csrfFail) {
            if (!csrfFail) return res;
            return _fetchCsrfToken().then(function (fresh) {
              if (!fresh) return res;
              return _origFetch(url, _attachCsrfHeader(opts, fresh));
            });
          });
        });
      });
    }

    window.fetch = function (url, opts) {
      opts = opts || {};
      var method = (opts.method || "GET").toUpperCase();
      if (
        method === "POST" ||
        method === "PATCH" ||
        method === "DELETE" ||
        method === "PUT"
      ) {
        return _mutatingFetch(url, opts, true);
      }
      return _origFetch(url, opts);
    };

    window.ensureCsrfReady = ensureCsrfReady;

    // Warm csrf-token for sessions that pre-date CSRF rollout.
    ensureCsrfReady().catch(function () {});
  }

  // ── Shared /api/auth/me (perf/hot-paths Task 7) ────────────────────────
  // nav.js loads first on every page (before user.js, home.js,
  // training-plan.js, projection.js), so the single cached fetch lives
  // here — every consumer awaits this same promise instead of issuing its
  // own /api/auth/me request. Resolves to null specifically for 401/403
  // (not authenticated) so callers can redirect; rejects for other
  // failures (5xx/network) so callers can distinguish "not logged in"
  // from "request failed" the way each page did before consolidation.
  var _currentUserPromise = null;
  window.fetchCurrentUser = function () {
    if (_currentUserPromise) return _currentUserPromise;
    var ready = window.ensureCsrfReady ? window.ensureCsrfReady() : Promise.resolve();
    _currentUserPromise = ready
      .then(function () {
        return fetch("/api/auth/me");
      })
      .then(function (res) {
        if (res.status === 401 || res.status === 403) return null;
        if (!res.ok) throw new Error("auth/me error " + res.status);
        return res.json();
      });
    return _currentUserPromise;
  };

  // Every primary destination, shown inline in the bar (left → right).
  var LINKS = [
    { href: '/home',     label: 'Home',         icon: 'ti-home',         match: ['/', '/home', '/home.html'] },
    { href: '/log',      label: 'Training',     icon: 'ti-list-details', match: ['/log', '/training', '/training.html'] },
    { href: '/weight',   label: 'Weight',       icon: 'ti-scale',        match: ['/weight', '/weight.html'] },
    { href: '/habits',   label: 'Habits',       icon: 'ti-checklist',    match: ['/habits', '/habits.html'] },
    // The consult loop, end to end: start a check-in, paste the changes
    // back, see the history. Supersedes the old standalone /decisions link
    // (decisions.html is now a redirect shim to here — see main.py's _PAGES).
    { href: '/coach',    label: 'Coach',        icon: 'ti-notes',        match: ['/coach', '/coach.html'] },
    { href: '/trends',      label: 'Trends',      icon: 'ti-chart-line',   match: ['/trends', '/trends.html'] }
    // Users is intentionally omitted — it's an admin-only page (see js/admin-gate.js).
  ];

  // Scoped under .global-nav so it cannot leak into page styles. Colours are the
  // literal values from the original home.html topnav (no CSS-var dependency).
  var CSS = [
    ".global-nav{background:linear-gradient(180deg,#eaf0fb 0%,#d8e3f5 100%);",
    "border-bottom:1px solid rgba(13,30,67,0.06);padding:0 24px;height:60px;",
    "display:flex;align-items:center;gap:20px;position:sticky;top:0;z-index:100;",
    "font-family:inherit;}",
    ".global-nav .gn-links{display:flex;gap:4px;flex:1;min-width:0;overflow-x:auto;scrollbar-width:none;}",
    ".global-nav .gn-links::-webkit-scrollbar{display:none;}",
    ".global-nav .gn-link{padding:8px 14px;border-radius:999px;font-size:16px;font-weight:600;",
    "color:#5c6886;text-decoration:none;display:inline-flex;align-items:center;gap:7px;white-space:nowrap;flex-shrink:0;}",
    ".global-nav .gn-link i{font-size:17px;line-height:1;}",
    ".global-nav .gn-link:hover{background:rgba(13,30,67,0.05);color:#0b1530;}",
    ".global-nav .gn-link.active{background:#0b1530;color:#fff;}",
    ".global-nav .gn-right{display:flex;align-items:center;gap:10px;flex-shrink:0;margin-left:auto;}",
    // Profile: avatar on the FAR RIGHT opens a dropdown (Settings + Log out).
    ".global-nav .gn-profile{position:relative;flex-shrink:0;}",
    ".global-nav .gn-avatar{width:36px;height:36px;border-radius:50%;overflow:hidden;",
    "background:linear-gradient(135deg,#ffb88a,#d97a3a);color:#fff;display:flex;",
    "align-items:center;justify-content:center;font-weight:600;font-size:14px;flex-shrink:0;",
    "border:none;padding:0;cursor:pointer;transition:box-shadow 0.12s ease;}",
    ".global-nav .gn-avatar:hover{box-shadow:0 0 0 2px rgba(13,30,67,0.18);}",
    ".global-nav .gn-avatar.active{box-shadow:0 0 0 2px #0b1530;}",
    ".global-nav .gn-profile-menu{display:none;position:absolute;top:calc(100% + 8px);right:0;left:auto;",
    "min-width:180px;background:#fff;border:1px solid rgba(13,30,67,0.1);border-radius:12px;",
    "box-shadow:0 12px 36px rgba(8,18,48,0.16);padding:6px;z-index:200;}",
    ".global-nav .gn-profile-menu.is-open{display:block;}",
    ".global-nav .gn-profile-menu a,.global-nav .gn-profile-menu button{display:flex;",
    "align-items:center;gap:9px;width:100%;box-sizing:border-box;min-height:44px;padding:10px 12px;border:none;",
    "background:none;border-radius:8px;font:inherit;font-size:14px;color:#0b1530;",
    "text-decoration:none;cursor:pointer;text-align:left;}",
    ".global-nav .gn-profile-menu a:hover,.global-nav .gn-profile-menu button:hover{background:rgba(13,30,67,0.05);}",
    ".global-nav .gn-profile-menu .gn-logout{min-height:44px;color:#c92a2a;}",
    ".global-nav .gn-profile-menu .gn-logout:disabled{opacity:0.55;cursor:default;}",
    ".global-nav .gn-profile-menu i{font-size:17px;line-height:1;}",
    // Environment badge (UAT/LOCAL). Hidden on PRD and while empty (pre-load).
    ".global-nav .gn-env{font-size:11px;font-weight:700;letter-spacing:0.04em;color:#8a5a00;",
    "background:#ffe6b0;border:1px solid #f0c97a;padding:2px 8px;border-radius:999px;",
    "text-transform:uppercase;flex-shrink:0;line-height:1.5;}",
    ".global-nav .gn-env:empty{display:none;}",
    'body[data-env="prd"] .global-nav .gn-env{display:none;}',
    ".global-nav .gn-link-disabled{opacity:0.42;color:#9aa3b2;pointer-events:none;cursor:not-allowed;}",
    ".global-nav .gn-link-disabled i{opacity:0.7;}",
    // Copy for Claude / Copy for consult: one payload, two clipboard writes,
    // grouped under a single entry point with a dropdown (product decision —
    // they're two distinct actions on the same data, not one action, so they
    // stay as two menu choices rather than merging the logic). Same visual
    // weight as the nav links so the trigger reads as an action, not a
    // destination.
    ".global-nav .gn-copy-menu{position:relative;flex-shrink:0;}",
    ".global-nav .gn-copy{position:relative;display:inline-flex;align-items:center;gap:6px;padding:7px 13px;",
    "border:1px solid rgba(13,30,67,0.14);border-radius:999px;background:#fff;",
    "font:inherit;font-size:14px;font-weight:600;color:#0b1530;cursor:pointer;",
    "white-space:nowrap;flex-shrink:0;transition:background 0.12s ease,border-color 0.12s ease;}",
    ".global-nav .gn-copy:hover{background:rgba(13,30,67,0.05);border-color:rgba(13,30,67,0.28);}",
    ".global-nav .gn-copy[disabled]{opacity:0.6;cursor:progress;}",
    ".global-nav .gn-copy i{font-size:16px;line-height:1;}",
    // The trigger's caret flips to signal open/closed state, same idea as the
    // profile menu's aria-expanded but with a visible affordance since this
    // one isn't an avatar users already know is a menu.
    ".global-nav .gn-copy-caret{font-size:12px;line-height:1;transition:transform 0.14s ease;}",
    '.global-nav .gn-copy-trigger[aria-expanded="true"] .gn-copy-caret{transform:rotate(180deg);}',
    // The export takes several seconds to assemble (90 days across many
    // blocks) — without motion, the "Building…" state reads as frozen rather
    // than working for the whole wait. Same rotate-in-place pattern as the
    // sync bar's spinner (ssb-spin), just applied to the tabler loader glyph.
    ".global-nav .gn-copy .ti-loader-2{display:inline-block;animation:gn-copy-spin 0.8s linear infinite;}",
    "@keyframes gn-copy-spin{to{transform:rotate(360deg)}}",
    ".global-nav .gn-copy.is-error{border-color:#e08c8c;color:#c92a2a;}",
    // Dropdown panel: right-aligned to the trigger (not centered), same
    // pattern as .gn-profile-menu — the trigger sits near the env badge/
    // avatar at the nav's right edge, and a centered panel clipped off-screen
    // there the same way the old per-button info-tip bubbles did (fixed in
    // e4fb2e2c). Right-aligning is the fix that already works for the
    // profile menu, so it's reused here instead of a new bubble-positioning
    // scheme.
    ".global-nav .gn-copy-dropdown{display:none;position:absolute;top:calc(100% + 8px);right:0;left:auto;",
    "min-width:250px;max-width:min(88vw,320px);background:#fff;border:1px solid rgba(13,30,67,0.1);",
    "border-radius:12px;box-shadow:0 12px 36px rgba(8,18,48,0.16);padding:6px;z-index:200;}",
    ".global-nav .gn-copy-dropdown.is-open{display:block;}",
    // Each item carries its own explanation as always-in-DOM body text
    // instead of a hover/focus info-tip bubble — inside an already-floating,
    // already-positioned dropdown, a second nested absolutely-positioned
    // bubble is exactly the kind of thing that reintroduces off-screen
    // clipping (the bug e4fb2e2c fixed), and a menu is read top-to-bottom
    // anyway so hover-to-reveal buys nothing here. The explanation is simply
    // part of the item.
    ".global-nav .gn-copy-item{display:flex;flex-direction:column;align-items:stretch;gap:2px;width:100%;",
    "box-sizing:border-box;padding:9px 12px;border:none;background:none;border-radius:8px;",
    "font:inherit;text-align:left;cursor:pointer;color:#0b1530;transition:background 0.12s ease;}",
    ".global-nav .gn-copy-item:hover,.global-nav .gn-copy-item:focus-visible{background:rgba(13,30,67,0.05);outline:none;}",
    ".global-nav .gn-copy-item[disabled]{opacity:0.6;cursor:progress;}",
    ".global-nav .gn-copy-item.is-error{color:#c92a2a;}",
    ".global-nav .gn-copy-item-title{display:flex;align-items:center;gap:8px;font-size:14px;font-weight:600;}",
    ".global-nav .gn-copy-item-title i{font-size:16px;line-height:1;flex-shrink:0;}",
    ".global-nav .gn-copy-item-title .ti-loader-2{animation:gn-copy-spin 0.8s linear infinite;}",
    ".global-nav .gn-copy-item-desc{font-size:12px;font-weight:400;color:#5c6886;line-height:1.4;",
    "padding-left:24px;}",
    "#gn-copy-toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%) translateY(8px);",
    "max-width:min(92vw,460px);padding:10px 16px;border-radius:999px;background:#0b1530;color:#fff;",
    "font-size:13px;font-weight:500;line-height:1.4;box-shadow:0 12px 32px rgba(8,18,48,0.28);",
    "opacity:0;pointer-events:none;transition:opacity 0.16s ease,transform 0.16s ease;z-index:400;",
    "display:flex;align-items:center;gap:12px;}",
    "#gn-copy-toast.is-open{opacity:1;transform:translateX(-50%) translateY(0);pointer-events:auto;}",
    "#gn-copy-toast.is-error{background:#8f1f1f;}",
    "#gn-copy-toast .gnct-retry{border:1px solid rgba(255,255,255,0.5);background:none;color:#fff;",
    "font:inherit;font-size:12px;font-weight:600;padding:4px 11px;border-radius:999px;cursor:pointer;}",
    "#gn-copy-toast .gnct-retry:hover{background:rgba(255,255,255,0.14);}",
  ".global-nav .gn-brand{display:none;font-weight:700;font-size:15px;letter-spacing:-0.02em;color:#0b1530;}",
  ".global-nav .gn-spacer{display:none;}",
  ".global-nav .gn-menu-btn{display:none;align-items:center;justify-content:center;",
    "width:40px;height:40px;border:0;border-radius:10px;background:transparent;",
    "color:#0b1530;font-size:22px;cursor:pointer;flex-shrink:0;}",
  ".global-nav .gn-menu-btn:hover{background:rgba(13,30,67,0.06);}",
  ".global-nav .gn-menu-backdrop{display:none;position:fixed;inset:0;background:rgba(11,21,48,0.35);z-index:90;}",
  ".global-nav .gn-menu-backdrop.is-open{display:block;}",
    // Mobile: hamburger menu with labeled links (Option B).
    "@media (max-width:880px){.global-nav{padding:0 12px;height:56px;gap:10px;}",
    ".global-nav .gn-brand{display:block;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}",
    ".global-nav .gn-spacer{display:block;flex:1;}",
    ".global-nav .gn-link-disabled{display:none;}",
    ".global-nav .gn-right{display:flex;}",
    ".global-nav .gn-env{display:none;}",
    // Mobile: keep the trigger, drop its label — the icon (+ caret) carries
    // it. Unlike the old per-button info-tip bubble, the dropdown items'
    // explanations live in .gn-copy-item-desc, a different class outside
    // .gn-copy entirely, so this rule doesn't need an exclusion to keep them
    // reachable — they were never a `.gn-copy span` to begin with.
    ".global-nav .gn-copy{padding:7px 9px;}",
    ".global-nav .gn-copy-trigger span{display:none;}",
    ".global-nav .gn-copy-dropdown{max-width:88vw;}",
    ".global-nav .gn-menu-btn{display:flex;}",
    ".global-nav .gn-links{display:none;position:fixed;left:12px;right:12px;top:56px;",
      "flex-direction:column;gap:4px;background:#fff;border:1px solid rgba(13,30,67,0.1);",
      "border-radius:14px;padding:8px;box-shadow:0 16px 40px rgba(8,18,48,0.18);z-index:95;",
      "max-height:calc(100vh - 72px);overflow-y:auto;}",
    ".global-nav .gn-links.is-open{display:flex;}",
    ".global-nav .gn-link{padding:12px 14px;border-radius:10px;font-size:15px;}",
    ".global-nav .gn-link span{display:inline;}",
    ".global-nav .gn-link i{font-size:18px;}}",
  ].join("");

  var SYNC_BAR_CSS = [
    "#sync-status-bar{display:none;align-items:center;gap:8px;padding:5px 24px;",
    "font-size:12px;font-weight:500;line-height:1.4;",
    "border-bottom:1px solid rgba(13,30,67,0.08);",
    "font-family:inherit;}",
    "#sync-status-bar.ssb-state-running{background:#eef2ff;color:#3b5bdb;display:flex;}",
    "#sync-status-bar.ssb-state-success{background:#ebfbee;color:#2f9e44;display:flex;}",
    "#sync-status-bar.ssb-state-error{background:#fff5f5;color:#c92a2a;display:flex;}",
    "#sync-status-bar .ssb-spinner{width:11px;height:11px;border-radius:50%;flex-shrink:0;",
    "border:2px solid rgba(59,91,219,0.25);border-top-color:#3b5bdb;",
    "animation:ssb-spin 0.75s linear infinite;}",
    "@keyframes ssb-spin{to{transform:rotate(360deg)}}",
    "#sync-status-bar .ssb-msg{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;}",
    "#sync-status-bar .ssb-dismiss{margin-left:auto;padding:2px 10px;border-radius:999px;",
    "font-size:11.5px;font-weight:500;cursor:pointer;background:none;color:inherit;flex-shrink:0;",
    "border:1.5px solid rgba(13,30,67,0.2);",
    "font-family:inherit;}",
    "#sync-status-bar .ssb-dismiss:hover{background:rgba(13,30,67,0.08);}",
    "@media(max-width:880px){#sync-status-bar{padding:5px 14px;}}",
  ].join("");

  function ensureIconFont() {
    if (document.querySelector('link[href*="tabler-icons"]')) return;
    var link = document.createElement("link");
    link.rel = "stylesheet";
    link.href =
      "https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3/dist/tabler-icons.min.css";
    // Insert early so icons render before first paint on slow connections.
    var head = document.head;
    if (head.firstChild) head.insertBefore(link, head.firstChild);
    else head.appendChild(link);
  }

  function injectStyles() {
    if (document.getElementById("global-nav-styles")) return;
    var style = document.createElement("style");
    style.id = "global-nav-styles";
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  // Delegates to the shared escaper (issue #1603). The local copies
  // disagreed about the apostrophe, so identical content was safe on
  // some pages and attribute-injectable on others.
  function escAttr(s) {
    return window.AppCommon.escapeHtml(s);
  }

  function buildNav() {
    if (document.querySelector(".global-nav")) return;
    var path = window.location.pathname;

    var linksHtml = LINKS.map(function (l) {
      if (l.disabled) {
        return (
          '<span class="gn-link gn-link-disabled" aria-disabled="true" title="Coming soon">' +
          '<i class="ti ' +
          l.icon +
          '" aria-hidden="true"></i>' +
          "<span>" +
          l.label +
          "</span></span>"
        );
      }
      var active = l.match.indexOf(path) !== -1;
      return (
        '<a class="gn-link' +
        (active ? " active" : "") +
        '" href="' +
        escAttr(l.href) +
        '"' +
        (active ? ' aria-current="page"' : "") +
        ">" +
        '<i class="ti ' +
        l.icon +
        '" aria-hidden="true"></i>' +
        "<span>" +
        l.label +
        "</span></a>"
      );
    }).join("");

    var nav = document.createElement("nav");
    nav.className = "global-nav";
    nav.setAttribute("aria-label", "Primary navigation");
    nav.innerHTML =
      '<span class="gn-brand">perf-coach</span>' +
      '<span class="gn-spacer" aria-hidden="true"></span>' +
      '<button type="button" class="gn-menu-btn" id="gn-menu-btn"' +
      ' aria-label="Open navigation menu" aria-expanded="false" aria-controls="gn-links">' +
      '<i class="ti ti-menu-2" aria-hidden="true"></i></button>' +
      '<div class="gn-links" id="gn-links" role="navigation">' +
      linksHtml +
      "</div>" +
      '<div class="gn-right">' +
      // One entry point, two choices (product decision — the daily paste and
      // the consult blob are distinct actions on the same data, so they stay
      // separate menu items rather than merging the copy logic itself; see
      // _copyForClaude below). aria-label on the trigger duplicates its
      // visible <span> deliberately: the mobile media query
      // (".gn-copy-trigger span{display:none}") hides that span on narrow
      // viewports, and a display:none span drops out of the accessible-name
      // computation — without this, a screen-reader user on mobile would hit
      // an unlabeled button here.
      '<div class="gn-copy-menu" id="gn-copy-menu">' +
      '<button type="button" class="gn-copy gn-copy-trigger" id="gn-copy-trigger"' +
      ' aria-haspopup="true" aria-expanded="false" aria-controls="gn-copy-dropdown"' +
      ' aria-label="Copy for Claude or consult">' +
      '<i class="ti ti-clipboard-text" aria-hidden="true"></i>' +
      "<span>Copy</span>" +
      '<i class="ti ti-chevron-down gn-copy-caret" aria-hidden="true"></i>' +
      "</button>" +
      '<div class="gn-copy-dropdown" id="gn-copy-dropdown" role="menu" aria-labelledby="gn-copy-trigger">' +
      // Each item's explanation is plain body text under its title rather
      // than a hover info-tip bubble — see the CSS comment above
      // .gn-copy-item for why (this is the fix for the off-screen clipping
      // that e4fb2e2c had to chase for the old standalone buttons: there is
      // no absolutely-positioned bubble left to clip).
      '<button type="button" class="gn-copy-item" id="gn-copy-claude" role="menuitem">' +
      '<span class="gn-copy-item-title"><i class="ti ti-clipboard-text" aria-hidden="true"></i>Copy for Claude</span>' +
      '<span class="gn-copy-item-desc">' +
      "Copies a training summary — readiness, training load, and your " +
      "last 90 days of workouts — as plain text to paste into a fresh " +
      "Claude chat. About 10 seconds to build, ~25k characters." +
      "</span></button>" +
      '<button type="button" class="gn-copy-item" id="gn-copy-consult" role="menuitem">' +
      '<span class="gn-copy-item-title"><i class="ti ti-messages" aria-hidden="true"></i>Copy for consult</span>' +
      '<span class="gn-copy-item-desc">' +
      "Copies the check-in prompt — asks a few questions, then ends in " +
      "a change list to paste into /decisions. Same last-90-days data, " +
      "about 10 seconds to build." +
      "</span></button>" +
      "</div>" +
      "</div>" +
      '<span class="gn-env" id="env-label" aria-label="Environment"></span>' +
      '<div class="gn-profile" id="gn-profile">' +
      '<button class="gn-avatar' +
      (path === "/settings" ? " active" : "") +
      '" id="nav-avatar" type="button" aria-haspopup="true" aria-expanded="false"' +
      ' title="Profile" aria-label="Profile menu">U</button>' +
      '<div class="gn-profile-menu" id="gn-profile-menu" role="menu">' +
      '<a class="gn-settings" href="/settings" role="menuitem"><i class="ti ti-settings" aria-hidden="true"></i>Settings</a>' +
      '<a class="gn-settings" href="/training-log?tab=plan#prefs" role="menuitem"><i class="ti ti-sliders" aria-hidden="true"></i>Preferences</a>' +
      '<button type="button" class="gn-logout" id="nav-logout" role="menuitem">' +
      '<i class="ti ti-logout" aria-hidden="true"></i>Log out</button>' +
      "</div>" +
      "</div>" +
      "</div>" +
      '<div class="gn-menu-backdrop" id="gn-menu-backdrop" hidden></div>';

    document.body.insertBefore(nav, document.body.firstChild);

    _wireProfileMenu(nav);
    _wireMobileMenu(nav);
    _wireCopyMenu(nav);
    _wireCopyForClaude();
    _positionGlobalNav();
    _observeNavRightWidth(nav);

    document
      .getElementById("nav-logout")
      .addEventListener("click", function () {
        var btn = this;
        btn.disabled = true;
        fetch("/api/auth/logout", { method: "POST" })
          .then(function () {
            window.location.href = "/login";
          })
          .catch(function () {
            btn.disabled = false;
          });
      });
  }

  // ── Copy for Claude ──────────────────────────────────────────────────────
  // Fetches the complete paste blob (prompt template + 90-day payload) in ONE
  // request and writes it to the clipboard. Never copies a partial blob: on any
  // fetch failure nothing touches the clipboard and the toast offers a retry.

  // Two blobs, one mechanism. The daily message is one-way and short; the
  // consult asks questions and ends in a change list you paste into
  // /decisions. Both are plain text from the same export payload, so the only
  // difference is which endpoint is fetched.
  var COPY_ENDPOINT = "/api/coach/export/paste";
  var CONSULT_ENDPOINT = "/api/coach/consult";

  /** Same contract as training-plan.js's Stryd copy: Clipboard API, then a
   * hidden-textarea fallback for older webviews and non-secure contexts. */
  function _writeClipboard(text) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      return navigator.clipboard.writeText(text).catch(function () {
        return _fallbackClipboard(text);
      });
    }
    return _fallbackClipboard(text);
  }

  function _fallbackClipboard(text) {
    return new Promise(function (resolve, reject) {
      var ta = document.createElement("textarea");
      ta.value = text;
      ta.setAttribute("readonly", "");
      ta.style.position = "fixed";
      ta.style.top = "0";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      ta.setSelectionRange(0, ta.value.length);
      var ok = false;
      try {
        ok = document.execCommand("copy");
      } catch (e) {
        ok = false;
      }
      document.body.removeChild(ta);
      ok ? resolve() : reject(new Error("clipboard unavailable"));
    });
  }

  var _toastTimer = null;

  function _copyToast(message, opts) {
    opts = opts || {};
    var toast = document.getElementById("gn-copy-toast");
    if (!toast) {
      toast = document.createElement("div");
      toast.id = "gn-copy-toast";
      toast.setAttribute("role", "status");
      toast.setAttribute("aria-live", "polite");
      document.body.appendChild(toast);
    }
    toast.innerHTML = "";
    var label = document.createElement("span");
    label.textContent = message;
    toast.appendChild(label);
    if (opts.onRetry) {
      var retry = document.createElement("button");
      retry.type = "button";
      retry.className = "gnct-retry";
      retry.textContent = "Retry";
      retry.addEventListener("click", function () {
        toast.classList.remove("is-open");
        opts.onRetry();
      });
      toast.appendChild(retry);
    }
    // onCopy: the export is already fetched and sitting in memory — this
    // button's click is a fresh, real user gesture, so the clipboard write
    // it triggers succeeds even in the case (see _copyForClaude) where the
    // automatic post-fetch write couldn't. Deliberately not styled/labeled
    // as an error state — this is the expected, common path, not a failure.
    if (opts.onCopy) {
      var copyBtn = document.createElement("button");
      copyBtn.type = "button";
      copyBtn.className = "gnct-retry";
      copyBtn.textContent = "Copy";
      copyBtn.addEventListener("click", function () {
        opts.onCopy(toast);
      });
      toast.appendChild(copyBtn);
    }
    toast.classList.toggle("is-error", !!opts.error);
    toast.classList.add("is-open");
    if (_toastTimer) clearTimeout(_toastTimer);
    // An error/action toast holds a button, so it stays until dismissed by
    // the next toast rather than vanishing mid-reach. A persisted toast (the
    // in-flight "Building…" status) skips the auto-dismiss for the same
    // reason: the ~12s build regularly outlasts the normal 4s toast life, and
    // it would otherwise vanish mid-wait, right when it's most needed, and
    // leave nothing but the button's own spinner for the rest of the wait.
    // The next _copyToast call (success or error) always replaces it.
    if (!opts.onRetry && !opts.onCopy && !opts.persist) {
      _toastTimer = setTimeout(function () {
        toast.classList.remove("is-open");
      }, 4000);
    }
  }

  function _copyCharCount(chars) {
    return chars >= 1000 ? Math.round(chars / 1000) + "k chars" : chars + " chars";
  }

  function _copyForClaude(btn, endpoint, label) {
    endpoint = endpoint || COPY_ENDPOINT;
    label = label || "copied";
    var original = btn ? btn.innerHTML : null;
    if (btn) {
      btn.disabled = true;
      btn.classList.remove("is-error");
      btn.innerHTML =
        '<i class="ti ti-loader-2" aria-hidden="true"></i><span>Building…</span>';
    }

    function restore() {
      if (btn && original !== null) {
        btn.disabled = false;
        btn.innerHTML = original;
      }
    }

    // The button's own "Building…" + spinner only reads clearly once you've
    // noticed it; the toast is the loud, hard-to-miss half of the same
    // signal, and names roughly how long the ~12s build takes so the wait
    // reads as expected rather than possibly-stuck. persist:true keeps it
    // open for the full wait — see _copyToast's comment on why the normal
    // 4s auto-dismiss doesn't fit this case.
    var buildingMsg =
      endpoint === CONSULT_ENDPOINT
        ? "Building your check-in — usually takes about 10 seconds…"
        : "Building your training summary — usually takes about 10 seconds…";
    _copyToast(buildingMsg, { persist: true });

    fetch(endpoint, { credentials: "same-origin" })
      .then(function (res) {
        if (!res.ok) throw new Error("export failed (" + res.status + ")");
        return res.text();
      })
      .then(function (blob) {
        if (!blob || !blob.trim()) throw new Error("export was empty");

        function stamped() {
          // Bangkok date, not the browser's — this app is single-timezone and
          // the stamp must match the day the export itself was built for.
          return new Date().toLocaleDateString("en-CA", { timeZone: "Asia/Bangkok" });
        }

        return _writeClipboard(blob).then(function () {
          restore();
          _copyToast(label + " · " + _copyCharCount(blob.length) + " · " + stamped());
        }).catch(function () {
          // The automatic write failed — almost always because this fetch
          // took the ~10-12s it's expected to, and by the time it resolved,
          // the browser's clipboard-write permission (tied to a recent, real
          // user gesture — "transient activation") had expired. Retrying the
          // whole fetch would hit the exact same timing wall again. Instead,
          // the blob is already sitting in memory — offer a manual Copy
          // button, whose own click is a fresh gesture, so the write it
          // triggers succeeds even though the automatic one couldn't.
          restore();
          _copyToast("Ready — " + _copyCharCount(blob.length) + " to copy", {
            persist: true,
            onCopy: function (toastEl) {
              _writeClipboard(blob).then(function () {
                toastEl.classList.remove("is-open");
                _copyToast(label + " · " + _copyCharCount(blob.length) + " · " + stamped());
              }).catch(function () {
                _copyToast("Still couldn't copy — select and copy the text manually.", {
                  error: true,
                });
              });
            },
          });
        });
      })
      .catch(function (err) {
        restore();
        if (btn) btn.classList.add("is-error");
        _copyToast(
          "Couldn't copy — " + (err && err.message ? err.message : "request failed") + ".",
          {
            error: true,
            onRetry: function () {
              _copyForClaude(btn, endpoint, label);
            },
          }
        );
      });
  }

  // Shared with coach.js's "Start a check-in" card — the /coach page's own
  // consult trigger calls this SAME function (same fetch, clipboard write,
  // persisted "Building…" toast, and error/retry behavior) rather than
  // reimplementing it, so the nav dropdown's "Copy for consult" item and the
  // Coach page entry point can't drift apart the way 17 divergent esc()
  // copies once did (issue #1603). nav.js is a single IIFE with nothing else
  // copy-related on window, so this is the one addition needed to make the
  // logic reachable from another page's script.
  window.NavCopy = {
    copyForClaude: _copyForClaude,
    COPY_ENDPOINT: COPY_ENDPOINT,
    CONSULT_ENDPOINT: CONSULT_ENDPOINT,
  };

  function _wireCopyForClaude() {
    var btn = document.getElementById("gn-copy-claude");
    if (btn && !btn._wired) {
      btn._wired = true;
      btn.addEventListener("click", function () {
        _closeCopyDropdown();
        _copyForClaude(btn, COPY_ENDPOINT, "copied");
      });
    }
    var consult = document.getElementById("gn-copy-consult");
    if (consult && !consult._wired) {
      consult._wired = true;
      consult.addEventListener("click", function () {
        _closeCopyDropdown();
        _copyForClaude(consult, CONSULT_ENDPOINT, "consult copied");
      });
    }
  }

  // ── Copy menu (dropdown) ────────────────────────────────────────────────
  // One trigger, one panel holding both copy choices (see the CSS comment
  // above .gn-copy-menu for why they're grouped this way instead of two peer
  // buttons). Open/close/outside-click/Escape mirrors _wireProfileMenu below;
  // kept as its own function because selecting an item fires a network
  // request and closes the panel, rather than navigating to a destination.
  var _closeCopyDropdown = function () {};

  function _wireCopyMenu(nav) {
    var trigger = document.getElementById("gn-copy-trigger");
    var dropdown = document.getElementById("gn-copy-dropdown");
    if (!trigger || !dropdown) return;

    function close() {
      dropdown.classList.remove("is-open");
      trigger.setAttribute("aria-expanded", "false");
    }
    // Exposed so _wireCopyForClaude's item click handlers (wired separately,
    // after this function runs) can close the panel once a choice is made.
    _closeCopyDropdown = close;

    function open() {
      // Mutually exclusive with the profile menu and the mobile links panel —
      // the same rule _wireProfileMenu/_wireMobileMenu already apply to each
      // other, so at most one floating panel is open at a time.
      var profileMenu = document.getElementById("gn-profile-menu");
      var avatar = document.getElementById("nav-avatar");
      if (profileMenu) profileMenu.classList.remove("is-open");
      if (avatar) avatar.setAttribute("aria-expanded", "false");
      var links = document.getElementById("gn-links");
      var menuBtn = document.getElementById("gn-menu-btn");
      var backdrop = document.getElementById("gn-menu-backdrop");
      if (links && links.classList.contains("is-open")) {
        links.classList.remove("is-open");
        if (menuBtn) menuBtn.setAttribute("aria-expanded", "false");
        if (backdrop) {
          backdrop.classList.remove("is-open");
          backdrop.hidden = true;
        }
        document.body.style.overflow = "";
      }
      dropdown.classList.add("is-open");
      trigger.setAttribute("aria-expanded", "true");
    }

    trigger.addEventListener("click", function (e) {
      e.stopPropagation();
      if (dropdown.classList.contains("is-open")) close();
      else open();
    });

    document.addEventListener("click", function (e) {
      if (!nav.contains(e.target)) close();
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });
  }

  /**
   * Desktop: inset sticky global nav to the page content column edges.
   * Prefer measuring ``.page`` (Home = 1320/28) so Home / Training / etc.
   * match their own column; fall back to Training's 1000 + 24 geometry.
   */
  function _positionGlobalNav() {
    var gnav = document.querySelector(".global-nav");
    if (!gnav) return;
    if (window.innerWidth < 880) {
      gnav.style.removeProperty("padding-left");
      gnav.style.removeProperty("padding-right");
      return;
    }

    var page = document.querySelector("main.page, .page");
    if (page) {
      var rect = page.getBoundingClientRect();
      var cs = window.getComputedStyle(page);
      var pl = parseFloat(cs.paddingLeft) || 0;
      var pr = parseFloat(cs.paddingRight) || 0;
      var left = Math.max(0, rect.left + pl);
      var right = Math.max(0, document.documentElement.clientWidth - (rect.right - pr));
      gnav.style.paddingLeft = left + "px";
      gnav.style.paddingRight = right + "px";
      _shrinkNavInsetIfClipped(gnav);
      return;
    }

    var CONTENT_MAX = 1000;
    var PAD = 24;
    var vw = document.documentElement.clientWidth;
    var inset = Math.max(0, (vw - CONTENT_MAX) / 2) + PAD;
    gnav.style.paddingLeft = inset + "px";
    gnav.style.paddingRight = inset + "px";
    _shrinkNavInsetIfClipped(gnav);
  }

  // The page-column inset above is cosmetic (lines the nav up with the page's
  // own content edges) — it must never win over the nav's OWN links actually
  // fitting. A narrow centered column (e.g. Decisions' 760px page, centered
  // at 1440px) or a page with no `.page` wrapper at all (the CONTENT_MAX
  // fallback, e.g. Trends/Habits/Log) can compute an inset that leaves
  // `.gn-links` narrower than its own content. Because that row scrolls
  // (`overflow-x:auto`) with no visible scrollbar (`scrollbar-width:none`),
  // the overflow doesn't look like a scrollable list — it looks like the
  // last link got cut off mid-word ("Trends" rendering as "Tren"). Re-measure
  // after applying the inset and back off symmetrically, down to a 16px
  // floor, until the links row actually fits.
  var _NAV_PAD_FLOOR = 16;
  var _NAV_PAD_STEP = 8;

  function _shrinkNavInsetIfClipped(gnav) {
    var links = gnav.querySelector(".gn-links");
    if (!links) return;
    // Bounded, not unconditional: on the common case (nothing clipped) this
    // reads layout once and exits without writing a second style.
    for (var guard = 0; guard < 40 && links.scrollWidth > links.clientWidth + 1; guard++) {
      var pl = parseFloat(gnav.style.paddingLeft) || 0;
      var pr = parseFloat(gnav.style.paddingRight) || 0;
      if (pl <= _NAV_PAD_FLOOR && pr <= _NAV_PAD_FLOOR) break;
      gnav.style.paddingLeft = Math.max(_NAV_PAD_FLOOR, pl - _NAV_PAD_STEP) + "px";
      gnav.style.paddingRight = Math.max(_NAV_PAD_FLOOR, pr - _NAV_PAD_STEP) + "px";
    }
  }

  // `_positionGlobalNav` runs once at build time (and again on resize/load),
  // but `.gn-right` keeps changing size AFTER that: env.js fetches /api/env
  // and pops the UAT/LOCAL badge in asynchronously, the avatar swaps from a
  // text initial to an <img> once it loads, and the copy buttons' label
  // toggles ("Copy for Claude" ↔ "Building…"). None of those fire a resize
  // event, so the padding computed at build time can go stale and the links
  // row silently clips (this is what produced "Tren" instead of "Trends" on
  // /log, /habits, /trends — .gn-env was still empty/width:0 when the padding
  // was first computed). A ResizeObserver on `.gn-right` reacts to exactly
  // the content that can drift, without polling and without the feedback
  // loop a `.gn-links` observer would risk (nav padding doesn't feed back
  // into .gn-right's own size).
  function _observeNavRightWidth(nav) {
    if (!window.ResizeObserver) return;
    var right = nav.querySelector(".gn-right");
    if (!right) return;
    var ro = new ResizeObserver(function () {
      _positionGlobalNav();
    });
    ro.observe(right);
  }

  function _wireProfileMenu(nav) {
    var avatar = document.getElementById("nav-avatar");
    var menu = document.getElementById("gn-profile-menu");
    if (!avatar || !menu) return;

    function close() {
      menu.classList.remove("is-open");
      avatar.setAttribute("aria-expanded", "false");
    }

    avatar.addEventListener("click", function (e) {
      e.stopPropagation();
      var links = document.getElementById("gn-links");
      var menuBtn = document.getElementById("gn-menu-btn");
      var backdrop = document.getElementById("gn-menu-backdrop");
      if (links && links.classList.contains("is-open")) {
        links.classList.remove("is-open");
        if (menuBtn) menuBtn.setAttribute("aria-expanded", "false");
        if (backdrop) {
          backdrop.classList.remove("is-open");
          backdrop.hidden = true;
        }
        document.body.style.overflow = "";
      }
      var open = menu.classList.toggle("is-open");
      avatar.setAttribute("aria-expanded", open ? "true" : "false");
    });

    document.addEventListener("click", function (e) {
      if (!nav.contains(e.target)) close();
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });
  }

  function _wireMobileMenu(nav) {
    var menuBtn = document.getElementById("gn-menu-btn");
    var links = document.getElementById("gn-links");
    var backdrop = document.getElementById("gn-menu-backdrop");
    if (!menuBtn || !links) return;

    function close() {
      links.classList.remove("is-open");
      menuBtn.setAttribute("aria-expanded", "false");
      if (backdrop) {
        backdrop.classList.remove("is-open");
        backdrop.hidden = true;
      }
      document.body.style.overflow = "";
    }

    function open() {
      var profileMenu = document.getElementById("gn-profile-menu");
      if (profileMenu) profileMenu.classList.remove("is-open");
      var avatar = document.getElementById("nav-avatar");
      if (avatar) avatar.setAttribute("aria-expanded", "false");
      links.classList.add("is-open");
      menuBtn.setAttribute("aria-expanded", "true");
      if (backdrop) {
        backdrop.hidden = false;
        backdrop.classList.add("is-open");
      }
      if (window.innerWidth <= 880) document.body.style.overflow = "hidden";
    }

    menuBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      if (links.classList.contains("is-open")) close();
      else open();
    });

    if (backdrop) {
      backdrop.addEventListener("click", close);
    }

    links.addEventListener("click", function (e) {
      if (e.target.closest("a.gn-link")) close();
    });

    document.addEventListener("click", function (e) {
      if (!nav.contains(e.target)) close();
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });

    window.addEventListener("resize", function () {
      if (window.innerWidth > 880) close();
    });
  }

  var _navUserName = null;
  var _navUserId = null;

  function _navInitial() {
    return (
      _navUserName ? _navUserName.trim().charAt(0) || "U" : "U"
    ).toUpperCase();
  }

  function updateAvatar(bust) {
    var el = document.getElementById("nav-avatar");
    if (!el) return;
    var initial = _navInitial();
    el.innerHTML = "";
    el.textContent = initial;
    if (!_navUserId) return;
    var img = new Image();
    img.style.cssText =
      "width:36px;height:36px;object-fit:cover;display:block;";
    img.alt = initial;
    img.onload = function () {
      el.innerHTML = "";
      el.appendChild(img);
    };
    img.src =
      "/api/users/" +
      _navUserId +
      "/avatar" +
      (bust ? "?_t=" + Date.now() : "");
  }

  window.navRefreshAvatar = function () {
    updateAvatar(true);
  };

  var _PHASE_LABELS = {
    pulling_strava: "Syncing Strava…",
    pulling_stryd: "Syncing Stryd…",
    reconciling: "Reconciling activities…",
  };

  var _syncPollerUnsub = null;

  function buildSyncBar() {
    if (document.getElementById("sync-status-bar")) return;
    var style = document.createElement("style");
    style.id = "sync-bar-styles";
    style.textContent = SYNC_BAR_CSS;
    document.head.appendChild(style);
    var bar = document.createElement("div");
    bar.id = "sync-status-bar";
    bar.setAttribute("role", "status");
    bar.setAttribute("aria-live", "polite");
    var nav = document.querySelector(".global-nav");
    if (nav && nav.parentNode) {
      nav.parentNode.insertBefore(bar, nav.nextSibling);
    } else {
      document.body.appendChild(bar);
    }
  }

  function _ssbShow(state, html) {
    var bar = document.getElementById("sync-status-bar");
    if (!bar) return;
    bar.className = "ssb-state-" + state;
    bar.innerHTML = html;
  }

  function _ssbHide() {
    var bar = document.getElementById("sync-status-bar");
    if (bar) bar.className = "";
  }

  // A finished job keeps being returned by /api/sync/status until it ages
  // out of the registry (or the 10-min worker-run window), so without a
  // dismissal record the banner reappears on every page load. Remember the
  // dismissed job by its started_at (unique per job) in localStorage.
  var _SSB_DISMISSED_KEY = "ssb-dismissed-job";

  function _ssbJobKey(data) {
    return String(data.started_at || data.finished_at || "");
  }

  function _ssbMarkDismissed(data) {
    try {
      var k = _ssbJobKey(data);
      if (k) localStorage.setItem(_SSB_DISMISSED_KEY, k);
    } catch (e) {
      /* private mode — banner just stays session-transient */
    }
  }

  function _ssbIsDismissed(data) {
    try {
      var k = _ssbJobKey(data);
      return !!k && localStorage.getItem(_SSB_DISMISSED_KEY) === k;
    } catch (e) {
      return false;
    }
  }

  function _ssbRunning(data) {
    var label =
      _PHASE_LABELS[data.phase] ||
      (data.provider ? data.provider + " sync…" : "Syncing…");
    var count = "";
    if (data.current > 0) {
      count =
        data.total != null
          ? " (" + data.current + " / " + data.total + ")"
          : " (" + data.current + " activities)";
    }
    _ssbShow(
      "running",
      '<span class="ssb-spinner" aria-hidden="true"></span>' +
        '<span class="ssb-msg">' +
        escAttr(label) +
        escAttr(count) +
        "</span>" +
        '<button class="ssb-dismiss" type="button" aria-label="Dismiss">×</button>',
    );
    var dismiss = document.querySelector("#sync-status-bar .ssb-dismiss");
    if (dismiss)
      dismiss.addEventListener("click", function () {
        window.SyncPoller.stop();
        _ssbHide();
      });
  }

  function _ssbSuccess(data) {
    var n = data.items_synced != null ? data.items_synced : 0;
    _ssbShow(
      "success",
      '<span class="ssb-msg">Sync complete — ' +
        n +
        " workouts updated</span>" +
        '<button class="ssb-dismiss" type="button" aria-label="Dismiss">×</button>',
    );
    var dismiss = document.querySelector("#sync-status-bar .ssb-dismiss");
    if (dismiss)
      dismiss.addEventListener("click", function () {
        _ssbMarkDismissed(data);
        _ssbHide();
      });
    setTimeout(function () {
      var bar = document.getElementById("sync-status-bar");
      if (bar && bar.className === "ssb-state-success") {
        // Auto-hide counts as seen too — the same job must not reappear on
        // the next page load.
        _ssbMarkDismissed(data);
        _ssbHide();
      }
    }, 5000);
  }

  function _ssbError(data) {
    var msg = data.error || "Sync failed";
    _ssbShow(
      "error",
      '<span class="ssb-msg">' +
        escAttr(msg) +
        "</span>" +
        '<button class="ssb-dismiss" type="button">Dismiss</button>',
    );
    var dismiss = document.querySelector("#sync-status-bar .ssb-dismiss");
    if (dismiss)
      dismiss.addEventListener("click", function () {
        _ssbMarkDismissed(data);
        _ssbHide();
      });
  }

  function _onSyncPollerUpdate(data) {
    if (!data) return;
    if (data.status === "running") {
      _ssbRunning(data);
    } else if (data.status === "success" || data.status === "error") {
      if (_ssbIsDismissed(data)) {
        _ssbHide();
        return;
      }
      if (data.status === "success") _ssbSuccess(data);
      else _ssbError(data);
    } else {
      // Anything else — "idle" (job aged out of the registry, e.g. a
      // server restart mid-sync per docs/sync.md "Status lost on restart"),
      // "cancelled", "pending", or any status this bar doesn't render a
      // dedicated state for. SyncPoller stops polling as soon as status
      // leaves "running" (see lib/sync-poller.js), so without this branch
      // the bar was left frozen on its last "Syncing…" spinner forever —
      // found live during the S1 UX review by stubbing exactly this
      // transition. Hiding is the safe default: it matches what the athlete
      // actually knows (no sync is running right now).
      _ssbHide();
    }
  }

  window.syncBarRefresh = function () {
    window.SyncPoller.checkNow();
  };

  function init() {
    ensureIconFont();
    injectStyles();
    buildNav();
    buildSyncBar();
    window.addEventListener("resize", _positionGlobalNav);
    window.addEventListener("load", _positionGlobalNav);
    // One initial status check on load (picks up a sync started elsewhere);
    // SyncPoller only continues polling while a job is actually running.
    _syncPollerUnsub = window.SyncPoller.subscribe(_onSyncPollerUpdate);
    window.SyncPoller.checkNow();
    window.addEventListener("userReady", function (e) {
      _navUserName = (e.detail && e.detail.userName) || "";
      _navUserId = (e.detail && e.detail.userId) || null;
      updateAvatar(false);
    });
    // Self-fetch identity so the avatar initial is correct even on pages that
    // do not load user.js / dispatch userReady (e.g. the weight page).
    window
      .fetchCurrentUser()
      .then(function (u) {
        if (!u) return;
        _navUserName = u.name || _navUserName || "";
        _navUserId = u.id || _navUserId || null;
        updateAvatar(false);
      })
      .catch(function () {});
  }

  if (document.body) init();
  else document.addEventListener("DOMContentLoaded", init);
})();
