(function () {
  "use strict";

  function csrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrf-token=([^;]*)/);
    if (m) return Promise.resolve(decodeURIComponent(m[1]));
    return fetch("/api/csrf-token", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (b) { return (b && b.csrf_token) || ""; });
  }

  function loadPrefs() {
    return fetch("/api/user-preferences", { credentials: "include" })
      .then(function (r) { return r.json(); });
  }

  function loadConnections() {
    return Promise.all([
      fetch("/api/strava/status", { credentials: "include" }).then(function (r) { return r.json(); }),
      fetch("/api/stryd/status", { credentials: "include" }).then(function (r) { return r.json(); }),
    ]).then(function (parts) {
      return { strava: parts[0], stryd: parts[1] };
    });
  }

  function renderConn(data) {
    var host = document.getElementById("v2-settings-conn-body");
    if (!host) return;
    var s1 = data.strava && data.strava.connected ? "Connected" : "Not connected";
    var stryd = data.stryd || {};
    var s2 = "Not connected";
    if (stryd.connected) {
      if (stryd.status === "reauth_required") s2 = "Needs your password again";
      else if (stryd.status === "unreachable") s2 = "Connected (Stryd unreachable)";
      else s2 = "Connected";
    }
    host.innerHTML =
      "<p class='rv-subtitle'>Strava — " + s1 + "</p>" +
      "<p class='rv-subtitle'>Stryd — " + s2 + "</p>" +
      '<a class="rv-btn rv-btn--secondary" href="/settings">Full integrations UI</a>';
  }

  loadPrefs().then(function (p) {
    var sel = document.getElementById("v2-settings-tss-method");
    if (sel && p.tss_method_default) sel.value = p.tss_method_default;
  });

  loadConnections().then(renderConn);

  var save = document.getElementById("v2-settings-tss-save");
  if (save) {
    save.onclick = function () {
      var sel = document.getElementById("v2-settings-tss-method");
      var warn = document.getElementById("v2-settings-tss-warn");
      if (warn) warn.hidden = false;
      csrfToken().then(function (token) {
        return fetch("/api/user-preferences", {
          method: "PATCH",
          credentials: "include",
          headers: {
            "Content-Type": "application/json",
            "X-CSRF-Token": token,
          },
          body: JSON.stringify({ tss_method_default: sel.value }),
        });
      }).then(function (r) {
        if (r.ok && window.RevampUI) window.RevampUI.showToast("Saved — replay queued");
      });
    };
  }
})();