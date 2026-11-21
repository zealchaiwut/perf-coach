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

  document.addEventListener("DOMContentLoaded", function () {
    loadFocus();
    loadMobility();
    loadAnchors();
  });
})();
