// Revamp Performance page (v2). Regions are added per Phase 4 ticket; each
// region renders from one API payload and never recomputes scores locally.
(function () {
  "use strict";

  var esc = window.AppCommon.escapeHtml;

  function toast(msg) {
    var el = document.getElementById("rv-toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.add("is-visible");
    window.setTimeout(function () { el.classList.remove("is-visible"); }, 2800);
  }

  function getJSON(url) {
    return fetch(url, { credentials: "same-origin" }).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
  }

  function sendJSON(method, url, body) {
    return fetch(url, {
      method: method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) throw new Error((data && data.detail) || "HTTP " + r.status);
        return data;
      });
    });
  }

  // ── Strength anchors (P4-4) ───────────────────────────────────────────────

  function renderAnchors(host, anchors) {
    var rows = anchors.map(function (a, i) {
      return '<div class="rv-row" data-anchor-row="' + i + '">' +
        '<span>' + esc(a.label) + '</span>' +
        '<label class="rv-label">Target x trend mass ' +
        '<input type="number" step="0.05" min="0.05" max="5" value="' + esc(a.target_factor) +
        '" data-anchor-factor="' + i + '" aria-label="' + esc(a.label) + ' target factor"></label>' +
        '</div>';
    }).join("");
    host.innerHTML =
      '<span class="rv-label">Strength anchors</span>' +
      '<p class="rv-subtitle">Strength score = best e1RM of the last 45 days / (target factor x trend mass), averaged across these lifts.</p>' +
      rows +
      '<div><button type="button" class="rv-btn rv-btn--secondary" id="v2-anchors-save">Save anchors</button></div>';
    host.querySelector("#v2-anchors-save").addEventListener("click", function () {
      var next = anchors.map(function (a, i) {
        var input = host.querySelector('[data-anchor-factor="' + i + '"]');
        return { key: a.key, label: a.label, match: a.match, target_factor: parseFloat(input.value) };
      });
      sendJSON("PUT", "/api/performance/anchor-lifts", { anchors: next })
        .then(function (data) { renderAnchors(host, data.anchors); toast("Anchors saved"); })
        .catch(function (e) { toast("Could not save: " + e.message); });
    });
  }

  function loadAnchors() {
    var host = document.getElementById("v2-perf-strength-anchors");
    if (!host) return;
    getJSON("/api/performance/anchor-lifts")
      .then(function (data) { renderAnchors(host, data.anchors || []); })
      .catch(function () { host.innerHTML = '<span class="rv-label">Strength anchors</span><p>Not available.</p>'; });
  }

  // ── Drawer (P0-6 pattern: backdrop + aside, Escape closes, focus returns) ──

  var drawerFocus = null;

  function closeDrawer() {
    var d = document.getElementById("v2-perf-drawer");
    var b = document.getElementById("v2-perf-drawer-backdrop");
    if (d) { d.classList.remove("is-open"); d.hidden = true; }
    if (b) { b.classList.remove("is-open"); b.hidden = true; }
    document.removeEventListener("keydown", onDrawerKey);
    if (drawerFocus && drawerFocus.focus) drawerFocus.focus();
  }

  function onDrawerKey(ev) { if (ev.key === "Escape") closeDrawer(); }

  function openDrawer(html) {
    var d = document.getElementById("v2-perf-drawer");
    var b = document.getElementById("v2-perf-drawer-backdrop");
    var body = document.getElementById("v2-perf-drawer-body");
    if (!d || !body) return null;
    drawerFocus = document.activeElement;
    body.innerHTML = html;
    d.hidden = false; d.classList.add("is-open");
    if (b) { b.hidden = false; b.classList.add("is-open"); b.onclick = closeDrawer; }
    document.addEventListener("keydown", onDrawerKey);
    var first = body.querySelector("input,button");
    if (first) first.focus();
    return body;
  }

  // ── Mobility self-test (P4-5) ─────────────────────────────────────────────

  function todayISO() {
    return window.AppCommon && window.AppCommon.todayISO ? window.AppCommon.todayISO() : "";
  }

  function renderMobility(host, data) {
    var axis = data.axis || {};
    var chip = "";
    if (axis.never_measured) {
      chip = '<span class="rv-chip">Not yet measured</span>';
    } else if (axis.test_due) {
      chip = '<span class="rv-chip" data-testid="mobility-test-due" style="background:#fff1dc">Test due · ' +
        esc(axis.days_since_test) + ' days ago</span>';
    }
    var scoreLine = axis.score == null ? "—" : esc(axis.score);
    var raw = axis.raw || {};
    var detail = axis.never_measured ? "Log a test to wake this axis up." :
      "Knee-to-wall " + esc(raw.knee_to_wall_left_cm) + " / " + esc(raw.knee_to_wall_right_cm) +
      " cm (weaker side counts) · sit-and-reach " + esc(raw.sit_and_reach_cm) + " cm";
    host.innerHTML =
      '<div class="rv-row"><span class="rv-label">Mobility</span>' + chip + '</div>' +
      '<div class="rv-row"><strong style="font-size:1.6rem">' + scoreLine + '</strong>' +
      '<button type="button" class="rv-btn rv-btn--primary" id="v2-mobility-log">Log a test</button></div>' +
      '<p class="rv-subtitle">' + detail + '</p>';
    host.querySelector("#v2-mobility-log").addEventListener("click", openMobilityDrawer);
  }

  function openMobilityDrawer() {
    var body = openDrawer(
      '<h2 class="rv-label" id="v2-perf-drawer-title">Log a mobility test</h2>' +
      '<form id="v2-mobility-form" class="rv-stack" novalidate>' +
      '<label class="rv-label">Date <input type="date" name="test_date" value="' + esc(todayISO()) + '" max="' + esc(todayISO()) + '" required></label>' +
      '<label class="rv-label">Knee-to-wall, left (cm, 0–30) <input type="number" name="knee_to_wall_left_cm" min="0" max="30" step="0.5" required></label>' +
      '<label class="rv-label">Knee-to-wall, right (cm, 0–30) <input type="number" name="knee_to_wall_right_cm" min="0" max="30" step="0.5" required></label>' +
      '<label class="rv-label">Sit-and-reach (cm, −20 to 40) <input type="number" name="sit_and_reach_cm" min="-20" max="40" step="0.5" required></label>' +
      '<p class="rv-warn-inline" id="v2-mobility-error" role="alert" hidden></p>' +
      '<div class="rv-row"><button type="button" class="rv-btn rv-btn--secondary" data-close>Cancel</button>' +
      '<button type="submit" class="rv-btn rv-btn--primary">Save test</button></div></form>'
    );
    if (!body) return;
    body.querySelector("[data-close]").addEventListener("click", closeDrawer);
    body.querySelector("#v2-mobility-form").addEventListener("submit", function (ev) {
      ev.preventDefault();
      var f = ev.target;
      var err = body.querySelector("#v2-mobility-error");
      function val(n) { var v = f.elements[n].value; return v === "" ? null : parseFloat(v); }
      var payload = {
        test_date: f.elements.test_date.value || null,
        knee_to_wall_left_cm: val("knee_to_wall_left_cm"),
        knee_to_wall_right_cm: val("knee_to_wall_right_cm"),
        sit_and_reach_cm: val("sit_and_reach_cm"),
      };
      sendJSON("POST", "/api/performance/mobility-tests", payload).then(function () {
        closeDrawer();
        toast("Mobility test saved");
        loadMobility();
      }).catch(function (e) { err.textContent = e.message; err.hidden = false; });
    });
  }

  function loadMobility() {
    var host = document.getElementById("v2-perf-mobility");
    if (!host) return;
    getJSON("/api/performance/mobility-tests")
      .then(function (data) { renderMobility(host, data); })
      .catch(function () { host.innerHTML = '<span class="rv-label">Mobility</span><p>Not available.</p>'; });
  }

  // ── Focus card, why-not card and the queue into Plan (P4-7) ───────────────

  function renderFocus(host, data) {
    var focus = data.focus;
    if (!focus) {
      host.innerHTML = '<div class="rv-card rv-stack"><span class="rv-label">Most room to grow</span>' +
        '<p class="rv-subtitle">Nothing to rank yet: it needs a fresh, measured axis.</p></div>';
      return;
    }
    var work = focus.work || {};
    var queuedItem = (data.queue || {})[focus.axis];
    var action;
    if (!work.queueable) {
      action = '<p class="rv-subtitle" style="color:#d5def3">' + esc(work.advice) + ' (advice only, not queued)</p>';
    } else if (queuedItem) {
      action = '<span class="rv-chip" data-testid="focus-queued">Queued for week of ' + esc(queuedItem.earliest_week) + '</span>';
    } else {
      action = '<button type="button" class="rv-btn rv-btn--primary" id="v2-focus-queue">Queue this work</button>';
    }
    var whyNot = (data.why_not || []).map(function (w) {
      return '<li><strong>' + esc(w.label) + '</strong> ' + esc(w.score) + ': ' + esc(w.reason) + '</li>';
    }).join("");
    host.innerHTML =
      '<div class="rv-card rv-stack" style="background:#0b1530;color:#fff">' +
      '<span class="rv-label" style="color:#e4ff52">Most room to grow</span>' +
      '<h2 style="margin:0">' + esc(focus.label) + ' <span style="font-family:var(--rv-mono)">' + esc(Math.round(focus.score)) + '</span></h2>' +
      '<p style="margin:0">' + esc(work.advice) + '</p>' + action + '</div>' +
      '<div class="rv-card rv-card--soft rv-stack"><span class="rv-label">Why not these</span>' +
      (whyNot ? '<ul>' + whyNot + '</ul>' : '<p class="rv-subtitle">No other measured axes.</p>') + '</div>';
    var btn = host.querySelector("#v2-focus-queue");
    if (btn) {
      btn.addEventListener("click", function () {
        btn.disabled = true;
        sendJSON("POST", "/api/performance/focus/queue", { axis: focus.axis })
          .then(function (res) {
            toast("Queued for the week of " + res.item.earliest_week);
            loadFocus();
          })
          .catch(function (e) { btn.disabled = false; toast("Could not queue: " + e.message); });
      });
    }
  }

  function loadFocus() {
    var host = document.getElementById("v2-perf-focus");
    if (!host) return;
    getJSON("/api/performance/focus")
      .then(function (data) { renderFocus(host, data); })
      .catch(function () { host.innerHTML = '<div class="rv-card"><span class="rv-label">Focus</span><p>Not available.</p></div>'; });
  }

  // ── A-race hero and the after-the-race card (P4-8) ────────────────────────
  // Display only: every value comes from /api/performance/hero; the one local
  // calculation is formatting seconds as h:mm:ss.

  function fmtHMS(sec) {
    if (sec == null) return "—";
    var s = Math.abs(Math.round(sec));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(r).padStart(2, "0");
  }
  function fmtPace(sec) { return sec == null ? "—" : fmtHMS(sec).replace(/^0:/, "") + " /km"; }
  function signedGap(sec) {
    if (sec == null) return "—";
    if (sec === 0) return "0:00";
    // goal minus estimate: positive means the estimate beats the goal (shown as a minus time vs goal)
    return (sec > 0 ? "\u2212" : "+") + fmtHMS(sec);
  }

  function tile(label, value, sub, extra) {
    return '<div class="rv-metric"' + (extra || "") + '><span class="rv-label">' + esc(label) + '</span><br>' +
      '<strong>' + value + '</strong>' + (sub ? '<br><span class="rv-subtitle">' + sub + '</span>' : "") + '</div>';
  }

  function renderHero(host, afterHost, data) {
    var r = data.race;
    if (!r) {
      host.innerHTML = '<span class="rv-label">A race</span><p class="rv-subtitle">No upcoming A race. Add one on the race list.</p>';
    } else {
      var est = data.estimate || {};
      var goal = data.goal || {};
      var gap = data.gap || {};
      var estTile = est.available
        ? tile("Estimate", esc(fmtHMS(est.est_sec)), esc(fmtPace(est.pace_seconds_per_km)), ' data-hero="estimate"')
        : tile("Estimate", "—", esc(est.reason || "not available"), ' data-hero="estimate"');
      var rangeTile = est.available && est.range_low_sec != null
        ? tile("Range" + (est.uncertainty_min ? " · ±" + esc(est.uncertainty_min) + " min" : ""),
            esc(fmtHMS(est.range_low_sec)) + " –<br>" + esc(fmtHMS(est.range_high_sec)), "", ' data-hero="range"')
        : tile("Range", "—", "not available", ' data-hero="range"');
      var rs = data.race_specific || {};
      host.innerHTML =
        '<div class="rv-row"><div><span class="rv-chip">' + esc(r.priority) + '</span> ' +
        '<h2 style="display:inline;margin:0 8px">' + esc(r.name) + '</h2>' +
        '<span class="rv-subtitle">' + esc(r.race_date) + (r.distance_km ? " · " + esc(r.distance_km) + " km" : "") + '</span></div>' +
        '<div class="rv-row"><span class="rv-chip" data-hero="countdown"><strong>' + esc(r.days_to_race) + '</strong>&nbsp;days</span>' +
        '<button type="button" class="rv-btn rv-btn--secondary" id="v2-hero-change-race">Change race</button></div></div>' +
        '<div class="rv-row" style="align-items:stretch;flex-wrap:wrap">' +
        tile("Goal", esc(fmtHMS(goal.time_sec)), esc(fmtPace(goal.pace_seconds_per_km)), ' data-hero="goal"') +
        estTile + rangeTile +
        tile("Gap to goal", esc(signedGap(gap.goal_minus_estimate_sec)), esc(gap.reading || ""), ' data-hero="gap"') +
        '</div>' +
        '<div class="rv-row" style="justify-content:flex-start;flex-wrap:wrap"><span class="rv-label">Race-specific</span>' +
        '<span class="rv-chip" data-hero="race-endurance">End ' + esc(rs.endurance == null ? "—" : Math.round(rs.endurance)) + '</span>' +
        '<span class="rv-chip" data-hero="race-speed">Spd ' + esc(rs.speed == null ? "—" : Math.round(rs.speed)) + '</span>' +
        '<span class="rv-subtitle">' + esc(rs.explanation || "") + '</span></div>';
      var change = host.querySelector("#v2-hero-change-race");
      if (change) {
        change.addEventListener("click", function () {
          document.dispatchEvent(new CustomEvent("perf:edit-race", { detail: { raceId: r.id } }));
          var list = document.getElementById("v2-perf-races");
          if (list && list.scrollIntoView) list.scrollIntoView({ behavior: "smooth" });
        });
      }
    }
    var after = data.after_race || {};
    var cp = after.next_checkpoint;
    var cpHtml = "";
    if (cp) {
      var ce = cp.estimate || {};
      cpHtml = '<div class="rv-row" data-after="checkpoint"><span><strong>' + esc(cp.label) + '</strong> · ' + esc(cp.target_date) +
        (cp.distance_km ? " · " + esc(cp.distance_km) + " km" : "") + '</span>' +
        '<span>' + (ce.available ? "Estimate " + esc(fmtHMS(ce.est_sec)) : "Estimate not available") + '</span></div>';
    }
    afterHost.innerHTML = '<span class="rv-label">After the race</span><p>' + esc(after.copy || "") + '</p>' + cpHtml;
  }

  function loadHero() {
    var host = document.getElementById("v2-perf-hero");
    var after = document.getElementById("v2-perf-after-race");
    if (!host || !after) return;
    getJSON("/api/performance/hero")
      .then(function (data) { renderHero(host, after, data); })
      .catch(function () { host.innerHTML = '<span class="rv-label">A race</span><p>Not available.</p>'; });
  }

  // ── Endurance and Speed cards (P4-9) ──────────────────────────────────────

  function sparkline(spark) {
    if (!spark || !spark.values || spark.values.length < 2) return "";
    var v = spark.values, lo = Math.min.apply(null, v), hi = Math.max.apply(null, v);
    var span = hi - lo || 1, w = 200, h = 44;
    var pts = v.map(function (y, i) {
      return (i * w / (v.length - 1)).toFixed(1) + "," + (h - 4 - (y - lo) / span * (h - 8)).toFixed(1);
    }).join(" ");
    return '<svg viewBox="0 0 200 44" style="width:100%;height:44px" aria-hidden="true" data-sparkline>' +
      '<polyline points="' + pts + '" fill="none" stroke="#1f3b8a" stroke-width="2"/></svg>';
  }

  function num(v) { return v == null ? "—" : (Math.round(v * 10) / 10).toString(); }
  function signed(v) {
    if (v == null) return "";
    var n = Math.round(v);
    return n === 0 ? "0" : (n > 0 ? "+" + n : "\u2212" + Math.abs(n));
  }

  function renderScoreCard(c) {
    var chip = c.delta_28d == null ? "" :
      '<span class="rv-chip" data-card-delta>' + esc(signed(c.delta_28d)) + ' in 28 days</span>';
    var d = c.decomposition;
    var line = d ? '<p class="rv-subtitle" data-card-decomposition>' +
      esc(num(d.score_then)) + ' then · ' + esc(num(d.decay)) + ' decay · ' + esc(num(d.efforts)) +
      ' efforts · ' + esc(num(d.consistency)) + ' consistency · ' + esc(num(d.score_now)) + ' now</p>' : "";
    var split = c.split && (c.split.decay || c.split.gains) ?
      '<div class="rv-zone-bar" role="img" aria-label="Decay ' + esc(num(c.split.decay)) + ' points versus gains ' + esc(num(c.split.gains)) + ' points" data-card-split>' +
      '<span class="rv-zone-seg" style="width:' + (c.split.decay_share * 100).toFixed(1) + '%;background:#f0b27a"></span>' +
      '<span class="rv-zone-seg" style="width:' + (c.split.gains_share * 100).toFixed(1) + '%;background:#1f3b8a"></span></div>' : "";
    var reason = c.reason ? '<p data-card-reason>' + esc(c.reason) + '</p>' : "";
    var toReach = c.to_reach ? '<p data-card-to-reach>' + esc(c.to_reach) + '</p>' : "";
    var anchors = (c.anchors || []).map(function (a) {
      return '<li>' + esc(a.date) + ' · raw ' + esc(num(a.raw_score)) + ' · ' + esc(num(a.age_weeks)) + ' wk' +
        (a.is_stale ? ' · <strong>stale</strong>' : '') + '</li>';
    }).join("");
    return '<div class="rv-card rv-stack" data-score-card="' + esc(c.axis) + '">' +
      '<div class="rv-row"><span class="rv-label">' + esc(c.label) + '</span>' + chip + '</div>' +
      '<strong style="font-size:1.8rem">' + esc(c.score == null ? "—" : Math.round(c.score)) + '</strong>' +
      sparkline(c.sparkline) + line + split + reason + toReach +
      (anchors ? '<details><summary>Anchors</summary><ul>' + anchors + '</ul></details>' : "") + '</div>';
  }

  function loadScoreCards() {
    var host = document.getElementById("v2-perf-score-cards");
    if (!host) return;
    getJSON("/api/performance/score-cards")
      .then(function (data) { host.innerHTML = (data.cards || []).map(renderScoreCard).join(""); })
      .catch(function () { host.innerHTML = '<div class="rv-card"><span class="rv-label">Endurance and Speed</span><p>Not available.</p></div>'; });
  }

  // ── Races and projections: tiles, chain, chart (P4-10) ────────────────────
  // Every value comes from /api/performance/projection. The chart maps the
  // server's seconds and 0..1 date positions onto the SVG; nothing is derived.

  var NA = "not available";

  function projTile(label, tileData, render) {
    var body = tileData && tileData.available ? render(tileData) : '<span class="rv-subtitle">' + NA + '</span>';
    return '<div class="rv-metric" data-tile="' + esc(label.toLowerCase().replace(/\s+/g, "-")) + '"><span class="rv-label">' +
      esc(label) + '</span><br><strong>' + body + '</strong></div>';
  }

  function renderTiles(t) {
    t = t || {};
    return '<div class="rv-row" style="align-items:stretch;flex-wrap:wrap">' +
      projTile("Last recalibrated", t.last_recalibrated, function (d) {
        return esc(d.date) + (d.race_name ? ' · ' + esc(d.race_name) : "");
      }) +
      projTile("Data", t.data_sufficiency, function (d) { return '<span class="rv-chip">' + esc(d.value) + '</span>'; }) +
      projTile("Band confidence", t.band_confidence, function (d) { return '<span class="rv-chip">' + esc(d.value) + '</span>'; }) +
      projTile("Model correction", t.model_correction, function (d) {
        return esc((d.pct > 0 ? "+" : d.pct < 0 ? "\u2212" : "") + Math.abs(d.pct)) + '%' +
          ' <span class="rv-subtitle">' + esc(d.reading || "") + ' \u00b7 ' + esc(d.n_races) + ' race' + (d.n_races === 1 ? "" : "s") + '</span>';
      }) + '</div>';
  }

  function stage(label, key, inner) {
    return '<div class="rv-metric" data-chain="' + key + '"><span class="rv-label">' + esc(label) + '</span><br>' + inner + '</div>';
  }

  function paceOrNA(st) {
    return st && st.available ? '<strong>' + esc(fmtPace(st.pace_seconds_per_km)) + '</strong>' : '<span class="rv-subtitle">' + NA + '</span>';
  }

  function renderChain(chain) {
    if (!chain) return "";
    var e = chain.endurance || {}, sp = chain.speed || {}, b = chain.blended || {}, c = chain.correction || {}, f = chain.final || {};
    var arrow = '<span class="rv-subtitle" aria-hidden="true">\u2192</span>';
    var scoreLine = function (name, st) {
      return '<div><span class="rv-subtitle">' + name + (st.score != null ? ' <b>' + esc(Math.round(st.score)) + '</b>' : "") + '</span><br>' + paceOrNA(st) + '</div>';
    };
    var corrNote = c.available
      ? '<br><span class="rv-subtitle">' + esc((c.pct > 0 ? "+" : c.pct < 0 ? "\u2212" : "") + Math.abs(c.pct)) + '% \u00b7 ' + esc(c.n_races) + ' race' + (c.n_races === 1 ? "" : "s") + '</span>'
      : '<br><span class="rv-subtitle">' + NA + '</span>';
    var goal = f.goal || {};
    var finalHtml = f.available
      ? '<span class="rv-label">Projected finish \u00b7 ' + esc(f.race_name) + '</span><br><strong data-chain-final style="font-size:1.6em">' + esc(fmtHMS(f.est_sec)) + '</strong>' +
        '<br><span class="rv-subtitle">pace ' + esc(fmtPace(f.pace_seconds_per_km)) + ' \u00b7 band ' +
        (f.band_sec != null ? '\u00b1' + esc(fmtHMS(f.band_sec)) : NA) + ' \u00b7 goal ' + esc(fmtHMS(goal.time_sec)) +
        (goal.state ? ' <span class="rv-chip" data-goal-state>' + esc(goal.state) + '</span>' : "") + '</span>'
      : '<span class="rv-label">Projected finish</span><br><span class="rv-subtitle">' + NA + '</span>';
    return '<div class="rv-row" data-chain-row style="flex-wrap:wrap;align-items:stretch;gap:8px">' +
      stage("Endurance and Speed", "scores", scoreLine("Endurance", e) + scoreLine("Speed", sp)) + arrow +
      stage("Blended" + (b.available ? " \u00b7 " + esc(b.speed_weight_pct) + "% speed" : ""), "blended", paceOrNA(b)) + arrow +
      stage("Model correction", "correction", (c.available ? '<strong>' + esc(c.factor) + '\u00d7</strong>' : '<span class="rv-subtitle">' + NA + '</span>') + corrNote) + arrow +
      '<div class="rv-metric" data-chain="final">' + finalHtml + '</div></div>';
  }

  function renderChart(ch) {
    if (!ch || !ch.available) {
      return '<p class="rv-subtitle" data-chart-na>Chart ' + NA + '.</p>';
    }
    var W = 1000, top = 20, bottom = 220;
    var lo = ch.y_min_sec, hi = ch.y_max_sec, pad = Math.max(60, (hi - lo) * 0.08);
    lo -= pad; hi += pad;
    var X = function (f) { return Math.round(f * W * 10) / 10; };
    var Y = function (sec) { return Math.round((top + (hi - sec) / (hi - lo) * (bottom - top)) * 10) / 10; };
    var parts = [];
    parts.push('<line x1="0" y1="' + bottom + '" x2="' + W + '" y2="' + bottom + '" stroke="#dfe5f1"/>');
    if (ch.goal_sec != null) {
      parts.push('<line data-chart="goal" x1="0" y1="' + Y(ch.goal_sec) + '" x2="' + W + '" y2="' + Y(ch.goal_sec) + '" stroke="#15803d" stroke-width="2" stroke-dasharray="7 6"/>' +
        '<text x="6" y="' + (Y(ch.goal_sec) - 6) + '" font-size="12" font-weight="700" fill="#15803d">Goal ' + esc(ch.goal_label) + '</text>');
    }
    (ch.ticks || []).forEach(function (m) {
      parts.push('<line data-chart-tick="' + esc(m.role) + '" x1="' + X(m.x) + '" y1="' + (bottom - 16) + '" x2="' + X(m.x) + '" y2="' + bottom + '" stroke="#9aa5bd" stroke-width="2"><title>' + esc(m.name) + '</title></line>');
    });
    (ch.recalibrations || []).forEach(function (m) {
      parts.push('<line data-chart-recal x1="' + X(m.x) + '" y1="20" x2="' + X(m.x) + '" y2="' + bottom + '" stroke="#9aa5bd" stroke-dasharray="3 4"/>' +
        '<text x="' + (X(m.x) + 6) + '" y="32" font-size="11" fill="#56627f">' + esc(m.name) + ' \u00b7 recalibrated</text>');
    });
    (ch.pending || []).forEach(function (m) {
      parts.push('<line data-chart-pending x1="' + X(m.x) + '" y1="40" x2="' + X(m.x) + '" y2="' + bottom + '" stroke="#e0a56b" stroke-dasharray="3 4"/>' +
        '<text x="' + (X(m.x) + 6) + '" y="52" font-size="11" fill="#7a3a10">' + esc(m.name) + ' \u00b7 not recorded</text>');
    });
    var nowX = X(ch.now_x), p = ch.projection, band = ch.band;
    if (band) {
      parts.push('<polygon data-chart="band" points="' + nowX + ',' + Y(p.est_sec) + ' ' + W + ',' + Y(band.high_sec) + ' ' + W + ',' + Y(band.low_sec) + '" fill="#c9d9f6"/>');
    }
    var pts = (ch.history || []).map(function (h) { return X(h.x) + "," + Y(h.est_sec); });
    if (pts.length >= 2) {
      parts.push('<polyline data-chart="history" points="' + pts.join(" ") + '" fill="none" stroke="#1f3b8a" stroke-width="3" stroke-linejoin="round"/>');
    }
    var fromY = (ch.history && ch.history.length) ? Y(ch.history[ch.history.length - 1].est_sec) : Y(p.est_sec);
    parts.push('<line data-chart="projection" x1="' + nowX + '" y1="' + fromY + '" x2="' + W + '" y2="' + Y(p.est_sec) + '" stroke="#1f3b8a" stroke-width="3" stroke-dasharray="6 5"/>');
    parts.push('<line x1="' + nowX + '" y1="10" x2="' + nowX + '" y2="' + bottom + '" stroke="#0b1530" stroke-width="1.5"/>' +
      '<text x="' + (nowX - 6) + '" y="22" font-size="11" font-weight="700" fill="#0b1530" text-anchor="end">Now</text>');
    var mono = ' font-size="11.5" text-anchor="end" font-family="JetBrains Mono, monospace"';
    if (band) {
      parts.push('<text data-band-label="high" x="' + (W - 4) + '" y="' + (Y(band.high_sec) - 4) + '" fill="#56627f"' + mono + '>' + esc(band.high_label) + '</text>');
      parts.push('<text data-band-label="low" x="' + (W - 4) + '" y="' + (Y(band.low_sec) + 14) + '" fill="#56627f"' + mono + '>' + esc(band.low_label) + '</text>');
    }
    parts.push('<text data-band-label="estimate" x="' + (W - 4) + '" y="' + (Y(p.est_sec) - 4) + '" fill="#0b1530" font-weight="700"' + mono + '>' + esc(p.est_label) + '</text>');
    parts.push('<text x="0" y="242" font-size="11.5" fill="#56627f">' + esc(ch.start) + '</text>' +
      '<text x="' + W + '" y="242" font-size="11.5" fill="#56627f" text-anchor="end">Race ' + esc(ch.end) + '</text>');
    var label = "Projected " + ch.race_name + " time from " + ch.start + " to race day " + ch.end + ", ending at " + p.est_label +
      (band ? " with a band from " + band.low_label + " to " + band.high_label : "") + (ch.goal_label ? ". Goal " + ch.goal_label : "") + ".";
    return '<svg viewBox="0 0 1000 250" style="width:100%;height:250px;display:block" role="img" aria-label="' + esc(label) + '" data-projection-chart>' + parts.join("") + '</svg>';
  }

  function renderProjection(host, data) {
    host.innerHTML =
      '<div><span class="rv-label">Races and projections</span>' +
      '<p class="rv-subtitle">How the finish time is built, and how it has moved. The band tightens after each recalibration.</p></div>' +
      renderTiles(data.tiles) +
      (data.chain ? renderChain(data.chain) + renderChart(data.chart) :
        '<p class="rv-subtitle" data-chain-na>No upcoming A race, so there is no projection yet.</p>');
  }

  function loadProjection() {
    var host = document.getElementById("v2-perf-projection");
    if (!host) return;
    getJSON("/api/performance/projection")
      .then(function (data) { renderProjection(host, data); })
      .catch(function () { host.innerHTML = '<span class="rv-label">Races and projections</span><p>Not available.</p>'; });
  }

  document.addEventListener("DOMContentLoaded", function () {
    loadScoreCards();
    loadHero();
    loadProjection();
    loadFocus();
    loadMobility();
    loadAnchors();
  });
})();
