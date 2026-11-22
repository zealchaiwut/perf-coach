// Revamp Home (P5-1): today hero, race plan panel, alert strip.
(function () {
  "use strict";

  var esc = window.AppCommon && window.AppCommon.escapeHtml ? window.AppCommon.escapeHtml : function (s) {
    return String(s == null ? "" : s);
  };

  function csrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrf-token=([^;]*)/);
    if (m) return Promise.resolve(decodeURIComponent(m[1]));
    return fetch("/api/csrf-token", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (b) { return (b && b.csrf_token) || ""; })
      .catch(function () { return ""; });
  }

  function fmtPace(spk) {
    if (spk == null) return "—";
    var m = Math.floor(spk / 60);
    var s = spk % 60;
    return m + ":" + (s < 10 ? "0" : "") + s + " /km";
  }

  function weekdayLong(iso) {
    try {
      var d = new Date(iso + "T12:00:00");
      return d.toLocaleDateString(undefined, { weekday: "long", month: "long", day: "numeric" });
    } catch (e) {
      return iso;
    }
  }

  function tile(label, value) {
    return '<div class="rv-tile"><span class="rv-subtitle" style="font-size:12px;font-weight:700">' + esc(label) +
      '</span><span class="rv-mono" style="font-size:17px;font-weight:600">' + esc(value) + "</span></div>";
  }

  function renderAlerts(host, alerts) {
    if (!alerts || !alerts.length) {
      host.hidden = true;
      host.innerHTML = "";
      return;
    }
    host.hidden = false;
    host.innerHTML = alerts.map(function (a) {
      return '<div class="rv-alert-strip" data-alert="' + esc(a.rule_id) + '">' +
        '<span><b>' + esc(a.rule_id === "review_due" ? "Review due." : "") + "</b> " + esc(a.message) + "</span>" +
        '<a href="' + esc(a.href) + '">' + esc(
          a.rule_id === "weekly_checkin" ? "Check in" :
          a.rule_id === "review_due" ? "Record outcome" :
          a.rule_id === "week_planned_ceiling" ? "Open plan" : "Fix"
        ) + "</a></div>";
    }).join("");
  }

  function renderHero(host, data) {
    var hero = data.hero || {};
    var session = hero.session;
    var racePlan = data.show_race_plan && data.race_plan;
    var inner = "";

    if (hero.state === "rest") {
      inner = '<p class="rv-title" style="font-size:1.35rem">Rest day</p><p class="rv-subtitle">Recovery is on the plan.</p>';
    } else if (hero.state === "empty") {
      inner = '<p class="rv-subtitle">' + esc(hero.empty_copy || "Nothing planned today.") +
        ' <a href="' + esc(hero.plan_link) + '">Open plan</a></p>';
    } else if (session) {
      var tiles = session.tiles || {};
      var tss = tiles.target_tss != null ? Math.round(tiles.target_tss) + " TSS" : "—";
      var dur = tiles.duration_min != null ? tiles.duration_min + " min" : "—";
      var done = session.status === "done";
      inner =
        '<div class="rv-home-hero-grid">' +
        '<div class="rv-home-hero-main">' +
        '<div class="rv-row" style="align-items:flex-start;gap:14px">' +
        '<span class="rv-home-bar" aria-hidden="true"></span>' +
        '<div><h2 class="rv-title" style="font-size:1.35rem;margin:0' + (done ? ";text-decoration:line-through;color:var(--rv-secondary)" : "") + '">' +
        esc(session.name) + "</h2>" +
        '<p class="rv-subtitle">' + esc(session.source_subtitle) +
        (session.notes ? " · " + esc(session.notes) : "") + "</p></div></div>" +
        '<div class="rv-home-tiles">' + tile("Target", tss) + tile("Duration", dur) + tile("Effort", tiles.effort || "—") + "</div>" +
        '<div class="rv-row" style="border-top:1px solid var(--rv-hairline);padding-top:12px">' +
        '<span class="rv-subtitle">' +
        (session.run_auto_complete_note ? esc(session.run_auto_complete_note) : (done ? "Done" : "")) +
        "</span>" +
        (session.mark_done_allowed
          ? '<button type="button" class="rv-btn rv-btn--accent" data-mark-done="' + esc(session.id) + '">Mark done</button>'
          : "") +
        "</div></div>";

      if (racePlan) {
        inner +=
          '<aside class="rv-home-race-plan" aria-labelledby="rv-race-plan-h">' +
          '<span id="rv-race-plan-h" class="rv-label">Race plan</span>' +
          '<div class="rv-row rv-home-race-row"><span style="font-weight:600">Fuel</span><span class="rv-mono rv-subtitle">' +
          esc(racePlan.fuel_timing) + "</span></div>" +
          '<div class="rv-row rv-home-race-row"><span style="font-weight:600">Target pace</span><span class="rv-mono rv-subtitle">' +
          esc(racePlan.target_pace_label || fmtPace(racePlan.target_pace_seconds_per_km)) + "</span></div>" +
          '<div class="rv-row rv-home-race-row"><span style="font-weight:600">First 10 km, no faster than</span><span class="rv-mono rv-subtitle">' +
          esc(racePlan.first_10k_cap_label || fmtPace(racePlan.first_10k_cap_seconds_per_km)) + "</span></div>" +
          '<p class="rv-warn-box">' + esc(racePlan.reminder_copy) + "</p></aside>";
      }
      inner += "</div>";
    }

    host.innerHTML =
      '<div class="rv-row"><span class="rv-label">Today</span><a href="' + esc(hero.plan_link || "/v2/training/plan") + '">Open in Training</a></div>' +
      inner;
  }

  function markDone(id) {
    return csrfToken().then(function (token) {
      var headers = {};
      if (token) headers["X-CSRF-Token"] = token;
      return fetch("/api/planned-sessions/" + encodeURIComponent(id) + "/mark-done", {
        method: "POST",
        credentials: "same-origin",
        headers: headers,
      });
    });
  }

  function load() {
    var alertsHost = document.getElementById("rv-home-alerts");
    var heroHost = document.getElementById("rv-home-today");
    var dateEl = document.getElementById("rv-home-date");
    fetch("/api/home/revamp", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(new Error("HTTP " + r.status)); })
      .then(function (data) {
        if (dateEl) dateEl.textContent = weekdayLong(data.as_of);
        var greet = document.getElementById("rv-home-greet");
        if (greet && data.greeting_name) greet.textContent = "Good morning, " + data.greeting_name;
        renderAlerts(alertsHost, data.alerts);
        renderHero(heroHost, data);
      })
      .catch(function (err) {
        if (heroHost) heroHost.innerHTML = '<p class="rv-subtitle">Could not load home — ' + esc(err.message) + "</p>";
      });
  }

  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-mark-done]");
    if (!btn) return;
    var psId = btn.getAttribute("data-mark-done");
    btn.disabled = true;
    markDone(psId).then(function () { return load(); }).catch(function () { btn.disabled = false; });
  });

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();