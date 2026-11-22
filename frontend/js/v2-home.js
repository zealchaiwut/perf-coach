// Revamp Home (P5-1): today hero, race plan panel, alert strip.
// APIs: GET /api/home/revamp (primary), GET /api/home/weight-card, GET /api/body-log/weekly-rollup.
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

  function patchBodyLog(payload) {
    return csrfToken().then(function (token) {
      var headers = { "Content-Type": "application/json" };
      if (token) headers["X-CSRF-Token"] = token;
      return fetch("/api/body-log", {
        method: "PATCH",
        credentials: "same-origin",
        headers: headers,
        body: JSON.stringify(payload),
      });
    });
  }

  function dailyBasicsHtml(basics) {
    basics = basics || {};
    var w = basics.weight_kg;
    var wLogged = w != null ? '<span class="rv-daily-logged">Logged</span>' : "";
  return (
      '<aside class="rv-daily-basics" aria-label="Daily basics">' +
      '<span class="rv-label">Daily basics</span>' +
      '<div class="rv-daily-row"><label for="rv-db-weight">Morning weight (kg)</label>' +
      '<div><input type="number" step="0.1" min="40" max="200" class="rv-daily-input" id="rv-db-weight" data-bl-field="weight_kg" value="' +
      (w != null ? esc(w) : "") + '" inputmode="decimal" />' + wLogged + "</div></div>" +
      '<div class="rv-daily-row"><span>Lunch rule</span>' +
      '<div class="rv-daily-toggle" data-bl-field="lunch_rule">' +
      '<button type="button" data-val="true" class="' + (basics.lunch_rule === true ? "is-on" : "") + '">Yes</button>' +
      '<button type="button" data-val="false" class="' + (basics.lunch_rule === false ? "is-on" : "") + '">No</button>' +
      "</div></div>" +
      '<div class="rv-daily-row"><label for="rv-db-steps">Steps</label>' +
      '<input type="number" min="0" step="1" class="rv-daily-input" id="rv-db-steps" data-bl-field="steps" value="' +
      (basics.steps != null ? esc(basics.steps) : "") + '" inputmode="numeric" /></div>' +
      '<div class="rv-daily-row"><span>Feet</span>' +
      '<div class="rv-daily-feet rv-daily-toggle" data-bl-field="feet">' +
      [0, 1, 2, 3].map(function (n) {
        return '<button type="button" data-val="' + n + '" class="' + (basics.feet === n ? "is-on" : "") + '">' + n + "</button>";
      }).join("") +
      "</div></div></aside>"
    );
  }

  function bindDailyBasics(host, reload) {
    if (!host) return;
    var weight = host.querySelector("#rv-db-weight");
    if (weight) {
      weight.addEventListener("change", function () {
        var v = parseFloat(weight.value, 10);
        if (!v || v < 40 || v > 200) return;
        patchBodyLog({ weight_kg: v }).then(function () { return reload(); });
      });
    }
    var steps = host.querySelector("#rv-db-steps");
    if (steps) {
      steps.addEventListener("change", function () {
        var v = parseInt(steps.value, 10);
        if (isNaN(v) || v < 0) return;
        patchBodyLog({ steps: v }).then(function () { return reload(); });
      });
    }
    host.querySelectorAll(".rv-daily-toggle").forEach(function (group) {
      var field = group.getAttribute("data-bl-field");
      group.querySelectorAll("button").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var raw = btn.getAttribute("data-val");
          var payload = {};
          if (field === "lunch_rule") payload.lunch_rule = raw === "true";
          else if (field === "feet") payload.feet = parseInt(raw, 10);
          patchBodyLog(payload).then(function () { return reload(); });
        });
      });
    });
  }

  function supportBlocksHtml(blocks) {
    return (blocks || []).map(function (b) {
      var done = b.status === "done";
      return '<div class="rv-support-line">' +
        '<span' + (done ? ' style="text-decoration:line-through;color:var(--rv-secondary)"' : "") + ">" + esc(b.name) + "</span>" +
        (done ? '<span class="rv-chip rv-chip--done">DONE</span>' : (
          b.mark_done_allowed
            ? '<button type="button" class="rv-btn rv-btn--secondary" data-mark-done="' + esc(b.id) + '">Done</button>'
            : ""
        )) +
        "</div>";
    }).join("");
  }

  function syncAgeLabel(syncSummary) {
    syncSummary = syncSummary || {};
    var states = [syncSummary.strava, syncSummary.stryd].filter(Boolean);
    var best = null;
    states.forEach(function (s) {
      if (!s || !s.last_success_at) return;
      var t = Date.parse(s.last_success_at);
      if (!isNaN(t) && (best == null || t > best)) best = t;
    });
    if (best == null) return "";
    var hrs = Math.round((Date.now() - best) / 3600000);
    if (hrs < 1) return " · last sync just now";
    return " · last sync " + hrs + " h ago";
  }

  function renderHeaderPill(pillText) {
    var el = document.getElementById("rv-home-race-pill");
    if (!el) return;
    if (!pillText) {
      el.hidden = true;
      el.textContent = "";
      return;
    }
    el.hidden = false;
    el.textContent = pillText;
  }

  function renderDailyBasicsCard(host, basics, reload) {
    if (!host) return;
    host.hidden = false;
    host.innerHTML = dailyBasicsHtml(basics || {});
    bindDailyBasics(host, reload || load);
  }

  function renderHero(host, data, reload) {
    var hero = data.hero || {};
    var session = hero.session;
    var racePlan = data.show_race_plan && data.race_plan;
    var inner = "";
    var gridCls = "rv-home-hero-grid";
    var rightPanel = "";

    if (hero.state === "rest") {
      inner =
        '<div class="' + gridCls + '"><div class="rv-home-hero-main">' +
        '<p class="rv-title" style="font-size:1.35rem">Rest day</p><p class="rv-subtitle">Recovery is on the plan.</p></div>' +
        (racePlan ? "" : "</div>");
    } else if (hero.state === "empty") {
      inner =
        '<div class="' + gridCls + (racePlan ? "" : " rv-home-hero-grid--single") + '">' +
        '<div class="rv-home-hero-main">' +
        '<p class="rv-subtitle">' + esc(hero.empty_copy || "Nothing planned today.") +
        ' <a href="' + esc(hero.plan_link) + '">Open plan</a></p></div>';
    } else if (session) {
      var tiles = session.tiles || {};
      var tss = tiles.target_tss != null ? Math.round(tiles.target_tss) + " TSS" : "—";
      var dur = tiles.duration_min != null ? tiles.duration_min + " min" : "—";
      var done = session.status === "done";
      var syncNote = session.run_auto_complete_note
        ? esc(session.run_auto_complete_note) + syncAgeLabel(data.sync_summary)
        : (done ? "Done" : "");
      inner =
        '<div class="' + gridCls + '">' +
        '<div class="rv-home-hero-main">' +
        '<div class="rv-row" style="align-items:flex-start;gap:14px">' +
        '<span class="rv-home-bar" aria-hidden="true"></span>' +
        '<div><h2 class="rv-title rv-home-session-title' + (done ? " is-done" : "") + '">' +
        esc(session.name) + "</h2>" +
        '<p class="rv-subtitle">' + esc(session.source_subtitle) +
        (session.notes ? " · " + esc(session.notes) : "") + "</p></div></div>" +
        supportBlocksHtml(session.support_blocks) +
        '<div class="rv-home-tiles">' + tile("Target", tss) + tile("Duration", dur) + tile("Effort", tiles.effort || "—") + "</div>" +
        '<div class="rv-row" style="border-top:1px solid var(--rv-hairline);padding-top:12px">' +
        '<span class="rv-subtitle">' + syncNote + "</span>" +
        (session.mark_done_allowed
          ? '<button type="button" class="rv-btn rv-btn--accent" data-mark-done="' + esc(session.id) + '">Mark done</button>'
          : "") +
        "</div></div>";
    }

    if (racePlan) {
      var fuelMeta = racePlan.fuel_rehearsal_count != null
        ? "rehearsed " + racePlan.fuel_rehearsal_count + "×"
        : "";
      rightPanel =
        '<aside class="rv-home-race-plan" aria-labelledby="rv-race-plan-h">' +
        '<span id="rv-race-plan-h" class="rv-label">Race plan</span>' +
        '<div class="rv-row rv-home-race-row"><span style="font-weight:600">' +
        esc(racePlan.fuel_timing || "Fuel") + '</span><span class="rv-mono rv-subtitle">' +
        esc(fuelMeta) + "</span></div>" +
        '<div class="rv-row rv-home-race-row"><span style="font-weight:600">Target pace</span><span class="rv-mono rv-subtitle">' +
        esc(racePlan.target_pace_label || fmtPace(racePlan.target_pace_seconds_per_km)) + "</span></div>" +
        '<div class="rv-row rv-home-race-row"><span style="font-weight:600">First 10 km, no faster than</span><span class="rv-mono rv-subtitle">' +
        esc(racePlan.first_10k_cap_label || fmtPace(racePlan.first_10k_cap_seconds_per_km)) + "</span></div>" +
        '<p class="rv-warn-box">' + esc(racePlan.reminder_copy) + "</p></aside>";
      if (inner) inner += rightPanel + "</div>";
      else {
        inner = '<div class="' + gridCls + '"><div class="rv-home-hero-main"></div>' + rightPanel + "</div>";
      }
    } else if (inner) {
      inner += "</div>";
    }

    host.innerHTML =
      '<div class="rv-row"><span class="rv-label">Today</span><a href="' + esc(hero.plan_link || "/v2/training/plan") + '">Open in Training</a></div>' +
      inner;
  }

  function rateChipLabel(chip) {
    if (chip === "in_range") return "In range";
    if (chip === "too_fast") return "Too fast";
    if (chip === "slow") return "Slow";
    return "—";
  }

  var GET_HOME_WEIGHT_CARD = "/api/home/weight-card";
  var GET_BODY_LOG_WEEKLY = "/api/body-log/weekly-rollup";

  function fetchWeightCardFallback() {
    return fetch(GET_HOME_WEIGHT_CARD, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; });
  }

  function renderWeightCard(host, card) {
    if (!host || !card) return;
    if (card.seven_day_avg_kg == null && !(card.sparkline_6w || []).some(function (p) { return p.value != null; })) {
      host.hidden = true;
      host.innerHTML = "";
      return;
    }
    host.hidden = false;
    var avg = card.seven_day_avg_kg;
    var rate = card.weekly_rate_kg;
    var chip = card.rate_chip || "unknown";
    var chipCls = chip === "in_range" ? "is-range" : chip === "too_fast" ? "is-fast" : "is-slow";
    var spark = (card.sparkline_6w || []).filter(function (p) { return p.value != null; });
    var maxV = spark.reduce(function (m, p) { return Math.max(m, p.value); }, 0) || 1;
    var bars = spark.map(function (p) {
      var h = Math.round((p.value / maxV) * 100);
      return '<span style="height:' + h + '%" title="' + esc(p.date) + '"></span>';
    }).join("");
    host.innerHTML =
      '<div class="rv-home-weight-head">' +
      '<p class="rv-label" id="rv-weight-h">Weight</p>' +
      '<span class="rv-weight-chip ' + chipCls + '">' + esc(rateChipLabel(chip)) +
      (rate != null ? " · " + esc(rate) + " kg/wk" : "") + "</span>" +
      '<span class="rv-subtitle">' + esc(card.phase_label) + "</span></div>" +
      '<p class="rv-title" style="margin:8px 0 0;font-size:1.5rem">' +
      (avg != null ? esc(avg) + " kg" : "—") +
      '<span class="rv-subtitle" style="margin-left:8px;font-size:0.9rem">7-day avg</span></p>' +
      (card.eat_more_flag ? '<p class="rv-weight-eat-more">EAT MORE — ease the deficit.</p>' : "") +
      '<div class="rv-weight-spark" aria-hidden="true">' + bars + "</div>";
  }

  function kindDot(kind) {
    if (kind === "rest") return "#e2e8f0";
    if (kind === "race") return "#e4ff52";
    if (kind === "run" || (kind && kind.indexOf("run") === 0)) return "#fca5a5";
    if (kind === "strength" || kind === "plyo") return "#bbf7d0";
    return "#ddd6fe";
  }

  function ladderBarHeight(actual, scaleMax) {
    if (actual == null || !scaleMax) return 4;
    return Math.max(4, Math.round((actual / scaleMax) * 100));
  }

  function renderLadder(host, ladder) {
    if (!host) return;
    if (!ladder || !ladder.available) {
      host.hidden = true;
      host.innerHTML = "";
      return;
    }
    host.hidden = false;
    var scale = ladder.scale_max_seconds || ladder.need_seconds || 1;
    var chip =
      (ladder.qualifying_count != null ? ladder.qualifying_count : 0) +
      " / " +
      (ladder.qualifying_count_target || 2) +
      " at " +
      esc(ladder.need_label || "3:30");
    var red = ladder.red_state ? " rv-ladder--red" : "";
    var bars = (ladder.weeks || []).map(function (w) {
      var pct = ladderBarHeight(w.actual_seconds, scale);
      var cls = "rv-ladder-bar rv-ladder-bar--" + esc(w.state || "done");
      if (w.race_role) cls += " rv-ladder-bar--race";
      var style = "height:" + pct + "%";
      if (w.bar_color) style += ";background:" + esc(w.bar_color);
      if (w.state === "current") style += ";outline:2px solid var(--rv-ink)";
      return '<div class="' + cls + '" title="' + esc((w.actual_label || "—") + " / " + (w.target_label || "—")) + '" style="' + style + '"></div>';
    }).join("");
    host.innerHTML =
      '<div class="rv-row rv-ladder-head' + red + '">' +
      '<h2 id="rv-ladder-h" class="rv-label">Long-run ladder</h2>' +
      '<span class="rv-chip">' + chip + "</span></div>" +
      '<p class="rv-subtitle">' + esc(ladder.a_race_name) + " · " + esc(ladder.a_race_date) + "</p>" +
      '<div class="rv-ladder-chart" role="img" aria-label="Weekly longest run bars">' + bars + "</div>" +
      '<div class="rv-ladder-refs rv-mono rv-subtitle">' +
      '<span>Need ' + esc(ladder.need_label || "3:30") + "</span>" +
      (ladder.prior_a_peak_label
        ? '<span>Prior A peak ' + esc(ladder.prior_a_peak_label) + "</span>"
        : "") +
      "</div>";
  }

  function renderWeek(host, week) {
    if (!host || !week) return;
    var bar = week.load_bar;
    var barHtml = "";
    if (bar) {
      barHtml =
        '<div class="rv-row rv-week-load-row"><span class="rv-subtitle">' + esc(week.subtitle || "") + '</span>' +
        '<span class="rv-mono rv-week-tss">' + esc(bar.tss_label || "") + "</span></div>" +
        '<div class="rv-week-bar" role="presentation">' +
        '<span style="width:' + Math.min(bar.logged_pct, 100) + '%"></span>' +
        '<span style="width:' + Math.min(bar.planned_pct, 100) + '%"></span>' +
        '<span style="width:' + Math.min(bar.remaining_pct || 0, 100) + '%"></span></div>';
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
      var note = primary.notes ? '<span class="rv-subtitle rv-week-day-note">' + esc(primary.notes) + "</span>" : "";
      var cls = "rv-week-day";
      if (day.is_today) cls += " is-today";
      if (day.is_race_day) cls += " is-race-day";
      return '<div class="' + cls + '">' +
        '<div class="rv-week-day-label"><span class="rv-weekday' + (day.is_today ? " rv-weekday--today" : "") + '">' + esc(day.weekday) + '</span>' +
        '<span class="rv-mono rv-day-num">' + esc(day.day_of_month) + "</span></div>" +
        '<div class="rv-week-day-body">' +
        '<span class="rv-kind-dot" style="background:' + kindDot(primary.kind) + '"></span>' +
        '<span class="rv-week-day-title' + (done ? " is-done" : "") + '">' + esc(primary.name) + "</span>" +
        note + chips + "</div>" +
        '<span class="rv-mono rv-subtitle">' + esc(tss) + "</span></div>";
    }).join("");
    host.innerHTML =
      '<div class="rv-row"><h2 id="rv-week-h" class="rv-label">This week</h2>' +
      '<a href="' + esc(week.plan_href) + '">Edit the week</a></div>' +
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
    var raceLine = esc(r.name) + " · " + esc(r.race_date_label || r.race_date || "");
    var sub = r.subtitle || (r.priority === "A" ? "A race" : "Upcoming race");
    host.innerHTML =
      '<div class="rv-row"><span class="rv-label">Next race</span><a href="' + esc(card.href) + '">All races</a></div>' +
      '<div class="rv-row rv-next-race-hero">' +
      '<div><p class="rv-next-race-title">' + raceLine + '</p>' +
      '<p class="rv-subtitle">' + esc(sub) + "</p></div>" +
      '<span class="rv-mono rv-countdown">' + esc(card.days_to_race) +
      '<span class="rv-countdown-suffix"> d</span></span></div>' +
      '<div class="rv-home-tiles rv-next-race-tiles">' +
      tile("Goal", card.goal_time_label || "—") +
      '<div class="rv-tile rv-tile--estimate"><span class="rv-subtitle" style="font-size:12px;font-weight:700">Estimate</span>' +
      '<span class="rv-mono" style="font-size:15px;font-weight:600;color:#15803d">' + esc(card.estimate_time_label || "—") + "</span></div>" +
      tile("Range", card.range_label || "—") +
      "</div>";
  }

  function renderStatus(host, focus) {
    if (!host) return;
    var axisLabel = focus && focus.axis ? esc(focus.axis.replace(/_/g, " ")) : "—";
    var advice = focus && focus.advice ? esc(focus.advice) : "See Performance for your full status.";
    host.innerHTML =
      '<div class="rv-row"><h2 id="rv-status-h" class="rv-label">Status · same as Performance</h2>' +
      '<a href="' + esc((focus && focus.href) || "/v2/performance") + '">Performance</a></div>' +
      '<div class="rv-focus-banner">' +
      '<span class="rv-label rv-focus-eyebrow">Most room to grow</span>' +
      '<p class="rv-title rv-focus-axis">' + axisLabel + "</p>" +
      '<p class="rv-subtitle rv-focus-advice">' + advice + "</p></div>" +
      '<div data-perf-radar data-size="small" class="rv-home-radar" aria-busy="true"></div>' +
      '<div class="rv-radar-legend">' +
      '<span><i class="rv-legend-swatch rv-legend-now"></i>Now</span>' +
      '<span><i class="rv-legend-swatch rv-legend-prior"></i>4 wk ago</span>' +
      '<span><i class="rv-legend-swatch rv-legend-stale"></i>Stale</span>' +
      '<span><i class="rv-legend-swatch rv-legend-focus"></i>Focus</span></div>';
    var radar = host.querySelector("[data-perf-radar]");
    if (radar && window.PerfRadar) {
      window.PerfRadar.mount(radar, { size: "small" });
    }
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
        renderHeaderPill(data.header_race_pill);
        renderAlerts(alertsHost, data.alerts);
        renderHero(heroHost, data, load);
        renderDailyBasicsCard(document.getElementById("rv-home-daily-basics"), data.daily_basics, load);
        var weightHost = document.getElementById("rv-home-weight");
        if (data.weight_card) {
          renderWeightCard(weightHost, data.weight_card);
        } else {
          fetchWeightCardFallback().then(function (card) { renderWeightCard(weightHost, card); });
        }
        void GET_BODY_LOG_WEEKLY;
        renderWeek(document.getElementById("rv-home-week"), data.this_week);
        renderLadder(document.getElementById("rv-home-ladder"), data.long_run_ladder);
        renderRecent(document.getElementById("rv-home-recent"), data.recent_sessions);
        renderNextRace(document.getElementById("rv-home-next-race"), data.next_race);
        renderStatus(document.getElementById("rv-home-status"), data.focus);
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