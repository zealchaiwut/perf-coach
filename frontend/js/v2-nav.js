// Shared primary nav for revamp pages + Settings gear with sync ring.
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
      '<button type="button" class="rv-tab rv-tab--util rv-sync-gear' + (settingsOn ? " on" : "") +
      '" id="rv-sync-gear" aria-haspopup="dialog" aria-expanded="false" aria-controls="rv-sync-pop"' +
      ' aria-label="Settings" title="Settings">' + GEAR_SVG + "</button></li>" +
      "</ul>";

    host.innerHTML = html;

    if (window.V2SyncStatus) {
      if (typeof window.V2SyncStatus.paint === "function" && window.V2SyncStatus.lastDetail()) {
        window.V2SyncStatus.paint(window.V2SyncStatus.lastDetail());
      } else if (typeof window.V2SyncStatus.poll === "function") {
        window.V2SyncStatus.poll();
      }
    } else {
      fetch("/api/sync/status", { credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (data) {
          var btn = document.getElementById("rv-sync-gear");
          if (!btn || !data) return;
          var overall = data.overall || "ok";
          var label = data.overall_label || "Settings";
          btn.className = "rv-tab rv-tab--util rv-sync-gear rv-sync-gear--" + overall +
            (settingsOn ? " on" : "");
          btn.setAttribute("aria-label", label);
          btn.title = label;
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

  function ensurePwaMeta() {
    if (!document.querySelector('link[rel="manifest"]')) {
      var man = document.createElement("link");
      man.rel = "manifest";
      man.href = "/manifest.webmanifest";
      document.head.appendChild(man);
    }
    if (!document.querySelector('meta[name="theme-color"]')) {
      var theme = document.createElement("meta");
      theme.name = "theme-color";
      theme.content = "#1f3b8a";
      document.head.appendChild(theme);
    }
    if (!document.querySelector('link[rel="apple-touch-icon"]')) {
      var icon = document.createElement("link");
      icon.rel = "apple-touch-icon";
      icon.href = "/icons/icon-192.png";
      document.head.appendChild(icon);
    }
  }

  function init() {
    ensurePwaMeta();
    var host = document.getElementById("rv-primary-nav");
    if (host) renderNav(host);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
