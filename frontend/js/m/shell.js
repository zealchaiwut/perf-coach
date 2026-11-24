/* App shell: routes, SW registration, version toast. */
(function (global) {
  "use strict";

  function route() {
    var p = location.pathname || "";
    if (p.indexOf("/m/gym") === 0) return "gym";
    if (p.indexOf("/m/body") === 0) return "body";
    return "today";
  }

  function showToast(text, action, onClick) {
    var el = document.getElementById("m-toast");
    if (!el) return;
    el.hidden = false;
    el.innerHTML = "<span>" + text + '</span><button type="button" id="m-toast-act">' + action + "</button>";
    document.getElementById("m-toast-act").addEventListener("click", onClick);
  }

  function registerSw() {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).then(function (reg) {
      if (!navigator.serviceWorker.controller && reg.waiting) {
        reg.waiting.postMessage({ type: "SKIP_WAITING" });
        return;
      }
      if (reg.waiting) maybeToast(reg);
      reg.addEventListener("updatefound", function () {
        var w = reg.installing;
        if (!w) return;
        w.addEventListener("statechange", function () {
          if (w.state === "installed" && navigator.serviceWorker.controller) maybeToast(reg);
        });
      });
    });
  }

  function maybeToast(reg) {
    MStore.getMeta("session-active").then(function (active) {
      if (active) return;
      showToast("New version ready.", "Refresh", function () {
        if (reg.waiting) reg.waiting.postMessage({ type: "SKIP_WAITING" });
        location.reload();
      });
    });
  }

  function boot() {
    var r = route();
    var title = document.getElementById("m-title");
    document.body.classList.toggle("m-app--gym", r === "gym");
    if (title) title.textContent = r === "gym" ? "Gym" : r === "body" ? "Body" : "Today";
    MStatus.bind();
    MStore.getMeta("device-remembered").then(function (done) {
      if (done) return;
      return fetch("/api/auth/remember-device", {
        method: "POST",
        credentials: "same-origin",
        headers: (function () {
          var h = { "Content-Type": "application/json" };
          var m = document.cookie.match(/(?:^|; )csrf-token=([^;]+)/);
          if (m) h["X-CSRF-Token"] = decodeURIComponent(m[1]);
          return h;
        })(),
        body: JSON.stringify({ label: "Phone" })
      }).then(function (r) {
        if (r.ok) return MStore.setMeta("device-remembered", true);
      }).catch(function () {});
    });
    MSync.boot();
    if (r === "gym") MGym.mount();
    else if (r === "body") MBody.mount();
    else MToday.mount();
    registerSw();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", boot);
  else boot();

  global.MShell = { route: route, boot: boot };
})(window);
