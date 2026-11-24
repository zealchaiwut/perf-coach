(function () {
  "use strict";

  function loadPrefs() {
    return fetch("/api/user-preferences", { credentials: "include" }).then(function (r) {
      return r.json();
    });
  }

  loadPrefs().then(function (p) {
    var sel = document.getElementById("v2-settings-tss-method");
    if (sel && p.tss_method_default) sel.value = p.tss_method_default;
  });

  var save = document.getElementById("v2-settings-tss-save");
  if (save) {
    save.onclick = function () {
      var sel = document.getElementById("v2-settings-tss-method");
      var warn = document.getElementById("v2-settings-tss-warn");
      if (warn) warn.hidden = false;
      var body = { tss_method_default: sel.value };
      fetch("/api/user-preferences", {
        method: "PATCH",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      }).then(function (r) {
        if (r.ok && window.RevampUI) window.RevampUI.showToast("Saved — replay queued");
      });
    };
  }
})();