/*
 * coach.js — the /coach page: check-in → paste-back → history, in one place.
 *
 * Three pieces that used to live in two disconnected surfaces:
 *  1. "Start a check-in" — calls the exact same /api/coach/consult flow the
 *     nav dropdown's "Copy for consult" item already implements. Rather than
 *     re-fetch/re-clipboard/re-toast a second time, this reuses nav.js's own
 *     _copyForClaude, exposed as window.NavCopy (see nav.js's "Copy for
 *     Claude" section) — one fetch/clipboard/toast/retry path for both entry
 *     points, so they cannot drift the way 17 divergent esc() copies once did
 *     (issue #1603).
 *  2. The paste-back box — relocated verbatim from decisions.js. There is no
 *     parser and there should not be one: the CHANGES TO APPLY block is
 *     stored exactly as the consult wrote it, and the value is in having the
 *     history at all.
 *  3. The decisions history/log — same list, same outcome/applied actions,
 *     just living on this page now that /decisions is a redirect shim to
 *     /coach.
 */
(function () {
  "use strict";

  // ── 1. Start a check-in ──────────────────────────────────────────────────
  // Same endpoint, same "Building…" persisted toast, same success/error
  // behavior as the nav dropdown's "Copy for consult" item — see nav.js.
  var checkinBtn = document.getElementById("coach-checkin-btn");
  if (checkinBtn) {
    if (window.NavCopy && typeof window.NavCopy.copyForClaude === "function") {
      checkinBtn.addEventListener("click", function () {
        window.NavCopy.copyForClaude(
          checkinBtn,
          window.NavCopy.CONSULT_ENDPOINT,
          "consult copied"
        );
      });
    } else {
      // nav.js failed to load/expose the shared helper — fail loud rather
      // than silently doing nothing when clicked.
      checkinBtn.disabled = true;
      checkinBtn.title = "Check-in unavailable — reload the page.";
    }
  }

  // ── 2 & 3. Paste-back box + history log (relocated from decisions.js) ──────
  // One textarea in, a dated list out. There is no parser and there should
  // not be one: the block is stored exactly as the consult wrote it, and the
  // value is in having the history at all. Recording an outcome is the half
  // that closes the loop, so it is one tap from the list rather than a
  // separate screen.

  var listEl = document.getElementById("dc-list");
  var rawEl = document.getElementById("dc-raw");
  var decidedEl = document.getElementById("dc-decided-on");
  var reviewEl = document.getElementById("dc-review-on");
  var tagsEl = document.getElementById("dc-tags");
  var raceEl = document.getElementById("dc-race");
  var saveBtn = document.getElementById("dc-save");
  var feedbackEl = document.getElementById("dc-feedback");

  // Delegates to the shared escaper (issue #1603). The local copies
  // disagreed about the apostrophe, so identical content was safe on
  // some pages and attribute-injectable on others.
  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  function setFeedback(msg, kind) {
    if (!feedbackEl) return;
    feedbackEl.textContent = msg || "";
    feedbackEl.className = "dc-feedback" + (kind ? " " + kind : "");
  }

  function agoLabel(decidedOn) {
    var then = new Date(decidedOn + "T00:00:00");
    var days = Math.round((Date.now() - then.getTime()) / 86400000);
    if (days <= 0) return "today";
    if (days === 1) return "yesterday";
    if (days < 14) return days + " days ago";
    if (days < 60) return Math.round(days / 7) + " weeks ago";
    return Math.round(days / 30) + " months ago";
  }

  function isDue(d) {
    return d.review_on && !d.outcome_note && d.review_on <= window.AppCommon.todayISO();
  }

  function entryHtml(d) {
    var chips = "";
    if (isDue(d)) chips += '<span class="dc-chip due">due for review</span>';
    if (!d.applied) chips += '<span class="dc-chip notapplied">not applied</span>';
    (d.tags || []).forEach(function (t) {
      chips += '<span class="dc-chip">' + esc(t) + "</span>";
    });

    var outcome = d.outcome_note
      ? '<div class="dc-outcome"><strong>Outcome:</strong> ' + esc(d.outcome_note) + "</div>"
      : "";
    var review = d.review_on && !d.outcome_note
      ? '<div class="dc-outcome">Review on ' + esc(d.review_on) + "</div>"
      : "";

    var lessons = (d.lessons || []).length
      ? '<ul class="dc-lessons" data-lessons>' + d.lessons.map(function (l) { return "<li>" + esc(l) + "</li>"; }).join("") + "</ul>"
      : "";
    if (d.race_id) chips += '<span class="dc-chip" data-race-linked>race debrief</span>';

    return (
      '<article class="dc-entry" id="decision-' + esc(d.id) + '" data-id="' + esc(d.id) + '">' +
      '<div class="dc-entry-head">' +
      '<span class="dc-date">' + esc(d.decided_on) + "</span>" +
      '<span class="dc-ago">' + esc(agoLabel(d.decided_on)) + "</span>" +
      chips +
      "</div>" +
      '<pre class="dc-raw">' + esc(d.raw_text) + "</pre>" +
      lessons +
      review +
      outcome +
      '<div class="dc-entry-actions">' +
      '<button type="button" class="dc-btn dc-secondary" data-outcome="' + esc(d.id) + '">' +
      (d.outcome_note ? "Edit outcome" : "Record outcome") +
      "</button>" +
      '<button type="button" class="dc-btn dc-secondary" data-applied="' + esc(d.id) + '">' +
      (d.applied ? "Mark not applied" : "Mark applied") +
      "</button>" +
      "</div>" +
      "</article>"
    );
  }

  function render(decisions) {
    if (!listEl) return;
    if (!decisions.length) {
      listEl.innerHTML =
        '<div class="dc-empty">No decisions yet. After your check-in, paste the change list above.</div>';
      return;
    }
    listEl.innerHTML = decisions.map(entryHtml).join("");
    focusHashDecision();
  }

  // A race row's Debrief chip links to /coach#decision-<id>; open it in the history.
  function focusHashDecision() {
    var m = /^#decision-(.+)$/.exec(window.location.hash || "");
    if (!m || !listEl) return;
    var el = document.getElementById("decision-" + m[1]);
    if (!el) return;
    el.classList.add("is-target");
    if (el.scrollIntoView) el.scrollIntoView({ block: "center" });
  }

  // ── Race link (P4-13) ──────────────────────────────────────────────────────
  // Same markers the server uses: the race-debrief prompt version line, or a
  // lessons line in the pasted change list. Mirrors decision_lessons.py.
  var DEBRIEF_VERSION = /prompt_version\s*:\s*race-debrief-v1\b/i;
  var LESSONS_LINE = /^\s*lessons\s*:/im;
  var SESSION_LINE = /session_id\s*:\s*([0-9a-fA-F]{8}-[0-9a-fA-F-]{27})/;
  var raceTouched = false;
  var recentDoneRaceId = "";

  function looksLikeDebrief(text) {
    return DEBRIEF_VERSION.test(text) || LESSONS_LINE.test(text);
  }

  function loadRaceOptions() {
    if (!raceEl) return;
    fetch("/api/races", { credentials: "same-origin" })
      .then(function (res) { return res.ok ? res.json() : []; })
      .then(function (races) {
        var done = races.filter(function (r) { return r.status === "done"; })
          .sort(function (a, b) { return a.race_date < b.race_date ? 1 : -1; });
        var rest = races.filter(function (r) { return r.status !== "done"; })
          .sort(function (a, b) { return a.race_date < b.race_date ? 1 : -1; });
        recentDoneRaceId = done.length ? done[0].id : "";
        raceEl.innerHTML = '<option value="">None</option>' + done.concat(rest).map(function (r) {
          return '<option value="' + esc(r.id) + '">' + esc(r.race_date + " \u00b7 " + r.name) + "</option>";
        }).join("");
      })
      .catch(function () {});
  }

  if (raceEl) {
    raceEl.addEventListener("change", function () { raceTouched = true; });
    if (rawEl) {
      rawEl.addEventListener("input", function () {
        // Auto-prefill only: never override a choice the user made.
        if (raceTouched || raceEl.value || !recentDoneRaceId) return;
        if (looksLikeDebrief(rawEl.value)) raceEl.value = recentDoneRaceId;
      });
    }
    loadRaceOptions();
  }

  function load() {
    return fetch("/api/decisions", { credentials: "same-origin" })
      .then(function (res) {
        if (!res.ok) throw new Error("could not load decisions (" + res.status + ")");
        return res.json();
      })
      .then(function (body) {
        render(body.decisions || []);
      })
      .catch(function (err) {
        if (listEl) {
          listEl.innerHTML = '<div class="dc-empty">' + esc(err.message) + "</div>";
        }
      });
  }

  function save() {
    var raw = (rawEl && rawEl.value ? rawEl.value : "").trim();
    if (!raw) {
      setFeedback("Paste the change list first.", "error");
      return;
    }
    var payload = { raw_text: raw };
    if (raceEl && raceEl.value) payload.race_id = raceEl.value;
    var sess = SESSION_LINE.exec(raw);
    if (sess) payload.session_id = sess[1];
    if (decidedEl && decidedEl.value) payload.decided_on = decidedEl.value;
    if (reviewEl && reviewEl.value) payload.review_on = reviewEl.value;
    if (tagsEl && tagsEl.value.trim()) {
      payload.tags = tagsEl.value.split(",").map(function (t) { return t.trim(); })
        .filter(Boolean);
    }

    saveBtn.disabled = true;
    setFeedback("");
    fetch("/api/decisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
      .then(function (res) {
        if (!res.ok) return res.json().then(function (d) { return Promise.reject(d); });
        return res.json();
      })
      .then(function () {
        rawEl.value = "";
        if (tagsEl) tagsEl.value = "";
        if (reviewEl) reviewEl.value = "";
        if (raceEl) { raceEl.value = ""; raceTouched = false; }
        setFeedback("Saved.", "success");
        return load();
      })
      .catch(function (errData) {
        var detail = errData && errData.detail;
        var msg = "Save failed.";
        if (Array.isArray(detail) && detail.length) msg = detail[0].msg || msg;
        else if (typeof detail === "string") msg = detail;
        setFeedback(msg, "error");
      })
      .finally(function () {
        saveBtn.disabled = false;
      });
  }

  function patch(id, body) {
    return fetch("/api/decisions/" + id, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
      .then(function (res) {
        if (!res.ok) throw new Error("update failed");
        return load();
      })
      .catch(function (err) {
        setFeedback(err.message, "error");
      });
  }

  if (listEl) {
    listEl.addEventListener("click", function (ev) {
      var outcomeBtn = ev.target.closest("[data-outcome]");
      if (outcomeBtn) {
        // A prompt is the right weight here: recording an outcome is a sentence,
        // typed once, weeks after the fact.
        var existing = outcomeBtn.closest(".dc-entry").querySelector(".dc-outcome strong");
        var note = window.prompt(
          "What happened? (e.g. held for 2 weeks, trend moved -0.4 kg)",
          existing ? existing.parentNode.textContent.replace(/^Outcome:\s*/, "") : ""
        );
        if (note === null) return;
        patch(outcomeBtn.getAttribute("data-outcome"), { outcome_note: note });
        return;
      }
      var appliedBtn = ev.target.closest("[data-applied]");
      if (appliedBtn) {
        var wasApplied = appliedBtn.textContent.indexOf("not applied") !== -1;
        patch(appliedBtn.getAttribute("data-applied"), { applied: wasApplied ? false : true });
      }
    });
  }

  if (saveBtn) saveBtn.addEventListener("click", save);

  if (decidedEl && !decidedEl.value) {
    decidedEl.value = window.AppCommon.todayISO();
  }

  load();
})();
