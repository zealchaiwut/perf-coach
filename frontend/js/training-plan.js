/* Training > Plan sub-tab — weekly training schedule (window.TrainingPlan).
 *
 * Ported from the interactive mock (plan-tab-mock.html): a single scrolling
 * page with three regions — Week plan (always), Add panel (collapsed), Detail
 * panel (collapsed) as a mutually-exclusive accordion. Wired to the live
 * /api/planned-sessions endpoints. Also owns Plan settings (ramp rate/taper
 * window/schedule preview) — moved here from Projection's ramp/taper model.
 *
 * CSS is injected once, scoped under .plan-panel with a pl- prefix so it never
 * clashes with the Log/Projection/Performance styles. All glyphs are clean UTF-8.
 */
(function () {
  'use strict';

  // ── State ─────────────────────────────────────────────────────────────────
  var _initialized = false;
  var _weekStart = null;          // Date (Monday) of the visible week
  var _bundle = null;             // last GET bundle
  var _panel = { open: null };    // null | 'add' | 'detail'
  var _addState = { top: 'single', sub: 'form', delim: 'pipe' };
  var _detail = null;             // the planned session dict being viewed
  var _dismissedGhosts = {};      // client-side Ignore

  var DOW = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'];
  var MON = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

  // Verbatim canonical weekly-plan kickoff prompt (scratchpad source of
  // truth). Embedded EXACTLY as written; only backticks are backslash-escaped
  // for the template literal. Do not paraphrase.
  var KICKOFF_PROMPT_TEMPLATE = `# Weekly Training Plan — Kickoff Prompt

Paste this as the first message in a new conversation to plan next week's
perf-coach training (running + strength). It tells Claude what to ask, what
defaults/preferences to apply, and the exact JSON format to hand back.

---

I want to plan next week's training and get it into a bulk-create JSON I can
paste into perf-coach's Plan tab. Please ask me the following before producing
anything:

1. **What did my coach give me for next week?** — paste the raw plan/notes as I
   have them (running sessions, paces, distances, any prescribed strength work).
2. **Any scheduling blockers or day preferences?** — days I can't train, a
   preferred day for the long run, travel, etc.
3. **How many sessions total this week?** — running + strength combined, so the
   week isn't over- or under-built relative to what I actually have time for.
4. *(Optional)* **Paste last week's plan and how it felt** — so you can adjust
   load, exercise selection, or scheduling based on what actually happened
   (soreness, missed sessions, sessions that felt too easy/hard).

Ask these one at a time or as a batch, whichever your interface supports. Don't
generate the plan until I've answered.

## Design principles to apply automatically (don't re-ask about these)

**Strength sessions** follow my usual 5-phase structure:
- **Warm-up** — ~10 minutes, only 2–4 exercises, building toward *today's*
  specific movement patterns (e.g. bodyweight squats + a light hinge drill
  before a squat/deadlift day) — not generic full-body mobility.
- **Heavy compound** — the day's main lift (squat/deadlift/front squat variant).
- **Superset 1** and **Superset 2** — each superset must pair **opposing muscle
  groups** (e.g. a lower-body pull paired with an upper-body push) so one side
  can rest while the other works. Never pair two exercises that hit the same
  muscle group back-to-back.
- Any exercise without a clean non-overlapping partner (e.g. hip thrust) gets
  its own standalone block rather than being forced into a bad pairing.
- **Accessories** — low-load finishers (plank, superman, stretching).

**Load and exercise selection:**
- If I give you a stated 1RM, **cross-check it against my recent logged working
  sets** before trusting it. If there's a big gap (e.g. a stated 1RM that's far
  above what recent RPE-rated sets imply), flag the mismatch and default to the
  more conservative, recent-data-based number — don't silently use the higher
  one.
- Prefer **dumbbells over barbell** for hinge-pattern accessory/superset work
  (e.g. RDL) unless I ask for barbell specifically. Give a conservative starting
  load for any DB variation I haven't done before, not a precise %1RM figure —
  those don't transfer cleanly across implements.
- Keep strength load **lighter/moderate** on any day adjacent to a long run,
  even if my "usual" version of that session is heavier. Say so explicitly when
  you dial something back for that reason.
- For light accessory days, feel free to **suggest specific exercises** in the
  style of my recent training (e.g. DB snatch, single-leg deadlift, glute
  bridge, lateral band walk) rather than leaving it vague.

**Running sessions** use Warmup → Main set (repeatable) → Cooldown blocks, each
with a **power or pace** target — never HR-based, since Stryd's importer
rejects HR blocks.

## Output format

Give me the final week as a single JSON array, one object per session (same
date can have multiple sessions), ready to paste into perf-coach's bulk-create
JSON input:

\`\`\`json
[
  {
    "date": "YYYY-MM-DD",
    "type": "run",
    "name": "Session name",
    "notes": "Optional context, e.g. 'From coach.'",
    "blocks": [
      {"phase": "warmup", "duration_min": 10},
      {"phase": "main", "duration_min": 10, "repeat": 3, "rest_min": 2, "target": "92% CP"},
      {"phase": "cooldown", "duration_min": 8}
    ]
  },
  {
    "date": "YYYY-MM-DD",
    "type": "strength",
    "name": "Session name",
    "notes": "Any load/structure caveats worth flagging",
    "exercises": [
      {"block": "Warm-up", "name": "...", "sets": 2, "reps": 15, "load": "..."},
      {"block": "Heavy compound", "name": "...", "sets": 4, "reps": 8, "load": "..."},
      {"block": "Superset 1", "name": "...", "sets": 3, "reps": 8, "load": "..."},
      {"block": "Superset 1", "name": "...", "sets": 3, "reps": 12, "load": "..."},
      {"block": "Accessories", "name": "...", "sets": 3, "reps": "40s hold", "load": "bodyweight"}
    ]
  },
  {
    "date": "YYYY-MM-DD",
    "type": "rest"
  }
]
\`\`\`

\`type\` is one of \`run\` / \`strength\` / \`plyo\` / \`rest\`. Only include the days we
actually discussed — don't invent sessions for days I didn't give you
information about.
`;

  // ── Public API ──────────────────────────────────────────────────────────────
  window.TrainingPlan = {
    init: function () {
      _injectStyles();
      if (!_weekStart) _weekStart = _mondayOf(new Date());
      // Idempotent: always re-render the shell + reload the current week.
      _renderAll();
      _loadWeek(function () {
        if (_pendingOpenId) {
          var id = _pendingOpenId;
          _pendingOpenId = null;
          _openDetailById(id);
        }
      });
      _wireLoadPlanSettings();
      _loadLoadPlan();
      _loadWeekLoad(_iso(_weekStart));
    },
    // Deep link from outside the Plan tab (e.g. the Log calendar): scope the
    // week to the session's date and flag it to open once init()'s own
    // _loadWeek resolves. Call BEFORE switching to the Plan tab, so init()
    // (triggered by the tab switch) picks up the right _weekStart/_pendingOpenId.
    openSession: function (sessionId, dateIso) {
      if (dateIso) _weekStart = _mondayOf(_parseISO(dateIso));
      _pendingOpenId = sessionId;
    },
    reload: function () {
      _loadWeek(function () {});
    },
    // Exposed for the Plan Suggestions module (a separate closure below) so it
    // scopes suggestions to whichever week is actually on screen, instead of
    // assuming "next Monday" regardless of what the athlete is looking at.
    getWeekStartISO: function () {
      return _iso(_weekStart || _mondayOf(new Date()));
    },
    // day_offset/date/open (no logged workout, no existing planned session,
    // not before today) for each day of the currently-viewed week — lets the
    // suggestions prefs form show accurate checkboxes without a second
    // network round trip (the backend is still the authority: it re-derives
    // and enforces the same allowed_offsets itself).
    getOpenDayInfo: function () {
      if (!_weekStart) return [];
      var wsIso = _iso(_weekStart);
      var todayIso = _todayISO();
      var offsetOfToday = Math.round((_parseISO(todayIso) - _parseISO(wsIso)) / 86400000);
      var days = (_bundle && _bundle.days) || [];
      var out = [];
      for (var i = 0; i < 7; i++) {
        var day = days[i] || {};
        var hasPlanned = (day.planned || []).length > 0;
        var hasUnplanned = (day.unplanned || []).some(function (u) { return !_dismissedGhosts[u.id]; });
        out.push({
          day_offset: i,
          date: day.date || _iso(_addDays(_weekStart, i)),
          open: i >= offsetOfToday && !hasPlanned && !hasUnplanned
        });
      }
      return out;
    }
  };

  // ── Date helpers ──────────────────────────────────────────────────────────
  function _mondayOf(d) {
    var x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    var dow = (x.getDay() + 6) % 7; // 0=Mon
    x.setDate(x.getDate() - dow);
    return x;
  }
  function _iso(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }
  function _parseISO(s) {
    var p = String(s).split('-');
    return new Date(+p[0], +p[1] - 1, +p[2]);
  }
  function _addDays(d, n) { var x = new Date(d); x.setDate(x.getDate() + n); return x; }
  function _todayISO() {
    return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' });
  }
  function _fmtWeekTitle(start) {
    var end = _addDays(start, 6);
    return 'Week of ' + MON[start.getMonth()] + ' ' + start.getDate() +
      ' – ' + MON[end.getMonth()] + ' ' + end.getDate() + ', ' + end.getFullYear();
  }
  function _fmtDayDate(iso) {
    var d = _parseISO(iso);
    return DOW[(d.getDay() + 6) % 7].charAt(0) + DOW[(d.getDay() + 6) % 7].slice(1).toLowerCase() +
      ', ' + MON[d.getMonth()] + ' ' + d.getDate();
  }
  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ── CSRF-safe fetch (window.fetch is patched by nav.js to attach X-CSRF) ────
  function _api(method, url, body) {
    var opts = { method: method, credentials: 'same-origin', headers: {} };
    if (body !== undefined) { opts.headers['Content-Type'] = 'application/json'; opts.body = JSON.stringify(body); }
    return fetch(url, opts).then(function (r) {
      if (r.status === 204) return null;
      return r.json().then(function (d) {
        if (!r.ok) throw new Error((d && (d.detail && (d.detail.error || d.detail)) ) || ('HTTP ' + r.status));
        return d;
      });
    });
  }

  function _toast(msg, isErr) {
    if (window.UIStates && window.UIStates.showToast) window.UIStates.showToast(msg, !!isErr);
  }

  // ── Load / reload the week ──────────────────────────────────────────────────
  function _loadWeek(onDone) {
    var from = _iso(_weekStart), to = _iso(_addDays(_weekStart, 6));
    var host = document.getElementById('plan-week-list');
    if (host) host.innerHTML = '<div class="pl-loading">Loading week…</div>';
    _api('GET', '/api/planned-sessions?from=' + from + '&to=' + to)
      .then(function (data) {
        _bundle = data;
        _renderWeekList();
        // Keep an open detail panel in sync with the freshly loaded bundle
        // (a mutation triggered from inside the panel doesn't otherwise
        // refresh it, since it renders from _detail, not _bundle).
        if (_detail) {
          var updated = null;
          (_bundle.days || []).forEach(function (d) {
            (d.planned || []).forEach(function (p) { if (p.id === _detail.id) updated = p; });
          });
          _detail = updated;
          _renderDetailSection();
        }
        if (onDone) onDone();
      })
      .catch(function () {
        if (host) host.innerHTML = '<div class="pl-loading">Could not load the week.</div>';
      });
  }

  // Set by openSession() before the tab switch triggers init(); consumed once
  // the resulting week load resolves (see init() below).
  var _pendingOpenId = null;

  // ── Session Load Plan (Plan-tab revamp, Part 1) ─────────────────────────────
  // Race-anchored ramp/hold/taper weekly TSS targets. Every number rendered
  // here comes straight from GET /api/plan/load-plan — the math (ramp/hold/
  // taper/ACWR-ceiling) lives ONLY in backend/services/load_plan.py; this
  // file just draws it. See docs/calculations/load-plan.md. Static HTML host
  // (#load-plan-section) — wired once in init() via property assignment
  // (.onclick/.oninput), same idempotent convention as the rest of this file.
  var _lpData = null; // last GET /api/plan/load-plan response (null = no A race)
  var PHASE_LABEL = { ramp: 'Target — ramp', hold: 'Target — peak hold', taper: 'Target — taper', race: 'Race week' };

  function _fmtPct1(fraction) {
    return (Math.round(fraction * 1000) / 10) + '%';
  }
  function _fmtShortDate(iso) {
    var d = _parseISO(iso);
    return MON[d.getMonth()] + ' ' + d.getDate();
  }

  function _loadLoadPlan() {
    _api('GET', '/api/plan/load-plan').then(function (data) {
      _lpData = data;
      _renderLoadPlan();
    }).catch(function () {
      _lpData = null;
      _renderLoadPlan();
    });
  }

  function _renderLoadPlan() {
    var rulesStrip = document.getElementById('lp-rules-strip');
    var chartWrap = document.getElementById('lp-chart-wrap');
    var legend = document.getElementById('lp-legend');
    var footnote = document.getElementById('lp-footnote');
    var emptyEl = document.getElementById('lp-empty');
    var warnEl = document.getElementById('lp-warning');
    var subtitle = document.getElementById('lp-subtitle');
    var cogBtn = document.getElementById('lp-cog-btn');

    if (!_lpData) {
      if (rulesStrip) rulesStrip.hidden = true;
      if (chartWrap) { chartWrap.hidden = true; chartWrap.innerHTML = ''; }
      if (legend) legend.hidden = true;
      if (footnote) footnote.hidden = true;
      if (warnEl) warnEl.hidden = true;
      if (emptyEl) emptyEl.hidden = false;
      if (subtitle) subtitle.innerHTML = '&nbsp;';
      if (cogBtn) cogBtn.hidden = true;
      return;
    }

    if (emptyEl) emptyEl.hidden = true;
    if (cogBtn) cogBtn.hidden = false;

    if (subtitle) {
      var firstWeek = _lpData.weeks[0];
      var lastWeek = _lpData.weeks[_lpData.weeks.length - 1];
      subtitle.textContent =
        (firstWeek ? _fmtShortDate(firstWeek.week_start) : '') + ' → ' +
        _fmtShortDate(_lpData.race.date) + ' · ' + _lpData.race.name;
    }

    if (rulesStrip) {
      rulesStrip.hidden = false;
      _setText('lp-rule-race', _lpData.race.name + ' · ' + _fmtShortDate(_lpData.race.date));
      _setText('lp-rule-weeks', _lpData.weeks_to_race + ' weeks');
      _setText('lp-rule-ramp', '+' + _fmtPct1(_lpData.ramp_rate) + ' / week');
      _setText('lp-rule-hold', _lpData.hold_weeks + ' wks · ' + Math.round(_lpData.peak) + ' TSS');
      _setText('lp-rule-taper', _lpData.taper_weeks + ' weeks');
    }

    if (warnEl) {
      if (_lpData.warning) { warnEl.hidden = false; warnEl.textContent = _lpData.warning; }
      else warnEl.hidden = true;
    }

    _renderLoadPlanChart();
    _renderWeekBudget();

    if (legend) {
      legend.hidden = false;
      legend.innerHTML =
        _legendItem('#4f6ef7', 'Actual (logged)') +
        _legendItem('#e6ebfe', 'Target — ramp', '#4f6ef7') +
        _legendItem('#e4e9fd', 'Target — peak hold', '#6d87f8') +
        _legendItem('#fdf3da', 'Target — taper', '#d97706') +
        _legendItem('#fee2e2', 'Race week', '#dc2626');
    }
    if (footnote) footnote.hidden = false;
  }

  function _legendItem(bg, label, borderColor) {
    var style = 'background:' + bg + (borderColor ? ';border:1.5px solid ' + borderColor : '');
    return '<span class="lp-legend-item"><span class="lp-legend-swatch" style="' + style + '"></span>' + esc(label) + '</span>';
  }

  function _setText(id, text) {
    var el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function _renderLoadPlanChart() {
    var host = document.getElementById('lp-chart-wrap');
    if (!host) return;
    host.hidden = false;

    var prior = _lpData.prior_weeks || [];
    var weeks = _lpData.weeks || [];
    var totalCols = prior.length + weeks.length;
    if (totalCols === 0) { host.innerHTML = ''; return; }

    var allValues = prior.map(function (p) { return p.actual_tss; })
      .concat(weeks.map(function (w) { return w.target_tss; }));
    var maxVal = Math.max.apply(null, allValues.concat([1]));

    var barsHtml = '';
    var axisHtml = '';
    var prevMonth = null;

    function axisCol(iso) {
      var d = _parseISO(iso);
      var m = d.getMonth();
      var showMonth = m !== prevMonth;
      prevMonth = m;
      return '<div class="lp-axis-col">' + d.getDate() +
        (showMonth ? '<span class="mon">' + MON[m] + '</span>' : '') + '</div>';
    }

    prior.forEach(function (p) {
      var h = Math.max(6, (p.actual_tss / maxVal) * 100);
      barsHtml += '<div class="lp-bar-col"><div class="lp-bar actual" style="height:' + h + '%">' +
        '<span class="lp-bar-value">' + Math.round(p.actual_tss) + '</span></div></div>';
      axisHtml += axisCol(p.week_start);
    });

    var thisWeekCol = -1, raceCol = -1;
    var holdFirst = -1, holdLast = -1;

    weeks.forEach(function (w, i) {
      var col = prior.length + i;
      if (w.phase === 'ramp' && w.week_index === 1) thisWeekCol = col;
      if (w.phase === 'hold') { if (holdFirst < 0) holdFirst = col; holdLast = col; }
      if (w.phase === 'race') raceCol = col;
      if (w.week_index === 1) thisWeekCol = col; // week_index 1 is always "this week", any phase

      var h = Math.max(6, (w.target_tss / maxVal) * 100);
      var cls = 'lp-bar target phase-' + w.phase + (w.clamped ? ' is-clamped' : '');
      var colCls = 'lp-bar-col' + (w.week_index === 1 ? ' is-this-week' : '');
      barsHtml += '<div class="' + colCls + '"><div class="' + cls + '" style="height:' + h + '%" title="' +
        esc(PHASE_LABEL[w.phase] || w.phase) + (w.clamped ? ' — ACWR-clamped' : '') + '">' +
        '<span class="lp-bar-value">' + Math.round(w.target_tss) + '</span></div></div>';
      axisHtml += axisCol(w.week_start);
    });

    var bracketHtml = '';
    if (holdFirst >= 0 && holdLast >= 0) {
      var left = (holdFirst / totalCols) * 100;
      var width = ((holdLast - holdFirst + 1) / totalCols) * 100;
      bracketHtml = '<div class="lp-bracket" style="left:' + left + '%;width:' + width + '%">' +
        '<span class="lp-bracket-lab">PEAK HOLD · ' + _lpData.hold_weeks + ' WKS</span></div>';
    }

    var flagHtml = '';
    if (thisWeekCol >= 0) {
      var twLeft = ((thisWeekCol + 0.5) / totalCols) * 100;
      flagHtml += '<div class="lp-flag-this-week" style="left:' + twLeft + '%">THIS WEEK</div>';
    }
    if (raceCol >= 0) {
      var rLeft = ((raceCol + 0.5) / totalCols) * 100;
      flagHtml += '<div class="lp-flag-race" style="left:' + rLeft + '%">' +
        '<div class="caret">▲</div><div class="lp-flag-race-badge">RACE DAY<br>' +
        esc(_fmtRaceDayLabel(_lpData.race.date)) + '</div></div>';
    }

    host.innerHTML =
      '<div class="lp-bracket-row" style="position:relative;height:14px;">' + bracketHtml + '</div>' +
      '<div class="lp-bars">' + barsHtml + '</div>' +
      '<div class="lp-axis">' + axisHtml + '</div>' +
      '<div class="lp-flag-row">' + flagHtml + '</div>';
  }

  function _fmtRaceDayLabel(iso) {
    var d = _parseISO(iso);
    return DOW[(d.getDay() + 6) % 7].charAt(0) + DOW[(d.getDay() + 6) % 7].slice(1).toLowerCase() +
      ' ' + MON[d.getMonth()] + ' ' + d.getDate();
  }

  function _renderWeekBudget() {
    var bar = document.getElementById('lp-week-budget-bar');
    var line = document.getElementById('lp-week-budget-line');
    if (!bar || !_lpData) return;
    var ramp = _lpData.ramp_weeks, hold = _lpData.hold_weeks, taper = _lpData.taper_weeks;
    var total = Math.max(1, ramp + hold + taper);
    bar.innerHTML =
      '<span class="ramp" style="flex:' + ramp + ' 0 0" title="Ramp · ' + ramp + ' wks"></span>' +
      '<span class="hold" style="flex:' + hold + ' 0 0" title="Peak hold · ' + hold + ' wks"></span>' +
      '<span class="taper" style="flex:' + taper + ' 0 0" title="Taper · ' + taper + ' wks"></span>';
    if (line) {
      line.textContent = 'ramp ' + ramp + ' + hold ' + hold + ' + taper ' + taper + ' = ' + total +
        ' weeks · peak ' + Math.round(_lpData.peak) + ' TSS';
    }
  }

  // ── Settings panel (cog toggle, ramp slider<->input sync, save) ─────────────

  function _toggleLoadPlanSettings() {
    var panel = document.getElementById('lp-settings-panel');
    var cogBtn = document.getElementById('lp-cog-btn');
    if (!panel) return;
    var opening = panel.hidden;
    panel.hidden = !opening;
    if (cogBtn) cogBtn.classList.toggle('is-active', opening);
    if (opening && _lpData) {
      _setNum('lp-ramp-slider', _lpData.ramp_rate * 100);
      _setNum('lp-ramp-input', _lpData.ramp_rate * 100);
      _setNum('lp-hold-input', _lpData.hold_weeks);
      _setNum('lp-taper-input', _lpData.taper_weeks);
      _renderWeekBudget();
    }
  }

  function _setNum(id, val) {
    var el = document.getElementById(id);
    if (el) el.value = val;
  }

  function _saveLoadPlanRules() {
    var rampIn = document.getElementById('lp-ramp-input');
    var holdIn = document.getElementById('lp-hold-input');
    var taperIn = document.getElementById('lp-taper-input');
    var errEl = document.getElementById('lp-settings-error');
    var savedEl = document.getElementById('lp-settings-saved');
    if (errEl) errEl.textContent = '';

    var rampPct = rampIn ? parseFloat(rampIn.value) : NaN;
    var hold = holdIn ? parseInt(holdIn.value, 10) : NaN;
    var taper = taperIn ? parseInt(taperIn.value, 10) : NaN;

    if (isNaN(rampPct) || rampPct < 0 || rampPct > 10) {
      if (errEl) errEl.textContent = 'Ramp rate must be between 0 and 10%.';
      return;
    }
    if (isNaN(hold) || hold < 0) {
      if (errEl) errEl.textContent = 'Peak hold must be 0 or more weeks.';
      return;
    }
    if (isNaN(taper) || taper < 0) {
      if (errEl) errEl.textContent = 'Taper window must be 0 or more weeks.';
      return;
    }

    _api('PUT', '/api/plan/rules', { ramp_rate: rampPct / 100, hold_weeks: hold, taper_weeks: taper })
      .then(function () {
        if (savedEl) {
          savedEl.style.display = '';
          setTimeout(function () { savedEl.style.display = 'none'; }, 2000);
        }
        _loadLoadPlan();
        _loadWeekLoad();
      })
      .catch(function (e) {
        if (errEl) errEl.textContent = e.message || 'Save failed.';
      });
  }

  function _wireLoadPlanSettings() {
    var cogBtn = document.getElementById('lp-cog-btn');
    var rampSlider = document.getElementById('lp-ramp-slider');
    var rampInput = document.getElementById('lp-ramp-input');
    var saveBtn = document.getElementById('lp-save-btn');
    if (cogBtn) cogBtn.onclick = _toggleLoadPlanSettings;
    if (rampSlider) rampSlider.oninput = function () { if (rampInput) rampInput.value = rampSlider.value; };
    if (rampInput) rampInput.oninput = function () { if (rampSlider) rampSlider.value = rampInput.value; };
    if (saveBtn) saveBtn.onclick = _saveLoadPlanRules;
  }

  // ── Session load · this week (Plan-tab revamp, Part 2) ──────────────────────
  // target_tss/clamped always come straight from GET /api/plan/week-load,
  // itself backed by the same compute_load_plan series as the Session Load
  // Plan card above — never recomputed client-side. See
  // docs/calculations/load-plan.md.
  var _wlData = null;

  function _loadWeekLoad(weekStartISO) {
    var url = '/api/plan/week-load' + (weekStartISO ? '?week_start=' + weekStartISO : '');
    _api('GET', url).then(function (data) {
      _wlData = data;
      _renderWeekLoad();
    }).catch(function () {
      _wlData = null;
      _renderWeekLoad();
    });
  }

  function _renderWeekLoad() {
    var body = document.getElementById('wl-body');
    var emptyEl = document.getElementById('wl-empty');
    if (!body) return;

    if (!_wlData || _wlData.target_tss == null) {
      body.hidden = true;
      if (emptyEl) emptyEl.hidden = false;
      return;
    }
    if (emptyEl) emptyEl.hidden = true;
    body.hidden = false;

    var d = _wlData;
    _setText('wl-target-val', Math.round(d.target_tss));

    var pill = document.getElementById('wl-state-pill');
    if (pill) {
      pill.className = 'wl-state-pill' + (d.state ? ' ' + d.state : '');
      pill.textContent = d.state === 'on_track' ? 'On track' : d.state === 'under' ? 'Under' :
        d.state === 'over' ? 'Over' : '—';
    }

    var lower = Math.round(d.target_tss * 0.95), upper = Math.round(d.target_tss * 1.05);
    var diff = Math.round(d.projected_tss - d.target_tss);
    var diffStr = (diff > 0 ? '+' : '') + diff;
    var inOut = (d.projected_tss >= lower && d.projected_tss <= upper) ? 'inside' : 'outside';
    var line = document.getElementById('wl-projected-line');
    if (line) {
      line.innerHTML = 'projected <b>' + Math.round(d.projected_tss) + '</b> &middot; ' + esc(diffStr) +
        ' ' + inOut + ' &plusmn;5% band (' + lower + '&ndash;' + upper + ')';
    }

    _setText('wl-baseline-val', Math.round(d.baseline_tss) + ' TSS');
    _setText('wl-ramp-val', (d.ramp_rate * 100).toFixed(1).replace(/\.0$/, '') + '%');
    _setText('wl-target-cell-val', Math.round(d.target_tss) + ' TSS');

    var spark = document.getElementById('wl-sparkline');
    if (spark) {
      var priors = d.prior_4_weeks_actual || [];
      var maxV = Math.max.apply(null, priors.map(function (p) { return p.actual_tss; }).concat([1]));
      spark.innerHTML = priors.map(function (p) {
        var h = Math.max(4, (p.actual_tss / maxV) * 100);
        return '<span style="height:' + h + '%" title="' + esc(p.week_start) + ': ' +
          Math.round(p.actual_tss) + ' TSS"></span>';
      }).join('');
    }
    _setText(
      'wl-baseline-compare',
      'planned ' + Math.round(d.baseline_planned_tss) + ' · logged ' + Math.round(d.baseline_tss),
    );

    if (d.acwr_ceiling != null) {
      _setText('wl-guardrail-ceiling', Math.round(d.acwr_ceiling));
      _setText(
        'wl-guardrail-detail',
        'ACWR ' + (d.acwr != null ? d.acwr.toFixed(2) : '—') +
          ' · 28-d avg ' + Math.round(d.trailing_28d_avg),
      );
    } else {
      _setText('wl-guardrail-ceiling', '—');
      _setText('wl-guardrail-detail', '');
    }

    // Gauge: logged (solid) + planned (hatched) stacked, scaled to whichever
    // is bigger — the ceiling, the target, or the projected total — so both
    // ticks always land on-gauge, even for a clamped (target < ceiling-ish)
    // or way-over week.
    var scaleMax = Math.max(d.target_tss, d.acwr_ceiling || 0, d.projected_tss, 1) * 1.05;
    var loggedPct = Math.min(100, (d.logged_tss / scaleMax) * 100);
    var plannedPct = Math.min(100 - loggedPct, (d.planned_tss / scaleMax) * 100);
    var loggedEl = document.getElementById('wl-gauge-logged');
    var plannedEl = document.getElementById('wl-gauge-planned');
    if (loggedEl) loggedEl.style.width = loggedPct + '%';
    if (plannedEl) { plannedEl.style.left = loggedPct + '%'; plannedEl.style.width = plannedPct + '%'; }
    var targetTick = document.getElementById('wl-gauge-tick-target');
    if (targetTick) targetTick.style.left = Math.min(100, (d.target_tss / scaleMax) * 100) + '%';
    var ceilingTick = document.getElementById('wl-gauge-tick-ceiling');
    if (ceilingTick) {
      if (d.acwr_ceiling != null) {
        ceilingTick.style.display = '';
        ceilingTick.style.left = Math.min(100, (d.acwr_ceiling / scaleMax) * 100) + '%';
      } else {
        ceilingTick.style.display = 'none';
      }
    }
    var legend = document.getElementById('wl-gauge-legend');
    if (legend) {
      legend.innerHTML =
        '<span><span class="sw" style="background:var(--pm-blue)"></span>Logged ' + Math.round(d.logged_tss) + '</span>' +
        '<span><span class="sw" style="background:repeating-linear-gradient(45deg,var(--pm-blueSoft) 0 3px,transparent 3px 6px),rgba(79,110,247,0.18)"></span>Planned ' + Math.round(d.planned_tss) + '</span>' +
        '<span>Projected ' + Math.round(d.projected_tss) + ' / ' + Math.round(d.target_tss) + ' TSS' +
          (d.clamped ? ' &middot; <span style="color:var(--pm-amber);font-weight:700;">clamped</span>' : '') + '</span>';
    }
  }

  // ── Render shell ────────────────────────────────────────────────────────────
  function _renderAll() {
    _renderWeekSection();
    _renderAddSection();
    _renderDetailSection();
  }

  function _renderWeekSection() {
    var host = document.getElementById('plan-week-section');
    if (!host) return;
    host.innerHTML =
      '<div class="pl-card">' +
        '<div class="pl-chead"><div class="pl-wknav">' +
          '<button class="pl-arw" id="pl-prev" aria-label="Previous week">‹</button>' +
          '<span class="pl-wktitle" id="pl-wktitle">' + esc(_fmtWeekTitle(_weekStart)) + '</span>' +
          '<button class="pl-arw" id="pl-next" aria-label="Next week">›</button>' +
        '</div>' +
        '<div class="pl-btnrow">' +
          /* Repurposed to open the AI next-week suggestions panel (issue #1315).
             It proxies a click to the suggestions module's own (hidden) trigger
             button, which lives in a separate closure. */
          '<button class="pl-btn pl-ghost" id="pl-suggest" title="AI-suggested sessions for next week">✨ Suggest sessions</button>' +
          '<button class="pl-btn pl-dark" id="pl-add">+ Add</button>' +
        '</div></div>' +
        '<div class="pl-infobanner" style="margin-bottom:12px;">Synced workouts from Strava/Stryd auto-match to planned sessions. Drag a <b>planned</b> or <b>missed</b> card to reschedule; ambiguous or missing matches need a quick confirm below. These planned sessions <b>don’t feed Projection’s ramp/taper load model</b> — separate systems.</div>' +
        '<div class="pl-weeklist" id="plan-week-list"></div>' +
        '<div class="pl-legend">' +
          '<span><b style="background:var(--pl-run)"></b>Run</span><span><b style="background:var(--pl-lift)"></b>Strength / Plyo</span>' +
          '<span style="color:var(--pl-faint);margin:0 2px;">·</span>' +
          '<span><b style="background:var(--pl-green)"></b>Done</span><span><b style="background:var(--pl-amber)"></b>Needs review</span><span><b style="background:var(--pl-red)"></b>Missed</span>' +
        '</div>' +
      '</div>';
    document.getElementById('pl-prev').onclick = function () {
      _weekStart = _addDays(_weekStart, -7); _renderWeekSection(); _loadWeek(); _loadWeekLoad(_iso(_weekStart));
    };
    document.getElementById('pl-next').onclick = function () {
      _weekStart = _addDays(_weekStart, 7); _renderWeekSection(); _loadWeek(); _loadWeekLoad(_iso(_weekStart));
    };
    document.getElementById('pl-add').onclick = function () { _openAdd('single'); };
    var sugBtn = document.getElementById('pl-suggest');
    if (sugBtn) sugBtn.onclick = function () {
      var t = document.getElementById('plan-suggestions-trigger');
      if (t) t.click();
      var panel = document.getElementById('plan-suggestions-panel');
      if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    };
    if (_bundle) _renderWeekList();
  }

  function _renderWeekList() {
    var host = document.getElementById('plan-week-list');
    if (!host || !_bundle) return;
    var todayStr = _todayISO();
    host.innerHTML = (_bundle.days || []).map(function (day) {
      var isPast = day.date < todayStr;
      var cls = day.date === todayStr ? 'today' : (isPast ? 'past' : '');
      var cards = (day.planned || []).map(function (p) { return _plannedCardHtml(p, day); }).join('');
      var ghosts = (day.unplanned || []).filter(function (u) { return !_dismissedGhosts[u.id]; })
        .map(function (u) { return _ghostCardHtml(u, day); }).join('');
      var hasContent = (day.planned || []).length || ghosts;
      var rest = !hasContent ? '<div class="pl-restday">Rest day</div>' : '';
      // A past day is done — no NEW session should be added to it. Existing
      // cards keep every action (match/change match/mark missed/delete); only
      // the "+ add" trigger for a fresh session is disabled.
      var addDay = isPast
        ? '<div class="pl-addday is-disabled" title="This day has passed — nothing new can be added">+ add</div>'
        : '<div class="pl-addday" data-add-date="' + day.date + '">+ add</div>';
      return '<div class="pl-dayrow ' + cls + '" data-date="' + day.date + '">' +
        '<div class="pl-daylabel"><span class="pl-dname">' + day.dow + '</span><span class="pl-dnum">' + _parseISO(day.date).getDate() + '</span></div>' +
        '<div class="pl-daybody">' + cards + ghosts + rest + addDay +
        '</div>' +
      '</div>';
    }).join('');
    _wireWeekEvents();
  }

  function _statusTag(status, hasActual) {
    if (status === 'missed') return '<span class="pl-stat-tag missed">MISSED</span>';
    if (status === 'needs_review') return '<span class="pl-stat-tag review">NEEDS REVIEW</span>';
    if (status === 'done_auto') return '<span class="pl-stat-tag done">AUTO-MATCHED</span>';
    if (status === 'done_manual') return hasActual
      ? '<span class="pl-stat-tag done">MANUALLY LINKED</span>'
      : '<span class="pl-stat-tag done">COMPLETED (no data)</span>';
    return '';
  }

  function _plannedMeta(p) {
    // Prefer a short structure-derived summary; fall back to notes.
    var s = p.structure || {};
    if (Array.isArray(s.blocks) && s.blocks.length) {
      var tot = 0;
      s.blocks.forEach(function (b) {
        var d = Number(b.duration_min) || 0, r = Math.max(1, Number(b.repeat) || 1);
        tot += d * r + (Number(b.rest_min) || 0) * (r - 1);
      });
      var tgt = (s.blocks.find(function (b) { return b.target; }) || {}).target;
      return (tot ? tot + 'min' : '') + (tgt ? ' · ' + tgt : '');
    }
    if (Array.isArray(s.exercises) && s.exercises.length) {
      return s.exercises.length + ' exercise' + (s.exercises.length > 1 ? 's' : '');
    }
    return p.notes ? String(p.notes).slice(0, 40) : '';
  }

  function _famClass(t) { return (t === 'run') ? 'run' : 'lift'; }

  // Quick-tag effort feeling row (😩 hard / 😐 ok / 😊 easy). Untagged → all
  // three faint; tagged → only the selected icon shown filled, others hidden.
  // Writes PATCH /api/workouts/{workoutId} feeling. workoutId="" → no row.
  var _FEELINGS = [
    { key: 'hard', icon: '😩', label: 'Hard' },
    { key: 'ok', icon: '😐', label: 'OK' },
    { key: 'easy', icon: '😊', label: 'Easy' }
  ];
  // "View full workout →" deep link on a matched (done_*) card. Navigates to
  // the Log tab and opens that workout's existing detail drawer.
  function _viewFullLinkHtml(workoutId) {
    if (!workoutId) return '';
    return '<button type="button" class="pl-viewfull" data-viewfull="' + workoutId + '">View full workout →</button>';
  }

  function _feelRowHtml(workoutId, current) {
    if (!workoutId) return '';
    var tagged = current === 'hard' || current === 'ok' || current === 'easy';
    var btns = _FEELINGS.map(function (f) {
      var on = current === f.key;
      // When tagged, hide the non-selected icons; when untagged, show all faint.
      var cls = 'pl-feel-btn' + (on ? ' is-on' : (tagged ? ' is-hidden' : ''));
      return '<button type="button" class="' + cls + '" data-feel="' + workoutId +
        '" data-feel-val="' + f.key + '" title="' + f.label + '" aria-label="' + f.label +
        (on ? '" aria-pressed="true' : '') + '">' + f.icon + '</button>';
    }).join('');
    return '<div class="pl-feelrow" data-feelrow="' + workoutId + '">' + btns + '</div>';
  }

  function _plannedCardHtml(p, day) {
    var fam = _famClass(p.session_type);
    var draggable = (p.status === 'planned' || p.status === 'missed');
    var clickable = (p.status !== 'needs_review');
    var handle = draggable ? '<span class="pl-dhandle">⠿⠿</span>' : '';
    var meta = p.actual && (p.status === 'done_auto' || p.status === 'done_manual')
      ? _plannedMeta(p) : _plannedMeta(p);
    var body = '';
    if (p.status === 'done_auto' || p.status === 'done_manual') {
      var actMeta = p.actual ? p.actual.meta : '';
      var mwid = p.matched_workout_id || (p.actual && p.actual.id) || '';
      var feel = p.actual ? p.actual.feeling : null;
      var diffLine = p.actual
        ? '<div class="pl-diffline">Planned ' + esc((_plannedMeta(p) || '').split('·')[0].trim() || p.session_type) +
          ' → Actual ' + esc(actMeta) + '</div>'
        : '<div class="pl-diffline pl-diffline--manual">Marked complete manually — no workout data attached</div>';
      body = diffLine +
        _viewFullLinkHtml(mwid) +
        _feelRowHtml(mwid, feel) +
        '<div class="pl-matchbtns">' +
          '<button class="pl-unlink" data-unlink="' + p.id + '">' + (mwid ? 'unlink match' : 'revert to planned') + '</button>' +
          '<button class="pl-pickbtn" data-pick="' + p.id + '" data-pick-mode="override">' + (mwid ? 'Change matched workout' : 'Attach a workout') + '</button>' +
        '</div>' +
        '<div class="pl-picker" data-pickerfor="' + p.id + '" hidden></div>';
    } else if (p.status === 'needs_review') {
      var day2 = day;
      var cands = _reviewCandidates(p, day2);
      body = '<div class="pl-candlist">' + cands.map(function (c, ci) {
          return '<label class="pl-candrow"><input type="radio" name="pl-cand-' + p.id + '" value="' + c.id + '"' + (ci === 0 ? ' checked' : '') + '/>' +
            '<span class="pl-cn">' + esc(c.name) + '</span><span class="pl-cm">' + esc(c.meta) + '</span></label>';
        }).join('') +
        '<div class="pl-candbtns">' +
          (cands.length ? '<button class="pl-btn pl-lime pl-tiny" data-confirm="' + p.id + '">Confirm match</button>' : '') +
          '<button class="pl-btn pl-ghost pl-tiny" data-missed="' + p.id + '">None → missed</button>' +
        '</div></div>';
    }
    return '<div class="pl-sess ' + fam + ' status-' + p.status + '"' +
        (draggable ? ' draggable="true"' : '') +
        ' data-sess="' + p.id + '"' + (clickable ? ' data-click="1"' : '') + '>' +
      handle +
      '<div class="pl-sesstop"><span class="pl-stypetag ' + fam + '">' + (fam === 'run' ? 'run' : 'lift') + '</span>' + _statusTag(p.status, !!p.actual) + '</div>' +
      '<div class="pl-sn">' + esc(p.name || '(untitled)') + '</div>' +
      '<div class="pl-sm">' + esc(meta) + '</div>' + body +
    '</div>';
  }

  // Candidate list for a needs_review card. Prefer the server-attached
  // `candidates` (the matcher's own ±1-day / type / ≤±40% pool — single source
  // of truth, and includes adjacent-day candidates). Fall back to same-day
  // ghosts if the field is absent.
  function _reviewCandidates(p, day) {
    if (Array.isArray(p.candidates)) {
      return p.candidates.map(function (c) { return { id: c.id, name: c.name, meta: c.meta }; });
    }
    var runLike = p.session_type === 'run';
    return (day.unplanned || []).filter(function (u) {
      var isRun = (u.workout_type || '').toLowerCase() === 'run';
      return runLike ? isRun : !isRun;
    }).map(function (u) { return { id: u.id, name: u.name, meta: u.meta }; });
  }

  function _ghostCardHtml(u, day) {
    // Match candidates span the whole loaded week, not just the ghost's own
    // day — a Tuesday run should still be matchable to a Friday-planned run,
    // and a day whose only planned session is already taken (e.g. strength)
    // shouldn't leave a same-day-only run with nothing to map to.
    var allDays = (_bundle && _bundle.days) || [day];
    var opts = allDays.reduce(function (acc, d) {
      return acc.concat((d.planned || []).filter(function (p) {
        return p.status !== 'done_auto' && p.status !== 'done_manual' && p.session_type !== 'rest';
      }).map(function (p) {
        var label = (p.name || '(untitled)') + (d.date !== u.date ? ' — ' + d.dow + ' ' + _parseISO(d.date).getDate() : '');
        return '<option value="' + p.id + '">' + esc(label) + '</option>';
      }));
    }, []).join('');
    var mapper = opts
      ? '<select class="pl-ghostsel" data-ghostsel="' + u.id + '"><option value="">Map to…</option>' + opts + '</select>' +
        '<div class="pl-candbtns"><button class="pl-btn pl-ghost pl-tiny" data-map="' + u.id + '">Map</button><button class="pl-btn pl-ghost pl-tiny" data-ignore="' + u.id + '">Ignore</button></div>'
      : '<div class="pl-candbtns"><button class="pl-btn pl-ghost pl-tiny" data-ignore="' + u.id + '">Ignore</button></div>';
    return '<div class="pl-ghost"><div class="pl-gtop"><span class="pl-gtag">UNPLANNED</span></div>' +
      '<div class="pl-sn" style="font-style:italic;">' + esc(u.name) + '</div><div class="pl-sm">' + esc(u.meta) + '</div>' + mapper +
    '</div>';
  }

  // ── Week event wiring (delegated) ───────────────────────────────────────────
  var _dragCtx = null;
  function _wireWeekEvents() {
    var host = document.getElementById('plan-week-list');
    if (!host) return;

    host.querySelectorAll('.pl-sess[data-click="1"]').forEach(function (el) {
      el.addEventListener('click', function () { _openDetailById(el.getAttribute('data-sess')); });
    });
    host.querySelectorAll('[data-unlink]').forEach(function (b) {
      b.addEventListener('click', function (e) { e.stopPropagation(); _mutate('POST', '/api/planned-sessions/' + b.getAttribute('data-unlink') + '/unmatch'); });
    });
    host.querySelectorAll('[data-confirm]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var id = b.getAttribute('data-confirm');
        var checked = host.querySelector('input[name="pl-cand-' + id + '"]:checked');
        if (!checked) { _toast('Pick a candidate first', true); return; }
        _mutate('POST', '/api/planned-sessions/' + id + '/match', { workout_id: checked.value });
      });
    });
    host.querySelectorAll('[data-missed]').forEach(function (b) {
      b.addEventListener('click', function (e) { e.stopPropagation(); _mutate('POST', '/api/planned-sessions/' + b.getAttribute('data-missed') + '/miss'); });
    });
    host.querySelectorAll('[data-feel]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var wid = b.getAttribute('data-feel');
        var val = b.getAttribute('data-feel-val');
        // Overwrite immediately, no confirm. Reload the week so the card
        // re-renders from the server (matched actual carries the new feeling).
        _api('PATCH', '/api/workouts/' + wid, { feeling: val })
          .then(function () { _loadWeek(); })
          .catch(function (err) { _toast(err.message || 'Could not save feeling', true); });
      });
    });
    host.querySelectorAll('[data-pick]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        _togglePicker(host, b.getAttribute('data-pick'), b.getAttribute('data-pick-mode'));
      });
    });
    host.querySelectorAll('[data-viewfull]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        // Hand off to the Log tab's deep-link path (inline script listener).
        document.dispatchEvent(new CustomEvent('plan:view-workout', {
          detail: { workoutId: b.getAttribute('data-viewfull') }
        }));
      });
    });
    host.querySelectorAll('[data-map]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var gid = b.getAttribute('data-map');
        var sel = host.querySelector('[data-ghostsel="' + gid + '"]');
        var target = sel ? sel.value : '';
        if (!target) { _toast('Choose a session to map to', true); return; }
        _mutate('POST', '/api/planned-sessions/' + target + '/match', { workout_id: gid });
      });
    });
    host.querySelectorAll('[data-ignore]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        _dismissedGhosts[b.getAttribute('data-ignore')] = true;
        _renderWeekList();
      });
    });
    host.querySelectorAll('.pl-addday[data-add-date]').forEach(function (el) {
      el.addEventListener('click', function () { _openAdd('single', el.getAttribute('data-add-date')); });
    });

    // Drag & drop reschedule (planned/missed only).
    host.querySelectorAll('.pl-sess[draggable="true"]').forEach(function (el) {
      el.addEventListener('dragstart', function (e) {
        _dragCtx = el.getAttribute('data-sess');
        el.classList.add('dragging');
        e.dataTransfer.effectAllowed = 'move';
        try { e.dataTransfer.setData('text/plain', _dragCtx); } catch (_) {}
      });
      el.addEventListener('dragend', function () { el.classList.remove('dragging'); });
    });
    host.querySelectorAll('.pl-dayrow').forEach(function (row) {
      row.addEventListener('dragover', function (e) { e.preventDefault(); row.classList.add('dragover'); });
      row.addEventListener('dragleave', function () { row.classList.remove('dragover'); });
      row.addEventListener('drop', function (e) {
        e.preventDefault(); row.classList.remove('dragover');
        if (!_dragCtx) return;
        var newDate = row.getAttribute('data-date');
        _mutate('PATCH', '/api/planned-sessions/' + _dragCtx, { planned_date: newDate });
        _dragCtx = null;
      });
    });
  }

  // Detail-panel event wiring — attach/mark-done/mark-missed, and the same
  // 24h picker used in the week pane (see _togglePicker below).
  function _wireDetailEvents(host) {
    host.querySelectorAll('[data-pick]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        _togglePicker(host, b.getAttribute('data-pick'), b.getAttribute('data-pick-mode'));
      });
    });
    host.querySelectorAll('[data-missed]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        _mutate('POST', '/api/planned-sessions/' + b.getAttribute('data-missed') + '/miss');
      });
    });
    host.querySelectorAll('[data-markdone]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        _mutate('POST', '/api/planned-sessions/' + b.getAttribute('data-markdone') + '/mark-done');
      });
    });
    host.querySelectorAll('[data-unlink]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        _mutate('POST', '/api/planned-sessions/' + b.getAttribute('data-unlink') + '/unmatch');
      });
    });
  }

  // Run a mutation then reload the week from the server.
  function _mutate(method, url, body) {
    _api(method, url, body)
      .then(function () { _loadWeek(); })
      .catch(function (err) { _toast(err.message || 'Update failed', true); });
  }

  // ── 24h workout history picker (attach / override) ──────────────────────────
  function _togglePicker(host, sessId, mode) {
    var box = host.querySelector('.pl-picker[data-pickerfor="' + sessId + '"]');
    if (!box) return;
    if (!box.hidden) { box.hidden = true; box.innerHTML = ''; return; }
    // Close any other open picker first.
    host.querySelectorAll('.pl-picker').forEach(function (b) { if (b !== box) { b.hidden = true; b.innerHTML = ''; } });
    box.hidden = false;
    box.innerHTML = '<div class="pl-loading">Loading recent workouts…</div>';
    _api('GET', '/api/workouts/recent?hours=24')
      .then(function (list) { _renderPickerList(box, sessId, mode, list || []); })
      .catch(function () { box.innerHTML = '<div class="pl-loading">Could not load recent workouts.</div>'; });
  }

  function _pickWhen(w) {
    var iso = w.created_at || w.start_time;
    if (!iso) return '';
    var d = new Date(iso);
    if (isNaN(d.getTime())) return '';
    var hh = d.getHours(), mm = d.getMinutes();
    return DOW[(d.getDay() + 6) % 7].charAt(0) + DOW[(d.getDay() + 6) % 7].slice(1, 3).toLowerCase() +
      ' ' + (hh < 10 ? '0' : '') + hh + ':' + (mm < 10 ? '0' : '') + mm;
  }

  function _renderPickerList(box, sessId, mode, list) {
    if (!list.length) {
      box.innerHTML = '<div class="pl-picker-empty">No workouts logged in the last 24 hours.</div>';
      return;
    }
    var rows = list.map(function (w) {
      var type = (w.workout_type || '').toLowerCase() === 'run' ? 'run' : 'lift';
      var metaBits = [_pickWhen(w)];
      if (w.meta) metaBits.push(w.meta);
      if (w.source === 'manual') metaBits.push('manual');
      return '<button type="button" class="pl-pickrow" data-pickrow="' + sessId + '" data-workout="' + w.id + '">' +
        '<span class="pl-pickrow-badge ' + type + '">' + type + '</span>' +
        '<span class="pl-pickrow-name">' + esc(w.name || '(untitled)') + '</span>' +
        '<span class="pl-pickrow-meta">' + esc(metaBits.filter(Boolean).join(' · ')) + '</span>' +
        '</button>';
    }).join('');
    box.innerHTML = '<div class="pl-pickerlist">' + rows + '</div>' +
      // Override needs a lightweight inline confirm before applying.
      (mode === 'override'
        ? '<div class="pl-pickconfirm" hidden><span>Replace the current match?</span>' +
          '<button type="button" class="pl-btn pl-lime pl-tiny" data-pickyes="' + sessId + '">Yes</button>' +
          '<button type="button" class="pl-btn pl-ghost pl-tiny" data-pickcancel="' + sessId + '">Cancel</button></div>'
        : '');

    var pending = { workoutId: null };
    box.querySelectorAll('[data-pickrow]').forEach(function (r) {
      r.addEventListener('click', function (e) {
        e.stopPropagation();
        var wid = r.getAttribute('data-workout');
        if (mode === 'override') {
          pending.workoutId = wid;
          box.querySelectorAll('.pl-pickrow').forEach(function (x) { x.classList.remove('is-sel'); });
          r.classList.add('is-sel');
          var conf = box.querySelector('.pl-pickconfirm');
          if (conf) conf.hidden = false;
        } else {
          _mutate('POST', '/api/planned-sessions/' + sessId + '/match', { workout_id: wid });
        }
      });
    });
    var yes = box.querySelector('[data-pickyes]');
    if (yes) yes.addEventListener('click', function (e) {
      e.stopPropagation();
      if (!pending.workoutId) return;
      _mutate('POST', '/api/planned-sessions/' + sessId + '/match', { workout_id: pending.workoutId });
    });
    var cancel = box.querySelector('[data-pickcancel]');
    if (cancel) cancel.addEventListener('click', function (e) {
      e.stopPropagation();
      pending.workoutId = null;
      box.querySelectorAll('.pl-pickrow').forEach(function (x) { x.classList.remove('is-sel'); });
      var conf = box.querySelector('.pl-pickconfirm');
      if (conf) conf.hidden = true;
    });
  }

  // ══ ADD / EDIT PANEL ════════════════════════════════════════════════════════
  function _openAdd(topMode, presetDate) {
    _panel.open = 'add';
    _addState.top = topMode; _addState.sub = 'form';
    _addState.editId = null; _addState.edit = null;
    _addState.presetDate = presetDate || _iso(_weekStart);
    // Fresh create: reset the builders to the demo templates so leftovers from
    // a previous edit don't leak into a new session.
    _sfBlocks = [
      { phase: 'warmup', duration_min: 10 },
      { phase: 'main', duration_min: 10, repeat: 3, rest_min: 2, target: '92% CP' },
      { phase: 'cooldown', duration_min: 8 }
    ];
    _sfExercises = [
      { name: 'Back squat', sets: 5, reps: 5, load: '78% 1RM' },
      { name: 'Romanian deadlift', sets: 4, reps: 8, load: 'moderate' }
    ];
    _sfStrengthMode = 'detailed'; _sfFocus = '';
    _renderAddSection(); _renderDetailSection();
    var el = document.getElementById('plan-add-section');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  // Edit an existing planned session in the same structured form the create
  // flow uses, seeded from the session and saved via PATCH. (The Edit button
  // used to open the CREATE flow with demo template data and POST a duplicate.)
  function _openEdit(p) {
    _panel.open = 'add';
    _addState.top = 'single'; _addState.sub = 'form';
    _addState.editId = p.id;
    _addState.edit = { name: p.name || '', notes: p.notes || '', type: p.session_type };
    _addState.presetDate = p.planned_date;
    var s = p.structure || {};
    if (p.session_type === 'run') {
      _sfBlocks = (Array.isArray(s.blocks) ? s.blocks : []).map(function (b) {
        return Object.assign({}, b);
      });
      if (!_sfBlocks.length) _sfBlocks = [{ phase: 'main', duration_min: 10 }];
    } else if (p.session_type === 'strength' || p.session_type === 'plyo') {
      if (Array.isArray(s.exercises) && s.exercises.length) {
        _sfStrengthMode = 'detailed';
        _sfExercises = s.exercises.map(function (x) { return Object.assign({}, x); });
      } else {
        _sfStrengthMode = 'simple';
        _sfFocus = s.focus || '';
        _sfExercises = [];
      }
    }
    _renderAddSection(); _renderDetailSection();
    var el = document.getElementById('plan-add-section');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function _closeAdd() { _panel.open = null; _addState.editId = null; _addState.edit = null; _renderAddSection(); }

  function _renderAddSection() {
    var host = document.getElementById('plan-add-section');
    if (!host) return;
    if (_panel.open !== 'add') { host.innerHTML = ''; return; }
    var editing = !!_addState.editId;
    host.innerHTML = '<div class="pl-card pl-panelcard">' +
      '<div class="pl-panelhead"><span class="pl-sectitle">' + (editing ? 'Edit session' : 'Add session(s)') + '</span><button class="pl-closepanel" id="pl-addclose">✕</button></div>' +
      // No single/bulk toggle while editing — bulk/JSON create flows would
      // silently turn the edit into a duplicate-creating POST (the old bug).
      (editing ? '' : '<div class="pl-modetoggle" id="pl-addmode"><button data-m="single">Single session</button><button data-m="bulk">Bulk-add a week</button></div>') +
      '<div id="pl-addbody"></div>' +
    '</div>';
    document.getElementById('pl-addclose').onclick = _closeAdd;
    _renderAddBody();
  }

  function _renderAddBody() {
    var editing = !!_addState.editId;
    var subs = _addState.top === 'single' ? [['form', 'Form'], ['json', 'JSON'], ['ai', 'Ask AI']]
      : [['form', 'Form'], ['json', 'JSON'], ['sep', 'Separator']];
    // Editing pins the structured Form — the JSON/Ask-AI sub-tabs are CREATE
    // affordances (paste or generate a fresh plan) and would duplicate
    // instead of update.
    var subHtml = editing ? '' : '<div class="pl-subtoggle" id="pl-addsub">' + subs.map(function (x) {
      return '<button class="' + (x[0] === _addState.sub ? 'on' : '') + '" data-sm="' + x[0] + '">' + x[1] + '</button>';
    }).join('') + '</div>';
    var content;
    if (_addState.top === 'single') {
      content = _addState.sub === 'form' ? _singleFormHtml() : (_addState.sub === 'json' ? _singleJSONHtml() : _singleAIHtml());
    } else {
      content = _addState.sub === 'form' ? _bulkFormHtml() : (_addState.sub === 'json' ? _bulkJSONHtml() : _bulkSepHtml());
    }
    document.getElementById('pl-addbody').innerHTML = subHtml + content;
    var modeEl0 = document.getElementById('pl-addmode');
    if (modeEl0) [].forEach.call(modeEl0.children, function (b) {
      b.classList.toggle('on', b.dataset.m === _addState.top);
    });
    _wireAddBody();
  }

  // ── Single Form (adaptive: run block builder vs strength exercise rows) ─────
  function _singleFormHtml() {
    var ed = _addState.edit || {};
    function sel(t) { return ed.type === t ? ' selected' : ''; }
    return '<div class="pl-frow">' +
        '<div class="pl-fld"><label>Date</label><input type="date" id="pl-sf-date" value="' + esc(_addState.presetDate) + '"/></div>' +
        '<div class="pl-fld"><label>Type</label><select id="pl-sf-type">' +
          '<option value="run"' + sel('run') + '>Run</option>' +
          '<option value="strength"' + sel('strength') + '>Strength</option>' +
          '<option value="plyo"' + sel('plyo') + '>Plyo</option>' +
          '<option value="rest"' + sel('rest') + '>Rest</option>' +
        '</select></div>' +
        '<div class="pl-fld"><label>Session name</label><input id="pl-sf-name" placeholder="Sustained Tempo" value="' + esc(ed.name || '') + '"/></div>' +
      '</div>' +
      '<div id="pl-sf-structure"></div>' +
      '<div class="pl-fld" style="margin-top:14px;"><label>Notes from coach</label><textarea id="pl-sf-notes" placeholder="e.g. hold 92% CP even on the 3rd rep">' + esc(ed.notes || '') + '</textarea></div>' +
      '<div class="pl-btnrow" style="margin-top:14px;"><button class="pl-btn pl-lime" id="pl-sf-save">' + (_addState.editId ? 'Save changes' : 'Save session') + '</button><button class="pl-btn pl-ghost" id="pl-sf-cancel">Cancel</button></div>';
  }

  // Run block builder rows
  var _sfBlocks = [
    { phase: 'warmup', duration_min: 10 },
    { phase: 'main', duration_min: 10, repeat: 3, rest_min: 2, target: '92% CP' },
    { phase: 'cooldown', duration_min: 8 }
  ];
  var _sfExercises = [
    { name: 'Back squat', sets: 5, reps: 5, load: '78% 1RM' },
    { name: 'Romanian deadlift', sets: 4, reps: 8, load: 'moderate' }
  ];
  var _sfStrengthMode = 'detailed'; // 'simple' | 'detailed' | 'json'
  var _sfFocus = ''; // seed for the simple-mode Focus input (edit prefill)

  function _renderStructureBuilder() {
    var host = document.getElementById('pl-sf-structure');
    if (!host) return;
    var type = document.getElementById('pl-sf-type').value;
    if (type === 'rest') { host.innerHTML = '<div class="pl-infobanner">Rest day — no structure.</div>'; return; }
    if (type === 'run') {
      host.innerHTML = '<div class="pl-infobanner" style="margin-bottom:14px;">Block template: <b>Warmup → Main set (repeatable) → Cooldown</b>, each with a Power or Pace target. Stryd doesn’t accept HR-based blocks, so skip HR here.</div>' +
        '<div class="pl-fld" style="margin-bottom:6px;"><label>Structure</label></div>' +
        '<div class="pl-blocklist" id="pl-blocklist">' + _sfBlocks.map(_blockRowHtml).join('') + '</div>' +
        '<button class="pl-addblock" id="pl-addblock">+ Add block</button>';
      _wireBlockBuilder();
    } else {
      // strength / plyo
      host.innerHTML = '<div class="pl-subtoggle" id="pl-strmode" style="margin-bottom:12px;">' +
          '<button class="' + (_sfStrengthMode === 'simple' ? 'on' : '') + '" data-str="simple">Simple</button>' +
          '<button class="' + (_sfStrengthMode === 'detailed' ? 'on' : '') + '" data-str="detailed">Detailed</button>' +
          '<button class="' + (_sfStrengthMode === 'json' ? 'on' : '') + '" data-str="json">JSON</button>' +
        '</div>' +
        (_sfStrengthMode === 'simple'
          ? '<div class="pl-fld"><label>Focus</label><input id="pl-str-focus" placeholder="Lower / posterior chain" value="' + esc(_sfFocus || '') + '"/></div>'
          : _sfStrengthMode === 'json'
          ? '<div class="pl-fld" style="margin-bottom:6px;"><label>Exercises (JSON)</label></div>' +
            '<textarea class="pl-jsonta" id="pl-exjson-ta" style="min-height:160px;">' + esc(JSON.stringify(_sfExercises, null, 2)) + '</textarea>' +
            '<div id="pl-exjson-err"></div>'
          : '<div class="pl-fld" style="margin-bottom:6px;"><label>Exercises</label></div>' +
            // RPE here is a blank-by-default TARGET the coach can optionally
            // set going in — distinct from the real logged RPE, which is
            // only known once the session is actually trained and shows up
            // on the matched workout's detail instead (see _liftDetailHtml).
            '<div class="pl-exhead"><span>Name</span><span>Sets</span><span>Reps</span><span>Load</span><span>RPE</span><span></span></div>' +
            '<div class="pl-blocklist" id="pl-exlist">' + _sfExercises.map(_exRowHtml).join('') + '</div>' +
            '<button class="pl-addblock" id="pl-addex">+ Add exercise</button>');
      _wireStrengthBuilder();
    }
  }

  function _blockRowHtml(b, i) {
    var cls = b.phase === 'warmup' ? 'warm' : (b.phase === 'main' ? 'main' : 'cool');
    var label = b.phase === 'warmup' ? 'Warmup' : (b.phase === 'main' ? 'Main set' : (b.phase === 'cooldown' ? 'Cooldown' : b.phase));
    return '<div class="pl-block" data-bi="' + i + '"><span class="pl-btag ' + cls + '">' + label + '</span>' +
      '<input class="pl-bdur" data-f="duration_min" value="' + esc(b.duration_min != null ? b.duration_min : '') + '" placeholder="min"/>' +
      '<input class="pl-btgt" data-f="repeat" value="' + esc(b.repeat != null ? b.repeat : '') + '" placeholder="×reps"/>' +
      '<input class="pl-btgt" data-f="target" value="' + esc(b.target || '') + '" placeholder="target"/>' +
      '<button class="pl-rm" data-rm-block="' + i + '">✕</button></div>';
  }
  function _exRowHtml(x, i) {
    return '<div class="pl-block" data-xi="' + i + '">' +
      '<input class="pl-exname" data-f="name" value="' + esc(x.name || '') + '" placeholder="Exercise"/>' +
      '<input class="pl-bdur" data-f="sets" value="' + esc(x.sets != null ? x.sets : '') + '" placeholder="sets"/>' +
      '<input class="pl-bdur" data-f="reps" value="' + esc(x.reps != null ? x.reps : '') + '" placeholder="reps"/>' +
      '<input class="pl-btgt" data-f="load" value="' + esc(x.load || '') + '" placeholder="load"/>' +
      // Target RPE for this exercise (blank until the coach sets one) — this
      // is the PLANNED target, separate from the real logged RPE that shows
      // on the matched workout's actual detail once trained.
      '<input class="pl-bdur" data-f="rpe" value="' + esc(x.rpe != null ? x.rpe : '') + '" placeholder="RPE"/>' +
      '<button class="pl-rm" data-rm-ex="' + i + '">✕</button></div>';
  }

  function _wireBlockBuilder() {
    var list = document.getElementById('pl-blocklist');
    if (!list) return;
    list.querySelectorAll('.pl-block').forEach(function (row) {
      var i = +row.getAttribute('data-bi');
      row.querySelectorAll('input[data-f]').forEach(function (inp) {
        inp.addEventListener('input', function () {
          var f = inp.getAttribute('data-f'), v = inp.value;
          if (f === 'duration_min' || f === 'repeat') v = v === '' ? undefined : Number(v);
          if (v === undefined) delete _sfBlocks[i][f]; else _sfBlocks[i][f] = v;
        });
      });
    });
    list.querySelectorAll('[data-rm-block]').forEach(function (b) {
      b.addEventListener('click', function () { _sfBlocks.splice(+b.getAttribute('data-rm-block'), 1); _renderStructureBuilder(); });
    });
    var add = document.getElementById('pl-addblock');
    if (add) add.onclick = function () { _sfBlocks.push({ phase: 'main', duration_min: 10 }); _renderStructureBuilder(); };
  }
  function _wireStrengthBuilder() {
    document.querySelectorAll('#pl-strmode button').forEach(function (b) {
      b.addEventListener('click', function () { _sfStrengthMode = b.getAttribute('data-str'); _renderStructureBuilder(); });
    });
    var focusInp = document.getElementById('pl-str-focus');
    if (focusInp) focusInp.addEventListener('input', function () { _sfFocus = focusInp.value; });
    var list = document.getElementById('pl-exlist');
    if (list) {
      list.querySelectorAll('.pl-block').forEach(function (row) {
        var i = +row.getAttribute('data-xi');
        row.querySelectorAll('input[data-f]').forEach(function (inp) {
          inp.addEventListener('input', function () {
            var f = inp.getAttribute('data-f'), v = inp.value;
            if (f === 'sets' || f === 'reps') v = v === '' ? undefined : Number(v);
            if (v === undefined) delete _sfExercises[i][f]; else _sfExercises[i][f] = v;
          });
        });
      });
      list.querySelectorAll('[data-rm-ex]').forEach(function (b) {
        b.addEventListener('click', function () { _sfExercises.splice(+b.getAttribute('data-rm-ex'), 1); _renderStructureBuilder(); });
      });
      var add = document.getElementById('pl-addex');
      if (add) add.onclick = function () { _sfExercises.push({ name: '', sets: 3, reps: 10, load: '', rpe: '' }); _renderStructureBuilder(); };
    }
    var jsonTa = document.getElementById('pl-exjson-ta');
    if (jsonTa) {
      jsonTa.addEventListener('input', function () {
        var err = document.getElementById('pl-exjson-err');
        try {
          var parsed = JSON.parse(jsonTa.value);
          if (!Array.isArray(parsed)) throw new Error('Must be a JSON array of exercises.');
          // Kept in sync live so Simple/Detailed/Save all read the same
          // _sfExercises array regardless of which mode last touched it —
          // last-valid-parse wins; invalid JSON is flagged but never clears it.
          _sfExercises = parsed;
          if (err) err.innerHTML = '';
        } catch (e) {
          if (err) err.innerHTML = '<div class="pl-previewbox err">Invalid JSON — ' + esc(e.message) + '</div>';
        }
      });
    }
  }

  function _collectSingleForm() {
    var type = document.getElementById('pl-sf-type').value;
    var out = {
      planned_date: document.getElementById('pl-sf-date').value,
      session_type: type,
      name: document.getElementById('pl-sf-name').value || null,
      notes: document.getElementById('pl-sf-notes').value || null,
      structure: null
    };
    if (type === 'run') {
      out.structure = { blocks: _sfBlocks.slice() };
    } else if (type === 'strength' || type === 'plyo') {
      if (_sfStrengthMode === 'simple') {
        var focusEl = document.getElementById('pl-str-focus');
        out.structure = { focus: focusEl ? focusEl.value : '' };
      } else {
        out.structure = { exercises: _sfExercises.slice() };
      }
    }
    return out;
  }

  function _wireAddBody() {
    // mode / sub toggles
    var modeEl = document.getElementById('pl-addmode');
    if (modeEl) modeEl.querySelectorAll('button').forEach(function (b) {
      b.addEventListener('click', function () { _addState.top = b.dataset.m; _addState.sub = 'form'; _renderAddBody(); });
    });
    var subEl = document.getElementById('pl-addsub');
    if (subEl) subEl.querySelectorAll('button').forEach(function (b) {
      b.addEventListener('click', function () { _addState.sub = b.dataset.sm; _renderAddBody(); });
    });

    if (_addState.top === 'single' && _addState.sub === 'form') {
      _renderStructureBuilder();
      document.getElementById('pl-sf-type').addEventListener('change', _renderStructureBuilder);
      document.getElementById('pl-sf-cancel').onclick = _closeAdd;
      document.getElementById('pl-sf-save').onclick = function () {
        var payload = _collectSingleForm();
        if (!payload.planned_date || !payload.session_type) { _toast('Date and type are required', true); return; }
        // Editing PATCHes the existing session; creating POSTs a new one.
        var editId = _addState.editId;
        var req = editId
          ? _api('PATCH', '/api/planned-sessions/' + editId, payload)
          : _api('POST', '/api/planned-sessions', payload);
        req
          .then(function () { _toast(editId ? 'Session updated' : 'Session saved'); _closeAdd(); _loadWeek(); })
          .catch(function (e) { _toast(e.message || 'Save failed', true); });
      };
    } else if (_addState.top === 'single' && _addState.sub === 'json') {
      _wireSingleJSON();
    } else if (_addState.top === 'single' && _addState.sub === 'ai') {
      _wireSingleAI();
    } else if (_addState.top === 'bulk' && _addState.sub === 'form') {
      _wireBulkForm();
    } else if (_addState.top === 'bulk' && _addState.sub === 'json') {
      _wireBulkJSON();
    } else if (_addState.top === 'bulk' && _addState.sub === 'sep') {
      _wireBulkSep();
    }
  }

  // ── JSON templates ──────────────────────────────────────────────────────────
  var tplSingleRun = {
    date: '2026-07-03', type: 'run', name: 'Sustained Tempo',
    notes: 'Hold 92% CP even on the 3rd rep — don’t fade.',
    blocks: [
      { phase: 'warmup', duration_min: 10 },
      { phase: 'main', duration_min: 10, repeat: 3, rest_min: 2, target: '92% CP' },
      { phase: 'cooldown', duration_min: 8 }
    ]
  };
  var tplSingleStrength = {
    date: '2026-07-02', type: 'strength', name: 'Lower body strength',
    notes: 'Keep in the 6-12wk economy window.',
    exercises: [
      { name: 'Back squat', sets: 5, reps: 5, load: '78% 1RM' },
      { name: 'Romanian deadlift', sets: 4, reps: 8, load: 'moderate' }
    ]
  };
  var tplBulkWeek = [
    { date: '2026-06-29', type: 'rest' },
    { date: '2026-06-30', type: 'run', name: 'Easy + strides', blocks: [{ phase: 'main', duration_min: 45, target: 'Z2' }] },
    { date: '2026-07-01', type: 'run', name: 'Sustained Tempo', notes: tplSingleRun.notes, blocks: tplSingleRun.blocks },
    { date: '2026-07-02', type: 'strength', name: 'Lower body strength', notes: tplSingleStrength.notes, exercises: tplSingleStrength.exercises },
    { date: '2026-07-03', type: 'run', name: 'Recovery jog', blocks: [{ phase: 'main', duration_min: 30, target: 'easy' }] },
    { date: '2026-07-04', type: 'run', name: 'Long run', blocks: [{ phase: 'main', duration_min: 110, target: 'Z2, last 20min @ MP' }] },
    { date: '2026-07-05', type: 'rest' }
  ];

  // Map a template object {date,type,name,notes,blocks|exercises} → API payload.
  function _tplToPayload(o) {
    var p = { planned_date: o.date, session_type: (o.type || '').toLowerCase(), name: o.name || null, notes: o.notes || null, structure: null };
    if (o.blocks) p.structure = { blocks: o.blocks };
    else if (o.exercises) p.structure = { exercises: o.exercises };
    else if (o.focus) p.structure = { focus: o.focus };
    return p;
  }

  function _downloadFile(name, content, mime) {
    var blob = new Blob([content], { type: mime || 'application/json' });
    var url = URL.createObjectURL(blob);
    var a = document.createElement('a'); a.href = url; a.download = name;
    document.body.appendChild(a); a.click();
    setTimeout(function () { document.body.removeChild(a); URL.revokeObjectURL(url); }, 100);
  }

  function _singleJSONHtml() {
    return '<div class="pl-jsontools">' +
        '<button class="pl-btn pl-ghost" id="pl-sj-dl">⬇ Download template</button>' +
        '<label class="pl-uploadlbl">Upload .json<input type="file" accept=".json" id="pl-sj-up" style="display:none"/></label>' +
      '</div>' +
      '<div class="pl-infobanner" style="margin-bottom:10px;">Paste a session as JSON — same shape as the template.</div>' +
      '<textarea class="pl-jsonta" id="pl-sj-ta">' + esc(JSON.stringify(tplSingleRun, null, 2)) + '</textarea>' +
      '<div class="pl-btnrow" style="margin-top:10px;"><button class="pl-btn pl-ghost" id="pl-sj-val">Validate &amp; preview</button></div>' +
      '<div id="pl-sj-prev"></div>' +
      '<div class="pl-btnrow" style="margin-top:14px;"><button class="pl-btn pl-lime" id="pl-sj-save">Save session</button><button class="pl-btn pl-ghost" id="pl-sj-cancel">Cancel</button></div>';
  }
  function _wireSingleJSON() {
    document.getElementById('pl-sj-dl').onclick = function () { _downloadFile('perf-coach-session-template.json', JSON.stringify(tplSingleRun, null, 2)); };
    document.getElementById('pl-sj-up').onchange = function () { _readFileInto(this, 'pl-sj-ta'); };
    document.getElementById('pl-sj-cancel').onclick = _closeAdd;
    document.getElementById('pl-sj-val').onclick = function () { _previewSingleJSON(); };
    document.getElementById('pl-sj-save').onclick = function () {
      var obj = _previewSingleJSON();
      if (!obj) return;
      _api('POST', '/api/planned-sessions', _tplToPayload(obj))
        .then(function () { _toast('Session saved'); _closeAdd(); _loadWeek(); })
        .catch(function (e) { _toast(e.message || 'Save failed', true); });
    };
  }
  function _previewSingleJSON() {
    var ta = document.getElementById('pl-sj-ta'), out = document.getElementById('pl-sj-prev');
    try {
      var obj = JSON.parse(ta.value);
      if (!obj.date || !obj.type) throw new Error('Missing required field: date and type are required.');
      var parts = [obj.date + ' · ' + String(obj.type).toUpperCase() + ' · ' + (obj.name || '(untitled)')];
      if (obj.blocks) parts.push(obj.blocks.length + ' block(s)');
      if (obj.exercises) parts.push(obj.exercises.length + ' exercise(s)');
      out.innerHTML = '<div class="pl-previewbox ok">Valid — ' + esc(parts.join(' · ')) + '</div>';
      return obj;
    } catch (e) { out.innerHTML = '<div class="pl-previewbox err">Invalid JSON — ' + esc(e.message) + '</div>'; return null; }
  }

  // ── Single session — Ask AI (generate one day from date/type/note) ──────────
  // Shares the backend's single-session generator with the suggestion-row
  // "Refine" action below — same endpoint, same session shape, this side just
  // starts from a blank date/type instead of an existing suggestion.
  var _aiSessionResult = null; // the last generated session, pending Save

  function _singleAIHtml() {
    _aiSessionResult = null;
    return '<div class="pl-frow">' +
        '<div class="pl-fld"><label>Date</label><input type="date" id="pl-ai-date" value="' + esc(_addState.presetDate) + '"/></div>' +
        '<div class="pl-fld"><label>Type</label><select id="pl-ai-type">' +
          '<option value="run">Run</option><option value="strength">Strength</option>' +
          '<option value="plyo">Plyo</option><option value="rest">Rest</option>' +
        '</select></div>' +
      '</div>' +
      '<div class="pl-fld" style="margin-top:10px;"><label>Note to the coach (optional)</label>' +
        '<textarea id="pl-ai-note" placeholder="e.g. focus on hip mobility, keep it under 30 minutes"></textarea></div>' +
      '<div class="pl-btnrow" style="margin-top:10px;"><button class="pl-btn pl-ghost" id="pl-ai-gen">✨ Generate</button></div>' +
      '<div id="pl-ai-prev"></div>' +
      '<div class="pl-btnrow" style="margin-top:14px;"><button class="pl-btn pl-lime" id="pl-ai-save" disabled>Save session</button><button class="pl-btn pl-ghost" id="pl-ai-cancel">Cancel</button></div>';
  }

  // Local, read-only preview rows — _sugExercisesHtml/_sugBlocksHtml live in
  // the separate Plan Suggestions closure below and aren't reachable here.
  function _aiPreviewExRow(x) {
    var sr = (x.sets != null && x.reps != null) ? (x.sets + ' × ' + x.reps) : (x.sets != null ? x.sets + ' sets' : '');
    return '<div class="pl-exd"><span class="pl-en">' + esc(x.name || 'Exercise') + '</span>' +
      '<span class="pl-sr">' + esc(sr) + '</span>' +
      '<span class="pl-es" style="color:var(--pl-faint)">' + esc(x.load || '') + '</span></div>';
  }
  function _aiPreviewBlockRow(b) {
    var dur = b.duration_min != null ? b.duration_min + ' min' : '';
    var main = (b.repeat && b.repeat > 1) ? (b.repeat + ' × ' + dur) : dur;
    return '<div class="pl-exd"><span class="pl-en">' + esc(_phaseLabel(b.phase)) + '</span>' +
      '<span class="pl-sr">' + esc(main) + '</span>' +
      '<span class="pl-es" style="color:var(--pl-faint)">' + esc(b.target || '') + '</span></div>';
  }

  function _aiSessionPreviewHtml(s) {
    var tssStr = s.target_tss > 0 ? s.target_tss + ' TSS' : '';
    var durStr = s.duration_minutes > 0 ? s.duration_minutes + 'min' : '';
    var meta = [tssStr, durStr].filter(Boolean).join(' · ');
    var body = '';
    if (Array.isArray(s.exercises) && s.exercises.length) {
      body = '<div class="pl-blocklist" style="margin-top:8px;">' + s.exercises.map(_aiPreviewExRow).join('') + '</div>';
    } else if (Array.isArray(s.blocks) && s.blocks.length) {
      body = '<div class="pl-blocklist" style="margin-top:8px;">' + s.blocks.map(_aiPreviewBlockRow).join('') + '</div>';
    }
    return '<div class="pl-previewbox ok">' +
        '<b>' + esc((s.workout_type || '').toUpperCase()) + '</b>' + (meta ? ' · ' + esc(meta) : '') +
        (s.intent ? ' · ' + esc(s.intent) : '') +
      '</div>' +
      (s.notes ? '<div class="pl-infobanner" style="margin-top:6px;">' + esc(s.notes) + '</div>' : '') +
      body;
  }

  function _aiSessionToPayload(dateIso, s) {
    var body = { planned_date: dateIso, session_type: s.workout_type, name: s.intent ? s.intent.substring(0, 80) : null, notes: s.notes || null, structure: null };
    if (Array.isArray(s.exercises) && s.exercises.length) body.structure = { exercises: s.exercises };
    else if (Array.isArray(s.blocks) && s.blocks.length) body.structure = { blocks: s.blocks };
    return body;
  }

  function _wireSingleAI() {
    document.getElementById('pl-ai-cancel').onclick = _closeAdd;
    var genBtn = document.getElementById('pl-ai-gen');
    var saveBtn = document.getElementById('pl-ai-save');
    genBtn.onclick = function () {
      var dateEl = document.getElementById('pl-ai-date');
      if (!dateEl.value) { _toast('Pick a date first', true); return; }
      genBtn.disabled = true; genBtn.textContent = 'Generating…';
      saveBtn.disabled = true;
      _api('POST', '/api/plan/suggestions/session', {
        date: dateEl.value,
        workout_type: document.getElementById('pl-ai-type').value,
        note: document.getElementById('pl-ai-note').value || null,
      })
        .then(function (data) {
          _aiSessionResult = data.session;
          document.getElementById('pl-ai-prev').innerHTML = _aiSessionPreviewHtml(_aiSessionResult);
          saveBtn.disabled = false;
        })
        .catch(function (e) {
          document.getElementById('pl-ai-prev').innerHTML = '<div class="pl-previewbox err">' + esc(e.message || 'Could not generate a session — try again.') + '</div>';
        })
        .finally(function () { genBtn.disabled = false; genBtn.textContent = '✨ Generate'; });
    };
    saveBtn.onclick = function () {
      if (!_aiSessionResult) return;
      var dateEl = document.getElementById('pl-ai-date');
      _api('POST', '/api/planned-sessions', _aiSessionToPayload(dateEl.value, _aiSessionResult))
        .then(function () { _toast('Session saved'); _closeAdd(); _loadWeek(); })
        .catch(function (e) { _toast(e.message || 'Save failed', true); });
    };
  }

  function _bulkFormHtml() {
    var rows = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'].map(function (d, i) {
      return '<tr data-bulk-i="' + i + '"><td class="pl-bd">' + d + '</td>' +
        '<td><select data-bf="type"><option value="rest">Rest</option><option value="run">Run</option><option value="strength">Strength</option><option value="plyo">Plyo</option></select></td>' +
        '<td><input data-bf="name" placeholder="session name"/></td>' +
        '<td><input data-bf="duration" placeholder="—"/></td></tr>';
    }).join('');
    return '<div class="pl-infobanner" style="margin-bottom:14px;">Quickly stub out the whole week. Open any session afterward to add block/exercise detail.</div>' +
      '<table class="pl-bulktbl"><thead><tr><th></th><th>Type</th><th>Session name</th><th>Duration</th></tr></thead><tbody>' + rows + '</tbody></table>' +
      '<div class="pl-btnrow" style="margin-top:14px;"><button class="pl-btn pl-lime" id="pl-bf-save">Save week</button><button class="pl-btn pl-ghost" id="pl-bf-cancel">Cancel</button></div>';
  }
  function _wireBulkForm() {
    document.getElementById('pl-bf-cancel').onclick = _closeAdd;
    document.getElementById('pl-bf-save').onclick = function () {
      var payloads = [];
      document.querySelectorAll('#pl-addbody tr[data-bulk-i]').forEach(function (tr) {
        var i = +tr.getAttribute('data-bulk-i');
        var type = tr.querySelector('[data-bf="type"]').value;
        var name = tr.querySelector('[data-bf="name"]').value;
        var dur = tr.querySelector('[data-bf="duration"]').value;
        if (type === 'rest' && !name) { payloads.push({ planned_date: _iso(_addDays(_weekStart, i)), session_type: 'rest' }); return; }
        var structure = null;
        var m = /(\d+)/.exec(dur || '');
        if (type === 'run' && m) structure = { blocks: [{ phase: 'main', duration_min: Number(m[1]) }] };
        payloads.push({ planned_date: _iso(_addDays(_weekStart, i)), session_type: type, name: name || null, structure: structure });
      });
      _api('POST', '/api/planned-sessions/bulk', payloads)
        .then(function () { _toast('Week saved'); _closeAdd(); _loadWeek(); })
        .catch(function (e) { _toast(e.message || 'Save failed', true); });
    };
  }

  function _bulkJSONHtml() {
    return '<div class="pl-jsontools">' +
        '<button class="pl-btn pl-ghost" id="pl-bj-dl">⬇ Download template</button>' +
        '<button class="pl-btn pl-ghost" id="pl-bj-dlprompt" title="Download the blank weekly-plan kickoff prompt">⬇ Download planning prompt</button>' +
        '<label class="pl-uploadlbl">Upload .json<input type="file" accept=".json" id="pl-bj-up" style="display:none"/></label>' +
      '</div>' +
      '<div class="pl-infobanner" style="margin-bottom:10px;">Paste an array of sessions — one file for the whole week, full block/exercise detail.</div>' +
      '<textarea class="pl-jsonta" id="pl-bj-ta">' + esc(JSON.stringify(tplBulkWeek, null, 2)) + '</textarea>' +
      '<div class="pl-btnrow" style="margin-top:10px;"><button class="pl-btn pl-ghost" id="pl-bj-val">Validate &amp; preview</button></div>' +
      '<div id="pl-bj-prev"></div>' +
      '<div class="pl-btnrow" style="margin-top:14px;"><button class="pl-btn pl-lime" id="pl-bj-save">Save week</button><button class="pl-btn pl-ghost" id="pl-bj-cancel">Cancel</button></div>';
  }
  function _wireBulkJSON() {
    document.getElementById('pl-bj-dl').onclick = function () { _downloadFile('perf-coach-week-template.json', JSON.stringify(tplBulkWeek, null, 2)); };
    document.getElementById('pl-bj-dlprompt').onclick = function () {
      _downloadFile('weekly-plan-kickoff-prompt.md', KICKOFF_PROMPT_TEMPLATE, 'text/markdown');
    };
    document.getElementById('pl-bj-up').onchange = function () { _readFileInto(this, 'pl-bj-ta'); };
    document.getElementById('pl-bj-cancel').onclick = _closeAdd;
    document.getElementById('pl-bj-val').onclick = function () { _previewBulkJSON(); };
    document.getElementById('pl-bj-save').onclick = function () {
      var arr = _previewBulkJSON();
      if (!arr) return;
      _api('POST', '/api/planned-sessions/bulk', arr.map(_tplToPayload))
        .then(function () { _toast('Week saved'); _closeAdd(); _loadWeek(); })
        .catch(function (e) { _toast(e.message || 'Save failed', true); });
    };
  }
  function _previewBulkJSON() {
    var ta = document.getElementById('pl-bj-ta'), out = document.getElementById('pl-bj-prev');
    try {
      var arr = JSON.parse(ta.value);
      if (!Array.isArray(arr)) throw new Error('Expected a JSON array of sessions.');
      var rows = arr.map(function (o) {
        var det = o.blocks ? o.blocks.length + ' blocks' : (o.exercises ? o.exercises.length + ' exercises' : '—');
        return '<div class="pl-previewrow"><span style="width:92px">' + esc(o.date || '?') + '</span><span style="width:72px">' + esc(o.type || '?') + '</span><span style="flex:1">' + esc(o.name || '') + '</span><span style="color:var(--pl-faint)">' + esc(det) + '</span></div>';
      }).join('');
      out.innerHTML = '<div class="pl-previewbox ok">' + arr.length + ' sessions parsed<div class="pl-previewlist">' + rows + '</div></div>';
      return arr;
    } catch (e) { out.innerHTML = '<div class="pl-previewbox err">Invalid JSON — ' + esc(e.message) + '</div>'; return null; }
  }

  function _delimChar(code) { return code === 'comma' ? ',' : (code === 'tab' ? '\t' : '|'); }
  function _sepTemplate(code) {
    var d = _delimChar(code);
    return [
      ['date', 'type', 'name', 'duration', 'notes'],
      ['2026-06-29', 'rest', '', '', ''],
      ['2026-06-30', 'run', 'Easy + strides', '45min', ''],
      ['2026-07-01', 'run', 'Sustained Tempo', '60min', 'Hold 92% CP'],
      ['2026-07-02', 'strength', 'Lower body strength', '50min', ''],
      ['2026-07-03', 'run', 'Recovery jog', '30min', ''],
      ['2026-07-04', 'run', 'Long run', '110min', 'last 20min @ MP'],
      ['2026-07-05', 'rest', '', '', '']
    ].map(function (r) { return r.join(d); }).join('\n');
  }
  function _bulkSepHtml() {
    var code = _addState.delim, dc = _delimChar(code);
    return '<div class="pl-jsontools">' +
        '<span style="font-size:11px;font-weight:700;color:var(--pl-muted);">Delimiter:</span>' +
        '<select class="pl-delimsel" id="pl-delim">' +
          '<option value="pipe"' + (code === 'pipe' ? ' selected' : '') + '>Pipe  |</option>' +
          '<option value="comma"' + (code === 'comma' ? ' selected' : '') + '>Comma  ,</option>' +
          '<option value="tab"' + (code === 'tab' ? ' selected' : '') + '>Tab</option>' +
        '</select>' +
        '<button class="pl-btn pl-ghost" id="pl-sep-dl">⬇ Download template</button>' +
      '</div>' +
      '<div class="pl-infobanner" style="margin-bottom:10px;">One session per line: <b>date' + dc + 'type' + dc + 'name' + dc + 'duration' + dc + 'notes</b>. Simple fields only; open a session afterward for block/exercise detail.</div>' +
      '<textarea class="pl-jsonta" id="pl-sep-ta">' + esc(_sepTemplate(code)) + '</textarea>' +
      '<div class="pl-btnrow" style="margin-top:10px;"><button class="pl-btn pl-ghost" id="pl-sep-val">Parse &amp; preview</button></div>' +
      '<div id="pl-sep-prev"></div>' +
      '<div class="pl-btnrow" style="margin-top:14px;"><button class="pl-btn pl-lime" id="pl-sep-save">Save week</button><button class="pl-btn pl-ghost" id="pl-sep-cancel">Cancel</button></div>';
  }
  function _parseSep() {
    var ta = document.getElementById('pl-sep-ta'), out = document.getElementById('pl-sep-prev'), d = _delimChar(_addState.delim);
    var lines = ta.value.split('\n').map(function (l) { return l.trim(); }).filter(function (l) { return l.length; });
    if (lines.length < 2) { out.innerHTML = '<div class="pl-previewbox err">No data rows found below the header.</div>'; return null; }
    var rows = lines.slice(1).map(function (l) {
      var c = l.split(d);
      return { date: (c[0] || '').trim(), type: (c[1] || '').trim().toLowerCase(), name: (c[2] || '').trim(), duration: (c[3] || '').trim(), notes: (c[4] || '').trim() };
    });
    var html = rows.map(function (r) {
      return '<div class="pl-previewrow"><span style="width:92px">' + esc(r.date || '?') + '</span><span style="width:72px">' + esc(r.type || '?') + '</span><span style="flex:1">' + esc(r.name || '—') + '</span><span style="color:var(--pl-faint)">' + esc(r.duration || '—') + '</span></div>';
    }).join('');
    out.innerHTML = '<div class="pl-previewbox ok">' + rows.length + ' sessions parsed<div class="pl-previewlist">' + html + '</div></div>';
    return rows;
  }
  function _wireBulkSep() {
    document.getElementById('pl-delim').onchange = function () { _addState.delim = this.value; _renderAddBody(); };
    document.getElementById('pl-sep-dl').onclick = function () { _downloadFile('perf-coach-week-template.csv', _sepTemplate(_addState.delim), 'text/csv'); };
    document.getElementById('pl-sep-cancel').onclick = _closeAdd;
    document.getElementById('pl-sep-val').onclick = function () { _parseSep(); };
    document.getElementById('pl-sep-save').onclick = function () {
      var rows = _parseSep();
      if (!rows) return;
      var payloads = rows.map(function (r) {
        var structure = null, m = /(\d+)/.exec(r.duration || '');
        if (r.type === 'run' && m) structure = { blocks: [{ phase: 'main', duration_min: Number(m[1]) }] };
        return { planned_date: r.date, session_type: r.type, name: r.name || null, notes: r.notes || null, structure: structure };
      });
      _api('POST', '/api/planned-sessions/bulk', payloads)
        .then(function () { _toast('Week saved'); _closeAdd(); _loadWeek(); })
        .catch(function (e) { _toast(e.message || 'Save failed', true); });
    };
  }

  function _readFileInto(input, targetId) {
    var f = input.files[0]; if (!f) return;
    var reader = new FileReader();
    reader.onload = function (e) { var t = document.getElementById(targetId); if (t) t.value = e.target.result; };
    reader.readAsText(f);
  }

  // ══ DETAIL PANEL ══════════════════════════════════════════════════════════════
  function _openDetailById(id) {
    var found = null;
    (_bundle.days || []).forEach(function (d) {
      (d.planned || []).forEach(function (p) { if (p.id === id) found = p; });
    });
    if (!found) return;
    _detail = found;
    _panel.open = 'detail';
    _renderDetailSection(); _renderAddSection();
    var el = document.getElementById('plan-detail-section');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  function _closeDetail() { _panel.open = null; _detail = null; _renderDetailSection(); }

  function _renderDetailSection() {
    var host = document.getElementById('plan-detail-section');
    if (!host) return;
    if (_panel.open !== 'detail' || !_detail) { host.innerHTML = ''; return; }
    var p = _detail;
    var isRun = p.session_type === 'run';
    host.innerHTML = '<div class="pl-card pl-panelcard">' +
      '<div class="pl-panelhead" style="margin-bottom:2px;"><span class="pl-sectitle">Session detail</span><button class="pl-closepanel" id="pl-detclose">✕</button></div>' +
      (isRun ? _runDetailHtml(p) : _liftDetailHtml(p)) +
    '</div>';
    document.getElementById('pl-detclose').onclick = _closeDetail;
    var editBtn = document.getElementById('pl-det-edit');
    if (editBtn) editBtn.onclick = function () {
      // Once matched, the planned template is history — what's actually
      // editable is the real logged workout. Redirect to it instead of
      // opening the (now-stale) plan structure editor, so Plan/Log/Detail
      // stay one source of truth rather than two that can drift apart.
      if (p.actual && p.actual.id) {
        document.dispatchEvent(new CustomEvent('plan:view-workout', {
          detail: { workoutId: p.actual.id }
        }));
        return;
      }
      _openEdit(p);
    };
    var delBtn = document.getElementById('pl-det-delete');
    if (delBtn) delBtn.onclick = function () {
      if (!window.confirm('Delete this planned session? This can’t be undone.')) return;
      _api('DELETE', '/api/planned-sessions/' + p.id)
        .then(function () { _toast('Planned session deleted'); _closeDetail(); _loadWeek(); })
        .catch(function (err) { _toast(err.message || 'Delete failed', true); });
    };
    var copyBtn = document.getElementById('pl-det-copy');
    if (copyBtn) copyBtn.onclick = function () {
      var pre = document.getElementById('pl-stryd-pre');
      var text = pre ? pre.textContent : '';
      _copyText(text, copyBtn);
    };
    var idCopyBtn = document.getElementById('pl-detid-copy');
    // Icon-only button — _copyText() swaps textContent for feedback, which
    // would blow away the SVG. Toggle a class + title instead (same pattern
    // as the Log tab's dp-id-copy).
    if (idCopyBtn) idCopyBtn.onclick = function () {
      function flash() {
        idCopyBtn.classList.add('pl-detid-copy--done');
        idCopyBtn.setAttribute('title', 'Copied!');
        setTimeout(function () {
          idCopyBtn.classList.remove('pl-detid-copy--done');
          idCopyBtn.setAttribute('title', 'Copy ID');
        }, 1400);
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(p.id).then(flash).catch(function () { _fallbackCopy(p.id); flash(); });
      } else { _fallbackCopy(p.id); flash(); }
    };
    _wireDetailEvents(host);
  }

  function _fmtDur(min) { return min != null ? (min + ' min') : '—'; }

  function _runTiles(p) {
    var s = p.structure || {}, blocks = Array.isArray(s.blocks) ? s.blocks : [];
    var tot = 0;
    blocks.forEach(function (b) {
      var d = Number(b.duration_min) || 0, r = Math.max(1, Number(b.repeat) || 1);
      tot += d * r + (Number(b.rest_min) || 0) * (r - 1);
    });
    var tss = tot ? Math.round(tot * 1.2) : null;   // rough planned-TSS heuristic
    var distKm = tot ? (tot / 6).toFixed(1) : null; // ~6 min/km placeholder
    return '<div class="pl-dettiles">' +
      '<div class="pl-dettile"><div class="l">Planned duration</div><div class="v">' + _fmtDur(tot || null) + '</div></div>' +
      '<div class="pl-dettile"><div class="l">Planned TSS</div><div class="v">' + (tss != null ? '~' + tss : '—') + '</div></div>' +
      '<div class="pl-dettile"><div class="l">Planned distance</div><div class="v">' + (distKm != null ? '~' + distKm + ' km' : '—') + '</div></div>' +
    '</div>';
  }

  // Attach/mark-complete/mark-missed actions, shown in the detail panel for
  // unresolved sessions (planned/missed). Wired by _wireDetailEvents.
  function _detailStatusActionsHtml(p) {
    if (p.status !== 'planned' && p.status !== 'missed') return '';
    return '<div class="pl-detactions">' +
        '<button class="pl-btn pl-ghost pl-tiny" data-pick="' + p.id + '" data-pick-mode="attach">🔗 Attach a recent workout</button>' +
        '<button class="pl-btn pl-lime pl-tiny" data-markdone="' + p.id + '">✓ Mark as completed</button>' +
        (p.status === 'planned' ? '<button class="pl-btn pl-ghost pl-tiny" data-missed="' + p.id + '">Mark as missed</button>' : '') +
      '</div>' +
      '<div class="pl-picker" data-pickerfor="' + p.id + '" hidden></div>';
  }

  function _phaseLabel(ph) { return ph === 'warmup' ? 'Warmup' : (ph === 'cooldown' ? 'Cooldown' : (ph === 'main' ? 'Main set' : (ph || 'Block'))); }
  function _phaseCls(ph) { return ph === 'warmup' ? 'warm' : (ph === 'cooldown' ? 'cool' : 'main'); }

  function _detailIdRowHtml(p) {
    if (!p.id) return '';
    return '<div class="pl-detid-row"><code class="pl-detid" id="pl-detid-value">' + esc(p.id) + '</code>' +
      '<button type="button" class="pl-detid-copy" id="pl-detid-copy" aria-label="Copy session ID" title="Copy ID">' +
      '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>' +
      '</button></div>';
  }

  function _runDetailHtml(p) {
    var s = p.structure || {}, blocks = Array.isArray(s.blocks) ? s.blocks : [];
    var segs = blocks.map(function (b) {
      var dur = b.duration_min != null ? b.duration_min + ' min' : '';
      var rep = (b.repeat && b.repeat > 1) ? ('<span class="pl-repeatlbl">×' + b.repeat + '</span>') : '';
      var main = (b.repeat && b.repeat > 1) ? (b.repeat + ' × ' + dur) : dur;
      var tgt = (b.target || '') + (b.rest_min ? ' · ' + b.rest_min + 'min rest between' : '');
      return '<div class="pl-segblk"><span class="pl-sbtag ' + _phaseCls(b.phase) + '">' + _phaseLabel(b.phase) + '</span>' +
        '<span class="pl-sbmain">' + esc(main) + rep + '</span><span class="pl-sbtgt">' + esc(tgt) + '</span></div>';
    }).join('') || '<div class="pl-segblk"><span class="pl-sbmain" style="color:var(--pl-faint)">No structure yet.</span></div>';

    return '<div class="pl-dethead"><span class="pl-dettag run">Run</span>' +
        '<span style="font-size:11px;color:var(--pl-faint);font-family:var(--pl-mono)">' + esc(_fmtDayDate(p.planned_date)) + '</span>' +
        '<span style="flex:1"></span><button class="pl-btn pl-ghost pl-danger" id="pl-det-delete" title="Delete this planned session">Delete</button>' +
        '<button class="pl-btn pl-ghost" id="pl-det-edit" title="' + (p.actual && p.actual.id ? 'Edit the logged workout' : 'Edit the plan') + '">' + (p.actual && p.actual.id ? 'Edit workout' : 'Edit') + '</button></div>' +
      '<div class="pl-dettitle">' + esc(p.name || '(untitled)') + '</div>' +
      _detailIdRowHtml(p) +
      _detailStatusActionsHtml(p) +
      (p.notes ? '' : '') +
      _runTiles(p) +
      '<div class="pl-segwrap"><div class="pl-sectitle" style="margin-bottom:8px;">Structure</div><div class="pl-seg2">' + segs + '</div></div>' +
      (p.notes ? '<div class="pl-fld" style="margin-top:16px;"><label>Coach notes</label><div class="pl-notebox">' + esc(p.notes) + '</div></div>' : '') +
      '<div class="pl-exportbox"><div class="pl-eh"><span class="pl-et">Copy for Stryd Workout Builder</span><button class="pl-copybtn" id="pl-det-copy">Copy</button></div>' +
        '<div class="pl-ewarn">Stryd doesn’t accept structured workouts pushed from third-party apps — only synced from TrainingPeaks/Final Surge. Paste this into PowerCenter’s own Workout Builder to rebuild it. Power-or-pace targets only, no nested repeats, no ramps — matches Stryd’s import rules.</div>' +
        '<pre id="pl-stryd-pre">' + esc(_strydText(p)) + '</pre>' +
      '</div>';
  }

  // Build the flat Stryd paste block from the run structure (no nested repeats/ramps).
  function _strydText(p) {
    var s = p.structure || {}, blocks = Array.isArray(s.blocks) ? s.blocks : [];
    var out = [];
    function pad(label) { return (label + '        ').slice(0, 9); }
    function mmss(min) { var m = Math.floor(min), sec = Math.round((min - m) * 60); return m + ':' + String(sec).padStart(2, '0'); }
    blocks.forEach(function (b) {
      var dur = Number(b.duration_min) || 0;
      var tgt = b.target || 'easy';
      if (b.phase === 'main' && b.repeat && b.repeat > 1) {
        out.push('Repeat x' + b.repeat + ':');
        out.push('  Work    ' + pad(mmss(dur)) + tgt);
        if (b.rest_min) out.push('  Rest    ' + pad(mmss(Number(b.rest_min))) + 'easy jog');
      } else {
        var label = b.phase === 'warmup' ? 'Warmup' : (b.phase === 'cooldown' ? 'Cooldown' : 'Work');
        out.push(pad(label) + ' ' + pad(mmss(dur)) + tgt);
      }
    });
    return out.join('\n') || '(no structure)';
  }

  function _liftDetailHtml(p) {
    var s = p.structure || {}, plannedExs = Array.isArray(s.exercises) ? s.exercises : [];
    var focus = s.focus || '';
    var typeLabel = p.session_type === 'plyo' ? 'Plyo' : 'Strength';
    // A matched session shows what ACTUALLY happened (real sets/reps/weight/
    // RPE, live off the matched Workout — see _workout_actual_summary), not
    // the plan. It's always fetched fresh on load, so editing the workout's
    // exercises on the Log tab shows up here next time this panel opens —
    // no separate "sync back" step needed.
    var actual = p.actual;
    var actualExs = actual && Array.isArray(actual.exercises) ? actual.exercises : [];
    var usingActual = actualExs.length > 0;
    // Real logged exercises have no block field of their own — but the plan
    // they were matched against usually named the same exercises under a
    // block, so borrow that grouping by name (case/whitespace-insensitive)
    // rather than always falling back to one flat list once matched.
    if (usingActual) {
      var blockByName = {};
      plannedExs.forEach(function (x) {
        if (x && x.name && x.block) blockByName[String(x.name).toLowerCase().trim()] = x.block;
      });
      actualExs = actualExs.map(function (x) {
        var b = blockByName[String(x.name || '').toLowerCase().trim()];
        return b ? Object.assign({}, x, { block: b }) : x;
      });
    }
    var exs = usingActual ? actualExs : plannedExs;

    // One row template for both planned and actual exercises — same columns
    // (name / sets×reps / load-or-weight / RPE), same plain styling. Actual
    // rows use the real weight_kg + logged RPE (blank shows as a faint "—",
    // not a colored badge); planned rows use the free-text load + optional
    // target RPE. Kept as one function, not two, so matched vs. unmatched
    // sessions render one visual design instead of two.
    function _exRow(x) {
      var sr = (x.sets != null && x.reps != null) ? (x.sets + ' × ' + x.reps) : (x.sets != null ? x.sets + ' sets' : '');
      var loadTxt = usingActual ? (x.weight_kg != null ? x.weight_kg + 'kg' : '') : (x.load || '');
      var rpeVal = x.rpe != null && x.rpe !== '' ? x.rpe : null;
      var rpeHtml = rpeVal != null
        ? '<span class="pl-es">' + (usingActual ? 'RPE ' : 'Target RPE ') + esc(rpeVal) + '</span>'
        : (usingActual ? '<span class="pl-es" style="color:var(--pl-faint)">RPE —</span>' : '');
      return '<div class="pl-exd"><span class="pl-en">' + esc(x.name || 'Exercise') + '</span>' +
        '<span class="pl-sr">' + esc(sr) + '</span>' +
        '<span class="pl-es" style="color:var(--pl-faint)">' + esc(loadTxt) + '</span>' +
        rpeHtml + '</div>';
    }
    var exHtml;
    if (!exs.length) {
      exHtml = focus ? '' : '<div class="pl-exd"><span class="pl-en" style="color:var(--pl-faint)">No exercises listed.</span></div>';
    } else if (exs.some(function (x) { return x && x.block; })) {
      // Group by the pasted-back `block` label (Warm-up / Heavy compound /
      // Superset 1 / … / Accessories), preserving order of first appearance.
      // Real logged exercises never carry a block, so matched sessions just
      // fall through to the flat list below.
      var order = [];
      exs.forEach(function (x) {
        var b = (x && x.block) ? x.block : 'Other';
        if (order.indexOf(b) === -1) order.push(b);
      });
      exHtml = order.map(function (b) {
        var rows = exs.filter(function (x) { return ((x && x.block) ? x.block : 'Other') === b; }).map(_exRow).join('');
        return '<div class="pl-exblock"><div class="pl-exblock-h">' + esc(b) + '</div>' + rows + '</div>';
      }).join('');
    } else {
      exHtml = exs.map(_exRow).join('');
    }

    return '<div class="pl-dethead"><span class="pl-dettag lift">' + typeLabel + '</span>' +
        '<span style="font-size:11px;color:var(--pl-faint);font-family:var(--pl-mono)">' + esc(_fmtDayDate(p.planned_date)) + '</span>' +
        '<span style="flex:1"></span><button class="pl-btn pl-ghost pl-danger" id="pl-det-delete" title="Delete this planned session">Delete</button>' +
        '<button class="pl-btn pl-ghost" id="pl-det-edit" title="' + (p.actual && p.actual.id ? 'Edit the logged workout' : 'Edit the plan') + '">' + (p.actual && p.actual.id ? 'Edit workout' : 'Edit') + '</button></div>' +
      '<div class="pl-dettitle">' + esc(p.name || '(untitled)') + '</div>' +
      _detailIdRowHtml(p) +
      _detailStatusActionsHtml(p) +
      (actual && actual.needs_rpe
        ? '<div class="pl-infobanner" style="margin:8px 0;">Some exercises are missing RPE.' +
            (actual.id ? ' <button type="button" class="pl-rpe-fixlink" data-viewfull="' + esc(actual.id) + '">Add it on the logged workout →</button>' : '') +
          '</div>'
        : '') +
      '<div class="pl-dettiles">' +
        '<div class="pl-dettile"><div class="l">Type</div><div class="v" style="font-size:14px;">' + typeLabel + '</div></div>' +
        (focus && !usingActual ? '<div class="pl-dettile"><div class="l">Focus</div><div class="v" style="font-size:14px;">' + esc(focus) + '</div></div>' : '') +
      '</div>' +
      (exs.length ? '<div class="pl-segwrap"><div class="pl-sectitle" style="margin-bottom:8px;">Exercises</div>' + exHtml + '</div>' : '') +
      (p.notes ? '<div class="pl-fld" style="margin-top:16px;"><label>Coach notes</label><div class="pl-notebox">' + esc(p.notes) + '</div></div>' : '') +
      '<div class="pl-infobanner" style="margin-top:16px;">No Stryd export here — power-based workout export only applies to runs. This session logs into the Economy model once completed.</div>';
  }

  function _copyText(text, btn) {
    function done() { if (btn) { var o = btn.textContent; btn.textContent = 'Copied ✓'; setTimeout(function () { btn.textContent = o; }, 1400); } }
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(function () { _fallbackCopy(text); done(); });
    } else { _fallbackCopy(text); done(); }
  }
  function _fallbackCopy(text) {
    var ta = document.createElement('textarea'); ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); } catch (_) {}
    document.body.removeChild(ta);
  }

  // ── Scoped styles (injected once) ───────────────────────────────────────────
  function _injectStyles() {
    if (document.getElementById('plan-tab-styles')) return;
    var css = document.createElement('style');
    css.id = 'plan-tab-styles';
    css.textContent = PLAN_CSS;
    document.head.appendChild(css);
  }

  var PLAN_CSS = [
    '.plan-panel{',
    '--pl-ink:#1b2340;--pl-muted:#6b7280;--pl-faint:#9aa3b8;--pl-line:#eceef4;--pl-tile:#f6f7fb;',
    '--pl-blue:#4f6ef7;--pl-blueSoft:#e6ebfe;--pl-lavHi:#6366f1;--pl-green:#16a34a;--pl-greenSoft:#dcfce7;',
    '--pl-amber:#d97706;--pl-amberSoft:#fdf3da;--pl-red:#dc2626;--pl-redSoft:#fee2e2;',
    '--pl-run:#4f6ef7;--pl-lift:#8b5cf6;--pl-liftSoft:#ede9fe;--pl-lime:#cff245;--pl-mono:"JetBrains Mono",monospace;',
    'display:flex;flex-direction:column;gap:16px;color:var(--pl-ink);}',
    '.plan-panel .pl-card{background:#fff;border-radius:16px;padding:18px 20px;box-shadow:0 8px 24px rgba(20,28,70,0.16);}',
    '.plan-panel .pl-sectitle{font-size:11px;font-weight:800;letter-spacing:0.07em;color:var(--pl-faint);text-transform:uppercase;}',
    '.plan-panel .pl-chead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:4px;flex-wrap:wrap;}',
    '.plan-panel .pl-btn{font-size:12px;font-weight:700;border-radius:8px;padding:8px 13px;cursor:pointer;border:1px solid var(--pl-line);background:var(--pl-tile);color:var(--pl-ink);font-family:inherit;}',
    '.plan-panel .pl-btn:disabled{opacity:0.42;cursor:not-allowed;}',
    '.plan-panel .pl-btn.pl-dark{background:var(--pl-ink);color:#fff;border-color:var(--pl-ink);}',
    '.plan-panel .pl-btn.pl-lime{background:var(--pl-lime);color:var(--pl-ink);border-color:var(--pl-lime);}',
    '.plan-panel .pl-btn.pl-ghost{background:none;border:1px solid var(--pl-line);}',
    '.plan-panel .pl-btn.pl-danger{color:#b91c1c;border-color:#fecaca;}',
    '.plan-panel .pl-btn.pl-danger:hover{background:#fee2e2;}',
    '.plan-panel .pl-btn.pl-tiny{font-size:10px;padding:5px 9px;}',
    '.plan-panel .pl-detactions{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 4px;}',
    '.plan-panel .pl-btnrow{display:flex;gap:8px;flex-wrap:wrap;}',
    '.plan-panel .pl-loading{font-size:12.5px;color:var(--pl-faint);padding:14px 0;}',
    '.plan-panel .pl-infobanner{background:#f2f5ff;border:1px solid #e0e7ff;border-radius:11px;padding:10px 14px;font-size:12px;color:#3f4a7a;}',
    '.plan-panel .pl-infobanner b{color:var(--pl-lavHi);}',
    '.plan-panel .pl-panelcard{animation:plPanelIn .18s ease;}',
    '@keyframes plPanelIn{from{opacity:0;transform:translateY(-6px);}to{opacity:1;transform:translateY(0);}}',
    '.plan-panel .pl-panelhead{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;gap:10px;}',
    '.plan-panel .pl-closepanel{width:27px;height:27px;flex-shrink:0;border:1px solid var(--pl-line);background:var(--pl-tile);border-radius:8px;cursor:pointer;color:var(--pl-muted);font-size:13px;}',
    '.plan-panel .pl-closepanel:hover{color:var(--pl-red);border-color:#fecaca;}',
    '.plan-panel .pl-wknav{display:flex;align-items:center;gap:10px;}',
    '.plan-panel .pl-arw{width:26px;height:26px;border:1px solid var(--pl-line);background:var(--pl-tile);border-radius:8px;cursor:pointer;font-size:14px;color:var(--pl-muted);}',
    '.plan-panel .pl-wktitle{font-size:13px;font-weight:800;}',
    '.plan-panel .pl-weeklist{display:flex;flex-direction:column;gap:10px;margin-top:14px;}',
    '.plan-panel .pl-dayrow{display:flex;gap:14px;padding:12px 14px;border:1px solid var(--pl-line);border-radius:12px;background:var(--pl-tile);align-items:flex-start;}',
    '.plan-panel .pl-dayrow.today{border-color:#c7d2fe;background:#f4f6ff;}',
    '.plan-panel .pl-dayrow.past{opacity:0.94;}',
    '.plan-panel .pl-dayrow.dragover{outline:2px dashed var(--pl-lavHi);outline-offset:-2px;background:#eef2ff;}',
    '.plan-panel .pl-daylabel{width:58px;flex-shrink:0;padding-top:2px;}',
    '.plan-panel .pl-daylabel .pl-dname{font-size:10px;font-weight:800;color:var(--pl-faint);text-transform:uppercase;display:block;}',
    '.plan-panel .pl-daylabel .pl-dnum{font-size:20px;font-family:var(--pl-mono);color:var(--pl-ink);font-weight:700;display:block;margin-top:2px;}',
    '.plan-panel .pl-daybody{flex:1;display:flex;flex-wrap:wrap;gap:10px;align-items:flex-start;min-width:0;}',
    '.plan-panel .pl-daybody .pl-sess,.plan-panel .pl-daybody .pl-ghost{flex:1 1 250px;max-width:360px;}',
    '.plan-panel .pl-sess{position:relative;border-radius:8px;padding:7px 9px;font-size:11px;cursor:pointer;border-left:3px solid transparent;background:#fff;box-shadow:0 1px 2px rgba(20,28,70,0.06);}',
    '.plan-panel .pl-sess.dragging{opacity:0.4;}',
    '.plan-panel .pl-sess[draggable="true"]{cursor:grab;}',
    '.plan-panel .pl-sess.run{border-left-color:var(--pl-run);}.plan-panel .pl-sess.lift{border-left-color:var(--pl-lift);}',
    '.plan-panel .pl-sess .pl-sn{font-weight:700;font-size:11.5px;}.plan-panel .pl-sess .pl-sm{color:var(--pl-muted);font-family:var(--pl-mono);font-size:10px;margin-top:2px;}',
    '.plan-panel .pl-stypetag{font-size:8px;font-weight:800;letter-spacing:0.03em;padding:1px 5px;border-radius:4px;text-transform:uppercase;display:inline-block;}',
    '.plan-panel .pl-stypetag.run{background:var(--pl-blueSoft);color:var(--pl-run);}.plan-panel .pl-stypetag.lift{background:var(--pl-liftSoft);color:#7c3aed;}',
    '.plan-panel .pl-dhandle{position:absolute;top:7px;right:8px;font-size:9px;color:var(--pl-faint);letter-spacing:-1px;}',
    '.plan-panel .pl-sesstop{display:flex;align-items:center;justify-content:space-between;gap:4px;margin-bottom:2px;}',
    '.plan-panel .pl-stat-tag{font-size:7.5px;font-weight:800;letter-spacing:0.03em;padding:1px 5px;border-radius:4px;text-transform:uppercase;}',
    '.plan-panel .pl-stat-tag.missed{background:var(--pl-redSoft);color:var(--pl-red);}',
    '.plan-panel .pl-stat-tag.review{background:var(--pl-amberSoft);color:var(--pl-amber);}',
    '.plan-panel .pl-stat-tag.done{background:var(--pl-greenSoft);color:var(--pl-green);}',
    '.plan-panel .pl-sess.status-missed{opacity:0.55;}',
    '.plan-panel .pl-sess.status-done_auto,.plan-panel .pl-sess.status-done_manual{background:#f4fbf6;border-left-color:var(--pl-green)!important;}',
    '.plan-panel .pl-sess.status-needs_review{background:#fffaf0;border-left-color:var(--pl-amber)!important;cursor:default;}',
    '.plan-panel .pl-diffline{font-size:9.5px;color:var(--pl-muted);font-family:var(--pl-mono);margin-top:6px;line-height:1.4;}',
    '.plan-panel .pl-diffline--manual{font-style:italic;}',
    '.plan-panel .pl-unlink{margin-top:4px;font-size:9.5px;color:var(--pl-faint);background:none;border:none;cursor:pointer;padding:0;}',
    '.plan-panel .pl-unlink:hover{color:var(--pl-red);}',
    // Quick-tag feeling row: faint icons until one is picked, then only it shows.
    '.plan-panel .pl-feelrow{display:flex;gap:4px;margin-top:5px;align-items:center;}',
    '.plan-panel .pl-feel-btn{background:none;border:none;padding:0 2px;font-size:14px;line-height:1;cursor:pointer;opacity:0.32;filter:grayscale(0.6);transition:opacity .12s,filter .12s,transform .12s;}',
    '.plan-panel .pl-feel-btn:hover{opacity:0.75;filter:grayscale(0);}',
    '.plan-panel .pl-feel-btn.is-on{opacity:1;filter:none;transform:scale(1.12);}',
    '.plan-panel .pl-feel-btn.is-hidden{display:none;}',
    // 24h attach/override picker.
    '.plan-panel .pl-matchbtns{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:4px;}',
    '.plan-panel .pl-pickbtn{font-size:9.5px;color:var(--pl-run);background:none;border:none;cursor:pointer;padding:0;text-align:left;}',
    '.plan-panel .pl-pickbtn:hover{text-decoration:underline;}',
    '.plan-panel .pl-picker{margin-top:6px;}',
    '.plan-panel .pl-pickerlist{display:flex;flex-direction:column;gap:4px;}',
    '.plan-panel .pl-pickrow{display:flex;align-items:center;gap:6px;font-size:10px;background:#fff;border:1px solid var(--pl-line);border-radius:6px;padding:5px 7px;cursor:pointer;text-align:left;width:100%;}',
    '.plan-panel .pl-pickrow:hover{border-color:var(--pl-run);}',
    '.plan-panel .pl-pickrow.is-sel{border-color:var(--pl-run);background:#eef3ff;}',
    '.plan-panel .pl-pickrow-badge{font-size:8px;font-weight:800;text-transform:uppercase;padding:1px 4px;border-radius:4px;color:#fff;}',
    '.plan-panel .pl-pickrow-badge.run{background:var(--pl-run);}.plan-panel .pl-pickrow-badge.lift{background:var(--pl-lift);}',
    '.plan-panel .pl-pickrow-name{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.plan-panel .pl-pickrow-meta{color:var(--pl-faint);font-family:var(--pl-mono);margin-left:auto;white-space:nowrap;}',
    '.plan-panel .pl-pickconfirm{display:flex;align-items:center;gap:8px;margin-top:6px;font-size:10px;color:var(--pl-muted);}',
    '.plan-panel .pl-picker-empty{font-size:10px;color:var(--pl-faint);font-style:italic;padding:4px 2px;}',
    // "View full workout →" deep link.
    '.plan-panel .pl-viewfull{display:block;margin-top:4px;font-size:9.5px;color:var(--pl-run);background:none;border:none;cursor:pointer;padding:0;text-align:left;}',
    '.plan-panel .pl-viewfull:hover{text-decoration:underline;}',
    // RPE-missing banner on a matched session's detail panel.
    '.plan-panel .pl-rpe-fixlink{background:none;border:none;padding:0;font-size:12px;font-weight:700;color:inherit;text-decoration:underline;cursor:pointer;font-family:inherit;}',
    '.plan-panel .pl-candlist{margin-top:7px;display:flex;flex-direction:column;gap:4px;}',
    '.plan-panel .pl-candrow{display:flex;align-items:center;gap:6px;font-size:10px;background:#fff;border:1px solid var(--pl-line);border-radius:6px;padding:5px 7px;cursor:pointer;}',
    '.plan-panel .pl-candrow .pl-cn{font-weight:600;}.plan-panel .pl-candrow .pl-cm{color:var(--pl-faint);font-family:var(--pl-mono);margin-left:auto;}',
    '.plan-panel .pl-candbtns{display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;}',
    '.plan-panel .pl-ghost{border:1.5px dashed #d7dcec;border-radius:8px;padding:8px 9px;background:#fbfcff;}',
    '.plan-panel .pl-gtop{margin-bottom:3px;}',
    '.plan-panel .pl-gtag{font-size:8px;font-weight:800;letter-spacing:0.03em;color:var(--pl-faint);background:var(--pl-tile);padding:1px 5px;border-radius:4px;}',
    '.plan-panel .pl-ghostsel{width:100%;font-size:10.5px;border:1px solid var(--pl-line);border-radius:6px;padding:4px 6px;margin-top:6px;background:#fff;}',
    '.plan-panel .pl-daybody .pl-addday{border:1.5px dashed #d7dcec;border-radius:8px;flex:0 0 76px;min-height:52px;display:flex;align-items:center;justify-content:center;text-align:center;font-size:10.5px;color:var(--pl-faint);cursor:pointer;}',
    '.plan-panel .pl-addday:hover{color:var(--pl-lavHi);border-color:#c7d2fe;}',
    '.plan-panel .pl-addday.is-disabled{cursor:not-allowed;opacity:0.5;border-style:solid;}',
    '.plan-panel .pl-addday.is-disabled:hover{color:var(--pl-faint);border-color:#d7dcec;}',
    '.plan-panel .pl-restday{font-size:11px;color:var(--pl-faint);font-style:italic;align-self:center;padding:6px 4px;}',
    '.plan-panel .pl-legend{display:flex;gap:14px;margin-top:12px;font-size:11px;color:var(--pl-muted);flex-wrap:wrap;}',
    '.plan-panel .pl-legend b{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px;}',
    '.plan-panel .pl-modetoggle{display:flex;background:var(--pl-tile);border:1px solid var(--pl-line);border-radius:9px;padding:3px;gap:2px;width:fit-content;margin-bottom:16px;}',
    '.plan-panel .pl-modetoggle button{font-size:12px;font-weight:600;color:var(--pl-muted);background:none;border:none;padding:6px 13px;border-radius:7px;cursor:pointer;font-family:inherit;}',
    '.plan-panel .pl-modetoggle button.on{background:#fff;color:var(--pl-ink);box-shadow:0 1px 2px rgba(0,0,0,0.06);}',
    '.plan-panel .pl-subtoggle{display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap;}',
    '.plan-panel .pl-subtoggle button{font-size:11.5px;font-weight:700;color:var(--pl-muted);background:var(--pl-tile);border:1px solid var(--pl-line);padding:6px 12px;border-radius:7px;cursor:pointer;font-family:inherit;}',
    '.plan-panel .pl-subtoggle button.on{background:var(--pl-ink);color:#fff;border-color:var(--pl-ink);}',
    '.plan-panel .pl-jsontools{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;align-items:center;}',
    '.plan-panel .pl-jsonta{width:100%;max-width:100%;min-height:230px;font-family:var(--pl-mono);font-size:12px;line-height:1.65;border:1px solid var(--pl-line);background:#0f1330;color:#cfe0ff;border-radius:10px;padding:14px;resize:vertical;white-space:pre;overflow:auto;}',
    '.plan-panel .pl-previewbox{margin-top:12px;border-radius:10px;padding:12px 14px;font-size:12.5px;}',
    '.plan-panel .pl-previewbox.ok{background:var(--pl-greenSoft);color:#14532d;}',
    '.plan-panel .pl-previewbox.err{background:var(--pl-redSoft);color:#7f1d1d;font-family:var(--pl-mono);white-space:pre-wrap;}',
    '.plan-panel .pl-previewlist{margin-top:9px;display:flex;flex-direction:column;gap:5px;}',
    '.plan-panel .pl-previewrow{display:flex;gap:10px;font-family:var(--pl-mono);font-size:11.5px;background:rgba(255,255,255,0.55);border-radius:6px;padding:6px 10px;}',
    '.plan-panel .pl-delimsel{font-size:12px;font-weight:600;border:1px solid var(--pl-line);border-radius:7px;padding:7px 10px;background:var(--pl-tile);color:var(--pl-ink);}',
    '.plan-panel .pl-uploadlbl{font-size:12px;font-weight:700;border-radius:8px;padding:8px 13px;cursor:pointer;border:1px solid var(--pl-line);background:var(--pl-tile);color:var(--pl-ink);}',
    '.plan-panel .pl-frow{display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap;}',
    '.plan-panel .pl-fld{flex:1;min-width:150px;}',
    '.plan-panel .pl-fld label{font-size:10px;font-weight:800;letter-spacing:0.05em;color:var(--pl-faint);text-transform:uppercase;display:block;margin-bottom:5px;}',
    '.plan-panel .pl-fld input,.plan-panel .pl-fld select,.plan-panel .pl-fld textarea{width:100%;font-family:inherit;font-size:13px;color:var(--pl-ink);border:1px solid var(--pl-line);background:var(--pl-tile);border-radius:8px;padding:9px 11px;}',
    '.plan-panel .pl-fld textarea{resize:vertical;min-height:54px;}',
    '.plan-panel .pl-notebox{font-size:13px;color:var(--pl-muted);background:var(--pl-tile);border-radius:9px;padding:10px 13px;}',
    '.plan-panel .pl-blocklist{display:flex;flex-direction:column;gap:8px;margin-top:6px;}',
    '.plan-panel .pl-block{display:flex;gap:8px;align-items:center;background:var(--pl-tile);border:1px solid var(--pl-line);border-radius:10px;padding:9px 11px;flex-wrap:wrap;}',
    '.plan-panel .pl-block .pl-btag{font-size:9px;font-weight:800;padding:3px 8px;border-radius:6px;flex-shrink:0;width:74px;text-align:center;}',
    '.plan-panel .pl-btag.warm{background:#e0f2fe;color:#0369a1;}.plan-panel .pl-btag.main{background:var(--pl-amberSoft);color:var(--pl-amber);}.plan-panel .pl-btag.cool{background:var(--pl-greenSoft);color:var(--pl-green);}',
    '.plan-panel .pl-block input{border:1px solid var(--pl-line);background:#fff;border-radius:6px;padding:6px 8px;font-size:11.5px;font-family:var(--pl-mono);}',
    '.plan-panel .pl-block .pl-bdur{width:70px;}.plan-panel .pl-block .pl-btgt{width:96px;}.plan-panel .pl-block .pl-exname{flex:1;min-width:120px;font-family:inherit;}',
    '.plan-panel .pl-block .pl-rm{margin-left:auto;color:var(--pl-faint);cursor:pointer;font-size:13px;background:none;border:none;}',
    '.plan-panel .pl-exhead{display:flex;gap:8px;padding:0 11px;margin-top:8px;font-size:9.5px;font-weight:700;letter-spacing:0.04em;text-transform:uppercase;color:var(--pl-faint);}',
    '.plan-panel .pl-exhead span:nth-child(1){flex:1;min-width:120px;}.plan-panel .pl-exhead span:nth-child(2){width:70px;}.plan-panel .pl-exhead span:nth-child(3){width:70px;}.plan-panel .pl-exhead span:nth-child(4){width:96px;}.plan-panel .pl-exhead span:nth-child(5){width:70px;}.plan-panel .pl-exhead span:nth-child(6){width:20px;}',
    '.plan-panel .pl-addblock{font-size:11.5px;font-weight:700;color:var(--pl-lavHi);background:none;border:1px dashed #c7d2fe;border-radius:8px;padding:7px;cursor:pointer;text-align:center;margin-top:8px;width:100%;}',
    '.plan-panel .pl-bulktbl{width:100%;border-collapse:separate;border-spacing:0 8px;}',
    '.plan-panel .pl-bulktbl th{font-size:9px;font-weight:800;color:var(--pl-faint);text-transform:uppercase;letter-spacing:0.04em;text-align:left;padding:0 8px 4px;}',
    '.plan-panel .pl-bulktbl td{background:var(--pl-tile);border-top:1px solid var(--pl-line);border-bottom:1px solid var(--pl-line);padding:8px;}',
    '.plan-panel .pl-bulktbl td:first-child{border-left:1px solid var(--pl-line);border-radius:9px 0 0 9px;}',
    '.plan-panel .pl-bulktbl td:last-child{border-right:1px solid var(--pl-line);border-radius:0 9px 9px 0;}',
    '.plan-panel .pl-bulktbl input,.plan-panel .pl-bulktbl select{width:100%;border:none;background:none;font-size:12px;font-family:inherit;color:var(--pl-ink);}',
    '.plan-panel .pl-bulktbl .pl-bd{font-size:11px;font-weight:800;color:var(--pl-faint);width:40px;}',
    '.plan-panel .pl-dethead{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}',
    '.plan-panel .pl-dettag{font-size:9px;font-weight:800;letter-spacing:0.04em;padding:3px 8px;border-radius:6px;text-transform:uppercase;}',
    '.plan-panel .pl-dettag.run{background:var(--pl-blueSoft);color:var(--pl-run);}.plan-panel .pl-dettag.lift{background:var(--pl-liftSoft);color:#7c3aed;}',
    '.plan-panel .pl-dettitle{font-size:19px;font-weight:800;margin-top:10px;}',
    '.plan-panel .pl-detid-row{display:flex;align-items:center;gap:6px;margin-top:3px;}',
    '.plan-panel .pl-detid{font-size:10.5px;font-family:var(--pl-mono);color:var(--pl-faint);letter-spacing:-0.01em;}',
    '.plan-panel .pl-detid-copy{display:flex;align-items:center;justify-content:center;width:20px;height:20px;padding:0;border:none;background:none;color:var(--pl-faint);cursor:pointer;border-radius:4px;}',
    '.plan-panel .pl-detid-copy:hover{background:var(--pl-tile);color:var(--pl-muted);}',
    '.plan-panel .pl-detid-copy--done{color:var(--pl-green);}',
    '.plan-panel .pl-dettiles{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap;}',
    '.plan-panel .pl-dettile{flex:1;min-width:120px;background:var(--pl-tile);border:1px solid var(--pl-line);border-radius:11px;padding:11px 13px;}',
    '.plan-panel .pl-dettile .l{font-size:9px;font-weight:800;color:var(--pl-faint);text-transform:uppercase;}.plan-panel .pl-dettile .v{font-size:18px;font-weight:700;font-family:var(--pl-mono);margin-top:4px;}',
    '.plan-panel .pl-segwrap{margin-top:18px;}',
    '.plan-panel .pl-seg2{border-radius:11px;overflow:hidden;border:1px solid var(--pl-line);}',
    '.plan-panel .pl-segblk{display:flex;align-items:center;gap:12px;padding:12px 14px;border-top:1px solid var(--pl-line);}',
    '.plan-panel .pl-segblk:first-child{border-top:none;}',
    '.plan-panel .pl-segblk .pl-sbtag{font-size:9px;font-weight:800;padding:4px 9px;border-radius:6px;width:76px;text-align:center;flex-shrink:0;}',
    '.plan-panel .pl-segblk .pl-sbtag.warm{background:#e0f2fe;color:#0369a1;}.plan-panel .pl-segblk .pl-sbtag.main{background:var(--pl-amberSoft);color:var(--pl-amber);}.plan-panel .pl-segblk .pl-sbtag.cool{background:var(--pl-greenSoft);color:var(--pl-green);}',
    '.plan-panel .pl-segblk .pl-sbmain{flex:1;font-size:13px;font-weight:600;}',
    '.plan-panel .pl-segblk .pl-sbtgt{font-size:12px;color:var(--pl-muted);font-family:var(--pl-mono);}',
    '.plan-panel .pl-repeatlbl{font-size:10.5px;color:var(--pl-lavHi);font-weight:700;background:var(--pl-blueSoft);padding:2px 8px;border-radius:6px;margin-left:6px;}',
    '.plan-panel .pl-exportbox{background:#0f1330;color:#e3e6ff;border-radius:12px;padding:15px 17px;margin-top:18px;}',
    '.plan-panel .pl-exportbox .pl-eh{display:flex;justify-content:space-between;align-items:center;gap:10px;}',
    '.plan-panel .pl-exportbox .pl-et{font-size:12px;font-weight:800;color:#fff;}.plan-panel .pl-exportbox .pl-ewarn{font-size:10.5px;color:#a5abe0;margin-top:5px;line-height:1.5;}',
    '.plan-panel .pl-exportbox pre{background:rgba(255,255,255,0.06);border-radius:9px;padding:12px 13px;margin-top:11px;font-family:var(--pl-mono);font-size:11px;color:#cfe0ff;line-height:1.7;overflow-x:auto;white-space:pre;}',
    '.plan-panel .pl-copybtn{background:var(--pl-lime);color:#1b2340;border:none;border-radius:8px;padding:7px 13px;font-size:11.5px;font-weight:800;cursor:pointer;flex-shrink:0;}',
    '.plan-panel .pl-exd{display:flex;align-items:center;gap:12px;background:var(--pl-tile);border:1px solid var(--pl-line);border-radius:10px;padding:10px 13px;margin-bottom:8px;flex-wrap:wrap;}',
    '.plan-panel .pl-exd .pl-en{flex:1;min-width:120px;font-size:13px;font-weight:600;}.plan-panel .pl-exd .pl-es{font-size:11.5px;color:var(--pl-muted);font-family:var(--pl-mono);}',
    '.plan-panel .pl-exd .pl-sr{font-size:14px;font-weight:800;color:#7c3aed;font-family:var(--pl-mono);}',
    // Exercises grouped by pasted-back `block` label.
    '.plan-panel .pl-exblock{margin-bottom:18px;padding:12px 12px 4px;border-radius:12px;background:rgba(13,30,67,0.03);}',
    '.plan-panel .pl-exblock:last-child{margin-bottom:0;}',
    '.plan-panel .pl-exblock-h{font-size:10.5px;font-weight:800;text-transform:uppercase;letter-spacing:0.05em;color:var(--pl-muted);margin-bottom:9px;padding-bottom:7px;border-bottom:1px solid var(--pl-line);}',
    '@media(max-width:560px){.plan-panel .pl-dayrow{flex-direction:column;gap:8px;}.plan-panel .pl-daylabel{width:auto;display:flex;align-items:baseline;gap:6px;padding-top:0;}}',
    // ── Suggestions panel (issue #1315) ─────────────────────────────────────
    '.pl-suggestions-panel{background:var(--pl-tile);border:1px solid var(--pl-line);border-radius:13px;padding:14px 16px;margin:14px 0;position:relative;}',
    '.pl-sug-header{display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap;}',
    '.pl-sug-title{font-size:13px;font-weight:800;color:var(--pl-ink);flex:1;}',
    '.pl-sug-source{font-size:10px;font-weight:700;padding:2px 7px;border-radius:6px;background:var(--pl-blueSoft);color:var(--pl-run);text-transform:uppercase;letter-spacing:0.04em;}',
    '.pl-sug-btn-sm{background:none;border:1px solid var(--pl-line);border-radius:7px;padding:3px 8px;font-size:12px;color:var(--pl-muted);cursor:pointer;}',
    '.pl-sug-btn-sm:hover{background:var(--pl-tile);color:var(--pl-ink);}',
    // Loading OVERLAY (not a full clear) — covers the panel (prefs form or the
    // previous suggestion list stays visible underneath, dimmed) while a
    // (re)generate call is in flight.
    '.pl-sug-loading{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;background:rgba(255,255,255,0.85);border-radius:13px;font-size:12.5px;font-weight:600;color:var(--pl-muted);z-index:2;}',
    '.pl-sug-spinner{width:22px;height:22px;border-radius:50%;border:2.5px solid var(--pl-line);border-top-color:var(--pl-run);animation:pl-sug-spin 0.7s linear infinite;}',
    '@keyframes pl-sug-spin{to{transform:rotate(360deg);}}',
    '@media (prefers-reduced-motion: reduce){.pl-sug-spinner{animation:none;border-top-color:var(--pl-line);}}',
    '.pl-sug-row-wrap{padding:9px 0;border-bottom:1px solid var(--pl-line);}',
    '.pl-sug-row-wrap:last-child{border-bottom:none;}',
    '.pl-sug-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}',
    '.pl-sug-exercises{margin:8px 0 2px 46px;padding:8px 0 0;border-top:1px dashed var(--pl-line);}',
    '.pl-sug-ex-block{margin-bottom:8px;}',
    '.pl-sug-ex-block:last-child{margin-bottom:0;}',
    '.pl-sug-ex-block-h{font-size:9.5px;font-weight:800;text-transform:uppercase;letter-spacing:0.04em;color:var(--pl-faint);margin-bottom:4px;}',
    '.pl-sug-ex-row{display:flex;align-items:baseline;gap:8px;font-size:12px;padding:2px 0;flex-wrap:wrap;}',
    '.pl-sug-ex-name{font-weight:600;color:var(--pl-ink);min-width:140px;}',
    '.pl-sug-ex-detail{font-family:var(--pl-mono);color:var(--pl-muted);}',
    '.pl-sug-ex-load{color:var(--pl-faint);font-size:11.5px;}',
    '.pl-sug-rep{font-size:10.5px;font-weight:800;color:var(--pl-run);background:var(--pl-blueSoft);border-radius:5px;padding:1px 5px;}',
    '.pl-sug-day{font-size:10px;font-weight:800;color:var(--pl-faint);text-transform:uppercase;width:36px;flex-shrink:0;}',
    '.pl-sug-type-select{font-size:10px;font-weight:800;padding:3px 6px;border-radius:6px;text-transform:uppercase;flex-shrink:0;border:1px solid transparent;cursor:pointer;-webkit-appearance:none;appearance:none;}',
    '.pl-sug-type-select.run{background:var(--pl-blueSoft);color:var(--pl-run);}.pl-sug-type-select.strength{background:var(--pl-liftSoft);color:#7c3aed;}.pl-sug-type-select.plyo{background:var(--pl-amberSoft);color:var(--pl-amber);}.pl-sug-type-select.rest{background:#f1f5f9;color:#64748b;}',
    '.pl-sug-meta{font-size:12px;font-family:var(--pl-mono);color:var(--pl-muted);flex-shrink:0;}',
    '.pl-sug-intent{flex:1;font-size:12px;color:var(--pl-ink);min-width:100px;}',
    '.pl-sug-notes-line{font-size:11.5px;color:var(--pl-muted);font-style:italic;margin:2px 0 4px 46px;line-height:1.4;}',
    '.pl-sug-adjust{display:flex;gap:4px;flex-shrink:0;}',
    '.pl-sug-adj{font-size:10.5px;font-weight:600;background:none;border:1px solid var(--pl-line);border-radius:6px;padding:4px 7px;cursor:pointer;color:var(--pl-muted);}',
    '.pl-sug-adj:hover{background:var(--pl-tile);color:var(--pl-ink);}',
    '.pl-sug-add{font-size:11px;font-weight:700;background:var(--pl-lime);color:#1b2340;border:none;border-radius:7px;padding:5px 11px;cursor:pointer;flex-shrink:0;}',
    '.pl-sug-add:disabled{opacity:0.5;cursor:default;}',
    '.pl-sug-add.added{background:#d1fae5;color:#065f46;}',
    '.pl-sug-refine-toggle{font-size:10.5px;font-weight:600;background:none;border:1px solid var(--pl-line);border-radius:6px;padding:4px 7px;cursor:pointer;color:var(--pl-lavHi);}',
    '.pl-sug-refine-toggle:hover{background:var(--pl-tile);}',
    '.pl-sug-refine-panel{display:flex;align-items:center;gap:6px;margin:4px 0 6px 46px;flex-wrap:wrap;}',
    '.pl-sug-refine-input{flex:1;min-width:180px;font-size:11.5px;border:1px solid var(--pl-line);border-radius:6px;padding:5px 8px;font-family:inherit;}',
    '.pl-sug-refine-status{font-size:10.5px;color:var(--pl-muted);}',
    '.pl-sug-trigger-row{margin:10px 0 4px;display:flex;justify-content:flex-start;}',
    '.pl-sug-trigger-btn{font-size:12px;font-weight:700;color:var(--pl-lavHi);background:none;border:1px dashed #c7d2fe;border-radius:8px;padding:7px 13px;cursor:pointer;}',
    // ── Pre-generation preferences form ─────────────────────────────────────
    '.pl-sug-prefs{display:flex;flex-direction:column;gap:12px;}',
    '.pl-sug-prefs-row{display:flex;flex-direction:column;gap:6px;}',
    '.pl-sug-prefs-label{font-size:11px;font-weight:700;color:var(--pl-muted);text-transform:uppercase;letter-spacing:0.03em;}',
    '.pl-sug-daychks{display:flex;gap:6px;flex-wrap:wrap;}',
    '.pl-sug-daychk{display:flex;align-items:center;gap:5px;font-size:12px;font-weight:600;color:var(--pl-ink);background:#fff;border:1px solid var(--pl-line);border-radius:8px;padding:5px 10px;cursor:pointer;}',
    '.pl-sug-daychk input{margin:0;}',
    '.pl-sug-daychk.is-closed{opacity:0.4;cursor:not-allowed;}',
    '.pl-sug-select{font-size:13px;padding:7px 10px;border:1px solid var(--pl-line);border-radius:8px;background:#fff;color:var(--pl-ink);width:auto;align-self:flex-start;}',
    '.pl-sug-notes{font-size:13px;padding:9px 11px;border:1px solid var(--pl-line);border-radius:9px;background:#fff;color:var(--pl-ink);min-height:52px;resize:vertical;font-family:inherit;}'
  ].join('');

}());

// ── Plan Suggestions (issue #1315 + PRD feedback v2) ─────────────────────────
(function () {
  var _dismissed = false;
  var _suggestionsData = null;
  // Remembered across Refresh clicks so re-opening the prefs form doesn't
  // lose what the athlete already told it.
  var _lastPrefs = { restDays: [], strengthEmphasis: 'same', notes: '' };

  var _DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  var _DAY_NAMES_FULL = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

  function _el(id) { return document.getElementById(id); }
  function esc(s) {
    return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // Local date helpers (this module is a separate closure from the main Plan
  // module above, which has its own copies it doesn't export).
  function _parseISO(s) { var p = String(s).split('-'); return new Date(+p[0], +p[1] - 1, +p[2]); }
  function _fmtISO(d) { return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0'); }

  function _weekStartISO() {
    return (window.TrainingPlan && window.TrainingPlan.getWeekStartISO)
      ? window.TrainingPlan.getWeekStartISO()
      : _fmtISO(new Date());
  }

  // The date a day_offset (0=Mon..6=Sun) lands on, relative to the week
  // actually on screen — replaces the old hardcoded "next Monday" assumption
  // that ignored which week the athlete was looking at.
  function _formatSugDate(dayOffset) {
    var d = _parseISO(_weekStartISO());
    d.setDate(d.getDate() + dayOffset);
    return _fmtISO(d);
  }

  // ── Per-session adjust: type override + lighter/harder ──────────────────────
  // Lighter/Harder used to touch only the summary target_tss/duration numbers
  // — the actual exercises/blocks never changed, so "harder" didn't translate
  // into anything the athlete could act on at the gym. Now it also nudges the
  // real prescription: exercise sets (and numeric reps, when parseable) for
  // strength/plyo, and block duration/repeat for run.

  function _adjustSession(s, harder) {
    var factor = harder ? 1.2 : 0.8;
    s.target_tss = Math.max(0, Math.min(400, Math.round((s.target_tss || 0) * factor)));
    s.duration_minutes = Math.max(0, Math.round((s.duration_minutes || 0) * factor));

    if (Array.isArray(s.exercises)) {
      s.exercises.forEach(function (ex) {
        if (ex.sets != null) {
          ex.sets = Math.max(1, Math.min(8, ex.sets + (harder ? 1 : -1)));
        }
        // reps is a freeform string ("10", "30s hold", "per side") — only
        // scale it when it's a plain integer; leave hold-durations/text alone.
        if (typeof ex.reps === 'string' && /^\d+$/.test(ex.reps.trim())) {
          var n = parseInt(ex.reps, 10);
          ex.reps = String(Math.max(1, Math.round(n * factor)));
        }
      });
    }
    if (Array.isArray(s.blocks)) {
      s.blocks.forEach(function (b) {
        if (b.duration_min != null) {
          b.duration_min = Math.max(1, Math.round(b.duration_min * factor));
        }
        if (b.repeat != null && b.repeat > 0) {
          b.repeat = Math.max(1, Math.min(20, b.repeat + (harder ? 1 : -1)));
        }
      });
    }
  }

  // Block-grouped exercise breakdown under a strength/plyo suggestion row —
  // same shape PlannedSession.structure.exercises stores, same grouping the
  // detail modal renders (see _liftDetailHtml). Without this the suggestion
  // was a bare TSS/duration/intent line and "Add" produced an empty-shell
  // planned session with nothing to actually do at the gym.
  function _sugExercisesHtml(exercises) {
    if (!exercises || !exercises.length) return '';
    var order = [];
    exercises.forEach(function (x) {
      var b = (x && x.block) ? x.block : 'Exercises';
      if (order.indexOf(b) === -1) order.push(b);
    });
    var blocks = order.map(function (b) {
      var rows = exercises.filter(function (x) { return ((x && x.block) ? x.block : 'Exercises') === b; })
        .map(function (x) {
          var sr = (x.sets != null && x.reps != null) ? (x.sets + ' × ' + x.reps) : (x.sets != null ? x.sets + ' sets' : '');
          return '<div class="pl-sug-ex-row"><span class="pl-sug-ex-name">' + esc(x.name || 'Exercise') + '</span>' +
            '<span class="pl-sug-ex-detail">' + esc(sr) + '</span>' +
            '<span class="pl-sug-ex-load">' + esc(x.load || '') + '</span></div>';
        }).join('');
      return '<div class="pl-sug-ex-block"><div class="pl-sug-ex-block-h">' + esc(b) + '</div>' + rows + '</div>';
    }).join('');
    return '<div class="pl-sug-exercises">' + blocks + '</div>';
  }

  // Phase-structured breakdown under a run suggestion row — same shape
  // PlannedSession.structure.blocks stores (see _runDetailHtml's segment
  // rendering). Without this a run suggestion was just target_tss/duration —
  // no warmup/main/cooldown structure, no repeat/target for a workout.
  function _phaseLabel(ph) { return ph === 'warmup' ? 'Warmup' : (ph === 'cooldown' ? 'Cooldown' : (ph === 'main' ? 'Main set' : (ph || 'Block'))); }
  function _sugBlocksHtml(blocks) {
    if (!blocks || !blocks.length) return '';
    var segs = blocks.map(function (b) {
      var dur = b.duration_min != null ? b.duration_min + ' min' : '';
      var rep = (b.repeat && b.repeat > 1) ? (' <span class="pl-sug-rep">×' + b.repeat + '</span>') : '';
      var main = (b.repeat && b.repeat > 1) ? (b.repeat + ' × ' + dur) : dur;
      var tgt = (b.target || '') + (b.rest_min ? ' · ' + b.rest_min + 'min rest between' : '');
      return '<div class="pl-sug-ex-row"><span class="pl-sug-ex-name">' + esc(_phaseLabel(b.phase)) + '</span>' +
        '<span class="pl-sug-ex-detail">' + esc(main) + '</span>' + rep +
        '<span class="pl-sug-ex-load">' + esc(tgt) + '</span></div>';
    }).join('');
    return '<div class="pl-sug-exercises"><div class="pl-sug-ex-block">' + segs + '</div></div>';
  }

  function _buildSugRow(s, idx) {
    var dow = _DAY_NAMES[s.day_offset] || ('D' + s.day_offset);
    var tssStr = s.target_tss > 0 ? s.target_tss + ' TSS' : '';
    var durStr = s.duration_minutes > 0 ? s.duration_minutes + 'min' : '';
    var metaParts = [tssStr, durStr].filter(Boolean);
    var metaStr = metaParts.join(' · ');

    var wrap = document.createElement('div');
    wrap.className = 'pl-sug-row-wrap';
    wrap.dataset.idx = idx;

    var wt = (s.workout_type || 'rest').toLowerCase();
    var types = ['run', 'strength', 'plyo', 'rest'];

    wrap.innerHTML =
      '<div class="pl-sug-row">' +
        '<span class="pl-sug-day">' + dow + '</span>' +
        '<select class="pl-sug-type-select ' + wt + '" data-idx="' + idx + '">' +
          types.map(function (t) { return '<option value="' + t + '"' + (t === wt ? ' selected' : '') + '>' + t + '</option>'; }).join('') +
        '</select>' +
        (metaStr ? '<span class="pl-sug-meta">' + metaStr + '</span>' : '') +
        '<span class="pl-sug-intent">' + esc(s.intent || '') + '</span>' +
        (wt !== 'rest'
          ? '<span class="pl-sug-adjust">' +
              '<button type="button" class="pl-sug-adj" data-adj="lighter" data-idx="' + idx + '" title="Fewer sets/reps or shorter — not just a lower TSS number">▾ Lighter</button>' +
              '<button type="button" class="pl-sug-adj" data-adj="harder" data-idx="' + idx + '" title="More sets/reps or longer — not just a higher TSS number">▴ Harder</button>' +
              '<button type="button" class="pl-sug-refine-toggle" title="Regenerate this session with a note — e.g. change focus, faster intervals">✎ Refine</button>' +
            '</span>' +
            '<button class="pl-sug-add" type="button" data-idx="' + idx + '">Add</button>'
          : '') +
      '</div>' +
      (wt !== 'rest'
        ? '<div class="pl-sug-refine-panel" style="display:none;">' +
            '<input type="text" class="pl-sug-refine-input" placeholder="e.g. change focus to posterior chain, faster intervals..."/>' +
            '<button type="button" class="pl-sug-refine-go pl-btn pl-ghost">Regenerate</button>' +
            '<span class="pl-sug-refine-status"></span>' +
          '</div>'
        : '') +
      (s.notes ? '<div class="pl-sug-notes-line">' + esc(s.notes) + '</div>' : '') +
      _sugExercisesHtml(wt !== 'rest' ? s.exercises : null) +
      _sugBlocksHtml(wt === 'run' ? s.blocks : null);

    var typeSel = wrap.querySelector('.pl-sug-type-select');
    typeSel.addEventListener('change', function () {
      s.workout_type = typeSel.value;
      if (typeSel.value === 'rest') { s.target_tss = 0; s.duration_minutes = 0; }
      _renderSuggestions(_suggestionsData); // small list — cheap full re-render
    });

    wrap.querySelectorAll('.pl-sug-adj').forEach(function (btn) {
      btn.addEventListener('click', function () {
        _adjustSession(s, btn.getAttribute('data-adj') === 'harder');
        _renderSuggestions(_suggestionsData);
      });
    });

    var addBtn = wrap.querySelector('.pl-sug-add');
    if (addBtn) {
      addBtn.addEventListener('click', function () {
        _addSuggestion(s, addBtn);
      });
    }

    var refineToggle = wrap.querySelector('.pl-sug-refine-toggle');
    var refinePanel = wrap.querySelector('.pl-sug-refine-panel');
    if (refineToggle && refinePanel) {
      refineToggle.addEventListener('click', function () {
        var open = refinePanel.style.display === 'none';
        refinePanel.style.display = open ? '' : 'none';
        if (open) refinePanel.querySelector('.pl-sug-refine-input').focus();
      });
      var goBtn = refinePanel.querySelector('.pl-sug-refine-go');
      var statusEl = refinePanel.querySelector('.pl-sug-refine-status');
      goBtn.addEventListener('click', function () {
        var note = refinePanel.querySelector('.pl-sug-refine-input').value.trim();
        if (!note) { statusEl.textContent = 'Add a note first'; return; }
        goBtn.disabled = true; statusEl.textContent = 'Regenerating…';
        // Raw fetch, not _api() — that helper lives in the OTHER closure (the
        // main Plan-tab module above) and isn't reachable from here; this
        // closure's own convention is plain fetch (see _addSuggestion).
        fetch('/api/plan/suggestions/session', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            date: _formatSugDate(s.day_offset),
            workout_type: s.workout_type,
            note: note,
            current_session: s,
          }),
        })
          .then(function (r) {
            return r.json().then(function (d) {
              if (!r.ok) throw new Error((d && d.detail) || ('HTTP ' + r.status));
              return d;
            });
          })
          .then(function (data) {
            _suggestionsData.suggestions[idx] = data.session;
            _renderSuggestions(_suggestionsData); // small list — cheap full re-render
          })
          .catch(function (e) {
            statusEl.textContent = e.message || 'Could not regenerate — try again.';
            goBtn.disabled = false;
          });
      });
    }
    return wrap;
  }

  function _addSuggestion(s, btn) {
    btn.disabled = true;
    var dateIso = _formatSugDate(s.day_offset);
    var body = {
      planned_date: dateIso,
      session_type: s.workout_type,
      name: s.intent ? s.intent.substring(0, 80) : null,
    };
    // Prefer the LLM's own rationale (why this weight/exercise/pairing) when
    // present; otherwise fall back to the bare TSS/duration summary the
    // template path (no rationale) still provides.
    if (s.notes) {
      body.notes = s.notes;
    } else if (s.target_tss > 0 || s.duration_minutes > 0) {
      body.notes = [
        s.target_tss > 0 ? 'Target TSS: ' + s.target_tss : '',
        s.duration_minutes > 0 ? 'Duration: ' + s.duration_minutes + ' min' : ''
      ].filter(Boolean).join('. ');
    }
    // Carry the exercise/block breakdown into the planned session's structure
    // — same shape the manual Add-session form builder produces — so Add
    // creates a fully detailed session, not an empty shell to rebuild by hand.
    if (Array.isArray(s.exercises) && s.exercises.length) {
      body.structure = { exercises: s.exercises };
    } else if (Array.isArray(s.blocks) && s.blocks.length) {
      body.structure = { blocks: s.blocks };
    }

    fetch('/api/planned-sessions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function () {
        btn.textContent = '✓ Added';
        btn.classList.add('added');
        if (window.TrainingPlan && window.TrainingPlan.reload) window.TrainingPlan.reload();
      })
      .catch(function () {
        btn.disabled = false;
        btn.textContent = 'Retry';
      });
  }

  function _renderSuggestions(data) {
    _suggestionsData = data;
    var panel = _el('plan-suggestions-panel');
    var list = _el('plan-suggestions-list');
    var srcEl = _el('plan-suggestions-source');
    if (!panel || !list) return;

    var src = data.source || 'fallback';
    if (srcEl) srcEl.textContent = src === 'llm' ? 'AI' : 'template';

    list.innerHTML = '';
    var suggestions = data.suggestions || [];
    if (!suggestions.length) {
      list.innerHTML = '<span style="font-size:12px;color:var(--pl-muted);">Nothing left to suggest — the rest of this week is already scheduled.</span>';
    } else {
      suggestions.forEach(function (s, i) {
        list.appendChild(_buildSugRow(s, i));
      });
    }

    panel.style.display = '';
    var prefsEl = _el('plan-suggestions-prefs');
    if (prefsEl) prefsEl.innerHTML = '';
    var loading = _el('plan-suggestions-loading');
    if (loading) loading.style.display = 'none';
  }

  // ── Pre-generation preferences form ──────────────────────────────────────────
  // PRD feedback: generating blind (no visibility into what's already on the
  // schedule, no way to say "I want these days off" or "more strength this
  // week") produced suggestions the athlete had to fight with. Ask first.

  function _titleForOpenDays(openDays) {
    var titleEl = _el('plan-suggestions-title');
    if (!titleEl) return;
    var open = openDays.filter(function (d) { return d.open; });
    if (!open.length) { titleEl.textContent = 'Suggested sessions'; return; }
    var first = _DAY_NAMES_FULL[open[0].day_offset];
    var last = _DAY_NAMES_FULL[open[open.length - 1].day_offset];
    titleEl.textContent = open.length === 7
      ? 'Next week’s suggestions'
      : 'Suggestions for ' + (first === last ? first : first + '–' + last);
  }

  function _renderPrefsForm() {
    var host = _el('plan-suggestions-prefs');
    if (!host) return;
    var list = _el('plan-suggestions-list');
    if (list) list.innerHTML = '';
    var loading = _el('plan-suggestions-loading');
    if (loading) loading.style.display = 'none';

    var openDays = (window.TrainingPlan && window.TrainingPlan.getOpenDayInfo)
      ? window.TrainingPlan.getOpenDayInfo() : [];
    _titleForOpenDays(openDays);

    var dayChecks = openDays.map(function (d) {
      var checked = _lastPrefs.restDays.indexOf(d.day_offset) !== -1;
      return '<label class="pl-sug-daychk' + (d.open ? '' : ' is-closed') + '" title="' +
        (d.open ? 'Ask for this day off' : 'Already scheduled or in the past') + '">' +
        '<input type="checkbox" data-restday="' + d.day_offset + '"' +
        (checked ? ' checked' : '') + (d.open ? '' : ' disabled') + '/>' +
        '<span>' + _DAY_NAMES[d.day_offset] + '</span></label>';
    }).join('');

    var anyOpen = openDays.some(function (d) { return d.open; });

    host.innerHTML =
      '<div class="pl-sug-prefs">' +
        (anyOpen ? (
          '<div class="pl-sug-prefs-row">' +
            '<label class="pl-sug-prefs-label">Rest days</label>' +
            '<div class="pl-sug-daychks">' + dayChecks + '</div>' +
          '</div>' +
          '<div class="pl-sug-prefs-row">' +
            '<label class="pl-sug-prefs-label" for="pl-sug-emphasis">Strength this week</label>' +
            '<select id="pl-sug-emphasis" class="pl-sug-select">' +
              '<option value="less"' + (_lastPrefs.strengthEmphasis === 'less' ? ' selected' : '') + '>Less</option>' +
              '<option value="same"' + (_lastPrefs.strengthEmphasis === 'same' ? ' selected' : '') + '>Same</option>' +
              '<option value="more"' + (_lastPrefs.strengthEmphasis === 'more' ? ' selected' : '') + '>More</option>' +
            '</select>' +
          '</div>' +
          '<div class="pl-sug-prefs-row">' +
            '<label class="pl-sug-prefs-label" for="pl-sug-notes">Anything else the coach should know?</label>' +
            '<textarea id="pl-sug-notes" class="pl-sug-notes" placeholder="e.g. easing back after a cold, prioritize a long run Saturday…" maxlength="300">' + esc(_lastPrefs.notes) + '</textarea>' +
          '</div>' +
          '<div class="pl-btnrow"><button type="button" class="pl-btn pl-lime" id="pl-sug-generate">Generate suggestions</button>' +
          '<button type="button" class="pl-btn pl-ghost" id="pl-sug-cancel">Cancel</button></div>'
        ) : (
          '<div class="pl-infobanner">The rest of this week is already fully scheduled or logged — nothing left to suggest here. Use the week arrows to look at next week instead.</div>' +
          '<div class="pl-btnrow"><button type="button" class="pl-btn pl-ghost" id="pl-sug-cancel">Close</button></div>'
        )) +
      '</div>';

    host.querySelectorAll('[data-restday]').forEach(function (chk) {
      chk.addEventListener('change', function () {
        var off = +chk.getAttribute('data-restday');
        var i = _lastPrefs.restDays.indexOf(off);
        if (chk.checked && i === -1) _lastPrefs.restDays.push(off);
        else if (!chk.checked && i !== -1) _lastPrefs.restDays.splice(i, 1);
      });
    });
    var genBtn = _el('pl-sug-generate');
    if (genBtn) genBtn.addEventListener('click', function () {
      var emphasisEl = _el('pl-sug-emphasis');
      var notesEl = _el('pl-sug-notes');
      if (emphasisEl) _lastPrefs.strengthEmphasis = emphasisEl.value;
      if (notesEl) _lastPrefs.notes = notesEl.value;
      _loadSuggestions();
    });
    var cancelBtn = _el('pl-sug-cancel');
    if (cancelBtn) cancelBtn.addEventListener('click', _dismissPanel);
  }

  function _showPrefsForm() {
    var panel = _el('plan-suggestions-panel');
    if (panel) panel.style.display = '';
    _renderPrefsForm();
  }

  function _loadSuggestions() {
    var panel = _el('plan-suggestions-panel');
    var loading = _el('plan-suggestions-loading');
    var list = _el('plan-suggestions-list');
    if (!panel) return;
    panel.style.display = '';
    // Show the overlay ON TOP of whatever's already there (the prefs form, or
    // last time's suggestion list) — don't clear it first, so the panel never
    // goes blank while the LLM call is in flight.
    if (loading) loading.style.display = '';

    fetch('/api/plan/suggestions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        week_start: _weekStartISO(),
        rest_days: _lastPrefs.restDays,
        strength_emphasis: _lastPrefs.strengthEmphasis,
        notes: _lastPrefs.notes,
      }),
    })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(_renderSuggestions)
      .catch(function () {
        if (loading) loading.style.display = 'none';
        if (list) list.innerHTML = '<span style="font-size:12px;color:var(--pl-muted);">Could not load suggestions.</span>';
      });
  }

  function _dismissPanel() {
    _dismissed = true;
    var panel = _el('plan-suggestions-panel');
    if (panel) panel.style.display = 'none';
    // The bottom trigger row stays hidden — the "✨ Suggest sessions" button in
    // the week-pane header is the entry point now (it proxies a click to the
    // hidden #plan-suggestions-trigger).
  }

  function _initSuggestions() {
    var trigger = _el('plan-suggestions-trigger');
    var refresh = _el('plan-suggestions-refresh');
    var dismiss = _el('plan-suggestions-dismiss');

    if (trigger) {
      trigger.addEventListener('click', function () {
        _dismissed = false;
        _showPrefsForm();
      });
    }
    if (refresh) {
      refresh.addEventListener('click', function () {
        _dismissed = false;
        _showPrefsForm();
      });
    }
    if (dismiss) {
      dismiss.addEventListener('click', _dismissPanel);
    }
  }

  document.addEventListener('DOMContentLoaded', _initSuggestions);
}());
