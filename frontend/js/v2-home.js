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

  function kindDot(kind) {
    if (kind === "rest") return "#e2e8f0";
    if (kind === "race") return "#e4ff52";
    if (kind === "run" || (kind && kind.indexOf("run") === 0)) return "#fca5a5";
    if (kind === "strength" || kind === "plyo") return "#bbf7d0";
    return "#ddd6fe";
  }

  function renderWeek(host, week) {
    if (!host || !week) return;
    var bar = week.load_bar;
    var barHtml = "";
    if (bar) {
      barHtml =
        '<div class="rv-week-bar" role="presentation">' +
        '<span style="width:' + Math.min(bar.logged_pct, 100) + '%"></span>' +
        '<span style="width:' + Math.min(bar.planned_pct, 100) + '%"></span></div>';
    }
    var rows = (week.days || []).map(function (day) {
      var primary = (day.items && day.items[0]) || { name: "—", kind: "rest" };
      var st = primary.status || "planned";
      var done = st === "done";
      var chips = "";
      if (day.is_today) chips += '<span class="rv-chip rv-chip--today">TODAY</span>';
      if (done) chips += '<span class="rv-chip rv-chip--done">DONE</span>';
      if (primary.race_priority === "A") chips += '<span class="rv-chip rv-chip--race">A RACE</span>';
      var tss = primary.estimated_tss != null ? String(Math.round(primary.estimated_tss)) : "—";
      var cls = "rv-week-day";
      if (day.is_today) cls += " is-today";
      if (day.is_race_day) cls += " is-race-day";
      return '<div class="' + cls + '">' +
        '<div class="rv-week-day-label"><span class="rv-weekday">' + esc(day.weekday) + '</span>' +
        '<span class="rv-mono rv-day-num">' + esc(day.day_of_month) + "</span></div>" +
        '<div class="rv-week-day-body">' +
        '<span class="rv-kind-dot" style="background:' + kindDot(primary.kind) + '"></span>' +
        '<span class="rv-week-day-title' + (done ? " is-done" : "") + '">' + esc(primary.name) + "</span>" +
        chips + "</div>" +
        '<span class="rv-mono rv-subtitle">' + esc(tss) + "</span></div>";
    }).join("");
    host.innerHTML =
      '<div class="rv-row"><h2 id="rv-week-h" class="rv-label">This week</h2>' +
      '<a href="' + esc(week.plan_href) + '">Edit the week</a></div>' +
      (week.subtitle ? '<div class="rv-row"><span class="rv-subtitle">' + esc(week.subtitle) + "</span></div>" : "") +
      barHtml + '<div class="rv-week-days">' + rows + "</div>";
  }

  function renderNextRace(host, card) {
    if (!host) return;
    if (!card || !card.available) {
      host.hidden = true;
      host.innerHTML = "";
      return;
    }
    host.hidden = false;
    var r = card.race || {};
    host.innerHTML =
      '<div class="rv-row"><span class="rv-label">Next race</span><a href="' + esc(card.href) + '">All races</a></div>' +
      '<div class="rv-row" style="align-items:flex-end">' +
      '<div><p class="rv-title" style="font-size:1.1rem;margin:0">' + esc(r.name) + " · " + esc(r.race_date) + '</p>' +
      '<p class="rv-subtitle">A race</p></div>' +
      '<span class="rv-mono rv-countdown">' + esc(card.days_to_race) + '<span class="rv-subtitle"> d</span></span></div>' +
      '<div class="rv-home-tiles">' +
      tile("Goal", card.goal_time_label || "—") +
      tile("Estimate", card.estimate_time_label || "—") +
      tile("Range", card.range_label || "—") +
      "</div>";
  }

  function renderFocus(host, focus) {
    if (!host) return;
    if (!focus || !focus.axis) {
      host.innerHTML =
        '<div class="rv-row"><span class="rv-label">Status</span><a href="/v2/performance">Performance</a></div>' +
        '<p class="rv-subtitle">No fresh focus axis yet — see Performance for the full radar.</p>';
      return;
    }
    host.innerHTML =
      '<div class="rv-row"><span class="rv-label">Most room to grow</span><a href="' + esc(focus.href) + '">Performance</a></div>' +
      '<div class="rv-focus-banner">' +
      '<span class="rv-label" style="color:#e4ff52">Most room to grow</span>' +
      '<p class="rv-title" style="color:#fff;margin:4px 0">' + esc(focus.axis.replace(/_/g, " ")) +
      (focus.score != null ? ' <span class="rv-mono" style="font-size:1rem">' + esc(focus.score) + "/100</span>" : "") +
      "</p>" +
      '<p class="rv-subtitle" style="color:#d5def3">' + esc(focus.advice || "") + "</p></div>" +
      '<p class="rv-subtitle">Full status radar lives on Performance (not duplicated here).</p>';
  }

  function renderRecent(host, sessions) {
    if (!host) return;
    var rows = (sessions || []).map(function (s) {
      var meta = [s.relative_date];
      if (s.distance_km != null) meta.push(s.distance_km.toFixed(1) + " km");
      if (s.duration_min != null) meta.push(Math.round(s.duration_min) + " min");
      if (s.tss != null) meta.push(Math.round(s.tss) + " TSS");
      return '<a class="rv-recent-row" href="' + esc(s.log_href) + '">' +
        '<div><span class="rv-recent-title">' + esc(s.name) + '</span><span class="rv-mono rv-subtitle">' +
        esc(meta.join(" · ")) + "</span></div>" +
        '<span class="rv-chip rv-chip--who">' + esc(s.who) + "</span></a>";
    }).join("");
    host.innerHTML =
      '<div class="rv-row"><h2 id="rv-recent-h" class="rv-label">Recent sessions</h2>' +
      '<a href="/v2/training/log">Training log</a></div>' + rows;
  }

  function copyConsult(btn, endpoint) {
    if (window.NavCopy && typeof window.NavCopy.copyForClaude === "function") {
      window.NavCopy.copyForClaude(btn, endpoint, "consult copied");
      return;
    }
    btn.disabled = true;
    fetch(endpoint, { credentials: "same-origin" })
      .then(function (r) { return r.text(); })
      .then(function (text) {
        return navigator.clipboard.writeText(text);
      })
      .then(function () { btn.textContent = "Copied"; })
      .catch(function () { btn.textContent = "Copy failed"; })
      .finally(function () { btn.disabled = false; });
  }

  function renderCoach(host, coach) {
    if (!host || !coach) return;
    var checkin = coach.checkin || {};
    var review = coach.review_due;
    host.innerHTML =
      '<span class="rv-label">Coach</span>' +
      '<div class="rv-row" style="margin-top:8px">' +
      '<span class="rv-subtitle">Check-in: ' + esc(checkin.state === "done" ? "done this week" : "due") + "</span>" +
      '<button type="button" class="rv-btn rv-btn--secondary" id="rv-home-copy-consult">Copy for Claude</button></div>' +
      (review
        ? '<p class="rv-subtitle" style="margin-top:8px"><a href="/v2/performance#coach">Review due on Performance</a></p>'
        : "");
    var copyBtn = host.querySelector("#rv-home-copy-consult");
    if (copyBtn) {
      copyBtn.addEventListener("click", function () {
        copyConsult(copyBtn, coach.consult_endpoint || "/api/coach/consult");
      });
    }
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
        renderWeek(document.getElementById("rv-home-week"), data.this_week);
        renderRecent(document.getElementById("rv-home-recent"), data.recent_sessions);
        renderNextRace(document.getElementById("rv-home-next-race"), data.next_race);
        renderFocus(document.getElementById("rv-home-focus"), data.focus);
        renderCoach(document.getElementById("rv-home-coach"), data.coach);
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