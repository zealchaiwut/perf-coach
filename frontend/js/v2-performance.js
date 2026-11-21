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

  // Revamp pages do not load nav.js (which patches fetch with the CSRF header),
  // so mutating calls attach the double-submit token themselves.
  function csrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrf-token=([^;]*)/);
    if (m) return Promise.resolve(decodeURIComponent(m[1]));
    return fetch("/api/csrf-token", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (b) {
        if (b && b.csrf_token) {
          document.cookie = "csrf-token=" + encodeURIComponent(b.csrf_token) + "; Path=/; SameSite=Lax" +
            (window.location.protocol === "https:" ? "; Secure" : "");
        }
        var again = document.cookie.match(/(?:^|;\s*)csrf-token=([^;]*)/);
        return again ? decodeURIComponent(again[1]) : (b && b.csrf_token) || "";
      })
      .catch(function () { return ""; });
  }

  function sendJSON(method, url, body) {
    return csrfToken().then(function (token) {
      var headers = { "Content-Type": "application/json" };
      if (token) headers["X-CSRF-Token"] = token;
      return fetch(url, {
        method: method,
        credentials: "same-origin",
        headers: headers,
        body: JSON.stringify(body),
      });
    }).then(function (r) {
      return r.json().then(function (data) {
        if (!r.ok) throw new Error(errText(data, r.status));
        return data;
      });
    });
  }

  function errText(data, status) {
    var d = data && data.detail;
    if (Array.isArray(d) && d.length) return d[0].msg || ("HTTP " + status);
    if (d && typeof d === "object") return d.error || ("HTTP " + status);
    return d || ("HTTP " + status);
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

  // ── Race list: needs result, upcoming, completed, add/edit (P4-11) ────────
  // Rows come from /api/performance/races. Recording uses the existing
  // POST /api/races/{id}/calibrate flow; edits use PATCH /api/races/{id}.

  var raceIndex = {};

  function parseHMS(text) {
    var t = String(text || "").trim();
    if (!t) return null;
    var parts = t.split(":");
    if (parts.length < 2 || parts.length > 3) return NaN;
    var nums = parts.map(function (p) { return /^\d+$/.test(p) ? parseInt(p, 10) : NaN; });
    if (nums.some(isNaN)) return NaN;
    if (nums.length === 2) return nums[0] * 60 + nums[1];
    return nums[0] * 3600 + nums[1] * 60 + nums[2];
  }

  function reloadProjectionViews() {
    loadHero();
    loadProjection();
    loadRaces();
    loadCoach();
    loadRaces();
  }

  function roleChips(r) {
    return '<span class="rv-chip" data-race-priority>' + esc(r.priority) + '</span> ' +
      '<span class="rv-chip" data-race-role="' + esc(r.role) + '">' + esc(r.role_label) + '</span>';
  }

  function raceHead(r, extra) {
    return '<div>' + roleChips(r) + ' <strong>' + esc(r.name) + '</strong>' + (extra || "") +
      '<br><span class="rv-subtitle">' + esc(r.race_date) + (r.distance_km ? " \u00b7 " + esc(r.distance_km) + " km" : "") +
      ' \u00b7 ' + esc(r.role_target) + '</span></div>';
  }

  function goalCell(r) {
    return '<div><span class="rv-label">Goal</span><br><strong>' + esc(fmtHMS(r.goal_sec)) + '</strong>' +
      (r.goal_pace_seconds_per_km ? ' <span class="rv-subtitle">' + esc(fmtPace(r.goal_pace_seconds_per_km)) + '</span>' : "") + '</div>';
  }

  function deltaChip(label, c) {
    if (!c || c.score == null) return '<span class="rv-chip">' + label + ' \u2014</span>';
    var d = c.delta_28d == null ? "" : " " + (c.delta_28d > 0 ? "+" : c.delta_28d < 0 ? "\u2212" : "") + Math.abs(Math.round(c.delta_28d));
    return '<span class="rv-chip">' + label + " " + esc(Math.round(c.score)) + esc(d) + '</span>';
  }

  function debriefChip(r) {
    var d = r.debrief;
    if (!d) return "";
    return ' <a class="rv-chip" data-debrief-chip href="' + esc(d.link) + '">Debrief' +
      (d.lessons_count ? " \u00b7 " + esc(d.lessons_count) + " lesson" + (d.lessons_count === 1 ? "" : "s") : "") + '</a>';
  }

  function renderNeedsResult(r) {
    var sug = r.suggested_actual;
    var actual = sug
      ? '<strong data-suggested-actual>' + esc(fmtHMS(sug.moving_seconds)) + '</strong> <span class="rv-subtitle">suggested \u00b7 ' +
        esc(sug.date) + ' \u00b7 ' + esc(sug.distance_km) + ' km</span>'
      : '<span class="rv-subtitle" data-no-match>' + esc(r.suggestion_reason || "No synced run matched") + '</span>';
    return '<div class="rv-row rv-card--soft" data-needs-result="' + esc(r.id) + '" style="flex-wrap:wrap;padding:10px">' +
      raceHead(r, debriefChip(r)) + goalCell(r) +
      '<div><span class="rv-label">Actual</span><br>' + actual + '</div>' +
      '<div class="rv-row"><label class="rv-label">Time <input type="text" inputmode="numeric" placeholder="h:mm:ss" size="8" data-actual-input value="' +
      esc(sug ? fmtHMS(sug.moving_seconds) : "") + '"></label>' +
      '<button type="button" class="rv-btn rv-btn--primary" data-record="' + esc(r.id) + '">Record and recalibrate</button></div></div>';
  }

  function renderUpcoming(r) {
    var est = r.estimate || {};
    var estHtml = est.available
      ? '<strong data-race-estimate>' + esc(fmtHMS(est.est_sec)) + '</strong>' +
        (est.band_sec != null ? ' <span class="rv-subtitle">\u00b1' + esc(fmtHMS(est.band_sec)) + '</span>' : "")
      : '<span class="rv-subtitle">not available</span>';
    var rs = r.race_specific || {};
    var extra = (r.is_target ? ' <span class="rv-chip" data-race-target>Target</span>' : "") +
      (r.recalibrates_here ? ' <span class="rv-subtitle" data-recalibrates-here>recalibrates here</span>' : "");
    return '<div class="rv-row" data-upcoming="' + esc(r.id) + '" style="flex-wrap:wrap;padding:8px 0">' +
      raceHead(r, extra) + goalCell(r) +
      '<div><span class="rv-label">Estimate</span><br>' + estHtml + '</div>' +
      '<div class="rv-row">' + deltaChip("End", rs.endurance) + deltaChip("Spd", rs.speed) + '</div>' +
      '<button type="button" class="rv-btn rv-btn--secondary" data-edit-race="' + esc(r.id) + '">Edit</button></div>';
  }

  function renderCompleted(r) {
    var g = r.goal_minus_actual_sec;
    var vs = g == null ? "" : g >= 0 ? "beat goal by " + fmtHMS(g) : "missed goal by " + fmtHMS(g);
    return '<div class="rv-metric" data-completed="' + esc(r.id) + '">' + roleChips(r) + ' <strong>' + esc(r.name) + '</strong>' + debriefChip(r) + '<br>' +
      '<span class="rv-subtitle">' + esc(r.race_date) + (r.distance_km ? " \u00b7 " + esc(r.distance_km) + " km" : "") + '</span><br>' +
      '<span class="rv-label">Chip</span> <strong data-chip-time>' + esc(fmtHMS(r.chip_time_sec)) + '</strong>' +
      (r.moving_time_sec != null ? ' <span class="rv-subtitle" data-moving-time>moving ' + esc(fmtHMS(r.moving_time_sec)) + '</span>' : "") +
      '<br><span class="rv-subtitle">goal ' + esc(fmtHMS(r.goal_sec)) + (vs ? " \u00b7 " + esc(vs) : "") + '</span></div>';
  }

  function renderRaces(host, data) {
    var needs = data.needs_result || [], up = data.upcoming || [], done = data.completed || [];
    raceIndex = {};
    needs.concat(up, done).forEach(function (r) { raceIndex[r.id] = r; });
    var more = data.total_upcoming > up.length ? '<span class="rv-subtitle">Showing ' + up.length + ' of ' + esc(data.total_upcoming) + ' upcoming races</span>' : "";
    host.innerHTML =
      '<div class="rv-row"><span class="rv-label">Races</span><button type="button" class="rv-btn rv-btn--primary" id="v2-race-add">Add a race</button></div>' +
      (needs.length ? '<div class="rv-stack" data-section="needs-result"><span class="rv-label">Needs a result</span>' + needs.map(renderNeedsResult).join("") + '</div>' : "") +
      '<div class="rv-stack" data-section="upcoming"><span class="rv-label">Upcoming</span>' +
      (up.length ? up.map(renderUpcoming).join("") + more : '<p class="rv-subtitle">No upcoming races.</p>') + '</div>' +
      (done.length ? '<div class="rv-stack" data-section="completed"><span class="rv-label">Completed</span><div class="rv-row" style="flex-wrap:wrap;align-items:stretch">' + done.map(renderCompleted).join("") + '</div></div>' : "");
    host.querySelector("#v2-race-add").addEventListener("click", function () { openRaceDrawer(null); });
    Array.prototype.forEach.call(host.querySelectorAll("[data-edit-race]"), function (b) {
      b.addEventListener("click", function () { openRaceDrawer(raceIndex[b.getAttribute("data-edit-race")]); });
    });
    Array.prototype.forEach.call(host.querySelectorAll("[data-record]"), function (b) {
      b.addEventListener("click", function () {
        var row = b.closest("[data-needs-result]");
        recordResult(b.getAttribute("data-record"), row.querySelector("[data-actual-input]").value, b);
      });
    });
  }

  function recordResult(raceId, text, btn) {
    var secs = parseHMS(text);
    if (secs == null || isNaN(secs) || secs <= 0) { toast("Enter the finish time as h:mm:ss"); return; }
    btn.disabled = true;
    sendJSON("POST", "/api/races/" + encodeURIComponent(raceId) + "/calibrate", { actual_time_seconds: secs })
      .then(function (res) {
        var s = (res && res.suggestions) || {};
        toast("Result recorded and projection recalibrated");
        reloadProjectionViews();
        if (s.suggested_ctl_days != null || s.suggested_atl_days != null) openAcceptDrawer(raceId, s);
      })
      .catch(function (e) {
        btn.disabled = false;
        var m = String(e.message || "");
        toast(m.indexOf("goal") >= 0 ? "Set a goal time on this race first (Edit), then record the result" : "Could not record: " + m);
      });
  }

  function openAcceptDrawer(raceId, s) {
    var body = openDrawer(
      '<h2 class="rv-label" id="v2-perf-drawer-title">Update your fitness constants?</h2>' +
      '<p>' + esc(s.explanation || "This result suggests new fitness constants.") + '</p>' +
      '<p class="rv-subtitle">Fitness ' + esc(s.suggested_ctl_days == null ? "unchanged" : s.suggested_ctl_days + " days") +
      ' \u00b7 fatigue ' + esc(s.suggested_atl_days == null ? "unchanged" : s.suggested_atl_days + " days") + '</p>' +
      '<div class="rv-row"><button type="button" class="rv-btn rv-btn--secondary" data-close>Keep current</button>' +
      '<button type="button" class="rv-btn rv-btn--primary" data-accept>Accept</button></div>'
    );
    if (!body) return;
    body.querySelector("[data-close]").addEventListener("click", closeDrawer);
    body.querySelector("[data-accept]").addEventListener("click", function () {
      sendJSON("POST", "/api/races/" + encodeURIComponent(raceId) + "/calibrate/accept",
        { ctl_days: s.suggested_ctl_days, atl_days: s.suggested_atl_days })
        .then(function () { closeDrawer(); toast("Constants updated"); reloadProjectionViews(); })
        .catch(function (e) { toast("Could not save: " + e.message); });
    });
  }

  function openRaceDrawer(race) {
    var editing = !!race;
    var body = openDrawer(
      '<h2 class="rv-label" id="v2-perf-drawer-title">' + (editing ? "Edit race" : "Add a race") + '</h2>' +
      '<form id="v2-race-form" class="rv-stack" novalidate>' +
      '<label class="rv-label">Name <input type="text" name="name" required value="' + esc(editing ? race.name : "") + '"></label>' +
      '<label class="rv-label">Date <input type="date" name="race_date" required value="' + esc(editing ? race.race_date : "") + '"></label>' +
      '<label class="rv-label">Distance (km) <input type="number" name="distance_km" min="0.1" step="0.001" required value="' + esc(editing && race.distance_km ? race.distance_km : "") + '"></label>' +
      '<label class="rv-label">Goal time (h:mm:ss, optional) <input type="text" name="goal" placeholder="4:30:00" value="' + esc(editing && race.goal_sec ? fmtHMS(race.goal_sec) : "") + '"></label>' +
      '<label class="rv-label">Priority <select name="priority">' +
      [["A", "A \u00b7 A race"], ["B", "B \u00b7 PB attempt"], ["C", "C \u00b7 Fun run"]].map(function (o) {
        return '<option value="' + o[0] + '"' + ((editing ? race.priority : "B") === o[0] ? " selected" : "") + '>' + o[1] + '</option>';
      }).join("") + '</select></label>' +
      '<p class="rv-subtitle">The race role follows priority: A is the A race, B a PB attempt, C a fun run. Only the first two recalibrate the projection.</p>' +
      '<p class="rv-warn-inline" id="v2-race-error" role="alert" hidden></p>' +
      '<div class="rv-row"><button type="button" class="rv-btn rv-btn--secondary" data-close>Cancel</button>' +
      '<button type="submit" class="rv-btn rv-btn--primary">' + (editing ? "Save race" : "Add race") + '</button></div></form>'
    );
    if (!body) return;
    body.querySelector("[data-close]").addEventListener("click", closeDrawer);
    body.querySelector("#v2-race-form").addEventListener("submit", function (ev) {
      ev.preventDefault();
      var f = ev.target, err = body.querySelector("#v2-race-error");
      var goal = parseHMS(f.elements.goal.value);
      if (isNaN(goal)) { err.textContent = "Goal time must look like 4:30:00"; err.hidden = false; return; }
      var dist = parseFloat(f.elements.distance_km.value);
      if (!f.elements.name.value.trim() || !f.elements.race_date.value || !(dist > 0)) {
        err.textContent = "Name, date and a distance above zero are required"; err.hidden = false; return;
      }
      var payload = { name: f.elements.name.value.trim(), distance_km: dist, goal_time_seconds: goal, priority: f.elements.priority.value };
      var req;
      if (editing) {
        payload.race_date = f.elements.race_date.value;
        req = sendJSON("PATCH", "/api/races/" + encodeURIComponent(race.id), payload);
      } else {
        payload.date = f.elements.race_date.value;
        req = sendJSON("POST", "/api/races", payload);
      }
      req.then(function () {
        closeDrawer();
        toast(editing ? "Race saved" : "Race added");
        reloadProjectionViews();
      }).catch(function (e) { err.textContent = e.message; err.hidden = false; });
    });
  }

  function loadRaces() {
    var host = document.getElementById("v2-perf-races");
    if (!host) return;
    getJSON("/api/performance/races")
      .then(function (data) { renderRaces(host, data); })
      .catch(function () { host.innerHTML = '<span class="rv-label">Races</span><p>Not available.</p>'; });
  }

  document.addEventListener("perf:edit-race", function (ev) {
    var r = ev.detail && raceIndex[ev.detail.raceId];
    if (r) openRaceDrawer(r);
  });

  // ── Coach block: check-in, review due, history (P4-12) ────────────────────
  // Everything comes from /api/performance/coach-block; outcomes save through
  // the existing PATCH /api/decisions/{id}. No model call.

  function copyCheckin(btn) {
    // Preferred path: the shared nav.js helper when it is on the page.
    if (window.NavCopy && typeof window.NavCopy.copyForClaude === "function") {
      window.NavCopy.copyForClaude(btn, window.NavCopy.CONSULT_ENDPOINT, "consult copied");
      return;
    }
    // Revamp pages do not load nav.js (it would inject the legacy top nav), so use
    // the same endpoint and the page's own toast.
    btn.disabled = true;
    toast("Building check-in\u2026");
    fetch("/api/coach/consult", { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("export failed (" + r.status + ")");
        return r.text();
      })
      .then(function (text) { return navigator.clipboard.writeText(text); })
      .then(function () { toast("Check-in copied \u2014 paste it into Claude"); })
      .catch(function (e) { toast("Could not copy check-in: " + e.message); })
      .then(function () { btn.disabled = false; });
  }

  function chipHtml(c) {
    return '<span class="rv-chip" data-evidence="' + esc(c.key) + '">' + esc(c.label) + ': <strong>' + esc(c.value) + '</strong>' +
      (c.unit ? " " + esc(c.unit) : "") + '</span>';
  }

  function renderReviewDue(r) {
    if (!r) return "";
    var lines = (r.review_lines || []).length
      ? '<ul>' + r.review_lines.map(function (l) { return '<li data-review-line>' + esc(l) + '</li>'; }).join("") + '</ul>'
      : '<p class="rv-subtitle">This change list did not name what to check. Note how it went.</p>';
    return '<div class="rv-card rv-card--soft rv-stack" data-review-due="' + esc(r.id) + '">' +
      '<div class="rv-row"><span class="rv-label">Review due</span><span class="rv-subtitle">decided ' + esc(r.decided_on) + ' \u00b7 review on ' + esc(r.review_on) + '</span></div>' +
      lines +
      ((r.chips || []).length ? '<div class="rv-row" style="justify-content:flex-start;flex-wrap:wrap">' + r.chips.map(chipHtml).join("") + '</div>' : "") +
      '<label class="rv-label">Outcome <textarea data-outcome-text rows="3" maxlength="1000" style="width:100%" placeholder="What happened?"></textarea></label>' +
      '<div class="rv-row"><button type="button" class="rv-btn rv-btn--secondary" data-not-applied>Did not apply</button>' +
      '<button type="button" class="rv-btn rv-btn--primary" data-save-outcome>Save outcome</button></div></div>';
  }

  function renderHistory(rows, pasteLink) {
    var list = (rows || []).length
      ? rows.map(function (h) {
          return '<div class="rv-row" data-history="' + esc(h.id) + '" style="padding:6px 0">' +
            '<span class="rv-subtitle">' + esc(h.decided_on) + '</span>' +
            '<span style="flex:1;margin:0 10px">' + esc(h.summary || "\u2014") + '</span>' +
            '<span class="rv-chip" data-status="' + esc(h.status) + '">' + esc(h.status_label) + '</span></div>';
        }).join("")
      : '<p class="rv-subtitle">No decisions yet. After a check-in, paste the change list.</p>';
    return '<div class="rv-stack"><div class="rv-row"><span class="rv-label">Decision history</span>' +
      '<a href="' + esc(pasteLink || "/coach#paste") + '" data-paste-link>Paste a change list</a></div>' + list + '</div>';
  }

  function renderCoach(host, data) {
    var ck = data.checkin || {};
    var state = ck.state === "done" ? "Check-in done this week" : "Check-in due this week";
    host.innerHTML =
      '<div class="rv-row"><div><span class="rv-label">Coach</span> ' +
      '<span class="rv-chip" data-checkin-state="' + esc(ck.state || "due") + '">' + esc(state) + '</span> ' +
      '<a href="' + esc(ck.link || "/coach") + '" data-checkin-link>Open check-in</a></div>' +
      '<button type="button" class="rv-btn rv-btn--primary" id="v2-copy-checkin">Copy check-in</button></div>' +
      renderReviewDue(data.review_due) + renderHistory(data.history, data.paste_link);
    host.querySelector("#v2-copy-checkin").addEventListener("click", function (ev) { copyCheckin(ev.currentTarget); });
    var due = data.review_due;
    if (!due) return;
    var card = host.querySelector("[data-review-due]");
    card.querySelector("[data-save-outcome]").addEventListener("click", function () {
      var note = card.querySelector("[data-outcome-text]").value.trim();
      if (!note) { toast("Write what happened first"); return; }
      sendJSON("PATCH", "/api/decisions/" + encodeURIComponent(due.id), { outcome_note: note })
        .then(function () { toast("Outcome saved"); loadCoach(); })
        .catch(function (e) { toast("Could not save: " + e.message); });
    });
    card.querySelector("[data-not-applied]").addEventListener("click", function () {
      sendJSON("PATCH", "/api/decisions/" + encodeURIComponent(due.id), { applied: false })
        .then(function () { toast("Marked as not applied"); loadCoach(); })
        .catch(function (e) { toast("Could not update: " + e.message); });
    });
  }

  function loadCoach() {
    var host = document.getElementById("v2-perf-coach");
    if (!host) return;
    getJSON("/api/performance/coach-block")
      .then(function (data) { renderCoach(host, data); })
      .catch(function () { host.innerHTML = '<span class="rv-label">Coach</span><p>Not available.</p>'; });
  }

  document.addEventListener("DOMContentLoaded", function () {
    loadScoreCards();
    loadHero();
    loadProjection();
    loadRaces();
    loadFocus();
    loadMobility();
    loadAnchors();
  });
})();
