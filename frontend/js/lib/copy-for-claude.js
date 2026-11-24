// Consult/check-in copy helper for revamp pages that do not load nav.js.
(function () {
  "use strict";
  var CONSULT_ENDPOINT = "/api/coach/consult";

  function copy(btn, opts) {
    opts = opts || {};
    var endpoint = opts.endpoint || CONSULT_ENDPOINT;
    var toast = typeof opts.toast === "function" ? opts.toast : function () {};
    var okMsg = opts.okMsg || "Check-in copied — paste it into Claude";
    if (btn) btn.disabled = true;
    toast("Building check-in…");
    return fetch(endpoint, { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("export failed (" + r.status + ")");
        return r.text();
      })
      .then(function (text) {
        if (!text || !String(text).trim()) throw new Error("export was empty");
        return navigator.clipboard.writeText(text);
      })
      .then(function () { toast(okMsg); })
      .catch(function (e) { toast("Could not copy check-in: " + (e && e.message ? e.message : "error")); })
      .then(function () { if (btn) btn.disabled = false; });
  }

  window.CopyForClaude = {
    CONSULT_ENDPOINT: CONSULT_ENDPOINT,
    copy: copy,
  };
})();
