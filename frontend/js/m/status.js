/* Status pill + Waiting to sync sheet. */
(function (global) {
  "use strict";

  function hhmm(ts) {
    if (!ts) return "";
    var d = new Date(ts);
    var h = d.getHours();
    var m = d.getMinutes();
    return (h < 10 ? "0" : "") + h + ":" + (m < 10 ? "0" : "") + m;
  }

  function opLabel(op) {
    if (!op) return "Change";
    if (op.op_type === "weigh_in") {
      var kg = op.payload && (op.payload.kg || op.payload.weight_kg);
      return "Weigh-in · " + (kg != null ? kg + " kg" : "");
    }
    if (op.op_type === "session_log") {
      var n = ((op.payload && op.payload.exercises) || []).reduce(function (a, ex) {
        return a + ((ex.sets && ex.sets.length) || 0);
      }, 0);
      var name = (op.payload && op.payload.name) || "Strength";
      return name + " · " + n + " sets logged";
    }
    if (op.op_type === "session_meta") return "Session notes";
    return op.op_type;
  }

  function paintPill(ops, sync) {
    var pill = document.getElementById("m-pill");
    if (!pill) return;
    var n = (ops || []).length;
    var conflicts = (ops || []).filter(function (o) { return o.conflict; });
    var failed = (ops || []).filter(function (o) { return (o.attempts || 0) >= 5; });
    pill.className = "m-pill";
    if (conflicts.length || failed.length) {
      pill.classList.add("m-pill--bad");
      pill.innerHTML = '<span class="m-dot m-dot--red"></span>Sync problem';
    } else if (sync && sync.waking) {
      pill.classList.add("m-pill--wake");
      pill.innerHTML = '<span class="m-dot m-dot--blue"></span>Waking the server…';
    } else if (n > 0 || !navigator.onLine) {
      pill.classList.add("m-pill--off");
      pill.innerHTML = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M2 8a15 15 0 0 1 20 0"/><path d="M5.5 12a10 10 0 0 1 13 0"/><path d="M3 3l18 18"/></svg>Offline · ' + n;
    } else {
      pill.classList.add("m-pill--ok");
      pill.innerHTML = '<span class="m-dot m-dot--green"></span>Synced ' + hhmm(sync && sync.lastSyncedAt || Date.now());
    }
  }

  function openSheet() {
    var sheet = document.getElementById("m-sheet");
    if (sheet) {
      sheet.hidden = false;
      renderSheet();
    }
  }
  function closeSheet() {
    var sheet = document.getElementById("m-sheet");
    if (sheet) sheet.hidden = true;
  }

  function renderSheet() {
    Promise.all([MStore.listOutbox(), Promise.resolve(MSync.snapshot())]).then(function (pair) {
      var ops = pair[0] || [];
      var sync = pair[1] || {};
      var list = document.getElementById("m-sheet-list");
      var wake = document.getElementById("m-sheet-wake");
      var conflicts = document.getElementById("m-sheet-conflicts");
      if (list) {
        list.innerHTML = ops.map(function (op) {
          var t = op.created_at ? hhmm(Date.parse(op.created_at)) : "";
          return '<div class="m-sheet-row"><span class="m-dot m-dot--amber"></span><span>' +
            opLabel(op).replace(/</g, "") + '</span><span class="m-mono">' + t + "</span></div>";
        }).join("") || '<div class="m-muted">Nothing waiting.</div>';
      }
      if (wake) {
        wake.hidden = !sync.waking;
        var elapsed = sync.wakingSince ? Math.round((Date.now() - sync.wakingSince) / 1000) : 0;
        var el = document.getElementById("m-wake-elapsed");
        if (el) el.textContent = elapsed + " s";
      }
      if (conflicts) {
        var bad = ops.filter(function (o) { return o.conflict; });
        conflicts.innerHTML = bad.map(function (op) {
          return '<div class="m-conflict"><div>' + opLabel(op).replace(/</g, "") +
            '</div><div class="m-conflict-actions">' +
            '<button type="button" data-keep="' + op.client_mutation_id + '">Keep phone version</button>' +
            '<button type="button" data-drop="' + op.client_mutation_id + '">Use server version</button></div></div>';
        }).join("");
      }
    });
  }

  function bind() {
    var pill = document.getElementById("m-pill");
    if (pill) pill.addEventListener("click", openSheet);
    var keep = document.getElementById("m-sheet-keep");
    if (keep) keep.addEventListener("click", closeSheet);
    var backdrop = document.getElementById("m-sheet-backdrop");
    if (backdrop) backdrop.addEventListener("click", closeSheet);
    document.addEventListener("click", function (e) {
      var keepBtn = e.target.closest("[data-keep]");
      var dropBtn = e.target.closest("[data-drop]");
      if (keepBtn) {
        MStore.listOutbox().then(function (ops) {
          var op = ops.filter(function (o) { return o.client_mutation_id === keepBtn.getAttribute("data-keep"); })[0];
          if (!op) return;
          op.conflict = false;
          op.base_version = op.server_version && op.server_version.version_id;
          return MStore.putOutbox(op).then(function () { MSync.flush(); renderSheet(); });
        });
      }
      if (dropBtn) {
        MStore.deleteOutbox(dropBtn.getAttribute("data-drop")).then(function () {
          MSync.flush();
          renderSheet();
        });
      }
    });
    global.addEventListener("pc:sync", function () {
      MStore.listOutbox().then(function (ops) {
        paintPill(ops, MSync.snapshot());
        var sheet = document.getElementById("m-sheet");
        if (sheet && !sheet.hidden) renderSheet();
      });
    });
    MStore.listOutbox().then(function (ops) { paintPill(ops, MSync.snapshot()); });
  }

  global.MStatus = { bind: bind, paintPill: paintPill, openSheet: openSheet, closeSheet: closeSheet, opLabel: opLabel };
})(window);
