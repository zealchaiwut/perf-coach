// Season road page (P6-6 / #1880). Visual layout matches Performance race rows.
(function () {
  "use strict";

  var esc = window.AppCommon.escapeHtml;
  var prBadge = window.AppCommon.racePriorityBadge
    ? window.AppCommon.racePriorityBadge
    : function (r) {
      var kind = (r && r.race_type === "checkpoint" && !r.priority) ? "CP" : ((r && r.priority) || "?");
      var mod = kind === "CP" ? "cp" : String(kind).toLowerCase();
      return '<span class="rv-race-pr rv-race-pr--' + esc(mod) + '">' + esc(kind) + "</span>";
    };

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
    var s = Math.round(spk % 60);
    return m + ":" + String(s).padStart(2, "0");
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

  function chipClass(tone) {
    if (tone === "good") return "rv-status-chip rv-status-chip--good";
    if (tone === "bad") return "rv-status-chip rv-status-chip--bad";
    if (tone === "warn") return "rv-chip rv-chip--warn";
    if (tone === "neutral") return "rv-status-chip rv-status-chip--neutral";
    return "rv-chip";
  }

  function statusChip(chip) {
    if (!chip) return "";
    return '<span class="' + chipClass(chip.tone) + '" data-role-result="' + esc(chip.text || "") +
      '" title="' + esc(chip.title || chip.text || "") + '">' + esc(chip.text || "—") + "</span>";
  }

  function dateLabel(r) {
    return r.race_date_label || r.date_label || "";
  }

  function kmLabel(r) {
    if (r.distance_label) return r.distance_label + " km";
    if (r.distance_km != null) return Number(r.distance_km).toFixed(1).replace(/\.0$/, "") + " km";
    return "";
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
      (g.pace_seconds_per_km ? '<span class="rv-mono rv-subtitle">' + esc(fmtPace(g.pace_seconds_per_km)) + " /km</span>" : "") +
      (g.reason ? '<span class="rv-subtitle">' + esc(g.reason) + "</span>" : "");
    var estInner = e.available
      ? '<span class="rv-perf-hero-tile-val rv-perf-hero-tile-val--good rv-mono">' + esc(fmtHMS(e.est_sec)) + "</span>" +
        (e.band_sec != null ? '<span class="rv-subtitle rv-mono">±' + esc(fmtHMS(e.band_sec)) + "</span>" : "") +
        (e.pace_seconds_per_km ? '<span class="rv-mono rv-subtitle">' + esc(fmtPace(e.pace_seconds_per_km)) + " /km</span>" : "")
      : '<span class="rv-subtitle">not available</span>';
    var statusInner =
      '<span class="sr-status ' + esc(statusClass(st.status)) + ' rv-perf-hero-tile-val" style="font-size:1.25rem" data-track-status="' + esc(st.status || "") + '">' +
      esc(st.label || "—") + "</span>";
    var readyInner = '<span class="rv-perf-hero-tile-val rv-mono" data-readiness-count>' +
      esc(rd.count_label || ((rd.done || 0) + " of " + (rd.total || 5))) + "</span>";
    var meta = [dateLabel(r), kmLabel(r), r.role_label || "A race"].filter(Boolean).join(" · ");
    return (
      '<section class="rv-card rv-stack sr-hero rv-perf-hero-card" data-season-hero>' +
        '<div class="rv-perf-hero-head">' +
          '<div class="rv-race-row__head">' + prBadge(r) +
            '<div><h2 class="rv-perf-hero-title">' + esc(r.name) + '</h2>' +
            '<span class="rv-perf-hero-meta rv-mono">' + esc(meta) + "</span></div></div>" +
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
    var nodes = tl.nodes.slice();
    var marks = nodes.map(function (n, i) {
      var pri = String(n.priority || "").toLowerCase();
      var cls = "sr-node";
      if (n.is_target_a) cls += " sr-node--target";
      else if (i === 0) cls += " sr-node--first";
      if (pri) cls += " sr-node--" + pri;
      var dx = n.tag_dx || 0;
      var left = Math.max(0, Math.min(1, n.x + dx)) * 100;
      var tone = n.status_tone === "good" || n.status_tone === "bad" ? n.status_tone : "";
      var tag = [n.date_label || dateLabel(n), n.distance_label ? n.distance_label + "K" : ""].filter(Boolean).join(" · ");
      if (n.is_target_a) left = 100;
      return (
        '<div class="' + cls + '" style="left:' + left + '%" data-timeline-node="' + esc(n.id) + '" data-role="' + esc(n.role) + '">' +
          '<span class="sr-node-dot' + (tone ? " sr-node-dot--" + tone : "") + '"></span>' +
          '<span class="sr-node-lab">' + esc(tag) + "</span></div>"
      );
    }).join("");
    var todayMark =
      '<div class="sr-today" style="left:' + (tl.today_x * 100) + '%" data-today-marker aria-hidden="true"><span>Today</span></div>';
    return (
      '<section class="rv-card rv-stack sr-timeline-wrap" aria-label="Season timeline">' +
        '<span class="rv-label">Timeline</span>' +
        '<p class="rv-subtitle">' + esc(tl.start_label || "") + " → " + esc(tl.end_label || "") + "</p>" +
        '<div class="sr-timeline" role="img" aria-label="Races from previous A race to target A race">' +
          '<div class="sr-timeline-rail"></div>' + todayMark + marks + "</div></section>"
    );
  }

  function resultCell(row) {
    var res = row.result || {};
    if (res.kind === "result") {
      var tone = (row.status_chip && row.status_chip.tone === "bad") ? " rv-race-time--bad" :
        (row.status_chip && row.status_chip.tone === "good") ? " rv-race-time--good" : "";
      return '<span class="rv-mono rv-race-time' + tone + '">' + esc(res.time_hms || fmtHMS(res.time_sec)) + "</span>" +
        (res.pace_label ? ' <span class="rv-mono rv-subtitle">' + esc(res.pace_label) + "</span>" : "");
    }
    if (res.kind === "record") {
      return '<div class="rv-race-record">' +
        '<label class="sr-only" for="sr-actual-' + esc(row.id) + '">Finish time</label>' +
        '<input id="sr-actual-' + esc(row.id) + '" type="text" inputmode="numeric" placeholder="h:mm:ss">' +
        '<button type="button" class="rv-btn rv-btn--accent rv-btn--sm" data-record="' + esc(row.id) + '">Record</button></div>';
    }
    return '<span class="rv-subtitle">—</span>';
  }

  function renderRow(row) {
    var recal = row.recalibrates ? " · recalibrates here" : "";
    var meta = [dateLabel(row), kmLabel(row), row.role_label].filter(Boolean).join(" · ") + recal;
    return (
      '<div class="rv-sr-race-row rv-race-row" data-season-row="' + esc(row.id) + '" data-race-role="' + esc(row.role) + '">' +
        '<div class="rv-race-row__name"><div class="rv-race-row__head">' + prBadge(row) +
          '<div><span class="rv-race-row__title">' + esc(row.name) + "</span>" +
          '<span class="rv-mono rv-subtitle rv-race-row__meta">' + esc(meta) + "</span></div></div></div>" +
        '<div><span class="rv-race-col-lbl">Target</span><span class="rv-subtitle">' + esc(row.role_target || "") + "</span></div>" +
        '<div><span class="rv-race-col-lbl">Result</span>' + resultCell(row) + "</div>" +
        '<div class="rv-sr-race-row__status">' + statusChip(row.status_chip) + "</div></div>"
    );
  }

  function renderEarlier(rows) {
    if (!rows || !rows.length) return "";
    var shown = rows.slice(0, 3);
    var more = rows.length - shown.length;
    var html = '<section class="rv-card rv-stack" aria-label="Earlier this season" data-earlier-season>' +
      '<span class="rv-race-sec" style="padding-top:0">Earlier this season</span>' +
      '<div class="rv-stack" style="gap:8px" data-earlier-list>' + shown.map(renderRow).join("") + "</div>";
    if (more > 0) {
      html += '<button type="button" class="rv-score-trend-link" data-show-earlier>Show ' + more + " more</button>";
      html += '<div class="rv-stack" style="gap:8px;display:none" data-earlier-rest>' + rows.slice(3).map(renderRow).join("") + "</div>";
    }
    return html + "</section>";
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
        "</section>" +
      renderEarlier(data.earlier_rows || []);
    var btn = host.querySelector("[data-show-earlier]");
    if (btn) {
      btn.addEventListener("click", function () {
        var rest = host.querySelector("[data-earlier-rest]");
        if (rest) rest.style.display = "flex";
        btn.hidden = true;
      });
    }
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

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", load);
  else load();
})();
