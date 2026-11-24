(function () {
  "use strict";

  var root = document.getElementById("wci-root");
  var weekLabel = document.getElementById("wci-week-label");
  var state = null;
  var parsedItems = [];
  var saveTimer = null;
  var esc = window.AppCommon && window.AppCommon.escapeHtml
    ? window.AppCommon.escapeHtml.bind(window.AppCommon)
    : function (s) { return String(s == null ? "" : s); };
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var WEEKDAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

  function toast(msg) {
    var el = document.getElementById("rv-toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.add("is-visible");
    clearTimeout(toast._t);
    toast._t = setTimeout(function () { el.classList.remove("is-visible"); }, 3200);
  }

  function setStatus(msg) {
    var el = document.getElementById("wci-live-status");
    if (el) el.textContent = msg || "";
  }

  function isoParts(iso) {
    var p = String(iso || "").slice(0, 10).split("-");
    return { y: parseInt(p[0], 10), m: parseInt(p[1], 10), d: parseInt(p[2], 10) };
  }

  function utcDate(iso) {
    var p = isoParts(iso);
    if (!p.y || !p.m || !p.d) return null;
    return new Date(Date.UTC(p.y, p.m - 1, p.d));
  }

  function fmtDayMon(d) {
    return d.getUTCDate() + " " + MONTHS[d.getUTCMonth()];
  }

  function weekSubtitle(weekStart) {
    var start = utcDate(weekStart);
    if (!start) return "";
    var end = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth(), start.getUTCDate() + 6));
    var wd = WEEKDAYS[end.getUTCDay()];
    return wd + " " + fmtDayMon(end) + " · week " + start.getUTCDate() + "–" + fmtDayMon(end) +
      " · 5 minutes, then copy to Claude";
  }

  function fmtNA(field, suffix) {
    if (!field || field.status === "not_available" || field.value == null) {
      return { text: "—", missing: true };
    }
    var unit = suffix != null ? suffix : (field.unit ? " " + field.unit : "");
    return { text: String(field.value) + unit, missing: false };
  }

  function naTitle(field) {
    return (!field || field.status === "not_available" || field.value == null)
      ? ' title="Not available: ask me"'
      : "";
  }

  function csrfFetch(url, opts) {
    if (window.AppCommon && typeof window.AppCommon.fetchWithCsrf === "function") {
      return window.AppCommon.fetchWithCsrf(url, opts);
    }
    return fetch(url, opts);
  }

  function patch(body) {
    setStatus("Saving…");
    return csrfFetch("/api/weekly-check-in", {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(function (r) {
      if (!r.ok) throw new Error("save");
      return r.json();
    }).then(function (d) {
      state = d;
      var preview = document.getElementById("wci-preview");
      if (preview) preview.textContent = d.prompt_preview || "";
      setStatus("Saved");
      return d;
    }).catch(function () {
      setStatus("");
      toast("Could not save, try again");
      throw new Error("save");
    });
  }

  function debouncePatch(body, okToast) {
    clearTimeout(saveTimer);
    saveTimer = setTimeout(function () {
      patch(body).then(function () { if (okToast) toast(okToast); }).catch(function () {});
    }, 300);
  }

  function segButtons(name, options, current, aria) {
    return '<div class="wci-seg" role="group" aria-label="' + esc(aria) + '">' +
      options.map(function (opt) {
        var on = String(current) === String(opt.value);
        return '<button type="button" class="wci-seg-btn" data-field="' + esc(name) +
          '" data-val="' + esc(opt.value) + '" aria-pressed="' + (on ? "true" : "false") + '">' +
          esc(opt.label) + "</button>";
      }).join("") + "</div>";
  }

  function renderChanges(items) {
    if (!items || !items.length) {
      return '<p class="rv-subtitle">Nothing carried from last week.</p>';
    }
    return items.map(function (c) {
      var st = c.status || "not_yet";
      var sub = [c.change_type, c.detail].filter(Boolean).join(" · ");
      return '<div class="wci-change" data-change="' + esc(c.id) + '">' +
        '<div class="wci-change-copy"><p class="wci-change-text">' + esc(c.text) + "</p>" +
        (sub ? '<p class="rv-subtitle">' + esc(sub) + "</p>" : "") + "</div>" +
        '<div class="wci-seg" role="group" aria-label="' + esc(c.text || "change") + ' status">' +
        [["done", "Done"], ["partly", "Partly"], ["not_yet", "Not yet"]].map(function (pair) {
          var on = st === pair[0];
          return '<button type="button" class="wci-seg-btn" data-status="' + pair[0] +
            '" aria-pressed="' + (on ? "true" : "false") + '">' + pair[1] + "</button>";
        }).join("") + "</div></div>";
    }).join("");
  }

  function tile(label, main, suffix, extraCls, title) {
    return '<div class="wci-tile' + (extraCls ? " " + extraCls : "") + '"' + (title || "") + ">" +
      '<span class="wci-tile-lbl">' + esc(label) + "</span>" +
      '<span class="rv-mono wci-tile-val">' + esc(main) +
      (suffix ? '<span class="wci-tile-suf">' + esc(suffix) + "</span>" : "") +
      "</span></div>";
  }

  function renderSnapshot(snap) {
    snap = snap || {};
    var sessions = fmtNA(snap.sessions_done);
    var planned = fmtNA(snap.sessions_planned);
    var tss = fmtNA(snap.week_tss);
    var long = fmtNA(snap.longest_run_seconds);
    var longT = fmtNA(snap.longest_run_target_seconds);
    var wt = fmtNA(snap.avg_7d_kg);
    var lunch = fmtNA(snap.lunch_rule_yes_count);
    var steps = fmtNA(snap.steps_avg);
    var feetB = fmtNA(snap.foot_blocks_done);
    var runs = fmtNA(snap.runs_in_week);
    var fuel = fmtNA(snap.fuel_rehearsals_done);
    var fuelDue = fmtNA(snap.fuel_rehearsals_due);
    var races = snap.races || [];
    var raceText = races.length
      ? races.map(function (r) { return r.name; }).join(", ")
      : "none this week";
    var rate = snap.weekly_rate_kg;
    var wtCls = "";
    if (rate && rate.status === "ok" && rate.value != null && Number(rate.value) < 0) wtCls = "is-good";
    var stepsCls = "";
    return '<div class="wci-snap-grid">' +
      tile("Sessions", sessions.missing || planned.missing ? "—" : sessions.text + " / " + planned.text + " planned", "", "", naTitle(snap.sessions_done)) +
      tile("Load", tss.missing ? "—" : tss.text, tss.missing ? "" : " TSS", "", naTitle(snap.week_tss)) +
      tile("Longest run", long.text, longT.missing ? "" : " / " + longT.text, "", naTitle(snap.longest_run_seconds)) +
      tile("Weight · 7-day avg", wt.text, "", wtCls, naTitle(snap.avg_7d_kg)) +
      tile("Lunch rule", lunch.missing ? "—" : lunch.text + " / 7", "", "", naTitle(snap.lunch_rule_yes_count)) +
      tile("Steps · avg", steps.text, "", stepsCls, naTitle(snap.steps_avg)) +
      tile("Foot blocks", feetB.missing || runs.missing ? "—" : feetB.text + " / " + runs.text + " runs", "", "", naTitle(snap.foot_blocks_done)) +
      tile("Fuel rehearsals", fuel.missing || fuelDue.missing ? "—" : fuel.text + " / " + fuelDue.text, "", "", naTitle(snap.fuel_rehearsals_done)) +
      tile("Races", raceText, "") +
      "</div>";
  }

  function promptVersion(data) {
    if (data.prompt_version) return data.prompt_version;
    var m = String(data.prompt_preview || "").match(/prompt_version:\s*(\S+)/);
    return m ? m[1] : "";
  }

  function renderError() {
    if (weekLabel) weekLabel.textContent = "";
    root.removeAttribute("aria-busy");
    root.innerHTML =
      '<section class="rv-card rv-stack">' +
      "<p class=\"rv-subtitle\">Could not load this week's check-in.</p>" +
      '<button type="button" class="rv-btn rv-btn--secondary" id="wci-retry">Try again</button></section>';
    var btn = document.getElementById("wci-retry");
    if (btn) btn.addEventListener("click", load);
  }

  function bindStepper() {
    var links = document.querySelectorAll(".wci-step[href^='#step-']");
    if (!links.length || !window.IntersectionObserver) return;
    var map = {};
    links.forEach(function (a) {
      var id = (a.getAttribute("href") || "").slice(1);
      if (id) map[id] = a;
    });
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (en) {
        if (!en.isIntersecting) return;
        links.forEach(function (a) { a.removeAttribute("aria-current"); a.classList.remove("is-on"); });
        var a = map[en.target.id];
        if (a) {
          a.setAttribute("aria-current", "step");
          a.classList.add("is-on");
        }
      });
    }, { rootMargin: "-20% 0px -60% 0px", threshold: 0.2 });
    ["step-1", "step-2", "step-3", "step-4"].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) io.observe(el);
    });
  }

  function render(data) {
    state = data;
    parsedItems = [];
    var noteKeep = "";
    var pasteKeep = "";
    var noteEl = document.getElementById("wci-note");
    var pasteEl = document.getElementById("wci-paste");
    if (noteEl) noteKeep = noteEl.value;
    if (pasteEl) pasteKeep = pasteEl.value;
    var snap = data.snapshot || {};
    if (weekLabel) weekLabel.textContent = weekSubtitle(data.week_start);
    var self = data.self_report || {};
    if (noteKeep) self.note = noteKeep;
    var streak = data.streak_days_to_a_race;
    var ver = promptVersion(data);
    var raceName = (snap.races && snap.races[0] && snap.races[0].name) || "";
    var step1Sub = raceName ? "from the " + raceName + " debrief" : "";
    var streakHtml = '<section class="rv-card rv-card--soft rv-stack wci-streak-card">' +
      '<h2 class="rv-label">Streak</h2>';
    if (data.checkins_done != null && data.checkins_target != null) {
      streakHtml += '<div class="rv-row"><span>Check-ins done</span><span class="rv-mono wci-streak">' +
        esc(data.checkins_done) + " / " + esc(data.checkins_target) +
        (raceName ? " to " + esc(raceName) : "") + "</span></div>";
    }
    if (streak != null) {
      streakHtml += '<p class="rv-subtitle">Days to next A race · ' + esc(streak) + "</p>";
    } else {
      streakHtml += '<p class="rv-subtitle">No A race scheduled.</p>';
    }
    streakHtml += '<p class="rv-subtitle">A missed Sunday rolls into the next one. It never asks you to make it up.</p></section>';

    root.removeAttribute("aria-busy");
    root.innerHTML =
      '<div class="wci-col">' +
      '<section class="rv-card rv-stack" id="step-1" data-checkin-step="1">' +
      '<div class="rv-row"><h2 class="rv-label">1 · Last week\'s changes</h2>' +
      (step1Sub ? '<span class="rv-subtitle">' + esc(step1Sub) + "</span>" : "") + "</div>" +
      renderChanges(data.carried_changes) + "</section>" +
      '<section class="rv-card rv-stack" id="step-2" data-checkin-step="2">' +
      '<div class="rv-row"><h2 class="rv-label">2 · The week, filled in for you</h2>' +
      '<a href="/v2/training/log">Training log</a></div>' +
      '<div class="rv-row"><button type="button" class="rv-btn rv-btn--secondary" id="wci-refresh">Refresh</button></div>' +
      renderSnapshot(snap) + "</section>" +
      '<section class="rv-card rv-stack" id="step-3" data-checkin-step="3">' +
      '<div class="rv-row"><h2 class="rv-label">3 · Three quick scores</h2>' +
      '<span class="rv-subtitle">the only things the app can\'t see</span></div>' +
      '<div class="wci-score-row"><div><p class="wci-score-title">Feet</p>' +
      '<p class="rv-subtitle">0 fine · 3 pain or numbness</p></div>' +
      segButtons("feet", [{ value: "0", label: "0" }, { value: "1", label: "1" }, { value: "2", label: "2" }, { value: "3", label: "3" }], self.feet, "Feet score 0 to 3") +
      "</div>" +
      '<div class="wci-score-row"><div><p class="wci-score-title">Sleep</p>' +
      '<p class="rv-subtitle">bed before 12:30 on how many nights</p></div>' +
      segButtons("bed_bucket", [{ value: "0-2", label: "0–2" }, { value: "3-4", label: "3–4" }, { value: "5-7", label: "5–7" }], self.bed_bucket, "Bed bucket") +
      "</div>" +
      '<div class="wci-score-row"><div><p class="wci-score-title">Motivation</p>' +
      '<p class="rv-subtitle">how training felt this week</p></div>' +
      segButtons("motivation", [{ value: "low", label: "Low" }, { value: "ok", label: "OK" }, { value: "high", label: "High" }], self.motivation, "Motivation") +
      "</div>" +
      '<label for="wci-note">Anything else</label>' +
      '<textarea id="wci-note" rows="3" class="rv-input wci-textarea" placeholder="Optional · e.g. travel next week, coach changed Thursday">' +
      esc(self.note || "") + "</textarea></section></div>" +
      '<div class="wci-col">' +
      '<section class="rv-card rv-stack wci-prompt-card" id="step-4" data-checkin-step="4">' +
      '<div class="rv-row"><h2 class="rv-label wci-prompt-lbl">4 · PROMPT PREVIEW</h2>' +
      (ver ? '<span class="rv-mono wci-prompt-ver">' + esc(ver) + "</span>" : "") + "</div>" +
      '<pre class="wci-preview" id="wci-preview" tabindex="0" aria-label="Prompt preview">' +
      esc(data.prompt_preview || "") + "</pre>" +
      '<button type="button" class="rv-btn rv-btn--accent" id="wci-copy">Copy for Claude</button></section>' +
      '<section class="rv-card rv-stack">' +
      '<div class="rv-row"><h2 class="rv-label">Paste the reply</h2>' +
      '<span class="rv-subtitle">reads the CHANGES TO APPLY block</span></div>' +
      '<label for="wci-paste">Claude\'s reply</label>' +
      '<textarea id="wci-paste" class="rv-input wci-textarea" rows="5" placeholder="Paste change list">' +
      esc(pasteKeep) + "</textarea>" +
      '<div class="wci-parse-actions">' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="wci-parse">Preview changes</button>' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="wci-edit-paste" hidden>Edit before saving</button>' +
      '<button type="button" class="rv-btn" id="wci-apply" hidden>Save to week</button></div>' +
      '<div id="wci-parsed-panel" class="wci-parsed-panel" hidden aria-live="polite">' +
      '<p class="rv-label">Will be saved to this week</p><ul id="wci-parsed" class="rv-stack"></ul></div>' +
      '<p class="rv-subtitle">Next Sunday opens on step 1 with these three, so nothing gets lost between weeks.</p>' +
      "</section>" + streakHtml + "</div>";

    bindStepper();
    bindCardEvents();
  }

  function bindCardEvents() {
    root.querySelectorAll(".wci-change").forEach(function (row) {
      row.querySelectorAll("[data-status]").forEach(function (btn) {
        btn.addEventListener("click", function () {
          var id = row.getAttribute("data-change");
          var status = btn.getAttribute("data-status");
          row.querySelectorAll("[data-status]").forEach(function (b) {
            var on = b === btn;
            b.setAttribute("aria-pressed", on ? "true" : "false");
            b.classList.toggle("is-on", on);
          });
          var items = (state.carried_changes || []).map(function (c) {
            return { id: c.id, status: c.id === id ? status : c.status };
          });
          debouncePatch({ carried_changes: items }, "Saved");
        });
      });
    });

    root.querySelectorAll("[data-field]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var field = btn.getAttribute("data-field");
        var val = btn.getAttribute("data-val");
        btn.parentNode.querySelectorAll("[data-field]").forEach(function (b) {
          var on = b === btn;
          b.setAttribute("aria-pressed", on ? "true" : "false");
        });
        var payload = {};
        if (field === "feet") payload.feet = parseInt(val, 10);
        else payload[field] = val;
        debouncePatch(payload, "Scores saved");
      });
    });

    var note = root.querySelector("#wci-note");
    if (note) {
      note.addEventListener("blur", function () {
        debouncePatch({ note: note.value }, "Scores saved");
      });
    }

    root.querySelector("#wci-copy").addEventListener("click", function () {
      var text = (state && state.prompt_preview) || "";
      navigator.clipboard.writeText(text).then(function () {
        toast("Copied");
      }).catch(function () {
        toast("Could not copy, select the text and copy manually");
      });
    });

    root.querySelector("#wci-parse").addEventListener("click", function () {
      var raw = root.querySelector("#wci-paste").value;
      csrfFetch("/api/weekly-check-in/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw_text: raw }),
      }).then(function (r) {
        if (!r.ok) throw new Error("parse");
        return r.json();
      }).then(function (data) {
        parsedItems = data.items || [];
        var ul = root.querySelector("#wci-parsed");
        var panel = root.querySelector("#wci-parsed-panel");
        ul.innerHTML = parsedItems.map(function (it) {
          var kind = String(it.change_type || "review").toUpperCase();
          var chipCls = "wci-chip wci-chip--" + esc(String(it.change_type || "review"));
          var sub = it.review_date || it.keep || "";
          return '<li class="wci-parsed-row"><span class="' + chipCls + '">' + esc(kind) + "</span>" +
            '<span>' + esc(it.text) + "</span>" +
            (sub ? '<span class="rv-subtitle">' + esc(sub) + "</span>" : "") + "</li>";
        }).join("");
        if (panel) panel.hidden = parsedItems.length === 0;
        var apply = root.querySelector("#wci-apply");
        var edit = root.querySelector("#wci-edit-paste");
        if (apply) apply.hidden = parsedItems.length === 0;
        if (edit) edit.hidden = parsedItems.length === 0;
      }).catch(function () { toast("Could not parse reply"); });
    });

    var editBtn = root.querySelector("#wci-edit-paste");
    if (editBtn) {
      editBtn.addEventListener("click", function () {
        var ta = root.querySelector("#wci-paste");
        if (ta) ta.focus();
      });
    }

    root.querySelector("#wci-apply").addEventListener("click", function () {
      csrfFetch("/api/weekly-check-in/apply-paste", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ raw_text: root.querySelector("#wci-paste").value, items: parsedItems }),
      }).then(function (r) {
        if (!r.ok) throw new Error("apply");
        return r.json();
      }).then(function (d) {
        if (d.check_in) render(d.check_in);
        toast("Changes saved to next week");
      }).catch(function () { toast("Could not save paste"); });
    });

    var refresh = root.querySelector("#wci-refresh");
    if (refresh) {
      refresh.addEventListener("click", function () {
        csrfFetch("/api/weekly-check-in/refresh", { method: "POST" })
          .then(function (r) {
            if (!r.ok) throw new Error("refresh");
            return r.json();
          })
          .then(function (d) {
            render(d);
            toast("Week data refreshed");
          })
          .catch(function () { toast("Could not save, try again"); });
      });
    }
  }

  function load() {
    root.setAttribute("aria-busy", "true");
    root.innerHTML =
      '<div class="wci-skel" aria-hidden="true"><span></span><span></span><span></span></div>';
    fetch("/api/weekly-check-in", { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("load");
        return r.json();
      })
      .then(render)
      .catch(renderError);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", load);
  } else {
    load();
  }
})();
