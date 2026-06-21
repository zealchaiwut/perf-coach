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

  // Every primary destination, shown inline in the bar (left → right).
  var LINKS = [
    { href: '/home',     label: 'Home',         icon: 'ti-home',         match: ['/', '/home', '/home.html'] },
    { href: '/log',      label: 'Training',     icon: 'ti-list-details', match: ['/log', '/training', '/training.html'] },
    { href: '/weight',   label: 'Weight',       icon: 'ti-scale',        match: ['/weight', '/weight.html'] },
    { href: '/habits',   label: 'Habits',       icon: 'ti-checklist',    match: ['/habits', '/habits.html'] },
    { href: '/trends',   label: 'Trends',       icon: 'ti-chart-line',   match: ['/trends', '/trends.html'], disabled: true },
    { href: '/calendar', label: 'Calendar',     icon: 'ti-calendar',     match: ['/calendar', '/calendar.html'], disabled: true }
    // Users is intentionally omitted — it's an admin-only page (see js/admin-gate.js).
  ];

  // Scoped under .global-nav so it cannot leak into page styles. Colours are the
  // literal values from the original home.html topnav (no CSS-var dependency).
  var CSS = [
    ".global-nav{background:linear-gradient(180deg,#eaf0fb 0%,#d8e3f5 100%);",
    "border-bottom:1px solid rgba(13,30,67,0.06);padding:0 24px;height:60px;",
    "display:flex;align-items:center;gap:20px;position:sticky;top:0;z-index:100;",
    "font-family:inherit;}",
    ".global-nav .gn-brand{display:flex;align-items:center;gap:10px;font-weight:700;",
    "font-size:16px;letter-spacing:-0.02em;color:#0b1530;text-decoration:none;flex-shrink:0;}",
    ".global-nav .gn-mark{width:30px;height:30px;border-radius:9px;",
    "background:linear-gradient(135deg,#6e90f0,#2b4ca8);color:#fff;display:flex;",
    "align-items:center;justify-content:center;font-size:16px;flex-shrink:0;}",
    ".global-nav .gn-links{display:flex;gap:4px;flex:1;min-width:0;overflow-x:auto;scrollbar-width:none;}",
    ".global-nav .gn-links::-webkit-scrollbar{display:none;}",
    ".global-nav .gn-menu-toggle{display:none;align-items:center;justify-content:center;",
    "width:40px;height:40px;padding:0;border-radius:10px;border:1.5px solid rgba(13,30,67,0.12);",
    "background:rgba(255,255,255,0.65);cursor:pointer;flex-shrink:0;color:#0b1530;}",
    ".global-nav .gn-menu-toggle:hover{background:rgba(255,255,255,0.92);}",
    '.global-nav .gn-menu-toggle[aria-expanded="true"]{background:#0b1530;border-color:#0b1530;}',
    '.global-nav .gn-menu-toggle[aria-expanded="true"] .gn-menu-bar{background:#fff;}',
    ".global-nav .gn-menu-bars{display:flex;flex-direction:column;gap:5px;width:18px;}",
    ".global-nav .gn-menu-bar{display:block;height:2.5px;border-radius:2px;background:#0b1530;}",
    ".global-nav .gn-link{padding:8px 14px;border-radius:999px;font-size:13.5px;font-weight:500;",
    "color:#5c6886;text-decoration:none;display:inline-flex;align-items:center;gap:7px;white-space:nowrap;flex-shrink:0;}",
    ".global-nav .gn-link i{font-size:15px;line-height:1;}",
    ".global-nav .gn-mark i{font-size:16px;line-height:1;}",
    ".global-nav .gn-link:hover{background:rgba(13,30,67,0.05);color:#0b1530;}",
    ".global-nav .gn-link.active{background:#0b1530;color:#fff;}",
    ".global-nav .gn-right{display:flex;align-items:center;gap:10px;flex-shrink:0;}",
    ".global-nav .gn-avatar{width:34px;height:34px;border-radius:50%;overflow:hidden;",
    "background:linear-gradient(135deg,#ffb88a,#d97a3a);color:#fff;display:flex;",
    "align-items:center;justify-content:center;font-weight:600;font-size:13px;flex-shrink:0;}",
    // Environment badge (UAT/LOCAL). Hidden on PRD and while empty (pre-load).
    ".global-nav .gn-env{font-size:11px;font-weight:700;letter-spacing:0.04em;color:#8a5a00;",
    "background:#ffe6b0;border:1px solid #f0c97a;padding:2px 8px;border-radius:999px;",
    "text-transform:uppercase;flex-shrink:0;line-height:1.5;}",
    ".global-nav .gn-env:empty{display:none;}",
    'body[data-env="prd"] .global-nav .gn-env{display:none;}',
    ".global-nav a.gn-avatar{cursor:pointer;text-decoration:none;transition:box-shadow 0.12s ease;}",
    ".global-nav a.gn-avatar:hover{box-shadow:0 0 0 2px rgba(13,30,67,0.18);}",
    ".global-nav a.gn-avatar.active{box-shadow:0 0 0 2px #0b1530;}",
    ".global-nav .gn-logout{padding:7px 14px;border-radius:999px;font-size:13px;font-weight:500;",
    "color:#5c6886;background:none;border:1.5px solid rgba(13,30,67,0.12);cursor:pointer;",
    "font-family:inherit;",
    "display:inline-flex;align-items:center;gap:6px;white-space:nowrap;}",
    ".global-nav .gn-logout:hover{background:rgba(13,30,67,0.05);color:#0b1530;border-color:rgba(13,30,67,0.2);}",
    ".global-nav .gn-logout:disabled{opacity:0.55;cursor:default;}",
    "@media (max-width:880px){.global-nav{padding:0 14px;height:56px;gap:12px;}",
    ".global-nav .gn-brand-text{display:none;}",
    ".global-nav .gn-logout .gn-logout-label{display:none;}}",
    ".global-nav .gn-link-disabled{opacity:0.42;color:#9aa3b2;pointer-events:none;cursor:not-allowed;}",
    ".global-nav .gn-link-disabled i{opacity:0.7;}",
    // Narrow widths: collapse inline tabs into a menu toggle with labeled dropdown.
    "@media (max-width:760px){",
    ".global-nav{padding:0 12px;gap:8px;}",
    ".global-nav .gn-brand-text{display:none;}",
    ".global-nav .gn-logout .gn-logout-label{display:none;}",
    ".global-nav .gn-menu-toggle{display:inline-flex;}",
    ".global-nav .gn-links{",
    "display:none;position:absolute;top:calc(100% + 6px);left:12px;right:12px;",
    "flex-direction:column;align-items:stretch;gap:2px;overflow:visible;",
    "background:#fff;border:1px solid rgba(13,30,67,0.1);border-radius:14px;",
    "box-shadow:0 12px 36px rgba(8,18,48,0.14);padding:8px;z-index:200;}",
    ".global-nav .gn-links.is-open{display:flex;}",
    ".global-nav .gn-link span{display:inline !important;}",
    ".global-nav .gn-link{width:100%;padding:12px 14px;border-radius:10px;font-size:14px;}",
    ".global-nav .gn-link i{font-size:18px;}",
    "}",
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
      "https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3/tabler-icons.min.css";
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

  function escAttr(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/"/g, "&quot;")
      .replace(/</g, "&lt;");
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
      '<a class="gn-brand" href="/home">' +
      '<span class="gn-mark"><i class="ti ti-activity-heartbeat" aria-hidden="true"></i></span>' +
      '<span class="gn-brand-text">perf-coach</span>' +
      "</a>" +
      '<button class="gn-menu-toggle" id="gn-menu-toggle" type="button" ' +
      'aria-expanded="false" aria-controls="gn-links" aria-label="Open navigation menu">' +
      '<span class="gn-menu-bars" aria-hidden="true">' +
      '<span class="gn-menu-bar"></span><span class="gn-menu-bar"></span>' +
      "</span>" +
      "</button>" +
      '<div class="gn-links" id="gn-links">' +
      linksHtml +
      "</div>" +
      '<div class="gn-right">' +
      '<span class="gn-env" id="env-label" aria-label="Environment"></span>' +
      '<a class="gn-avatar' +
      (path === "/settings" ? " active" : "") +
      '" id="nav-avatar" href="/settings"' +
      ' title="Profile and settings" aria-label="Profile and settings"' +
      (path === "/settings" ? ' aria-current="page"' : "") +
      ">U</a>" +
      '<button class="gn-logout" id="nav-logout" type="button" aria-label="Log out">' +
      '<i class="ti ti-logout" aria-hidden="true"></i>' +
      '<span class="gn-logout-label">Log out</span>' +
      "</button>" +
      "</div>";

    document.body.insertBefore(nav, document.body.firstChild);

    _wireMobileMenu(nav);

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

  function _closeMobileMenu() {
    var links = document.getElementById("gn-links");
    var toggle = document.getElementById("gn-menu-toggle");
    if (!links || !toggle) return;
    links.classList.remove("is-open");
    toggle.setAttribute("aria-expanded", "false");
    toggle.setAttribute("aria-label", "Open navigation menu");
  }

  function _wireMobileMenu(nav) {
    var toggle = document.getElementById("gn-menu-toggle");
    var links = document.getElementById("gn-links");
    if (!toggle || !links) return;

    toggle.addEventListener("click", function (e) {
      e.stopPropagation();
      var open = links.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.setAttribute(
        "aria-label",
        open ? "Close navigation menu" : "Open navigation menu",
      );
    });

    links.querySelectorAll("a.gn-link").forEach(function (a) {
      a.addEventListener("click", _closeMobileMenu);
    });

    document.addEventListener("click", function (e) {
      if (!nav.contains(e.target)) _closeMobileMenu();
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") _closeMobileMenu();
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
      "width:34px;height:34px;object-fit:cover;display:block;";
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

  var _syncTimer = null;

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
        _syncStopPoll();
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
    if (dismiss) dismiss.addEventListener("click", _ssbHide);
    setTimeout(function () {
      var bar = document.getElementById("sync-status-bar");
      if (bar && bar.className === "ssb-state-success") _ssbHide();
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
    if (dismiss) dismiss.addEventListener("click", _ssbHide);
  }

  function _syncStopPoll() {
    if (_syncTimer) {
      clearInterval(_syncTimer);
      _syncTimer = null;
    }
  }

  function _doPoll() {
    fetch("/api/sync/status")
      .then(function (res) {
        return res.ok ? res.json() : null;
      })
      .then(function (data) {
        if (!data) {
          _syncStopPoll();
          return;
        }
        if (data.status === "running") {
          _ssbRunning(data);
          if (!_syncTimer) _syncTimer = setInterval(_doPoll, 4000);
        } else {
          _syncStopPoll();
          if (data.status === "success") _ssbSuccess(data);
          else if (data.status === "error") _ssbError(data);
        }
      })
      .catch(function () {
        _syncStopPoll();
      });
  }

  window.syncBarRefresh = function () {
    _syncStopPoll();
    _doPoll();
  };

  function init() {
    ensureIconFont();
    injectStyles();
    buildNav();
    buildSyncBar();
    _doPoll();
    window.addEventListener("userReady", function (e) {
      _navUserName = (e.detail && e.detail.userName) || "";
      _navUserId = (e.detail && e.detail.userId) || null;
      updateAvatar(false);
    });
    // Self-fetch identity so the avatar initial is correct even on pages that
    // do not load user.js / dispatch userReady (e.g. the weight page).
    fetch("/api/auth/me")
      .then(function (r) {
        return r.ok ? r.json() : null;
      })
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
