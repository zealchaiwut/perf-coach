// Shared primary nav for revamp pages + sync status dot.
(function () {
  "use strict";

  var GEAR_SVG =
    '<svg class="rv-settings-gear" viewBox="0 0 24 24" fill="none" aria-hidden="true">' +
    '<path d="M12 15.5a3.5 3.5 0 1 0 0-7 3.5 3.5 0 0 0 0 7Z" stroke="currentColor" stroke-width="1.8"/>' +
    '<path d="M19.4 13a7.8 7.8 0 0 0 .1-2l2-1.2-2-3.4-2.3.7a8 8 0 0 0-1.7-1L15 4h-4l-.5 2.1a8 8 0 0 0-1.7 1l-2.3-.7-2 3.4 2 1.2a7.8 7.8 0 0 0 0 2l-2 1.2 2 3.4 2.3-.7a8 8 0 0 0 1.7 1L11 20h4l.5-2.1a8 8 0 0 0 1.7-1l2.3.7 2-3.4-2-1.2Z" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>' +
    "</svg>";

  function currentArea() {
    var p = window.location.pathname || "";
    if (p.indexOf("/v2/home") === 0 || p === "/v2/home") return "home";
    if (p.indexOf("/v2/training") === 0) return "training";
    if (p.indexOf("/v2/performance") === 0) return "performance";
    if (p.indexOf("/v2/settings") === 0) return "settings";
    return "";
  }

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

  function worstDot(providers) {
    providers = providers || {};
    var order = { red: 3, amber: 2, green: 1 };
    var best = "green";
    ["strava", "stryd"].forEach(function (k) {
      var d = dotFromProvider(providers[k]);
      if (order[d] > order[best]) best = d;
    });
    return best;
  }

  function renderNav(host) {
    var invert = host.getAttribute("data-rv-nav-invert") != null;
    var area = currentArea();
    var ulClass = "rv-tabnav" + (invert ? " rv-tabnav--invert" : "");

    function tab(href, label, key) {
      var on = area === key;
      return (
        "<li><a class=\"rv-tab" + (on ? " on" : "") + "\" href=\"" + href + "\"" +
        (on ? ' aria-current="page"' : "") + ">" + label + "</a></li>"
      );
    }

    var settingsOn = area === "settings";
  var html =
      "<ul class=\"" + ulClass + "\">" +
      tab("/v2/home", "Home", "home") +
      tab("/v2/training/plan", "Training", "training") +
      tab("/v2/performance", "Performance", "performance") +
      '<li id="rv-admin-tab" hidden><a class="rv-tab" href="/v2/training/admin">Admin <span class="rv-admin-badge">ADMINS ONLY</span></a></li>' +
      '<li class="rv-tabnav-divider" aria-hidden="true"></li>' +
      '<li class="rv-nav-util">' +
      '<a class="rv-sync-dot-link" id="rv-sync-dot-link" href="/v2/settings#integrations" title="Integration status">' +
      '<span class="rv-sync-dot rv-sync-dot--amber" id="rv-sync-dot" aria-hidden="true"></span>' +
      '<span class="sr-only">Sync status</span></a></li>' +
      '<li class="rv-nav-util"><a class="rv-tab rv-tab--util' + (settingsOn ? " on" : "") + '" href="/v2/settings"' +
      (settingsOn ? ' aria-current="page"' : "") +
      ' aria-label="Settings">' + GEAR_SVG + '<span class="rv-settings-label">Settings</span></a></li>' +
      "</ul>";

    host.innerHTML = html;

    if (window.V2SyncStatus && typeof window.V2SyncStatus.poll === "function") {
      window.V2SyncStatus.poll();
    } else {
      fetch("/api/sync/status", { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          var dot = document.getElementById("rv-sync-dot");
          if (!dot || !data || !data.providers) return;
          var state = worstDot(data.providers);
          dot.className = "rv-sync-dot rv-sync-dot--" + state;
        })
        .catch(function () {});
    }

    var adminTab = document.getElementById("rv-admin-tab");
    if (adminTab && window.fetchCurrentUser) {
      if (adminTab.querySelector('[aria-current="page"]')) {
        adminTab.hidden = false;
        return;
      }
      window.fetchCurrentUser()
        .then(function (u) {
          if (u && u.is_admin) adminTab.hidden = false;
        })
        .catch(function () {});
    }
  }

  function init() {
    var host = document.getElementById("rv-primary-nav");
    if (host) renderNav(host);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();