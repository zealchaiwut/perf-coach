(function () {
  "use strict";
  var kind = document.body && document.body.getAttribute("data-revamp-archived");
  if (!kind) return;
  fetch("/api/revamp-ui", { credentials: "same-origin" })
    .then(function (r) { return r.ok ? r.json() : { enabled: false }; })
    .then(function (b) {
      if (!b || !b.enabled) return;
      var text =
        kind === "habits"
          ? "Habits checklist is retired in the new UI. Your habit records are unchanged in the database."
          : "The Weight tab is retired from navigation in the new UI. Entries below are unchanged and still feed Performance metrics.";
      var bar = document.createElement("div");
      bar.setAttribute("role", "status");
      bar.style.cssText =
        "background:#fff4d8;color:#6b4408;padding:12px 16px;font:600 14px/1.45 system-ui,sans-serif;border-bottom:1px solid #e8c878";
      bar.textContent = text;
      document.body.insertBefore(bar, document.body.firstChild);
    })
    .catch(function () {});
})();