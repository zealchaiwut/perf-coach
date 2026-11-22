// Shared GET /api/sync/status poller for v2 nav + Training Log pill.
(function (global) {
  "use strict";

  var FAST_MS = 3000;
  var SLOW_MS = 60000;
  var timer = null;
  var lastPayload = null;

  function dotFromProvider(p) {
    p = p || {};
    if (!p.connected) return "red";
    if (p.needs_reauth) return "amber";
    if (p.last_error) {
      var err = String(p.last_error || "").toLowerCase();
      if (err.indexOf("temporarily unavailable") !== -1) return "amber";
      return "red";
    }
    if (!p.last_success_at) return "amber";
    var last = new Date(p.last_success_at);
    if (isNaN(last.getTime())) return "amber";
    var ageH = (Date.now() - last.getTime()) / 3600000;
    if (ageH >= 48) return "amber";
    return "green";
  }

  function providerState(p) {
    p = p || {};
    if (p.running) return "syncing";
    if (p.needs_reauth) return "failed";
    if (p.last_error) {
      var err = String(p.last_error || "").toLowerCase();
      if (err.indexOf("temporarily unavailable") === -1) return "failed";
    }
    if (!p.connected) return "failed";
    var colour = dotFromProvider(p);
    if (colour === "red") return "failed";
    if (colour === "amber") return "stale";
    return "ok";
  }

  function overallState(providers, topStatus) {
    var st = String(topStatus || "").toLowerCase();
    var strava = providerState(providers.strava);
    var stryd = providerState(providers.stryd);
    if (st === "running" || st === "pending" || strava === "syncing" || stryd === "syncing") {
      return "syncing";
    }
    if (strava === "failed" || stryd === "failed") return "failed";
    if (strava === "stale" || stryd === "stale") return "stale";
    return "ok";
  }

  function ensureDot() {
    var existing = document.getElementById("rv-sync-dot");
    if (existing) return existing;
    var nav = document.querySelector(".rv-tabnav");
    if (!nav) return null;
    var li = document.createElement("li");
    li.className = "rv-nav-util";
    li.innerHTML =
      '<a class="rv-sync-dot-link" id="rv-sync-dot-link" href="/v2/settings#integrations" title="Integration status">' +
      '<span class="rv-sync-dot rv-sync-dot--amber" id="rv-sync-dot" aria-hidden="true"></span>' +
      '<span class="rv-sync-dot-label" id="rv-sync-dot-label" hidden></span>' +
      '<span class="sr-only">Sync status</span></a>';
    nav.appendChild(li);
    return document.getElementById("rv-sync-dot");
  }

  function ageLabel(iso) {
    if (!iso) return "";
    var last = new Date(iso);
    if (isNaN(last.getTime())) return "";
    var hours = (Date.now() - last.getTime()) / 3600000;
    if (hours < 24) return "today";
    var days = Math.round(hours / 24);
    if (days === 1) return "1 day ago";
    return days + " days ago";
  }

  function srText(detail) {
    var providers = detail.providers || {};
    var running = [];
    var failed = [];
    var stale = [];
    ["strava", "stryd"].forEach(function (key) {
      var p = providers[key] || {};
      var name = key === "strava" ? "Strava" : "Stryd";
      if (p.state === "syncing") running.push(name);
      else if (p.state === "failed") failed.push(name);
      else if (p.state === "stale") {
        var when = ageLabel(p.last_success_at);
        stale.push(when ? name + " " + when : name);
      }
    });
    if (running.length) return "Syncing " + running.join(" + ") + "…";
    if (failed.length) return failed.join(" and ") + " sync failed — tap to fix";
    if (stale.length) return stale.join(" · ") + " — tap to sync";
    return "All synced";
  }

  function paintDot(detail) {
    var dot = ensureDot();
    if (!dot) return;
    var cls = "rv-sync-dot";
    if (detail.overall === "syncing") cls += " rv-sync-dot--syncing";
    else if (detail.overall === "failed") cls += " rv-sync-dot--red";
    else if (detail.overall === "stale") cls += " rv-sync-dot--amber";
    else cls += " rv-sync-dot--green";
    dot.className = cls;
    var copy = srText(detail);
    var sr = dot.parentElement && dot.parentElement.querySelector(".sr-only");
    var link = document.getElementById("rv-sync-dot-link");
    if (link) {
      link.title = copy;
      link.setAttribute("aria-label", copy);
    }
    var label = document.getElementById("rv-sync-dot-label");
    if (label) {
      if (detail.overall === "ok") {
        label.hidden = true;
        label.textContent = "";
        if (sr) sr.textContent = copy;
      } else {
        label.hidden = false;
        label.textContent = copy;
        if (sr) sr.textContent = "";
      }
    } else if (sr) {
      sr.textContent = copy;
    }
  }

  function emit(data) {
    var providers = (data && data.providers) || {};
    var annotated = {
      strava: Object.assign({}, providers.strava || {}, { state: providerState(providers.strava) }),
      stryd: Object.assign({}, providers.stryd || {}, { state: providerState(providers.stryd) }),
    };
    var detail = {
      overall: overallState(annotated, data && data.status),
      status: (data && data.status) || "idle",
      providers: annotated,
      raw: data,
    };
    lastPayload = detail;
    paintDot(detail);
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
    fetch("/api/sync/status", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (data) emit(data);
      })
      .catch(function () {})
      .then(schedule);
  }

  function onVisibility() {
    if (document.hidden) {
      if (timer) {
        clearTimeout(timer);
        timer = null;
      }
      return;
    }
    poll();
  }

  function init() {
    ensureDot();
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener("focus", function () {
      if (!document.hidden) poll();
    });
    poll();
  }

  global.V2SyncStatus = {
    providerState: providerState,
    dotFromProvider: dotFromProvider,
    overallState: overallState,
    poll: poll,
    lastDetail: function () { return lastPayload; },
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
