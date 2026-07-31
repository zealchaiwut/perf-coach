/*
 * decisions.js — the consult loop's log view.
 *
 * One textarea in, a dated list out. There is no parser and there should not be
 * one: the block is stored exactly as the consult wrote it, and the value is in
 * having the history at all. Recording an outcome is the half that closes the
 * loop, so it is one tap from the list rather than a separate screen.
 */
(function () {
  "use strict";

  var listEl = document.getElementById("dc-list");
  var rawEl = document.getElementById("dc-raw");
  var decidedEl = document.getElementById("dc-decided-on");
  var reviewEl = document.getElementById("dc-review-on");
  var tagsEl = document.getElementById("dc-tags");
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

    return (
      '<article class="dc-entry" data-id="' + esc(d.id) + '">' +
      '<div class="dc-entry-head">' +
      '<span class="dc-date">' + esc(d.decided_on) + "</span>" +
      '<span class="dc-ago">' + esc(agoLabel(d.decided_on)) + "</span>" +
      chips +
      "</div>" +
      '<pre class="dc-raw">' + esc(d.raw_text) + "</pre>" +
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
        '<div class="dc-empty">No decisions yet. After your next consult, paste the change list above.</div>';
      return;
    }
    listEl.innerHTML = decisions.map(entryHtml).join("");
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
