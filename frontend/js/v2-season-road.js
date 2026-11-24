// Season road page (P6-6 / #1880). Visual layout matches Performance race rows.
(function () {
  "use strict";

  var esc = window.AppCommon.escapeHtml;

  function fmtHMS(sec) {
    if (sec == null) return "—";
    sec = Math.round(sec);
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = sec % 60;
    if (h > 0) return h + ":" + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0");
    return m + ":" + String(s).padStart(2, "0");
  }

  function fmtPace(spk) {
    if (spk == null) return "";
    var m = Math.floor(spk / 60);
    var s = spk % 60;
    return m + ":" + String(s).padStart(2, "0") + " /km";
  }

  function getJSON(url) {
    return fetch(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function statusClass(st) {
    if (st === "on_track") return "sr-status--ok";
    if (st === "building") return "sr-status--build";
    if (st === "at_risk") return "sr-status--risk";
    return "";
  }

  function prBadge(r) {
    var isCp = r.role === "long_run" || r.race_type === "checkpoint";
    var text = isCp ? "CP" : (r.priority || "A");
    var mod = isCp ? "cp" : String(r.priority || "a").toLowerCase();
    return '<span class="rv-race-pr rv-race-pr--' + esc(mod) + '">' + esc(text) + "</span>";
  }

  function heroTile(label, inner, opts) {
    opts = opts || {};
    return '<div class="rv-perf-hero-tile' + (opts.mod ? " rv-perf-hero-tile--" + opts.mod : "") + '">' +
      '<span class="rv-perf-hero-tile-lbl' + (opts.lblGood ? " rv-perf-hero-tile-lbl--good" : "") + '">' + esc(label) + "</span>" +
      inner + "</div>";
  }

  function renderHero(hero) {
    var r = hero.race;
    var g = hero.goal || {};
    var e = hero.estimate || {};
    var st = hero.track_status || {};
    var rd = hero.readiness || {};
    var goalLabel = g.state === "locked" ? "Locked goal" : "Provisional goal";
    var goalInner =
      '<span class="rv-perf-hero-tile-val rv-mono" data-goal-state="' + esc(g.state || "") + '">' + esc(fmtHMS(g.time_sec)) + "</span>" +
      (g.pace_seconds_per_km ? '<span class="rv-mono rv-subtitle">' + esc(fmtPace(g.pace_seconds_per_km)) + "</span>" : "") +
      (g.reason ? '<span class="rv-subtitle">' + esc(g.reason) + "</span>" : "");
    var estInner = e.available
      ? '<span class="rv-perf-hero-tile-val rv-perf-hero-tile-val--good rv-mono">' + esc(fmtHMS(e.est_sec)) + "</span>" +
        (e.band_sec != null ? '<span class="rv-subtitle rv-mono">±' + esc(fmtHMS(e.band_sec)) + "</span>" : "") +
        (e.pace_seconds_per_km ? '<span class="rv-mono rv-subtitle">' + esc(fmtPace(e.pace_seconds_per_km)) + "</span>" : "")
      : '<span class="rv-subtitle">not available</span>';
    var statusInner =
      '<span class="sr-status ' + esc(statusClass(st.status)) + ' rv-perf-hero-tile-val" style="font-size:1.25rem" data-track-status="' + esc(st.status || "") + '">' +
      esc(st.label || "—") + "</span>";
    var readyInner = '<span class="rv-perf-hero-tile-val rv-mono" data-readiness-count>' + esc(rd.count_label || (rd.done + " / " + rd.total)) + "</span>";
    return (
      '<section class="rv-card rv-stack sr-hero rv-perf-hero-card" data-season-hero>' +
        '<div class="rv-perf-hero-head">' +
          '<div class="rv-race-row__head">' + prBadge({ priority: "A", role: "a_race" }) +
            '<div><h2 class="rv-perf-hero-title">' + esc(r.name) + '</h2>' +
            '<span class="rv-perf-hero-meta rv-mono">' + esc(r.race_date) +
            (r.distance_km ? " · " + esc(r.distance_km) + " km" : "") + " · A race</span></div></div>" +
          '<div class="rv-perf-countdown" data-hero="countdown"><div class="rv-perf-countdown-val rv-mono">' + esc(r.days_to_race) +
          '</div><div class="rv-perf-countdown-lbl">DAYS</div></div></div>' +
        '<div class="rv-perf-hero-tiles">' +
          heroTile(goalLabel, goalInner) +
          heroTile("Estimate", estInner, { mod: "est", lblGood: e.available, valGood: false }) +
          heroTile("Status", statusInner) +
          heroTile("Readiness", readyInner) +
        "</div></section>"
    );
  }

  function renderTimeline(tl) {
    if (!tl || !tl.nodes || !tl.nodes.length) {
      return '<section class="rv-card"><span class="rv-label">Timeline</span><p class="rv-subtitle">No races in this block.</p></section>';
    }
    var marks = tl.nodes.map(function (n) {
      var cls = "sr-node";
      if (n.is_target_a) cls += " sr-node--target";
      return (
        '<div class="' + cls + '" style="left:' + (n.x * 100) + '%" data-timeline-node="' + esc(n.id) + '" data-role="' + esc(n.role) + '">' +
          '<span class="sr-node-dot" title="' + esc(n.role_label) + '"></span>' +
          '<span class="sr-node-lab">' + esc(n.race_date.slice(5)) + " · " + esc(n.role_label) + "</span>" +
          '<span class="sr-node-sub">' + esc(n.role_target) + "</span></div>"
      );
    }).join("");
    var todayMark =
      '<div class="sr-today" style="left:' + (tl.today_x * 100) + '%" data-today-marker aria-hidden="true"><span>Today</span></div>';
    return (
      '<section class="rv-card rv-stack sr-timeline-wrap" aria-label="Season timeline">' +
        '<span class="rv-label">Timeline</span>' +
        '<p class="rv-subtitle">' + esc(tl.start) + " → " + esc(tl.end) + "</p>" +
        '<div class="sr-timeline" role="img" aria-label="Races from previous A race to target A race">' +
          '<div class="sr-timeline-rail"></div>' + todayMark + marks + "</div></section>"
    );
  }

  function renderRow(row) {
    var rr = row.role_result;
    var rrHtml = rr
      ? '<span class="rv-chip rv-chip--good" data-role-result="' + esc(rr.status || "") + '">' + esc(rr.status || "—") + "</span>"
      : "";
    var res = row.chip_time_sec != null
      ? '<span class="rv-mono rv-race-time">' + esc(fmtHMS(row.chip_time_sec)) + "</span>"
      : '<span class="rv-subtitle" data-counts-as>' + esc(row.result_line || row.counts_as) + "</span>";
    var recal = row.recalibrates ? ' <span class="rv-subtitle rv-race-recal">recalibrates here</span>' : "";
    return (
      '<div class="rv-sr-race-row" data-season-row="' + esc(row.id) + '" data-race-role="' + esc(row.role) + '">' +
        '<div class="rv-race-row__name"><div class="rv-race-row__head">' + prBadge(row) +
          '<div><span class="rv-race-row__title">' + esc(row.name) + "</span>" +
          '<span class="rv-mono rv-subtitle rv-race-row__meta">' + esc(row.race_date) +
          (row.distance_km ? " · " + esc(row.distance_km) + " km" : "") + recal + "</span></div></div></div>" +
        '<div><span class="rv-race-col-lbl">Target</span><span class="rv-subtitle">' + esc(row.role_target) + "</span></div>" +
        '<div><span class="rv-race-col-lbl">Result</span>' + res + "</div>" +
        '<div class="rv-sr-race-row__status">' + rrHtml + "</div></div>"
    );
  }

  function render(host, data) {
    if (!data.available) {
      host.innerHTML =
        '<section class="rv-card"><p class="rv-subtitle">' + esc(data.reason || "Season road is not available yet.") +
        ' <a href="/v2/performance">Back to Performance</a></p></section>';
      return;
    }
    host.innerHTML =
      renderHero(data.hero) +
      renderTimeline(data.timeline) +
      '<section class="rv-card rv-stack" aria-label="Races in this season">' +
        '<span class="rv-race-sec" style="padding-top:0">Races in this block</span>' +
        (data.rows.length ? '<div class="rv-stack" style="gap:8px">' + data.rows.map(renderRow).join("") + "</div>" :
          '<p class="rv-subtitle">No races scheduled in this block.</p>') +
        "</section>";
    var sub = document.getElementById("sr-subtitle");
    if (sub && data.hero && data.hero.race) {
      sub.textContent = "Road to " + data.hero.race.name + " · roles, results, and projection status.";
    }
  }

  function load() {
    var host = document.getElementById("sr-root");
    if (!host) return;
    getJSON("/api/performance/season-road")
      .then(function (data) { render(host, data); })
      .catch(function () {
        host.innerHTML = '<section class="rv-card"><p class="rv-subtitle">Could not load season road.</p></section>';
      });
  }

  document.addEventListener("DOMContentLoaded", load);
})();