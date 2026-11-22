(function () {
  "use strict";
  var root = document.getElementById("wci-root");
  var weekLabel = document.getElementById("wci-week-label");
  var state = null;
  var esc = window.AppCommon.escapeHtml;
  function toast(msg) {
    var el = document.getElementById("rv-toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.add("is-visible");
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { el.classList.remove("is-visible"); }, 3200);
  }
  function fmtNA(field) {
    if (!field || field.status === "not_available" || field.value == null) return "—";
    return String(field.value) + (field.unit ? " " + field.unit : "");
  }
  function patch(body) {
    return fetch("/api/weekly-check-in", {
      method: "PATCH",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": window.AppCommon.csrfToken() },
      body: JSON.stringify(body),
    }).then(function (r) { if (!r.ok) throw new Error("Save failed"); return r.json(); });
  }
  function renderSnapshot(snap) {
    return '<div class="wci-snap-grid">' +
      '<div class="rv-tile"><span class="rv-subtitle">Sessions</span><span class="rv-mono">' + esc(fmtNA(snap.sessions_done)) + " / " + esc(fmtNA(snap.sessions_planned)) + '</span></div>' +
      '<div class="rv-tile"><span class="rv-subtitle">Week TSS</span><span class="rv-mono">' + esc(fmtNA(snap.week_tss)) + '</span></div>' +
      '<div class="rv-tile"><span class="rv-subtitle">Longest run</span><span class="rv-mono">' + esc(fmtNA(snap.longest_run_seconds)) + " / " + esc(fmtNA(snap.longest_run_target_seconds)) + '</span></div>' +
      '<div class="rv-tile"><span class="rv-subtitle">Weight avg (7d)</span><span class="rv-mono">' + esc(fmtNA(snap.avg_7d_kg)) + '</span></div>' +
      '<div class="rv-tile"><span class="rv-subtitle">Lunch yes</span><span class="rv-mono">' + esc(fmtNA(snap.lunch_rule_yes_count)) + '</span></div>' +
      '<div class="rv-tile"><span class="rv-subtitle">Steps avg</span><span class="rv-mono">' + esc(fmtNA(snap.steps_avg)) + '</span></div>' +
      '<div class="rv-tile"><span class="rv-subtitle">Foot blocks</span><span class="rv-mono">' + esc(fmtNA(snap.foot_blocks_done)) + " / " + esc(fmtNA(snap.runs_in_week)) + '</span></div>' +
      '<div class="rv-tile"><span class="rv-subtitle">Fuel rehearsals</span><span class="rv-mono">' + esc(fmtNA(snap.fuel_rehearsals_done)) + " / " + esc(fmtNA(snap.fuel_rehearsals_due)) + '</span></div></div>';
  }
  function renderChanges(items) {
    if (!items || !items.length) return '<p class="rv-subtitle">Nothing carried from last week.</p>';
    return items.map(function (c) {
      var st = c.status || "not_yet";
      return '<div class="wci-change" data-change="' + esc(c.id) + '"><span class="rv-label">' + esc(c.change_type) + '</span><p>' + esc(c.text) + '</p><div class="wci-status-row">' +
        ["done", "partly", "not_yet"].map(function (opt) {
          return '<button type="button" class="wci-status' + (st === opt ? " is-on" : "") + '" data-status="' + opt + '">' + opt.replace("_", " ") + '</button>';
        }).join("") + '</div></div>';
    }).join("");
  }
  function render(data) {
    state = data;
    var snap = data.snapshot || {};
    weekLabel.textContent = "Week " + (data.week_start || "");
    var self = data.self_report || {};
    var streak = data.streak_days_to_a_race;
    var streakHtml = streak == null ? '<p class="rv-subtitle">No A race scheduled.</p>' : '<p class="rv-subtitle">Days to next A race</p><div class="wci-streak">' + esc(streak) + '</div>';
    root.innerHTML = '<div class="wci-col"><section class="rv-card rv-stack" data-checkin-step="1"><span class="rv-label">Step 1</span>' + renderChanges(data.carried_changes) + '</section>' +
      '<section class="rv-card rv-stack" data-checkin-step="2"><div class="rv-row"><span class="rv-label">Step 2</span><button type="button" class="rv-btn rv-btn--secondary" id="wci-refresh">Refresh</button></div>' + renderSnapshot(snap) + '</section>' +
      '<section class="rv-card rv-stack" data-checkin-step="3"><span class="rv-label">Step 3</span>' +
      '<select id="wci-feet" class="rv-input" style="min-height:44px"><option value="">Feet —</option>' + [0,1,2,3].map(function(n){return '<option value="'+n+'"'+(self.feet===n?' selected':'')+'>'+n+'</option>';}).join('') + '</select>' +
      '<select id="wci-bed" class="rv-input" style="min-height:44px"><option value="">Bed bucket —</option>' + ["0-2","3-4","5-7"].map(function(b){return '<option value="'+b+'"'+(self.bed_bucket===b?' selected':'')+'>'+b+'</option>';}).join('') + '</select>' +
      '<select id="wci-motivation" class="rv-input" style="min-height:44px"><option value="">Motivation —</option>' + ["low","ok","high"].map(function(m){return '<option value="'+m+'"'+(self.motivation===m?' selected':'')+'>'+m+'</option>';}).join('') + '</select>' +
      '<textarea id="wci-note" rows="3" class="rv-input">' + esc(self.note || "") + '</textarea></section></div>' +
      '<div class="wci-col"><section class="rv-card rv-stack" data-checkin-step="4"><span class="rv-label">Step 4</span><pre class="wci-preview" id="wci-preview">' + esc(data.prompt_preview || "") + '</pre>' +
      '<button type="button" class="rv-btn rv-btn--primary" id="wci-copy" style="min-height:44px">Copy check-in</button><a class="rv-btn rv-btn--secondary" href="/coach#paste">Paste change list</a></section>' +
      '<section class="rv-card rv-card--soft rv-stack">' + streakHtml + '</section></div>';
    root.querySelectorAll(".wci-change").forEach(function (row) {
      row.querySelectorAll("[data-status]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var id = row.getAttribute("data-change");
          var status = btn.getAttribute("data-status");
          row.querySelectorAll("[data-status]").forEach(function (b) { b.classList.toggle("is-on", b === btn); });
          var items = (state.carried_changes || []).map(function (c) { return { id: c.id, status: c.id === id ? status : c.status }; });
          patch({ carried_changes: items }).then(function (d) { state = d; root.querySelector("#wci-preview").textContent = d.prompt_preview || ""; toast("Saved"); });
        });
      });
    });
    function saveScores() {
      var feet = root.querySelector("#wci-feet");
      var bed = root.querySelector("#wci-bed");
      var mot = root.querySelector("#wci-motivation");
      var note = root.querySelector("#wci-note");
      patch({ feet: feet.value === "" ? null : parseInt(feet.value, 10), bed_bucket: bed.value || null, motivation: mot.value || null, note: note.value })
        .then(function (d) { state = d; root.querySelector("#wci-preview").textContent = d.prompt_preview || ""; toast("Scores saved"); });
    }
    ["wci-feet", "wci-bed", "wci-motivation"].forEach(function (id) { root.querySelector("#" + id).addEventListener("change", saveScores); });
    root.querySelector("#wci-note").addEventListener("blur", saveScores);
    root.querySelector("#wci-copy").addEventListener("click", function () {
      navigator.clipboard.writeText(state.prompt_preview || "").then(function () { toast("Copied"); });
    });
    root.querySelector("#wci-refresh").addEventListener("click", function () {
      fetch("/api/weekly-check-in/refresh", { method: "POST", credentials: "same-origin", headers: { "X-CSRF-Token": window.AppCommon.csrfToken() } })
        .then(function (r) { return r.json(); }).then(render).then(function () { toast("Refreshed"); });
    });
  }
  document.addEventListener("DOMContentLoaded", function () {
    fetch("/api/weekly-check-in", { credentials: "same-origin" }).then(function (r) { return r.json(); }).then(render);
  });
})();
