// Revamp Performance page (v2). Regions are added per Phase 4 ticket; each
// region renders from one API payload and never recomputes scores locally.
(function () {
  "use strict";

  var esc = window.AppCommon.escapeHtml;
  var PERFORMANCE_PAGE = "/api/performance/page";
  var FIRST_SECTIONS = "hero,radar,score_cards";
  var LAZY_SECTIONS = "readiness,projection,races,coach,mobility,anchors";
  var LAZY_HOST_IDS = [
    "v2-perf-readiness",
    "v2-perf-projection-wrap",
    "v2-perf-coach",
    "v2-perf-mobility",
    "v2-perf-strength-anchors",
  ];

  function scoreText(obj, raw) {
    if (typeof obj === "number") return String(Math.round(obj));
    if (obj && obj.score_display != null) return String(obj.score_display);
    if (raw === undefined) raw = obj && obj.score;
    if (raw == null) return "—";
    if (typeof raw === "number") return String(Math.round(raw));
    var n = Number(raw);
    return isNaN(n) ? String(raw) : String(Math.round(n));
  }

  function toast(msg) {
    var el = document.getElementById("rv-toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.add("is-visible");
    window.setTimeout(function () { el.classList.remove("is-visible"); }, 2800);
  }

  function pageUrl(sections) {
    return PERFORMANCE_PAGE + "?sections=" + encodeURIComponent(sections) + "&size=large";
  }

  function isRetryable(err) {
    var status = err && err.status;
    if (!status) return true;
    return status === 502 || status === 503 || status === 504;
  }

  var pageEtags = {};

  function fetchJSONOnce(url) {
    var headers = {};
    if (pageEtags[url]) headers["If-None-Match"] = pageEtags[url];
    return fetch(url, { credentials: "same-origin", headers: headers }).then(function (r) {
      var tag = r.headers.get("ETag");
      if (tag) pageEtags[url] = tag;
      if (r.status === 304) return { _notModified: true };
      if (!r.ok) {
        var err = new Error("HTTP " + r.status);
        err.status = r.status;
        throw err;
      }
      return r.json();
    });
  }

  function fetchPage(sections) {
    var url = pageUrl(sections);
    return fetchJSONOnce(url).catch(function (err) {
      if (!isRetryable(err)) throw err;
      var delay = 1000 + Math.floor(Math.random() * 1000);
      return new Promise(function (ok) { setTimeout(ok, delay); }).then(function () {
        return fetchJSONOnce(url);
      });
    });
  }

  function sectionFailed(data) {
    return !data || (typeof data === "object" && data.error);
  }

  function setRegionLoading(host, label) {
    if (!host) return;
    host.setAttribute("aria-busy", "true");
    host.hidden = false;
    host.innerHTML = '<p class="rv-subtitle rv-region-loading">' + esc(label) + "…</p>";
  }

  function renderSectionError(host, label, retryFn) {
    if (!host) return;
    host.removeAttribute("aria-busy");
    host.hidden = false;
    host.innerHTML =
      '<span class="rv-label">' + esc(label) + "</span>" +
      '<p class="rv-subtitle">Could not load this section. ' +
      '<button type="button" class="rv-btn rv-btn--secondary rv-btn--sm" data-section-retry>Retry</button></p>';
    var btn = host.querySelector("[data-section-retry]");
    if (btn) btn.addEventListener("click", retryFn);
  }

  function refetchSections(sections, apply) {
    delete pageEtags[pageUrl(sections)];
    fetchPage(sections).then(function (body) {
      if (body && body._notModified) return;
      apply(body || {});
    }).catch(function () {
      apply(null);
    });
  }

  var AFTER_RACE_COPY =
    "Once you record a race result, it replaces your current anchors: Endurance, Speed " +
    "and the projection re-anchor on that effort. Record it on the race list to recalibrate.";

  function renderAfterRaceFallback(afterEl, copy) {
    if (!afterEl) return;
    afterEl.innerHTML =
      '<span class="rv-label">After the race</span>' +
      '<p class="rv-subtitle" style="margin:0;line-height:1.55">' + esc(copy || AFTER_RACE_COPY) + "</p>";
  }

  function initPerfHeader() {
    var el = document.getElementById("v2-perf-subtitle");
    if (!el) return;
    var d = new Date();
    var day = d.toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long" });
    el.textContent = day + " \u00b7 where you stand, and what work moves it";
  }

  function sendJSON(method, url, body) {
    var opts = {
      method: method,
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
    };
    if (body !== undefined && body !== null) opts.body = JSON.stringify(body);
    return fetch(url, opts).then(function (r) {
      if (r.status === 204 || r.status === 205) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return null;
      }
      return r.text().then(function (text) {
        var data = null;
        if (text) {
          try { data = JSON.parse(text); } catch (e) { data = { detail: text }; }
        }
        if (!r.ok) {
          var err = new Error(errText(data, r.status));
          err.status = r.status;
          throw err;
        }
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
        .then(function (data) {
          renderAnchors(host, data.anchors);
          toast("Anchors saved");
          refetchSections("radar", function (b) { applyRadar(b && b.radar); });
        })
        .catch(function (e) { toast("Could not save: " + e.message); });
    });
  }

  function applyAnchors(data) {
    var host = document.getElementById("v2-perf-strength-anchors");
    if (!host) return;
    if (sectionFailed(data)) {
      renderSectionError(host, "Strength anchors", loadAnchors);
      return;
    }
    host.removeAttribute("aria-busy");
    renderAnchors(host, data.anchors || []);
  }

  function loadAnchors() {
    var host = document.getElementById("v2-perf-strength-anchors");
    if (!host) return;
    setRegionLoading(host, "Loading anchors");
    refetchSections("anchors", function (body) { applyAnchors(body && body.anchors); });
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
        refetchSections("mobility,radar", function (b) {
          applyMobility(b && b.mobility);
          applyRadar(b && b.radar);
        });
      }).catch(function (e) { err.textContent = e.message; err.hidden = false; });
    });
  }

  function applyMobility(data) {
    var host = document.getElementById("v2-perf-mobility");
    if (!host) return;
    if (sectionFailed(data)) {
      renderSectionError(host, "Mobility self-test", loadMobility);
      return;
    }
    host.removeAttribute("aria-busy");
    renderMobility(host, data);
  }

  function loadMobility() {
    var host = document.getElementById("v2-perf-mobility");
    if (!host) return;
    setRegionLoading(host, "Loading mobility");
    refetchSections("mobility", function (body) { applyMobility(body && body.mobility); });
  }

  // ── Focus card, why-not card and the queue into Plan (P4-7) ───────────────

  function focusChipLabel(tag) {
    var map = {
      plyo: "Plyo \u00b7 2\u00d7 week",
      heavy_calf_raise: "Heavy calf raise \u00b7 1\u00d7 week",
      drills: "Drills before easy runs",
    };
    return map[tag] || tag.replace(/_/g, " ");
  }

  function renderFocus(host, data) {
    var focus = data.focus;
    if (!focus) {
      host.innerHTML = '<div class="rv-card rv-stack"><span class="rv-label">Most room to grow</span>' +
        '<p class="rv-subtitle">Nothing to rank yet: it needs a fresh, measured axis.</p></div>';
      return;
    }
    var work = focus.work || {};
    var queuedItem = (data.queue || {})[focus.axis];
    var weekLbl = "Queue this work";
    if (data.suggested_queue_week) {
      try {
        var wd = new Date(data.suggested_queue_week + "T12:00:00");
        weekLbl = "Queue for week of " + wd.toLocaleDateString("en-GB", { day: "numeric", month: "short" });
      } catch (e) { weekLbl = "Queue for week of " + esc(data.suggested_queue_week); }
    }
    var chips = (work.template_tags || []).map(function (t) {
      return '<span class="rv-focus-work-chip">' + esc(focusChipLabel(t)) + "</span>";
    }).join("");
    var tss = work.tss_estimate != null ? '<span class="rv-subtitle" style="color:#a8b6d6">+' +
      esc(Math.round(work.tss_estimate)) + " TSS a week</span>" : "";
    var action;
    if (!work.queueable) {
      action = '<p class="rv-subtitle" style="color:#d5def3">' + esc(work.advice) + " (advice only, not queued)</p>";
    } else if (queuedItem) {
      action = '<span class="rv-chip" data-testid="focus-queued">Queued for week of ' + esc(queuedItem.earliest_week) + "</span>";
    } else {
      action = '<div class="rv-row" style="flex-wrap:wrap;align-items:center;gap:10px">' +
        '<button type="button" class="rv-btn rv-btn--accent" id="v2-focus-queue">' + weekLbl + "</button>" + tss + "</div>";
    }
    var whyTitle = "Why " + focus.label + " and not the others";
    var dist = data.distance_class || "marathon";
    function whyRow(w, kind) {
      var axis = w.label + (kind === "focus" ? " (focus)" : "");
      var score = scoreText(w);
      var weight = w.weight_pct != null ? w.weight_pct + "%" : "—";
      var gap = w.weighted_gap != null ? Number(w.weighted_gap).toFixed(1) : "—";
      return '<tr class="rv-why-row--' + kind + '">' +
        "<td>" + esc(axis) + "</td>" +
        '<td class="rv-why-num">' + esc(score) + "</td>" +
        '<td class="rv-why-num rv-why-col-weight">' + esc(weight) + "</td>" +
        '<td class="rv-why-num rv-why-col-gap">' + esc(gap) + "</td>" +
        "<td>" + esc(w.reason || "") + "</td></tr>";
    }
    var body = whyRow(focus, "focus");
    (data.why_not || []).forEach(function (w) {
      var kind = w.status === "never_measured" || w.never_measured ? "never" :
        (w.status === "stale" || w.stale ? "stale" : "ranked");
      body += whyRow(w, kind);
    });
    var whyTable =
      '<table class="rv-why-table"><thead><tr>' +
      '<th scope="col">Axis</th>' +
      '<th scope="col" class="rv-why-num">Score</th>' +
      '<th scope="col" class="rv-why-num rv-why-col-weight">Weight · ' + esc(dist) + "</th>" +
      '<th scope="col" class="rv-why-num rv-why-col-gap">Weighted gap</th>' +
      '<th scope="col">Why not</th>' +
      "</tr></thead><tbody>" + body + "</tbody></table>";
    host.innerHTML =
      '<div class="rv-card rv-stack" style="background:#0b1530;color:#fff">' +
      '<span class="rv-label" style="color:#e4ff52">Most room to grow</span>' +
      '<h2 style="margin:0">' + esc(focus.label) + ' <span style="font-family:var(--rv-mono)">' + esc(scoreText(focus)) + "</span></h2>" +
      '<div class="rv-focus-work-chips">' + chips + "</div>" +
      action + "</div>" +
      '<div class="rv-card rv-stack rv-perf-focus-why"><span class="rv-label">' +
      esc(whyTitle) + "</span>" + whyTable + "</div>";
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

  function applyRadar(data) {
    var chart = document.getElementById("v2-perf-radar-chart");
    var focusHost = document.getElementById("v2-perf-focus");
    if (sectionFailed(data)) {
      if (chart) renderSectionError(chart, "Status", loadFocus);
      if (focusHost) renderSectionError(focusHost, "Focus", loadFocus);
      return;
    }
    if (chart) {
      if (window.PerfRadar && window.PerfRadar.paint) window.PerfRadar.paint(chart, data);
      else {
        chart.innerHTML = data.svg || "";
        chart.removeAttribute("aria-busy");
      }
      chart.onclick = function (ev) {
        var t = ev.target;
        var href = "";
        while (t && t !== chart) {
          if (t.getAttribute) href = t.getAttribute("href") || href;
          if (t.tagName === "A" || href) break;
          t = t.parentNode;
        }
        if (href === "#v2-mobility-log") {
          ev.preventDefault();
          openMobilityDrawer();
        }
      };
    }
    if (focusHost) {
      if (sectionFailed(data.focus)) renderSectionError(focusHost, "Focus", loadFocus);
      else renderFocus(focusHost, data.focus);
    }
  }

  function loadFocus() {
    var chart = document.getElementById("v2-perf-radar-chart");
    if (chart) chart.setAttribute("aria-busy", "true");
    refetchSections("radar", function (body) { applyRadar(body && body.radar); });
  }

  // ── A-race hero and the after-the-race card (P4-8) ────────────────────────
  // Display only: every value comes from the page hero section; the one local
  // calculation is formatting seconds as h:mm:ss.

  function fmtHMS(sec) {
    if (sec == null) return "—";
    var s = Math.abs(Math.round(sec));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(r).padStart(2, "0");
  }
  function fmtPace(sec) { return sec == null ? "—" : fmtHMS(sec).replace(/^0:/, "") + " /km"; }
  var MONTHS_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  function fmtDayMonth(iso) {
    if (!iso) return "";
    var p = String(iso).slice(0, 10).split("-");
    if (p.length < 3) return String(iso);
    var d = parseInt(p[2], 10);
    var mi = parseInt(p[1], 10) - 1;
    if (!d || mi < 0 || mi > 11) return String(iso);
    return d + " " + MONTHS_SHORT[mi];
  }
  function fmtKm(km, label) {
    if (label) return String(label);
    if (km == null || km === "") return "";
    var n = Number(km);
    if (isNaN(n)) return String(km);
    if (Math.abs(n - 21.0975) < 0.2 || Math.abs(n - 42.195) < 0.2 || n >= 21) {
      return (Math.round(n * 10) / 10).toFixed(1);
    }
    if (Math.abs(n - Math.round(n)) < 1e-6) return String(Math.round(n));
    return String(n);
  }
  var ICON_EDIT = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
  var ICON_TRASH = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4h6v2"/></svg>';
  function signedGap(sec) {
    if (sec == null) return "—";
    if (sec === 0) return "0:00";
    // goal minus estimate: positive means the estimate beats the goal (shown as a minus time vs goal)
    return (sec > 0 ? "\u2212" : "+") + fmtHMS(sec);
  }

  function heroTile(label, value, sub, opts) {
    opts = opts || {};
    return '<div class="rv-perf-hero-tile' + (opts.mod ? " rv-perf-hero-tile--" + opts.mod : "") + '"' + (opts.attr || "") + ">" +
      '<span class="rv-perf-hero-tile-lbl' + (opts.lblGood ? " rv-perf-hero-tile-lbl--good" : "") + '">' + esc(label) + '</span>' +
      '<span class="rv-perf-hero-tile-val' + (opts.valGood ? " rv-perf-hero-tile-val--good" : "") + ' rv-mono">' + value + '</span>' +
      (sub ? '<span class="rv-mono rv-subtitle">' + sub + '</span>' : "") + '</div>';
  }

  function prBadge(r) {
    var isCp = r.role === "long_run" || r.race_type === "checkpoint";
    var text = isCp ? "CP" : (r.priority || "?");
    var mod = isCp ? "cp" : String(r.priority || "c").toLowerCase();
    return '<span class="rv-race-pr rv-race-pr--' + esc(mod) + '">' + esc(text) + '</span>';
  }

  function renderHero(host, afterHost, data) {
    var r = data.race;
    if (!r) {
      host.innerHTML = '<div class="rv-perf-hero-empty"><div><span class="rv-label">A race</span>' +
        '<p class="rv-subtitle">No upcoming A race. Pick the race this block is building to, and the radar targets switch to its distance and goal time.</p></div>' +
        '<a href="/v2/training/plan?setup=1" class="rv-btn rv-btn--secondary rv-btn--sm">+ Add an A race</a></div>';
    } else {
      var est = data.estimate || {};
      var goal = data.goal || {};
      var gap = data.gap || {};
      var estTile = est.available
        ? heroTile("Estimate", esc(fmtHMS(est.est_sec)), esc(fmtPace(est.pace_seconds_per_km)), { mod: "est", lblGood: true, valGood: true, attr: ' data-hero="estimate"' })
        : heroTile("Estimate", "—", esc(est.reason || "not available"), { mod: "est", attr: ' data-hero="estimate"' });
      var rangeTile = est.available && est.range_low_sec != null
        ? heroTile("Range" + (est.uncertainty_min ? " · ±" + esc(est.uncertainty_min) + " min" : ""),
            esc(fmtHMS(est.range_low_sec)) + " –<br>" + esc(fmtHMS(est.range_high_sec)), "", { attr: ' data-hero="range"' })
        : heroTile("Range", "—", "not available", { attr: ' data-hero="range"' });
      var gapVal = esc(signedGap(gap.goal_minus_estimate_sec));
      var gapGood = gap.goal_minus_estimate_sec != null && gap.goal_minus_estimate_sec > 0;
      var rs = data.race_specific || {};
      host.innerHTML =
        '<div class="rv-perf-hero-head">' +
        '<div class="rv-race-row__head">' + prBadge(r) +
        '<div><h2 class="rv-perf-hero-title">' + esc(r.name) + '</h2>' +
        '<span class="rv-perf-hero-meta rv-mono">' + esc(fmtDayMonth(r.race_date)) + (r.distance_km ? " · " + esc(fmtKm(r.distance_km, r.distance_label)) + " km" : "") +
        ' · ' + esc(r.role_label || "A race") + '</span></div></div>' +
        '<div class="rv-row">' +
        '<div class="rv-perf-countdown" data-hero="countdown"><div class="rv-perf-countdown-val rv-mono">' + esc(r.days_to_race) + '</div>' +
        '<div class="rv-perf-countdown-lbl">DAYS</div></div>' +
        (data.readiness_checklist ? '<span class="rv-chip" data-hero="readiness" title="A-race readiness">' +
          esc(data.readiness_checklist.count_label || "—") + ' ready</span>' : "") +
        '<button type="button" class="rv-btn rv-btn--secondary rv-btn--sm" id="v2-hero-change-race">Change race</button></div></div>' +
        '<div class="rv-perf-hero-tiles">' +
        heroTile("Goal", esc(fmtHMS(goal.time_sec)), esc(fmtPace(goal.pace_seconds_per_km)), { attr: ' data-hero="goal"' }) +
        estTile + rangeTile +
        heroTile("Gap to goal", gapVal, esc(gap.reading || ""), { valGood: gapGood, attr: ' data-hero="gap"' }) +
        '</div>' +
        '<div class="rv-perf-race-pills"><span class="rv-label">Race-specific</span>' +
        '<span class="rv-perf-race-pill" data-hero="race-endurance">End ' + esc(scoreText(rs.endurance)) + '</span>' +
        '<span class="rv-perf-race-pill" data-hero="race-speed">Spd ' + esc(scoreText(rs.speed)) + '</span>' +
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
      cpHtml = '<div class="rv-perf-checkpoint" data-after="checkpoint">' +
        '<span class="rv-subtitle" style="font-size:12px;font-weight:700">' + esc(cp.label) + ' · ' + esc(fmtDayMonth(cp.target_date)) +
        (cp.distance_km ? " · " + esc(fmtKm(cp.distance_km, cp.distance_label)) + " km" : "") + '</span>' +
        '<span class="rv-mono" style="font-size:1.35rem;font-weight:600">' +
        (ce.available ? esc(fmtHMS(ce.est_sec)) : "Estimate not available") + '</span>' +
        (ce.available && cp.goal_sec ? '<span class="rv-mono rv-subtitle">goal ' + esc(fmtHMS(cp.goal_sec)) +
          (ce.band_sec != null ? " · ±" + esc(fmtHMS(ce.band_sec)).replace(/^0:/, "") : "") + '</span>' : "") +
        '</div>';
    }
    afterHost.innerHTML = '<span class="rv-label">After the race</span>' +
      '<p class="rv-subtitle" style="margin:0;line-height:1.55">' + esc(after.copy || "") + '</p>' + cpHtml;
  }

  function applyHero(data) {
    var host = document.getElementById("v2-perf-hero");
    var after = document.getElementById("v2-perf-after-race");
    if (!host || !after) return;
    if (sectionFailed(data)) {
      renderSectionError(host, "A race", loadHero);
      after.removeAttribute("aria-busy");
      after.innerHTML =
        '<span class="rv-label">After the race</span>' +
        '<p class="rv-subtitle">Could not load this section.</p>';
      return;
    }
    host.removeAttribute("aria-busy");
    after.removeAttribute("aria-busy");
    renderHero(host, after, data);
  }

  function loadHero() {
    var host = document.getElementById("v2-perf-hero");
    var after = document.getElementById("v2-perf-after-race");
    if (!host || !after) return;
    setRegionLoading(host, "Loading A race");
    setRegionLoading(after, "Loading");
    refetchSections("hero", function (body) { applyHero(body && body.hero); });
  }

  function stateChip(state) {
    var bg = state === "done" ? "#dcfce7" : state === "in_progress" ? "#fef3c7" : "#eef1f7";
    var ink = state === "done" ? "#15803d" : state === "in_progress" ? "#92400e" : "#475569";
    return '<span class="rv-chip" style="background:' + bg + ";color:" + ink + '">' + esc(state.replace("_", " ")) + "</span>";
  }

  function renderReadiness(host, data) {
    if (!data || !data.available) {
      host.hidden = true;
      host.innerHTML = "";
      return;
    }
    host.hidden = false;
    var items = (data.items || []).map(function (it) {
      var action = "";
      if (it.action === "update_cp") {
        action = '<a class="rv-btn rv-btn--secondary rv-btn--sm" href="/v2/settings#thresholds" data-readiness-action="update-cp">Update CP</a>';
      }
      if (it.manual) {
        action = '<button type="button" class="rv-btn rv-btn--secondary rv-btn--sm" data-toilet-save>Save plan</button>';
      }
      var note = it.note != null ? it.note : "";
      return '<div class="rv-readiness-row" data-readiness-item="' + esc(it.key) + '">' +
        '<div class="rv-readiness-copy"><div class="rv-readiness-title">' + esc(it.label) + "</div>" +
        '<div class="rv-readiness-detail">' + esc(it.detail || "") + "</div>" +
        (it.manual ? '<textarea class="rv-readiness-note" rows="2" data-toilet-note placeholder="Race-morning toilet plan\u2026">' +
          esc(note) + "</textarea>" : "") + "</div>" +
        '<div class="rv-readiness-status">' + stateChip(it.state) + "</div>" +
        '<div class="rv-readiness-action">' + action + "</div></div>";
    }).join("");
    host.innerHTML = '<h2 class="rv-label">A-race readiness</h2><p class="rv-subtitle">' +
      esc((data.summary && data.summary.count_label) || "") + " items complete.</p>" + items;
    var raceId = data.race_id;
    var saveBtn = host.querySelector("[data-toilet-save]");
    var noteEl = host.querySelector("[data-toilet-note]");
    if (saveBtn && noteEl && raceId) {
      saveBtn.addEventListener("click", function () {
        var note = noteEl.value.trim();
        if (!note) { toast("Write the toilet plan first"); return; }
        sendJSON("PATCH", "/api/races/" + encodeURIComponent(raceId), { notes: note, toilet_plan_done: true })
          .then(function () {
            toast("Toilet plan saved");
            refetchSections("readiness,hero", function (b) {
              applyReadiness(b && b.readiness);
              applyHero(b && b.hero);
            });
          })
          .catch(function (e) { toast("Could not save: " + e.message); });
      });
    }
  }

  function applyReadiness(data) {
    var host = document.getElementById("v2-perf-readiness");
    if (!host) return;
    if (sectionFailed(data)) {
      renderSectionError(host, "A-race readiness", loadReadiness);
      return;
    }
    host.removeAttribute("aria-busy");
    renderReadiness(host, data);
  }

  function loadReadiness() {
    var host = document.getElementById("v2-perf-readiness");
    if (!host) return;
    setRegionLoading(host, "Loading readiness");
    refetchSections("readiness", function (body) { applyReadiness(body && body.readiness); });
  }

  // ── Endurance and Speed cards (P4-9) ──────────────────────────────────────

  function sparkline(spark, axis) {
    if (!spark || !spark.values || spark.values.length < 2) return "";
    var v = spark.values, lo = Math.min.apply(null, v), hi = Math.max.apply(null, v);
    var span = hi - lo || 1, w = 200, h = 44;
    var stroke = axis === "speed" ? "#b45309" : "#1f3b8a";
    var fill = axis === "speed" ? "#fdeedd" : "#e3eaf8";
    var ptList = v.map(function (y, i) {
      return (i * w / (v.length - 1)).toFixed(1) + "," + (h - 4 - (y - lo) / span * (h - 8)).toFixed(1);
    });
    var pts = ptList.join(" ");
    var area = "M0," + h + " L" + ptList.join(" L") + " L" + w + "," + h + " Z";
    return '<svg viewBox="0 0 200 44" style="width:100%;height:44px" aria-hidden="true" data-sparkline>' +
      '<path d="' + area + '" fill="' + fill + '"/>' +
      '<polyline points="' + pts + '" fill="none" stroke="' + stroke + '" stroke-width="2"/></svg>';
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
    var axisMod = c.axis === "speed" ? " rv-score-card--speed" : "";
    var scoreCls = c.axis === "speed" ? " rv-score-num--speed" : " rv-score-num--endurance";
    var rows = (c.breakdown_rows || []).map(function (row) {
      var muted = row.muted ? " rv-score-bd-row--muted" : "";
      var val;
      if (row.key === "score") {
        val = esc(num(row.value)) + " \u2192 " + esc(row.display != null ? row.display : scoreText(c));
      } else if (row.signed) {
        val = (row.value > 0 ? "+" : "") + esc(num(row.value));
      } else {
        val = esc(num(row.value));
      }
      var valStyle = row.signed && row.value > 0 ? ' style="color:#2d5e10"' : "";
      return '<div class="rv-score-bd-row' + muted + '" data-breakdown="' + esc(row.key) + '">' +
        '<span class="rv-score-bd-dot"></span><span>' + esc(row.label) + '</span>' +
        '<span class="rv-mono rv-score-bd-val"' + valStyle + '>' + val + '</span></div>';
    }).join("");
    var where = rows
      ? '<div class="rv-score-bd"><span class="rv-score-bd-title">Where ' + esc(scoreText(c)) +
        ' comes from</span><div class="rv-score-bd-list" data-card-breakdown>' + rows + '</div></div>'
      : "";
    var callout = c.to_reach
      ? '<div class="rv-to-reach' + (c.axis === "speed" ? " rv-to-reach--speed" : "") + '" data-card-to-reach>' +
        (c.target_score != null ? '<span class="rv-mono rv-to-reach-arrow">\u2192 ' + esc(c.target_score) + '</span>' : "") +
        '<span>' + esc(c.to_reach) + '</span></div>'
      : "";
    var reason = c.reason ? '<p class="rv-score-headline" data-card-reason>' + esc(c.reason) + '</p>' : "";
    var ancHead = '<div class="rv-score-anc rv-score-anc--head"><span>Date</span><span>Raw</span><span>Age</span><span>Status</span></div>';
    var ancRows = (c.anchors || []).map(function (a) {
      var st = a.is_stale
        ? '<span class="rv-chip rv-chip--warn" data-anchor-stale>Stale \u00b7 decaying</span>'
        : '<span class="rv-chip rv-chip--good" data-anchor-fresh>Fresh</span>';
      return '<div class="rv-score-anc" data-anchor>' +
        '<span class="rv-mono">' + esc(a.display_date || a.date) + '</span>' +
        '<span class="rv-mono">' + esc(num(a.raw_score)) + '</span>' +
        '<span class="rv-mono">' + esc(num(a.age_weeks)) + ' wk</span>' +
        '<span>' + st + '</span></div>';
    }).join("");
    var anchors = ancRows
      ? '<div class="rv-score-anchors" data-card-anchors><span class="rv-score-bd-title">Anchor efforts</span>' +
        ancHead + ancRows + '</div>'
      : "";
    return '<div class="rv-card rv-stack rv-score-card' + axisMod + '" data-score-card="' + esc(c.axis) + '">' +
      '<div class="rv-row rv-score-card-head"><span class="rv-label">' + esc(c.label) + '</span>' +
      '<a href="/v2/training/trends" class="rv-score-trend-link">Trend</a></div>' +
      '<div class="rv-score-hero-row">' +
      '<strong class="rv-score-num' + scoreCls + '">' + esc(scoreText(c)) + "</strong>" +
      chip + sparkline(c.sparkline, c.axis) + "</div>" + reason + where + callout + anchors + '</div>';
  }

  function applyScoreCards(data) {
    var host = document.getElementById("v2-perf-score-cards");
    if (!host) return;
    if (sectionFailed(data)) {
      renderSectionError(host, "Endurance and Speed", loadScoreCards);
      return;
    }
    host.removeAttribute("aria-busy");
    host.innerHTML = (data.cards || []).map(renderScoreCard).join("");
  }

  function loadScoreCards() {
    var host = document.getElementById("v2-perf-score-cards");
    if (!host) return;
    setRegionLoading(host, "Loading");
    refetchSections("score_cards", function (body) { applyScoreCards(body && body.score_cards); });
  }

  // ── Races and projections: tiles, chain, chart (P4-10) ────────────────────
  // Every value comes from the page projection section. The chart maps the
  // server's seconds and 0..1 date positions onto the SVG; nothing is derived.

  var NA = "not available";

  function projTile(label, tileData, render) {
    var inner = tileData && tileData.available
      ? render(tileData)
      : '<span class="rv-perf-tile-val rv-subtitle">' + NA + "</span>";
    return '<div class="rv-perf-tile" data-tile="' + esc(label.toLowerCase().replace(/\s+/g, "-")) + '">' +
      '<span class="rv-perf-tile-lbl">' + esc(label) + "</span>" + inner + "</div>";
  }

  function renderTiles(t, built) {
    t = t || {};
    built = built || {};
    return '<div class="rv-perf-proj-tiles">' +
      projTile("Last recalibrated", t.last_recalibrated, function (d) {
        var sub = "";
        if (built.race_time_sec != null || built.cp_w != null) {
          sub = '<span class="rv-perf-tile-sub">' +
            (built.race_time_sec != null ? esc(fmtHMS(built.race_time_sec)) : "") +
            (built.cp_w != null ? (built.race_time_sec != null ? " \u00b7 " : "") + "CP " + esc(built.cp_w) + " W" : "") +
            (built.cp_stale ? ' <span class="rv-chip rv-chip--warn">CP stale</span>' : "") +
            "</span>";
        }
        return '<span class="rv-perf-tile-val">' + esc(fmtDayMonth(d.date)) +
          (d.race_name ? " \u00b7 " + esc(d.race_name) : "") + "</span>" + sub;
      }) +
      projTile("Data", t.data_sufficiency, function (d) {
        return '<span class="rv-perf-tile-val rv-perf-tile-val--good">' + esc(d.value) + "</span>";
      }) +
      projTile("Band confidence", t.band_confidence, function (d) {
        return '<span class="rv-perf-tile-val rv-perf-tile-val--good">' + esc(d.value) + "</span>";
      }) +
      projTile("Model correction", t.model_correction, function (d) {
        var sign = d.pct > 0 ? "+" : d.pct < 0 ? "\u2212" : "";
        return '<span class="rv-perf-tile-val rv-mono">' + esc(sign + Math.abs(d.pct)) + "%</span>" +
          '<span class="rv-perf-tile-sub">' + esc(d.reading || "") + " over " + esc(d.n_races) +
          " race" + (d.n_races === 1 ? "" : "s") + "</span>";
      }) + "</div>";
  }

  function paceOrNA(st) {
    return st && st.available
      ? '<span class="rv-mono rv-proj-stage-val">' + esc(fmtPace(st.pace_seconds_per_km)) + "</span>"
      : '<span class="rv-subtitle">' + NA + "</span>";
  }

  function corrLabel(c) {
    if (!c || !c.available) return null;
    if (c.formatted) return c.formatted;
    if (c.factor == null) return null;
    return "\u00d7" + Number(c.factor).toFixed(3);
  }

  function renderChain(chain, race) {
    if (!chain) return "";
    var e = chain.endurance || {}, sp = chain.speed || {}, b = chain.blended || {};
    var fit = chain.fitness || {}, c = chain.correction || {}, f = chain.final || {};
    var arrow = '<span class="rv-proj-chain__arrow" aria-hidden="true">\u2192</span>';
    var scoreLine = function (name, st) {
      return '<div class="rv-proj-score-row"><span class="rv-proj-score-lbl">' + esc(name) +
        (st.score != null || st.score_display != null ? " " + esc(scoreText(st)) : "") +
        '</span><span class="rv-mono rv-proj-score-pace">' +
        (st && st.available ? esc(fmtPace(st.pace_seconds_per_km)) : NA) + "</span></div>";
    };
    var vs = f.vs_goal;
    var finalMod = vs === "slower" ? " rv-proj-final--warn" : (f.available ? " rv-proj-final--good" : "");
    var dateBit = race && race.race_date ? " \u00b7 " + esc(fmtDayMonth(race.race_date)) : "";
    var gapBit = "";
    if (f.available && f.goal && f.goal.time_sec != null && f.est_sec != null) {
      var g = f.goal.time_sec - f.est_sec;
      gapBit = " \u00b7 " + esc(fmtHMS(Math.abs(g))) + (g >= 0 ? " faster than goal" : " slower than goal");
    }
    var finalHtml = f.available
      ? '<div class="rv-proj-final' + finalMod + '" data-chain="final"><span class="rv-proj-final-lbl">' +
        esc(f.race_name || "") + dateBit + "</span>" +
        '<div class="rv-proj-final-val" data-chain-final>' + esc(fmtHMS(f.est_sec)) +
        (f.band_sec != null ? ' <span class="rv-proj-final-band">\u00b1' +
          esc(fmtHMS(f.band_sec)).replace(/^0:/, "") + "</span>" : "") +
        '</div><span class="rv-subtitle" style="font-size:11.5px">' + esc(fmtPace(f.pace_seconds_per_km)) + gapBit + "</span></div>"
      : '<div class="rv-proj-final" data-chain="final"><span class="rv-subtitle">' +
        esc((f && f.reason) || NA) + "</span></div>";
    var blendLabel = b.available ? "Blend \u00b7 " + esc(b.speed_weight_pct) + "% speed" : "Blend";
    var corrTxt = corrLabel(c);
    var corrInner = corrTxt
      ? '<span class="rv-proj-stage-lbl">Model correction</span>' +
        '<span class="rv-mono rv-proj-stage-val">' + esc(corrTxt) + "</span>"
      : '<span class="rv-subtitle">' + NA + "</span>";
    var blendInner = b.available
      ? '<span class="rv-proj-stage-lbl rv-proj-stage-lbl--blend">' + blendLabel + "</span>" + paceOrNA(b)
      : '<span class="rv-subtitle">' + NA + "</span>";
    var fitInner = fit.available
      ? '<span class="rv-proj-stage-lbl">Race-day fitness</span>' +
        '<span class="rv-mono rv-proj-stage-val">' + esc(fit.formatted || corrLabel(fit) || "\u00d71.000") + "</span>" +
        (fit.projected_ctl != null ? '<span class="rv-subtitle" style="font-size:11.5px">projected CTL on ' +
          (race && race.race_date ? esc(fmtDayMonth(race.race_date)) : "") + "</span>" : "")
      : '<span class="rv-subtitle">' + NA + "</span>";
    return '<div class="rv-proj-chain" data-chain-row>' +
      '<div class="rv-proj-stage rv-proj-stage--scores" data-chain="scores">' + scoreLine("Endurance", e) + scoreLine("Speed", sp) + "</div>" +
      arrow + '<div class="rv-proj-stage rv-proj-stage--blend" data-chain="blended">' + blendInner + "</div>" +
      arrow + '<div class="rv-proj-stage rv-proj-stage--fitness" data-chain="fitness">' + fitInner + "</div>" +
      arrow + '<div class="rv-proj-stage rv-proj-stage--corr" data-chain="correction">' + corrInner + "</div>" +
      arrow + finalHtml + "</div>";
  }

  function renderChart(ch) {
    if (!ch || !ch.available) {
      return '<p class="rv-subtitle" data-chart-na>Chart ' + NA + ".</p>";
    }
    var W = 1200, H = 270, PX_L = 56, PX_R = 1140, PY_TOP = 20, PY_AXIS = 210;
    var lo = ch.y_min_sec, hi = ch.y_max_sec;
    var yTicks = ch.y_ticks || [];
    if (yTicks.length) {
      lo = Math.min(lo, yTicks[0].sec);
      hi = Math.max(hi, yTicks[yTicks.length - 1].sec);
    }
    if (hi === lo) { lo -= 150; hi += 150; }
    var X = function (f) { return Math.round((PX_L + f * (PX_R - PX_L)) * 10) / 10; };
    var Y = function (sec) { return Math.round((PY_TOP + (sec - lo) / (hi - lo) * (PY_AXIS - PY_TOP)) * 10) / 10; };
    var parts = [];
    function svgLine(x1, y1, x2, y2, stroke, width, dash, attr) {
      return '<line x1="' + x1 + '" y1="' + y1 + '" x2="' + x2 + '" y2="' + y2 + '" stroke="' + stroke +
        '" stroke-width="' + (width || 1) + '"' + (dash ? ' stroke-dasharray="' + dash + '"' : "") +
        (attr || "") + "/>";
    }
    yTicks.forEach(function (t) {
      var y = Y(t.sec);
      var isGoal = ch.goal_sec != null && Math.abs(t.sec - ch.goal_sec) < 45;
      parts.push(svgLine(PX_L, y, PX_R, y, isGoal ? "#15803d" : "#eef1f7", isGoal ? 1.8 : 1, isGoal ? "7 6" : null));
      parts.push('<text x="' + (PX_L - 8) + '" y="' + (y + 4) + '" text-anchor="end" font-family="JetBrains Mono, monospace" font-size="12" fill="' +
        (isGoal ? "#15803d" : "#56627f") + '">' + esc(t.label) + "</text>");
    });
    if (ch.goal_sec != null && !yTicks.some(function (t) { return Math.abs(t.sec - ch.goal_sec) < 45; })) {
      parts.push(svgLine(PX_L, Y(ch.goal_sec), PX_R, Y(ch.goal_sec), "#15803d", 1.8, "7 6", ' data-chart="goal"'));
    }
    parts.push(svgLine(PX_L, PY_AXIS, PX_R, PY_AXIS, "#dfe5f1"));

    function daysBetween(a, b) {
      var ms = Date.parse(b) - Date.parse(a);
      return isNaN(ms) ? 0 : Math.abs(ms) / 86400000;
    }
    function estAtX(x) {
      var pts = (ch.history || []).map(function (h) { return { x: h.x, sec: h.est_sec }; });
      if (ch.projection && ch.now_x != null) {
        var last = pts.length ? pts[pts.length - 1] : null;
        if (!last || last.x < ch.now_x - 0.001) pts.push({ x: ch.now_x, sec: ch.projection.est_sec });
      }
      if (!pts.length) return null;
      if (x <= pts[0].x) return pts[0].sec;
      for (var i = 1; i < pts.length; i++) {
        if (x <= pts[i].x) {
          var a = pts[i - 1], b = pts[i];
          var t = (b.x - a.x) ? (x - a.x) / (b.x - a.x) : 0;
          return a.sec + t * (b.sec - a.sec);
        }
      }
      return pts[pts.length - 1].sec;
    }

    var nowX = X(ch.now_x), p = ch.projection, band = ch.band;
    if (band && p) {
      parts.push('<polygon data-chart="band" points="' + nowX + "," + Y(p.est_sec) + " " + PX_R + "," +
        Y(band.high_sec) + " " + PX_R + "," + Y(band.low_sec) + '" fill="#dbe7ff"/>');
    }

    var NOW_R = 5.5;
    var yNow = p ? Y(p.est_sec) : null;
    var hist = (ch.history || []).map(function (h) {
      return { x: h.x, est_sec: h.est_sec, date: h.date };
    });
    if (p && ch.now_x != null) {
      var lastH = hist.length ? hist[hist.length - 1] : null;
      if (lastH && Math.abs(lastH.x - ch.now_x) < 0.008) lastH.est_sec = p.est_sec;
      else hist.push({ x: ch.now_x, est_sec: p.est_sec, date: ch.today });
    }
    function isNowX(x) { return ch.now_x != null && Math.abs(x - ch.now_x) < 0.008; }
    var histAttr = ' data-chart="history"';
    if (hist.length >= 2) {
      var solid = [];
      hist.forEach(function (h, i) {
        if (i === 0) {
          solid.push(h);
          return;
        }
        var prev = hist[i - 1];
        var dashed = daysBetween(prev.date, h.date) > 12;
        if (dashed) {
          if (solid.length >= 2) {
            parts.push('<polyline' + histAttr + ' points="' + solid.map(function (pt) { return X(pt.x) + "," + Y(pt.est_sec); }).join(" ") +
              '" fill="none" stroke="#1f3b8a" stroke-width="2.5" stroke-linejoin="round"/>');
            histAttr = "";
          }
          parts.push(svgLine(X(prev.x), Y(prev.est_sec), X(h.x), Y(h.est_sec), "#1f3b8a", 2.5, "6 5", histAttr));
          histAttr = "";
          solid = [h];
        } else {
          solid.push(h);
        }
      });
      if (solid.length >= 2) {
        parts.push('<polyline' + histAttr + ' points="' + solid.map(function (pt) { return X(pt.x) + "," + Y(pt.est_sec); }).join(" ") +
          '" fill="none" stroke="#1f3b8a" stroke-width="2.5" stroke-linejoin="round"/>');
        histAttr = "";
      }
    } else if (p && yNow != null) {
      parts.push(svgLine(PX_L, yNow, nowX, yNow, "#1f3b8a", 2.5, null, histAttr));
    }
    hist.forEach(function (h) {
      if (isNowX(h.x)) return;
      parts.push('<circle cx="' + X(h.x) + '" cy="' + Y(h.est_sec) + '" r="4" fill="#ffffff" stroke="#1f3b8a" stroke-width="2"/>');
    });
    if (p && yNow != null) {
      parts.push(svgLine(nowX + NOW_R, yNow, PX_R, yNow, "#1f3b8a", 2, "5 4", ' data-chart="projection"'));
    }

    var tagItems = [];
    function pushTag(m, fill, ink, label, kind) {
      var name = String(label || m.name || "").trim();
      if (!name) return;
      tagItems.push({
        xFrac: m.x, name: name, fill: fill, ink: ink, kind: kind, role: m.role, tag_lane: m.tag_lane
      });
    }
    (ch.ticks || []).forEach(function (m) { pushTag(m, "#eef2fb", "#33405e", m.name, "tick"); });
    (ch.recalibrations || []).forEach(function (m) { pushTag(m, "#eef2fb", "#33405e", m.name, "recal"); });
    (ch.pending || []).forEach(function (m) { pushTag(m, "#fff1dc", "#7a3a10", m.name ? "CP \u00b7 not recorded" : "", "pending"); });
    tagItems.sort(function (a, b) { return a.xFrac - b.xFrac; });
    var laid = [];
    tagItems.forEach(function (it) {
      var full = String(it.name);
      var label = full.length > 16 ? full.slice(0, 15) + "\u2026" : full;
      var tw = Math.min(Math.max(56, label.length * 7.2 + 16), 128);
      var x = X(it.xFrac);
      var tx = Math.max(PX_L, Math.min(x - tw / 2, PX_R - tw));
      var lane = it.tag_lane || 0;
      function hits(laneN, txN, twN) {
        return laid.some(function (p) {
          return p.lane === laneN && txN < p.tx + p.tw + 8 && txN + twN > p.tx - 8;
        });
      }
      if (hits(lane, tx, tw)) lane = 1 - lane;
      if (hits(lane, tx, tw)) {
        var nudged = Math.min(tx + 12, PX_R - tw);
        if (!hits(lane, nudged, tw)) tx = nudged;
      }
      var yOn = estAtX(it.xFrac);
      laid.push({ x: x, tx: tx, tw: tw, lane: lane, label: label, full: full, fill: it.fill, ink: it.ink, kind: it.kind, role: it.role, yOn: yOn });
    });
    laid.forEach(function (tag) {
      var yOn = tag.yOn != null ? Y(tag.yOn) : PY_AXIS;
      var tagY = PY_AXIS + 10 + tag.lane * 26;
      var attr = tag.kind === "recal" ? " data-chart-recal" : tag.kind === "pending" ? " data-chart-pending" :
        ' data-chart-tick="' + esc(tag.role || "") + '"';
      parts.push(svgLine(tag.x, yOn, tag.x, PY_AXIS, "#c3cbdb", 1, "2 3", attr));
      if (!(p && Math.abs(tag.x - nowX) < 0.8)) {
        parts.push('<circle cx="' + tag.x + '" cy="' + yOn + '" r="4" fill="#ffffff" stroke="#1f3b8a" stroke-width="2"/>');
      }
      parts.push('<rect data-chart-tag x="' + tag.tx + '" y="' + tagY + '" width="' + tag.tw + '" height="22" rx="6" fill="' + tag.fill + '">' +
        "<title>" + esc(tag.full) + "</title></rect>" +
        '<text x="' + (tag.tx + tag.tw / 2) + '" y="' + (tagY + 15) + '" text-anchor="middle" font-size="11.5" font-weight="700" fill="' + tag.ink + '">' +
        '<title>' + esc(tag.full) + "</title>" + esc(tag.label) + "</text>");
    });

    parts.push(svgLine(nowX, PY_TOP, nowX, PY_AXIS, "#0b1530", 1.2) +
      '<text x="' + Math.min(nowX + 6, PX_R - 80) + '" y="30" font-size="12" font-weight="700" fill="#0b1530">Now' +
      (p && p.est_label ? " \u00b7 " + esc(p.est_label) : "") + "</text>");
    if (p && yNow != null) {
      parts.push('<circle data-chart="now" cx="' + nowX + '" cy="' + yNow + '" r="' + NOW_R + '" fill="#1f3b8a"/>');
    }
    if (!ch.history_only) {
      parts.push(svgLine(PX_R, PY_TOP, PX_R, PY_AXIS, "#b45309", 1.2, "3 3") +
        '<text x="' + (PX_R - 4) + '" y="30" text-anchor="end" font-size="12" font-weight="700" fill="#7a3a10">Race day</text>');
    }
    var mono = ' font-size="11.5" text-anchor="end" font-family="JetBrains Mono, monospace"';
    if (band && p) {
      function bandLabelY(sec, fallbackShift) {
        var y = Y(sec) + fallbackShift;
        if (y < 52) y = 52;
        if (y > PY_AXIS - 6) y = PY_AXIS - 6;
        return y;
      }
      parts.push('<text data-band-label="high" x="' + (PX_R - 8) + '" y="' + bandLabelY(band.high_sec, -4) + '" fill="#56627f"' + mono + ">" + esc(band.high_label) + "</text>");
      parts.push('<text data-band-label="low" x="' + (PX_R - 8) + '" y="' + bandLabelY(band.low_sec, 14) + '" fill="#56627f"' + mono + ">" + esc(band.low_label) + "</text>");
      parts.push('<text data-band-label="estimate" x="' + (PX_R - 8) + '" y="' + bandLabelY(p.est_sec, -4) + '" fill="#0b1530" font-weight="700"' + mono + ">" + esc(p.est_label) + "</text>");
    }
    parts.push('<text x="' + PX_L + '" y="262" font-size="11.5" fill="#56627f" font-family="JetBrains Mono, monospace">' + esc(fmtDayMonth(ch.start)) + "</text>" +
      '<text x="' + PX_R + '" y="262" font-size="11.5" fill="#56627f" text-anchor="end" font-family="JetBrains Mono, monospace">' + esc(fmtDayMonth(ch.end)) + "</text>");
    var aria = ch.history_only
      ? ("Finish estimate trend for " + ch.race_name + " from " + fmtDayMonth(ch.start) + " to " + fmtDayMonth(ch.end) + ".")
      : ("Projected " + ch.race_name + " time from " + fmtDayMonth(ch.start) + " to race day " + fmtDayMonth(ch.end) +
        (p && p.est_label ? ", ending at " + p.est_label : "") +
        (band ? " with a band from " + band.low_label + " to " + band.high_label : "") +
        (ch.goal_label ? ". Goal " + ch.goal_label : "") + ".");
    return '<svg viewBox="0 0 ' + W + " " + H + '" style="width:100%;height:auto;display:block" role="img" aria-label="' +
      esc(aria) + '" data-projection-chart>' + parts.join("") + "</svg>";
  }

  function renderBuiltFrom(b) {
    if (!b || !b.available) return "";
    var parts = [];
    if (b.race_name && b.race_time_sec != null) {
      parts.push("Built from " + esc(b.race_name) + " " + esc(fmtHMS(b.race_time_sec)));
    }
    if (b.cp_w != null) {
      parts.push("CP " + esc(b.cp_w) + " W" + (b.cp_stale ? " · stale" : ""));
    }
    return parts.length
      ? '<p class="rv-subtitle" data-projection-built-from>' + parts.join(" · ") + "</p>"
      : "";
  }

  function chartLegend(ch) {
    if (!ch || !ch.available) return "";
    return '<div class="rv-proj-chart-head"><span class="rv-perf-tile-lbl">' +
      esc(ch.race_name || "") + " estimate over time</span>" +
      '<span class="rv-chart-legend"><span><span class="rv-chart-legend-line"></span>Estimate</span>' +
      '<span><span class="rv-chart-legend-band"></span>Band to race day</span>' +
      (ch.goal_label ? '<span><span class="rv-chart-legend-goal"></span>Goal ' + esc(ch.goal_label) + "</span>" : "") +
      "</span></div>";
  }

  function renderProjection(host, data) {
    var chainName = data.race && data.race.name ? data.race.name : "finish";
    host.innerHTML =
      '<div class="rv-perf-proj-head">' +
      '<div><h2 class="rv-perf-proj-title">Races and projections</h2>' +
      '<p class="rv-subtitle" style="margin:4px 0 0;font-size:13px">How the finish time is built and how it has moved. The band tightens after each recalibration.</p></div>' +
      '<div class="rv-row rv-perf-proj-actions">' +
      '<button type="button" class="rv-btn rv-btn--secondary rv-btn--sm" id="v2-proj-recalibrate">Recalibrate</button>' +
      '<button type="button" class="rv-btn rv-btn--secondary rv-btn--sm" id="v2-race-add">+ Add a race</button></div></div>' +
      renderTiles(data.tiles, data.built_from) +
      '<div class="rv-proj-chain-block"><span class="rv-perf-tile-lbl">How the ' + esc(chainName) + " estimate is built</span>" +
      (data.chain ? renderChain(data.chain, data.race) : '<p class="rv-subtitle" data-chain-na>Pace blend is ' + NA + " until an upcoming race is set.</p>") +
      "</div>" +
      ((data.chart && data.chart.available)
        ? '<div class="rv-proj-chart-block">' + chartLegend(data.chart) + renderChart(data.chart) + "</div>"
        : "");
    var recal = host.querySelector("#v2-proj-recalibrate");
    if (recal) {
      recal.addEventListener("click", function () {
        var row = document.querySelector("[data-needs-result]");
        if (row && row.scrollIntoView) row.scrollIntoView({ behavior: "smooth" });
        else toast("Record a race result in Needs a result to recalibrate");
      });
    }
    var addBtn = host.querySelector("#v2-race-add");
    if (addBtn) addBtn.addEventListener("click", function () { openRaceDrawer(null); });
  }

  function applyProjection(data) {
    var host = document.getElementById("v2-perf-projection");
    if (!host) return;
    if (sectionFailed(data)) {
      renderSectionError(host, "Races and projections", loadProjection);
      return;
    }
    host.removeAttribute("aria-busy");
    renderProjection(host, data);
  }

  function loadProjection() {
    var host = document.getElementById("v2-perf-projection");
    if (!host) return;
    setRegionLoading(host, "Loading projection");
    refetchSections("projection", function (body) { applyProjection(body && body.projection); });
  }

  // ── Race list: needs result, upcoming, completed, add/edit (P4-11) ────────
  // Rows come from the page races section. Recording uses the existing
  // POST /api/races/{id}/calibrate flow; edits use PATCH /api/races/{id}.

  var raceIndex = {};
  var raceRoleCatalog = null;
  var raceRoleCatalogPromise = null;
  var raceModalInitial = "";
  var raceModalOpener = null;
  var DISTANCE_PRESETS = [
    { label: "5K", km: 5 },
    { label: "10K", km: 10 },
    { label: "Half", km: 21.0975 },
    { label: "Marathon", km: 42.195 },
  ];
  var ROLE_BLURBS = {
    a_race: "Run for the goal time. The result re-anchors Endurance, Speed and the projection.",
    pb: "All out for a personal best. Also recalibrates.",
    long_run: "Run it as a supported long run.",
    fun: "Just for the day; logged, not scored.",
  };
  var PRIORITY_OPTS = [
    { value: "A", label: "A \u00b7 the goal race" },
    { value: "B", label: "B \u00b7 tune-up" },
    { value: "C", label: "C \u00b7 training" },
  ];
  var FALLBACK_ROLES = [
    { id: "a_race", label: "A race", recalibrates: null },
    { id: "pb", label: "PB attempt", recalibrates: null },
    { id: "long_run", label: "Long run", recalibrates: null },
    { id: "fun", label: "Fun run", recalibrates: null },
  ];

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
    refetchSections("hero,readiness,projection,races,score_cards,radar", function (b) {
      if (!b) {
        applyHero({ error: "failed" });
        applyReadiness({ error: "failed" });
        applyProjection({ error: "failed" });
        applyRaces({ error: "failed" });
        applyScoreCards({ error: "failed" });
        applyRadar({ error: "failed" });
        return;
      }
      applyHero(b.hero);
      applyReadiness(b.readiness);
      applyProjection(b.projection);
      applyRaces(b.races);
      applyScoreCards(b.score_cards);
      applyRadar(b.radar);
    });
  }

  function raceNameCell(r, extra) {
    var target = r.is_target ? '<span class="rv-race-target-chip" data-race-target>TARGET</span>' : "";
    var recal = r.recalibrates_here ? ' · <span class="rv-race-recal" data-recalibrates-here>recalibrates here</span>' : "";
    return '<div class="rv-race-row__name"><div class="rv-race-row__head">' + prBadge(r) +
      '<div><span class="rv-race-row__title">' + esc(r.name) + target + (extra || "") + '</span>' +
      '<span class="rv-mono rv-subtitle rv-race-row__meta">' + esc(fmtDayMonth(r.race_date)) +
      (r.distance_km ? " · " + esc(fmtKm(r.distance_km, r.distance_label)) + " km" : "") +
      (r.role_label ? ' · <span data-race-role="' + esc(r.role || "") + '">' + esc(r.role_label) + "</span>" : "") +
      recal + '</span></div></div></div>';
  }

  function goalCell(r) {
    var pace = r.goal_pace_seconds_per_km ? fmtPace(r.goal_pace_seconds_per_km).replace(" /km", "") : "";
    return '<div class="rv-race-row__goal"><span class="rv-race-col-lbl">Goal</span>' +
      '<span class="rv-mono rv-race-time">' + esc(fmtHMS(r.goal_sec)) + '</span>' +
      (pace ? ' <span class="rv-subtitle rv-mono">' + esc(pace) + '</span>' : "") + '</div>';
  }

  function statusChip(chip) {
    if (!chip || !chip.text) return '<div class="rv-race-row__status"></div>';
    var tone = chip.tone || "warn";
    var title = chip.title || chip.aria_label || chip.text;
    return '<div class="rv-race-row__status"><span class="rv-status-chip rv-status-chip--' + esc(tone) +
      '" data-status-chip title="' + esc(title) + '" aria-label="' + esc(chip.aria_label || title) + '">' +
      esc(chip.text) + "</span></div>";
  }

  function timeToneClass(chip) {
    if (!chip) return "";
    if (chip.tone === "good") return " rv-race-time--good";
    if (chip.tone === "bad") return " rv-race-time--bad rv-race-time--warn";
    if (chip.tone === "warn") return " rv-race-time--warn";
    return "";
  }

  function raceRowIcons(r) {
    return '<button type="button" class="rv-icon-btn" data-edit-race="' + esc(r.id) +
      '" aria-label="Edit ' + esc(r.name) + '">' + ICON_EDIT + "</button>" +
      '<button type="button" class="rv-icon-btn" data-delete-race="' + esc(r.id) +
      '" aria-label="Delete ' + esc(r.name) + '">' + ICON_TRASH + "</button>";
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
      ? '<span class="rv-mono rv-race-time" data-suggested-actual>' + esc(fmtHMS(sug.moving_seconds)) + "</span>" +
        ' <span class="rv-subtitle">suggested \u00b7 ' + esc(sug.date) + " \u00b7 " + esc(sug.distance_km) + " km</span>"
      : '<span class="rv-subtitle" data-no-match>' + esc(r.suggestion_reason || "No synced run matched") + "</span>";
    return '<div class="rv-race-row rv-race-row--needs" data-needs-result="' + esc(r.id) + '">' +
      raceNameCell(r) + goalCell(r) +
      '<div class="rv-race-row__actual"><span class="rv-race-col-lbl">Actual</span>' + actual + "</div>" +
      statusChip(r.status_chip) +
      '<div class="rv-race-row__actions"><div class="rv-race-record">' +
      '<label class="sr-only" for="actual-' + esc(r.id) + '">Finish time</label>' +
      '<input id="actual-' + esc(r.id) + '" type="text" inputmode="numeric" placeholder="h:mm:ss" data-actual-input value="' +
      esc(sug ? fmtHMS(sug.moving_seconds) : "") + '">' +
      '<button type="button" class="rv-btn rv-btn--accent rv-btn--sm" data-record="' + esc(r.id) + '">Record</button></div>' +
      raceRowIcons(r) + "</div></div>";
  }

  function renderUpcoming(r) {
    var est = r.estimate || {};
    var timeCls = "rv-mono rv-race-time" + timeToneClass(r.status_chip);
    var estHtml = est.available
      ? '<span class="' + timeCls + '" data-race-estimate>' + esc(fmtHMS(est.est_sec)) + "</span>" +
        (est.band_sec != null ? ' <span class="rv-subtitle rv-mono">\u00b1' + esc(fmtHMS(est.band_sec)).replace(/^0:/, "") + "</span>" : "")
      : '<span class="rv-subtitle">' + esc(est.reason || "not available") + "</span>";
    var rowCls = "rv-race-row" + (r.is_target || r.priority === "A" ? " rv-race-row--upcoming-a" : "");
    return '<div class="' + rowCls + '" data-upcoming="' + esc(r.id) + '">' +
      raceNameCell(r) + goalCell(r) +
      '<div class="rv-race-row__est"><span class="rv-race-col-lbl">Estimate</span>' + estHtml + "</div>" +
      statusChip(r.status_chip) +
      '<div class="rv-race-row__actions">' + raceRowIcons(r) + "</div></div>";
  }

  function renderCompleted(r) {
    var href = (r.debrief && r.debrief.link) || (r.workout_id ? "/log?workout=" + encodeURIComponent(r.workout_id) : "");
    var action = href
      ? '<a class="rv-score-trend-link" data-debrief-chip href="' + esc(href) + '">Debrief \u203a</a>'
      : "";
    var pace = r.actual_pace_seconds_per_km;
    var timeCls = "rv-mono rv-race-time" + timeToneClass(r.status_chip);
    return '<div class="rv-race-row" data-completed="' + esc(r.id) + '">' +
      raceNameCell(r) + goalCell(r) +
      '<div class="rv-race-row__actual"><span class="rv-race-col-lbl">Actual</span>' +
      '<span class="' + timeCls + '" data-chip-time>' + esc(fmtHMS(r.chip_time_sec)) + "</span>" +
      (pace != null ? ' <span class="rv-mono rv-subtitle" data-moving-time data-actual-pace>' +
        esc(fmtPace(pace).replace(" /km", "")) + "</span>" : "") +
      "</div>" + statusChip(r.status_chip) +
      '<div class="rv-race-row__actions">' + action + raceRowIcons(r) + "</div></div>";
  }

  function calibratesOnDelete(r) {
    if (!r) return false;
    var role = r.role;
    var hasResult = r.chip_time_sec != null || (r.actual && r.actual.time_sec != null);
    return hasResult && (role === "a_race" || role === "pb");
  }

  function closeDeleteConfirm() {
    var root = document.getElementById("v2-race-delete-root");
    if (root) root.innerHTML = "";
  }

  function openDeleteRaceConfirm(r) {
    if (!r) return;
    var root = document.getElementById("v2-race-delete-root");
    if (!root) {
      root = document.createElement("div");
      root.id = "v2-race-delete-root";
      document.body.appendChild(root);
    }
    var extra = calibratesOnDelete(r)
      ? "<p>The projection will recalibrate without this race.</p>"
      : "";
    root.innerHTML =
      '<div class="rv-confirm-backdrop" id="v2-race-delete-backdrop">' +
      '<div class="rv-confirm" role="dialog" aria-modal="true" aria-labelledby="v2-race-delete-title">' +
      '<h2 id="v2-race-delete-title">Delete ' + esc(r.name) + "?</h2>" +
      "<p>Its result and calibration will be removed.</p>" + extra +
      '<div class="rv-confirm__actions">' +
      '<button type="button" class="rv-btn rv-btn--secondary rv-btn--sm" data-delete-cancel>Cancel</button>' +
      '<button type="button" class="rv-btn rv-btn--danger rv-btn--sm" data-delete-confirm>Delete</button>' +
      "</div></div></div>";
    function onKey(ev) {
      if (ev.key === "Escape") { ev.preventDefault(); closeDeleteConfirm(); }
    }
    document.addEventListener("keydown", onKey, { once: true });
    root.querySelector("[data-delete-cancel]").addEventListener("click", closeDeleteConfirm);
    root.querySelector("#v2-race-delete-backdrop").addEventListener("click", function (ev) {
      if (ev.target.id === "v2-race-delete-backdrop") closeDeleteConfirm();
    });
    root.querySelector("[data-delete-confirm]").addEventListener("click", function () {
      var btn = this;
      btn.disabled = true;
      sendJSON("DELETE", "/api/races/" + encodeURIComponent(r.id))
        .then(function () {
          closeDeleteConfirm();
          toast("Race deleted");
          reloadProjectionViews();
        })
        .catch(function (e) {
          var gone = e && (e.status === 404 || /not found/i.test(String(e.message || "")));
          if (gone) {
            closeDeleteConfirm();
            toast("Race deleted");
            reloadProjectionViews();
            return;
          }
          btn.disabled = false;
          toast("Could not delete: " + e.message);
        });
    });
  }

  function renderRaces(host, data) {
    var needs = data.needs_result || [], up = data.upcoming || [], done = data.completed || [];
    raceIndex = {};
    needs.concat(up, done).forEach(function (r) { raceIndex[r.id] = r; });
    var more = "";
    if (data.total_upcoming > up.length && !data.showing_all) {
      more = '<button type="button" class="rv-btn rv-btn--secondary rv-btn--sm" data-show-all-races>Show all ' +
        esc(data.total_upcoming) + " upcoming</button>";
    }
    var earlier = "";
    if (data.hidden_completed > 0 && !data.showing_all) {
      earlier = '<button type="button" class="rv-btn rv-show-earlier" data-show-earlier-completed>Show ' +
        esc(data.hidden_completed) + " earlier race" + (data.hidden_completed === 1 ? "" : "s") + "</button>";
    }
    host.innerHTML =
      (needs.length ? '<span class="rv-race-sec">Needs a result</span>' + needs.map(renderNeedsResult).join("") : "") +
      '<div class="rv-row rv-race-sec-row"><span class="rv-race-sec">Upcoming</span>' +
      '<a href="/v2/performance/season-road" data-season-road-link style="font-size:13px;font-weight:700">Season road \u203a</a></div>' +
      (up.length ? '<div class="rv-stack" style="gap:8px" data-section="upcoming">' + up.map(renderUpcoming).join("") + more + "</div>" :
        '<p class="rv-subtitle">No upcoming races.</p>') +
      (done.length ? '<span class="rv-race-sec">Completed</span><div class="rv-stack" style="gap:8px" data-section="completed">' +
        done.map(renderCompleted).join("") + earlier + "</div>" : "");
    Array.prototype.forEach.call(host.querySelectorAll("[data-edit-race]"), function (b) {
      b.addEventListener("click", function () { openRaceDrawer(raceIndex[b.getAttribute("data-edit-race")]); });
    });
    Array.prototype.forEach.call(host.querySelectorAll("[data-delete-race]"), function (b) {
      b.addEventListener("click", function () {
        openDeleteRaceConfirm(raceIndex[b.getAttribute("data-delete-race")]);
      });
    });
    Array.prototype.forEach.call(host.querySelectorAll("[data-record]"), function (b) {
      b.addEventListener("click", function () {
        var row = b.closest("[data-needs-result]");
        recordResult(b.getAttribute("data-record"), row.querySelector("[data-actual-input]").value, b);
      });
    });
    function loadAllRaces(b) {
      b.disabled = true;
      fetch("/api/performance/races?all=1", { credentials: "same-origin" })
        .then(function (r) {
          if (!r.ok) throw new Error("HTTP " + r.status);
          return r.json();
        })
        .then(applyRaces)
        .catch(function (e) { toast("Could not load all races: " + e.message); b.disabled = false; });
    }
    Array.prototype.forEach.call(host.querySelectorAll("[data-show-all-races]"), function (b) {
      b.addEventListener("click", function () { loadAllRaces(b); });
    });
    Array.prototype.forEach.call(host.querySelectorAll("[data-show-earlier-completed]"), function (b) {
      b.addEventListener("click", function () { loadAllRaces(b); });
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

  function loadRaceRoles() {
    if (raceRoleCatalog) return Promise.resolve(raceRoleCatalog);
    if (raceRoleCatalogPromise) return raceRoleCatalogPromise;
    raceRoleCatalogPromise = fetch("/api/races/roles", { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        raceRoleCatalog = (data && data.roles) || FALLBACK_ROLES;
        return raceRoleCatalog;
      })
      .catch(function () {
        raceRoleCatalogPromise = null;
        raceRoleCatalog = FALLBACK_ROLES;
        return raceRoleCatalog;
      });
    return raceRoleCatalogPromise;
  }

  function roleById(id) {
    var list = raceRoleCatalog || FALLBACK_ROLES;
    var i;
    for (i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }

  function snapshotRaceForm(f) {
    return JSON.stringify({
      name: f.elements.name.value,
      race_date: f.elements.race_date.value,
      distance_km: f.elements.distance_km.value,
      goal: f.elements.goal.value,
      priority: f.elements.priority.value,
      role: f.elements.role.value,
    });
  }

  function raceModalFocusables(panel) {
    return Array.prototype.slice.call(panel.querySelectorAll(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )).filter(function (el) { return el.offsetParent !== null || el === document.activeElement; });
  }

  function closeRaceModal() {
    var root = document.getElementById("v2-race-modal-root");
    if (root) root.innerHTML = "";
    document.removeEventListener("keydown", onRaceModalKey, true);
    document.body.style.overflow = "";
    raceModalInitial = "";
    var opener = raceModalOpener;
    raceModalOpener = null;
    if (opener && opener.focus) opener.focus();
  }

  function raceModalDirty() {
    var f = document.getElementById("v2-race-form");
    return !!(f && raceModalInitial && snapshotRaceForm(f) !== raceModalInitial);
  }

  function requestCloseRaceModal() {
    if (raceModalDirty() && !window.confirm("Discard unsaved race details?")) return;
    closeRaceModal();
  }

  function onRaceModalKey(ev) {
    var panel = document.getElementById("v2-race-modal");
    if (!panel) return;
    if (ev.key === "Escape") {
      ev.preventDefault();
      requestCloseRaceModal();
      return;
    }
    if (ev.key !== "Tab") return;
    var nodes = raceModalFocusables(panel);
    if (!nodes.length) return;
    var first = nodes[0], last = nodes[nodes.length - 1];
    if (ev.shiftKey && document.activeElement === first) {
      ev.preventDefault();
      last.focus();
    } else if (!ev.shiftKey && document.activeElement === last) {
      ev.preventDefault();
      first.focus();
    }
  }

  function selectRadio(group, btn) {
    if (!group || !btn) return;
    Array.prototype.forEach.call(group.querySelectorAll('[role="radio"]'), function (b) {
      var on = b === btn;
      b.classList.toggle("is-on", on);
      b.setAttribute("aria-checked", on ? "true" : "false");
      b.tabIndex = on ? 0 : -1;
    });
    var form = document.getElementById("v2-race-form");
    var name = group.getAttribute("data-field");
    if (form && name && form.elements[name]) form.elements[name].value = btn.getAttribute("data-value");
    updateRaceModalMeta();
  }

  function bindRadioGroup(group) {
    group.addEventListener("click", function (ev) {
      var btn = ev.target.closest('[role="radio"]');
      if (btn && group.contains(btn)) selectRadio(group, btn);
    });
    group.addEventListener("keydown", function (ev) {
      var dir = ev.key === "ArrowRight" || ev.key === "ArrowDown" ? 1
        : ev.key === "ArrowLeft" || ev.key === "ArrowUp" ? -1 : 0;
      if (!dir) return;
      ev.preventDefault();
      var btns = Array.prototype.slice.call(group.querySelectorAll('[role="radio"]'));
      var i = btns.findIndex(function (b) { return b.getAttribute("aria-checked") === "true"; });
      if (i < 0) i = 0;
      var next = btns[(i + dir + btns.length) % btns.length];
      selectRadio(group, next);
      next.focus();
    });
  }

  function distMatches(a, b) {
    return Math.abs(Number(a) - Number(b)) < 0.00005;
  }

  function updateRaceModalMeta() {
    var form = document.getElementById("v2-race-form");
    if (!form) return;
    var distEl = form.elements.distance_km;
    var goalEl = form.elements.goal;
    var paceEl = document.getElementById("v2-race-pace");
    var goalErr = document.getElementById("v2-race-goal-error");
    var summary = document.getElementById("v2-race-summary");
    var dist = parseFloat(distEl.value);
    Array.prototype.forEach.call(form.querySelectorAll("[data-dist-chip]"), function (chip) {
      chip.classList.toggle("is-on", distMatches(chip.getAttribute("data-dist-chip"), dist));
    });
    var goalText = String(goalEl.value || "").trim();
    var goal = parseHMS(goalEl.value);
    if (goalErr) {
      if (goalText && isNaN(goal)) {
        goalErr.textContent = "Goal time must look like 1:50:00";
        goalErr.hidden = false;
      } else {
        goalErr.textContent = "";
        goalErr.hidden = true;
      }
    }
    if (paceEl) {
      if (goal != null && !isNaN(goal) && dist > 0) {
        paceEl.innerHTML = "= <b>" + esc(fmtPace(goal / dist)) + "</b>";
        paceEl.hidden = false;
      } else {
        paceEl.hidden = true;
        paceEl.textContent = "";
      }
    }
    if (summary) {
      var pri = form.elements.priority.value || "B";
      var role = roleById(form.elements.role.value) || {};
      var bits = [pri + " race", role.label || form.elements.role.value];
      if (role.recalibrates === true) bits.push("recalibrates the projection");
      else if (role.recalibrates === false) bits.push("does not recalibrate");
      summary.textContent = bits.join(" \u00b7 ");
    }
  }

  function renderRaceModal(race, opts, roles) {
    var root = document.getElementById("v2-race-modal-root");
    if (!root) return;
    var editing = !!race;
    var asARace = !!(opts && opts.asARace);
    var priority = editing ? (race.priority || "B") : (asARace ? "A" : "B");
    var role = editing ? (race.role || "pb") : (asARace ? "a_race" : "pb");
    var title = editing ? "Edit race" : "Add a race";
    var distVal = editing && race.distance_km ? String(race.distance_km) : "";
    var goalVal = editing && race.goal_sec ? fmtHMS(race.goal_sec) : "";
    var chips = DISTANCE_PRESETS.map(function (p) {
      return '<button type="button" class="rv-race-modal__chip" data-dist-chip="' + p.km + '">' + esc(p.label) + "</button>";
    }).join("");
    var priBtns = PRIORITY_OPTS.map(function (o) {
      var on = o.value === priority;
      return '<button type="button" role="radio" aria-checked="' + (on ? "true" : "false") + '"' +
        (on ? ' class="is-on"' : "") + ' tabindex="' + (on ? "0" : "-1") + '" data-value="' + o.value + '">' +
        esc(o.label) + "</button>";
    }).join("");
    var roleBtns = (roles || FALLBACK_ROLES).map(function (r) {
      var on = r.id === role;
      var tag = r.recalibrates == null ? ""
        : '<span class="rv-race-role__tag rv-race-role__tag--' + (r.recalibrates ? "on" : "off") + '">' +
          (r.recalibrates ? "RECALIBRATES" : "NO RECALIBRATE") + "</span>";
      return '<button type="button" role="radio" class="rv-race-role' + (on ? " is-on" : "") +
        '" aria-checked="' + (on ? "true" : "false") + '" tabindex="' + (on ? "0" : "-1") +
        '" data-value="' + esc(r.id) + '"><span class="rv-race-role__top">' + esc(r.label) + tag +
        '</span><span class="rv-race-role__blurb">' + esc(ROLE_BLURBS[r.id] || "") + "</span></button>";
    }).join("");
    root.innerHTML =
      '<div class="rv-race-modal-backdrop" id="v2-race-modal-backdrop">' +
      '<div class="rv-race-modal" id="v2-race-modal" role="dialog" aria-modal="true" aria-labelledby="v2-race-modal-title">' +
      '<form id="v2-race-form" novalidate>' +
      '<div class="rv-race-modal__head">' +
      '<div><span class="rv-race-modal__kicker">Races</span>' +
      '<h2 class="rv-race-modal__title" id="v2-race-modal-title">' + esc(title) + "</h2></div>" +
      '<button type="button" class="rv-race-modal__close" data-close aria-label="Close">\u00d7</button></div>' +
      '<div class="rv-race-modal__body">' +
      '<div class="rv-race-modal__field"><label class="rv-race-modal__label" for="v2-race-name">Race name</label>' +
      '<input class="rv-race-modal__input" id="v2-race-name" type="text" name="name" required value="' +
      esc(editing ? race.name : "") + '"></div>' +
      '<div class="rv-race-modal__pair">' +
      '<div class="rv-race-modal__field"><label class="rv-race-modal__label" for="v2-race-date">Date</label>' +
      '<input class="rv-race-modal__input rv-race-modal__input--mono" id="v2-race-date" type="date" name="race_date" required value="' +
      esc(editing ? race.race_date : "") + '"></div>' +
      '<div class="rv-race-modal__field"><label class="rv-race-modal__label" for="v2-race-dist">Distance <span class="rv-race-modal__hint">km</span></label>' +
      '<input class="rv-race-modal__input rv-race-modal__input--mono" id="v2-race-dist" type="number" name="distance_km" min="0.1" step="0.0001" required value="' +
      esc(distVal) + '"></div></div>' +
      '<div class="rv-race-modal__chips">' + chips + "</div>" +
      '<div class="rv-race-modal__field"><label class="rv-race-modal__label" for="v2-race-goal">Goal time <span class="rv-race-modal__hint">optional \u00b7 h:mm:ss</span></label>' +
      '<div class="rv-race-modal__goal-row">' +
      '<input class="rv-race-modal__input rv-race-modal__input--mono" id="v2-race-goal" type="text" name="goal" inputmode="numeric" placeholder="1:50:00" value="' +
      esc(goalVal) + '">' +
      '<span class="rv-race-modal__pace" id="v2-race-pace" hidden></span></div>' +
      '<p class="rv-race-modal__field-error" id="v2-race-goal-error" hidden></p></div>' +
      '<div class="rv-race-modal__field"><span class="rv-race-modal__label" id="v2-race-pri-lbl">Priority</span>' +
      '<input type="hidden" name="priority" value="' + esc(priority) + '">' +
      '<div class="rv-race-modal__seg" role="radiogroup" aria-labelledby="v2-race-pri-lbl" data-field="priority">' +
      priBtns + "</div></div>" +
      '<div class="rv-race-modal__field"><span class="rv-race-modal__label" id="v2-race-role-lbl">How it is run</span>' +
      '<input type="hidden" name="role" value="' + esc(role) + '">' +
      '<div class="rv-race-modal__roles" role="radiogroup" aria-labelledby="v2-race-role-lbl" data-field="role">' +
      roleBtns + "</div></div></div>" +
      '<p class="rv-warn-inline rv-race-modal__alert" id="v2-race-error" role="alert" hidden></p>' +
      '<div class="rv-race-modal__foot"><span class="rv-race-modal__summary" id="v2-race-summary"></span>' +
      '<div class="rv-race-modal__actions">' +
      '<button type="button" class="rv-btn rv-btn--secondary" data-close>Cancel</button>' +
      '<button type="submit" class="rv-btn rv-btn--primary">' + (editing ? "Save race" : "Add race") +
      "</button></div></div></form></div></div>";

    var form = document.getElementById("v2-race-form");
    var backdrop = document.getElementById("v2-race-modal-backdrop");
    document.body.style.overflow = "hidden";
    document.addEventListener("keydown", onRaceModalKey, true);
    Array.prototype.forEach.call(root.querySelectorAll("[data-close]"), function (b) {
      b.addEventListener("click", requestCloseRaceModal);
    });
    backdrop.addEventListener("click", function (ev) {
      if (ev.target === backdrop) requestCloseRaceModal();
    });
    bindRadioGroup(form.querySelector('[data-field="priority"]'));
    bindRadioGroup(form.querySelector('[data-field="role"]'));
    Array.prototype.forEach.call(form.querySelectorAll("[data-dist-chip]"), function (chip) {
      chip.addEventListener("click", function () {
        form.elements.distance_km.value = chip.getAttribute("data-dist-chip");
        updateRaceModalMeta();
        form.elements.distance_km.focus();
      });
    });
    form.elements.distance_km.addEventListener("input", updateRaceModalMeta);
    form.elements.goal.addEventListener("input", updateRaceModalMeta);
    raceModalInitial = snapshotRaceForm(form);
    updateRaceModalMeta();
    var nameEl = form.elements.name;
    if (nameEl) nameEl.focus();

    form.addEventListener("submit", function (ev) {
      ev.preventDefault();
      var f = ev.target, err = document.getElementById("v2-race-error");
      var goal = parseHMS(f.elements.goal.value);
      if (isNaN(goal)) {
        updateRaceModalMeta();
        f.elements.goal.focus();
        return;
      }
      var dist = parseFloat(f.elements.distance_km.value);
      if (!f.elements.name.value.trim() || !f.elements.race_date.value || !(dist > 0)) {
        err.textContent = "Name, date and a distance above zero are required";
        err.hidden = false;
        return;
      }
      err.hidden = true;
      var payload = {
        name: f.elements.name.value.trim(),
        distance_km: dist,
        goal_time_seconds: goal,
        priority: f.elements.priority.value,
        role: f.elements.role.value,
      };
      var req;
      if (editing) {
        payload.race_date = f.elements.race_date.value;
        req = sendJSON("PATCH", "/api/races/" + encodeURIComponent(race.id), payload);
      } else {
        payload.date = f.elements.race_date.value;
        req = sendJSON("POST", "/api/races", payload);
      }
      var submitBtn = f.querySelector('[type="submit"]');
      if (submitBtn) submitBtn.disabled = true;
      req.then(function () {
        closeRaceModal();
        toast(editing ? "Race saved" : "Race added");
        reloadProjectionViews();
      }).catch(function (e) {
        if (submitBtn) submitBtn.disabled = false;
        err.textContent = e.message;
        err.hidden = false;
      });
    });
  }

  function openRaceDrawer(race, opts) {
    raceModalOpener = document.activeElement;
    loadRaceRoles().then(function (roles) {
      renderRaceModal(race, opts || {}, roles);
    });
  }

  function applyRaces(data) {
    var host = document.getElementById("v2-perf-races");
    if (!host) return;
    if (sectionFailed(data)) {
      renderSectionError(host, "Races", loadRaces);
      return;
    }
    host.removeAttribute("aria-busy");
    renderRaces(host, data);
  }

  function loadRaces() {
    var host = document.getElementById("v2-perf-races");
    if (!host) return;
    setRegionLoading(host, "Loading races");
    refetchSections("races", function (body) { applyRaces(body && body.races); });
  }

  document.addEventListener("perf:edit-race", function (ev) {
    var r = ev.detail && raceIndex[ev.detail.raceId];
    if (r) openRaceDrawer(r);
  });

  // ── Coach block: check-in, review due, history (P4-12) ────────────────────
  // Everything comes from the page coach section; outcomes save through
  // the existing PATCH /api/decisions/{id}. No model call.

  function copyCheckin(btn) {
    if (window.NavCopy && typeof window.NavCopy.copyForClaude === "function") {
      window.NavCopy.copyForClaude(btn, window.NavCopy.CONSULT_ENDPOINT, "consult copied");
      return;
    }
    if (window.CopyForClaude && typeof window.CopyForClaude.copy === "function") {
      window.CopyForClaude.copy(btn, { toast: toast });
      return;
    }
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

  var STATUS_OPEN = "open";
  var STATUS_KEPT = "kept";

  function statusChipClass(status) {
    if (status === STATUS_OPEN || status === "open") return "rv-chip--due";
    if (status === "kept" || status === STATUS_KEPT) return "rv-chip--good";
    return "rv-chip--muted";
  }

  function renderCoach(host, data) {
    var ck = data.checkin || {};
    var state = ck.state === "done" ? "Check-in done this week" : "Check-in due this week";
    var review = data.review_due;
    var reviewCard = "";
    if (review) {
      var dueChip = '<span class="rv-chip rv-chip--due">DUE ' + esc((review.review_on || "").slice(5)) + "</span>";
      reviewCard =
        '<div class="rv-card rv-stack" style="background:#fff;border-radius:12px;padding:14px">' +
        '<div class="rv-row"><span style="font-size:14px;font-weight:700">Review due \u00b7 decided ' + esc(review.decided_on) + "</span>" + dueChip + "</div>" +
        ((review.review_lines || []).map(function (l) { return "<p class=\"rv-subtitle\">" + esc(l) + "</p>"; }).join("") || "") +
        '<label class="rv-label">Outcome<textarea data-outcome-text rows="3" maxlength="1000" style="width:100%" placeholder="What actually happened"></textarea></label>' +
        '<div class="rv-row"><button type="button" class="rv-btn rv-btn--accent" data-save-outcome>Save outcome</button>' +
        '<button type="button" class="rv-btn rv-btn--secondary" data-not-applied>Didn\u2019t apply it</button></div></div>';
    }
    var hist = (data.history || []).map(function (h) {
      return '<div class="rv-coach-hist-row" data-history="' + esc(h.id) + '">' +
        '<span class="rv-mono rv-subtitle">' + esc(h.decided_on) + "</span>" +
        '<div><strong style="font-size:14px">' + esc(h.summary || "\u2014") + "</strong>" +
        (h.outcome_note ? '<span class="rv-subtitle" style="display:block;font-size:12.5px">' + esc(h.outcome_note) + "</span>" : "") + "</div>" +
        '<span class="rv-chip ' + statusChipClass(h.status) + '">' + esc(h.status_label) + "</span></div>";
    }).join("");
    host.innerHTML =
      '<div class="rv-perf-coach-grid">' +
      '<div class="rv-card rv-card--soft rv-stack">' +
      '<span class="rv-label">Check-in with Claude</span> ' +
      '<span class="rv-chip" data-checkin-state="' + esc(ck.state || "due") + '">' + esc(state) + '</span>' +
      '<p class="rv-subtitle">Copy your last 90 days out, talk it through, paste the change list back here.</p>' +
      '<button type="button" class="rv-btn rv-btn--primary" id="v2-copy-checkin">Copy check-in</button>' +
      reviewCard + "</div>" +
      '<div class="rv-card rv-stack">' +
      '<div class="rv-row"><span class="rv-label">Decision history</span>' +
      '<a href="' + esc(data.paste_link || "/coach#paste") + '" data-paste-link>Paste a change list</a></div>' +
      (hist || '<p class="rv-subtitle">No decisions yet.</p>') + "</div></div>";
    host.querySelector("#v2-copy-checkin").addEventListener("click", function (ev) { copyCheckin(ev.currentTarget); });
    var due = data.review_due;
    if (!due) return;
    var saveBtn = host.querySelector("[data-save-outcome]");
    var skipBtn = host.querySelector("[data-not-applied]");
    if (!saveBtn || !skipBtn) return;
    saveBtn.addEventListener("click", function () {
      var noteEl = host.querySelector("[data-outcome-text]");
      var note = noteEl ? noteEl.value.trim() : "";
      if (!note) { toast("Write what happened first"); return; }
      sendJSON("PATCH", "/api/decisions/" + encodeURIComponent(due.id), { outcome_note: note })
        .then(function () { toast("Outcome saved"); loadCoach(); })
        .catch(function (e) { toast("Could not save: " + e.message); });
    });
    skipBtn.addEventListener("click", function () {
      sendJSON("PATCH", "/api/decisions/" + encodeURIComponent(due.id), { applied: false })
        .then(function () { toast("Marked as not applied"); loadCoach(); })
        .catch(function (e) { toast("Could not update: " + e.message); });
    });
  }

  function applyCoach(data) {
    var host = document.getElementById("v2-perf-coach");
    if (!host) return;
    if (sectionFailed(data)) {
      renderSectionError(host, "Coach", loadCoach);
      return;
    }
    host.removeAttribute("aria-busy");
    try { renderCoach(host, data); } catch (e) {
      renderSectionError(host, "Coach", loadCoach);
    }
  }

  function loadCoach() {
    var host = document.getElementById("v2-perf-coach");
    if (!host) return;
    setRegionLoading(host, "Loading coach");
    refetchSections("coach", function (body) { applyCoach(body && body.coach); });
  }

  var lazyStarted = false;

  function applyLazy(body) {
    if (!body) {
      applyReadiness({ error: "failed" });
      applyProjection({ error: "failed" });
      applyRaces({ error: "failed" });
      applyCoach({ error: "failed" });
      applyMobility({ error: "failed" });
      applyAnchors({ error: "failed" });
      return;
    }
    applyReadiness(body.readiness);
    applyProjection(body.projection);
    applyRaces(body.races);
    applyCoach(body.coach);
    applyMobility(body.mobility);
    applyAnchors(body.anchors);
  }

  function startLazy() {
    if (lazyStarted) return;
    lazyStarted = true;
    ["v2-perf-readiness", "v2-perf-projection", "v2-perf-races", "v2-perf-coach",
      "v2-perf-mobility", "v2-perf-strength-anchors"].forEach(function (id) {
      var h = document.getElementById(id);
      if (h) setRegionLoading(h, "Loading");
    });
    fetchPage(LAZY_SECTIONS).then(function (body) {
      if (body && body._notModified) return;
      applyLazy(body);
    }).catch(function () { applyLazy(null); });
  }

  function observeLazy() {
    var targets = LAZY_HOST_IDS.map(function (id) { return document.getElementById(id); }).filter(Boolean);
    if (!targets.length) return;
    if (!("IntersectionObserver" in window)) {
      window.addEventListener("scroll", startLazy, { passive: true, once: true });
      return;
    }
    var io = new IntersectionObserver(function (entries) {
      for (var i = 0; i < entries.length; i++) {
        if (entries[i].isIntersecting) {
          io.disconnect();
          startLazy();
          return;
        }
      }
    }, { rootMargin: "300px 0px" });
    targets.forEach(function (t) { io.observe(t); });
  }

  document.addEventListener("DOMContentLoaded", function () {
    loadRaceRoles();
    if (/(?:^|[?&])add=a-race(?:&|$)/.test(location.search)) {
      openRaceDrawer(null, { asARace: true });
      if (window.history && history.replaceState) {
        history.replaceState({}, "", location.pathname + location.hash);
      }
    }
    initPerfHeader();
    setRegionLoading(document.getElementById("v2-perf-hero"), "Loading A race");
    setRegionLoading(document.getElementById("v2-perf-after-race"), "Loading");
    setRegionLoading(document.getElementById("v2-perf-score-cards"), "Loading");
    var radarHost = document.getElementById("v2-perf-radar-chart");
    if (radarHost) radarHost.setAttribute("aria-busy", "true");
    fetchPage(FIRST_SECTIONS).then(function (body) {
      if (body && body._notModified) return;
      applyHero(body && body.hero);
      applyRadar(body && body.radar);
      applyScoreCards(body && body.score_cards);
    }).catch(function () {
      applyHero({ error: "failed" });
      applyRadar({ error: "failed" });
      applyScoreCards({ error: "failed" });
    });
    observeLazy();
  });
})();
