// Shared GET /api/sync/status poller for the Settings-gear ring + Training Log pills.
(function (global) {
  "use strict";

  var FAST_MS = 5000;
  var SLOW_MS = 60000;
  var REUSE_MS = 5000;
  var FOCUS_MIN_MS = 30000;
  var timer = null;
  var lastPayload = null;
  var inflight = null;
  var lastFetchAt = 0;
  var lastFocusPollAt = 0;
  var popOpen = false;
  var popOpener = null;
  var bound = false;
  var lastPopHtml = "";

  function esc(s) {
    return global.AppCommon && global.AppCommon.escapeHtml
      ? global.AppCommon.escapeHtml(String(s))
      : String(s);
  }

  function toast(msg) {
    var el = document.getElementById("rv-toast") || document.getElementById("v2-toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.add("is-visible");
    setTimeout(function () { el.classList.remove("is-visible"); }, 3200);
  }

  function onSettingsPage() {
    return (window.location.pathname || "").indexOf("/v2/settings") === 0;
  }

  function providerName(key) {
    return key === "strava" ? "Strava" : "Stryd";
  }

  function syncUrl(key) {
    return key === "strava" ? "/api/strava/sync" : "/api/stryd/sync";
  }

  function startSync(url, label) {
    fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ full: false }),
    })
      .then(function (r) {
        if (r.status === 409) {
          toast("Sync already running");
          poll();
          return;
        }
        if (r.status === 422) {
          toast(label + " is not connected");
          return;
        }
        if (!r.ok) throw new Error("sync failed");
        toast("Syncing " + label + "\u2026");
        lastFetchAt = 0;
        if (lastPayload) {
          lastPayload.overall = "syncing";
          if (lastPayload.providers && lastPayload.providers[label.toLowerCase()]) {
            lastPayload.providers[label.toLowerCase()].ui_state = "syncing";
            lastPayload.providers[label.toLowerCase()].ui_label = "Syncing\u2026";
            lastPayload.providers[label.toLowerCase()].ui_action = null;
          }
          lastPayload.overall_label = "Settings \u00b7 syncing";
          paint(lastPayload);
        }
        if (global.SyncPoller) global.SyncPoller.start();
        poll();
      })
      .catch(function () { toast("Could not start " + label + " sync"); });
  }

  function startAll(providers) {
    providers = providers || {};
    ["strava", "stryd"].forEach(function (key) {
      var p = providers[key] || {};
      if (!p.connected) return;
      if (p.ui_action === "reauth" || p.ui_action === "reconnect") return;
      startSync(syncUrl(key), providerName(key));
    });
  }

  function ensurePopover() {
    var pop = document.getElementById("rv-sync-pop");
    if (pop) return pop;
    pop = document.createElement("div");
    pop.id = "rv-sync-pop";
    pop.className = "rv-sync-pop";
    pop.setAttribute("role", "dialog");
    pop.setAttribute("aria-label", "Sync status and settings");
    pop.hidden = true;
    document.body.appendChild(pop);
    return pop;
  }

  function popFocusables(pop) {
    return Array.prototype.filter.call(
      pop.querySelectorAll('a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])'),
      function (el) { return !el.hidden && el.offsetParent !== null; }
    );
  }

  function positionPopover() {
    var pop = document.getElementById("rv-sync-pop");
    var gear = document.getElementById("rv-sync-gear");
    if (!pop || !gear || pop.hidden) return;
    var rect = gear.getBoundingClientRect();
    pop.style.position = "fixed";
    pop.style.top = Math.round(rect.bottom + 8) + "px";
    if (window.innerWidth <= 600) {
      pop.style.left = "16px";
      pop.style.right = "16px";
      pop.style.width = "auto";
      pop.style.maxWidth = "none";
    } else {
      pop.style.right = Math.max(8, Math.round(window.innerWidth - rect.right)) + "px";
      pop.style.left = "auto";
      pop.style.width = "";
      pop.style.maxWidth = "";
    }
  }

  function paintGear(detail) {
    var btn = document.getElementById("rv-sync-gear");
    if (!btn) return;
    var overall = (detail && detail.overall) || "ok";
    var label = (detail && detail.overall_label) || "Settings";
    btn.className = "rv-tab rv-tab--util rv-sync-gear rv-sync-gear--" + overall +
      (onSettingsPage() ? " on" : "");
    btn.setAttribute("aria-label", label);
    btn.title = label;
    btn.setAttribute("aria-expanded", popOpen ? "true" : "false");
  }

  function paintPopover(detail) {
    var pop = document.getElementById("rv-sync-pop");
    if (!pop || pop.hidden) return;
    var providers = (detail && detail.providers) || {};
    var rows = ["strava", "stryd"].map(function (key) {
      var p = providers[key] || {};
      var state = p.ui_state || "ok";
      var right;
      if (p.ui_action === "reauth" || p.ui_action === "reconnect") {
        right = '<a class="rv-sync-pop__action" href="/v2/settings#integrations">' +
          esc(p.ui_label || (p.ui_action === "reauth" ? "Sign in again" : "Reconnect")) + "</a>";
      } else if (p.ui_action === "retry") {
        right = '<button type="button" class="rv-sync-pop__action rv-sync-pop__action-btn" data-sync-retry="' +
          key + '">' + esc(p.ui_label || "Retry") + "</button>";
      } else {
        right = '<span class="rv-sync-pop__time">' + esc(p.ui_label || "") + "</span>";
      }
      return '<div class="rv-sync-pop__row">' +
        '<span class="rv-sync-pop__dot rv-sync-pop__dot--' + esc(state) + '" aria-hidden="true"></span>' +
        "<span class=\"rv-sync-pop__name\">" + esc(providerName(key)) + "</span>" +
        right + "</div>";
    }).join("");
    var html = rows +
      '<div class="rv-sync-pop__foot">' +
      '<button type="button" class="rv-sync-pop__now" id="rv-sync-pop-now">Sync now</button>' +
      '<a class="rv-sync-pop__settings" href="/v2/settings">Settings \u203a</a></div>';
    if (html === lastPopHtml) return;
    lastPopHtml = html;
    pop.innerHTML = html;
  }

  function openPopover() {
    var gear = document.getElementById("rv-sync-gear");
    var pop = ensurePopover();
    popOpener = document.activeElement;
    popOpen = true;
    lastPopHtml = "";
    pop.hidden = false;
    paintPopover(lastPayload);
    positionPopover();
    if (gear) gear.setAttribute("aria-expanded", "true");
    var first = popFocusables(pop)[0];
    if (first) first.focus();
    if (!lastPayload) poll();
  }

  function closePopover() {
    var pop = document.getElementById("rv-sync-pop");
    var gear = document.getElementById("rv-sync-gear");
    var wasOpen = popOpen;
    popOpen = false;
    lastPopHtml = "";
    if (pop) pop.hidden = true;
    if (gear) gear.setAttribute("aria-expanded", "false");
    if (wasOpen && gear && gear.focus) gear.focus();
  }

  function togglePopover() {
    if (popOpen) closePopover();
    else openPopover();
  }

  function onDocClick(ev) {
    var gear = ev.target.closest && ev.target.closest("#rv-sync-gear");
    if (gear) {
      ev.preventDefault();
      ev.stopPropagation();
      togglePopover();
      return;
    }
    var pop = document.getElementById("rv-sync-pop");
    if (popOpen && pop && !pop.contains(ev.target)) closePopover();
  }

  function onDocKey(ev) {
    if (!popOpen) return;
    var pop = document.getElementById("rv-sync-pop");
    if (!pop) return;
    if (ev.key === "Escape") {
      ev.preventDefault();
      closePopover();
      return;
    }
    if (ev.key !== "Tab") return;
    var nodes = popFocusables(pop);
    if (!nodes.length) return;
    var first = nodes[0], last = nodes[nodes.length - 1];
    if (ev.shiftKey && document.activeElement === first) {
      ev.preventDefault();
      last.focus();
    } else if (!ev.shiftKey && document.activeElement === last) {
      ev.preventDefault();
      first.focus();
    }
  }

  function onPopClick(ev) {
    var retry = ev.target.closest && ev.target.closest("[data-sync-retry]");
    if (retry) {
      var key = retry.getAttribute("data-sync-retry");
      startSync(syncUrl(key), providerName(key));
      return;
    }
    if (ev.target.id === "rv-sync-pop-now" || (ev.target.closest && ev.target.closest("#rv-sync-pop-now"))) {
      startAll((lastPayload && lastPayload.providers) || {});
    }
  }

  function bindUi() {
    if (bound) return;
    bound = true;
    document.addEventListener("click", onDocClick);
    document.addEventListener("keydown", onDocKey);
    document.addEventListener("click", onPopClick);
    window.addEventListener("resize", positionPopover);
    window.addEventListener("scroll", positionPopover, true);
    window.addEventListener("popstate", closePopover);
  }

  function paint(detail) {
    lastPayload = detail || lastPayload;
    paintGear(lastPayload);
    paintPopover(lastPayload);
  }

  function emit(data) {
    var detail = {
      overall: (data && data.overall) || "ok",
      overall_label: (data && data.overall_label) || "Settings",
      status: (data && data.status) || "idle",
      providers: (data && data.providers) || {},
      raw: data,
    };
    lastPayload = detail;
    paint(detail);
    document.dispatchEvent(new CustomEvent("rv:sync-status", { detail: detail }));
  }

  function busy(detail) {
    if (!detail) return false;
    if (detail.overall === "syncing") return true;
    var st = String(detail.status || "").toLowerCase();
    return st === "running" || st === "pending";
  }

  function schedule() {
    if (timer) {
      clearTimeout(timer);
      timer = null;
    }
    if (document.hidden) return;
    var ms = busy(lastPayload) ? FAST_MS : SLOW_MS;
    timer = setTimeout(poll, ms);
  }

  function poll() {
    var now = Date.now();
    if (lastPayload && lastFetchAt && (now - lastFetchAt) < REUSE_MS) {
      paint(lastPayload);
      schedule();
      return Promise.resolve(lastPayload);
    }
    if (inflight) return inflight;
    inflight = fetch("/api/sync/status", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        lastFetchAt = Date.now();
        if (data) emit(data);
        return lastPayload;
      })
      .catch(function () { return lastPayload; })
      .then(function (detail) {
        inflight = null;
        schedule();
        return detail;
      });
    return inflight;
  }

  function onVisibility() {
    if (document.hidden) {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      return;
    }
    maybeFocusPoll();
  }

  function maybeFocusPoll() {
    var now = Date.now();
    if (lastFocusPollAt && (now - lastFocusPollAt) < FOCUS_MIN_MS) {
      schedule();
      return;
    }
    lastFocusPollAt = now;
    poll();
  }

  function init() {
    bindUi();
    ensurePopover();
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", function () {
      if (!document.hidden) maybeFocusPoll();
    });
    lastFocusPollAt = Date.now();
    poll();
  }

  global.V2SyncStatus = {
    poll: poll,
    paint: paint,
    startSync: startSync,
    startAll: startAll,
    lastDetail: function () { return lastPayload; },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
