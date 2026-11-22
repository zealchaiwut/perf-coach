// Season road page (P6-6 / #1880). Layout follows Performance.dc.html race rows.
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

  function renderHero(hero) {
    var r = hero.race;
    var g = hero.goal || {};
    var e = hero.estimate || {};
    var st = hero.track_status || {};
    var rd = hero.readiness || {};
    var goalLabel = g.state === "locked" ? "Locked goal" : "Provisional goal";
    var estHtml = e.available
      ? '<strong class="sr-mono">' + esc(fmtHMS(e.est_sec)) + "</strong>" +
        (e.band_sec != null ? ' <span class="rv-subtitle">±' + esc(fmtHMS(e.band_sec)) + "</span>" : "") +
        (e.pace_seconds_per_km ? '<br><span class="rv-subtitle sr-mono">' + esc(fmtPace(e.pace_seconds_per_km)) + "</span>" : "")
      : '<span class="rv-subtitle">not available</span>';
    return (
      '<section class="rv-card rv-stack sr-hero" data-season-hero>' +
        '<div class="rv-row" style="flex-wrap:wrap;align-items:flex-start">' +
          '<div><span class="rv-chip">A</span> <strong style="font-size:1.25rem">' + esc(r.name) + "</strong>" +
            '<p class="rv-subtitle">' + esc(r.race_date) + (r.distance_km ? " · " + esc(r.distance_km) + " km" : "") + "</p></div>" +
          '<div class="sr-days"><span class="sr-days-n">' + esc(r.days_to_race) + '</span><span class="sr-days-k">days</span></div>' +
        "</div>" +
        '<div class="sr-tiles">' +
          '<div class="rv-metric"><span class="rv-label">' + esc(goalLabel) + "</span>" +
            '<strong class="sr-mono" data-goal-state="' + esc(g.state || "") + '">' + esc(fmtHMS(g.time_sec)) + "</strong>" +
            (g.pace_seconds_per_km ? '<span class="rv-subtitle sr-mono">' + esc(fmtPace(g.pace_seconds_per_km)) + "</span>" : "") +
            (g.reason ? '<span class="rv-subtitle">' + esc(g.reason) + "</span>" : "") + "</div>" +
          '<div class="rv-metric"><span class="rv-label">Estimate</span>' + estHtml + "</div>" +
          '<div class="rv-metric"><span class="rv-label">Status</span>' +
            '<span class="sr-status ' + esc(statusClass(st.status)) + '" data-track-status="' + esc(st.status || "") + '">' +
            esc(st.label || "—") + "</span></div>" +
          '<div class="rv-metric"><span class="rv-label">Readiness</span>' +
            '<strong data-readiness-count>' + esc(rd.count_label || (rd.done + " / " + rd.total)) + "</strong></div>" +
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
      ? '<span class="rv-chip" data-role-result="' + esc(rr.status || "") + '">' + esc(rr.status || "—") + "</span>"
      : "";
    var res = row.chip_time_sec != null
      ? '<strong class="sr-mono">' + esc(fmtHMS(row.chip_time_sec)) + "</strong>"
      : '<span class="rv-subtitle" data-counts-as>' + esc(row.result_line || row.counts_as) + "</span>";
    var mark = row.recalibrates ? ' <span class="rv-subtitle" data-recalibrates>recalibrates</span>' : "";
    return (
      '<div class="sr-row rv-row" data-season-row="' + esc(row.id) + '" data-race-role="' + esc(row.role) + '">' +
        '<div><span class="rv-chip" data-race-role-chip>' + esc(row.role_label) + "</span> <strong>" + esc(row.name) + "</strong>" + mark +
          '<br><span class="rv-subtitle">' + esc(row.race_date) + (row.distance_km ? " · " + esc(row.distance_km) + " km" : "") + "</span></div>" +
        '<div><span class="rv-label">Target</span><br><span class="rv-subtitle">' + esc(row.role_target) + "</span></div>" +
        '<div><span class="rv-label">Result</span><br>' + res + "</div>" +
        '<div class="rv-row">' + rrHtml + "</div></div>"
    );
  }

  function render(host, data) {
    if (!data.available) {
      host.innerHTML =
        '<section class="rv-card"><p class="rv-subtitle">' + esc(data.reason || "Season road is not available yet.") + "</p></section>";
      return;
    }
    host.innerHTML =
      renderHero(data.hero) +
      renderTimeline(data.timeline) +
      '<section class="rv-card rv-stack" aria-label="Races in this season">' +
        '<span class="rv-label">Races</span>' +
        (data.rows.length ? data.rows.map(renderRow).join("") : '<p class="rv-subtitle">No races scheduled in this block.</p>') +
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