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
  var _nextUpBundle = null;       // today→+20d for Next-up hero
  var _panel = { open: null };    // null | 'add' | 'detail'
  var _addState = { top: 'single', sub: 'form', delim: 'pipe' };
  // Create-mode draft-first: optional AI/manual content before Save draft.
  var _addDraftExtras = { ai: null, manualOpen: false };
  var _detail = null;             // the planned session dict being viewed
  var _dismissedGhosts = {};      // client-side Ignore
  var _draft = null;              // GET /api/plan/draft payload (pipeline v2)
  var _pipeline = null;           // GET /api/plan/pipeline
  var _draftVisible = false;      // shadow mode requires ?draft=1
  var _detailDraft = null;        // draft slot dict open in the detail panel
  var _generatingIds = {};        // planned_session id → true while Ask-AI fills details

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
      _applyUrlWeekParam();
      // Idempotent: always re-render the shell + reload the current week.
      _renderAll();
      _loadPipelineThenWeek(function () {
        if (_pendingOpenId) {
          var id = _pendingOpenId;
          _pendingOpenId = null;
          _openDetailById(id);
        }
      });
      _wireLoadPlanSettings();
      _loadLoadPlan();
      _loadWeekLoad(_iso(_weekStart));
      if (window.location.hash === '#prefs') {
        setTimeout(function () {
          var t = document.getElementById('plan-suggestions-trigger');
          if (t) t.click();
          var panel = document.getElementById('plan-suggestions-panel');
          if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
        }, 80);
      }
      if (!window.__plSmEscWired) {
        window.__plSmEscWired = true;
        document.addEventListener('keydown', function (e) {
          if (e.key === 'Escape' && _panel.open === 'detail') {
            e.preventDefault();
            _smTryClose();
          }
        });
      }
    },
    // Deep link from outside the Plan tab (e.g. the Log calendar): scope the
    // week to the session's date and flag it to open once init()'s own
    // _loadWeek resolves. Call BEFORE switching to the Plan tab, so init()
    // (triggered by the tab switch) picks up the right _weekStart/_pendingOpenId.
    openSession: function (sessionId, dateIso) {
      if (dateIso) _weekStart = _mondayOf(_parseISO(dateIso));
      _pendingOpenId = sessionId;
    },
    // Plan-guard helpers (issue #1383), exported for the suggestions module
    // — it is a SEPARATE closure below in this file, so bare references to
    // _planCheck/_planGuardHtml there throw ReferenceError (which killed
    // every suggestion "Add" click before the request even fired).
    planCheck: function (payload, cb) { _planCheck(payload, cb); },
    planGuardHtml: function (result) { return _planGuardHtml(result); },
    reload: function () {
      _loadWeek(function () { _loadDraft(); });
    },
    // Exposed for the Plan Suggestions module (a separate closure below) so it
    // scopes suggestions to whichever week is actually on screen, instead of
    // assuming "next Monday" regardless of what the athlete is looking at.
    getWeekStartISO: function () {
      return _iso(_weekStart || _mondayOf(new Date()));
    },
    // Suggestions module (separate closure) calls this after queueing a
    // plan_draft so the week strip picks up the new draft when it lands.
    // Both no-ops while drafts are parked (D1) — the suggestions module still
    // calls them, and a stub is cheaper than teaching it that drafts are gone.
    markDraftPending: function () {},
    reloadDraft: function () {},
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
        var past = i < offsetOfToday;
        var hasSession = hasPlanned || hasUnplanned;
        out.push({
          day_offset: i,
          date: day.date || _iso(_addDays(_weekStart, i)),
          past: past,
          hasSession: hasSession,
          // Suggestable open day: not past and no existing session/ghost
          open: !past && !hasSession,
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
    return window.AppCommon.todayISO();
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
  // Delegates to the shared escaper (issue #1603). The local copies
  // disagreed about the apostrophe, so identical content was safe on
  // some pages and attribute-injectable on others.
  function esc(s) {
    return window.AppCommon.escapeHtml(s);
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

  // ── Pipeline v2 draft overlay ───────────────────────────────────────────────
  function _urlFlag(name) {
    try {
      return new URLSearchParams(window.location.search).get(name);
    } catch (e) { return null; }
  }

  function _applyUrlWeekParam() {
    var w = _urlFlag('week');
    if (w) {
      try { _weekStart = _mondayOf(_parseISO(w)); } catch (e) { /* ignore */ }
    }
  }

  // PARKED (Priority 2, D1). Worker drafts are off: nothing enqueues a
  // plan_draft job and the worker no longer dispatches one, so there is never a
  // draft to overlay. This returns false unconditionally rather than depending
  // on _pipeline.ui_default / ?draft=1, so no server config or query param can
  // surface an overlay that can only ever be empty.
  //
  // The overlay's rendering code below is left in place, unreachable, for one
  // quiet release — it goes with plan_draft.py in the step-7 cleanup. Keeping
  // the gate a single function is what makes that deletion mechanical.
  function _shouldShowDraftUi() {
    return false;
  }

  function _loadPipelineThenWeek(onDone) {
    _api('GET', '/api/plan/pipeline')
      .then(function (p) {
        _pipeline = p || { mode: 'legacy', enabled: false, shadow: false, ui_default: false };
        _draftVisible = _shouldShowDraftUi();
        _loadWeek(function () {
          if (_draftVisible) _loadDraft(onDone);
          else if (onDone) onDone();
        });
      })
      .catch(function () {
        _pipeline = { mode: 'legacy', enabled: false, shadow: false, ui_default: false };
        _draftVisible = false;
        _loadWeek(onDone);
      });
  }

  function _loadDraft(onDone) {
    if (!_draftVisible) {
      _draft = null;
      if (onDone) onDone();
      return;
    }
    var ws = _iso(_weekStart);
    _api('GET', '/api/plan/draft?week_start=' + encodeURIComponent(ws))
      .then(function (d) {
        _draft = d;
        _renderDraftChrome();
        _renderWeekList();
        _updatePlanTabBadge(true);
        if (onDone) onDone();
      })
      .catch(function () {
        _draft = null;
        _renderDraftChrome();
        _renderWeekList();
        if (onDone) onDone();
      });
  }

  function _updatePlanTabBadge(ready) {
    var tab = document.getElementById('log-tab-plan');
    if (!tab) return;
    var badge = tab.querySelector('.pl-draft-badge');
    if (ready && _draft && (_draft.status === 'fresh' || _draft.status === 'outdated')) {
      if (!badge) {
        badge = document.createElement('span');
        badge.className = 'pl-draft-badge';
        badge.title = 'Week draft ready';
        badge.textContent = '•';
        tab.appendChild(badge);
      }
      badge.hidden = false;
    } else if (badge) {
      badge.hidden = true;
    }
  }

  function _draftSessionsByOffset() {
    var map = {};
    if (!_draft || !_draft.payload) return map;
    (_draft.payload.sessions || []).forEach(function (s) {
      if (s && s.day_offset != null) map[s.day_offset] = s;
    });
    return map;
  }

  function _sourceChip(src) {
    // Mock plan-draft-review.html: AI = green pill, user = dark, template = amber.
    var label = 'AI';
    var cls = 'ai';
    if (src === 'template') { label = 'TEMPLATE'; cls = 'tmpl'; }
    else if (src === 'user') { label = 'EDITED'; cls = 'user'; }
    else if (src === 'llm' || !src) { label = 'AI'; cls = 'ai'; }
    return '<span class="pl-src-chip pl-src-' + cls + '">' + label + '</span>';
  }

  // CSS border spinner — same as plan-draft-review.html STATE 4 (.spin / .src.gen i).
  function _genSpinHtml(cls) {
    return '<i class="' + (cls || 'pl-gen-spin') + '" aria-hidden="true"></i>';
  }
  function _generatingChipHtml() {
    return '<span class="pl-src-chip pl-src-gen" title="Content regenerating">' +
      _genSpinHtml() + 'GENERATING</span>';
  }

  function _draftCardHtml(s, day) {
    var fam = _famClass(s.workout_type);
    var typeLabel = fam === 'lift' ? 'LIFT' : fam.toUpperCase();
    var tss = s.target_tss != null ? Math.round(s.target_tss) : null;
    var pending = !!s.pending;
    var sid = s.slot_id || ('d' + s.day_offset);
    var title = s.intent || s.workout_type || 'Session';
    // Mock: title carries the slot budget ("Easy aerobic run → 70 TSS").
    if (pending && tss != null && title.indexOf(String(tss)) < 0) {
      title = title + (/\s*(→|->)\s*/.test(title) ? '' : ' → ' + tss + ' TSS');
    }
    var moveOpts = '';
    for (var d = 0; d < 7; d++) {
      if (d === s.day_offset) continue;
      moveOpts += '<option value="' + d + '">' + DOW[d] + '</option>';
    }
    var metaHtml = pending
      ? '<div class="pl-sm pl-sm-generating">content updating for the new budget…</div>'
      : (function () {
          var bits = [];
          if (s.duration_minutes) bits.push(s.duration_minutes + ' min');
          if (s.notes) bits.push(String(s.notes).slice(0, 48));
          else if (!s.duration_minutes && tss != null) bits.push(tss + ' TSS');
          return bits.length ? '<div class="pl-sm">' + esc(bits.join(' · ')) + '</div>' : '';
        })();
    // Horizontal row matching mock .sess.draft: TAG | title+meta | chips | acts
    var rightHtml = pending
      ? _generatingChipHtml()
      : (_sourceChip(s.source) +
          (tss != null ? '<span class="pl-draft-tss">' + tss + ' TSS</span>' : '') +
          '<label class="pl-draft-move"><select data-draft-move="' + esc(sid) + '" title="Move to…">' +
            '<option value="">Move to ▾</option>' + moveOpts + '</select></label>' +
          '<button type="button" class="pl-draft-rm" data-draft-rm="' + esc(sid) + '" title="Remove">Remove ✕</button>');
    return '<div class="pl-draft ' + fam + (pending ? ' is-pending' : '') + '" draggable="' + (pending ? 'false' : 'true') + '"' +
      ' data-draft-offset="' + s.day_offset + '" data-slot-id="' + esc(sid) + '" data-orig-idx="' + s.day_offset + '">' +
      '<span class="pl-stypetag ' + fam + '">' + typeLabel + '</span>' +
      '<div class="pl-draft-main"><div class="pl-sn">' + esc(title) + '</div>' + metaHtml + '</div>' +
      '<div class="pl-draft-right">' + rightHtml + '</div>' +
    '</div>';
  }

  function _draftOp(op, body) {
    body = body || {};
    body.week_start = _iso(_weekStart);
    if (_draft && _draft.draft_version) body.draft_version = _draft.draft_version;
    return fetch('/api/plan/draft/ops/' + op, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (r) {
      return r.json().then(function (res) {
        if (r.status === 409 && res && res.detail && res.detail.needs_confirm) {
          return Promise.reject({
            needs_confirm: true,
            warnings: res.detail.warnings || [],
            body: body,
            op: op,
          });
        }
        if (!r.ok) {
          var d = res && res.detail;
          return Promise.reject({ detail: typeof d === 'object' ? d : { error: d || ('HTTP ' + r.status) } });
        }
        // Some paths return the result object directly (ok:true)
        var payload = res.detail && res.detail.ok !== undefined ? res.detail : res;
        if (payload && payload.draft) {
          _draft = payload.draft;
          if (payload.draft_version) _draft.draft_version = payload.draft_version;
          _renderDraftChrome();
          _renderWeekList();
        }
        return payload;
      });
    });
  }

  // Styled-dialog reuse: training-log.js loads before this file on
  // training-log.html and exposes its shared .modal-overlay/.modal-box
  // confirm dialog on window.TrainingLog._confirmDialog. Fall back to the
  // native confirm() only if that's somehow unavailable.
  function _plConfirm(msg, onConfirm, opts) {
    if (window.TrainingLog && window.TrainingLog._confirmDialog) {
      window.TrainingLog._confirmDialog(msg, onConfirm, opts);
      return;
    }
    opts = opts || {};
    if (window.confirm(msg)) onConfirm();
    else if (opts.onCancel) opts.onCancel();
  }

  function _confirmWarnings(warnings, onYes) {
    var msg = (warnings || []).join('\n') + '\n\nProceed anyway?';
    _plConfirm(msg, function () { onYes(true); });
  }

  function _removeDraftSlot(slotId, sessionLabel) {
    var existing = document.getElementById('pl-draft-rm-overlay');
    if (existing) existing.remove();
    var label = sessionLabel || 'this draft session';
    var overlay = document.createElement('div');
    overlay.id = 'pl-draft-rm-overlay';
    overlay.className = 'pl-draft-q-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.innerHTML =
      '<div class="pl-draft-q-card">' +
        '<h3>Remove draft session?</h3>' +
        '<p>Remove <b>' + esc(label) + '</b> from the week draft.</p>' +
        '<p class="pl-draft-rm-hint">Default is drop only — other sessions keep their TSS and won’t regenerate.</p>' +
        '<div class="pl-del-confirm-actions" style="flex-direction:column;align-items:stretch;gap:8px;">' +
          '<button type="button" class="pl-btn pl-danger" data-rm-drop>Remove</button>' +
          '<button type="button" class="pl-btn pl-ghost" data-rm-redistribute>' +
            'Remove &amp; redistribute TSS' +
          '</button>' +
          '<button type="button" class="pl-btn" data-rm-cancel>Cancel</button>' +
        '</div>' +
        '<p class="pl-draft-rm-hint" style="margin-top:10px;">Redistribute spreads this session’s TSS onto other non-long draft slots and regenerates their content.</p>' +
      '</div>';
    document.body.appendChild(overlay);
    function close() { overlay.remove(); }
    overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
    overlay.querySelector('[data-rm-cancel]').addEventListener('click', close);

    function run(mode, btn) {
      btn.disabled = true;
      var other = overlay.querySelectorAll('[data-rm-drop], [data-rm-redistribute], [data-rm-cancel]');
      other.forEach(function (b) { b.disabled = true; });
      btn.textContent = mode === 'redistribute' ? 'Redistributing…' : 'Removing…';
      _draftOp('remove', { slot_id: slotId, mode: mode, confirm_warnings: true })
        .then(function (res) {
          close();
          if (mode === 'redistribute' && res && res.redistribute) {
            var m = res.redistribute;
            _toast(
              'Removed · redistributed ' + Math.round(m.replaced_tss || 0) +
              ' TSS' + (m.dropped_tss ? (' · ' + Math.round(m.dropped_tss) + ' unused') : '')
            );
          } else {
            _toast('Draft session removed');
          }
          if (_detailDraft && _detailDraft.slot_id === slotId) _closeDraftDetail();
        })
        .catch(function (err) {
          other.forEach(function (b) { b.disabled = false; });
          btn.disabled = false;
          btn.textContent = mode === 'redistribute' ? 'Remove & redistribute TSS' : 'Remove';
          if (err && err.needs_confirm) {
            _confirmWarnings(err.warnings, function () {
              err.body.confirm_warnings = true;
              _draftOp(err.op, err.body)
                .then(function () { close(); _toast('Draft session removed'); })
                .catch(function () { _toast('Remove failed', true); });
            });
            return;
          }
          _toast((err && err.detail && err.detail.block_reason) || 'Could not remove', true);
        });
    }

    overlay.querySelector('[data-rm-drop]').addEventListener('click', function (e) {
      run('drop', e.currentTarget);
    });
    overlay.querySelector('[data-rm-redistribute]').addEventListener('click', function (e) {
      run('redistribute', e.currentTarget);
    });
  }

  function _moveDraftSlot(slotId, toDay, confirmed) {
    _draftOp('move', { slot_id: slotId, to_day: toDay, confirm_warnings: !!confirmed })
      .catch(function (err) {
        if (err && err.needs_confirm) {
          _confirmWarnings(err.warnings, function () {
            _moveDraftSlot(slotId, toDay, true);
          });
          return;
        }
        var detail = err && err.detail;
        _toast((detail && (detail.block_reason || detail.error)) || 'Move blocked', true);
      });
  }

  function _addDraftKind(day, kind, btnEl) {
    if (btnEl) {
      btnEl.disabled = true;
      btnEl.dataset.label = btnEl.textContent;
      btnEl.innerHTML = '<i class="pl-gen-spin" aria-hidden="true"></i> Adding…';
    }
    var dayRow = document.querySelector('.pl-dayrow[data-day-offset="' + day + '"]');
    if (dayRow) dayRow.classList.add('is-draft-adding');
    function _restore() {
      if (dayRow) dayRow.classList.remove('is-draft-adding');
      if (btnEl && btnEl.dataset.label) {
        btnEl.disabled = false;
        btnEl.textContent = btnEl.dataset.label;
      }
    }
    _draftOp('add', { day: day, kind: kind, confirm_warnings: false })
      .then(function () { _restore(); })
      .catch(function (err) {
        if (err && err.needs_confirm) {
          _confirmWarnings(err.warnings, function () {
            _draftOp('add', { day: day, kind: kind, confirm_warnings: true })
              .then(_restore)
              .catch(function () { _restore(); _toast('Add failed', true); });
          });
          return;
        }
        _restore();
        var detail = err && err.detail;
        _toast((detail && detail.block_reason) || 'Could not add', true);
      });
  }

  function _addDraftCustom(day, custom, opts) {
    opts = opts || {};
    return _draftOp('add', {
      day: day,
      kind: 'custom',
      custom: custom,
      confirm_warnings: !!opts.confirm,
    }).then(function (payload) {
      var slotId = payload && payload.added_slot_id;
      if (!slotId) {
        // Fallback: newest non-rest session on that day after draft refresh.
        var sessions = ((_draft && _draft.payload) || {}).sessions || [];
        sessions.forEach(function (s) {
          if (s && parseInt(s.day_offset, 10) === parseInt(day, 10) && (s.workout_type || '') !== 'rest') {
            slotId = s.slot_id;
          }
        });
      }
      if (opts.apply && slotId) return _applyDraftSlot(slotId);
      if (opts.apply && !slotId) {
        return Promise.reject({ detail: { error: 'Draft saved but apply target missing' } });
      }
      return payload;
    }).catch(function (err) {
      if (err && err.needs_confirm && !opts.confirm) {
        return new Promise(function (resolve, reject) {
          _confirmWarnings(err.warnings, function () {
            _addDraftCustom(day, custom, Object.assign({}, opts, { confirm: true }))
              .then(resolve).catch(reject);
          });
        });
      }
      throw err;
    });
  }

  function _applyDraftSlot(slotId) {
    return _api('POST', '/api/plan/draft/apply-slot', {
      week_start: _iso(_weekStart),
      slot_id: slotId,
    }).then(function (res) {
      _toast('Session applied to plan');
      if (res && res.draft) {
        _draft = res.draft;
        _renderDraftChrome();
      }
      _closeDraftDetail();
      _loadWeek(function () { if (_draftVisible) _loadDraft(); });
      return res;
    });
  }

  function _regenDraftSlot(slotId) {
    return fetch('/api/plan/draft/ops/regen', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        week_start: _iso(_weekStart),
        slot_id: slotId,
        draft_version: _draft && _draft.draft_version,
      }),
    }).then(function (r) {
      return r.json().then(function (d) {
        if (!r.ok) throw new Error((d && d.detail && (d.detail.error || d.detail)) || ('HTTP ' + r.status));
        if (d.draft) {
          _draft = d.draft;
          if (d.draft_version) _draft.draft_version = d.draft_version;
          _renderDraftChrome();
          _renderWeekList();
          var sess = null;
          (((_draft || {}).payload || {}).sessions || []).forEach(function (s) {
            if (s && s.slot_id === slotId) sess = s;
          });
          if (sess && _detailDraft && _detailDraft.slot_id === slotId) {
            _detailDraft = sess;
            _renderDraftDetailSection();
          }
        }
        _toast('Details filled');
        return d;
      });
    });
  }

  function _dayOffsetForDate(isoDate) {
    if (!_weekStart) return 0;
    var d = _parseISO(isoDate);
    return Math.round((d - _weekStart) / 86400000);
  }

  function _openDraftAddPicker(isoDate) {
    var existing = document.getElementById('pl-draft-add-picker');
    if (existing) existing.remove();
    var day = _dayOffsetForDate(isoDate);
    var overlay = document.createElement('div');
    overlay.id = 'pl-draft-add-picker';
    overlay.className = 'pl-draft-q-overlay';
    overlay.innerHTML =
      '<div class="pl-draft-q-card" role="dialog" aria-modal="true">' +
        '<h3>Add draft session</h3>' +
        '<p>' + esc(isoDate) + ' — stays in the week draft until you apply.</p>' +
        '<label class="pl-dap-field">Type' +
          '<select id="pl-dap-type">' +
            '<option value="run">Run</option>' +
            '<option value="strength">Strength</option>' +
            '<option value="plyo">Plyo</option>' +
            '<option value="stretch">Stretch</option>' +
          '</select></label>' +
        '<div class="pl-dap-row">' +
          '<label class="pl-dap-field">TSS<input id="pl-dap-tss" type="number" min="0" max="400" value="30"/></label>' +
          '<label class="pl-dap-field">Minutes<input id="pl-dap-dur" type="number" min="0" max="600" value="30"/></label>' +
        '</div>' +
        '<label class="pl-dap-field">Name / intent<input id="pl-dap-intent" type="text" placeholder="Optional"/></label>' +
        '<div class="pl-draft-q-actions">' +
          '<button type="button" class="pl-btn pl-lime" id="pl-dap-draft">Create draft</button>' +
          '<button type="button" class="pl-btn" id="pl-dap-apply">Create draft &amp; apply</button>' +
        '</div>' +
        '<button type="button" class="pl-btn pl-ghost" id="pl-dap-cancel" style="margin-top:8px;width:100%">Cancel</button>' +
      '</div>';
    document.body.appendChild(overlay);
    function close() { overlay.remove(); }
    overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
    document.getElementById('pl-dap-cancel').onclick = close;
    function readCustom() {
      var wt = document.getElementById('pl-dap-type').value;
      return {
        workout_type: wt,
        subtype: wt,
        target_tss: parseFloat(document.getElementById('pl-dap-tss').value) || 0,
        duration_minutes: parseInt(document.getElementById('pl-dap-dur').value, 10) || 30,
        intent: (document.getElementById('pl-dap-intent').value || '').trim(),
      };
    }
    function run(apply) {
      var btn = document.getElementById(apply ? 'pl-dap-apply' : 'pl-dap-draft');
      btn.disabled = true;
      btn.textContent = apply ? 'Applying…' : 'Adding…';
      _addDraftCustom(day, readCustom(), { apply: !!apply })
        .then(function () { close(); _toast(apply ? 'Draft applied' : 'Draft added'); })
        .catch(function (err) {
          btn.disabled = false;
          btn.textContent = apply ? 'Create draft & apply' : 'Create draft';
          var detail = err && err.detail;
          _toast((detail && (detail.block_reason || detail.error)) || (err && err.message) || 'Failed', true);
        });
    }
    document.getElementById('pl-dap-draft').onclick = function () { run(false); };
    document.getElementById('pl-dap-apply').onclick = function () { run(true); };
  }

  function _openDraftDetail(slotId) {
    var found = null;
    (((_draft || {}).payload || {}).sessions || []).forEach(function (s) {
      if (s && s.slot_id === slotId) found = s;
    });
    if (!found || (found.workout_type || '') === 'rest') return;
    _detail = null;
    _detailDraft = Object.assign({}, found);
    _panel.open = 'detail';
    _renderDraftDetailSection();
    var el = document.getElementById('plan-detail-section');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function _closeDraftDetail() {
    _detailDraft = null;
    if (!_detail) {
      _panel.open = null;
      var host = document.getElementById('plan-detail-section');
      if (host) host.innerHTML = '';
    }
  }

  function _renderDraftDetailSection() {
    var host = document.getElementById('plan-detail-section');
    if (!host || !_detailDraft) return;
    var s = _detailDraft;
    var pending = !!s.pending;
    host.innerHTML =
      '<div class="pl-card pl-panelcard">' +
        '<div class="pl-chead"><span class="pl-sectitle">Draft session</span>' +
          '<button type="button" class="pl-btn pl-ghost" id="pl-dd-close">Close</button></div>' +
        '<div class="pl-dd-grid">' +
          '<label>Type<select id="pl-dd-type">' +
            ['run','strength','plyo','stretch'].map(function (t) {
              return '<option value="' + t + '"' + (s.workout_type === t ? ' selected' : '') + '>' + t + '</option>';
            }).join('') +
          '</select></label>' +
          '<label>TSS<input id="pl-dd-tss" type="number" min="0" max="400" value="' + (s.target_tss != null ? s.target_tss : '') + '"/></label>' +
          '<label>Minutes<input id="pl-dd-dur" type="number" min="0" max="600" value="' + (s.duration_minutes != null ? s.duration_minutes : '') + '"/></label>' +
        '</div>' +
        '<label class="pl-dd-block">Intent / name<input id="pl-dd-intent" type="text" value="' + esc(s.intent || '') + '"/></label>' +
        '<label class="pl-dd-block">Notes<textarea id="pl-dd-notes" rows="3">' + esc(s.notes || '') + '</textarea></label>' +
        (pending
          ? '<div class="pl-draft-pending" style="display:flex">' + _genSpinHtml('pl-gen-spin pl-gen-spin-lg') + ' Generating details…</div>'
          : '') +
        '<div class="pl-dd-actions">' +
          '<button type="button" class="pl-btn pl-lime" id="pl-dd-save">Save draft</button>' +
          '<button type="button" class="pl-btn" id="pl-dd-gen"' + (pending ? ' disabled' : '') + '>Generate details</button>' +
          '<button type="button" class="pl-btn pl-dark" id="pl-dd-apply">Apply this session</button>' +
        '</div>' +
      '</div>';

    document.getElementById('pl-dd-close').onclick = function () {
      _closeDraftDetail();
      _renderDetailSection();
    };
    document.getElementById('pl-dd-save').onclick = function () {
      var patch = {
        week_start: _iso(_weekStart),
        day_offset: s.day_offset,
        workout_type: document.getElementById('pl-dd-type').value,
        target_tss: parseFloat(document.getElementById('pl-dd-tss').value) || 0,
        duration_minutes: parseInt(document.getElementById('pl-dd-dur').value, 10) || 0,
        intent: document.getElementById('pl-dd-intent').value,
        notes: document.getElementById('pl-dd-notes').value || null,
      };
      _api('PATCH', '/api/plan/draft/slot', patch)
        .then(function (d) {
          _draft = d;
          _toast('Draft saved');
          var refreshed = null;
          (((_draft || {}).payload || {}).sessions || []).forEach(function (x) {
            if (x && x.slot_id === s.slot_id) refreshed = x;
          });
          if (refreshed) _detailDraft = refreshed;
          _renderWeekList();
          _renderDraftDetailSection();
        })
        .catch(function (err) { _toast(err.message || 'Save failed', true); });
    };
    document.getElementById('pl-dd-gen').onclick = function () {
      _regenDraftSlot(s.slot_id).catch(function (err) {
        _toast(err.message || 'Could not queue generation', true);
      });
    };
    document.getElementById('pl-dd-apply').onclick = function () {
      _applyDraftSlot(s.slot_id).catch(function (err) {
        var d = err && err.message;
        _toast(d || 'Apply failed', true);
      });
    };
  }

  function _renderDraftChrome() {
    var banner = document.getElementById('pl-draft-banner');
    var applyBtn = document.getElementById('pl-apply-draft');
    var refreshBtn = document.getElementById('pl-refresh-draft');
    var pendingBar = document.getElementById('pl-draft-pending');
    if (!_draftVisible || !_draft || _draft.status === 'applied') {
      if (banner) banner.hidden = true;
      if (applyBtn) applyBtn.hidden = true;
      if (refreshBtn) refreshBtn.hidden = true;
      if (pendingBar) pendingBar.hidden = true;
      return;
    }
    if (applyBtn) applyBtn.hidden = false;
    if (refreshBtn) refreshBtn.hidden = false;
    var sessions = (_draft.payload && _draft.payload.sessions) || [];
    var pendingN = sessions.filter(function (s) { return s && s.pending; }).length;
    if (pendingBar) {
      if (pendingN > 0) {
        pendingBar.hidden = false;
        pendingBar.innerHTML =
          '<span class="pl-gen-spin pl-gen-spin-lg" aria-hidden="true"></span>' +
          '<span>Regenerating ' + pendingN + ' session' + (pendingN === 1 ? '' : 's') +
          '…</span>';
      } else {
        pendingBar.hidden = true;
        pendingBar.innerHTML = '';
      }
    }
    if (banner) {
      if (_draft.status === 'outdated') {
        banner.hidden = false;
        banner.innerHTML = 'Plan inputs changed — <button type="button" class="pl-draft-link" id="pl-draft-banner-refresh">refresh draft?</button> Untouched slots only.';
        var br = document.getElementById('pl-draft-banner-refresh');
        if (br) br.onclick = _refreshDraft;
      } else {
        banner.hidden = true;
      }
    }
  }

  function _refreshDraft() {
    _api('POST', '/api/plan/draft/refresh', { week_start: _iso(_weekStart) })
      .then(function (res) {
        if (res && res.draft) _draft = res.draft;
        _toast('Draft refreshed');
        _loadDraft();
      })
      .catch(function () { _toast('Could not refresh draft', true); });
  }

  function _applyDraftWeek() {
    var btn = document.getElementById('pl-apply-draft');
    if (btn) btn.disabled = true;
    _api('POST', '/api/plan/draft/apply', { week_start: _iso(_weekStart) })
      .then(function (res) {
        var n = (res && res.created) ? res.created.length : 0;
        _toast(n ? ('Applied ' + n + ' session' + (n === 1 ? '' : 's')) : 'Draft applied');
        if (btn) btn.disabled = false;
        _draft = null;
        _loadWeek(function () { _loadDraft(); });
        _updatePlanTabBadge(false);
      })
      .catch(function () {
        if (btn) btn.disabled = false;
        _toast('Could not apply draft', true);
      });
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
        _loadNextUpRange();
        // Keep an open detail panel in sync with the freshly loaded bundle
        // (a mutation triggered from inside the panel doesn't otherwise
        // refresh it, since it renders from _detail, not _bundle).
        if (_detail) {
          var updated = null;
          (_bundle.days || []).forEach(function (d) {
            (d.planned || []).forEach(function (p) { if (p.id === _detail.id) updated = p; });
          });
          if (!updated) {
            _closeDetail();
          } else if (_sm.dirty) {
            // Keep in-progress edits; only refresh server-owned status fields.
            _detail.status = updated.status;
            _detail.matched_workout_id = updated.matched_workout_id;
            _detail.actual = updated.actual;
            _renderDetailSection();
          } else {
            _detail = updated;
            _smSeedBuilders(updated);
            _sm.suppressDomSync = true;
            _renderDetailSection();
            _sm.baseline = _smReadDraftFromDom(updated);
            _sm.dirty = false;
            _smMarkDirty();
          }
        }
        // Every planned-session mutation funnels through _loadWeek — refresh
        // the Session-load card's planned/projected numbers in the same
        // breath, so adding/editing a session recalculates the week TSS
        // immediately instead of waiting for a page reload.
        _loadWeekLoad(_iso(_weekStart));
        if (onDone) onDone();
      })
      .catch(function () {
        if (host) host.innerHTML = '<div class="pl-loading">Could not load the week.</div>';
        if (onDone) onDone();
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
  var PHASE_LABEL = { ramp: 'Target — ramp', hold: 'Target — peak hold', taper: 'Target — taper', race: 'Race week', consolidation: 'Target — consolidation' };
  var VERDICT_LABEL = { back_off: 'Back off', hold: 'Hold', build: 'Build' };

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
      var setlineEmpty = document.getElementById('lp-setline');
      if (setlineEmpty) setlineEmpty.hidden = true;
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

    var setline = document.getElementById('lp-setline');
    var setlineText = document.getElementById('lp-setline-text');
    if (setline && setlineText) {
      setline.hidden = false;
      setlineText.innerHTML =
        '<b>' + esc(String(_lpData.weeks_to_race)) + ' wks</b> to ' + esc(_lpData.race.name) +
        ' <span>·</span> ramp <b>+' + esc(_fmtPct1(_lpData.ramp_rate)) + '</b>' +
        ' <span>·</span> peak <b>' + Math.round(_lpData.peak) + '</b>';
    }

    if (warnEl) {
      // Two independent informational banners can both be true at once
      // (a degenerate ramp/hold/taper config AND a capped baseline) — join
      // them rather than picking one, since a silent cap is worse than no
      // cap (docs/calculations/load-plan.md "Baseline cap").
      var msgs = [];
      if (_lpData.warning) msgs.push(_lpData.warning);
      if (_lpData.baseline_capped) {
        msgs.push(
          'Baseline capped: seed (' + Math.round(_lpData.baseline_tss) +
          ') exceeded ACWR band vs chronic; using ' + Math.round(_lpData.capped_baseline_tss) + '.'
        );
      }
      if (msgs.length) { warnEl.hidden = false; warnEl.textContent = msgs.join(' '); }
      else warnEl.hidden = true;
    }

    _renderLoadPlanChart();
    _renderWeekBudget();

    if (legend) {
      legend.hidden = false;
      var hasConsolidation = (_lpData.weeks || []).some(function (w) { return w.phase === 'consolidation'; });
      legend.innerHTML =
        _legendItem('#4f6ef7', 'Actual (logged)') +
        _legendItem('#e6ebfe', 'Target — ramp', '#4f6ef7') +
        _legendItem('#e4e9fd', 'Target — peak hold', '#6d87f8') +
        _legendItem('#fdf3da', 'Target — taper', '#d97706') +
        _legendItem('#fee2e2', 'Race week', '#dc2626') +
        (hasConsolidation ? _legendItem('#f6f7fb', 'Consolidation (hold/back off)', '#6b7280') : '');
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

  function _isMobilePlanLayout() {
    return typeof window.matchMedia === 'function' && window.matchMedia('(max-width: 1039.98px)').matches;
  }

  function _barKind(w, isPrior) {
    if (isPrior) return 'actual' + (w.deload ? ' is-deload' : '');
    var cls = 'target phase-' + (w.phase || 'ramp');
    if (w.clamped) cls += ' is-clamped';
    if (w.deload) cls += ' is-deload';
    return cls;
  }

  function _phaseStripHtml(series) {
    // Collapse consecutive same-phase weeks into strips (desktop full chart).
    var segs = [];
    series.forEach(function (item) {
      var phase = item.isPrior ? 'prior' : (item.w.phase || 'ramp');
      var last = segs[segs.length - 1];
      if (last && last.phase === phase) { last.w += 1; return; }
      segs.push({ phase: phase, w: 1 });
    });
    return '<div class="lp-phasebar">' + segs.map(function (s) {
      if (s.phase === 'prior') return '<div class="lp-ph lp-ph-prior" style="flex:' + s.w + '"></div>';
      var lab = s.phase === 'hold' ? ('PEAK HOLD · ' + s.w + ' WKS')
        : s.phase === 'taper' ? 'TAPER'
        : s.phase === 'race' ? 'RACE'
        : s.phase === 'consolidation' ? 'HOLD'
        : 'BUILD';
      var cls = s.phase === 'hold' ? 'peakp' : s.phase === 'taper' ? 'taperp'
        : s.phase === 'race' ? 'racep' : 'build';
      return '<div class="lp-ph ' + cls + '" style="flex:' + s.w + '">' + lab + '</div>';
    }).join('') + '</div>';
  }

  function _mobileAheadChips(weeks, race) {
    var hold = weeks.filter(function (w) { return w.phase === 'hold'; });
    var taper = weeks.filter(function (w) { return w.phase === 'taper' || w.phase === 'race'; });
    var chips = [];
    if (hold.length) {
      chips.push('<div class="lp-amini peak"><div class="k">Peak hold</div><div class="v">' +
        Math.round(hold[0].target_tss) + '</div><div class="s">' + hold.length + ' wks · ' +
        _fmtShortDate(hold[0].week_start) + '</div></div>');
    }
    if (taper.length) {
      var first = taper[0], last = taper[taper.length - 1];
      chips.push('<div class="lp-amini tap"><div class="k">Taper</div><div class="v">' +
        Math.round(first.target_tss) + '→' + Math.round(last.target_tss) +
        '</div><div class="s">' + taper.length + ' wks · ' + _fmtShortDate(first.week_start) + '</div></div>');
    }
    if (race) {
      chips.push('<div class="lp-amini race"><div class="k">Race day</div><div class="v">' +
        esc(_fmtShortDate(race.date)) + '</div><div class="s">' + esc(race.name) + '</div></div>');
    }
    return chips.length ? ('<div class="lp-ahead">' + chips.join('') + '</div>') : '';
  }

  function _currentPhaseLabel(weeks) {
    var cur = null, idx = 0, total = 0;
    for (var i = 0; i < weeks.length; i++) {
      if (weeks[i].week_index === 1) { cur = weeks[i]; break; }
    }
    if (!cur) cur = weeks[0];
    if (!cur) return '';
    var phase = cur.phase || 'ramp';
    weeks.forEach(function (w) {
      if (w.phase === phase) total += 1;
    });
    // Position within phase: count weeks of this phase up to and including current
    var pos = 0;
    for (var j = 0; j < weeks.length; j++) {
      if (weeks[j].phase !== phase) continue;
      pos += 1;
      if (weeks[j].week_start === cur.week_start) break;
    }
    var name = phase === 'hold' ? 'PEAK HOLD' : phase === 'taper' ? 'TAPER'
      : phase === 'race' ? 'RACE' : phase === 'consolidation' ? 'HOLD' : 'BUILD';
    return '<div class="lp-phasenow"><div class="lp-ph">' + name + ' · WEEK ' + pos + ' OF ' + total + '</div></div>';
  }

  function _renderLoadPlanChart() {
    var host = document.getElementById('lp-chart-wrap');
    if (!host) return;
    host.hidden = false;

    var prior = _lpData.prior_weeks || [];
    var weeks = _lpData.weeks || [];
    if (!prior.length && !weeks.length) { host.innerHTML = ''; return; }

    var series = prior.map(function (p) { return { w: p, isPrior: true }; })
      .concat(weeks.map(function (w) { return { w: w, isPrior: false }; }));

    var mobile = _isMobilePlanLayout();
    var view = series;
    var thisIdx = -1;
    series.forEach(function (item, i) {
      if (!item.isPrior && item.w.week_index === 1) thisIdx = i;
    });
    if (mobile && thisIdx >= 0) {
      var from = Math.max(0, thisIdx - 2);
      var to = Math.min(series.length, thisIdx + 3);
      view = series.slice(from, to);
    }

    var allValues = view.map(function (item) {
      return item.isPrior ? item.w.actual_tss : item.w.target_tss;
    });
    var maxVal = Math.max.apply(null, allValues.concat([1]));

    var barsHtml = view.map(function (item) {
      var val = item.isPrior ? item.w.actual_tss : item.w.target_tss;
      var h = Math.max(6, (val / maxVal) * 100);
      var kind = _barKind(item.w, item.isPrior);
      var isNow = !item.isPrior && item.w.week_index === 1;
      var d = _parseISO(item.w.week_start);
      var dLab = d.getDate() + ' ' + MON[d.getMonth()];
      var tip = dLab + ' · ' + Math.round(val) + ' TSS';
      return '<div class="lp-bar-col' + (isNow ? ' is-this-week' : '') + '" title="' + esc(tip) + '">' +
        '<div class="lp-bar ' + kind + '" style="height:' + h + '%">' +
        (item.w.deload ? '<span class="lp-deload-arrow" aria-hidden="true">▼</span>' : '') +
        '<span class="lp-bar-value">' + Math.round(val) + '</span></div>' +
        '<span class="lp-bar-d">' + esc(dLab) + '</span></div>';
    }).join('');

    var mobileExtra = '';
    if (mobile) {
      var weeksAhead = Math.max(0, weeks.length - 1);
      mobileExtra =
        _currentPhaseLabel(weeks) +
        (weeksAhead > 0 ? '<div class="lp-divider"><span>' + weeksAhead + ' weeks ahead</span></div>' : '') +
        _mobileAheadChips(weeks, _lpData.race) +
        '<button type="button" class="lp-fullink" id="lp-full-chart-btn">Full season chart →</button>';
    }

    host.innerHTML =
      '<div class="lp-bars' + (mobile ? ' is-windowed' : '') + '">' + barsHtml + '</div>' +
      (mobile ? '' : _phaseStripHtml(series)) +
      mobileExtra;

    var fullBtn = document.getElementById('lp-full-chart-btn');
    if (fullBtn) fullBtn.onclick = function () { _openFullSeasonSheet(); };
  }

  function _openFullSeasonSheet() {
    if (!_lpData) return;
    var existing = document.getElementById('lp-full-sheet');
    if (existing) existing.remove();
    var prior = _lpData.prior_weeks || [];
    var weeks = _lpData.weeks || [];
    var series = prior.map(function (p) { return { w: p, isPrior: true }; })
      .concat(weeks.map(function (w) { return { w: w, isPrior: false }; }));
    var allValues = series.map(function (item) {
      return item.isPrior ? item.w.actual_tss : item.w.target_tss;
    });
    var maxVal = Math.max.apply(null, allValues.concat([1]));
    var bars = series.map(function (item) {
      var val = item.isPrior ? item.w.actual_tss : item.w.target_tss;
      var h = Math.max(6, (val / maxVal) * 100);
      var d = _parseISO(item.w.week_start);
      var dLab = d.getDate() + ' ' + MON[d.getMonth()];
      var isNow = !item.isPrior && item.w.week_index === 1;
      return '<div class="lp-bar-col' + (isNow ? ' is-this-week' : '') + '" title="' + esc(dLab + ' · ' + Math.round(val) + ' TSS') + '">' +
        '<div class="lp-bar ' + _barKind(item.w, item.isPrior) + '" style="height:' + h + '%">' +
        '<span class="lp-bar-value">' + Math.round(val) + '</span></div>' +
        '<span class="lp-bar-d">' + esc(dLab) + '</span></div>';
    }).join('');
    var sheet = document.createElement('div');
    sheet.id = 'lp-full-sheet';
    sheet.className = 'lp-full-sheet';
    sheet.innerHTML =
      '<div class="lp-full-sheet-card" role="dialog" aria-modal="true" aria-label="Full season chart">' +
        '<div class="lp-full-sheet-head"><span>Full season chart</span>' +
          '<button type="button" class="lp-full-sheet-close" id="lp-full-sheet-close" aria-label="Close">✕</button></div>' +
        '<div class="lp-bars">' + bars + '</div>' +
        _phaseStripHtml(series) +
      '</div>';
    document.body.appendChild(sheet);
    function close() { sheet.remove(); }
    sheet.addEventListener('click', function (e) { if (e.target === sheet) close(); });
    document.getElementById('lp-full-sheet-close').onclick = close;
  }

  function _isoAddDays(iso, n) {
    var d = _parseISO(iso);
    d.setDate(d.getDate() + n);
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
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
      var deloadEl = document.getElementById('lp-recovery-toggle');
      if (deloadEl) deloadEl.checked = !!_lpData.deload_enabled;
      var deloadWeekEl = document.getElementById('lp-deload-week-select');
      if (deloadWeekEl) deloadWeekEl.value = String(_lpData.deload_start_week || 4);
      _syncDeloadWeekRow();
      _renderWeekBudget();
    }
  }

  // The deload-week picker only means anything while the deload toggle is
  // on — hide the row entirely otherwise.
  function _syncDeloadWeekRow() {
    var row = document.getElementById('lp-deload-week-row');
    var deloadEl = document.getElementById('lp-recovery-toggle');
    if (row) row.hidden = !(deloadEl && deloadEl.checked);
  }

  function _setNum(id, val) {
    var el = document.getElementById(id);
    if (el) el.value = val;
  }

  function _saveLoadPlanRules() {
    var rampIn = document.getElementById('lp-ramp-input');
    var holdIn = document.getElementById('lp-hold-input');
    var taperIn = document.getElementById('lp-taper-input');
    var deloadIn = document.getElementById('lp-recovery-toggle');
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

    var deloadWeekIn = document.getElementById('lp-deload-week-select');
    _api('PUT', '/api/plan/rules', {
      ramp_rate: rampPct / 100, hold_weeks: hold, taper_weeks: taper,
      deload_enabled: deloadIn ? !!deloadIn.checked : false,
      deload_start_week: deloadWeekIn ? parseInt(deloadWeekIn.value, 10) || 4 : 4,
    })
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
    var deloadToggle = document.getElementById('lp-recovery-toggle');
    var setline = document.getElementById('lp-setline');
    if (cogBtn) cogBtn.onclick = _toggleLoadPlanSettings;
    if (deloadToggle) deloadToggle.onchange = _syncDeloadWeekRow;
    if (rampSlider) rampSlider.oninput = function () { if (rampInput) rampInput.value = rampSlider.value; };
    if (rampInput) rampInput.oninput = function () { if (rampSlider) rampSlider.value = rampInput.value; };
    if (saveBtn) saveBtn.onclick = _saveLoadPlanRules;
    if (setline) setline.onclick = function () {
      var strip = document.getElementById('lp-rules-strip');
      if (!strip) return;
      var open = strip.classList.toggle('is-open');
      setline.setAttribute('aria-expanded', open ? 'true' : 'false');
      setline.classList.toggle('is-open', open);
    };
    if (!window.__plChartResizeWired) {
      window.__plChartResizeWired = true;
      var t = null;
      window.addEventListener('resize', function () {
        clearTimeout(t);
        t = setTimeout(function () {
          if (_lpData) _renderLoadPlanChart();
        }, 150);
      });
    }
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
    // Refresh the week-plan card's target-dependent bits (header total,
    // "Suggest sessions" label, banner) whenever fresh data arrives —
    // regardless of whether the Session-load-this-week card itself is on
    // screen, since both read from the same _wlData.
    _updateWeekTargetUI();

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
    _setText('wl-target-val', '/' + Math.round(d.target_tss));
    _renderNextUp(); // Of-week share uses target_tss

    var projEl = document.getElementById('wl-target-projected');
    if (projEl) {
      // Status by severity: over the ACWR guardrail = red "warning"; over
      // the week target = orange "over target"; otherwise blue "on target".
      var proj = d.projected_tss != null ? d.projected_tss : null;
      var status = 'on';
      if (proj != null && d.acwr_ceiling != null && proj > d.acwr_ceiling) status = 'danger';
      else if (proj != null && proj > d.target_tss) status = 'over';
      projEl.className = 'wl-target-projected wl-proj-' + status;
      projEl.textContent = proj != null ? Math.round(proj) : '';
      var statusPill = document.getElementById('wl-proj-status');
      if (statusPill) {
        statusPill.className = 'wl-proj-pill wl-proj-' + status;
        statusPill.textContent = status === 'danger' ? 'warning' : (status === 'over' ? 'over target' : 'on target');
        statusPill.hidden = proj == null;
      }
    }

    // Deterministic verdict (backend/services/training_verdict.py) — never
    // an LLM decision. Only shown for hold/back_off (build is the default,
    // unremarkable state — no need to announce it every week).
    var verdictRow = document.getElementById('wl-verdict-row');
    if (verdictRow) {
      if (d.verdict && d.verdict !== 'build') {
        verdictRow.hidden = false;
        var vPill = document.getElementById('wl-verdict-pill');
        if (vPill) {
          vPill.className = 'wl-verdict-pill ' + d.verdict;
          vPill.textContent = VERDICT_LABEL[d.verdict] || d.verdict;
        }
        var vReason = document.getElementById('wl-verdict-reason');
        if (vReason) {
          var extra = (d.weeks_to_converge && d.converge_date)
            ? ' · back to normal in ~' + d.weeks_to_converge + ' wk (' + _fmtShortDate(d.converge_date) + ')'
            : '';
          vReason.textContent = (d.verdict_reason || '') + extra;
        }
      } else {
        verdictRow.hidden = true;
      }
    }

    var baselineEl = document.getElementById('wl-baseline-val');
    if (baselineEl) {
      // A silent cap reads as "the ramp is broken" — say so plainly
      // (docs/calculations/load-plan.md "Baseline cap") rather than just
      // showing the lower capped number with no explanation.
      if (d.baseline_capped) {
        baselineEl.innerHTML = Math.round(d.capped_baseline_tss) + ' TSS <span class="wl-baseline-capped" title="Seed (' +
          Math.round(d.baseline_tss) + ' TSS = max(logged, planned)) exceeded ACWR band vs chronic — capped to ' +
          Math.round(d.capped_baseline_tss) + ' TSS so the ramp does not compound the spike.">(capped)</span>';
      } else {
        baselineEl.textContent = Math.round(d.baseline_tss) + ' TSS';
      }
    }
    var rampPct = (d.ramp_rate * 100).toFixed(1).replace(/\.0$/, '') + '%';
    var rampCell = document.getElementById('wl-ramp-cell');
    var deloadSub = document.getElementById('wl-deload-sub');
    if (d.deload) {
      // Deload week: the chain is baseline × ramp × (1 − cut), not the plain
      // ramp — show the cut or the target looks broken next to "5%".
      var cutPct = Math.round((d.deload_cut || 0.3) * 100);
      _setText('wl-ramp-lab', 'Ramp − deload');
      _setText('wl-ramp-val', rampPct + ' − ' + cutPct + '%');
      if (deloadSub) {
        deloadSub.hidden = false;
        deloadSub.textContent = 'deload week — cut ' + cutPct + '% before the ceiling';
      }
      if (rampCell) rampCell.classList.add('is-deload');
    } else {
      _setText('wl-ramp-lab', 'Ramp');
      _setText('wl-ramp-val', rampPct);
      if (deloadSub) { deloadSub.hidden = true; deloadSub.textContent = ''; }
      if (rampCell) rampCell.classList.remove('is-deload');
    }
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
      'planned ' + Math.round(d.baseline_planned_tss) + ' · logged ' +
        Math.round(d.baseline_logged_tss != null ? d.baseline_logged_tss : d.baseline_tss),
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
        '<span><span class="sw" style="background:var(--primary)"></span>Logged ' + Math.round(d.logged_tss) + '</span>' +
        '<span><span class="sw" style="background:repeating-linear-gradient(45deg,var(--primary-soft) 0 3px,transparent 3px 6px),rgba(79,110,247,0.18)"></span>Planned ' + Math.round(d.planned_tss) + '</span>' +
        '<span>Projected ' + Math.round(d.projected_tss) + ' / ' + Math.round(d.target_tss) + ' TSS' +
          (d.clamped ? ' &middot; <span style="color:var(--warning);font-weight:700;">clamped</span>' : '') + '</span>';
    }
  }

  // ── Render shell ────────────────────────────────────────────────────────────

  // ── Next up hero (§1) ───────────────────────────────────────────────────────
  function _isOpenPlanned(p) {
    if (!p || p.session_type === 'rest') return false;
    var s = p.status || 'planned';
    if (s === 'done_auto' || s === 'done_manual') return false;
    if (s === 'missed' || s === 'missed_auto' || s === 'missed_manual') return false;
    return true;
  }

  function _fmtHeroDate(iso) {
    var d = _parseISO(iso);
    var dow = DOW[(d.getDay() + 6) % 7];
    var short = dow.charAt(0) + dow.slice(1).toLowerCase() + ' ' + d.getDate() + ' ' + MON[d.getMonth()];
    if (iso === _todayISO()) return short + ' · today';
    return short;
  }

  function _fmtThenDate(iso) {
    var d = _parseISO(iso);
    var dow = DOW[(d.getDay() + 6) % 7];
    return dow.charAt(0) + dow.slice(1).toLowerCase() + ' ' + d.getDate();
  }

  function _sessionCue(p) {
    if (!p) return null;
    if (p.notes && String(p.notes).trim()) {
      var n = String(p.notes).trim().replace(/\s+/g, ' ');
      if (n.length > 140) n = n.slice(0, 137) + '…';
      return n;
    }
    var s = p.structure || {};
    if (s.cue && String(s.cue).trim()) return String(s.cue).trim();
    if (s.key_instruction && String(s.key_instruction).trim()) return String(s.key_instruction).trim();
    if (Array.isArray(s.blocks)) {
      for (var i = 0; i < s.blocks.length; i++) {
        var b = s.blocks[i];
        if (b && b.notes && String(b.notes).trim()) return String(b.notes).trim();
        if (b && b.cue && String(b.cue).trim()) return String(b.cue).trim();
      }
    }
    return null;
  }

  function _pickNextUp(days) {
    var today = _todayISO();
    var best = null;
    (days || []).forEach(function (day) {
      if (day.date < today) return;
      (day.planned || []).forEach(function (p) {
        if (!_isOpenPlanned(p)) return;
        if (!best || day.date < best.day.date) best = { p: p, day: day };
      });
    });
    return best;
  }

  function _pickThenAfter(days, current) {
    if (!current) return null;
    var afterDate = current.day.date;
    var afterId = current.p.id;
    var passed = false;
    for (var i = 0; i < (days || []).length; i++) {
      var day = days[i];
      if (day.date < afterDate) continue;
      var planned = day.planned || [];
      for (var j = 0; j < planned.length; j++) {
        var p = planned[j];
        if (!passed) {
          if (p.id === afterId) { passed = true; continue; }
          if (day.date === afterDate) continue;
        }
        if (_isOpenPlanned(p)) {
          return {
            fam: _famClass(p.session_type),
            chip: _sessionTypeChipLabel(p),
            text: 'then ' + _fmtThenDate(day.date) + ' · ' + _sessionDisplayName(p)
          };
        }
      }
      if (passed && day.date > afterDate && !planned.length) {
        return {
          fam: null,
          chip: null,
          text: 'then ' + _fmtThenDate(day.date) + ' · rest day — nothing scheduled'
        };
      }
    }
    return null;
  }

  function _loadNextUpRange() {
    var today = _todayISO();
    var to = _iso(_addDays(_parseISO(today), 20));
    _api('GET', '/api/planned-sessions?from=' + today + '&to=' + to)
      .then(function (data) {
        _nextUpBundle = data;
        _renderNextUp();
      })
      .catch(function () {
        _nextUpBundle = null;
        _renderNextUp();
      });
  }

  function _renderNextUp() {
    var host = document.getElementById('plan-next-up');
    if (!host) return;
    var days = (_nextUpBundle && _nextUpBundle.days) || (_bundle && _bundle.days) || [];
    var next = _pickNextUp(days);
    if (!next) {
      host.innerHTML =
        '<div class="pl-hero pl-hero--empty">' +
          '<div class="pl-hero-top"><span class="pl-hero-k">Next up</span></div>' +
          '<div class="pl-hero-body">' +
            '<div class="pl-hero-empty-msg">Nothing scheduled from today forward.</div>' +
            '<button type="button" class="pl-hero-btn" id="pl-hero-suggest">Suggest sessions</button>' +
          '</div>' +
        '</div>';
      var sug = document.getElementById('pl-hero-suggest');
      if (sug) sug.onclick = _openSuggestPanel;
      return;
    }
    var p = next.p;
    var fam = _famClass(p.session_type);
    var cue = _sessionCue(p);
    var dur = _plannedDurationMin(p);
    var tss = _sessionTss(p) || (function () {
      var pt = _plannedTargetTss(p);
      return pt != null ? { value: pt, estimated: true } : null;
    })();
    var weekT = (_wlData && _wlData.target_tss != null) ? Number(_wlData.target_tss) : null;
    var share = (tss && weekT) ? Math.round((tss.value / weekT) * 100) + '%' : '—';
    var metaBits = [];
    if (dur != null) metaBits.push(dur + ' min');
    var soft = _plannedMeta(p);
    if (soft) metaBits.push(soft);
    metaBits.push('planned');
    var then = _pickThenAfter(days, next);
    var cueHtml = cue
      ? '<div class="pl-hero-cue"><span aria-hidden="true">⛽</span><span>' + esc(cue) + '</span></div>'
      : '';
    var thenHtml = then
      ? '<div class="pl-hero-foot">' +
          (then.chip ? '<span class="pl-stypetag ' + (then.fam || '') + '" style="opacity:.55">' + esc(then.chip) + '</span>' : '') +
          '<span class="pl-hero-then">' + esc(then.text) + '</span></div>'
      : '';

    host.innerHTML =
      '<div class="pl-hero">' +
        '<div class="pl-hero-top"><span class="pl-hero-k">Next up</span>' +
          '<span class="pl-hero-d">' + esc(_fmtHeroDate(next.day.date)) + '</span></div>' +
        '<div class="pl-hero-body">' +
          '<div class="pl-hero-left">' +
            '<div class="pl-hero-name"><span class="pl-stypetag ' + fam + '">' + esc(_sessionTypeChipLabel(p)) + '</span> ' +
              esc(_sessionDisplayName(p)) + '</div>' +
            '<div class="pl-hero-meta">' + esc(metaBits.join(' · ')) + '</div>' +
            cueHtml +
          '</div>' +
          '<div class="pl-hero-stats">' +
            '<div class="pl-hero-stat"><div class="k">Duration</div><div class="v">' + (dur != null ? dur : '—') + '</div></div>' +
            '<div class="pl-hero-stat"><div class="k">TSS</div><div class="v">' +
              (tss ? ((tss.estimated ? '~' : '') + Math.round(tss.value)) : '—') + '</div></div>' +
            '<div class="pl-hero-stat"><div class="k">Of week</div><div class="v">' + esc(share) + '</div></div>' +
          '</div>' +
          '<div class="pl-hero-acts">' +
            '<button type="button" class="pl-hero-btn" id="pl-hero-open">Open session</button>' +
            '<button type="button" class="pl-hero-btn ghost" id="pl-hero-done">Mark done</button>' +
          '</div>' +
        '</div>' + thenHtml +
      '</div>';

    var openBtn = document.getElementById('pl-hero-open');
    if (openBtn) openBtn.onclick = function () { _openDetailById(p.id); };
    var doneBtn = document.getElementById('pl-hero-done');
    if (doneBtn) doneBtn.onclick = function () {
      _mutate('POST', '/api/planned-sessions/' + p.id + '/mark-done');
    };
  }

  function _renderAll() {
    _renderNextUp();
    _renderWeekSection();
    _renderAddSection();
    _renderDetailSection();
  }

  function _openSuggestPanel() {
    var t = document.getElementById('plan-suggestions-trigger');
    if (t) t.click();
    setTimeout(function () {
      var panel = document.getElementById('plan-suggestions-panel');
      if (panel) panel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }, 50);
  }

  function _defaultNewSessionDate() {
    var today = _todayISO();
    var weekEnd = _iso(_addDays(_weekStart, 6));
    if (today >= _iso(_weekStart) && today <= weekEnd) return today;
    return _iso(_weekStart);
  }

  function _exportWeekSessions() {
    if (!_bundle || !(_bundle.days || []).length) {
      _toast('Nothing to export this week', true);
      return;
    }
    var out = [];
    (_bundle.days || []).forEach(function (day) {
      (day.planned || []).forEach(function (p) {
        if (p.session_type === 'rest') return;
        var type = (p.session_type || 'run').toLowerCase();
        var structure = p.structure || {};
        var row = {
          date: p.planned_date || day.date,
          type: type,
          name: _sessionDisplayName(p)
        };
        if (p.notes) row.notes = p.notes;
        if (Array.isArray(structure.blocks) && structure.blocks.length) row.blocks = structure.blocks;
        if (Array.isArray(structure.exercises) && structure.exercises.length) {
          row.exercises = structure.exercises.map(function (ex) {
            return _smExportExerciseRow(ex);
          }).filter(Boolean);
        }
        if (structure.target_tss != null) row.target_tss = structure.target_tss;
        if (structure.duration_minutes != null) row.duration_minutes = structure.duration_minutes;
        out.push(row);
      });
    });
    if (!out.length) {
      _toast('No sessions to export', true);
      return;
    }
    var ws = _iso(_weekStart);
    _downloadFile('week-plan-' + ws + '.json', JSON.stringify(out, null, 2), 'application/json');
    _toast('Exported ' + out.length + ' session' + (out.length === 1 ? '' : 's'));
  }

  function _renderWeekSection() {
    var host = document.getElementById('plan-week-section');
    if (!host) return;
    host.innerHTML =
      '<div class="pl-card">' +
        '<div class="pl-wknav">' +
          '<button class="pl-arw" id="pl-prev" aria-label="Previous week">‹</button>' +
          '<span class="pl-wktitle" id="pl-wktitle">' + esc(_fmtWeekTitle(_weekStart)) + '</span>' +
          '<button class="pl-arw" id="pl-next" aria-label="Next week">›</button>' +
          '<span class="pl-weektotal" id="pl-weektotal" hidden></span>' +
          '<span class="pl-wknav-right">' +
            '<button type="button" class="pl-btn pl-ghost pl-tiny" id="pl-new-session">+ New session</button>' +
            '<button type="button" class="pl-btn pl-ghost pl-tiny" id="pl-export-week">Export ↗</button>' +
          '</span>' +
        '</div>' +
        '<div class="pl-btnrow" style="display:none">' +
          '<button class="pl-btn pl-lime" id="pl-apply-draft" hidden title="Create planned sessions from this draft">Apply week</button>' +
          '<button class="pl-btn pl-ghost" id="pl-refresh-draft" hidden title="Regenerate untouched draft slots">Refresh draft</button>' +
          '<button class="pl-btn pl-ghost" id="pl-replan-remaining" hidden title="Replan open days from remaining budget">Replan remaining</button>' +
        '</div>' +
        '<div class="pl-draft-banner" id="pl-draft-banner" aria-live="polite" hidden></div>' +
        '<div class="pl-draft-pending" id="pl-draft-pending" hidden></div>' +
        '<button type="button" class="pl-suggest" id="pl-suggest" title="Suggest sessions for this week">' +
          '<span class="pl-suggest-ic" aria-hidden="true">✨</span>' +
          '<span class="pl-suggest-tx">' +
            '<span class="pl-suggest-t">Suggest sessions</span>' +
            '<span class="pl-suggest-s" id="pl-suggest-sub">deterministic · respects rest days and the ramp rule</span>' +
          '</span>' +
          '<span class="pl-suggest-ar" aria-hidden="true">›</span>' +
        '</button>' +
        '<div class="pl-weeklist" id="plan-week-list"></div>' +
        '<div class="pl-legend">' +
          '<span><b style="background:var(--primary)"></b>Run</span><span><b style="background:var(--workout-lift)"></b>Strength</span><span><b style="background:var(--warning)"></b>Plyo</span>' +
          '<span style="color:var(--text-sub);margin:0 2px;">·</span>' +
          '<span><b style="background:var(--success)"></b>Done</span><span><b style="background:var(--warning)"></b>Needs review</span><span><b style="background:var(--danger)"></b>Missed</span>' +
          '<span style="color:var(--text-sub);margin:0 2px;">·</span>' +
          '<span class="pl-legend-draft">Dashed = draft</span>' +
        '</div>' +
      '</div>';
    document.getElementById('pl-prev').onclick = function () {
      _weekStart = _addDays(_weekStart, -7); _renderWeekSection(); _loadWeek(function () { if (_draftVisible) _loadDraft(); }); _loadWeekLoad(_iso(_weekStart));
    };
    document.getElementById('pl-next').onclick = function () {
      _weekStart = _addDays(_weekStart, 7); _renderWeekSection(); _loadWeek(function () { if (_draftVisible) _loadDraft(); }); _loadWeekLoad(_iso(_weekStart));
    };
    var applyBtn = document.getElementById('pl-apply-draft');
    if (applyBtn) applyBtn.onclick = _applyDraftWeek;
    var refreshBtn = document.getElementById('pl-refresh-draft');
    if (refreshBtn) refreshBtn.onclick = _refreshDraft;
    var replanBtn = document.getElementById('pl-replan-remaining');
    if (replanBtn) replanBtn.onclick = function () {
      _api('POST', '/api/plan/draft/replan-remaining', { week_start: _iso(_weekStart) })
        .then(function () {
          _toast('Replan queued');
          _draftVisible = true;
          setTimeout(function () { _loadDraft(); }, 2000);
        })
        .catch(function () { _toast('Replan failed', true); });
    };
    var sugBtn = document.getElementById('pl-suggest');
    if (sugBtn) sugBtn.onclick = _openSuggestPanel;
    var newBtn = document.getElementById('pl-new-session');
    if (newBtn) newBtn.onclick = function () { _openAdd('single', _defaultNewSessionDate()); };
    var expBtn = document.getElementById('pl-export-week');
    if (expBtn) expBtn.onclick = _exportWeekSessions;
    _updateWeekTargetUI();
    _renderDraftChrome();
    if (_bundle) _renderWeekList();
  }

  // Target-dependent bits of the week-plan card (header total, "Suggest
  // sessions" label, banner) — factored out of _renderWeekSection so
  // _loadWeekLoad's async GET /api/plan/week-load can refresh just these
  // nodes in place once data arrives, without wiping the day list.
  function _updateWeekTargetUI() {
    var d = _wlData;
    var target = (d && d.target_tss != null) ? Math.round(d.target_tss) : null;

    var totalEl = document.getElementById('pl-weektotal');
    if (totalEl) {
      if (target != null) {
        totalEl.hidden = false;
        var stateLabel = d.state === 'on_track' ? 'on track' : d.state === 'under' ? 'under' :
          d.state === 'over' ? 'over' : '—';
        totalEl.innerHTML = '<b>' + Math.round(d.projected_tss) + '</b> / ' + target +
          ' TSS &middot; ' + esc(stateLabel);
      } else {
        totalEl.hidden = true;
      }
    }

    var sugSub = document.getElementById('pl-suggest-sub');
    if (sugSub) {
      sugSub.textContent = target != null
        ? 'fill to ' + target + ' TSS · deterministic · respects rest days and the ramp rule'
        : 'deterministic · respects rest days and the ramp rule';
    }
  }

  function _renderWeekList() {
    var host = document.getElementById('plan-week-list');
    if (!host || !_bundle) return;
    var todayStr = _todayISO();
    var drafts = (_draftVisible && _draft && _draft.status !== 'applied')
      ? _draftSessionsByOffset() : {};
    host.innerHTML = (_bundle.days || []).map(function (day, di) {
      var isPast = day.date < todayStr;
      var isToday = day.date === todayStr;
      var cards = (day.planned || []).map(function (p) { return _plannedCardHtml(p, day); }).join('');
      var ghosts = (day.unplanned || []).filter(function (u) { return !_dismissedGhosts[u.id]; })
        .map(function (u) { return _ghostCardHtml(u, day); }).join('');
      var draftSess = drafts[di];
      var draftHtml = '';
      if (draftSess && (draftSess.workout_type || '') !== 'rest' && !(day.planned || []).length) {
        draftHtml = _draftCardHtml(draftSess, day);
      }
      var addDraft = '';
      var draftActive = _draftVisible && (!_draft || _draft.status !== 'applied');
      if (draftActive && !isPast && !(day.planned || []).length && !draftHtml) {
        addDraft = '<div class="pl-draft-add">' +
          '<button type="button" class="pl-btn pl-ghost pl-tiny" data-draft-add="' + di + '" data-kind="easy_run">Quick easy</button>' +
          '<button type="button" class="pl-btn pl-ghost pl-tiny" data-draft-add="' + di + '" data-kind="light_strength">Quick strength</button>' +
          '<button type="button" class="pl-btn pl-ghost pl-tiny" data-draft-add="' + di + '" data-kind="stretch">Quick stretch</button>' +
        '</div>';
      }
      var hasSessions = !!(cards || ghosts || draftHtml || addDraft);
      var dayTotal = _dayTotalTss(day);
      var dayWarn = _dayHasWarning(day)
        ? '<span class="pl-day-guard-badge" title="A session this day loads an overused or injured muscle group">⚠</span>'
        : '';
      var gutTot = (hasSessions && dayTotal != null)
        ? '<span class="pl-gut-tot">' + Math.round(dayTotal) + ' TSS</span>'
        : '';
      var gut = '<span class="pl-gut"><span class="pl-gut-dw">' + esc(day.dow) + dayWarn +
        '</span><span class="pl-gut-dn">' + _parseISO(day.date).getDate() + '</span>' +
        gutTot + '</span>';

      var addRight = isPast
        ? ''
        : '<button type="button" class="pl-day-add" data-add-date="' + day.date +
          '" aria-label="Add a session on ' + esc(day.date) + '">+ add session</button>';

      var content;
      if (!hasSessions) {
        content = '<span class="pl-day-content"><span class="pl-day-sessions">' +
          '<div class="pl-rest-lab">rest day — nothing scheduled</div></span>' + addRight + '</span>';
      } else {
        content = '<span class="pl-day-content"><span class="pl-day-sessions">' +
          cards + draftHtml + addDraft + ghosts + '</span>' + addRight + '</span>';
      }

      var cls = 'pl-dayrow' + (isToday ? ' today' : '') + (isPast ? ' past' : '') +
        (!hasSessions ? ' rest' : '');
      return '<div class="' + cls + '" data-date="' + day.date + '" data-day-offset="' + di + '">' +
        gut + content + '</div>';
    }).join('');
    _wireWeekEvents();
  }

  // Real logged TSS (p.actual.tss) when the session is done/matched; the
  // server-computed historical-baseline estimate (p.estimated_tss, "~" —
  // ONLY present while the session is still achievable, see
  // _planned_session_dict) otherwise. Never fabricates a number.
  function _sessionTss(p) {
    if (p.actual && p.actual.tss != null) return { value: p.actual.tss, estimated: false };
    if (p.estimated_tss != null) return { value: p.estimated_tss, estimated: true };
    return null;
  }

  function _sessionTssBadge(p) {
    var t = _sessionTss(p);
    if (!t) return '';
    var label = (t.estimated ? '~' : '') + Math.round(t.value) + ' TSS';
    return '<span class="pl-tss-badge' + (t.estimated ? ' is-estimated' : '') + '">' + label + '</span>';
  }

  function _planWarnBadge(p) {
    var w = p.plan_warnings;
    if (!w || !w.length) return '';
    return '<span class="pl-guard-badge" title="' + esc(w.map(function (x) { return x.message; }).join(' | ')) + '">⚠</span>';
  }

  function _dayHasWarning(day) {
    return (day.planned || []).some(function (p) { return p.plan_warnings && p.plan_warnings.length; });
  }

  function _dayTotalTss(day) {
    var total = 0, any = false;
    (day.planned || []).forEach(function (p) {
      var t = _sessionTss(p);
      if (t) { total += t.value; any = true; }
    });
    return any ? total : null;
  }

  function _statusTag(status, hasActual) {
    if (status === 'missed' || status === 'missed_auto' || status === 'missed_manual') {
      return '<span class="pl-stat-tag missed">' + (status === 'missed_manual' ? 'MISSED' : 'MISSED') + '</span>';
    }
    if (status === 'needs_review') return '<span class="pl-stat-tag review">NEEDS REVIEW</span>';
    if (status === 'done_auto') return '<span class="pl-stat-tag done">AUTO-MATCHED</span>';
    if (status === 'done_manual') return hasActual
      ? '<span class="pl-stat-tag done">MANUALLY LINKED</span>'
      : '<span class="pl-stat-tag done">COMPLETED (no data)</span>';
    return '';
  }

  /** Never render empty session identity (Part 0.1). */
  function _sessionDisplayName(p) {
    var n = (p && p.name) ? String(p.name).trim() : '';
    if (n) return n;
    if (p && p.actual && p.actual.name) {
      n = String(p.actual.name).trim();
      if (n) return n;
    }
    var t = ((p && p.session_type) || 'run').toLowerCase();
    if (t === 'strength' || t === 'plyo') return 'Strength session';
    if (t === 'stretch') return 'Stretch session';
    if (t === 'rest') return 'Rest day';
    return 'Easy run';
  }

  function _sessionTypeChipLabel(p) {
    var t = ((p && p.session_type) || 'run').toLowerCase();
    if (t === 'strength') return 'LIFT';
    if (t === 'plyo') return 'PLYO';
    if (t === 'stretch') return 'STRETCH';
    if (t === 'rest') return 'REST';
    return 'RUN';
  }

  function _plannedTargetTss(p) {
    if (!p) return null;
    if (p.planned_tss != null && isFinite(Number(p.planned_tss))) return Number(p.planned_tss);
    var s = p.structure || {};
    if (s.target_tss != null && isFinite(Number(s.target_tss))) return Number(s.target_tss);
    if (p.estimated_tss != null && isFinite(Number(p.estimated_tss))) return Number(p.estimated_tss);
    return null;
  }

  function _actualDurationMin(p) {
    if (p && p.actual && p.actual.duration_seconds != null) {
      return Math.round(Number(p.actual.duration_seconds) / 60);
    }
    if (p && p.actual_duration_min != null) return Math.round(Number(p.actual_duration_min));
    return null;
  }

  function _plannedDurationMin(p) {
    var s = (p && p.structure) || {};
    if (s.duration_minutes != null && isFinite(Number(s.duration_minutes))) {
      return Math.round(Number(s.duration_minutes));
    }
    if (Array.isArray(s.blocks) && s.blocks.length) {
      var tot = 0;
      s.blocks.forEach(function (b) {
        var d = Number(b.duration_min) || 0;
        var r = Math.max(1, Number(b.repeat) || 1);
        tot += d * r + (Number(b.rest_min) || 0) * (r - 1);
      });
      return tot || null;
    }
    return null;
  }

  /**
   * One compact derivation line (Part 0.2) — never repeat TSS four ways.
   * Matched: `91 min · planned 54 → 70 · auto-matched`
   * Planned: `130 min · easy · planned` or `14 exercises · planned`
   */
  function _sessionCompactMeta(p) {
    var bits = [];
    var done = p.status === 'done_auto' || p.status === 'done_manual';
    var actMin = _actualDurationMin(p);
    var planMin = _plannedDurationMin(p);
    var planTss = _plannedTargetTss(p);
    var actTss = _sessionTss(p);
    var matchLab = p.status === 'done_auto' ? 'auto-matched'
      : (p.status === 'done_manual' ? 'manually linked' : '');

    if (done && (actMin != null || actTss)) {
      if (actMin != null) bits.push(actMin + ' min');
      if (planTss != null && actTss) {
        var deltaCls = actTss.value > planTss ? 'over' : 'delta';
        bits.push('planned ' + Math.round(planTss) + ' → <span class="pl-sdelta ' + deltaCls + '">' +
          Math.round(actTss.value) + ' TSS</span>');
      } else if (actTss) {
        bits.push(Math.round(actTss.value) + ' TSS');
      }
      if (matchLab) bits.push(matchLab);
      return bits.join(' · ');
    }

    var soft = _plannedMeta(p);
    if (planMin != null && !(soft && soft.indexOf('min') !== -1)) bits.push(planMin + ' min');
    if (soft) bits.push(esc(soft));
    else if (planTss != null) bits.push('~' + Math.round(planTss) + ' TSS');
    if (p.status === 'needs_review') bits.push('needs review');
    else if (p.status === 'missed' || p.status === 'missed_auto' || p.status === 'missed_manual') bits.push('missed');
    else bits.push('planned');
    return bits.join(' · ');
  }

  function _statusDotClass(status) {
    if (status === 'done_auto' || status === 'done_manual') return 'done';
    if (status === 'needs_review') return 'review';
    if (status === 'missed' || status === 'missed_auto' || status === 'missed_manual') return 'missed';
    return 'draft';
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

  // Type family for card styling — plyo and stretch get their own colors
  // (matching the Suggest-sessions palette: plyo amber, stretch teal)
  // instead of masquerading as purple "lift".
  function _famClass(t) {
    if (t === 'run') return 'run';
    if (t === 'plyo') return 'plyo';
    if (t === 'stretch') return 'stretch';
    return 'lift';
  }

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
      var label = on ? f.label + ' — tap to clear' : f.label;
      return '<button type="button" class="' + cls + '" data-feel="' + workoutId +
        '" data-feel-val="' + f.key + '" title="' + label + '" aria-label="' + label +
        (on ? '" data-feel-on="1" aria-pressed="true' : '') + '">' + f.icon + '</button>';
    }).join('');
    return '<div class="pl-feelrow" data-feelrow="' + workoutId + '">' + btns + '</div>';
  }

  function _plannedCardHtml(p, day) {
    var fam = _famClass(p.session_type);
    var chip = _sessionTypeChipLabel(p).toLowerCase();
    var displayName = _sessionDisplayName(p);
    var generating = !!(p.id && _generatingIds[p.id]);
    var draggable = !generating && (p.status === 'planned' || p.status === 'missed' || p.status === 'missed_auto' || p.status === 'missed_manual');
    var clickable = (p.status !== 'needs_review');
    var todayStr = _todayISO();
    var compact = generating ? 'content updating for the new budget…' : _sessionCompactMeta(p);
    if (!generating && day && day.date === todayStr && (p.status === 'planned' || !p.status)) {
      if (compact.indexOf('today') === -1) compact = compact.replace(/ · planned$/, ' · today');
    }
    var tss = _sessionTss(p);
    var tssHtml = tss
      ? '<span class="pl-stss' + (tss.estimated ? ' is-est' : '') + '">' + (tss.estimated ? '~' : '') + Math.round(tss.value) + '</span>'
      : '<span class="pl-stss"></span>';
    var warn = generating ? '' : _planWarnBadge(p);

    var expandBody = '';
    if (generating) {
      expandBody = '';
    } else if (p.status === 'done_auto' || p.status === 'done_manual') {
      var mwid = p.matched_workout_id || (p.actual && p.actual.id) || '';
      var feel = p.actual ? p.actual.feeling : null;
      var matchLine = '';
      if (p.actual) {
        var srcLab = p.status === 'done_auto' ? '✓ matched' : '↔ linked by you';
        matchLine = '<div class="pl-matchline' + (p.status === 'done_manual' ? ' manual' : '') + '">' +
          esc(srcLab) + (p.actual.name ? ' · ' + esc(p.actual.name) : '') +
          (p.actual.meta ? ' · ' + esc(p.actual.meta) : '') + '</div>';
      } else {
        matchLine = '<div class="pl-matchline manual">Marked complete manually — no workout data attached</div>';
      }
      if (p.actual && p.actual.date && p.planned_date && p.actual.date !== p.planned_date) {
        matchLine += '<div class="pl-diffline">done · a day late</div>';
      }
      expandBody = matchLine +
        _viewFullLinkHtml(mwid) +
        _feelRowHtml(mwid, feel) +
        '<div class="pl-sexp-acts">' +
          '<button type="button" class="pl-abtn" data-open-sess="' + p.id + '">Open session</button>' +
          '<button type="button" class="pl-abtn" data-pick="' + p.id + '" data-pick-mode="override">' +
            (mwid ? 'Change match' : 'Attach a workout') + '</button>' +
          '<button type="button" class="pl-abtn warn" data-unlink="' + p.id + '">' +
            (mwid ? 'Unlink' : 'Revert') + '</button>' +
        '</div>' +
        '<div class="pl-picker" data-pickerfor="' + p.id + '" hidden></div>';
    } else if (p.status === 'needs_review') {
      var cands = _reviewCandidates(p, day);
      expandBody = '<div class="pl-candlist">' + cands.map(function (c, ci) {
          return '<label class="pl-candrow"><input type="radio" name="pl-cand-' + p.id + '" value="' + c.id + '"' + (ci === 0 ? ' checked' : '') + '/>' +
            '<span class="pl-cn">' + esc(c.name) + '</span><span class="pl-cm">' + esc(c.meta) + '</span></label>';
        }).join('') +
        '<div class="pl-candbtns">' +
          (cands.length ? '<button class="pl-btn pl-lime pl-tiny" data-confirm="' + p.id + '">Confirm match</button>' : '') +
          '<button class="pl-btn pl-ghost pl-tiny" data-missed="' + p.id + '">None → missed</button>' +
        '</div></div>';
    } else {
      var moveOpts = ((_bundle && _bundle.days) || []).filter(function (d) {
        return d.date !== day.date;
      }).map(function (d) {
        return '<option value="' + d.date + '">' + d.dow + ' ' + _parseISO(d.date).getDate() + '</option>';
      }).join('');
      expandBody = '<div class="pl-sexp-acts">' +
        '<button type="button" class="pl-abtn" data-open-sess="' + p.id + '">Open session</button>' +
        (draggable
          ? '<label class="pl-abtn pl-abtn-sel">Move to… <select data-sess-move="' + p.id + '" aria-label="Move session"><option value="">…</option>' + moveOpts + '</select></label>'
          : '') +
        '<button type="button" class="pl-abtn warn" data-sess-del="' + p.id + '">Remove</button>' +
      '</div>';
    }

    var typeLabel = fam === 'lift' ? 'Strength' : (fam.charAt(0).toUpperCase() + fam.slice(1));
    var statusLabel = (p.status === 'needs_review') ? 'needs review'
      : (p.status === 'missed' || p.status === 'missed_auto' || p.status === 'missed_manual') ? 'missed'
      : (p.status === 'done_auto' || p.status === 'done_manual') ? 'completed'
      : 'planned';
    var ariaLabel = typeLabel + ' session, ' + displayName + ', ' +
      day.dow + ' ' + _parseISO(day.date).getDate() + ', ' + statusLabel;
    var a11yAttrs = clickable
      ? ' role="button" tabindex="0" aria-expanded="false" aria-label="' + esc(ariaLabel) + '"'
      : '';

    var forceOpen = (p.status === 'needs_review');
    return '<div class="pl-sess ' + fam + ' status-' + p.status + (generating ? ' is-generating' : '') + (forceOpen ? ' open' : '') + '"' +
        (draggable && !generating ? ' draggable="true"' : '') +
        ' data-sess="' + p.id + '"' + (clickable ? ' data-click="1"' : '') + a11yAttrs + '>' +
      '<div class="pl-srow">' +
        '<span class="pl-stypetag ' + fam + '">' + esc(_sessionTypeChipLabel(p)) + '</span>' +
        '<span class="pl-sn">' + esc(displayName) + warn + '</span>' +
        '<span class="pl-smeta2">' + (generating ? esc(compact) : compact) + '</span>' +
        tssHtml +
        '<span class="pl-sdot ' + _statusDotClass(p.status) + '" aria-hidden="true"></span>' +
      '</div>' +
      '<div class="pl-smeta-m">' + (generating ? esc(compact) : compact) + '</div>' +
      (expandBody ? '<div class="pl-sexp">' + expandBody + '</div>' : '') +
    '</div>';
  }

  function _confirmDeleteSession(id, name) {
    var existing = document.getElementById('pl-del-confirm-overlay');
    if (existing) existing.remove();
    var overlay = document.createElement('div');
    overlay.id = 'pl-del-confirm-overlay';
    overlay.className = 'pl-draft-q-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');
    overlay.innerHTML =
      '<div class="pl-draft-q-card">' +
        '<h3>Delete session?</h3>' +
        '<p>Remove <b>' + esc(name) + '</b> from this week’s plan. This can’t be undone.</p>' +
        '<div class="pl-del-confirm-actions">' +
          '<button type="button" class="pl-btn pl-danger" data-del-yes>Delete</button>' +
          '<button type="button" class="pl-btn" data-del-no>Cancel</button>' +
        '</div>' +
      '</div>';
    document.body.appendChild(overlay);
    function close() { overlay.remove(); }
    overlay.addEventListener('click', function (e) { if (e.target === overlay) close(); });
    overlay.querySelector('[data-del-no]').addEventListener('click', close);
    overlay.querySelector('[data-del-yes]').addEventListener('click', function () {
      var btn = overlay.querySelector('[data-del-yes]');
      btn.disabled = true;
      btn.textContent = 'Deleting…';
      _api('DELETE', '/api/planned-sessions/' + id)
        .then(function () {
          close();
          _toast('Session deleted');
          if (_detail && _detail.id === id) _closeDetail();
          _loadWeek(function () { if (_draftVisible) _loadDraft(); });
        })
        .catch(function (err) {
          btn.disabled = false;
          btn.textContent = 'Delete';
          _toast((err && err.message) || 'Delete failed', true);
        });
    });
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
        var label = _sessionDisplayName(p) + (d.date !== u.date ? ' — ' + d.dow + ' ' + _parseISO(d.date).getDate() : '');
        return '<option value="' + p.id + '">' + esc(label) + '</option>';
      }));
    }, []).join('');
    var mapper = opts
      ? '<select class="pl-ghostsel" data-ghostsel="' + u.id + '"><option value="">Map to…</option>' + opts + '</select>' +
        '<div class="pl-candbtns"><button class="pl-btn pl-ghost pl-tiny" data-map="' + u.id + '">Map</button><button class="pl-btn pl-ghost pl-tiny" data-ignore="' + u.id + '">Ignore</button></div>'
      : '<div class="pl-candbtns"><button class="pl-btn pl-ghost pl-tiny" data-ignore="' + u.id + '">Ignore</button></div>';
    return '<div class="pl-ghost"><div class="pl-gtop"><span class="pl-gtag">UNPLANNED</span></div>' +
      '<div class="pl-sn" style="font-style:italic;">' + esc(u.name || 'Unplanned workout') + '</div><div class="pl-sm">' + esc(u.meta) + '</div>' + mapper +
    '</div>';
  }

  // ── Week event wiring (delegated) ───────────────────────────────────────────
  var _dragCtx = null;
  function _wireWeekEvents() {
    var host = document.getElementById('plan-week-list');
    if (!host) return;

    host.querySelectorAll('[data-draft-rm]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        var sid = b.getAttribute('data-draft-rm');
        var card = b.closest('.pl-draft');
        var titleEl = card && card.querySelector('.pl-sn');
        _removeDraftSlot(sid, titleEl ? titleEl.textContent.trim() : null);
      });
    });
    host.querySelectorAll('[data-draft-move]').forEach(function (sel) {
      sel.addEventListener('change', function () {
        var to = parseInt(sel.value, 10);
        if (isNaN(to)) return;
        _moveDraftSlot(sel.getAttribute('data-draft-move'), to);
        sel.value = '';
      });
    });
    host.querySelectorAll('[data-draft-add]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.stopPropagation();
        _addDraftKind(+b.getAttribute('data-draft-add'), b.getAttribute('data-kind'), b);
      });
    });

    host.querySelectorAll('.pl-draft').forEach(function (el) {
      el.addEventListener('click', function (e) {
        if (e.target.closest('[data-draft-rm], [data-draft-move], .pl-draft-move, select, button')) return;
        var sid = el.getAttribute('data-slot-id');
        _openDraftDetail(sid);
      });
    });

    // Draft chip drag — keyed by slot_id (stable across re-renders).
    var _draftDragId = null;
    host.querySelectorAll('.pl-draft[draggable="true"]').forEach(function (el) {
      el.addEventListener('dragstart', function (e) {
        _draftDragId = el.getAttribute('data-slot-id');
        el.classList.add('dragging');
        try { e.dataTransfer.setData('text/plain', 'draft:' + _draftDragId); } catch (_) {}
        host.querySelectorAll('.pl-dayrow').forEach(function (row) {
          var off = +row.getAttribute('data-day-offset');
          row.classList.remove('drop-ok', 'drop-warn', 'drop-blocked');
          if (!_draft || !_draft.draft_version) return;
          // Preview via sync heuristics: past = blocked
          var todayStr = _todayISO();
          if (row.getAttribute('data-date') < todayStr) {
            row.classList.add('drop-blocked');
            row.setAttribute('data-drop-hint', '⛔ past');
          } else {
            row.classList.add('drop-ok');
            row.setAttribute('data-drop-hint', '✓');
          }
        });
      });
      el.addEventListener('dragend', function () {
        el.classList.remove('dragging');
        _draftDragId = null;
        host.querySelectorAll('.pl-dayrow').forEach(function (row) {
          row.classList.remove('drop-ok', 'drop-warn', 'drop-blocked', 'dragover');
          row.removeAttribute('data-drop-hint');
        });
      });
    });
    host.querySelectorAll('.pl-dayrow').forEach(function (row) {
      row.addEventListener('dragover', function (e) {
        if (!_draftDragId) return;
        e.preventDefault();
        row.classList.add('dragover');
      });
      row.addEventListener('dragleave', function () { row.classList.remove('dragover'); });
      row.addEventListener('drop', function (e) {
        if (!_draftDragId) return;
        e.preventDefault();
        row.classList.remove('dragover');
        if (row.classList.contains('drop-blocked')) {
          _toast('Cannot drop on a past day', true);
          return;
        }
        var to = +row.getAttribute('data-day-offset');
        var sid = _draftDragId;
        _draftDragId = null;
        // Amber confirm path: if preferred rest, confirm via API needs_confirm
        _moveDraftSlot(sid, to);
      });
    });

    host.querySelectorAll('.pl-sess[data-click="1"]').forEach(function (el) {
      el.addEventListener('click', function (e) {
        if (e.target.closest('button, select, input, label, a, .pl-picker, .pl-sexp-acts, .pl-candlist')) return;
        var open = el.classList.toggle('open');
        el.setAttribute('aria-expanded', open ? 'true' : 'false');
      });
      el.addEventListener('keydown', function (e) {
        if (e.target !== el) return;
        if (e.key === 'Enter' || e.key === ' ' || e.key === 'Spacebar') {
          e.preventDefault();
          var open = el.classList.toggle('open');
          el.setAttribute('aria-expanded', open ? 'true' : 'false');
        }
      });
    });
    host.querySelectorAll('[data-open-sess]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        _openDetailById(b.getAttribute('data-open-sess'));
      });
    });
    // Keyboard-operable reschedule (parity with the "Move to…" dropdown
    // already used for draft slots) — lives inside the expandable card,
    // so stop the click from also toggling the row.
    host.querySelectorAll('[data-sess-move]').forEach(function (sel) {
      sel.addEventListener('click', function (e) { e.stopPropagation(); });
      sel.addEventListener('change', function (e) {
        e.stopPropagation();
        var newDate = sel.value;
        if (!newDate) return;
        _mutate('PATCH', '/api/planned-sessions/' + sel.getAttribute('data-sess-move'), { planned_date: newDate });
        sel.value = '';
      });
    });
    host.querySelectorAll('[data-sess-del]').forEach(function (b) {
      b.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        var id = b.getAttribute('data-sess-del');
        var card = b.closest('.pl-sess');
        var name = card ? ((card.querySelector('.pl-sn') || {}).textContent || 'this session') : 'this session';
        _confirmDeleteSession(id, name);
      });
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
        // Tapping the already-selected feeling clears it (misclick undo).
        var val = b.hasAttribute('data-feel-on') ? null : b.getAttribute('data-feel-val');
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
    host.querySelectorAll('[data-add-date]').forEach(function (el) {
      el.addEventListener('click', function (e) {
        e.stopPropagation();
        _openAdd('single', el.getAttribute('data-add-date'));
      });
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
    _addDraftExtras = { ai: null, manualOpen: false };
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
    // Unified modal: editing IS the session surface (no separate Edit panel).
    // Matched workouts can still open the Log detail via status/attach flows.
    if (p && p.id) _openDetailById(p.id);
  }

  function _closeAdd() { _panel.open = null; _addState.editId = null; _addState.edit = null; _renderAddSection(); }

  function _renderAddSection() {
    var host = document.getElementById('plan-add-section');
    if (!host) return;
    if (_panel.open !== 'add') { host.innerHTML = ''; return; }
    var editing = !!_addState.editId;
    host.innerHTML = '<div class="pl-card pl-panelcard">' +
      '<div class="pl-panelhead"><h2 class="pl-sectitle">' + (editing ? 'Edit session' : 'Add session(s)') + '</h2><button class="pl-closepanel" id="pl-addclose">✕</button></div>' +
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
    // Create single-session: Form (draft-first) | JSON.
    // Edit / bulk keep prior subtabs.
    var subs;
    if (editing) {
      subs = [];
    } else if (_addState.top === 'single') {
      subs = [['form', 'Form'], ['json', 'JSON']];
    } else {
      subs = [['form', 'Form'], ['json', 'JSON'], ['sep', 'Separator']];
    }
    var subHtml = editing ? '' : '<div class="pl-subtoggle" id="pl-addsub">' + subs.map(function (x) {
      return '<button class="' + (x[0] === _addState.sub ? 'on' : '') + '" data-sm="' + x[0] + '">' + x[1] + '</button>';
    }).join('') + '</div>';
    var content;
    if (_addState.top === 'single') {
      content = _addState.sub === 'form' ? _singleFormHtml() : _singleJSONHtml();
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

  var _ADD_SUBTYPES = {
    run: [
      { v: 'easy', l: 'Easy' },
      { v: 'long', l: 'Long' },
      { v: 'intervals', l: 'Intervals' },
      { v: 'tempo', l: 'Tempo' },
    ],
    strength: [
      { v: 'upper', l: 'Upper' },
      { v: 'lower', l: 'Lower' },
      { v: 'full', l: 'Full body' },
      { v: 'light', l: 'Light' },
    ],
    plyo: [{ v: 'plyo', l: 'Plyo' }],
    stretch: [{ v: 'stretch', l: 'Stretch' }],
  };

  function _addSubtypeOptions(type, selected) {
    var list = _ADD_SUBTYPES[type] || [];
    if (!list.length) return '<option value="">—</option>';
    return list.map(function (o) {
      return '<option value="' + o.v + '"' + (o.v === selected ? ' selected' : '') + '>' + o.l + '</option>';
    }).join('');
  }

  // ── Single Form (adaptive: run block builder vs strength exercise rows) ─────
  function _singleFormHtml() {
    var ed = _addState.edit || {};
    function sel(t) { return ed.type === t ? ' selected' : ''; }

    // Edit existing planned session — keep full structure editor + Save changes.
    if (_addState.editId) {
      return '<div class="pl-frow">' +
          '<div class="pl-fld"><label>Date</label><input type="date" id="pl-sf-date" aria-label="Session date" value="' + esc(_addState.presetDate) + '"/></div>' +
          '<div class="pl-fld"><label>Type</label><select id="pl-sf-type" aria-label="Session type">' +
            '<option value="run"' + sel('run') + '>Run</option>' +
            '<option value="strength"' + sel('strength') + '>Strength</option>' +
            '<option value="plyo"' + sel('plyo') + '>Plyo</option>' +
            '<option value="rest"' + sel('rest') + '>Rest</option>' +
          '</select></div>' +
          '<div class="pl-fld"><label>Session name</label><input id="pl-sf-name" aria-label="Session name" placeholder="Sustained Tempo" value="' + esc(ed.name || '') + '"/></div>' +
        '</div>' +
        '<div id="pl-sf-structure"></div>' +
        '<div class="pl-fld" style="margin-top:14px;"><label>Notes from coach</label><textarea id="pl-sf-notes" aria-label="Notes from coach" placeholder="e.g. hold 92% CP even on the 3rd rep">' + esc(ed.notes || '') + '</textarea></div>' +
        '<div id="pl-sf-guard" aria-live="assertive"></div>' +
        '<div class="pl-btnrow" style="margin-top:14px;"><button class="pl-btn pl-lime" id="pl-sf-save">Save changes</button><button class="pl-btn pl-ghost" id="pl-sf-cancel">Cancel</button></div>';
    }

    // Create — draft-first: pins + optional manual structure, then save.
    var draftMode = !!_draftVisible;
    var defaultType = 'run';
    return '<div class="pl-infobanner" style="margin-bottom:12px;">' +
        (draftMode
          ? 'Adds to the <b>week draft</b> first. Apply later (or use Save draft &amp; apply to commit this session now).'
          : 'Pipeline draft is off — Save writes a planned session directly.') +
      '</div>' +
      '<div class="pl-frow">' +
        '<div class="pl-fld"><label>Date</label><input type="date" id="pl-sf-date" value="' + esc(_addState.presetDate) + '"/></div>' +
        '<div class="pl-fld"><label>Type</label><select id="pl-sf-type">' +
          '<option value="run" selected>Run</option>' +
          '<option value="strength">Strength</option>' +
          '<option value="plyo">Plyo</option>' +
          '<option value="stretch">Stretch</option>' +
        '</select></div>' +
        '<div class="pl-fld"><label>Subtype</label><select id="pl-sf-subtype">' +
          _addSubtypeOptions(defaultType, 'easy') +
        '</select></div>' +
      '</div>' +
      '<div class="pl-frow">' +
        '<div class="pl-fld"><label>Expected TSS</label><input type="number" id="pl-sf-tss" min="0" max="400" value="40"/></div>' +
        '<div class="pl-fld"><label>Duration (min)</label><input type="number" id="pl-sf-dur" min="0" max="600" value="45"/></div>' +
        '<div class="pl-fld"><label>Name / intent</label><input id="pl-sf-name" placeholder="Optional"/></div>' +
      '</div>' +
      '<div class="pl-btnrow pl-sf-draft-tools" style="margin-top:12px;gap:8px;flex-wrap:wrap;">' +
        '<button type="button" class="pl-btn pl-ghost" id="pl-sf-manual-tog">' +
          (_addDraftExtras.manualOpen ? 'Hide manual structure' : 'Fill structure manually') +
        '</button>' +
      '</div>' +
      '<div id="pl-sf-structure" style="' + (_addDraftExtras.manualOpen ? '' : 'display:none;') + 'margin-top:12px;"></div>' +
      '<div class="pl-fld" style="margin-top:12px;"><label>Notes</label><textarea id="pl-sf-notes" placeholder="Optional notes saved on the draft"></textarea></div>' +
      '<div id="pl-sf-guard" aria-live="assertive"></div>' +
      '<div class="pl-btnrow" style="margin-top:14px;gap:8px;flex-wrap:wrap;">' +
        (draftMode
          ? '<button class="pl-btn pl-lime" id="pl-sf-draft">Save draft</button>' +
            '<button class="pl-btn pl-dark" id="pl-sf-draft-apply">Save draft &amp; apply</button>'
          : '<button class="pl-btn pl-lime" id="pl-sf-save">Save session</button>') +
        '<button class="pl-btn pl-ghost" id="pl-sf-cancel">Cancel</button>' +
      '</div>' +
      (draftMode
        ? '<p class="pl-sf-hint">Leave structure empty — Save draft fills content from patterns. Or fill structure manually.</p>'
        : '');
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
        '<div class="pl-exhead pl-blockhead"><span>Phase</span><span>Min</span><span>Repeats</span><span>Target</span><span></span></div>' +
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
          ? '<div class="pl-fld"><label>Focus</label><input id="pl-str-focus" aria-label="Strength training focus" placeholder="Lower / posterior chain" value="' + esc(_sfFocus || '') + '"/></div>'
          : _sfStrengthMode === 'json'
          ? '<div class="pl-fld" style="margin-bottom:6px;"><label>Exercises (JSON)</label></div>' +
            '<textarea class="pl-jsonta" id="pl-exjson-ta" aria-label="Exercises JSON" style="min-height:160px;">' + esc(JSON.stringify(_sfExercises, null, 2)) + '</textarea>' +
            '<div id="pl-exjson-err" aria-live="polite"></div>'
          : '<div class="pl-fld" style="margin-bottom:6px;"><label>Exercises</label></div>' +
            // RPE here is a blank-by-default TARGET the coach can optionally
            // set going in — distinct from the real logged RPE, which is
            // only known once the session is actually trained and shows up
            // on the matched workout's detail instead (see _liftDetailHtml).
            '<div class="pl-exhead"><span>Name</span><span>Sets</span><span>Reps</span><span>Load</span><span>RPE</span><span></span></div>' +
            '<div class="pl-blocklist" id="pl-exlist">' + _exRowsGroupedHtml() + '</div>' +
            '<button class="pl-addblock" id="pl-addgroup">+ Add group</button>');
      _wireStrengthBuilder();
    }
  }

  function _blockRowHtml(b, i) {
    var ph = String(b.phase || '').toLowerCase();
    var cls = ph === 'warmup' ? 'warm' : (ph === 'main' || ph === 'mp' || ph === 'marathon_pace' ? 'main' : 'cool');
    var label = _phaseLabel(b.phase);
    return '<div class="pl-block" data-bi="' + i + '"><span class="pl-btag ' + cls + '">' + label + '</span>' +
      '<input class="pl-bdur" data-f="duration_min" aria-label="' + label + ' duration in minutes" value="' + esc(b.duration_min != null ? b.duration_min : '') + '" placeholder="min"/>' +
      '<input class="pl-btgt" data-f="repeat" aria-label="' + label + ' repeat count" value="' + esc(b.repeat != null ? b.repeat : '') + '" placeholder="×reps"/>' +
      '<input class="pl-btgt" data-f="target" aria-label="' + label + ' target" value="' + esc(b.target || '') + '" placeholder="target"/>' +
      '<button class="pl-rm" data-rm-block="' + i + '">✕</button></div>';
  }
  // Group containers derived from contiguous `block` runs in the flat
  // _sfExercises array (which stays the single source of truth — the save
  // path and the JSON view read it unchanged). Each group has a drag handle
  // (reorders the whole group), an editable name, a remove button, and a
  // per-group "+ exercise"; rows drag between/within groups.
  function _exGroups() {
    var groups = [];
    _sfExercises.forEach(function (x, i) {
      var b = (x && x.block) ? x.block : '';
      var last = groups[groups.length - 1];
      if (!last || last.block !== b) {
        groups.push({ block: b, idxs: [i] });
      } else {
        last.idxs.push(i);
      }
    });
    return groups;
  }

  function _exRowsGroupedHtml() {
    var groups = _exGroups();
    return groups.map(function (g, gi) {
      // Keyboard-operable alternative to the drag handle (drag alone has no
      // keyboard path): up/down buttons that swap this group with its
      // neighbor, disabled at the ends. The handle itself also gets a real
      // button role so screen-reader/keyboard users know it's interactive.
      var moveUp = '<button type="button" class="pl-gmove" data-gmove-up="' + gi + '"' +
        (gi === 0 ? ' disabled' : '') + ' aria-label="Move group ' + esc(g.block || '(untitled)') + ' up">▲</button>';
      var moveDown = '<button type="button" class="pl-gmove" data-gmove-down="' + gi + '"' +
        (gi === groups.length - 1 ? ' disabled' : '') + ' aria-label="Move group ' + esc(g.block || '(untitled)') + ' down">▼</button>';
      return '<div class="pl-exgroup" data-gi="' + gi + '">' +
        '<div class="pl-exgroup-h">' +
          '<span class="pl-gdrag" role="button" tabindex="0" title="Drag to reorder this group" aria-label="Reorder group ' + esc(g.block || '(untitled)') + ' — use the up/down buttons for keyboard" data-gdrag="' + gi + '">⠿</span>' +
          '<span class="pl-gmovebtns">' + moveUp + moveDown + '</span>' +
          '<input class="pl-gname" data-gname="' + gi + '" aria-label="Group name" value="' + esc(g.block) + '" placeholder="Group name"/>' +
          '<button type="button" class="pl-rm" data-rm-group="' + gi + '" title="Remove group and its exercises">✕</button>' +
        '</div>' +
        g.idxs.map(function (i) { return _exRowHtml(_sfExercises[i], i); }).join('') +
        '<button type="button" class="pl-addblock pl-addex-in" data-addex-in="' + gi + '">+ exercise</button>' +
      '</div>';
    }).join('');
  }

  // Group-level interactions for the detailed strength editor: rename,
  // remove, add-exercise-in-group, add-group, and drag & drop of both whole
  // groups and single exercises. All operations rewrite the flat
  // _sfExercises array and re-render — the array (with `block` per row)
  // stays the single source of truth for Simple/JSON/Save.
  function _wireExerciseGroups(list) {
    var groups = _exGroups();

    // Rename on change/blur (not per keystroke — re-render would drop focus).
    list.querySelectorAll('[data-gname]').forEach(function (inp) {
      inp.addEventListener('change', function () {
        var g = groups[+inp.getAttribute('data-gname')];
        if (!g) return;
        g.idxs.forEach(function (i) { _sfExercises[i].block = inp.value.trim(); });
        _renderStructureBuilder();
      });
    });
    list.querySelectorAll('[data-rm-group]').forEach(function (b) {
      b.addEventListener('click', function () {
        var g = groups[+b.getAttribute('data-rm-group')];
        if (!g) return;
        for (var k = g.idxs.length - 1; k >= 0; k--) _sfExercises.splice(g.idxs[k], 1);
        _renderStructureBuilder();
      });
    });
    list.querySelectorAll('[data-addex-in]').forEach(function (b) {
      b.addEventListener('click', function () {
        var g = groups[+b.getAttribute('data-addex-in')];
        if (!g) return;
        _sfExercises.splice(g.idxs[g.idxs.length - 1] + 1, 0,
          { block: g.block, name: '', sets: 3, reps: 10, load: '', rpe: '' });
        _renderStructureBuilder();
      });
    });
    var addGroup = document.getElementById('pl-addgroup');
    if (addGroup) addGroup.onclick = function () {
      _sfExercises.push({ block: 'New block', name: '', sets: 3, reps: 10, load: '', rpe: '' });
      _renderStructureBuilder();
    };

    // Drag & drop. A group is draggable only while the pointer holds its ⠿
    // handle (otherwise dragging a row would drag the whole group too).
    function _flatten(gs) {
      var out = [];
      gs.forEach(function (g) { g.idxs.forEach(function (i) { out.push(_sfExercises[i]); }); });
      return out;
    }
    // Keyboard-operable alternative to the group drag (parity with the
    // "Move to…" pattern used for session-card rescheduling above): swap
    // this group with its neighbor and re-render, keeping focus on the
    // button that moved so repeated presses keep working.
    function _swapGroups(gi, dir) {
      var gs = _exGroups();
      var target = gi + dir;
      if (target < 0 || target >= gs.length) return;
      var tmp = gs[gi];
      gs[gi] = gs[target];
      gs[target] = tmp;
      _sfExercises = _flatten(gs);
      _renderStructureBuilder();
      var again = list.querySelector(
        dir < 0 ? '[data-gmove-up="' + target + '"]' : '[data-gmove-down="' + target + '"]'
      );
      if (again) again.focus();
    }
    list.querySelectorAll('[data-gmove-up]').forEach(function (b) {
      b.addEventListener('click', function () { _swapGroups(+b.getAttribute('data-gmove-up'), -1); });
    });
    list.querySelectorAll('[data-gmove-down]').forEach(function (b) {
      b.addEventListener('click', function () { _swapGroups(+b.getAttribute('data-gmove-down'), 1); });
    });
    // The drag handle itself is now focusable (role="button" tabindex="0")
    // — Enter/Space moves the group down as a minimal keyboard path directly
    // on the handle, mirroring the dedicated ▲/▼ buttons next to it.
    list.querySelectorAll('.pl-gdrag').forEach(function (h) {
      h.addEventListener('keydown', function (e) {
        if (e.key !== 'Enter' && e.key !== ' ' && e.key !== 'Spacebar') return;
        e.preventDefault();
        _swapGroups(+h.getAttribute('data-gdrag'), 1);
      });
    });
    list.querySelectorAll('.pl-exgroup').forEach(function (gEl) {
      var gi = +gEl.getAttribute('data-gi');
      var handle = gEl.querySelector('.pl-gdrag');
      if (handle) {
        handle.addEventListener('mousedown', function () { gEl.setAttribute('draggable', 'true'); });
        handle.addEventListener('mouseup', function () { gEl.removeAttribute('draggable'); });
      }
      gEl.addEventListener('dragstart', function (e) {
        if (gEl.getAttribute('draggable') !== 'true') return;
        e.dataTransfer.setData('text/plain', JSON.stringify({ kind: 'group', gi: gi }));
        e.stopPropagation();
      });
      gEl.addEventListener('dragend', function () { gEl.removeAttribute('draggable'); });
      gEl.addEventListener('dragover', function (e) { e.preventDefault(); gEl.classList.add('drop-hover'); });
      gEl.addEventListener('dragleave', function () { gEl.classList.remove('drop-hover'); });
      gEl.addEventListener('drop', function (e) {
        e.preventDefault(); e.stopPropagation();
        var payload;
        try { payload = JSON.parse(e.dataTransfer.getData('text/plain')); } catch (err) { return; }
        var gs = _exGroups();
        if (payload.kind === 'group' && payload.gi !== gi && gs[payload.gi]) {
          var moved = gs.splice(payload.gi, 1)[0];
          gs.splice(gi > payload.gi ? gi - 1 : gi, 0, moved);
          _sfExercises = _flatten(gs);
          _renderStructureBuilder();
        } else if (payload.kind === 'ex' && gs[gi]) {
          var ex = _sfExercises[payload.i];
          var tgt = gs[gi];
          if (!ex || tgt.idxs.indexOf(payload.i) !== -1) return; // own group — no-op
          // Anchor on the target group's last exercise OBJECT — index math
          // shifts under the splice, object identity doesn't.
          var anchor = _sfExercises[tgt.idxs[tgt.idxs.length - 1]];
          ex.block = tgt.block;
          _sfExercises.splice(payload.i, 1);
          _sfExercises.splice(_sfExercises.indexOf(anchor) + 1, 0, ex);
          _renderStructureBuilder();
        }
      });
    });
    list.querySelectorAll('.pl-block[data-xi]').forEach(function (row) {
      row.setAttribute('draggable', 'true');
      row.addEventListener('dragstart', function (e) {
        e.dataTransfer.setData('text/plain', JSON.stringify({ kind: 'ex', i: +row.getAttribute('data-xi') }));
        e.stopPropagation();
      });
      row.addEventListener('dragover', function (e) { e.preventDefault(); e.stopPropagation(); row.classList.add('drop-hover'); });
      row.addEventListener('dragleave', function () { row.classList.remove('drop-hover'); });
      row.addEventListener('drop', function (e) {
        e.preventDefault(); e.stopPropagation();
        var payload;
        try { payload = JSON.parse(e.dataTransfer.getData('text/plain')); } catch (err) { return; }
        if (payload.kind !== 'ex') return;
        var from = payload.i, to = +row.getAttribute('data-xi');
        if (from === to) return;
        var ex = _sfExercises[from];
        ex.block = _sfExercises[to].block;
        _sfExercises.splice(from, 1);
        _sfExercises.splice(from < to ? to - 1 : to, 0, ex);
        _renderStructureBuilder();
      });
    });
  }

  function _exRowHtml(x, i) {
    // Each numeric field is wrapped in a labeled span: display:contents on
    // desktop (the column header row carries the names), a visible inline
    // label on mobile where wrapping detaches inputs from their columns.
    function fld(label, inputHtml) {
      return '<label class="pl-exfld"><span class="pl-exfld-l">' + label + '</span>' + inputHtml + '</label>';
    }
    return '<div class="pl-block" data-xi="' + i + '">' +
      '<input class="pl-exname" data-f="name" aria-label="Exercise name" value="' + esc(x.name || '') + '" placeholder="Exercise"/>' +
      fld('Sets', '<input class="pl-bdur" data-f="sets" value="' + esc(x.sets != null ? x.sets : '') + '" placeholder="sets"/>') +
      fld('Reps', '<input class="pl-bdur" data-f="reps" value="' + esc(x.reps != null ? x.reps : '') + '" placeholder="reps"/>') +
      fld('Load', '<input class="pl-btgt" data-f="load" value="' + esc(x.load || '') + '" placeholder="load"/>') +
      // Target RPE for this exercise (blank until the coach sets one) — this
      // is the PLANNED target, separate from the real logged RPE that shows
      // on the matched workout's actual detail once trained.
      fld('RPE', '<input class="pl-bdur" data-f="rpe" value="' + esc(x.rpe != null ? x.rpe : '') + '" placeholder="RPE"/>') +
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
          if (_panel.open === 'detail') _smMarkDirty();
        });
      });
    });
    list.querySelectorAll('[data-rm-block]').forEach(function (b) {
      b.addEventListener('click', function () {
        _sfBlocks.splice(+b.getAttribute('data-rm-block'), 1);
        if (_panel.open === 'detail') { _renderDetailSection(); }
        else { _renderStructureBuilder(); }
      });
    });
    var add = document.getElementById('pl-addblock');
    if (add) add.onclick = function () {
      _sfBlocks.push({ phase: 'main', duration_min: 10 });
      if (_panel.open === 'detail') { _renderDetailSection(); }
      else { _renderStructureBuilder(); }
    };
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
      _wireExerciseGroups(list);
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

  // ── Plan-guard helpers (issue #1383) ─────────────────────────────────────────

  function _planCheck(payload, cb) {
    fetch('/api/training/plan-check', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (result) { cb(result); })
      .catch(function () { cb(null); });
  }

  function _planGuardHtml(result) {
    if (!result) return '';
    var warnings = result.warnings || [];
    var suggestions = result.suggestions || [];
    if (!warnings.length && !suggestions.length) return '';
    var html = '<div class="pl-guard-banner">';
    if (warnings.length) {
      html += '<div class="pl-guard-title">⚠ Muscle load warning</div>';
      warnings.forEach(function (w) {
        html += '<div class="pl-guard-warn">' + esc(w.message) + '</div>';
      });
    }
    if (suggestions.length) {
      html += '<div class="pl-guard-sug-title">Consider instead</div>';
      suggestions.forEach(function (s) {
        html += '<div class="pl-guard-sug">' + esc(s.reason) + '</div>';
      });
    }
    html += '</div>';
    return html;
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
      document.getElementById('pl-sf-cancel').onclick = _closeAdd;

      if (_addState.editId) {
        _renderStructureBuilder();
        document.getElementById('pl-sf-type').addEventListener('change', _renderStructureBuilder);
        var _guardConfirmed = false;
        document.getElementById('pl-sf-save').onclick = function () {
          var payload = _collectSingleForm();
          if (!payload.planned_date || !payload.session_type) { _toast('Date and type are required', true); return; }
          var btn = document.getElementById('pl-sf-save');
          function _doSave() {
            var editId = _addState.editId;
            _api('PATCH', '/api/planned-sessions/' + editId, payload)
              .then(function () { _toast('Session updated'); _guardConfirmed = false; _closeAdd(); _loadWeek(); })
              .catch(function (e) { _toast(e.message || 'Save failed', true); });
          }
          if (_guardConfirmed) { _doSave(); return; }
          _planCheck({ session_type: payload.session_type, structure: payload.structure || null }, function (result) {
            var guardEl = document.getElementById('pl-sf-guard');
            if (result && result.warnings && result.warnings.length) {
              if (guardEl) guardEl.innerHTML = _planGuardHtml(result);
              _guardConfirmed = true;
              if (btn) btn.textContent = 'Save anyway';
            } else {
              if (guardEl) guardEl.innerHTML = '';
              _doSave();
            }
          });
        };
        return;
      }

      // ── Create: draft-first ───────────────────────────────────────────────
      var typeEl = document.getElementById('pl-sf-type');
      var subEl = document.getElementById('pl-sf-subtype');
      function _syncSubtype() {
        var t = typeEl.value;
        var cur = subEl.value;
        var opts = _ADD_SUBTYPES[t] || [];
        var keep = opts.some(function (o) { return o.v === cur; });
        subEl.innerHTML = _addSubtypeOptions(t, keep ? cur : (opts[0] && opts[0].v));
        var defaults = { run: [40, 45], strength: [30, 40], plyo: [25, 25], stretch: [0, 15] };
        var d = defaults[t] || [30, 30];
        var tssEl = document.getElementById('pl-sf-tss');
        var durEl = document.getElementById('pl-sf-dur');
        if (tssEl && !tssEl.dataset.touched) tssEl.value = d[0];
        if (durEl && !durEl.dataset.touched) durEl.value = d[1];
      }
      typeEl.addEventListener('change', function () {
        _syncSubtype();
        if (_addDraftExtras.manualOpen) _renderStructureBuilder();
        _addDraftExtras.ai = null;
      });
      ['pl-sf-tss', 'pl-sf-dur'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.addEventListener('input', function () { el.dataset.touched = '1'; });
      });

      var manualTog = document.getElementById('pl-sf-manual-tog');
      if (manualTog) manualTog.onclick = function () {
        _addDraftExtras.manualOpen = !_addDraftExtras.manualOpen;
        manualTog.textContent = _addDraftExtras.manualOpen ? 'Hide manual structure' : 'Fill structure manually';
        var host = document.getElementById('pl-sf-structure');
        if (!host) return;
        if (_addDraftExtras.manualOpen) {
          host.style.display = '';
          _renderStructureBuilder();
        } else {
          host.style.display = 'none';
          host.innerHTML = '';
        }
      };
      if (_addDraftExtras.manualOpen) _renderStructureBuilder();

      function _readCreateCustom() {
        var wt = typeEl.value;
        var custom = {
          workout_type: wt,
          subtype: subEl.value || wt,
          target_tss: parseFloat(document.getElementById('pl-sf-tss').value) || 0,
          duration_minutes: parseInt(document.getElementById('pl-sf-dur').value, 10) || 0,
          intent: (document.getElementById('pl-sf-name').value || '').trim(),
          notes: (document.getElementById('pl-sf-notes').value || '').trim() || null,
        };
        var structure = null;
        if (_addDraftExtras.manualOpen) {
          var payload = _collectSingleForm();
          if (payload && payload.structure) structure = payload.structure;
        } else if (_addDraftExtras.ai) {
          var ai = _addDraftExtras.ai;
          if (Array.isArray(ai.exercises) && ai.exercises.length) structure = { exercises: ai.exercises };
          else if (Array.isArray(ai.blocks) && ai.blocks.length) structure = { blocks: ai.blocks };
          if (!custom.intent && ai.intent) custom.intent = ai.intent;
          if (!custom.notes && ai.notes) custom.notes = ai.notes;
        }
        if (structure) custom.structure = structure;
        return custom;
      }

      function _saveCreateDraft(apply) {
        var dateEl = document.getElementById('pl-sf-date');
        if (!dateEl.value) { _toast('Pick a date first', true); return; }
        var day = _dayOffsetForDate(dateEl.value);
        if (day < 0 || day > 6) {
          _toast('Date must be in the visible week', true);
          return;
        }
        var btn = document.getElementById(apply ? 'pl-sf-draft-apply' : 'pl-sf-draft');
        if (btn) { btn.disabled = true; btn.textContent = apply ? 'Applying…' : 'Saving…'; }
        _addDraftCustom(day, _readCreateCustom(), { apply: !!apply })
          .then(function () {
            _toast(apply ? 'Draft applied to plan' : 'Saved to week draft');
            _closeAdd();
            _loadWeek(function () { if (_draftVisible) _loadDraft(); });
          })
          .catch(function (err) {
            if (btn) {
              btn.disabled = false;
              btn.textContent = apply ? 'Save draft & apply' : 'Save draft';
            }
            var detail = err && err.detail;
            _toast((detail && (detail.block_reason || detail.error)) || (err && err.message) || 'Failed', true);
          });
      }

      var draftBtn = document.getElementById('pl-sf-draft');
      var applyBtn = document.getElementById('pl-sf-draft-apply');
      var legacySave = document.getElementById('pl-sf-save');
      if (draftBtn) draftBtn.onclick = function () { _saveCreateDraft(false); };
      if (applyBtn) applyBtn.onclick = function () { _saveCreateDraft(true); };
      if (legacySave) {
        // Draft pipeline off — keep direct planned_sessions create
        legacySave.onclick = function () {
          var payload = {
            planned_date: document.getElementById('pl-sf-date').value,
            session_type: typeEl.value,
            name: document.getElementById('pl-sf-name').value || null,
            notes: document.getElementById('pl-sf-notes').value || null,
            structure: null,
          };
          var custom = _readCreateCustom();
          if (custom.structure) payload.structure = custom.structure;
          _api('POST', '/api/planned-sessions', payload)
            .then(function () { _toast('Session saved'); _closeAdd(); _loadWeek(); })
            .catch(function (e) { _toast(e.message || 'Save failed', true); });
        };
      }
    } else if (_addState.top === 'single' && _addState.sub === 'json') {
      _wireSingleJSON();
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
    var p = {
      planned_date: o.date,
      session_type: (o.type || '').toLowerCase(),
      name: o.name || null,
      notes: o.notes || null,
      structure: null,
    };
    var structure = {};
    if (o.structure && typeof o.structure === 'object' && !Array.isArray(o.structure)) {
      Object.keys(o.structure).forEach(function (k) {
        if (o.structure[k] != null) structure[k] = o.structure[k];
      });
    }
    if (o.blocks) structure.blocks = o.blocks;
    if (o.exercises) structure.exercises = o.exercises;
    if (o.focus) structure.focus = o.focus;
    ['target_tss', 'duration_minutes', 'distance_km', 'subtype'].forEach(function (k) {
      if (o[k] != null && structure[k] == null) structure[k] = o[k];
    });
    if (Object.keys(structure).length) p.structure = structure;
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
      '<textarea class="pl-jsonta" id="pl-sj-ta" aria-label="Session JSON">' + esc(JSON.stringify(tplSingleRun, null, 2)) + '</textarea>' +
      '<div class="pl-btnrow" style="margin-top:10px;"><button class="pl-btn pl-ghost" id="pl-sj-val">Validate &amp; preview</button></div>' +
      '<div id="pl-sj-prev" aria-live="polite"></div>' +
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
  // Shares the backend's single-session generator with suggestion-row Update
  // (POST /api/plan/suggestions/session → pattern fill). This side starts from
  // a blank date/type; Update re-fills an existing suggestion from duration/subtype.
  var _aiSessionResult = null; // the last generated session, pending Save

  function _phaseLabel(ph) {
    var p = String(ph || '').toLowerCase();
    if (p === 'warmup') return 'Warmup';
    if (p === 'cooldown') return 'Cooldown';
    if (p === 'main') return 'Main set';
    if (p === 'mp' || p === 'marathon_pace') return 'MP segment';
    return ph || 'Block';
  }

  function _singleAIHtml() {
    _aiSessionResult = null;
    return '<div class="pl-frow">' +
        '<div class="pl-fld"><label>Date</label><input type="date" id="pl-ai-date" aria-label="Session date" value="' + esc(_addState.presetDate) + '"/></div>' +
        '<div class="pl-fld"><label>Type</label><select id="pl-ai-type" aria-label="Session type">' +
          '<option value="run">Run</option><option value="strength">Strength</option>' +
          '<option value="plyo">Plyo</option><option value="rest">Rest</option>' +
        '</select></div>' +
      '</div>' +
      '<div class="pl-fld" style="margin-top:10px;"><label>Note to the coach (optional)</label>' +
        '<textarea id="pl-ai-note" aria-label="Note to the coach" placeholder="e.g. focus on hip mobility, keep it under 30 minutes"></textarea></div>' +
      '<div class="pl-btnrow" style="margin-top:10px;"><button class="pl-btn pl-ghost" id="pl-ai-gen">✨ Generate</button></div>' +
      '<div id="pl-ai-prev" aria-live="assertive"></div>' +
      '<div class="pl-btnrow" style="margin-top:14px;"><button class="pl-btn pl-lime" id="pl-ai-save" disabled>Save session</button><button class="pl-btn pl-ghost" id="pl-ai-cancel">Cancel</button></div>';
  }

  // Local, read-only preview rows for the Ask-AI modal.
  // Pattern-fill session pane is PlanFillPreview (js/lib/plan-fill-preview.js).
  function _aiPreviewExRow(x) {
    var sr = (x.sets != null && x.reps != null) ? (x.sets + ' × ' + x.reps) : (x.sets != null ? x.sets + ' sets' : '');
    return '<div class="pl-exd"><span class="pl-en">' + esc(x.name || 'Exercise') + '</span>' +
      '<span class="pl-sr">' + esc(sr) + '</span>' +
      '<span class="pl-es" style="color:var(--text-sub)">' + esc(x.load || '') + '</span></div>';
  }
  function _aiPreviewBlockRow(b) {
    var dur = b.duration_min != null ? b.duration_min + ' min' : '';
    var main = (b.repeat && b.repeat > 1) ? (b.repeat + ' × ' + dur) : dur;
    return '<div class="pl-exd"><span class="pl-en">' + esc(_phaseLabel(b.phase)) + '</span>' +
      '<span class="pl-sr">' + esc(main) + '</span>' +
      '<span class="pl-es" style="color:var(--text-sub)">' + esc(b.target || '') + '</span></div>';
  }

  function _aiSessionPreviewHtml(s) {
    var tssStr = s.target_tss > 0 ? s.target_tss + ' TSS' : '';
    var durStr = s.duration_minutes > 0 ? s.duration_minutes + 'min' : '';
    var meta = [tssStr, durStr].filter(Boolean).join(' · ');
    var body = '';
    if (Array.isArray(s.exercises) && s.exercises.length) {
      // Group by block (Warm-up / Heavy compound / Superset 1 / ...) — the
      // generated data carries the block names; a flat list hides them.
      var order = [];
      s.exercises.forEach(function (x) {
        var b = (x && x.block) ? x.block : 'Exercises';
        if (order.indexOf(b) === -1) order.push(b);
      });
      body = '<div class="pl-blocklist" style="margin-top:8px;">' + order.map(function (b) {
        var rows = s.exercises.filter(function (x) { return ((x && x.block) ? x.block : 'Exercises') === b; })
          .map(_aiPreviewExRow).join('');
        return '<div class="pl-ai-blockh">' + esc(b) + '</div>' + rows;
      }).join('') + '</div>';
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
        '<td><select data-bf="type" aria-label="' + d + ' session type"><option value="rest">Rest</option><option value="run">Run</option><option value="strength">Strength</option><option value="plyo">Plyo</option></select></td>' +
        '<td><input data-bf="name" aria-label="' + d + ' session name" placeholder="session name"/></td>' +
        '<td><input data-bf="duration" aria-label="' + d + ' duration" placeholder="—"/></td></tr>';
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
      '<textarea class="pl-jsonta" id="pl-bj-ta" aria-label="Week JSON">' + esc(JSON.stringify(tplBulkWeek, null, 2)) + '</textarea>' +
      '<div class="pl-btnrow" style="margin-top:10px;"><button class="pl-btn pl-ghost" id="pl-bj-val">Validate &amp; preview</button></div>' +
      '<div id="pl-bj-prev" aria-live="polite"></div>' +
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
        return '<div class="pl-previewrow"><span style="width:92px">' + esc(o.date || '?') + '</span><span style="width:72px">' + esc(o.type || '?') + '</span><span style="flex:1">' + esc(o.name || '') + '</span><span style="color:var(--text-sub)">' + esc(det) + '</span></div>';
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
        '<span style="font-size:11px;font-weight:700;color:var(--text-sub);">Delimiter:</span>' +
        '<select class="pl-delimsel" id="pl-delim" aria-label="Delimiter">' +
          '<option value="pipe"' + (code === 'pipe' ? ' selected' : '') + '>Pipe  |</option>' +
          '<option value="comma"' + (code === 'comma' ? ' selected' : '') + '>Comma  ,</option>' +
          '<option value="tab"' + (code === 'tab' ? ' selected' : '') + '>Tab</option>' +
        '</select>' +
        '<button class="pl-btn pl-ghost" id="pl-sep-dl">⬇ Download template</button>' +
      '</div>' +
      '<div class="pl-infobanner" style="margin-bottom:10px;">One session per line: <b>date' + dc + 'type' + dc + 'name' + dc + 'duration' + dc + 'notes</b>. Simple fields only; open a session afterward for block/exercise detail.</div>' +
      '<textarea class="pl-jsonta" id="pl-sep-ta" aria-label="Week sessions as delimited text">' + esc(_sepTemplate(code)) + '</textarea>' +
      '<div class="pl-btnrow" style="margin-top:10px;"><button class="pl-btn pl-ghost" id="pl-sep-val">Parse &amp; preview</button></div>' +
      '<div id="pl-sep-prev" aria-live="polite"></div>' +
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
      return '<div class="pl-previewrow"><span style="width:92px">' + esc(r.date || '?') + '</span><span style="width:72px">' + esc(r.type || '?') + '</span><span style="flex:1">' + esc(r.name || '—') + '</span><span style="color:var(--text-sub)">' + esc(r.duration || '—') + '</span></div>';
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

  // ══ UNIFIED SESSION MODAL (view = edit = AI) ════════════════════════════════
  // Merges Session Detail + Edit + Generate details into one surface.
  // Create-new still uses the Add panel (`_openAdd`); edit opens this modal.

  var _sm = {
    baseline: null,
    dirty: false,
    mode: 'view', // view (in-gym) | edit (structure)
    strydOpen: false,
    aiForcedOpen: false,
    aiBusy: false,
    aiError: '',
    structTab: 'simple', // simple | detailed | json
    suppressDomSync: false,
    swap: null, // { mode: 'swap'|'add', index?, block?, query, searchAll, avoid[] }
    avoidParts: null, // cached from /api/plan/exercises/avoid-parts
  };

  // Strength/plyo block labels — same catalog as plan_slot._STRENGTH_BLOCKS.
  var _SM_BLOCK_OPTIONS = [
    'Warm-up', 'Heavy compound', 'Superset 1', 'Superset 2', 'Standalone',
    'Accessories', 'Bodyweight', 'Plyometrics', 'Isometrics', 'Stretch',
    'Cooldown', 'Finisher', 'EMOM', '40/20',
  ];

  var _H = function () { return window.PlanSessionHelpers || {}; };

  function _smHasStructure(p) {
    var type = ((p && p.session_type) || 'run').toLowerCase();
    if (type === 'run') return _sfBlocks.length > 0;
    if (_sfExercises.length) return true;
    if (_sfFocus && String(_sfFocus).trim()) return true;
    return !!(_H().hasStructure && _H().hasStructure(p && p.structure));
  }

  function _smAiDormant(p) {
    if (_sm.aiForcedOpen) return false;
    return !!(_H().aiBarDormant && _H().aiBarDormant(p));
  }

  function _smSeedBuilders(p) {
    var s = (p && p.structure) || {};
    if ((p.session_type || '') === 'run') {
      _sfBlocks = (Array.isArray(s.blocks) ? s.blocks : []).map(function (b) {
        return Object.assign({}, b);
      });
      _sfExercises = [];
      _sfFocus = '';
      _sm.structTab = 'simple';
    } else {
      _sfBlocks = [];
      if (Array.isArray(s.exercises) && s.exercises.length) {
        _sfStrengthMode = 'detailed';
        if (!_sm.structTab || _sm.structTab === 'detailed') _sm.structTab = 'simple';
        _sfExercises = s.exercises.map(function (x) {
          var row = Object.assign({}, x);
          if (!row.source) row.source = 'generated';
          if (row.pinned == null) {
            row.pinned = row.source !== 'generated' && row.source !== 'pattern';
          }
          // Legacy "done" meant "not skipped". Gym checklist uses "completed".
          if (row.state === 'done') row.state = '';
          return row;
        });
        _sfFocus = s.focus || '';
      } else {
        _sfStrengthMode = 'simple';
        _sm.structTab = 'simple';
        _sfFocus = s.focus || '';
        _sfExercises = [];
      }
    }
  }

  function _smCollectStructure(type) {
    type = (type || 'run').toLowerCase();
    if (type === 'rest') return null;
    var prev = (_detail && _detail.structure) || {};
    var out;
    if (type === 'run') {
      out = { blocks: _sfBlocks.map(function (b) { return Object.assign({}, b); }) };
    } else if (_sm.structTab === 'simple' || _sfStrengthMode === 'simple') {
      out = { focus: _sfFocus || '' };
      if (_sfExercises.length) {
        out.exercises = _sfExercises.map(function (x) { return Object.assign({}, x); });
      }
    } else {
      out = { exercises: _sfExercises.map(function (x) { return Object.assign({}, x); }) };
      if (_sfFocus) out.focus = _sfFocus;
    }
    if (!out) return null;
    ['target_tss', 'duration_minutes', 'distance_km', 'source'].forEach(function (k) {
      if (prev[k] != null && out[k] == null) out[k] = prev[k];
    });
    // Session budget pins (editable) override structure pins.
    var tssEl = document.getElementById('pl-sm-pin-tss');
    var durEl = document.getElementById('pl-sm-pin-dur');
    var distEl = document.getElementById('pl-sm-pin-dist');
    if (tssEl && tssEl.value !== '' && isFinite(Number(tssEl.value))) {
      out.target_tss = Number(tssEl.value);
    }
    if (durEl && durEl.value !== '' && isFinite(Number(durEl.value))) {
      out.duration_minutes = Number(durEl.value);
    }
    if (distEl && !distEl.disabled && distEl.value !== '' && distEl.value !== '—' && isFinite(Number(distEl.value))) {
      out.distance_km = Number(distEl.value);
    }
    var subEl = document.getElementById('pl-sm-subtype');
    if (subEl && subEl.value) {
      out.subtype = subEl.value;
    } else if (prev.subtype != null && out.subtype == null) {
      out.subtype = prev.subtype;
    }
    return out;
  }

  function _smUiSubtype(type, p) {
    var raw = String(((p && p.structure && p.structure.subtype) || (p && p.subtype) || '')).trim().toLowerCase();
    if (!raw) return '';
    if (raw.indexOf('strength_') === 0) raw = raw.slice('strength_'.length);
    if (raw.indexOf('easy_') === 0) raw = 'easy';
    if (raw === 'long_run') raw = 'long';
    var list = _ADD_SUBTYPES[type] || [];
    for (var i = 0; i < list.length; i++) {
      if (list[i].v === raw) return raw;
    }
    return raw;
  }

  function _smReadDraftFromDom(p) {
    var nameEl = document.getElementById('pl-sm-name');
    var notesEl = document.getElementById('pl-sm-notes');
    var dateEl = document.getElementById('pl-sm-date');
    var typeEl = document.getElementById('pl-sm-type');
    var type = typeEl ? typeEl.value : (p.session_type || 'run');
    return {
      name: nameEl ? nameEl.value.trim() : (p.name || ''),
      notes: notesEl ? notesEl.value : (p.notes || ''),
      planned_date: dateEl ? dateEl.value : (p.planned_date || ''),
      session_type: type,
      structure: _smCollectStructure(type),
    };
  }

  function _smIsEdit() {
    return _sm.mode === 'edit';
  }

  /** Portable session JSON for sharing / later import (Add session → JSON). */
  function _smExportExerciseRow(ex) {
    if (!ex || typeof ex !== 'object') return null;
    var row = {};
    if (ex.block) row.block = ex.block;
    row.name = ex.name || 'Exercise';
    if (ex.sets != null && ex.sets !== '') row.sets = ex.sets;
    if (ex.reps != null && String(ex.reps).trim() !== '') row.reps = ex.reps;
    if (ex.load != null && String(ex.load).trim() !== '') row.load = ex.load;
    if (ex.spend_tss != null && isFinite(Number(ex.spend_tss))) row.spend_tss = Number(ex.spend_tss);
    if (ex.spend_min != null && isFinite(Number(ex.spend_min))) row.spend_min = Number(ex.spend_min);
    return row;
  }

  function _smExportSessionPayload(p) {
    p = p || _detail || {};
    var draft = _smReadDraftFromDom(p);
    var type = (draft.session_type || p.session_type || 'run').toLowerCase();
    var structure = draft.structure || p.structure || {};
    var out = {
      date: draft.planned_date || p.planned_date || '',
      type: type,
      name: draft.name || p.name || '',
    };
    var notes = draft.notes != null ? draft.notes : (p.notes || '');
    if (notes) out.notes = notes;
    if (structure.subtype) out.subtype = structure.subtype;
    if (structure.focus) out.focus = structure.focus;
    if (structure.target_tss != null) out.target_tss = structure.target_tss;
    if (structure.duration_minutes != null) out.duration_minutes = structure.duration_minutes;
    if (structure.distance_km != null) out.distance_km = structure.distance_km;
    if (type === 'run' && Array.isArray(structure.blocks)) {
      out.blocks = structure.blocks.map(function (b) { return Object.assign({}, b); });
    } else if (Array.isArray(structure.exercises) && structure.exercises.length) {
      out.exercises = structure.exercises.map(_smExportExerciseRow).filter(Boolean);
    } else if (Array.isArray(_sfExercises) && _sfExercises.length && type !== 'run') {
      out.exercises = _sfExercises.map(_smExportExerciseRow).filter(Boolean);
    } else if (Array.isArray(_sfBlocks) && _sfBlocks.length && type === 'run') {
      out.blocks = _sfBlocks.map(function (b) { return Object.assign({}, b); });
    }
    return out;
  }

  function _smExportFilename(payload) {
    var date = (payload.date || 'session').replace(/[^\d-]/g, '');
    var slug = String(payload.name || payload.type || 'session')
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '')
      .slice(0, 48) || 'session';
    return 'perf-coach-session-' + date + '-' + slug + '.json';
  }

  function _smDownloadSessionJson(p) {
    var payload = _smExportSessionPayload(p);
    _downloadFile(
      _smExportFilename(payload),
      JSON.stringify(payload, null, 2),
      'application/json'
    );
    _toast('Session JSON downloaded — share or paste into Add → JSON');
  }

  function _smMarkDirty() {
    if (!_detail || !_sm.baseline) return;
    var cur = _smReadDraftFromDom(_detail);
    _sm.dirty = !(_H().snapshotsEqual && _H().snapshotsEqual(_sm.baseline, cur));
    var dirtyEl = document.getElementById('pl-sm-dirty');
    var discardBtn = document.getElementById('pl-sm-discard');
    var saveBtn = document.getElementById('pl-sm-save');
    var closeBtn = document.getElementById('pl-sm-close-foot');
    if (dirtyEl) dirtyEl.textContent = _sm.dirty ? 'unsaved changes' : '';
    if (discardBtn) discardBtn.hidden = !_sm.dirty;
    if (saveBtn) saveBtn.hidden = !_sm.dirty;
    if (closeBtn) closeBtn.hidden = !!_sm.dirty;
  }

  function _smTypeLabel(t) {
    t = (t || '').toLowerCase();
    if (t === 'strength' || t === 'plyo') return 'LIFT';
    if (t === 'stretch') return 'STRETCH';
    if (t === 'rest') return 'REST';
    return 'RUN';
  }

  function _smMatchedLine(p) {
    if (!p.actual || !p.actual.id) return '';
    var bits = [p.actual.name || 'Matched workout'];
    if (p.actual.meta) bits.push(p.actual.meta);
    return '<span class="pl-sm-matched">✓ matched · ' + esc(bits.join(' ')) + '</span>';
  }

  function _smBudgetHtml(p) {
    if (!_smIsEdit()) return _smTilesHtml(p);
    var SB = window.SessionBudget;
    if (!SB || !SB.html) return _smTilesHtml(p) + _smAiBarHtml(p);
    if ((p.session_type || '') === 'rest') return '';
    if (_smAiDormant(p) && !_sm.aiForcedOpen) {
      return '<div class="pl-sm-ai pl-sm-ai-dormant" id="pl-sm-ai">' +
        '<div class="pl-sm-ai-h"><b>Session completed — nothing left to plan</b>' +
        '<button type="button" class="pl-sm-ai-expand" id="pl-sm-ai-expand">add structure anyway</button></div>' +
      '</div>';
    }
    var s = p.structure || {};
    var live = _smCollectStructure(p.session_type) || s;
    var type = (p.session_type || 'run').toLowerCase();
    var has = _smHasStructure(p);
    return SB.html({
      duration: live.duration_minutes != null ? live.duration_minutes : s.duration_minutes,
      tss: live.target_tss != null ? live.target_tss : s.target_tss,
      distance: live.distance_km != null ? live.distance_km : s.distance_km,
      distanceDisabled: type !== 'run',
      exercises: type === 'run' ? [] : (_sfExercises || []),
      hasStructure: has,
      refillBusy: _sm.aiBusy,
      refillLabel: has ? 'Refill unpinned' : 'Fill from patterns',
      showRefill: true,
      error: _sm.aiError || '',
    });
  }

  function _smTilesHtml(p) {
    var H = _H();
    var live = _smCollectStructure(p.session_type) || p.structure || {};
    var tiles = H.deriveTiles
      ? H.deriveTiles(live, {
          duration_minutes: live.duration_minutes,
          target_tss: live.target_tss,
          distance_km: live.distance_km,
        })
      : { duration_min: null, target_tss: null, distance_km: null };
    function cell(lab, val, empty) {
      return '<div class="pl-sm-tile"><div class="pl-sm-tl">' + lab + '</div>' +
        '<div class="pl-sm-tv' + (empty ? ' empty' : '') + '">' + esc(val) + '</div></div>';
    }
    return '<div class="pl-sm-tiles">' +
      cell('Duration', tiles.duration_min != null ? tiles.duration_min + ' min' : '—', tiles.duration_min == null) +
      cell('TSS', tiles.target_tss != null ? String(Math.round(tiles.target_tss)) : '—', tiles.target_tss == null) +
      cell('Distance', tiles.distance_km != null ? tiles.distance_km + ' km' : '—', tiles.distance_km == null) +
    '</div>';
  }

  function _smAiBarHtml(p) {
    if ((p.session_type || '') === 'rest') return '';
    var dormant = _smAiDormant(p);
    if (dormant) {
      return '<div class="pl-sm-ai pl-sm-ai-dormant" id="pl-sm-ai">' +
        '<div class="pl-sm-ai-h"><b>Session completed — nothing left to plan</b>' +
        '<button type="button" class="pl-sm-ai-expand" id="pl-sm-ai-expand">add structure anyway</button></div>' +
      '</div>';
    }
    var has = _smHasStructure(p);
    var s = p.structure || {};
    var pins = [];
    if (s.target_tss != null) pins.push(Math.round(s.target_tss) + ' TSS');
    if (s.duration_minutes != null) pins.push(s.duration_minutes + ' min');
    else {
      var dm = _H().durationMinutesFromBlocks && _H().durationMinutesFromBlocks(s.blocks);
      if (dm) pins.push(dm + ' min');
    }
    var pinNote = pins.length
      ? 'fills from patterns · keeps ' + pins.join(' · ') + ' pinned'
      : 'needs TSS or duration pinned to fill from patterns';
    var title = has ? 'Refill from patterns' : 'Fill from patterns';
    var goLab = has ? 'Refill' : 'Fill';
    var err = _sm.aiError
      ? '<div class="pl-sm-ai-err" id="pl-sm-ai-err" aria-live="assertive" role="alert">' + esc(_sm.aiError) + '</div>'
      : '<div class="pl-sm-ai-err" id="pl-sm-ai-err" aria-live="assertive" hidden></div>';
    return '<div class="pl-sm-ai" id="pl-sm-ai">' +
      '<div class="pl-sm-ai-h"><b>' + title + '</b><span>' + esc(pinNote) + '</span></div>' +
      '<div class="pl-sm-free">' +
        '<button type="button" class="pl-sm-go" id="pl-sm-ai-go"' +
          (_sm.aiBusy || !pins.length ? ' disabled' : '') + '>' +
          (_sm.aiBusy ? '…' : goLab) + '</button>' +
      '</div>' +
      err +
      '<div class="pl-sm-ai-n">' +
        'deterministic pattern fill · no LLM · review then save' +
      '</div>' +
    '</div>';
  }

  function _smStructureBodyHtml(p) {
    var type = (p.session_type || 'run').toLowerCase();
    var edit = _smIsEdit();
    if (type === 'rest') {
      return '<div class="pl-sm-empty-s">Rest day — no structure.</div>';
    }
    if (type === 'run') {
      if (!_sfBlocks.length && !_smHasStructure(p)) {
        return '<div class="pl-sm-empty-s">' +
          (edit ? 'No structure yet — Fill from patterns above, or open advanced › Detailed.'
            : 'No structure yet — tap Edit to fill this session.') +
          '</div>';
      }
      if (edit && _sm.structTab === 'json') {
        return '<textarea class="pl-jsonta" id="pl-sm-json" aria-label="Structure JSON" spellcheck="false">' +
          esc(JSON.stringify({ blocks: _sfBlocks }, null, 2)) + '</textarea>';
      }
      if (edit && _sm.structTab === 'detailed') {
        return '<div id="pl-sm-struct-host"></div>';
      }
      return _smPreviewPaneHtml(p, type);
    }
    // strength / plyo / stretch
    if (edit && _sm.structTab === 'json') {
      return '<textarea class="pl-jsonta" id="pl-sm-json" aria-label="Structure JSON" spellcheck="false">' +
        esc(JSON.stringify({ exercises: _sfExercises, focus: _sfFocus }, null, 2)) + '</textarea>';
    }
    if (edit && _sm.structTab === 'detailed') {
      return '<div id="pl-sm-struct-host"></div>';
    }
    if (!_sfFocus && !_sfExercises.length) {
      return '<div class="pl-sm-empty-s">' +
        (edit ? 'No structure yet — Fill from patterns above, or open advanced › Detailed.'
          : 'No structure yet — tap Edit to fill this session.') +
        '</div>';
    }
    var focusHtml = '';
    if (_sfFocus) {
      focusHtml = edit
        ? '<div class="pl-fld" style="margin-bottom:10px;"><label>Focus</label>' +
          '<input type="text" id="pl-sm-focus" aria-label="Focus" value="' + esc(_sfFocus) + '"/></div>'
        : '<div class="pl-sm-focus-ro">' + esc(_sfFocus) + '</div>';
    }
    return focusHtml + _smInteractiveExercisesHtml();
  }

  function _smProvChip(ex) {
    var src = String(ex.source || 'generated').toLowerCase();
    if (src === 'generated' || src === 'pattern') return '';
    var lab = '';
    var cls = 'manual';
    if (src === 'swap') { lab = 'SUBSTITUTED'; cls = 'swap'; }
    else if (src === 'substituted') { lab = 'SUBSTITUTED'; cls = 'swap'; }
    else if (src === 'homework_standing') { lab = 'HOMEWORK · STANDING'; cls = 'hwstand'; }
    else if (src === 'homework_week') {
      var days = ex.homework_days_left;
      lab = days != null ? ('HOMEWORK · ' + days + 'd LEFT') : 'HOMEWORK · WEEK';
      cls = 'hwweek';
    } else if (src === 'coach') { lab = 'COACH'; cls = 'hwstand'; }
    else if (src === 'manual') { lab = 'MANUAL'; cls = 'manual'; }
    else { lab = src.toUpperCase(); cls = 'manual'; }
    var tip = ex.replaced_name ? (' title="replaced ' + esc(ex.replaced_name) + '"') : '';
    return '<span class="pl-sm-prov ' + cls + '"' + tip + '>' + esc(lab) + '</span>';
  }

  function _smExIsPinned(ex) {
    if (window.SessionBudget && window.SessionBudget.isPinned) return window.SessionBudget.isPinned(ex);
    if (ex.pinned === true) return true;
    if (ex.pinned === false) return false;
    var src = String(ex.source || 'generated').toLowerCase();
    return src && src !== 'generated' && src !== 'pattern';
  }

  function _smSessionNameMap() {
    var map = {};
    _sfExercises.forEach(function (ex) {
      if (!ex || !ex.name) return;
      map[String(ex.name).trim().toLowerCase()] = ex.block || 'session';
    });
    return map;
  }

  function _smHlName(name, q) {
    if (!q) return esc(name);
    var i = String(name).toLowerCase().indexOf(String(q).toLowerCase());
    if (i < 0) return esc(name);
    return esc(name.slice(0, i)) + '<mark>' + esc(name.slice(i, i + q.length)) + '</mark>' +
      esc(name.slice(i + q.length));
  }

  function _smEnsureAvoidParts() {
    if (_sm.avoidParts) return Promise.resolve(_sm.avoidParts);
    return fetch('/api/plan/exercises/avoid-parts', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : { parts: [] }; })
      .then(function (j) {
        _sm.avoidParts = (j && j.parts) || [];
        return _sm.avoidParts;
      })
      .catch(function () {
        _sm.avoidParts = [];
        return _sm.avoidParts;
      });
  }

  function _smApplyCandidate(cand) {
    if (!_sm.swap || !cand) return;
    var SB = window.SessionBudget;
    if (_sm.swap.mode === 'swap') {
      var i = _sm.swap.index;
      var old = _sfExercises[i];
      if (!old) return;
      var oldSp = SB && SB.spendOf ? SB.spendOf(old) : { tss: Number(old.spend_tss) || 0, min: Number(old.spend_min) || 0 };
      // Keep the block's shared set count (not the library default).
      var keepSets = old.sets != null ? old.sets : (_smBlockSetsByName(old.block) || 3);
      _sfExercises[i] = {
        block: old.block,
        name: cand.name,
        sets: keepSets,
        reps: cand.default_reps || old.reps || '10',
        load: cand.default_load || old.load || 'moderate',
        spend_tss: cand.tss != null ? cand.tss : oldSp.tss,
        spend_min: oldSp.min,
        pinned: true,
        source: 'swap',
        replaced_name: old.name,
        state: old.state || '',
        exercise_id: cand.id || undefined,
      };
      if (_sm.swap.searchAll) _sfExercises[i].swap_left_block = true;
    } else {
      var block = _sm.swap.block || 'Accessories';
      var sets = _smBlockSetsByName(block);
      if (sets == null) sets = 3;
      var replaceIdx = -1;
      var insertAt = _sfExercises.length;
      for (var k = 0; k < _sfExercises.length; k++) {
        if (String(_sfExercises[k].block || '') === block) {
          insertAt = k + 1;
          if (!_sfExercises[k].name) replaceIdx = k;
        }
      }
      var row = {
        block: block,
        name: cand.name,
        sets: sets,
        reps: cand.default_reps || '10',
        load: cand.default_load || 'moderate',
        spend_tss: cand.tss != null ? cand.tss : Math.max(1, sets),
        spend_min: Math.max(2, sets * 2.5),
        pinned: true,
        source: 'manual',
        state: '',
        exercise_id: cand.id || undefined,
      };
      if (replaceIdx >= 0) _sfExercises[replaceIdx] = row;
      else _sfExercises.splice(insertAt, 0, row);
    }
    _sm.swap = null;
    _smMarkDirty();
    _renderDetailSection();
  }

  function _smMountSwapPicker(host) {
    if (!host || !_sm.swap) return;
    var swap = _sm.swap;
    // Search the whole library — no block scope / avoid-part chips.
    swap.searchAll = true;
    swap.avoid = [];
    var cur = swap.mode === 'swap' ? _sfExercises[swap.index] : null;
    var block = swap.mode === 'swap' ? ((cur && cur.block) || 'Exercises') : (swap.block || 'Exercises');
    var title = swap.mode === 'swap'
      ? ('Swap ' + ((cur && cur.name) || 'exercise'))
      : ('Add to ' + block);
    var SB = window.SessionBudget;
    var curTss = cur
      ? ((SB && SB.spendOf ? SB.spendOf(cur).tss : Number(cur.spend_tss)) || 0)
      : 0;

    host.innerHTML =
      '<div class="pl-sm-pickh"><span class="t">' + esc(title) + '</span>' +
        '<span class="s" id="pl-sm-pick-count"></span>' +
        '<button type="button" class="cx" id="pl-sm-pick-close" aria-label="Close">✕</button></div>' +
      '<div class="pl-sm-srch"><input type="search" id="pl-sm-pick-q" placeholder="Search exercises…" value="' +
        esc(swap.query || '') + '"/>' +
        '<button type="button" class="clr" id="pl-sm-pick-clr"' +
          ((swap.query) ? '' : ' hidden') + '>✕</button></div>' +
      '<div class="pl-sm-scope" id="pl-sm-pick-scope">loading…</div>' +
      '<div class="pl-sm-clist" id="pl-sm-pick-list"></div>' +
      '<div class="pl-sm-picknote" id="pl-sm-pick-note"></div>';

    document.getElementById('pl-sm-pick-close').onclick = function () {
      _sm.swap = null;
      _renderDetailSection();
    };
    var qEl = document.getElementById('pl-sm-pick-q');
    var clr = document.getElementById('pl-sm-pick-clr');
    qEl.oninput = function () {
      _sm.swap.query = qEl.value;
      clr.hidden = !qEl.value;
      _smFetchSwapCandidates();
    };
    clr.onclick = function () {
      qEl.value = '';
      _sm.swap.query = '';
      clr.hidden = true;
      _smFetchSwapCandidates();
      qEl.focus();
    };

    _smFetchSwapCandidates();
    qEl.focus();
  }

  function _smFetchSwapCandidates() {
    if (!_sm.swap) return;
    var swap = _sm.swap;
    var cur = swap.mode === 'swap' ? _sfExercises[swap.index] : null;
    var block = swap.mode === 'swap' ? ((cur && cur.block) || 'Exercises') : (swap.block || 'Exercises');
    var SB = window.SessionBudget;
    var curTss = cur
      ? ((SB && SB.spendOf ? SB.spendOf(cur).tss : Number(cur.spend_tss)) || 0)
      : 0;
    var body = {
      block: block,
      current_name: cur ? cur.name : null,
      current_tss: curTss,
      current_body_parts: (cur && cur.body_parts) || null,
      session_names: _smSessionNameMap(),
      avoid_parts: swap.avoid || [],
      query: swap.query || '',
      search_all_blocks: !!swap.searchAll,
    };
    fetch('/api/plan/exercises/swap-candidates', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (r) {
      return r.ok ? r.json() : Promise.reject(new Error('swap candidates failed'));
    }).then(function (data) {
      if (!_sm.swap) return;
      _smRenderSwapList(data, curTss, block);
    }).catch(function () {
      var list = document.getElementById('pl-sm-pick-list');
      if (list) list.innerHTML = '<div class="pl-sm-none">Could not load candidates</div>';
    });
  }

  function _smRenderSwapList(data, curTss, block) {
    var ok = data.eligible || [];
    var no = data.disabled || [];
    var count = document.getElementById('pl-sm-pick-count');
    if (count) {
      count.textContent = ok.length + ' available' + (no.length ? (' · ' + no.length + ' blocked') : '');
    }
    var scope = document.getElementById('pl-sm-pick-scope');
    if (scope) {
      scope.innerHTML = (data.library_count || 0) + ' in library · <b>' + ok.length + '</b> match' +
        (no.length ? (' · ' + no.length + ' already in session') : '');
    }
    var note = document.getElementById('pl-sm-pick-note');
    if (note) {
      note.innerHTML = 'searching all exercises · ranked by body-part overlap then TSS' +
        (curTss ? (' proximity to ' + curTss.toFixed(1)) : '') +
        ' · a swap arrives <b>pinned</b> — refill won\'t undo it';
    }
    function rowHtml(e, dis) {
      var d = Number(e.tss_delta != null ? e.tss_delta : ((e.tss || 0) - curTss));
      d = Math.round(d * 10) / 10;
      var cls = d > 0.5 ? 'up' : (d < -0.5 ? 'dn' : 'eq');
      var why = '';
      if (dis) {
        why = '<span class="pl-sm-why ' + esc(e.why_cls || '') + '">' + esc(e.why || '') +
          (e.where ? (' · ' + esc(e.where)) : '') + '</span>';
      }
      return '<button type="button" class="pl-sm-cand' + (dis ? ' dis' : '') + '"' +
        (dis ? ' disabled' : '') + ' data-cand-name="' + esc(e.name) + '">' +
        '<span class="cb"><span class="cn">' + _smHlName(e.name, _sm.swap.query || '') + '</span>' +
          '<span class="cr">' + esc(e.prescription || '') + '</span></span>' +
        why +
        '<span class="pl-sm-cd ' + cls + '">' + (d > 0 ? '+' : '') + d + ' TSS</span></button>';
    }
    var h = '';
    if (ok.length) {
      h = ok.map(function (e) { return rowHtml(e, false); }).join('');
    } else {
      h = '<div class="pl-sm-none">No ' +
        (_sm.swap.query ? ('match for "' + esc(_sm.swap.query) + '"') : 'candidate') +
        '.</div>';
    }
    if (no.length) {
      h += '<div class="pl-sm-sec">not available</div>' + no.map(function (e) { return rowHtml(e, true); }).join('');
    }
    var list = document.getElementById('pl-sm-pick-list');
    if (!list) return;
    list.innerHTML = h;
    list.querySelectorAll('.pl-sm-cand:not(.dis)').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var name = btn.getAttribute('data-cand-name');
        var cand = (ok.concat(no)).filter(function (c) { return c.name === name; })[0];
        if (cand) _smApplyCandidate(cand);
      });
    });
  }

  function _smExGroups() {
    var groups = [];
    _sfExercises.forEach(function (x, i) {
      var b = (x && x.block) ? x.block : 'Exercises';
      var last = groups[groups.length - 1];
      if (!last || last.block !== b) groups.push({ block: b, idxs: [i] });
      else last.idxs.push(i);
    });
    return groups;
  }

  function _smBlockSetsFromIdxs(idxs) {
    for (var i = 0; i < idxs.length; i++) {
      var ex = _sfExercises[idxs[i]];
      if (ex && ex.sets != null && isFinite(Number(ex.sets))) return Math.round(Number(ex.sets));
    }
    return 3;
  }

  function _smBlockSetsByName(block) {
    for (var i = 0; i < _sfExercises.length; i++) {
      if (String(_sfExercises[i].block || '') === String(block || '') &&
          _sfExercises[i].sets != null && isFinite(Number(_sfExercises[i].sets))) {
        return Math.round(Number(_sfExercises[i].sets));
      }
    }
    return null;
  }

  function _smApplyBlockSets(gi, sets) {
    var groups = _smExGroups();
    var g = groups[gi];
    if (!g) return;
    var n = Math.max(1, Math.min(12, Math.round(Number(sets)) || 3));
    g.idxs.forEach(function (i) {
      if (_sfExercises[i]) _sfExercises[i].sets = n;
    });
  }

  function _smNewBlockName() {
    var used = {};
    _sfExercises.forEach(function (x) { used[String(x.block || '')] = true; });
    for (var i = 0; i < _SM_BLOCK_OPTIONS.length; i++) {
      if (!used[_SM_BLOCK_OPTIONS[i]]) return _SM_BLOCK_OPTIONS[i];
    }
    var n = 2;
    while (used['Block ' + n]) n += 1;
    return 'Block ' + n;
  }

  function _smAddBlock() {
    var name = _smNewBlockName();
    _sfExercises.push({
      block: name,
      name: '',
      sets: 3,
      reps: '10',
      load: 'moderate',
      spend_tss: 3,
      spend_min: 7.5,
      pinned: false,
      source: 'manual',
      state: '',
    });
    _sm.swap = { mode: 'add', block: name, query: '', searchAll: true, avoid: [] };
    _smMarkDirty();
    _renderDetailSection();
  }

  function _smBlockSelectHtml(current, gi) {
    var cur = current || 'Exercises';
    var opts = _SM_BLOCK_OPTIONS.slice();
    if (opts.indexOf(cur) < 0) opts.unshift(cur);
    return '<select class="pl-sm-bnsel" data-blk-rename="' + gi + '" aria-label="Block type">' +
      opts.map(function (o) {
        return '<option value="' + esc(o) + '"' + (o === cur ? ' selected' : '') + '>' + esc(o) + '</option>';
      }).join('') +
    '</select>';
  }

  function _smMoveExInBlock(i, dir) {
    var j = i + dir;
    if (j < 0 || j >= _sfExercises.length) return false;
    var a = _sfExercises[i];
    var b = _sfExercises[j];
    if ((a.block || '') !== (b.block || '')) return false;
    _sfExercises[i] = b;
    _sfExercises[j] = a;
    return true;
  }

  function _smMoveBlockGroup(gi, dir) {
    var groups = _smExGroups();
    var gj = gi + dir;
    if (gj < 0 || gj >= groups.length) return false;
    var rebuilt = [];
    var order = groups.map(function (_, k) { return k; });
    var tmp = order[gi];
    order[gi] = order[gj];
    order[gj] = tmp;
    order.forEach(function (k) {
      groups[k].idxs.forEach(function (i) { rebuilt.push(_sfExercises[i]); });
    });
    _sfExercises = rebuilt;
    return true;
  }

  function _smDeleteBlockGroup(gi) {
    var groups = _smExGroups();
    if (!groups[gi]) return;
    var drop = {};
    groups[gi].idxs.forEach(function (i) { drop[i] = true; });
    _sfExercises = _sfExercises.filter(function (_, i) { return !drop[i]; });
  }

  function _smInteractiveExercisesHtml() {
    var groups = _smExGroups();
    var edit = _smIsEdit();
    var SB = window.SessionBudget;
    var swap = (_sm && _sm.swap) || null;

    function spendFooter() {
      var planned = (_detail && _detail.structure && _detail.structure.target_tss) || null;
      var actualTss = 0;
      var actualMin = 0;
      _sfExercises.forEach(function (ex) {
        if (String(ex.state || 'done') === 'skipped') return;
        var sp = SB && SB.spendOf ? SB.spendOf(ex) : { tss: 0, min: 0 };
        actualTss += sp.tss;
        actualMin += sp.min;
      });
      return '<div class="pl-sm-spend"><span>Session spend</span><span class="pl-sm-sv">' +
        (planned != null ? ('<s>planned ' + Math.round(planned) + ' TSS</s> ') : '') +
        'actual ' + (Math.round(actualMin * 10) / 10) + ' min · ' + (Math.round(actualTss * 10) / 10) + ' TSS' +
        '</span></div>';
    }

    var addBlkBtn = edit
      ? '<button type="button" class="pl-sm-addblk" data-blk-add="1">+ block</button>'
      : '';

    if (!groups.length) {
      if (!edit) return '';
      return '<div class="pl-sm-exlist" id="pl-sm-exlist">' + addBlkBtn + spendFooter() + '</div>';
    }

    var html = groups.map(function (g, gi) {
      var tss = 0;
      var mins = 0;
      var skipped = 0;
      var blockSets = _smBlockSetsFromIdxs(g.idxs);
      g.idxs.forEach(function (i) {
        var ex = _sfExercises[i];
        if (String(ex.state || 'done') === 'skipped') { skipped += 1; return; }
        var sp = SB && SB.spendOf ? SB.spendOf(ex) : { tss: Number(ex.spend_tss) || 0, min: Number(ex.spend_min) || 0 };
        tss += sp.tss;
        mins += sp.min;
      });
      var meta = (Math.round(mins * 10) / 10) + ' min · ' + (Math.round(tss * 10) / 10) + ' TSS' +
        (skipped ? (' · <span class="pl-sm-sk">' + skipped + ' skipped</span>') : '');
      var rows = g.idxs.map(function (i, pos) {
        var ex = _sfExercises[i];
        var pinned = _smExIsPinned(ex);
        var skippedRow = String(ex.state || '') === 'skipped';
        var doneRow = String(ex.state || '') === 'completed';
        var sp = SB && SB.spendOf ? SB.spendOf(ex) : { tss: Number(ex.spend_tss) || 0, min: Number(ex.spend_min) || 0 };
        // Sets live on the block — row shows reps · load only.
        var rxPlain = '';
        if (ex.reps != null && String(ex.reps).trim() !== '') rxPlain = String(ex.reps);
        if (ex.load) rxPlain += (rxPlain ? ' · ' : '') + ex.load;
        var rx;
        if (edit && ex.replaced_name) {
          rx = '<s>' + esc(ex.replaced_name) + '</s> → ' + esc(rxPlain) +
            (ex.substitute_reason ? (' · ' + esc(ex.substitute_reason)) : '');
        } else {
          rx = esc(rxPlain);
        }
        var minLab = (Math.round(sp.min * 10) / 10) + ' min';
        var tssLab = (Math.round(sp.tss * 10) / 10) + ' TSS';
        var leftCtl;
        var rightCtl;
        if (edit) {
          var swapOn = swap && swap.mode === 'swap' && swap.index === i;
          leftCtl = '<button type="button" class="pl-sm-delx" data-ex-del="' + i + '" title="Remove exercise" aria-label="Remove exercise">✕</button>' +
            '<span class="pl-sm-mv">' +
              '<button type="button" class="pl-sm-mbtn" data-ex-up="' + i + '"' +
                (pos === 0 ? ' disabled' : '') + ' aria-label="Move up">▲</button>' +
              '<button type="button" class="pl-sm-mbtn" data-ex-dn="' + i + '"' +
                (pos === g.idxs.length - 1 ? ' disabled' : '') + ' aria-label="Move down">▼</button>' +
            '</span>';
          rightCtl = '<span class="pl-sm-enum" data-ex-edit="min" data-ex-i="' + i + '" title="Minutes">' + minLab + '</span>' +
            '<span class="pl-sm-enum" data-ex-edit="tss" data-ex-i="' + i + '" title="TSS">' + tssLab + '</span>' +
            '<span class="pl-sm-exact">' +
              '<button type="button" class="pl-sm-pinbtn' + (pinned ? ' on' : '') + '" data-ex-pin="' + i + '"' +
                ' aria-pressed="' + (pinned ? 'true' : 'false') + '" title="Keep on refill">' +
                (pinned ? 'Pinned' : 'Pin') + '</button>' +
              '<button type="button" class="pl-sm-ib' + (swapOn ? ' on' : '') + '" data-ex-swap="' + i + '" title="Swap" aria-label="Swap">⇄</button>' +
            '</span>';
          return '<div class="pl-sm-ex' + (pinned ? ' pinned' : '') + (skippedRow ? ' skipped' : '') +
            (swapOn ? ' active' : '') + '" data-ex-i="' + i + '">' +
            leftCtl +
            '<span class="pl-sm-exb"><span class="pl-sm-en">' + esc(ex.name || 'Exercise') + '</span>' +
              '<span class="pl-sm-erx">' + rx + '</span></span>' +
            _smProvChip(ex) +
            rightCtl +
            '</div>' +
            (swapOn ? '<div class="pl-sm-pick" id="pl-sm-pick" data-pick-host="1"></div>' : '');
        }
        // View: empty checkbox until tapped at the gym; no per-row min/TSS; no swap strike.
        leftCtl = '<button type="button" class="pl-sm-chk' + (doneRow ? ' on' : '') + '" data-ex-skip="' + i + '"' +
          ' aria-label="' + (doneRow ? 'Mark not done' : 'Mark done') + '" aria-pressed="' +
          (doneRow ? 'true' : 'false') + '">' + (doneRow ? '✓' : '') + '</button>';
        return '<div class="pl-sm-ex' + (skippedRow ? ' skipped' : '') + (doneRow ? ' done' : '') +
          '" data-ex-i="' + i + '">' +
          leftCtl +
          '<span class="pl-sm-exb"><span class="pl-sm-en">' + esc(ex.name || 'Exercise') + '</span>' +
            '<span class="pl-sm-erx">' + esc(String(blockSets) + ' × ') + rx + '</span></span>' +
        '</div>';
      }).join('');
      var head;
      if (edit) {
        var addOn = swap && swap.mode === 'add' && swap.block === g.block;
        head = '<div class="pl-sm-blkh">' +
          '<span class="pl-sm-bhleft">' +
            '<span class="pl-sm-bmv">' +
              '<button type="button" class="pl-sm-mbtn" data-blk-up="' + gi + '"' +
                (gi === 0 ? ' disabled' : '') + ' aria-label="Move block up">▲</button>' +
              '<button type="button" class="pl-sm-mbtn" data-blk-dn="' + gi + '"' +
                (gi === groups.length - 1 ? ' disabled' : '') + ' aria-label="Move block down">▼</button>' +
            '</span>' +
            _smBlockSelectHtml(g.block, gi) +
            '<label class="pl-sm-bsets-lab" title="Sets for every exercise in this block">Sets ' +
              '<input type="number" class="pl-sm-bsets" data-blk-sets="' + gi + '" min="1" max="12" step="1" value="' +
              blockSets + '"/></label>' +
            '<button type="button" class="pl-sm-blkdel" data-blk-del="' + gi + '" title="Remove block" aria-label="Remove block">✕</button>' +
          '</span>' +
          '<span style="display:flex;gap:8px;align-items:center">' +
            '<span class="pl-sm-bm">' + meta + '</span>' +
            '<button type="button" class="pl-sm-addex" data-ex-add="' + esc(g.block) + '">+ exercise</button>' +
          '</span></div>';
        return '<div class="pl-sm-blk">' + head + rows +
          (addOn ? '<div class="pl-sm-pick" id="pl-sm-pick" data-pick-host="1"></div>' : '') +
        '</div>';
      }
      head = '<div class="pl-sm-blkh"><span class="pl-sm-bn">' + esc(g.block) + '</span>' +
        '<span class="pl-sm-bm">' + blockSets + ' sets · ' + meta + '</span></div>';
      return '<div class="pl-sm-blk">' + head + rows + '</div>';
    }).join('');

    return '<div class="pl-sm-exlist" id="pl-sm-exlist">' + html + addBlkBtn + spendFooter() + '</div>';
  }

  /** Read-only preview pane (same as admin / plan suggestions) for Simple tab. */
  function _smPreviewPaneHtml(p, type) {
    var P = window.PlanFillPreview;
    if (!P || !P.sessionPaneHtml) return '';
    var s = (p && p.structure) || {};
    var exs = type === 'run' ? [] : (_sfExercises || []);
    var blocks = type === 'run' ? (_sfBlocks || []) : [];
    if (!exs.length && !blocks.length) return '';
    return '<div class="pl-sm-preview">' + P.sessionPaneHtml({
      exercises: exs,
      blocks: blocks,
      workout_type: type,
      muscle_footprint: s._muscle_footprint || s.muscle_footprint || null,
      muscle_summary: s.muscle_summary || null,
      fill_log: null,
    }, { showBudget: false }) + '</div>';
  }

  function _smUnifiedHtml(p) {
    var type = (p.session_type || 'run').toLowerCase();
    var fam = _famClass(type);
    var tagCls = (type === 'strength' || type === 'plyo') ? 'lift' : '';
    var statusRow = _detailStatusActionsHtml(p);
    var edit = _smIsEdit();
    var advOpen = edit && (_sm.structTab === 'detailed' || _sm.structTab === 'json');
    var advHtml = edit
      ? ('<span class="pl-sm-adv">' +
          '<button type="button" class="pl-sm-adv-tog" id="pl-sm-adv-tog">' +
            (advOpen ? 'advanced ▾' : 'advanced ›') + '</button>' +
          (advOpen
            ? '<button type="button" class="pl-sm-tab' + (_sm.structTab === 'detailed' ? ' on' : '') + '" data-stab="detailed">Detailed</button>' +
              '<button type="button" class="pl-sm-tab' + (_sm.structTab === 'json' ? ' on' : '') + '" data-stab="json">JSON</button>'
            : '') +
        '</span>')
      : '';

    var subSelected = _smUiSubtype(type, p);
    var subtypeOpts = _ADD_SUBTYPES[type] || [];
    var subtypeHtml = '';
    if (subtypeOpts.length) {
      if (edit) {
        subtypeHtml = '<select id="pl-sm-subtype" aria-label="Session subtype">' +
          '<option value="">Subtype</option>' +
          _addSubtypeOptions(type, subSelected) +
        '</select>';
      } else if (subSelected) {
        var subLab = subSelected;
        subtypeOpts.forEach(function (o) { if (o.v === subSelected) subLab = o.l; });
        subtypeHtml = '<span class="pl-sm-subtag">' + esc(subLab) + '</span>';
      }
    }

    var stryd = '';
    if (type === 'run') {
      stryd = '<div class="pl-sm-stryd" id="pl-sm-stryd-toggle">▸ <b>Copy for Stryd Workout Builder</b> — power/pace targets, import-safe</div>' +
        '<div class="pl-exportbox" id="pl-sm-stryd-panel"' + (_sm.strydOpen ? '' : ' hidden') + '>' +
          '<div class="pl-eh"><span class="pl-et">Stryd paste</span><button class="pl-copybtn" id="pl-det-copy">Copy</button></div>' +
          '<div class="pl-ewarn">Paste into PowerCenter’s Workout Builder. Power-or-pace targets only.</div>' +
          '<pre id="pl-stryd-pre">' + esc(_strydText(p)) + '</pre>' +
        '</div>';
    }

    var modeBtn = edit
      ? '<button type="button" class="pl-sm-mode" id="pl-sm-done-edit">Done editing</button>'
      : '<button type="button" class="pl-sm-mode on" id="pl-sm-enter-edit">Edit</button>';
    var exportBtn =
      '<button type="button" class="pl-sm-mode" id="pl-sm-export-json" title="Download shareable session JSON">' +
      'Export JSON</button>';

    var metaType = edit
      ? ('<select id="pl-sm-type" aria-label="Session type">' +
          ['run', 'strength', 'plyo', 'stretch', 'rest'].map(function (t) {
            return '<option value="' + t + '"' + (type === t ? ' selected' : '') + '>' +
              (t.charAt(0).toUpperCase() + t.slice(1)) + '</option>';
          }).join('') +
        '</select>')
      : ('<span class="pl-sm-typero">' + esc(type.charAt(0).toUpperCase() + type.slice(1)) + '</span>');

    var dateHtml = edit
      ? '<input class="pl-sm-datef" type="date" id="pl-sm-date" aria-label="Session date" value="' + esc(p.planned_date || '') + '"/>'
      : '<span class="pl-sm-date-ro">' + esc(p.planned_date || '') + '</span>';

    var nameHtml = edit
      ? '<input class="pl-sm-name" id="pl-sm-name" aria-label="Session name" value="' + esc(p.name || '') + '" placeholder="Session name"/>'
      : '<div class="pl-sm-name-ro">' + esc(p.name || 'Session') + '</div>';

    var sech = edit
      ? ('<div class="pl-sm-sech"><span class="pl-sm-lbl">Exercises</span>' +
          '<div class="pl-sm-tabs">' +
            '<button type="button" class="pl-sm-tab' + (_sm.structTab === 'simple' || !advOpen ? ' on' : '') + '" data-stab="simple">Simple</button>' +
            advHtml +
          '</div></div>')
      : '<div class="pl-sm-sech"><span class="pl-sm-lbl">Exercises</span></div>';

    var notesHtml = edit
      ? ('<div class="pl-sm-notes"><span class="pl-sm-lbl">Coach notes</span>' +
          '<textarea id="pl-sm-notes" rows="3" aria-label="Coach notes">' + esc(p.notes || '') + '</textarea></div>')
      : (p.notes
        ? '<div class="pl-sm-notes"><span class="pl-sm-lbl">Coach notes</span><div class="pl-sm-notes-ro">' + esc(p.notes) + '</div></div>'
        : '');

    return '<div class="pl-sm-pad' + (edit ? ' is-edit' : ' is-view') + '" data-sm-mode="' + (edit ? 'edit' : 'view') + '">' +
      '<div class="pl-sm-top"><span class="pl-sm-lbl">Session</span>' +
        '<span class="pl-sm-topr">' + exportBtn + modeBtn +
        '<button type="button" class="pl-sm-x" id="pl-detclose" aria-label="Close">✕</button></span></div>' +
      '<div class="pl-sm-meta">' +
        '<span class="pl-sm-tag ' + tagCls + '">' + _smTypeLabel(type) + '</span>' +
        metaType +
        subtypeHtml +
        dateHtml +
        _smMatchedLine(p) +
      '</div>' +
      nameHtml +
      _detailIdRowHtml(p) +
      statusRow +
      _smBudgetHtml(p) +
      sech +
      '<div id="pl-sm-struct-body">' + _smStructureBodyHtml(p) + '</div>' +
      notesHtml +
      (edit ? stryd : '') +
    '</div>' +
    '<div class="pl-sm-foot">' +
      (edit ? '<button type="button" class="pl-sm-del" id="pl-det-delete">Delete</button>' : '') +
      '<span class="pl-sm-sp"></span>' +
      '<span class="pl-sm-dirty" id="pl-sm-dirty" aria-live="polite"></span>' +
      '<button type="button" class="pl-sm-ghost" id="pl-sm-discard" hidden>Discard</button>' +
      '<button type="button" class="pl-sm-ghost" id="pl-sm-close-foot">Close</button>' +
      '<button type="button" class="pl-sm-save" id="pl-sm-save" hidden>Save changes</button>' +
    '</div>';
  }

  function _smApplyTypeChange(newType, oldType) {
    if (newType === oldType) return;
    var has = _sfBlocks.length || _sfExercises.length || (_sfFocus && _sfFocus.trim());
    function finish() {
      if (_detail) _detail.session_type = newType;
      _smMarkDirty();
      _renderDetailSection();
    }
    if (has) {
      _plConfirm(
        'Structure is shaped for ' + oldType + ' — keep it or clear it?',
        function () {
          _sfBlocks = newType === 'run' ? [{ phase: 'main', duration_min: 30 }] : [];
          _sfExercises = [];
          _sfFocus = '';
          _sm.structTab = 'simple';
          finish();
        },
        {
          okLabel: 'Clear structure',
          cancelLabel: 'Keep structure',
          onCancel: finish,
        },
      );
      return;
    }
    if (newType === 'run' && !_sfBlocks.length) {
      _sfBlocks = [{ phase: 'main', duration_min: 30 }];
    }
    finish();
  }

  function _smRunAi() {
    var p = _detail;
    if (!p || _sm.aiBusy) return;
    var H = _H();
    var draft = _smReadDraftFromDom(p);
    var st = draft.structure || {};
    var current = {
      day_offset: 0,
      workout_type: draft.session_type,
      intent: draft.name,
      notes: draft.notes,
      exercises: st.exercises || null,
      blocks: st.blocks || null,
      source: (p.structure && p.structure.source) || null,
      target_tss: st.target_tss || 0,
      duration_minutes: st.duration_minutes ||
        (H.durationMinutesFromBlocks && H.durationMinutesFromBlocks(st.blocks || (p.structure || {}).blocks)) || 0,
    };
    if (!(current.target_tss > 0) && !(current.duration_minutes > 0)) {
      _sm.aiError = 'Set TSS or duration before filling from patterns.';
      _renderDetailSection();
      return;
    }
    var SB = window.SessionBudget;
    if (SB && SB.analyze && Array.isArray(current.exercises)) {
      var contract = SB.analyze({
        budgetTss: current.target_tss,
        budgetMin: current.duration_minutes,
        exercises: current.exercises,
      });
      if (contract.blocked) {
        _sm.aiError = contract.note;
        _renderDetailSection();
        return;
      }
    }
    var body = {
      date: draft.planned_date || p.planned_date,
      workout_type: draft.session_type,
      current_session: _smHasStructure(p) ? current : null,
      target_tss: current.target_tss > 0 ? current.target_tss : null,
      duration_minutes: current.duration_minutes > 0 ? current.duration_minutes : null,
      subtype: (p.structure && p.structure.subtype) || p.subtype || null,
    };

    _sm.aiBusy = true;
    _sm.aiError = '';
    _generatingIds[p.id] = true;
    _renderWeekList();
    _renderDetailSection();

    _api('POST', '/api/plan/suggestions/session', body)
      .then(function (data) {
        var s = data.session || {};
        var structure = null;
        if (Array.isArray(s.exercises) && s.exercises.length) {
          structure = { exercises: s.exercises };
        } else if (Array.isArray(s.blocks) && s.blocks.length) {
          structure = { blocks: s.blocks };
        } else {
          throw new Error('Pattern fill returned no exercises or run structure.');
        }
        // Keep budget pins from the UI / prior session.
        structure.target_tss = current.target_tss > 0 ? current.target_tss
          : (s.target_tss != null ? s.target_tss : (p.structure && p.structure.target_tss));
        structure.duration_minutes = current.duration_minutes > 0 ? current.duration_minutes
          : (s.duration_minutes != null ? s.duration_minutes : null);
        if (structure.duration_minutes == null && structure.blocks && H.durationMinutesFromBlocks) {
          var dmin = H.durationMinutesFromBlocks(structure.blocks);
          if (dmin) structure.duration_minutes = dmin;
        }
        if (s._muscle_footprint) structure._muscle_footprint = s._muscle_footprint;
        else if (s.muscle_footprint) structure._muscle_footprint = s.muscle_footprint;
        if (s.subtype) structure.subtype = s.subtype;
        // Do NOT stamp whole structure source=user — that blocked Refill.
        // Exercise rows carry their own pinned/source from the fill engine.
        structure.source = 'pattern';

        p.name = s.intent ? String(s.intent).substring(0, 80) : (draft.name || p.name);
        p.notes = s.notes != null ? s.notes : draft.notes;
        p.structure = structure;
        _smSeedBuilders(p);
        _sm.aiBusy = false;
        delete _generatingIds[p.id];
        _sm.dirty = true;
        _smMarkDirty();
        _renderWeekList();
        _sm.suppressDomSync = true;
        _renderDetailSection();
        var dirtyEl = document.getElementById('pl-sm-dirty');
        if (dirtyEl) dirtyEl.textContent = 'unsaved changes';
        var discardBtn = document.getElementById('pl-sm-discard');
        var saveBtn = document.getElementById('pl-sm-save');
        var closeBtn = document.getElementById('pl-sm-close-foot');
        if (discardBtn) discardBtn.hidden = false;
        if (saveBtn) saveBtn.hidden = false;
        if (closeBtn) closeBtn.hidden = true;
      })
      .catch(function (e) {
        _sm.aiBusy = false;
        delete _generatingIds[p.id];
        _sm.aiError = (e && e.message) || 'Pattern fill failed';
        _renderWeekList();
        _renderDetailSection();
      });
  }

  function _smSave() {
    var p = _detail;
    if (!p || !_sm.baseline) return;
    var draft = _smReadDraftFromDom(p);
    var H = _H();
    var b = _sm.baseline;
    var patch = {};
    if (draft.name !== b.name) patch.name = draft.name || null;
    if ((draft.notes || '') !== (b.notes || '')) patch.notes = (draft.notes || '').trim() || null;
    if (draft.planned_date !== b.planned_date) patch.planned_date = draft.planned_date;
    if (draft.session_type !== b.session_type) patch.session_type = draft.session_type;
    var structChanged = !(H.snapshotsEqual && H.snapshotsEqual(draft.structure, b.structure));
    if (structChanged) {
      var structure = draft.structure;
      if (structure && H.stampSourceUser) structure = H.stampSourceUser(structure);
      patch.structure = structure;
    }
    if (!Object.keys(patch).length) {
      _sm.dirty = false;
      _smMarkDirty();
      return;
    }
    var saveBtn = document.getElementById('pl-sm-save');
    if (saveBtn) { saveBtn.disabled = true; saveBtn.textContent = 'Saving…'; }
    _api('PATCH', '/api/planned-sessions/' + p.id, patch)
      .then(function (updated) {
        _detail = updated;
        _sm.dirty = false;
        _smSeedBuilders(updated);
        _toast('Session saved');
        _loadWeek(function () {
          if (_detail && _detail.id) {
            (_bundle.days || []).forEach(function (d) {
              (d.planned || []).forEach(function (row) {
                if (row.id === _detail.id) _detail = row;
              });
            });
          }
          _smSeedBuilders(_detail);
          _renderDetailSection();
          _sm.baseline = _smReadDraftFromDom(_detail);
          _sm.dirty = false;
          _smMarkDirty();
        });
      })
      .catch(function (err) {
        if (saveBtn) { saveBtn.disabled = false; saveBtn.textContent = 'Save changes'; }
        _toast((err && err.message) || 'Save failed', true);
      });
  }

  function _smDiscard() {
    if (!_detail || !_sm.baseline) return;
    _detail.name = _sm.baseline.name;
    _detail.notes = _sm.baseline.notes;
    _detail.planned_date = _sm.baseline.planned_date;
    _detail.session_type = _sm.baseline.session_type;
    _detail.structure = _sm.baseline.structure
      ? JSON.parse(JSON.stringify(_sm.baseline.structure)) : null;
    _smSeedBuilders(_detail);
    _sm.dirty = false;
    _sm.aiError = '';
    _sm.suppressDomSync = true;
    _renderDetailSection();
  }

  function _smTryClose() {
    if (_sm.dirty) {
      _plConfirm('Discard unsaved changes?', function () {
        _smDiscard();
        _closeDetail();
      });
      return;
    }
    _closeDetail();
  }

  function _openDetailById(id) {
    var found = null;
    (_bundle.days || []).forEach(function (d) {
      (d.planned || []).forEach(function (p) { if (p.id === id) found = p; });
    });
    if (!found) return;
    _detailDraft = null;
    _detail = found;
    _panel.open = 'detail';
    _sm.strydOpen = false;
    _sm.aiForcedOpen = false;
    _sm.aiBusy = false;
    _sm.aiError = '';
    _sm.dirty = false;
    _sm.mode = 'view';
    _sm.swap = null;
    _smSeedBuilders(found);
    _sm.suppressDomSync = true;
    _renderDetailSection(); _renderAddSection();
    // Baseline must match DOM/builder shape (not raw server structure) or the
    // footer lights "unsaved" on every open.
    _sm.baseline = _smReadDraftFromDom(found);
    _sm.dirty = false;
    _smMarkDirty();
    var el = document.getElementById('plan-detail-section');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function _closeDetail() {
    _panel.open = null;
    _detail = null;
    _detailDraft = null;
    _sm.baseline = null;
    _sm.dirty = false;
    _renderDetailSection();
  }

  function _renderDetailSection() {
    var host = document.getElementById('plan-detail-section');
    if (!host) return;
    if (_detailDraft) {
      _renderDraftDetailSection();
      return;
    }
    if (_panel.open !== 'detail' || !_detail) { host.innerHTML = ''; return; }
    var p = _detail;
    // Preserve live edits across re-renders (tab switch, add/remove block).
    // Skipped after AI apply / discard — those already wrote `_detail` + builders.
    if (!_sm.suppressDomSync && document.getElementById('pl-sm-name')) {
      var live = _smReadDraftFromDom(p);
      p.name = live.name;
      p.notes = live.notes;
      p.planned_date = live.planned_date;
      p.session_type = live.session_type;
      if (live.structure) p.structure = live.structure;
    }
    _sm.suppressDomSync = false;
    host.innerHTML = '<div class="pl-card pl-panelcard pl-sm-modal">' + _smUnifiedHtml(p) + '</div>';

    document.getElementById('pl-detclose').onclick = _smTryClose;
    var footClose = document.getElementById('pl-sm-close-foot');
    if (footClose) footClose.onclick = _smTryClose;
    var discardBtn = document.getElementById('pl-sm-discard');
    if (discardBtn) discardBtn.onclick = function () { _smDiscard(); };
    var saveBtn = document.getElementById('pl-sm-save');
    if (saveBtn) saveBtn.onclick = _smSave;

    var enterEdit = document.getElementById('pl-sm-enter-edit');
    if (enterEdit) enterEdit.onclick = function () {
      _sm.mode = 'edit';
      if (_sm.structTab !== 'simple' && _sm.structTab !== 'detailed' && _sm.structTab !== 'json') {
        _sm.structTab = 'simple';
      }
      _sm.suppressDomSync = true;
      _renderDetailSection();
    };
    var exportJson = document.getElementById('pl-sm-export-json');
    if (exportJson) exportJson.onclick = function () { _smDownloadSessionJson(p); };
    var doneEdit = document.getElementById('pl-sm-done-edit');
    if (doneEdit) doneEdit.onclick = function () {
      if (_detail && document.getElementById('pl-sm-name')) {
        var live = _smReadDraftFromDom(_detail);
        _detail.name = live.name;
        _detail.notes = live.notes;
        _detail.planned_date = live.planned_date;
        _detail.session_type = live.session_type;
        if (live.structure) _detail.structure = live.structure;
      }
      _sm.mode = 'view';
      _sm.swap = null;
      _sm.suppressDomSync = true;
      _renderDetailSection();
    };

    var delBtn = document.getElementById('pl-det-delete');
    if (delBtn) delBtn.onclick = function () {
      _plConfirm(
        'Delete this planned session? This can’t be undone.',
        function () {
          _api('DELETE', '/api/planned-sessions/' + p.id)
            .then(function () { _toast('Planned session deleted'); _closeDetail(); _loadWeek(); })
            .catch(function (err) { _toast(err.message || 'Delete failed', true); });
        },
        { okLabel: 'Delete' },
      );
    };

    var idCopyBtn = document.getElementById('pl-detid-copy');
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

    ['pl-sm-name', 'pl-sm-notes', 'pl-sm-date', 'pl-sm-focus', 'pl-sm-subtype'].forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      el.addEventListener('input', function () {
        if (id === 'pl-sm-focus') _sfFocus = el.value;
        _smMarkDirty();
      });
      el.addEventListener('change', function () {
        if (id === 'pl-sm-focus') _sfFocus = el.value;
        if (id === 'pl-sm-subtype' && _detail) {
          if (!_detail.structure) _detail.structure = {};
          _detail.structure.subtype = el.value || null;
        }
        _smMarkDirty();
      });
    });

    var typeEl = document.getElementById('pl-sm-type');
    if (typeEl) {
      typeEl.addEventListener('change', function () {
        var old = p.session_type;
        _smApplyTypeChange(typeEl.value, old);
      });
    }

    host.querySelectorAll('.pl-sm-tab').forEach(function (btn) {
      btn.addEventListener('click', function () {
        _sm.structTab = btn.getAttribute('data-stab');
        if (_sm.structTab === 'detailed') _sfStrengthMode = 'detailed';
        if (_sm.structTab === 'simple') _sfStrengthMode = 'simple';
        // sync JSON textarea → builders if leaving json
        _renderDetailSection();
      });
    });

    var jsonTa = document.getElementById('pl-sm-json');
    if (jsonTa) {
      jsonTa.addEventListener('change', function () {
        try {
          var parsed = JSON.parse(jsonTa.value);
          if (Array.isArray(parsed.blocks)) _sfBlocks = parsed.blocks;
          if (Array.isArray(parsed.exercises)) _sfExercises = parsed.exercises;
          if (parsed.focus != null) _sfFocus = parsed.focus;
          _smMarkDirty();
        } catch (e) {
          _toast('Invalid JSON', true);
        }
      });
    }

    // Detailed structure host — reuse Add-panel builders inside the modal
    var structHost = document.getElementById('pl-sm-struct-host');
    if (structHost) {
      var typeNow = (p.session_type || 'run').toLowerCase();
      structHost.innerHTML =
        '<select id="pl-sf-type" hidden aria-hidden="true">' +
          '<option value="' + typeNow + '" selected>' + typeNow + '</option></select>' +
        '<div id="pl-sf-structure"></div>';
      if (typeNow === 'run') {
        _sfStrengthMode = 'detailed';
      } else {
        _sfStrengthMode = 'detailed';
      }
      _renderStructureBuilder();
      // Mode toggles inside the add builder are redundant with the modal's
      // Simple/Detailed/JSON tabs — hide them when embedded here.
      var modeToggle = document.getElementById('pl-strmode');
      if (modeToggle) modeToggle.hidden = true;
      structHost.querySelectorAll('input,select,textarea').forEach(function (inp) {
        inp.addEventListener('change', function () { _smMarkDirty(); });
        inp.addEventListener('input', function () { _smMarkDirty(); });
      });
    }

    var aiExpand = document.getElementById('pl-sm-ai-expand');
    if (aiExpand) aiExpand.onclick = function () {
      _sm.aiForcedOpen = true;
      _renderDetailSection();
    };
    var aiGo = document.getElementById('pl-sm-ai-go');
    if (aiGo) aiGo.onclick = function () { _smRunAi(); };

    var advTog = document.getElementById('pl-sm-adv-tog');
    if (advTog) advTog.onclick = function () {
      if (_sm.structTab === 'detailed' || _sm.structTab === 'json') {
        _sm.structTab = 'simple';
      } else {
        _sm.structTab = 'detailed';
        _sfStrengthMode = 'detailed';
      }
      _renderDetailSection();
    };

    // Session budget steppers / pin inputs
    var budgetRoot = document.getElementById('pl-sm-budget');
    function _applyBudgetBump(kind, delta) {
      if (!_detail) return;
      if (!_detail.structure) _detail.structure = {};
      var key = kind === 'dur' ? 'duration_minutes' : 'target_tss';
      var el = document.getElementById(kind === 'dur' ? 'pl-sm-pin-dur' : 'pl-sm-pin-tss');
      var cur = el && el.value !== '' ? Number(el.value) : Number(_detail.structure[key] || 0);
      if (!isFinite(cur)) cur = 0;
      var next = Math.max(0, cur + delta);
      _detail.structure[key] = next;
      _smMarkDirty();
      _renderDetailSection();
    }
    function _applyBudgetChange(id, val) {
      if (!_detail) return;
      if (!_detail.structure) _detail.structure = {};
      var n = val === '' || val === '—' ? null : Number(val);
      if (id === 'pl-sm-pin-dur') _detail.structure.duration_minutes = (n != null && isFinite(n)) ? n : null;
      if (id === 'pl-sm-pin-tss') _detail.structure.target_tss = (n != null && isFinite(n)) ? n : null;
      if (id === 'pl-sm-pin-dist' && n != null && isFinite(n)) _detail.structure.distance_km = n;
      _smMarkDirty();
      _renderDetailSection();
    }
    if (window.SessionBudget && window.SessionBudget.wire && budgetRoot) {
      window.SessionBudget.wire(budgetRoot, {
        onBump: _applyBudgetBump,
        onChange: _applyBudgetChange,
      });
    } else if (budgetRoot) {
      budgetRoot.querySelectorAll('[data-sb-bump]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          _applyBudgetBump(btn.getAttribute('data-sb-bump'), Number(btn.getAttribute('data-d')) || 0);
        });
      });
    }

    // Exercise pin / skip / swap / delete / reorder (Simple interactive list)
    var exList = document.getElementById('pl-sm-exlist');
    if (exList) {
      exList.querySelectorAll('[data-ex-pin]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var i = +btn.getAttribute('data-ex-pin');
          var ex = _sfExercises[i];
          if (!ex) return;
          var next = !_smExIsPinned(ex);
          ex.pinned = next;
          if (next && (!ex.source || ex.source === 'generated' || ex.source === 'pattern')) {
            ex.source = 'manual';
          }
          if (!next) ex.source = 'generated';
          _smMarkDirty();
          _renderDetailSection();
        });
      });
      exList.querySelectorAll('[data-ex-skip]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var i = +btn.getAttribute('data-ex-skip');
          var ex = _sfExercises[i];
          if (!ex) return;
          // View checklist: tap to mark done at the gym (empty → completed → empty).
          if (String(ex.state || '') === 'completed') {
            ex.state = '';
          } else {
            ex.state = 'completed';
          }
          _smMarkDirty();
          _renderDetailSection();
        });
      });
      exList.querySelectorAll('[data-ex-del]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var i = +btn.getAttribute('data-ex-del');
          if (!_sfExercises[i]) return;
          _sfExercises.splice(i, 1);
          _sm.swap = null;
          _smMarkDirty();
          _renderDetailSection();
        });
      });
      exList.querySelectorAll('[data-ex-up]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          if (_smMoveExInBlock(+btn.getAttribute('data-ex-up'), -1)) {
            _smMarkDirty();
            _renderDetailSection();
          }
        });
      });
      exList.querySelectorAll('[data-ex-dn]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          if (_smMoveExInBlock(+btn.getAttribute('data-ex-dn'), 1)) {
            _smMarkDirty();
            _renderDetailSection();
          }
        });
      });
      exList.querySelectorAll('[data-blk-up]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          if (_smMoveBlockGroup(+btn.getAttribute('data-blk-up'), -1)) {
            _smMarkDirty();
            _renderDetailSection();
          }
        });
      });
      exList.querySelectorAll('[data-blk-dn]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          if (_smMoveBlockGroup(+btn.getAttribute('data-blk-dn'), 1)) {
            _smMarkDirty();
            _renderDetailSection();
          }
        });
      });
      exList.querySelectorAll('[data-blk-rename]').forEach(function (sel) {
        sel.addEventListener('change', function () {
          var gi = +sel.getAttribute('data-blk-rename');
          var groups = _smExGroups();
          var g = groups[gi];
          if (!g) return;
          var name = sel.value;
          g.idxs.forEach(function (i) {
            if (_sfExercises[i]) _sfExercises[i].block = name;
          });
          _smMarkDirty();
          _renderDetailSection();
        });
      });
      exList.querySelectorAll('[data-blk-del]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var gi = +btn.getAttribute('data-blk-del');
          var groups = _smExGroups();
          var g = groups[gi];
          if (!g) return;
          var n = g.idxs.length;
          function go() {
            _smDeleteBlockGroup(gi);
            _sm.swap = null;
            _smMarkDirty();
            _renderDetailSection();
          }
          if (n > 1) {
            _plConfirm('Remove block "' + (g.block || 'Block') + '" and its ' + n + ' exercises?', go, { okLabel: 'Remove' });
          } else {
            go();
          }
        });
      });
      exList.querySelectorAll('[data-ex-swap]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var i = +btn.getAttribute('data-ex-swap');
          if (_sm.swap && _sm.swap.mode === 'swap' && _sm.swap.index === i) {
            _sm.swap = null;
          } else {
            _sm.swap = { mode: 'swap', index: i, query: '', searchAll: true, avoid: [] };
          }
          _renderDetailSection();
        });
      });
      exList.querySelectorAll('[data-ex-add]').forEach(function (btn) {
        btn.addEventListener('click', function () {
          var block = btn.getAttribute('data-ex-add') || 'Exercises';
          if (_sm.swap && _sm.swap.mode === 'add' && _sm.swap.block === block) {
            _sm.swap = null;
          } else {
            _sm.swap = { mode: 'add', block: block, query: '', searchAll: true, avoid: [] };
          }
          _renderDetailSection();
        });
      });
      exList.querySelectorAll('[data-blk-add]').forEach(function (btn) {
        btn.addEventListener('click', function () { _smAddBlock(); });
      });
      exList.querySelectorAll('[data-blk-sets]').forEach(function (inp) {
        inp.addEventListener('change', function () {
          var gi = +inp.getAttribute('data-blk-sets');
          _smApplyBlockSets(gi, inp.value);
          _smMarkDirty();
          _renderDetailSection();
        });
      });
      if (_sm.swap) {
        _smMountSwapPicker(exList.querySelector('#pl-sm-pick'));
      }
      exList.querySelectorAll('[data-ex-edit]').forEach(function (cell) {
        cell.addEventListener('click', function () {
          var i = +cell.getAttribute('data-ex-i');
          var field = cell.getAttribute('data-ex-edit');
          var ex = _sfExercises[i];
          if (!ex) return;
          var cur = field === 'tss' ? (ex.spend_tss != null ? ex.spend_tss : '') : (ex.spend_min != null ? ex.spend_min : '');
          var next = window.prompt(field === 'tss' ? 'TSS' : 'Minutes', cur);
          if (next == null || next === '') return;
          var n = Number(next);
          if (!isFinite(n) || n < 0) return;
          if (field === 'tss') ex.spend_tss = n;
          else ex.spend_min = n;
          if (!_smExIsPinned(ex)) {
            ex.pinned = true;
            if (!ex.source || ex.source === 'generated') ex.source = 'manual';
          }
          _smMarkDirty();
          _renderDetailSection();
        });
      });
    }

    var strydToggle = document.getElementById('pl-sm-stryd-toggle');
    if (strydToggle) strydToggle.onclick = function () {
      _sm.strydOpen = !_sm.strydOpen;
      var panel = document.getElementById('pl-sm-stryd-panel');
      if (panel) panel.hidden = !_sm.strydOpen;
      strydToggle.textContent = (_sm.strydOpen ? '▾' : '▸') +
        ' Copy for Stryd Workout Builder — power/pace targets, import-safe';
    };
    var copyBtn = document.getElementById('pl-det-copy');
    if (copyBtn) copyBtn.onclick = function () {
      var pre = document.getElementById('pl-stryd-pre');
      _copyText(pre ? pre.textContent : '', copyBtn);
    };

    _wireDetailEvents(host);
    _smMarkDirty();
  }

  function _detailStatusActionsHtml(p) {
    var done = p.status === 'done_auto' || p.status === 'done_manual';
    var missed = p.status === 'missed' || p.status === 'missed_auto' || p.status === 'missed_manual';
    return '<div class="pl-sm-stat">' +
      '<button type="button" class="pl-sm-sbtn" data-pick="' + p.id + '" data-pick-mode="attach">⚲ Attach workout</button>' +
      '<button type="button" class="pl-sm-sbtn' + (done ? ' on' : '') + '" data-markdone="' + p.id + '">✓ Completed</button>' +
      '<button type="button" class="pl-sm-sbtn' + (missed ? ' on' : '') + '" data-missed="' + p.id + '">Missed</button>' +
    '</div><div class="pl-picker" data-pickerfor="' + p.id + '" hidden></div>';
  }

  function _detailIdRowHtml(p) {
    if (!p.id) return '';
    return '<div class="pl-detid-row"><code class="pl-detid" id="pl-detid-value">' + esc(p.id) + '</code>' +
      '<button type="button" class="pl-detid-copy" id="pl-detid-copy" aria-label="Copy session ID" title="Copy ID">' +
      '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>' +
      '</button></div>';
  }

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
        var label = b.phase === 'warmup' ? 'Warmup' : (b.phase === 'cooldown' ? 'Cooldown' : (b.phase === 'mp' || b.phase === 'marathon_pace' ? 'MP' : 'Work'));
        out.push(pad(label) + ' ' + pad(mmss(dur)) + tgt);
      }
    });
    return out.join('\n') || '(no structure)';
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
    var VER = '20260807planv3g';
    var existing = document.getElementById('plan-tab-styles');
    if (existing) {
      if (existing.getAttribute('data-ver') === VER) return;
      existing.remove();
    }
    var css = document.createElement('style');
    css.id = 'plan-tab-styles';
    css.setAttribute('data-ver', VER);
    css.textContent = PLAN_CSS;
    document.head.appendChild(css);
  }

  var PLAN_CSS = [
    // Custom-property namespace (--pl-*) removed — was a drifted local hex
    // duplicate of the canonical tokens in frontend/css/styles.css; every
    // rule below now references the canonical tokens directly.
    '.plan-panel{display:flex;flex-direction:column;gap:16px;color:var(--ink);}',
    '.plan-panel .pl-card{background:#fff;border-radius:16px;padding:18px 20px;box-shadow:0 8px 24px rgba(20,28,70,0.16);}',
    '.plan-panel .pl-sectitle{font-size:11px;font-weight:800;letter-spacing:0.07em;color:var(--text-sub);text-transform:uppercase;margin:0;}',
    '.plan-panel .pl-chead{display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:4px;flex-wrap:wrap;}',
    '.plan-panel .pl-btn{font-size:12px;font-weight:700;border-radius:8px;padding:8px 13px;cursor:pointer;border:1px solid var(--border);background:var(--tile);color:var(--ink);font-family:inherit;}',
    '.plan-panel .pl-btn:disabled{opacity:0.42;cursor:not-allowed;}',
    '.plan-panel .pl-btn.pl-dark{background:var(--ink);color:#fff;border-color:var(--ink);}',
    '.plan-panel .pl-btn.pl-lime{background:var(--accent);color:var(--ink);border-color:var(--accent);}',
    '.plan-panel .pl-btn.pl-ghost{background:none;border:1px solid var(--border);}',
    '.plan-panel .pl-btn.pl-danger{color:#b91c1c;border-color:#fecaca;}',
    '.plan-panel .pl-btn.pl-danger:hover{background:#fee2e2;}',
    '.plan-panel .pl-btn.pl-tiny{font-size:10px;padding:5px 9px;}',
    '.plan-panel .pl-detactions{display:flex;gap:8px;flex-wrap:wrap;margin:10px 0 4px;}',
    // Mobile: the three status actions share one row as equal thirds — short
    // labels, text allowed to wrap to two lines inside a button.
    '@media(max-width:640px){',
    '.plan-panel .pl-detactions{display:grid;grid-template-columns:repeat(3,1fr);gap:6px;}',
    '.plan-panel .pl-detactions .pl-btn{white-space:normal;line-height:1.25;padding:8px 6px;text-align:center;font-size:11.5px;}',
    '}',
    '.plan-panel .pl-det-ai{margin:10px 0 6px;padding:10px 12px;border:1px dashed #c7d2fe;border-radius:11px;background:#f8f9ff;}',
    '.plan-panel .pl-det-ai-head{display:flex;gap:8px;flex-wrap:wrap;align-items:center;}',
    '.plan-panel .pl-det-ai-panel{margin-top:8px;}',
    '.plan-panel .pl-det-ai-input{width:100%;box-sizing:border-box;font:inherit;font-size:12.5px;padding:8px 10px;border:1px solid var(--border);border-radius:8px;background:#fff;}',
    '.plan-panel .pl-det-ai-status{font-size:11.5px;color:var(--text-sub);margin-top:6px;min-height:1em;}',
    '.plan-panel .pl-det-ai-hint{font-size:11.5px;color:#3f4a7a;margin-top:8px;line-height:1.35;}',
    // Labeled input wrappers in the detailed exercise editor: invisible on
    // desktop (display:contents — the column header row names the fields),
    // visible inline labels on mobile where wrapping breaks column alignment.
    '.plan-panel .pl-exfld{display:contents;}',
    '.plan-panel .pl-exfld-l{display:none;}',
    '.plan-panel .pl-btnrow{display:flex;gap:8px;flex-wrap:wrap;}',
    '.plan-panel .pl-loading{font-size:12.5px;color:var(--text-sub);padding:14px 0;}',
    '.plan-panel .pl-infobanner{background:#f2f5ff;border:1px solid #e0e7ff;border-radius:11px;padding:10px 14px;font-size:12px;color:#3f4a7a;}',
    '.plan-panel .pl-infobanner b{color:var(--info-dark);}',
    '.plan-panel .pl-panelcard{animation:plPanelIn .18s ease;}',
    '@keyframes plPanelIn{from{opacity:0;transform:translateY(-6px);}to{opacity:1;transform:translateY(0);}}',
    '.plan-panel .pl-panelhead{display:flex;align-items:center;justify-content:space-between;margin-bottom:14px;gap:10px;}',
    '.plan-panel .pl-closepanel{width:44px;height:44px;flex-shrink:0;border:1px solid var(--border);background:var(--tile);border-radius:8px;cursor:pointer;color:var(--text-sub);font-size:13px;}',
    '.plan-panel .pl-closepanel:hover{color:var(--danger);border-color:#fecaca;}',
    '.plan-panel .pl-wknav{display:flex;align-items:center;gap:10px;flex-wrap:wrap;margin-bottom:4px;}',
    '.plan-panel .pl-wknav-right{margin-left:auto;display:flex;gap:7px;align-items:center;}',
    '.plan-panel .pl-suggest{display:flex;align-items:center;gap:12px;width:100%;margin:13px 0 4px;background:linear-gradient(100deg,#4f6ef7,#6d5cf0);border:none;border-radius:12px;padding:13px 16px;cursor:pointer;text-align:left;box-shadow:0 4px 14px rgba(79,110,247,.30);font-family:inherit;}',
    '.plan-panel .pl-suggest:hover{filter:brightness(1.04);}',
    '.plan-panel .pl-suggest-ic{width:32px;height:32px;border-radius:9px;background:rgba(255,255,255,.2);display:grid;place-items:center;font-size:15px;flex-shrink:0;}',
    '.plan-panel .pl-suggest-tx{flex:1;color:#fff;min-width:0;}',
    '.plan-panel .pl-suggest-t{display:block;font-size:14px;font-weight:700;color:#fff;}',
    '.plan-panel .pl-suggest-s{display:block;font-family:var(--mono);font-size:10px;opacity:.85;margin-top:2px;color:#fff;}',
    '.plan-panel .pl-suggest-ar{color:rgba(255,255,255,.8);font-size:17px;flex-shrink:0;}',

    '.plan-panel .pl-arw{width:44px;height:44px;border:1px solid var(--border);background:var(--tile);border-radius:8px;cursor:pointer;font-size:14px;color:var(--text-sub);}',
    '.plan-panel .pl-wktitle{font-size:13px;font-weight:800;}',
    '.plan-panel .pl-weektotal{font-size:11px;color:var(--text-sub);font-family:var(--mono);margin-left:6px;}',
    '.plan-panel .pl-weektotal b{color:var(--ink);font-weight:800;}',
    '.plan-panel .pl-weeklist{display:flex;flex-direction:column;margin-top:14px;}',
    '.plan-panel .pl-dayrow{display:flex;gap:14px;padding:10px 0;border-bottom:1px solid var(--border);align-items:flex-start;}',
    '.plan-panel .pl-dayrow:last-child{border-bottom:none;}',
    '.plan-panel .pl-dayrow.today{background:#f7f9ff;margin:0 -18px;padding-left:18px;padding-right:18px;}',
    '.plan-panel .pl-dayrow.past{opacity:0.94;}',
    '.plan-panel .pl-dayrow.dragover{outline:2px dashed var(--info);outline-offset:-2px;background:#eef2ff;}',
    '.plan-panel .pl-dayrow.rest{align-items:flex-start;}',
    '.plan-panel .pl-gut{width:52px;flex-shrink:0;padding-top:2px;}',
    '.plan-panel .pl-gut-dw{font-family:var(--mono);font-size:9px;font-weight:700;letter-spacing:.05em;color:var(--text-sub);line-height:1;display:block;}',
    '.plan-panel .pl-gut-dn{font-family:var(--mono);font-size:17px;font-weight:700;color:var(--text-sub);line-height:1.15;display:block;}',
    '.plan-panel .pl-dayrow.today .pl-gut-dw,.plan-panel .pl-dayrow.today .pl-gut-dn{color:var(--primary);}',
    '.plan-panel .pl-gut-tot{font-family:var(--mono);font-size:9px;color:var(--text-sub);margin-top:4px;display:block;}',
    '.plan-panel .pl-day-content{flex:1;min-width:0;display:flex;align-items:flex-start;gap:10px;}',
    '.plan-panel .pl-day-sessions{flex:1;min-width:0;}',
    /* Rest day — same pill footprint as a session card so the row aligns */
    '.plan-panel .pl-rest-lab{display:flex;align-items:center;min-height:42px;padding:9px 12px;border-radius:10px;background:#f8fafc;border:1px dashed #d1d5db;font-family:var(--mono);font-size:11px;color:#94a3b8;font-style:italic;box-sizing:border-box;}',
    '.plan-panel .pl-dayrow.today .pl-rest-lab{background:#f1f5ff;border-color:#c7d2fe;color:#7b87c9;}',
    '.plan-panel .pl-day-add,.plan-panel .pl-rest-add{border:1px dashed var(--border);background:none;border-radius:6px;padding:3px 10px;font-family:var(--mono);font-size:9.5px;color:var(--text-sub);cursor:pointer;flex-shrink:0;margin-left:auto;white-space:nowrap;align-self:center;}',
    '.plan-panel .pl-day-add:hover,.plan-panel .pl-rest-add:hover{border-color:var(--primary);color:var(--primary);}',
    '.plan-panel .pl-day-content .pl-sess,.plan-panel .pl-day-content .pl-ghost{max-width:none;}',
    '.plan-panel .pl-sess{position:relative;border-radius:10px;padding:9px 12px;font-size:11px;cursor:pointer;background:transparent;box-shadow:none;}',
    '.plan-panel .pl-sess+.pl-sess{margin-top:8px;}',
    '.plan-panel .pl-sess.dragging{opacity:0.4;}',
    '.plan-panel .pl-sess[draggable="true"]{cursor:grab;}',
    /* Planned — tinted by type (not greyscale) */
    '.plan-panel .pl-sess.status-planned.run{background:#e4e8fd;border:1px solid #c7d2fe;}',
    '.plan-panel .pl-sess.status-planned.run .pl-sn{color:#1e2a5a;}',
    '.plan-panel .pl-sess.status-planned.lift{background:#efe9fd;border:1px solid #ddd6fe;}',
    '.plan-panel .pl-sess.status-planned.lift .pl-sn{color:#4c1d95;}',
    '.plan-panel .pl-sess.status-planned.plyo{background:#ffedd5;border:1px solid #fdba74;}',
    '.plan-panel .pl-sess.status-planned.plyo .pl-sn{color:#9a3412;}',
    '.plan-panel .pl-sess.status-planned.stretch{background:#e6f7ef;border:1px solid #a7f3d0;}',
    '.plan-panel .pl-sess.status-planned.stretch .pl-sn{color:#065f46;}',
    '.plan-panel .pl-sess.status-planned .pl-smeta2,.plan-panel .pl-sess.status-planned .pl-smeta-m,.plan-panel .pl-sess.status-planned .pl-stss{color:var(--text-sub);}',
    /* Matched / linked — green (finished) */
    '.plan-panel .pl-sess.status-done_auto,.plan-panel .pl-sess.status-done_manual{background:#dcfce7;border:1px solid #86efac;}',
    '.plan-panel .pl-sess.status-done_auto .pl-sn,.plan-panel .pl-sess.status-done_manual .pl-sn{color:#14532d;}',
    '.plan-panel .pl-sess.status-done_auto .pl-stss,.plan-panel .pl-sess.status-done_manual .pl-stss{color:#14532d;}',
    '.plan-panel .pl-srow{display:flex;align-items:center;gap:10px;}',
    '.plan-panel .pl-sess .pl-sn{font-weight:650;font-size:13.5px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;flex:1;min-width:0;}',
    '.plan-panel .pl-smeta2{font-family:var(--mono);font-size:10px;color:var(--text-sub);margin-left:auto;white-space:nowrap;}',
    '.plan-panel .pl-smeta-m{display:none;font-family:var(--mono);font-size:10px;color:var(--text-sub);margin-top:4px;}',
    '@media(max-width:1039.98px){.plan-panel .pl-smeta2{display:none;}.plan-panel .pl-smeta-m{display:block;}}',
    '.plan-panel .pl-sdelta.delta{color:var(--success);font-weight:700;}',
    '.plan-panel .pl-sdelta.over{color:var(--warning);font-weight:700;}',
    '.plan-panel .pl-stss{font-family:var(--mono);font-size:13px;font-weight:700;min-width:44px;text-align:right;}',
    '.plan-panel .pl-stss.is-est{font-style:italic;color:var(--text-sub);}',
    '.plan-panel .pl-sdot{width:8px;height:8px;border-radius:99px;flex-shrink:0;background:#c3c9d6;}',
    '.plan-panel .pl-sdot.done{background:var(--success);}.plan-panel .pl-sdot.review{background:var(--warning);}.plan-panel .pl-sdot.missed{background:var(--danger);}',
    '.plan-panel .pl-sexp{display:none;margin-top:9px;padding-top:9px;border-top:1px dashed var(--border);}',
    '.plan-panel .pl-sess.open .pl-sexp{display:block;}',
    '.plan-panel .pl-matchline{font-family:var(--mono);font-size:10px;color:var(--success);margin-bottom:8px;}',
    '.plan-panel .pl-matchline.manual{color:var(--primary);}',
    '.plan-panel .pl-sexp-acts{display:flex;gap:6px;flex-wrap:wrap;}',
    '.plan-panel .pl-abtn{border:1px solid var(--border);background:#fff;border-radius:7px;padding:5px 11px;font-family:var(--mono);font-size:10px;font-weight:700;color:var(--text-sub);cursor:pointer;}',
    '.plan-panel .pl-abtn:hover{border-color:var(--primary);color:var(--primary);}',
    '.plan-panel .pl-abtn.warn{color:var(--warning);border-color:#fde68a;}',
    '.plan-panel .pl-abtn-sel{display:inline-flex;align-items:center;gap:4px;}',
    '.plan-panel .pl-abtn-sel select{font:inherit;border:none;background:transparent;color:inherit;cursor:pointer;}',
    '.plan-panel .pl-sess .pl-sm{color:var(--text-sub);font-family:var(--mono);font-size:10px;margin-top:2px;}',
    // .pl-stypetag base + variant colors were fully re-declared further down
    // (re-audit #14) and that later, un-tokenized block always won the
    // cascade — this tokenized version was dead. Removed rather than kept,
    // to avoid a visual change without browser verification; see the note
    // by the surviving definition.
    '.plan-panel .pl-dhandle{font-size:9px;color:var(--text-sub);letter-spacing:-1px;line-height:1;padding:2px 0;}',
    '.plan-panel .pl-sess-acts{position:absolute;top:5px;right:6px;display:flex;align-items:center;gap:4px;z-index:2;}',
    '.plan-panel .pl-sess-del{background:none;border:none;padding:2px 3px;font-size:13px;line-height:1;cursor:pointer;opacity:0.35;border-radius:5px;}',
    '.plan-panel .pl-sess-del:hover{opacity:1;background:var(--danger-soft);}',
    '.pl-del-confirm-actions{display:flex;gap:8px;flex-wrap:wrap;margin-top:4px;}',
    '.pl-del-confirm-actions .pl-btn{flex:1;min-width:110px;text-align:center;font-size:12.5px;font-weight:700;padding:9px 12px;border-radius:9px;cursor:pointer;border:1px solid var(--border);background:#fff;color:var(--ink);}',
    '.pl-del-confirm-actions .pl-btn.pl-danger{background:#fee2e2;border-color:#fecaca;color:#b91c1c;}',
    '.pl-draft-rm-hint{font-size:11.5px;color:var(--text-sub);line-height:1.4;margin:8px 0 0;}',
    '.plan-panel .pl-sesstop{display:flex;align-items:center;justify-content:space-between;gap:4px;margin-bottom:2px;padding-right:44px;}',
    '.plan-panel .pl-sesstop-left{display:flex;align-items:center;gap:6px;}',
    '.plan-panel .pl-tss-badge{font-size:10.5px;font-weight:700;font-family:var(--mono);color:var(--text-sub);}',
    '.plan-panel .pl-tss-badge.is-estimated{color:var(--text-sub);font-style:italic;}',
    '.plan-panel .pl-guard-badge{font-size:10px;color:#b45309;cursor:help;}',
    '.plan-panel .pl-day-guard-badge{font-size:10px;color:#b45309;margin-left:2px;cursor:help;}',
    '.plan-panel .pl-guard-banner{background:#fffbeb;border:1px solid #fcd34d;border-radius:8px;padding:10px 12px;margin-bottom:10px;font-size:12px;}',
    '.plan-panel .pl-guard-title{font-weight:700;color:#92400e;margin-bottom:4px;}',
    '.plan-panel .pl-guard-warn{color:#78350f;margin-bottom:3px;line-height:1.5;}',
    '.plan-panel .pl-guard-sug-title{font-weight:700;color:#1e40af;margin-top:6px;margin-bottom:2px;}',
    '.plan-panel .pl-guard-sug{color:#1e3a8a;margin-bottom:2px;line-height:1.5;}',
    '.plan-panel .pl-guard-inline{margin-top:8px;}',
    '.plan-panel .pl-stat-tag{font-size:10px;font-weight:800;letter-spacing:0.03em;padding:1px 5px;border-radius:4px;text-transform:uppercase;}',
    '.plan-panel .pl-stat-tag.missed{background:var(--danger-soft);color:var(--danger);}',
    '.plan-panel .pl-stat-tag.review{background:var(--warning-soft);color:var(--warning);}',
    '.plan-panel .pl-stat-tag.done{background:var(--success-soft);color:var(--success);}',
    '.plan-panel .pl-sess.status-missed,.plan-panel .pl-sess.status-missed_auto,.plan-panel .pl-sess.status-missed_manual{opacity:0.55;background:#f9fafb;border:1px solid #e5e7eb;}',
    '.plan-panel .pl-sess.status-needs_review{background:#fffaf0;border:1px solid #fde68a;cursor:default;}',
    /* v3 layout / next-up / chart window */
    '.plan-panel.pl-v3,.plan-panel .pl-v3{display:flex;flex-direction:column;gap:14px;}',
    /* Single column at all breakpoints: chart → this week → week list. */
    '.pl-v3-grid{display:flex;flex-direction:column;gap:14px;align-items:stretch;}',
    '.pl-v3-chart,.pl-v3-side,.pl-v3-week{min-width:0;width:100%;}',
    '.pl-v3-side{position:static;}',
    '.pl-hero{background:#fff;border-radius:14px;border:1px solid var(--border);overflow:hidden;box-shadow:0 2px 8px rgba(20,28,70,.07);}',
    '.pl-hero-top{display:flex;align-items:center;gap:9px;padding:9px 18px;background:linear-gradient(90deg,#eef2ff,#f7f9ff);border-bottom:1px solid #e2e8fd;}',
    '.pl-hero-k{font-family:var(--mono);font-size:9.5px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#3b4bb8;}',
    '.pl-hero-d{font-family:var(--mono);font-size:9.5px;color:#7b87c9;margin-left:auto;}',
    '.pl-hero-body{display:flex;align-items:center;gap:20px;padding:15px 18px;flex-wrap:wrap;}',
    '.pl-hero-left{flex:1;min-width:250px;}',
    '.pl-hero-name{font-size:19px;font-weight:700;display:flex;align-items:center;gap:10px;flex-wrap:wrap;}',
    '@media(max-width:1039.98px){.pl-hero-name{font-size:17px;}}',
    '.pl-hero-meta{font-family:var(--mono);font-size:11px;color:var(--text-sub);margin-top:6px;}',
    '.pl-hero-cue{display:inline-flex;align-items:center;gap:7px;margin-top:9px;background:#f7f8fe;border:1px solid #dfe3fb;border-radius:9px;padding:7px 11px;font-size:12.5px;color:#3b4bb8;}',
    '.pl-hero-stats{display:flex;gap:9px;flex-wrap:wrap;}',
    '@media(max-width:1039.98px){.pl-hero-stats{display:grid;grid-template-columns:repeat(3,1fr);width:100%;}}',
    '.pl-hero-stat{background:var(--tile);border-radius:10px;padding:9px 13px;min-width:78px;text-align:center;}',
    '.pl-hero-stat .k{font-family:var(--mono);font-size:8px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--text-sub);margin-bottom:4px;}',
    '.pl-hero-stat .v{font-family:var(--mono);font-size:17px;font-weight:700;}',
    '.pl-hero-acts{display:flex;gap:8px;flex-wrap:wrap;}',
    '@media(max-width:1039.98px){.pl-hero-acts{width:100%;}.pl-hero-acts .pl-hero-btn{flex:1;}}',
    '.pl-hero-btn{border:none;border-radius:10px;padding:11px 18px;font-family:inherit;font-size:13px;font-weight:700;cursor:pointer;background:var(--primary);color:#fff;}',
    '.pl-hero-btn.ghost{background:#fff;color:var(--text-sub);border:1px solid var(--border);font-weight:600;}',
    '.pl-hero-foot{display:flex;align-items:center;gap:9px;padding:9px 18px;background:var(--tile);border-top:1px solid var(--border);}',
    '.pl-hero-then{font-family:var(--mono);font-size:10px;color:var(--text-sub);}',
    '.pl-hero-empty-msg{font-size:14px;color:var(--text-sub);margin-bottom:10px;}',
    '.lp-setline{display:none;width:100%;text-align:left;border:1px solid var(--border);background:var(--tile);border-radius:10px;padding:10px 12px;font-family:var(--mono);font-size:11px;color:var(--text-sub);cursor:pointer;margin-bottom:12px;align-items:center;gap:6px;flex-wrap:wrap;}',
    '.lp-setline b{color:var(--ink);}',
    '.lp-setline-cv{margin-left:auto;}',
    '.lp-setline.is-open .lp-setline-cv{transform:rotate(180deg);}',
    '@media(max-width:1039.98px){.lp-setline{display:flex;}.lp-rules-strip{display:none;}.lp-rules-strip.is-open{display:grid;}}',
    '.lp-bars{display:flex;align-items:flex-end;gap:4px;height:150px;padding-top:16px;}',
    '.lp-bars .lp-bar-col{flex:1;display:flex;flex-direction:column;align-items:center;justify-content:flex-end;height:100%;gap:3px;min-width:0;}',
    '.lp-bars .lp-bar{width:100%;border-radius:3px 3px 0 0;}',
    '.lp-bars .lp-bar.actual{background:var(--primary);}',
    '.lp-bars .lp-bar.deload{background:#c3c9d6;}',
    '.lp-bars .lp-bar.target{background:#dfe5fd;border:1.5px solid var(--primary);border-bottom:none;}',
    '.lp-bars .lp-bar.peak{background:#e8edfe;border:1.5px solid #8fa5f9;border-bottom:none;}',
    '.lp-bars .lp-bar.taperb{background:#fff0dc;border:1.5px solid #f3b96b;border-bottom:none;}',
    '.lp-bars .lp-bar.raceb{background:#fee2e2;border:1.5px solid #f8a3a3;border-bottom:none;}',
    '.lp-bars .lp-bar-value{font-family:var(--mono);font-size:8.5px;font-weight:700;color:var(--text-sub);}',
    '.lp-bars .lp-bar-d{font-family:var(--mono);font-size:8px;color:var(--text-sub);margin-top:4px;white-space:nowrap;}',
    '.lp-bars .lp-bar-col.is-this-week .lp-bar{box-shadow:0 0 0 2px var(--ink);}',
    '.lp-phasebar{display:flex;gap:4px;margin-top:9px;}',
    '.lp-ph{border-radius:5px;padding:4px 0;text-align:center;font-family:var(--mono);font-size:8.5px;font-weight:700;letter-spacing:.04em;}',
    '.lp-ph.build{background:#e4e8fd;color:#3b4bb8;}',
    '.lp-ph.peakp{background:#e8edfe;color:#4055c9;}',
    '.lp-ph.taperp{background:#fff0dc;color:#a16207;}',
    '.lp-ph.racep{background:#fee2e2;color:#b91c1c;}',
    '.lp-ph-prior{background:transparent;}',
    '.lp-phasenow{margin-top:9px;}',
    '.lp-phasenow .lp-ph{width:100%;}',
    '.lp-divider{display:flex;align-items:center;gap:10px;margin:14px 0 10px;font-family:var(--mono);font-size:9.5px;color:var(--text-sub);}',
    '.lp-divider::before,.lp-divider::after{content:\"\";flex:1;height:1px;background:var(--border);}',
    '.lp-ahead{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;}',
    '.lp-amini{border-radius:10px;padding:9px 10px;}',
    '.lp-amini .k{font-family:var(--mono);font-size:8px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;margin-bottom:3px;}',
    '.lp-amini .v{font-family:var(--mono);font-size:14px;font-weight:700;}',
    '.lp-amini .s{font-family:var(--mono);font-size:9px;margin-top:2px;opacity:.85;}',
    '.lp-amini.peak{background:#e8edfe;color:#4055c9;}',
    '.lp-amini.tap{background:#fff0dc;color:#a16207;}',
    '.lp-amini.race{background:#fee2e2;color:#b91c1c;}',
    '.lp-fullink{display:inline-block;margin-top:12px;font-family:var(--mono);font-size:11px;font-weight:700;color:var(--primary);background:none;border:none;cursor:pointer;padding:0;}',
    '.lp-full-sheet{position:fixed;inset:0;background:rgba(15,20,50,.45);z-index:80;display:flex;align-items:flex-end;justify-content:center;padding:12px;}',
    '.lp-full-sheet-card{background:#fff;border-radius:16px 16px 12px 12px;padding:14px 16px 20px;width:min(960px,100%);max-height:85vh;overflow:auto;}',
    '.lp-full-sheet-head{display:flex;align-items:center;justify-content:space-between;font-weight:700;margin-bottom:10px;}',
    '.lp-full-sheet-close{border:1px solid var(--border);background:#fff;border-radius:8px;width:32px;height:32px;cursor:pointer;}',
    '.plan-panel .pl-diffline{font-size:10.5px;color:var(--text-sub);font-family:var(--mono);margin-top:6px;line-height:1.4;}',
    '.plan-panel .pl-diffline--manual{font-style:italic;}',
    '.plan-panel .pl-unlink{margin-top:4px;font-size:10.5px;color:var(--text-sub);background:none;border:none;cursor:pointer;padding:0;}',
    '.plan-panel .pl-unlink:hover{color:var(--danger);}',
    // Quick-tag feeling row: faint icons until one is picked, then only it shows.
    '.plan-panel .pl-feelrow{display:flex;gap:4px;margin-top:5px;align-items:center;}',
    '.plan-panel .pl-feel-btn{background:none;border:none;padding:0 2px;font-size:14px;line-height:1;cursor:pointer;opacity:0.32;filter:grayscale(0.6);transition:opacity .12s,filter .12s,transform .12s;}',
    '.plan-panel .pl-feel-btn:hover{opacity:0.75;filter:grayscale(0);}',
    '.plan-panel .pl-feel-btn.is-on{opacity:1;filter:none;transform:scale(1.12);}',
    '.plan-panel .pl-feel-btn.is-hidden{display:none;}',
    // 24h attach/override picker.
    '.plan-panel .pl-matchbtns{display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-top:4px;}',
    '.plan-panel .pl-pickbtn{font-size:10.5px;color:var(--primary);background:none;border:none;cursor:pointer;padding:0;text-align:left;}',
    '.plan-panel .pl-pickbtn:hover{text-decoration:underline;}',
    '.plan-panel .pl-picker{margin-top:6px;}',
    '.plan-panel .pl-pickerlist{display:flex;flex-direction:column;gap:4px;}',
    '.plan-panel .pl-pickrow{display:flex;align-items:center;gap:6px;font-size:10px;background:#fff;border:1px solid var(--border);border-radius:6px;padding:5px 7px;cursor:pointer;text-align:left;width:100%;}',
    '.plan-panel .pl-pickrow:hover{border-color:var(--primary);}',
    '.plan-panel .pl-pickrow.is-sel{border-color:var(--primary);background:#eef3ff;}',
    '.plan-panel .pl-pickrow-badge{font-size:10px;font-weight:800;text-transform:uppercase;padding:1px 4px;border-radius:4px;color:#fff;}',
    '.plan-panel .pl-pickrow-badge.run{background:var(--primary);}.plan-panel .pl-pickrow-badge.lift{background:var(--workout-lift);}',
    '.plan-panel .pl-pickrow-name{font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}',
    '.plan-panel .pl-pickrow-meta{color:var(--text-sub);font-family:var(--mono);margin-left:auto;white-space:nowrap;}',
    '.plan-panel .pl-pickconfirm{display:flex;align-items:center;gap:8px;margin-top:6px;font-size:10px;color:var(--text-sub);}',
    '.plan-panel .pl-picker-empty{font-size:10px;color:var(--text-sub);font-style:italic;padding:4px 2px;}',
    // "View full workout →" deep link.
    '.plan-panel .pl-viewfull{display:block;margin-top:4px;font-size:10.5px;color:var(--primary);background:none;border:none;cursor:pointer;padding:0;text-align:left;}',
    '.plan-panel .pl-viewfull:hover{text-decoration:underline;}',
    // RPE-missing banner on a matched session's detail panel.
    '.plan-panel .pl-rpe-fixlink{background:none;border:none;padding:0;font-size:12px;font-weight:700;color:inherit;text-decoration:underline;cursor:pointer;font-family:inherit;}',
    '.plan-panel .pl-candlist{margin-top:7px;display:flex;flex-direction:column;gap:4px;}',
    '.plan-panel .pl-candrow{display:flex;align-items:center;gap:6px;font-size:10px;background:#fff;border:1px solid var(--border);border-radius:6px;padding:5px 7px;cursor:pointer;}',
    '.plan-panel .pl-candrow .pl-cn{font-weight:600;}.plan-panel .pl-candrow .pl-cm{color:var(--text-sub);font-family:var(--mono);margin-left:auto;}',
    '.plan-panel .pl-candbtns{display:flex;gap:6px;margin-top:6px;flex-wrap:wrap;}',
    '.plan-panel .pl-ghost{border:1.5px dashed #d7dcec;border-radius:8px;padding:8px 9px;background:#fbfcff;}',
    // Draft cards — plan-draft-review.html .sess.draft layout (horizontal row).
    '.plan-panel .pl-draft{display:flex;align-items:center;gap:11px;flex-wrap:wrap;border:1.5px dashed #4f6ef7;border-radius:11px;padding:10px 13px;background:#f4f6fe;position:relative;flex:1 1 250px;max-width:100%;}',
    '.plan-panel .pl-draft .pl-stypetag{flex-shrink:0;}',
    '.plan-panel .pl-draft-main{flex:1;min-width:140px;}',
    '.plan-panel .pl-draft .pl-sn{font-size:13px;font-weight:650;line-height:1.3;}',
    '.plan-panel .pl-draft .pl-sm{font-family:var(--mono);font-size:10px;color:var(--text-sub);margin-top:2px;}',
    '.plan-panel .pl-draft-right{display:inline-flex;align-items:center;gap:8px;flex-wrap:wrap;margin-left:auto;}',
    '.plan-panel .pl-draft-tss{font-family:var(--mono);font-size:11px;font-weight:700;color:var(--text-sub);}',
    '.plan-panel .pl-draft-rm{font-family:var(--mono);font-size:10px;font-weight:700;color:#dc2626;background:none;border:none;cursor:pointer;padding:0;white-space:nowrap;}',
    '.plan-panel .pl-draft-rm:hover{text-decoration:underline;}',
    // Raw-hex, un-tokenized — this is the block that actually wins the
    // cascade (a dead, tokenized duplicate was removed above, re-audit
    // #14). Left as-is rather than swapped for tokens: doing so changes
    // the on-screen color of every .pl-stypetag site-wide, which needs a
    // real browser check before shipping, not a blind swap.
    '.plan-panel .pl-stypetag{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:0.04em;padding:2px 7px;border-radius:5px;background:#e4e8fd;color:#3b4bb8;text-transform:uppercase;}',
    '.plan-panel .pl-stypetag.lift{background:#efe9fd;color:#6d3fd1;}',
    '.plan-panel .pl-stypetag.plyo{background:#fef3c7;color:#92400e;}',
    '.plan-panel .pl-stypetag.stretch{background:#e6f7ef;color:#0f7a46;}',
    '.plan-panel .pl-stypetag.run{background:#e4e8fd;color:#3b4bb8;}',
    '.plan-panel .pl-draft-tag{font-size:10px;font-weight:800;letter-spacing:0.04em;color:var(--info-dark);background:#eef2ff;padding:1px 5px;border-radius:4px;}',
    '.plan-panel .pl-src-chip{font-family:var(--mono);font-size:10px;font-weight:700;padding:2px 7px;border-radius:99px;text-transform:uppercase;background:#f1f5f9;color:#64748b;display:inline-flex;align-items:center;gap:5px;}',
    '.plan-panel .pl-src-user{background:var(--ink);color:#fff;}',
    '.plan-panel .pl-src-tmpl{background:#fef3c7;color:#92400e;}',
    '.plan-panel .pl-src-ai{background:#dcfce7;color:#15803d;}',
    '.plan-panel .pl-src-gen{background:#e4e8fd;color:#3b4bb8;}',
    // CSS border spinner (mock .spin / .src.gen i) — not an SVG.
    '.plan-panel .pl-gen-spin{width:8px;height:8px;border-radius:99px;border:1.5px solid currentColor;border-right-color:transparent;display:inline-block;animation:pl-gen-spin 0.9s linear infinite;flex-shrink:0;}',
    '.plan-panel .pl-gen-spin-lg{width:12px;height:12px;border-width:2px;}',
    '.pl-gen-spin{width:8px;height:8px;border-radius:99px;border:1.5px solid currentColor;border-right-color:transparent;display:inline-block;animation:pl-gen-spin 0.9s linear infinite;flex-shrink:0;}',
    '.pl-gen-spin-lg{width:12px;height:12px;border-width:2px;}',
    '@keyframes pl-gen-spin{to{transform:rotate(360deg);}}',
    '.plan-panel .pl-draft.is-pending{opacity:0.75;pointer-events:none;}',
    '.plan-panel .pl-sess.is-generating{border:1.5px dashed #4f6ef7;border-left:1.5px dashed #4f6ef7;background:#f4f6fe;box-shadow:none;cursor:default;opacity:0.75;}',
    '.plan-panel .pl-sm-generating{color:var(--text-sub);font-style:normal;}',
    // Mock .genbar
    '.plan-panel .pl-draft-pending{display:flex;align-items:center;gap:10px;background:#eef1fe;border:1px solid #dfe5fd;border-radius:11px;padding:10px 14px;font-size:12.5px;color:#3b4bb8;margin-bottom:10px;line-height:1.4;flex-wrap:wrap;}',
    '.plan-panel .pl-det-ai-genline{display:inline-flex;align-items:center;gap:6px;color:var(--text-sub);}',
    '.plan-panel .pl-draft-add{display:flex;flex-wrap:wrap;gap:4px;align-items:center;}',
    '.plan-panel .pl-draft-move{font-family:var(--mono);font-size:10px;font-weight:700;color:var(--primary);display:inline-flex;align-items:center;gap:4px;cursor:pointer;}',
    '.plan-panel .pl-draft-move select{font-family:var(--mono);font-size:10px;font-weight:700;color:var(--primary);border:none;background:transparent;cursor:pointer;padding:0;}',
    '.plan-panel .pl-draft-move select:hover{text-decoration:underline;}',
    '.plan-panel .pl-draft-move select:focus-visible{outline:2px solid var(--primary);outline-offset:2px;border-radius:3px;}',
    '.plan-panel .pl-dayrow.drop-ok{outline:2px solid #86efac;outline-offset:-2px;}',
    '.plan-panel .pl-dayrow.drop-warn{outline:2px solid #fbbf24;outline-offset:-2px;}',
    '.plan-panel .pl-dayrow.drop-blocked{outline:2px solid #cbd5e1;outline-offset:-2px;opacity:0.7;}',
    '.plan-panel .pl-draft.dragging{opacity:0.4;}',
    '.plan-panel .pl-draft-banner{background:#fffbeb;border:1px solid #fcd34d;border-radius:11px;padding:10px 14px;font-size:12px;color:#92400e;margin-bottom:10px;}',
    '.plan-panel .pl-draft-link{background:none;border:none;padding:0;font:inherit;font-weight:700;color:#1e40af;text-decoration:underline;cursor:pointer;}',
    '.plan-panel .pl-legend-draft{font-style:italic;color:var(--text-sub);}',
    '#log-tab-plan{position:relative;}',
    '#log-tab-plan .pl-draft-badge{position:absolute;top:4px;right:6px;width:8px;height:8px;border-radius:50%;background:var(--info);color:transparent;font-size:0;line-height:0;}',
    '.plan-panel .pl-gtop{margin-bottom:3px;}',
    '.plan-panel .pl-gtag{font-size:10px;font-weight:800;letter-spacing:0.03em;color:var(--text-sub);background:var(--tile);padding:1px 5px;border-radius:4px;}',
    '.plan-panel .pl-ghostsel{width:100%;font-size:10.5px;border:1px solid var(--border);border-radius:6px;padding:4px 6px;margin-top:6px;background:#fff;}',
    '.plan-panel .pl-daybody .pl-addday{border:1.5px dashed #d7dcec;border-radius:8px;flex:0 0 76px;min-height:34px;display:flex;align-items:center;justify-content:center;text-align:center;font-size:10.5px;font-family:inherit;color:var(--text-sub);background:none;padding:0;cursor:pointer;}',
    '.plan-panel .pl-daybody .pl-addday:focus-visible{outline:2px solid var(--info);outline-offset:1px;}',
    '.plan-panel .pl-addday:hover{color:var(--info-dark);border-color:#c7d2fe;}',
    '.plan-panel .pl-addday.is-disabled{cursor:not-allowed;opacity:0.5;border-style:solid;}',
    '.plan-panel .pl-addday.is-disabled:hover{color:var(--text-sub);border-color:#d7dcec;}',
    '.plan-panel .pl-restday{font-size:11px;color:var(--text-sub);font-style:italic;align-self:center;padding:6px 4px;}',
    '.plan-panel .pl-legend{display:flex;gap:14px;margin-top:12px;font-size:11px;color:var(--text-sub);flex-wrap:wrap;}',
    '.plan-panel .pl-legend b{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px;}',
    '.plan-panel .pl-modetoggle{display:flex;background:var(--tile);border:1px solid var(--border);border-radius:9px;padding:3px;gap:2px;width:fit-content;margin-bottom:16px;}',
    '.plan-panel .pl-modetoggle button{font-size:12px;font-weight:600;color:var(--text-sub);background:none;border:none;padding:6px 13px;border-radius:7px;cursor:pointer;font-family:inherit;}',
    '.plan-panel .pl-modetoggle button.on{background:#fff;color:var(--ink);box-shadow:0 1px 2px rgba(0,0,0,0.06);}',
    '.plan-panel .pl-subtoggle{display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap;}',
    '.plan-panel .pl-subtoggle button{font-size:11.5px;font-weight:700;color:var(--text-sub);background:var(--tile);border:1px solid var(--border);padding:6px 12px;border-radius:7px;cursor:pointer;font-family:inherit;}',
    '.plan-panel .pl-subtoggle button.on{background:var(--ink);color:#fff;border-color:var(--ink);}',
    '.plan-panel .pl-jsontools{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;align-items:center;}',
    '.plan-panel .pl-jsonta{width:100%;max-width:100%;min-height:230px;font-family:var(--mono);font-size:12px;line-height:1.65;border:1px solid var(--border);background:#0f1330;color:#cfe0ff;border-radius:10px;padding:14px;resize:vertical;white-space:pre;overflow:auto;}',
    '.plan-panel .pl-previewbox{margin-top:12px;border-radius:10px;padding:12px 14px;font-size:12.5px;}',
    '.plan-panel .pl-previewbox.ok{background:var(--success-soft);color:#14532d;}',
    '.plan-panel .pl-previewbox.err{background:var(--danger-soft);color:#7f1d1d;font-family:var(--mono);white-space:pre-wrap;}',
    '.plan-panel .pl-previewlist{margin-top:9px;display:flex;flex-direction:column;gap:5px;}',
    '.plan-panel .pl-previewrow{display:flex;gap:10px;font-family:var(--mono);font-size:11.5px;background:rgba(255,255,255,0.55);border-radius:6px;padding:6px 10px;}',
    '.plan-panel .pl-delimsel{font-size:12px;font-weight:600;border:1px solid var(--border);border-radius:7px;padding:7px 10px;background:var(--tile);color:var(--ink);}',
    '.plan-panel .pl-uploadlbl{font-size:12px;font-weight:700;border-radius:8px;padding:8px 13px;cursor:pointer;border:1px solid var(--border);background:var(--tile);color:var(--ink);}',
    '.plan-panel .pl-frow{display:flex;gap:12px;margin-bottom:12px;flex-wrap:wrap;}',
    '.plan-panel .pl-fld{flex:1;min-width:150px;}',
    '.plan-panel .pl-fld label{font-size:10px;font-weight:800;letter-spacing:0.05em;color:var(--text-sub);text-transform:uppercase;display:block;margin-bottom:5px;}',
    '.plan-panel .pl-fld input,.plan-panel .pl-fld select,.plan-panel .pl-fld textarea{width:100%;font-family:inherit;font-size:13px;color:var(--ink);border:1px solid var(--border);background:var(--tile);border-radius:8px;padding:9px 11px;}',
    '.plan-panel .pl-fld textarea{resize:vertical;min-height:54px;}',
    '.plan-panel .pl-notebox{font-size:13px;color:var(--text-sub);background:var(--tile);border-radius:9px;padding:10px 13px;}',
    '.plan-panel .pl-blocklist{display:flex;flex-direction:column;gap:8px;margin-top:6px;}',
    '.plan-panel .pl-ai-blockh{font-size:10.5px;font-weight:800;text-transform:uppercase;letter-spacing:0.04em;color:var(--text-sub);margin:4px 0 -2px;}',
    '.plan-panel .pl-block{display:flex;gap:8px;align-items:center;background:var(--tile);border:1px solid var(--border);border-radius:10px;padding:9px 11px;flex-wrap:wrap;}',
    '.plan-panel .pl-block .pl-btag{font-size:10px;font-weight:800;padding:3px 8px;border-radius:6px;flex-shrink:0;width:74px;text-align:center;}',
    '.plan-panel .pl-btag.warm{background:#e0f2fe;color:#0369a1;}.plan-panel .pl-btag.main{background:var(--warning-soft);color:var(--warning);}.plan-panel .pl-btag.cool{background:var(--success-soft);color:var(--success);}',
    '.plan-panel .pl-block input{border:1px solid var(--border);background:#fff;border-radius:6px;padding:6px 8px;font-size:11.5px;font-family:var(--mono);}',
    '.plan-panel .pl-block .pl-bdur{width:70px;}.plan-panel .pl-block .pl-btgt{width:96px;}.plan-panel .pl-block .pl-exname{flex:1;min-width:120px;font-family:inherit;}',
    '.plan-panel .pl-block .pl-rm{margin-left:auto;color:var(--text-sub);cursor:pointer;font-size:13px;background:none;border:none;}',
    '.plan-panel .pl-exhead{display:flex;gap:8px;padding:0 11px;margin-top:8px;font-size:10.5px;font-weight:700;letter-spacing:0.04em;text-transform:uppercase;color:var(--text-sub);}',
    '.plan-panel .pl-exhead span:nth-child(1){flex:1;min-width:120px;}.plan-panel .pl-exhead span:nth-child(2){width:70px;}.plan-panel .pl-exhead span:nth-child(3){width:70px;}.plan-panel .pl-exhead span:nth-child(4){width:96px;}.plan-panel .pl-exhead span:nth-child(5){width:70px;}.plan-panel .pl-exhead span:nth-child(6){width:20px;}',
    // Mobile exercise editor: hide the column header row (each input carries
    // its own label via .pl-exfld-l), name goes full-width. MUST come after
    // the base .pl-exhead rules above — same specificity, cascade order wins.
    '@media(max-width:640px){',
    '.plan-panel .pl-exhead{display:none;}',
    '.plan-panel .pl-block .pl-exname{flex-basis:100%;min-width:0;}',
    '.plan-panel .pl-exfld{display:inline-flex;align-items:center;gap:5px;}',
    '.plan-panel .pl-exfld-l{display:inline;font-size:10px;font-weight:800;text-transform:uppercase;letter-spacing:0.04em;color:var(--text-sub);}',
    '}',
    // Exercise-group containers (detailed strength editor): drag handle
    // reorders the group, name is editable inline, rows drag between groups.
    '.plan-panel .pl-exgroup{border:1px dashed var(--border);border-radius:10px;padding:8px;display:flex;flex-direction:column;gap:8px;}',
    '.plan-panel .pl-exgroup.drop-hover{border-color:var(--info);background:#f4f6ff;}',
    '.plan-panel .pl-exgroup-h{display:flex;align-items:center;gap:8px;}',
    '.plan-panel .pl-gdrag{cursor:grab;color:var(--text-sub);font-size:13px;line-height:1;padding:2px 4px;user-select:none;}',
    '.plan-panel .pl-gdrag:active{cursor:grabbing;}',
    '.plan-panel .pl-gdrag:focus-visible{outline:2px solid var(--primary);outline-offset:1px;border-radius:4px;}',
    // Keyboard-operable up/down alternative to the drag handle above.
    '.plan-panel .pl-gmovebtns{display:flex;flex-direction:column;gap:1px;}',
    '.plan-panel .pl-gmove{cursor:pointer;color:var(--text-sub);background:none;border:1px solid var(--border);border-radius:3px;font-size:8px;line-height:1;padding:1px 3px;min-width:24px;min-height:24px;display:inline-flex;align-items:center;justify-content:center;}',
    '.plan-panel .pl-gmove:hover:not(:disabled){background:var(--tile);color:var(--ink);}',
    '.plan-panel .pl-gmove:disabled{opacity:0.35;cursor:not-allowed;}',
    '.plan-panel .pl-gname{flex:0 0 220px;min-width:0;font-size:10.5px;font-weight:800;text-transform:uppercase;letter-spacing:0.04em;color:var(--text-sub);border:1px solid transparent;border-radius:6px;padding:4px 6px;background:transparent;text-overflow:ellipsis;}',
    '.plan-panel .pl-gname:hover,.plan-panel .pl-gname:focus{border-color:var(--border);background:#fff;}',
    // Below ~640px the drag handle + move buttons + fixed-width name + remove
    // button no longer fit on one row (min combined width comfortably exceeds
    // a 320-375px phone) — let the row wrap and let the name field shrink
    // instead of forcing horizontal overflow/scroll.
    '@media(max-width:640px){',
    '.plan-panel .pl-exgroup-h{flex-wrap:wrap;row-gap:6px;}',
    '.plan-panel .pl-gname{flex:1 1 120px;}',
    '.plan-panel .pl-rm{margin-left:auto;}',
    '}',
    '.plan-panel .pl-addex-in{margin-top:0;font-size:10.5px;padding:4px 0;}',
    '.plan-panel .pl-block.drop-hover{outline:2px dashed var(--info);outline-offset:-2px;}',
    // Run block-builder header — columns mirror _blockRowHtml: 74px phase
    // tag, 70px min, 96px repeats, 96px target, remove button.
    '.plan-panel .pl-blockhead span:nth-child(1){flex:none;width:74px;min-width:0;}.plan-panel .pl-blockhead span:nth-child(2){width:70px;}.plan-panel .pl-blockhead span:nth-child(3){width:96px;}.plan-panel .pl-blockhead span:nth-child(4){width:96px;}.plan-panel .pl-blockhead span:nth-child(5){width:20px;}',
    '.plan-panel .pl-addblock{font-size:11.5px;font-weight:700;color:var(--info-dark);background:none;border:1px dashed #c7d2fe;border-radius:8px;padding:7px;cursor:pointer;text-align:center;margin-top:8px;width:100%;}',
    '.plan-panel .pl-bulktbl{width:100%;border-collapse:separate;border-spacing:0 8px;}',
    '.plan-panel .pl-bulktbl th{font-size:10px;font-weight:800;color:var(--text-sub);text-transform:uppercase;letter-spacing:0.04em;text-align:left;padding:0 8px 4px;}',
    '.plan-panel .pl-bulktbl td{background:var(--tile);border-top:1px solid var(--border);border-bottom:1px solid var(--border);padding:8px;}',
    '.plan-panel .pl-bulktbl td:first-child{border-left:1px solid var(--border);border-radius:9px 0 0 9px;}',
    '.plan-panel .pl-bulktbl td:last-child{border-right:1px solid var(--border);border-radius:0 9px 9px 0;}',
    '.plan-panel .pl-bulktbl input,.plan-panel .pl-bulktbl select{width:100%;border:none;background:none;font-size:12px;font-family:inherit;color:var(--ink);}',
    '.plan-panel .pl-bulktbl .pl-bd{font-size:11px;font-weight:800;color:var(--text-sub);width:40px;}',
    '.plan-panel .pl-dethead{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}',
    '.plan-panel .pl-dettag{font-size:10px;font-weight:800;letter-spacing:0.04em;padding:3px 8px;border-radius:6px;text-transform:uppercase;}',
    '.plan-panel .pl-dettag.run{background:var(--primary-soft);color:var(--primary);}.plan-panel .pl-dettag.lift{background:var(--workout-lift-soft);color:#7c3aed;}',
    '.plan-panel .pl-dettitle{font-size:19px;font-weight:800;margin-top:10px;}',
    '.plan-panel .pl-detid-row{display:flex;align-items:center;gap:6px;margin-top:3px;}',
    '.plan-panel .pl-detid{font-size:10.5px;font-family:var(--mono);color:var(--text-sub);letter-spacing:-0.01em;}',
    '.plan-panel .pl-detid-copy{display:flex;align-items:center;justify-content:center;width:44px;height:44px;margin:-12px 0;padding:0;border:none;background:none;color:var(--text-sub);cursor:pointer;border-radius:4px;}',
    '.plan-panel .pl-detid-copy:hover{background:var(--tile);color:var(--text-sub);}',
    '.plan-panel .pl-detid-copy--done{color:var(--success);}',
    '.plan-panel .pl-dettiles{display:flex;gap:10px;margin-top:14px;flex-wrap:wrap;}',
    '.plan-panel .pl-dettile{flex:1;min-width:120px;background:var(--tile);border:1px solid var(--border);border-radius:11px;padding:11px 13px;}',
    '.plan-panel .pl-dettile .l{font-size:10px;font-weight:800;color:var(--text-sub);text-transform:uppercase;}.plan-panel .pl-dettile .v{font-size:18px;font-weight:700;font-family:var(--mono);margin-top:4px;}',
    '.plan-panel .pl-segwrap{margin-top:18px;}',
    '.plan-panel .pl-seg2{border-radius:11px;overflow:hidden;border:1px solid var(--border);}',
    '.plan-panel .pl-segblk{display:flex;align-items:center;gap:12px;padding:12px 14px;border-top:1px solid var(--border);}',
    '.plan-panel .pl-segblk:first-child{border-top:none;}',
    '.plan-panel .pl-segblk .pl-sbtag{font-size:10px;font-weight:800;padding:4px 9px;border-radius:6px;width:76px;text-align:center;flex-shrink:0;}',
    '.plan-panel .pl-segblk .pl-sbtag.warm{background:#e0f2fe;color:#0369a1;}.plan-panel .pl-segblk .pl-sbtag.main{background:var(--warning-soft);color:var(--warning);}.plan-panel .pl-segblk .pl-sbtag.cool{background:var(--success-soft);color:var(--success);}',
    '.plan-panel .pl-segblk .pl-sbmain{flex:1;font-size:13px;font-weight:600;}',
    '.plan-panel .pl-segblk .pl-sbtgt{font-size:12px;color:var(--text-sub);font-family:var(--mono);}',
    '.plan-panel .pl-repeatlbl{font-size:10.5px;color:var(--info-dark);font-weight:700;background:var(--primary-soft);padding:2px 8px;border-radius:6px;margin-left:6px;}',
    '.plan-panel .pl-exportbox{background:#0f1330;color:#e3e6ff;border-radius:12px;padding:15px 17px;margin-top:18px;}',
    '.plan-panel .pl-exportbox .pl-eh{display:flex;justify-content:space-between;align-items:center;gap:10px;}',
    '.plan-panel .pl-exportbox .pl-et{font-size:12px;font-weight:800;color:#fff;}.plan-panel .pl-exportbox .pl-ewarn{font-size:10.5px;color:#a5abe0;margin-top:5px;line-height:1.5;}',
    '.plan-panel .pl-exportbox pre{background:rgba(255,255,255,0.06);border-radius:9px;padding:12px 13px;margin-top:11px;font-family:var(--mono);font-size:11px;color:#cfe0ff;line-height:1.7;overflow-x:auto;white-space:pre;}',
    '.plan-panel .pl-copybtn{background:var(--accent);color:#1b2340;border:none;border-radius:8px;padding:7px 13px;font-size:11.5px;font-weight:800;cursor:pointer;flex-shrink:0;}',
    '.plan-panel .pl-exd{display:flex;align-items:center;gap:12px;background:var(--tile);border:1px solid var(--border);border-radius:10px;padding:10px 13px;margin-bottom:8px;flex-wrap:wrap;}',
    '.plan-panel .pl-exd .pl-en{flex:1;min-width:120px;font-size:13px;font-weight:600;}.plan-panel .pl-exd .pl-es{font-size:11.5px;color:var(--text-sub);font-family:var(--mono);}',
    '.plan-panel .pl-exd .pl-sr{font-size:14px;font-weight:800;color:#7c3aed;font-family:var(--mono);}',
    // Mobile: two clean lines per exercise — name on its own (slightly
    // larger), then "2 × 12-15  bodyweight  RPE 7" together — instead of the
    // arbitrary 3-line wrap the desktop flex produced at 390px.
    '@media(max-width:640px){',
    '.plan-panel .pl-exd{row-gap:3px;column-gap:10px;}',
    '.plan-panel .pl-exd .pl-en{flex-basis:100%;min-width:0;font-size:15px;}',
    '.plan-panel .pl-exd .pl-sr{font-size:13px;}',
    '}',
    // Exercises grouped by pasted-back `block` label.
    '.plan-panel .pl-exblock{margin-bottom:18px;padding:12px 12px 4px;border-radius:12px;background:rgba(13,30,67,0.03);}',
    '.plan-panel .pl-exblock:last-child{margin-bottom:0;}',
    '.plan-panel .pl-exblock-h{font-size:10.5px;font-weight:800;text-transform:uppercase;letter-spacing:0.05em;color:var(--text-sub);margin-bottom:9px;padding-bottom:7px;border-bottom:1px solid var(--border);}',
    '@media(max-width:640px){.plan-panel .pl-dayrow{/* gutter stays horizontal */}.plan-panel .pl-hero-acts{width:100%;}}',
    // ── Suggestions panel (issue #1315) ─────────────────────────────────────
    '.pl-suggestions-panel{background:var(--tile);border:1px solid var(--border);border-radius:13px;padding:14px 16px;margin:14px 0;position:relative;}',
    '.pl-sug-header{display:flex;align-items:center;gap:8px;margin-bottom:10px;flex-wrap:wrap;}',
    '.pl-sug-title{font-size:13px;font-weight:800;color:var(--ink);flex:1;}',
    '.pl-sug-source{font-size:10px;font-weight:700;padding:2px 7px;border-radius:6px;background:var(--primary-soft);color:var(--primary);text-transform:uppercase;letter-spacing:0.04em;}',
    '.pl-sug-btn-sm{background:none;border:1px solid var(--border);border-radius:7px;padding:3px 8px;font-size:12px;color:var(--text-sub);cursor:pointer;}',
    '.pl-sug-btn-sm:hover{background:var(--tile);color:var(--ink);}',
    // Loading OVERLAY (not a full clear) — covers the panel (prefs form or the
    // previous suggestion list stays visible underneath, dimmed) while a
    // (re)generate call is in flight.
    '.pl-sug-loading{position:absolute;inset:0;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:10px;background:rgba(255,255,255,0.85);border-radius:13px;font-size:12.5px;font-weight:600;color:var(--text-sub);z-index:2;}',
    '.pl-sug-spinner{width:22px;height:22px;border-radius:50%;border:2.5px solid var(--border);border-top-color:var(--primary);animation:pl-sug-spin 0.7s linear infinite;}',
    '@keyframes pl-sug-spin{to{transform:rotate(360deg);}}',
    '.pl-sug-row-wrap{padding:9px 0;border-bottom:1px solid var(--border);}',
    '.pl-sug-row-wrap:last-child{border-bottom:none;}',
    '.pl-sug-row{display:flex;align-items:center;gap:10px;flex-wrap:wrap;}',
    '.pl-sug-exercises{margin:8px 0 2px 46px;padding:8px 0 0;border-top:1px dashed var(--border);}',
    '.pl-sug-ex-block{margin-bottom:8px;}',
    '.pl-sug-ex-block:last-child{margin-bottom:0;}',
    '.pl-sug-ex-block-h{font-size:10.5px;font-weight:800;text-transform:uppercase;letter-spacing:0.04em;color:var(--text-sub);margin-bottom:4px;}',
    '.pl-sug-ex-row{display:flex;align-items:baseline;gap:8px;font-size:12px;padding:2px 0;flex-wrap:wrap;}',
    '.pl-sug-ex-name{font-weight:600;color:var(--ink);min-width:140px;}',
    '.pl-sug-ex-detail{font-family:var(--mono);color:var(--text-sub);}',
    '.pl-sug-ex-load{color:var(--text-sub);font-size:11.5px;}',
    '.pl-sug-rep{font-size:10.5px;font-weight:800;color:var(--primary);background:var(--primary-soft);border-radius:5px;padding:1px 5px;}',
    /* Shared PlanFillPreview pane sits under the suggestion header */
    '.pl-sug-preview-wrap{margin:8px 0 4px 46px;padding-top:8px;border-top:1px dashed var(--border);min-width:0;}',
    '.pl-sug-collapsed{margin:6px 0 2px 46px;font-size:12px;color:var(--text-sub);}',
    '.pl-sug-collapsed>summary{cursor:pointer;font-weight:600;color:var(--text-sub);list-style:none;user-select:none;}',
    '.pl-sug-collapsed>summary::-webkit-details-marker{display:none;}',
    '.pl-sug-collapsed>summary::before{content:"▸ ";font-size:10px;}',
    '.pl-sug-collapsed[open]>summary::before{content:"▾ ";}',
    '.pl-sug-collapsed .pl-sug-preview-wrap{margin-left:0;}',
    '.pl-sug-collapsed .pl-sug-notes-line{margin-left:0;}',
    '.pl-sug-collapsed .pl-sug-fill-log{margin-left:0;}',
    '.pl-sug-row-wrap.is-added{opacity:0.92;}',
    '.pl-sug-day{font-size:10px;font-weight:800;color:var(--text-sub);text-transform:uppercase;width:36px;flex-shrink:0;}',
    '.pl-sug-type-select{font-size:10px;font-weight:800;padding:3px 6px;border-radius:6px;text-transform:uppercase;flex-shrink:0;border:1px solid transparent;cursor:pointer;}',
    '.pl-sug-type-select:hover{border-color:currentColor;}',
    '.pl-sug-type-select:focus-visible{outline:2px solid var(--primary);outline-offset:1px;}',
    '.pl-sug-type-select.run{background:var(--primary-soft);color:var(--primary);}.pl-sug-type-select.strength{background:var(--workout-lift-soft);color:#7c3aed;}.pl-sug-type-select.plyo{background:var(--warning-soft);color:var(--warning);}.pl-sug-type-select.rest{background:#f1f5f9;color:#64748b;}',
    '.pl-sug-meta{font-size:12px;font-family:var(--mono);color:var(--text-sub);flex-shrink:0;}',
    '.pl-sug-intent{flex:1;font-size:12px;color:var(--ink);min-width:100px;}',
    '.pl-sug-notes-line{font-size:11.5px;color:var(--text-sub);font-style:italic;margin:2px 0 4px 46px;line-height:1.4;}',
    '.pl-sug-adjust{display:flex;gap:4px;flex-shrink:0;}',
    '.pl-sug-adj{font-size:10.5px;font-weight:600;background:none;border:1px solid var(--border);border-radius:6px;padding:4px 7px;cursor:pointer;color:var(--text-sub);}',
    '.pl-sug-adj:hover{background:var(--tile);color:var(--ink);}',
    '.pl-sug-add{font-size:11px;font-weight:700;background:var(--accent);color:#1b2340;border:none;border-radius:7px;padding:5px 11px;cursor:pointer;flex-shrink:0;}',
    '.pl-sug-add:disabled{opacity:0.5;cursor:default;}',
    '.pl-sug-add.added{background:#d1fae5;color:#065f46;}',
    '.pl-sug-update{font-size:10.5px;font-weight:600;background:none;border:1px solid var(--border);border-radius:6px;padding:4px 7px;cursor:pointer;color:var(--info-dark);}',
    '.pl-sug-update:hover{background:var(--tile);}',
    '.pl-sug-update:disabled{opacity:0.4;cursor:not-allowed;}',
    '.pl-sug-reshuffle{font-size:10.5px;font-weight:600;background:none;border:1px solid var(--border);border-radius:6px;padding:4px 7px;cursor:pointer;color:var(--text-sub);}',
    '.pl-sug-reshuffle:hover{background:var(--tile);color:var(--ink);}',
    '.pl-sug-reshuffle:disabled{opacity:0.4;cursor:not-allowed;}',
    '.pl-sug-fill-log{margin:6px 0 2px 46px;font-size:11px;color:var(--text-sub);}',
    '.pl-sug-fill-log>summary{cursor:pointer;font-weight:600;color:var(--text-sub);list-style:none;}',
    '.pl-sug-fill-log>summary::-webkit-details-marker{display:none;}',
    '.pl-sug-fill-log>summary::before{content:"▸ ";font-size:10px;}',
    '.pl-sug-fill-log[open]>summary::before{content:"▾ ";}',
    '.pl-sug-fill-log-pre{margin:6px 0 0 46px;padding:8px 10px;background:var(--tile);border:1px solid var(--border);border-radius:8px;font-family:var(--mono);font-size:10.5px;line-height:1.45;white-space:pre-wrap;word-break:break-word;color:var(--ink);max-height:280px;overflow:auto;}',
    '.pl-sug-fill-log .pl-sug-fill-log-pre{margin-left:0;}',
    '.pl-sug-trigger-row{margin:10px 0 4px;display:flex;justify-content:flex-start;}',
    '.pl-sug-trigger-btn{font-size:12px;font-weight:700;color:var(--info-dark);background:none;border:1px dashed #c7d2fe;border-radius:8px;padding:7px 13px;cursor:pointer;}',
    // ── Pre-generation preferences form ─────────────────────────────────────
    '.pl-sug-prefs{display:flex;flex-direction:column;gap:10px;}',
    '.pl-sug-prefs-row{display:flex;flex-direction:column;gap:5px;}',
    '.pl-sug-prefs-row--inline{flex-direction:row;align-items:center;justify-content:space-between;gap:10px;}',
    '.pl-sug-prefs-row--inline .pl-sug-prefs-label{flex:1 1 auto;min-width:0;margin:0;}',
    '.pl-sug-prefs-label{font-size:10.5px;font-weight:700;color:var(--text-sub);text-transform:uppercase;letter-spacing:0.03em;}',
    '.pl-sug-daychks{display:flex;gap:5px;flex-wrap:wrap;}',
    '.pl-sug-daychk{display:flex;align-items:center;gap:4px;font-size:11.5px;font-weight:600;color:var(--ink);background:#fff;border:1px solid var(--border);border-radius:7px;padding:4px 8px;cursor:pointer;}',
    '.pl-sug-daychk input{margin:0;}',
    '.pl-sug-daychk.is-closed{opacity:0.4;cursor:not-allowed;}',
    '.pl-sug-daychk.is-past{opacity:0.45;cursor:not-allowed;background:var(--tile);}',
    '.pl-sug-daychk.has-session{border-color:#c7d2fe;background:#eef2ff;}',
    '.pl-sug-daychk .pl-sug-sess-tag{font-size:9.5px;font-weight:800;letter-spacing:0.03em;text-transform:uppercase;color:var(--primary);background:var(--primary-soft);border-radius:4px;padding:1px 5px;}',
    '.pl-sug-prefs-extra{display:grid;grid-template-columns:1fr 1fr;gap:8px 14px;margin-top:2px;padding-top:10px;border-top:1px dashed var(--border);}',
    '@media (max-width:520px){.pl-sug-prefs-extra{grid-template-columns:1fr;}}',
    '.pl-sug-prefs-row select,.pl-sug-prefs-row input[type=number]{font:inherit;font-size:12px;padding:4px 8px;border-radius:6px;border:1px solid var(--border);background:#fff;width:auto;max-width:100%;min-width:0;align-self:flex-start;box-sizing:border-box;}',
    '.pl-sug-prefs-row--inline select{min-width:7.5rem;flex:0 0 auto;}',
    '.pl-sug-prefs-row--inline input[type=number]{width:4.5rem;flex:0 0 auto;text-align:right;font-family:var(--mono);}',
    '.pl-sug-habits{font-size:11.5px;color:var(--text-sub);margin-top:4px;line-height:1.4;}',
    '.pl-sug-habits a{color:var(--primary);font-weight:600;}',
    '.pl-sug-prefs-err{color:#b91c1c;font-size:12px;margin-top:6px;white-space:pre-wrap;}',
    // Preference proposals ledger — moved out of the coach brief (D6).
    '.pl-prop-block{margin-top:14px;padding-top:12px;border-top:1px solid var(--border);}',
    '.pl-prop-count{display:inline-block;margin-left:6px;padding:0 6px;border-radius:9px;background:var(--primary);color:#fff;font-size:10.5px;font-weight:700;line-height:16px;vertical-align:middle;}',
    '.pl-props{display:flex;flex-direction:column;gap:8px;}',
    '.pl-prop{display:flex;flex-wrap:wrap;gap:8px;align-items:center;justify-content:space-between;padding:10px 11px;border:1px solid var(--border);border-radius:9px;background:var(--surface-2,#fafafa);}',
    '.pl-prop-main{flex:1 1 210px;min-width:0;}',
    '.pl-prop-delta{font-size:12.5px;font-weight:600;color:var(--ink);}',
    '.pl-prop-why{font-size:11.5px;color:var(--text-sub);margin-top:3px;line-height:1.4;}',
    '.pl-prop-life{font-size:11px;color:var(--text-sub);margin-top:3px;opacity:.85;}',
    '.pl-prop-actions{display:flex;gap:6px;flex-wrap:wrap;}',
    '.pl-prop-actions .pl-btn{font-size:12px;padding:5px 10px;}',
    '.pl-sug-select{font-size:12px;padding:4px 8px;border:1px solid var(--border);border-radius:6px;background:#fff;color:var(--ink);width:auto;max-width:100%;flex:0 0 auto;}',
    '.pl-sug-count-wrap{display:flex;align-items:center;gap:8px;flex:0 1 auto;min-width:0;}',
    '.pl-sug-count{width:56px;font-size:12px;padding:4px 8px;border:1px solid var(--border);border-radius:6px;background:#fff;color:var(--ink);font-family:var(--mono);}',
    '.pl-sug-count-hint{font-size:10.5px;color:var(--text-sub);white-space:nowrap;}',
    // ── Two-rail suggestions (issue #1417): rail 1 schedule grid ─────────────
    '#plan-suggestions-sched{margin-bottom:12px;}',
    '.pl-rail-head{display:flex;align-items:center;gap:10px;margin-bottom:8px;flex-wrap:wrap;}',
    '.pl-rail-title{font-size:11px;font-weight:800;color:var(--text-sub);text-transform:uppercase;letter-spacing:0.03em;flex:1;}',
    '.pl-rail-sum{font-size:12px;font-family:var(--mono);color:var(--text-sub);}',
    '.pl-rail-sum b.on{color:#16a34a;}.pl-rail-sum b.under{color:var(--warning);}.pl-rail-sum b.over{color:#b91c1c;}',
    '.pl-fill-all{font-size:11.5px;padding:6px 12px;}',
    '.pl-fill-all:disabled{opacity:0.45;cursor:default;}',
    '.pl-fill-group{display:inline-flex;align-items:stretch;position:relative;}',
    '.pl-fill-group .pl-fill-all{border-radius:7px 0 0 7px;}',
    '.pl-fill-menu-btn{font-size:11.5px;padding:6px 8px;border-radius:0 7px 7px 0;border-left:1px solid rgba(0,0,0,0.12);background:var(--accent);color:#1b2340;border-top:none;border-right:none;border-bottom:none;cursor:pointer;font-weight:800;}',
    '.pl-fill-menu-btn:disabled{opacity:0.45;cursor:default;}',
    '.pl-fill-menu{position:absolute;right:0;top:calc(100% + 4px);min-width:240px;background:#fff;border:1px solid var(--border);border-radius:9px;box-shadow:0 8px 24px rgba(15,23,42,0.12);z-index:80;padding:4px;display:none;}',
    '.pl-fill-menu.is-open{display:block;}',
    '.pl-fill-menu button{display:block;width:100%;text-align:left;background:none;border:none;border-radius:7px;padding:8px 10px;font-size:12px;font-weight:600;color:var(--ink);cursor:pointer;}',
    '.pl-fill-menu button:hover{background:var(--tile);}',
    '.pl-fill-menu button:disabled{opacity:0.45;cursor:default;}',
    '.pl-fill-menu .pl-fill-menu-hint{display:block;font-size:10.5px;font-weight:500;color:var(--text-sub);margin-top:2px;}',
    '.pl-fill-skiprun{font-size:11px;color:var(--text-sub);display:flex;align-items:center;gap:4px;cursor:pointer;user-select:none;}',
    /* Worker-draft queue UX */
    '.pl-suggestions-panel.is-draft-queued{position:relative;}',
    '.pl-suggestions-panel.is-draft-queued .pl-draft-lock-banner{display:flex;}',
    '.pl-draft-lock-banner{display:none;align-items:center;gap:10px;margin:0 0 10px;padding:10px 12px;border-radius:10px;background:#eff6ff;border:1px solid #bfdbfe;color:#1e40af;font-size:12.5px;font-weight:600;}',
    '.pl-draft-lock-banner .pl-draft-lock-msg{flex:1;line-height:1.35;}',
    '.pl-draft-lock-banner .pl-draft-lock-open{font-size:11px;font-weight:700;background:#fff;border:1px solid #93c5fd;border-radius:7px;padding:5px 9px;cursor:pointer;color:#1d4ed8;}',
    '.pl-suggestions-panel.is-draft-queued button:not(.pl-draft-lock-open):not(#plan-suggestions-dismiss),' +
      '.pl-suggestions-panel.is-draft-queued select,' +
      '.pl-suggestions-panel.is-draft-queued input,' +
      '.pl-suggestions-panel.is-draft-queued .pl-fill-menu-btn,' +
      '.pl-suggestions-panel.is-draft-queued .pl-slot-chip{pointer-events:none;opacity:0.5;}',
    '.pl-draft-q-overlay{position:fixed;inset:0;background:rgba(15,23,42,0.45);z-index:1200;display:flex;align-items:center;justify-content:center;padding:20px;animation:pl-draft-q-fade 0.18s ease-out;}',
    '@keyframes pl-draft-q-fade{from{opacity:0}to{opacity:1}}',
    '.pl-draft-q-card{background:#fff;border-radius:16px;padding:22px 24px;max-width:380px;width:100%;box-shadow:0 20px 50px rgba(15,23,42,0.25);animation:pl-draft-q-pop 0.22s ease-out;}',
    '@keyframes pl-draft-q-pop{from{transform:translateY(8px) scale(0.98);opacity:0}to{transform:none;opacity:1}}',
    '.pl-draft-q-card h3{margin:0 0 6px;font-size:17px;font-weight:800;color:var(--ink);}',
    '.pl-draft-q-card p{margin:0 0 14px;font-size:13px;line-height:1.45;color:var(--text-sub);}',
    '.pl-draft-q-spin-wrap{display:flex;align-items:center;gap:10px;margin-bottom:14px;font-size:12.5px;font-weight:600;color:var(--primary);}',
    '.pl-draft-q-actions{display:flex;gap:8px;flex-wrap:wrap;}',
    '.pl-draft-q-actions .pl-btn{flex:1;min-width:120px;text-align:center;text-decoration:none;font-size:12.5px;font-weight:700;padding:9px 12px;border-radius:9px;cursor:pointer;border:1px solid var(--border);background:#fff;color:var(--ink);}',
    '.pl-draft-q-actions .pl-btn.pl-lime{background:var(--accent);border-color:transparent;color:#1b2340;}',
    '.pl-draft-q-jid{font-family:var(--mono);font-size:10.5px;color:var(--text-sub);margin-top:10px;word-break:break-all;}',
    '.pl-dayrow.is-draft-adding{opacity:0.72;}',
    '.pl-draft-add .pl-gen-spin{width:8px;height:8px;border-width:1.5px;margin-right:4px;vertical-align:middle;}',
    '.pl-draft{cursor:pointer;}',
    '.pl-dap-field{display:block;font-size:12px;font-weight:600;color:var(--text-sub);margin:8px 0;}',
    '.pl-dap-field select,.pl-dap-field input{display:block;width:100%;margin-top:4px;font-size:13px;padding:7px 9px;border:1px solid var(--border);border-radius:8px;font-family:inherit;}',
    '.pl-dap-row{display:flex;gap:10px;}',
    '.pl-dap-row .pl-dap-field{flex:1;}',
    '.pl-dd-grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin:10px 0;}',
    '.pl-dd-grid label,.pl-dd-block{font-size:12px;font-weight:600;color:var(--text-sub);}',
    '.pl-dd-grid select,.pl-dd-grid input,.pl-dd-block input,.pl-dd-block textarea{display:block;width:100%;margin-top:4px;font-size:13px;padding:7px 9px;border:1px solid var(--border);border-radius:8px;font-family:inherit;font-weight:500;color:var(--ink);}',
    '.pl-dd-block{display:block;margin:8px 0;}',
    '.pl-dd-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:14px;}',
    '.pl-sf-hint{font-size:11.5px;color:var(--text-sub);margin:10px 0 0;line-height:1.4;}',
    '.pl-sf-draft-tools{display:flex;}',
    '.pl-fill-skiprun input{cursor:pointer;}',
    '.pl-sched-grid{display:grid;grid-template-columns:repeat(7,minmax(76px,1fr));gap:6px;overflow-x:auto;}',
    '.pl-sched-day{background:#fff;border:1px solid var(--border);border-radius:9px;padding:5px;min-height:74px;display:flex;flex-direction:column;gap:4px;}',
    '.pl-sched-day.is-closed{opacity:0.45;background:var(--tile);}',
    '.pl-sched-day.drop-hover{border-color:var(--primary);background:var(--primary-soft);}',
    '.pl-sched-day-h{font-size:10.5px;font-weight:800;text-transform:uppercase;letter-spacing:0.03em;color:var(--text-sub);display:flex;justify-content:space-between;padding:0 2px;}',
    // Two-line chip: type + remove on line 1, TSS·min on its own line so the
    // numbers never truncate in a narrow day column.
    '.pl-slot-chip{display:flex;flex-direction:column;gap:2px;border-radius:7px;padding:5px 6px;font-size:10px;cursor:grab;border:1px solid transparent;}',
    '.pl-slot-chip:active{cursor:grabbing;}',
    '.pl-slot-chip.run{background:var(--primary-soft);color:var(--primary);}.pl-slot-chip.strength{background:var(--workout-lift-soft);color:#7c3aed;}.pl-slot-chip.plyo{background:var(--warning-soft);color:var(--warning);}.pl-slot-chip.stretch{background:#ccfbf1;color:#0f766e;}.pl-slot-chip.rest{background:#f1f5f9;color:#64748b;}',
    '.pl-slot-line1{display:flex;align-items:center;justify-content:space-between;gap:4px;}',
    '.pl-slot-type{font-weight:800;text-transform:uppercase;}',
    '.pl-slot-meta{font-family:var(--mono);font-size:10.5px;opacity:0.85;white-space:nowrap;}',
    '.pl-slot-x{background:none;border:none;font-size:12px;line-height:1;color:inherit;opacity:0.55;cursor:pointer;padding:0 2px;flex-shrink:0;}',
    '.pl-slot-x:hover{opacity:1;}',
    '.pl-slot-addsel{margin-top:auto;background:none;border:1px dashed var(--border);border-radius:6px;color:var(--text-sub);font-size:11px;font-weight:700;line-height:1;padding:3px 2px;cursor:pointer;text-align:center;-webkit-appearance:none;appearance:none;width:100%;}',
    '.pl-slot-addsel:hover{color:var(--ink);border-color:var(--text-sub);}',
    '.pl-slot-addsel:focus-visible{outline:2px solid var(--primary);outline-offset:1px;}',
    // Rail 2 row additions: day select + editable TSS/duration + fill button.
    '.pl-sug-day-select{font-size:10px;font-weight:800;color:var(--text-sub);text-transform:uppercase;border:1px solid var(--border);border-radius:6px;padding:3px 4px;background:#fff;cursor:pointer;flex-shrink:0;}',
    '.pl-sug-meta-edit{display:inline-flex;align-items:center;gap:3px;}',
    '.pl-sug-tss-input,.pl-sug-dur-input{width:52px;font-size:11.5px;font-family:var(--mono);border:1px solid var(--border);border-radius:6px;padding:3px 5px;color:var(--ink);}',
    '.pl-sug-tss-label{font-size:11.5px;font-family:var(--mono);color:var(--text-sub);}',
    '.pl-sug-gen{font-size:10.5px;font-weight:700;background:none;border:1px solid #c7d2fe;border-radius:6px;padding:4px 8px;cursor:pointer;color:var(--info-dark);}',
    '.pl-sug-gen:hover{background:var(--primary-soft);}',
    '.pl-sug-gen:disabled{opacity:0.6;cursor:default;}',
    '.pl-sug-adj:disabled{opacity:0.4;cursor:not-allowed;}',
    '.pl-sug-intent-empty{color:var(--text-sub);font-style:italic;}',
    '.pl-rail-note{font-size:11.5px;color:#b45309;background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:6px 10px;margin-bottom:8px;}',
    '.pl-sug-type-select.stretch{background:#ccfbf1;color:#0f766e;}',
    '.pl-sug-subtype-select{font-size:10px;font-weight:700;color:var(--text-sub);border:1px solid var(--border);border-radius:6px;padding:3px 4px;background:#fff;cursor:pointer;flex-shrink:0;}',
    /* ── Unified session modal (view = edit = AI) ── */
    '.plan-panel .pl-sm-modal{padding:0;overflow:hidden;}',
    '.plan-panel .pl-sm-pad{padding:18px 22px;}',
    '.plan-panel .pl-sm-top{display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;margin-bottom:10px;}',
    '.plan-panel .pl-sm-topr{display:flex;align-items:center;gap:8px;margin-left:auto;flex-wrap:wrap;justify-content:flex-end;}',
    '.plan-panel .pl-sm-lbl{font-size:10px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--text-sub);}',
    '.plan-panel .pl-sm-x{width:30px;height:30px;border-radius:8px;border:none;background:var(--tile);color:var(--text-sub);font-size:15px;cursor:pointer;}',
    // Bump to the file's established 44px touch target under a coarse
    // (touch) pointer — matches .pl-closepanel/.pl-arw/.pl-detid-copy, which
    // are 44px outright; this one stays compact for mouse users and only
    // grows where precision is limited.
    '@media(pointer:coarse){.plan-panel .pl-sm-x{width:44px;height:44px;}}',
    '.plan-panel .pl-sm-meta{display:flex;align-items:center;gap:9px;margin-top:12px;flex-wrap:wrap;}',
    '.plan-panel .pl-sm-tag{font-family:var(--mono);font-size:10px;font-weight:700;letter-spacing:.04em;padding:3px 8px;border-radius:5px;background:#e4e8fd;color:#3b4bb8;}',
    '.plan-panel .pl-sm-tag.lift{background:#efe9fd;color:#6d3fd1;}',
    '.plan-panel .pl-sm-meta select,.plan-panel .pl-sm-datef{border:1px solid var(--border);border-radius:8px;padding:6px 9px;font-family:var(--mono);font-size:11px;color:var(--ink);background:#fff;}',
    '.plan-panel .pl-sm-matched{font-family:var(--mono);font-size:10px;color:var(--success);}',
    '.plan-panel .pl-sm-name{font-size:21px;font-weight:700;border:none;outline:none;width:100%;margin-top:10px;border-bottom:1.5px dashed transparent;font-family:inherit;color:var(--ink);background:transparent;padding:0;}',
    '.plan-panel .pl-sm-name:hover,.plan-panel .pl-sm-name:focus{border-bottom-color:var(--border);}',
    '.plan-panel .pl-sm-stat{display:flex;gap:8px;margin-top:13px;flex-wrap:wrap;}',
    '.plan-panel .pl-sm-sbtn{padding:7px 13px;border-radius:9px;border:1px solid var(--border);background:#fff;font-size:12.5px;font-weight:650;color:var(--text-sub);cursor:pointer;font-family:inherit;}',
    '.plan-panel .pl-sm-sbtn.on{background:var(--accent);border-color:var(--accent);color:var(--ink);}',
    '.plan-panel .pl-sm-ai{margin-top:15px;border:1.5px dashed #c9d2fb;background:#f7f8fe;border-radius:13px;padding:13px 15px;}',
    '.plan-panel .pl-sm-ai-h{display:flex;align-items:center;gap:8px;margin-bottom:9px;flex-wrap:wrap;}',
    '.plan-panel .pl-sm-ai-h b{font-size:13px;font-weight:700;}',
    '.plan-panel .pl-sm-ai-h span{font-family:var(--mono);font-size:10.5px;color:var(--text-sub);}',
    '.plan-panel .pl-sm-ai-dormant .pl-sm-ai-h{margin-bottom:0;}',
    '.plan-panel .pl-sm-ai-expand{margin-left:auto;background:none;border:none;font:inherit;font-size:12px;font-weight:650;color:var(--primary);cursor:pointer;text-decoration:underline;}',
    '.plan-panel .pl-sm-chips{display:flex;gap:7px;flex-wrap:wrap;margin-bottom:9px;}',
    '.plan-panel .pl-sm-chip{font-size:12px;font-weight:600;padding:6px 12px;border-radius:99px;border:1px solid var(--border);background:#fff;cursor:pointer;font-family:inherit;}',
    '.plan-panel .pl-sm-chip:hover{border-color:var(--primary);color:var(--primary);}',
    '.plan-panel .pl-sm-free{display:flex;gap:8px;}',
    '.plan-panel .pl-sm-free input{flex:1;border:1px solid var(--border);border-radius:9px;padding:9px 12px;font-family:inherit;font-size:12.5px;}',
    '.plan-panel .pl-sm-go{padding:9px 16px;border-radius:9px;border:none;background:var(--accent);color:var(--ink);font-size:12.5px;font-weight:700;cursor:pointer;white-space:nowrap;font-family:inherit;}',
    '.plan-panel .pl-sm-go:disabled{opacity:.5;cursor:default;}',
    '.plan-panel .pl-sm-ai-n{font-family:var(--mono);font-size:10.5px;color:var(--text-sub);margin-top:8px;}',
    '.plan-panel .pl-sm-ai-err{font-size:12px;color:var(--danger);margin-top:8px;line-height:1.35;}',
    '.plan-panel .pl-sm-sech{display:flex;align-items:center;gap:10px;margin-top:17px;margin-bottom:9px;}',
    '.plan-panel .pl-sm-tabs{display:flex;gap:4px;margin-left:auto;flex-wrap:wrap;align-items:center;}',
    '.plan-panel .pl-sm-adv{display:flex;gap:5px;align-items:center;margin-left:6px;}',
    '.plan-panel .pl-sm-adv-tog{border:none;background:none;font-family:var(--mono);font-size:9.5px;color:var(--text-sub);cursor:pointer;padding:4px 2px;}',
    '.plan-panel .pl-sm-adv-tog:hover{color:var(--primary);}',
    '.plan-panel .pl-sm-tab{font-size:11.5px;font-weight:650;padding:5px 11px;border-radius:8px;border:1px solid var(--border);background:#fff;color:var(--text-sub);cursor:pointer;font-family:inherit;}',
    '.plan-panel .pl-sm-tab.on{background:var(--ink);border-color:var(--ink);color:#fff;}',
    '.plan-panel .pl-sm-tiles{display:grid;grid-template-columns:1fr 1fr 1fr;gap:10px;margin-bottom:10px;}',
    '.plan-panel .pl-sm-tile{background:var(--tile);border-radius:11px;padding:10px 13px;}',
    '.plan-panel .pl-sm-tl{font-family:var(--mono);font-size:10.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--text-sub);}',
    '.plan-panel .pl-sm-tv{font-family:var(--mono);font-size:17px;font-weight:700;margin-top:4px;}',
    '.plan-panel .pl-sm-tv.empty{color:var(--text-sub);}',
    '.plan-panel .pl-sm-blocks{border:1px solid var(--border);border-radius:12px;overflow:hidden;}',
    '.plan-panel .pl-sm-brow{display:flex;gap:12px;padding:9px 14px;border-bottom:1px solid var(--border);align-items:center;}',
    '.plan-panel .pl-sm-brow:last-child{border-bottom:none;}',
    '.plan-panel .pl-sm-ph{font-family:var(--mono);font-size:10.5px;font-weight:700;color:var(--text-sub);min-width:66px;text-transform:uppercase;}',
    '.plan-panel .pl-sm-bt{flex:1;font-size:12.5px;}',
    '.plan-panel .pl-sm-bm{font-family:var(--mono);font-size:10.5px;color:var(--text-sub);}',
    '.plan-panel .pl-sm-empty-s{border:1.5px dashed var(--border);border-radius:12px;padding:16px;text-align:center;color:var(--text-sub);font-size:12.5px;font-style:italic;}',
    '.plan-panel .pl-sm-preview{margin-top:12px;min-width:0;}',
    '.plan-panel .pl-sm-preview .preview-layout{margin-top:0;}',
    '.plan-panel .pl-sm-mode{border:1px solid var(--border);background:#fff;border-radius:8px;padding:5px 12px;font:inherit;font-size:12px;font-weight:700;cursor:pointer;color:var(--ink,#1b2340);}',
    '.plan-panel .pl-sm-mode.on{background:var(--accent,#cff245);border-color:transparent;}',
    '.plan-panel .pl-sm-mode:hover{border-color:var(--primary);}',
    '.plan-panel .pl-sm-subtag,.plan-panel .pl-sm-typero,.plan-panel .pl-sm-date-ro{font-family:var(--mono);font-size:11.5px;color:var(--text-sub);padding:4px 8px;background:var(--tile);border-radius:7px;}',
    '.plan-panel .pl-sm-subtag{color:#3b4bb8;background:#eef0ff;font-weight:700;}',
    '.plan-panel .pl-sm-name-ro{font-size:22px;font-weight:800;margin:6px 0 8px;line-height:1.2;}',
    '.plan-panel .pl-sm-focus-ro{font-size:12.5px;color:var(--text-sub);margin-bottom:10px;font-style:italic;}',
    '.plan-panel .pl-sm-notes-ro{font-size:13px;line-height:1.45;white-space:pre-wrap;}',
    '.plan-panel #pl-sm-subtype{border:1px solid var(--border);border-radius:8px;padding:5px 8px;font:inherit;font-size:12.5px;background:#fff;}',
    '.plan-panel .pl-sm-bhleft{display:flex;align-items:center;gap:6px;min-width:0;flex:1;}',
    '.plan-panel .pl-sm-bnsel{border:1px solid var(--border);border-radius:6px;padding:3px 6px;font:inherit;font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;color:var(--text-sub);background:#fff;max-width:160px;}',
    '.plan-panel .pl-sm-blkdel,.plan-panel .pl-sm-delx{width:22px;height:22px;border-radius:6px;border:1px solid var(--border);background:#fff;color:var(--text-sub);cursor:pointer;font-size:12px;display:grid;place-items:center;padding:0;flex-shrink:0;}',
    '.plan-panel .pl-sm-blkdel:hover,.plan-panel .pl-sm-delx:hover{border-color:#fca5a5;color:#b91c1c;background:#fef2f2;}',
    '.plan-panel .pl-sm-mv,.plan-panel .pl-sm-bmv{display:flex;flex-direction:column;gap:1px;}',
    '.plan-panel .pl-sm-mbtn{width:18px;height:14px;border:none;background:#eef1f7;border-radius:3px;color:#6b7280;font-size:8px;line-height:1;cursor:pointer;padding:0;}',
    '.plan-panel .pl-sm-mbtn:hover:not(:disabled){background:#e4e8fd;color:#3b4bb8;}',
    '.plan-panel .pl-sm-mbtn:disabled{opacity:.35;cursor:default;}',
    '.plan-panel .pl-sm-pinbtn{border:1px solid var(--border);background:#fff;border-radius:7px;padding:4px 8px;font-family:var(--mono);font-size:9.5px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--text-sub);cursor:pointer;white-space:nowrap;}',
    '.plan-panel .pl-sm-pinbtn.on{background:#ede9fe;border-color:#c4b5fd;color:#6d28d9;}',
    '.plan-panel .pl-sm-pinbtn:hover{border-color:var(--primary);}',
    '.plan-panel .pl-sm-enum.ro{cursor:default;}',
    '.plan-panel .pl-sm-enum.ro:hover{background:none;box-shadow:none;}',
    '.plan-panel .pl-sm-exlist{margin-top:4px;}',
    '.plan-panel .pl-sm-blk{border:1px solid var(--border);border-radius:11px;overflow:hidden;margin-bottom:9px;}',
    '.plan-panel .pl-sm-blkh{background:var(--tile);padding:7px 12px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;gap:8px;}',
    '.plan-panel .pl-sm-bn{font-family:var(--mono);font-size:9.5px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--text-sub);}',
    '.plan-panel .pl-sm-bm{font-family:var(--mono);font-size:9.5px;color:var(--text-sub);}',
    '.plan-panel .pl-sm-sk{color:var(--warning,#d97706);}',
    '.plan-panel .pl-sm-addex{border:1px dashed var(--border);background:none;border-radius:6px;padding:2px 9px;font-family:var(--mono);font-size:9.5px;color:var(--text-sub);cursor:pointer;}',
    '.plan-panel .pl-sm-addex:hover{border-color:var(--primary);color:var(--primary);}',
    '.plan-panel .pl-sm-addblk{display:block;width:100%;margin:8px 0 4px;border:1px dashed var(--border);background:none;border-radius:8px;padding:8px 10px;font-family:var(--mono);font-size:11px;color:var(--text-sub);cursor:pointer;text-align:center;}',
    '.plan-panel .pl-sm-addblk:hover{border-color:var(--primary);color:var(--primary);}',
    '.plan-panel .pl-sm-bsets-lab{display:inline-flex;align-items:center;gap:5px;font-family:var(--mono);font-size:10px;color:var(--text-sub);margin-left:4px;}',
    '.plan-panel .pl-sm-bsets{width:44px;border:1px solid var(--border);border-radius:5px;padding:2px 4px;font-family:var(--mono);font-size:11px;text-align:right;}',
    '.plan-panel .pl-sm-ex{display:flex;align-items:center;gap:10px;padding:9px 12px;border-bottom:1px solid var(--border);}',
    '.plan-panel .pl-sm-ex:last-child{border-bottom:none;}',
    '.plan-panel .pl-sm-ex.pinned{background:#fbfaff;}',
    '.plan-panel .pl-sm-ex.skipped{background:#fafafa;}',
    '.plan-panel .pl-sm-ex.skipped .pl-sm-en,.plan-panel .pl-sm-ex.skipped .pl-sm-erx{text-decoration:line-through;color:var(--text-sub);}',
    '.plan-panel .pl-sm-chk{width:22px;height:22px;border-radius:6px;border:1.5px solid #cfd5e2;background:#fff;cursor:pointer;flex-shrink:0;display:grid;place-items:center;font-size:12px;color:#fff;padding:0;}',
    '.plan-panel .pl-sm-chk.on{background:var(--success,#16a34a);border-color:var(--success,#16a34a);}',
    '.plan-panel .pl-sm-exb{flex:1;min-width:0;}',
    '.plan-panel .pl-sm-en{font-size:15.5px;font-weight:650;display:block;line-height:1.25;}',
    '.plan-panel .pl-sm-erx{font-family:var(--mono);font-size:11.5px;color:var(--text-sub);margin-top:3px;display:block;}',
    '.plan-panel .pl-sm-erx s{color:#9ca3af;}',
    '.plan-panel .pl-sm-prov{font-family:var(--mono);font-size:8px;font-weight:700;padding:2px 6px;border-radius:4px;letter-spacing:.04em;white-space:nowrap;}',
    '.plan-panel .pl-sm-prov.swap{background:#fef3c7;color:#92400e;}',
    '.plan-panel .pl-sm-prov.hwweek{background:#f3e8ff;color:#7e22ce;}',
    '.plan-panel .pl-sm-prov.hwstand{background:#ede9fe;color:#5b21b6;}',
    '.plan-panel .pl-sm-prov.manual{background:#e4e8fd;color:#3b4bb8;}',
    '.plan-panel .pl-sm-enum{font-family:var(--mono);font-size:11.5px;text-align:right;min-width:58px;color:var(--text-sub);cursor:text;border-radius:5px;padding:2px 4px;white-space:nowrap;}',
    '.plan-panel .pl-sm-enum:hover{background:#eef2ff;box-shadow:inset 0 0 0 1px #c7d2fe;}',
    '.plan-panel .pl-sm-exact{display:flex;gap:3px;flex-shrink:0;align-items:center;}',
    '.plan-panel .pl-sm-ib{width:26px;height:26px;border-radius:7px;border:1px solid var(--border);background:#fff;color:var(--text-sub);cursor:pointer;font-size:12px;display:grid;place-items:center;padding:0;}',
    '.plan-panel .pl-sm-ib:hover{border-color:var(--primary);color:var(--primary);}',
    '.plan-panel .pl-sm-ib.on{background:#ede9fe;border-color:#c4b5fd;color:#6d28d9;}',
    '.plan-panel .pl-sm-ex.active{background:#fffdf5;}',
    '.plan-panel .pl-sm-pick{border:1.5px solid var(--primary,#4f6ef7);border-radius:12px;background:#fbfcff;margin:0 12px 10px;padding:12px 13px;}',
    '.plan-panel .pl-sm-pickh{display:flex;align-items:center;gap:9px;margin-bottom:9px;flex-wrap:wrap;}',
    '.plan-panel .pl-sm-pickh .t{font-size:12.5px;font-weight:700;}',
    '.plan-panel .pl-sm-pickh .s{font-family:var(--mono);font-size:10px;color:var(--text-sub);}',
    '.plan-panel .pl-sm-pickh .cx{margin-left:auto;border:none;background:none;color:var(--text-sub);cursor:pointer;font-size:14px;}',
    '.plan-panel .pl-sm-srch{position:relative;margin-bottom:9px;}',
    '.plan-panel .pl-sm-srch input{width:100%;border:1px solid var(--border);border-radius:9px;padding:9px 12px 9px 12px;font:inherit;font-size:13px;background:#fff;box-sizing:border-box;}',
    '.plan-panel .pl-sm-srch input:focus{outline:none;border-color:var(--primary);box-shadow:0 0 0 3px #dbeafe;}',
    '.plan-panel .pl-sm-srch .clr{position:absolute;right:10px;top:8px;border:none;background:none;color:var(--text-sub);cursor:pointer;font-size:13px;}',
    '.plan-panel .pl-sm-scope{display:flex;align-items:center;gap:7px;margin-bottom:9px;flex-wrap:wrap;font-family:var(--mono);font-size:9.5px;color:var(--text-sub);}',
    '.plan-panel .pl-sm-scope b{color:var(--primary);font-weight:700;}',
    '.plan-panel .pl-sm-filters{display:flex;gap:5px;flex-wrap:wrap;margin-bottom:10px;}',
    '.plan-panel .pl-sm-fchip{border:1px solid var(--border);background:#fff;border-radius:99px;padding:4px 10px;font-family:var(--mono);font-size:9.5px;font-weight:700;color:var(--text-sub);cursor:pointer;}',
    '.plan-panel .pl-sm-fchip.on{background:#fee2e2;border-color:#fca5a5;color:#b91c1c;}',
    '.plan-panel .pl-sm-clist{max-height:250px;overflow-y:auto;padding-right:3px;}',
    '.plan-panel .pl-sm-cand{display:flex;align-items:center;gap:10px;padding:8px 10px;background:#fff;border:1px solid var(--border);border-radius:9px;margin-bottom:6px;cursor:pointer;text-align:left;width:100%;font:inherit;color:inherit;}',
    '.plan-panel .pl-sm-cand:hover{border-color:var(--primary);box-shadow:0 2px 8px rgba(79,110,247,.10);}',
    '.plan-panel .pl-sm-cand.dis{opacity:.5;cursor:not-allowed;background:var(--tile);border-style:dashed;}',
    '.plan-panel .pl-sm-cand.dis:hover{border-color:var(--border);box-shadow:none;}',
    '.plan-panel .pl-sm-cand .cb{flex:1;min-width:0;}',
    '.plan-panel .pl-sm-cand .cn{font-size:12.5px;font-weight:600;display:block;}',
    '.plan-panel .pl-sm-cand .cn mark{background:#fef08a;color:inherit;border-radius:2px;padding:0 1px;}',
    '.plan-panel .pl-sm-cand .cr{font-family:var(--mono);font-size:10px;color:var(--text-sub);margin-top:2px;display:block;}',
    '.plan-panel .pl-sm-why{font-family:var(--mono);font-size:8.5px;font-weight:700;padding:2px 7px;border-radius:99px;background:var(--tile);color:var(--text-sub);white-space:nowrap;}',
    '.plan-panel .pl-sm-why.used{background:#e4e8fd;color:#3b4bb8;}',
    '.plan-panel .pl-sm-why.risk{background:#fee2e2;color:#b91c1c;}',
    '.plan-panel .pl-sm-cd{font-family:var(--mono);font-size:10px;font-weight:700;min-width:50px;text-align:right;}',
    '.plan-panel .pl-sm-cd.up{color:var(--warning,#d97706);}',
    '.plan-panel .pl-sm-cd.dn{color:var(--success,#16a34a);}',
    '.plan-panel .pl-sm-cd.eq{color:var(--text-sub);}',
    '.plan-panel .pl-sm-sec{font-family:var(--mono);font-size:8.5px;font-weight:700;letter-spacing:.07em;text-transform:uppercase;color:var(--text-sub);margin:9px 0 6px;}',
    '.plan-panel .pl-sm-picknote{font-family:var(--mono);font-size:9.5px;color:var(--text-sub);margin-top:8px;line-height:1.6;}',
    '.plan-panel .pl-sm-none{padding:15px;text-align:center;font-family:var(--mono);font-size:11px;color:var(--text-sub);background:#fff;border:1px dashed var(--border);border-radius:9px;}',
    '.plan-panel .pl-sm-none a{color:var(--primary);cursor:pointer;}',
    '.plan-panel .pl-sm-spend{display:flex;align-items:center;justify-content:space-between;padding:10px 12px;background:var(--tile);border-radius:11px;font-size:12.5px;font-weight:700;margin-top:3px;}',
    '.plan-panel .pl-sm-sv{font-family:var(--mono);}',
    '.plan-panel .pl-sm-sv s{color:var(--text-sub);font-weight:400;margin-right:7px;}',
    '.plan-panel .pl-sm-notes{margin-top:15px;}',
    '.plan-panel .pl-sm-notes textarea{width:100%;border:1px solid var(--border);border-radius:11px;padding:11px 13px;font-family:inherit;font-size:12.5px;color:var(--ink);background:var(--tile);resize:vertical;min-height:52px;box-sizing:border-box;}',
    '.plan-panel .pl-sm-stryd{margin-top:13px;font-family:var(--mono);font-size:10.5px;color:var(--text-sub);cursor:pointer;}',
    '.plan-panel .pl-sm-stryd b{color:var(--ink);}',
    '.plan-panel .pl-sm-foot{display:flex;gap:9px;align-items:center;padding:13px 22px;border-top:1px solid var(--border);background:var(--tile);}',
    '.plan-panel .pl-sm-del{color:var(--danger);border:1px solid #f6caca;background:#fff;padding:8px 14px;border-radius:9px;font-size:12.5px;font-weight:700;cursor:pointer;font-family:inherit;}',
    '.plan-panel .pl-sm-sp{flex:1;}',
    '.plan-panel .pl-sm-dirty{font-family:var(--mono);font-size:10.5px;color:var(--warning);}',
    '.plan-panel .pl-sm-save{background:var(--accent);border:none;color:var(--ink);padding:9px 17px;border-radius:9px;font-size:13px;font-weight:700;cursor:pointer;font-family:inherit;}',
    '.plan-panel .pl-sm-ghost{background:#fff;border:1px solid var(--border);color:var(--text-sub);padding:8px 14px;border-radius:9px;font-size:12.5px;font-weight:650;cursor:pointer;font-family:inherit;}',
    // Single reduced-motion override covering every animation/transition
    // declared above (placed last so it wins the cascade against each base
    // rule regardless of where that rule appears earlier in this sheet).
    '@media (prefers-reduced-motion: reduce){',
    '.plan-panel .pl-panelcard{animation:none;}',
    '.plan-panel .pl-feel-btn{transition:none;}',
    '.plan-panel .pl-gen-spin{animation:none;}',
    '.pl-sug-spinner{animation:none;border-top-color:var(--border);}',
    '}'
  ].join('');

}());

// ── Plan Suggestions (issue #1315 + PRD feedback v2) ─────────────────────────
(function () {
  var _dismissed = false;
  var _suggestionsData = null;
  // Remembered across Refresh clicks so re-opening the prefs form doesn't
  // lose what the athlete already told it.
  // Rest days + optional exact strength-session count ('' = auto from the
  // athlete's own last-3-weeks history). No free-text — the schedule rail is
  // rule-based (zero LLM); Update re-fills a slot from duration/subtype.
  var _lastPrefs = {
    restDays: [],
    strengthSessions: '',
    strengthEmphasis: 'same',
    plyoMode: 'standalone',
    plyoSessions: 0,
    mpSegmentMin: 0,
  };
  var _habitTargets = null;
  // Pending preference proposals, rendered as a ledger in the prefs panel.
  // Moved here from the coach brief (Priority 2, D6): the brief is a daily
  // read, and a decision about a preference belongs next to the preference it
  // would change, where the current value is on screen to compare against.
  var _prefProposals = [];

  // Worker-draft queue state — MUST live in THIS closure (suggestions is a
  // separate IIFE from the main Plan module; bare refs to its locals throw).
  var _draftQueueBusy = false;
  var _draftQueueJobId = null;
  var _draftQueuePollTimer = null;

  var _DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
  var _DAY_NAMES_FULL = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];

  function _el(id) { return document.getElementById(id); }
  // Delegates to the shared escaper (issue #1603). The local copies
  // disagreed about the apostrophe, so identical content was safe on
  // some pages and attribute-injectable on others.
  function esc(s) {
    return window.AppCommon.escapeHtml(s);
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

  // ── Per-session adjust: lighter / harder ───────────────────────────────────
  // Softens or stiffens the prescription itself — load ladder + sets for
  // strength/plyo; interval repeats (or main duration) for run. TSS/duration
  // summary numbers still move a little so the week budget stays coherent.

  var _LOAD_LADDER = [
    'bodyweight',
    'light band',
    'bodyweight or light DB',
    'light DB',
    'moderate',
    'moderate DB',
    'working weight',
    'heavy',
    'heavy DB',
  ];

  function _loadLadderIndex(load) {
    var s = String(load || '').toLowerCase().trim();
    if (!s) return -1;
    for (var i = 0; i < _LOAD_LADDER.length; i++) {
      if (s === _LOAD_LADDER[i]) return i;
    }
    if (/body\s*weight|\bbw\b/.test(s)) return 0;
    if (/band/.test(s)) return 1;
    if (/light/.test(s) && /db|dumb/.test(s)) return 3;
    if (/light/.test(s)) return 2;
    if (/moderate|med/.test(s)) return 5;
    if (/working|rpe\s*[6-7]/.test(s)) return 6;
    if (/heavy|max|rpe\s*[8-9]/.test(s)) return 7;
    return 4;
  }

  function _stepLoad(load, harder) {
    var i = _loadLadderIndex(load);
    if (i < 0) return harder ? 'light DB' : 'bodyweight';
    var next = harder ? Math.min(_LOAD_LADDER.length - 1, i + 1) : Math.max(0, i - 1);
    return _LOAD_LADDER[next];
  }

  function _isWarmCoolBlock(name) {
    var b = String(name || '').toLowerCase();
    return /warm|cool/.test(b);
  }

  function _adjustSession(s, harder) {
    var factor = harder ? 1.15 : 0.85;
    var nextTss = Math.max(0, Math.min(400, Math.round((s.target_tss || 0) * factor)));
    var nextDur = Math.max(0, Math.round((s.duration_minutes || 0) * factor));

    var c = s.preset_constraints || (s.structure && s.structure._preset_constraints) || null;
    if (!c && s._preset_constraints) c = s._preset_constraints;
    if (c) {
      if (c.min_tss != null) nextTss = Math.max(nextTss, Math.round(c.min_tss));
      if (c.max_tss != null) nextTss = Math.min(nextTss, Math.round(c.max_tss));
      if (c.min_duration_min != null) nextDur = Math.max(nextDur, Math.round(c.min_duration_min));
      if (c.max_duration_min != null) nextDur = Math.min(nextDur, Math.round(c.max_duration_min));
      if (s.load_ceiling_tss != null && c.must_respect_load_ceiling !== false) {
        nextTss = Math.min(nextTss, Math.round(s.load_ceiling_tss));
      }
    }

    if (!harder && c && c.min_duration_min != null && (s.duration_minutes || 0) <= c.min_duration_min
        && c.min_tss != null && (s.target_tss || 0) <= c.min_tss) {
      return;
    }

    s.target_tss = nextTss;
    s.duration_minutes = nextDur;

    if (Array.isArray(s.exercises)) {
      s.exercises.forEach(function (ex) {
        if (_isWarmCoolBlock(ex.block)) return;
        if (ex.sets != null) {
          ex.sets = Math.max(1, Math.min(8, ex.sets + (harder ? 1 : -1)));
        }
        if (ex.load != null && String(ex.load).trim()) {
          ex.load = _stepLoad(ex.load, harder);
        } else if (!harder) {
          ex.load = 'bodyweight';
        } else {
          ex.load = 'light DB';
        }
        // Plain integer reps only — leave "30s hold" / "per side" alone.
        if (typeof ex.reps === 'string' && /^\d+$/.test(ex.reps.trim())) {
          var n = parseInt(ex.reps, 10);
          ex.reps = String(Math.max(1, Math.round(n * (harder ? 1.1 : 0.9))));
        }
      });
    }
    if (Array.isArray(s.blocks)) {
      s.blocks.forEach(function (b) {
        var ph = String(b.phase || '').toLowerCase();
        if (ph === 'warmup' || ph === 'cooldown') return;
        if (b.repeat != null && Number(b.repeat) > 1) {
          // Interval / tempo sets: fewer or more repeats
          b.repeat = Math.max(1, Math.min(20, Number(b.repeat) + (harder ? 1 : -1)));
          return;
        }
        if (b.duration_min != null) {
          b.duration_min = Math.max(1, Math.round(b.duration_min * factor));
        }
      });
      if (c && c.min_duration_min != null) {
        var sum = 0;
        s.blocks.forEach(function (b) {
          sum += (b.duration_min || 0) * (b.repeat || 1);
        });
        if (sum > 0 && sum < c.min_duration_min) {
          var scale = c.min_duration_min / sum;
          s.blocks.forEach(function (b) {
            if (b.duration_min != null && String(b.phase || '').toLowerCase() === 'main') {
              b.duration_min = Math.max(1, Math.round(b.duration_min * scale));
            }
          });
        }
      }
    }
  }

  // Session detail pane — shared with admin Plan library live preview.
  function _sugSessionPaneHtml(s, wt) {
    var P = window.PlanFillPreview;
    if (!P || !P.sessionPaneHtml) return '';
    var hasEx = Array.isArray(s.exercises) && s.exercises.length;
    var hasBlocks = Array.isArray(s.blocks) && s.blocks.length;
    var hasMuscle = !!(s._muscle_footprint || s.muscle_footprint);
    var hasLog = !!(s.fill_log && (s.fill_log.budget_trace || []).length);
    if (!hasEx && !hasBlocks && !hasMuscle && !hasLog) return '';
    P.ensureStyles();
    return '<div class="pl-sug-preview-wrap">' + P.sessionPaneHtml({
      exercises: wt !== 'rest' ? (s.exercises || []) : [],
      blocks: wt === 'run' ? (s.blocks || []) : [],
      workout_type: wt,
      muscle_footprint: s._muscle_footprint || s.muscle_footprint || null,
      fill_log: s.fill_log || null,
      pool_counts: s.pool_counts || null,
    }) + '</div>';
  }

  function _formatFillStep(step) {
    var op = step.op || '?';
    if (op === 'normalize_subtype') {
      return op + ': ' + (step.from || '∅') + ' → ' + (step.to || '∅') +
        ' · ' + (step.duration_minutes || 0) + ' min · TSS ' +
        (step.target_tss != null ? step.target_tss : '—');
    }
    if (op === 'select_pattern') {
      if (step.picked === null) {
        return op + ': none (' + (step.reason || '') + ')';
      }
      var band = step.duration_band || [];
      return op + ': "' + (step.name || '') + '" subtype=' + (step.subtype || '') +
        ' [' + (band[0] != null ? band[0] : '?') + '–' +
        (band[1] != null ? band[1] : '?') + ' min]';
    }
    if (op === 'fill_strength') {
      return op + (step.attempt ? ' attempt ' + step.attempt : '') +
        ' · ' + (step.exercise_count || 0) + ' exercises' +
        (step.blocks && step.blocks.length ? ' · blocks: ' + step.blocks.join(', ') : '');
    }
    if (op === 'fill_run') {
      var phases = (step.phases || []).map(function (p) {
        var bit = (p.phase || '') + ' ' + (p.duration_min != null ? p.duration_min + 'm' : '');
        if (p.repeat && p.repeat > 1) bit += ' ×' + p.repeat;
        if (p.target) bit += ' (' + p.target + ')';
        return '  ' + bit;
      }).join('\n');
      return op + (phases ? '\n' + phases : '');
    }
    if (op === 'validate') {
      if (step.ok) return op + ': ok';
      return op + ': FAILED' + (step.retry ? ' (will retry)' : '') +
        ((step.errors && step.errors.length) ? '\n  ' + step.errors.join('\n  ') : '');
    }
    if (op === 'fallback' || op === 'template') {
      return op + (step.to ? ' → ' + step.to : '') +
        (step.reason ? ' (' + step.reason + ')' : '') +
        (step.intent ? ' intent="' + step.intent + '"' : '') +
        ((step.errors && step.errors.length) ? '\n  ' + step.errors.join('\n  ') : '');
    }
    if (op === 'keep_user') return op + ': ' + (step.reason || '');
    try { return op + ': ' + JSON.stringify(step); }
    catch (e) { return op; }
  }

  function _sugPipelineLogHtml(s) {
    var log = s && s.fill_log;
    if (!log || !log.steps || !log.steps.length) return '';
    var lines = log.steps.map(_formatFillStep).join('\n');
    var meta = [];
    if (s.pattern_name) meta.push(s.pattern_name);
    if (s.source) meta.push(s.source);
    return '<details class="pl-sug-fill-log">' +
      '<summary>Pipeline log' + (meta.length ? ' · ' + esc(meta.join(' · ')) : '') + '</summary>' +
      '<pre class="pl-sug-fill-log-pre">' + esc(lines) + '</pre>' +
      '</details>';
  }

  function _sugDetailSectionHtml(s, wt) {
    var body =
      (s.notes ? '<div class="pl-sug-notes-line">' + esc(s.notes) + '</div>' : '') +
      _sugSessionPaneHtml(s, wt) +
      _sugPipelineLogHtml(s);
    if (!body) return '';
    // Added sessions stay compact — expand to re-check the fill.
    if (s._added) {
      var bits = [];
      if (Array.isArray(s.exercises) && s.exercises.length) bits.push(s.exercises.length + ' exercises');
      else if (Array.isArray(s.blocks) && s.blocks.length) bits.push(s.blocks.length + ' blocks');
      var meta = bits.length ? ' · ' + bits.join(' · ') : '';
      return '<details class="pl-sug-collapsed">' +
        '<summary>Session detail (added)' + meta + '</summary>' +
        body +
        '</details>';
    }
    return body;
  }

  function _sugHasDetail(s) {
    if (!s) return false;
    var wt = (s.workout_type || '').toLowerCase();
    if (wt === 'rest') return false;
    if (Array.isArray(s.exercises) && s.exercises.length) return true;
    if (Array.isArray(s.blocks) && s.blocks.length) return true;
    // Stretch / simple pattern fills may set intent without exercise rows.
    if (s._ai && s.intent) return true;
    return false;
  }

  function _buildSugRow(s, idx) {
    var wrap = document.createElement('div');
    wrap.className = 'pl-sug-row-wrap' + (s._added ? ' is-added' : '');
    wrap.dataset.idx = idx;

    var wt = (s.workout_type || 'rest').toLowerCase();
    var types = ['run', 'strength', 'plyo', 'stretch', 'rest'];
    var allowed = (_suggestionsData && _suggestionsData.facts && _suggestionsData.facts.allowed_offsets) || [0, 1, 2, 3, 4, 5, 6];
    var hasDetail = _sugHasDetail(s);
    var tssLabel = (s.target_tss != null && s.target_tss !== '') ? (s.target_tss + ' TSS') : '— TSS';

    wrap.innerHTML =
      '<div class="pl-sug-row">' +
        '<select class="pl-sug-day-select" data-idx="' + idx + '" title="Move to another day">' +
          _DAY_NAMES.map(function (n, d) {
            var ok = allowed.indexOf(d) !== -1 || d === s.day_offset;
            return '<option value="' + d + '"' + (d === s.day_offset ? ' selected' : '') + (ok ? '' : ' disabled') + '>' + n + '</option>';
          }).join('') +
        '</select>' +
        '<select class="pl-sug-type-select ' + wt + '" data-idx="' + idx + '">' +
          types.map(function (t) { return '<option value="' + t + '"' + (t === wt ? ' selected' : '') + '>' + t + '</option>'; }).join('') +
        '</select>' +
        (_SLOT_SUBTYPES[wt]
          ? '<select class="pl-sug-subtype-select" data-idx="' + idx + '" title="Optional flavor — binding when the slot is filled from patterns">' +
              '<option value="">any</option>' +
              _SLOT_SUBTYPES[wt].map(function (t) { return '<option value="' + t + '"' + (t === s.subtype ? ' selected' : '') + '>' + t + '</option>'; }).join('') +
            '</select>'
          : '') +
        '<span class="pl-sug-meta pl-sug-meta-edit">' +
          '<span class="pl-sug-tss-label" title="Set by the week schedule / pattern fill">' + tssLabel + '</span> · ' +
          '<input type="number" class="pl-sug-dur-input" data-idx="' + idx + '" min="0" max="600" step="5" value="' + (s.duration_minutes || 0) + '" title="Slot duration"/> min' +
        '</span>' +
        '<span class="pl-sug-intent">' + (s.intent ? esc(s.intent) : '<span class="pl-sug-intent-empty">Not filled yet — use Fill from patterns</span>') + '</span>' +
        (wt !== 'rest'
          ? '<span class="pl-sug-adjust">' +
              '<button type="button" class="pl-sug-adj" data-adj="lighter" data-idx="' + idx + '" title="Lighter loads / fewer sets, or fewer interval repeats"' + (hasDetail ? '' : ' disabled') + '>▾ Lighter</button>' +
              '<button type="button" class="pl-sug-adj" data-adj="harder" data-idx="' + idx + '" title="Heavier loads / more sets, or more interval repeats"' + (hasDetail ? '' : ' disabled') + '>▴ Harder</button>' +
              '<button type="button" class="pl-sug-reshuffle" data-idx="' + idx + '" title="Re-roll exercise picks (same duration &amp; subtype)"' + (hasDetail ? '' : ' disabled') + '>⟳ Reshuffle</button>' +
              '<button type="button" class="pl-sug-update" data-idx="' + idx + '" title="Re-fill from patterns using the current duration and subtype">↻ Update</button>' +
            '</span>' +
            (s._added
              ? '<button class="pl-sug-add added" type="button" disabled>✓ Added</button>'
              : '<button class="pl-sug-add" type="button" data-idx="' + idx + '"' +
                  (hasDetail ? '' : ' disabled') +
                  ' title="' + (hasDetail ? 'Add this session to the week draft' : 'Fill the session from patterns first') + '">Add</button>')
          : '') +
      '</div>' +
      _sugDetailSectionHtml(s, wt);

    var typeSel = wrap.querySelector('.pl-sug-type-select');
    typeSel.addEventListener('change', function () {
      var prev = s.workout_type;
      s.workout_type = typeSel.value;
      if (typeSel.value === 'rest') { s.target_tss = 0; s.duration_minutes = 0; }
      if (prev !== typeSel.value) { s.exercises = null; s.blocks = null; s._ai = false; s.subtype = null; s.fill_log = null; s.pattern_name = null; s.source = null; s._muscle_footprint = null; }
      _renderSuggestions(_suggestionsData); // small list — cheap full re-render
    });

    var subSel = wrap.querySelector('.pl-sug-subtype-select');
    if (subSel) {
      subSel.addEventListener('change', function () {
        s.subtype = subSel.value || null;
        // Duration/subtype drive pattern fill — clear stale content until Update.
        s.exercises = null; s.blocks = null; s._ai = false; s.intent = null; s.notes = null;
        s.fill_log = null; s.pattern_name = null; s.source = null; s._muscle_footprint = null;
        _renderSuggestions(_suggestionsData);
      });
    }

    var daySel = wrap.querySelector('.pl-sug-day-select');
    daySel.addEventListener('change', function () {
      s.day_offset = +daySel.value;
      _renderSuggestions(_suggestionsData);
    });

    var durIn = wrap.querySelector('.pl-sug-dur-input');
    durIn.addEventListener('change', function () {
      s.duration_minutes = Math.max(0, Math.min(600, parseInt(durIn.value, 10) || 0));
      s.exercises = null; s.blocks = null; s._ai = false; s.intent = null; s.notes = null;
      s.fill_log = null; s.pattern_name = null; s.source = null; s._muscle_footprint = null;
      _renderSuggestions(_suggestionsData);
    });

    wrap.querySelectorAll('.pl-sug-adj').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (!_sugHasDetail(s)) return;
        _adjustSession(s, btn.getAttribute('data-adj') === 'harder');
        _renderSuggestions(_suggestionsData);
      });
    });

    var addBtn = wrap.querySelector('.pl-sug-add');
    if (addBtn && !addBtn.disabled) {
      addBtn.addEventListener('click', function () {
        if (!_sugHasDetail(s)) return;
        _addSuggestion(s, addBtn);
      });
    }

    var updateBtn = wrap.querySelector('.pl-sug-update');
    if (updateBtn) {
      updateBtn.addEventListener('click', function () {
        updateBtn.disabled = true;
        updateBtn.textContent = '…';
        _generateSlot(s).then(function () {
          _renderSuggestions(_suggestionsData);
        }).catch(function (e) {
          updateBtn.disabled = false;
          updateBtn.textContent = '↻ Update';
          if (window.UIStates && window.UIStates.showToast) {
            window.UIStates.showToast(e.message || 'Update failed', true);
          }
        });
      });
    }

    var reshuffleBtn = wrap.querySelector('.pl-sug-reshuffle');
    if (reshuffleBtn) {
      reshuffleBtn.addEventListener('click', function () {
        if (!_sugHasDetail(s)) return;
        reshuffleBtn.disabled = true;
        reshuffleBtn.textContent = '…';
        // Fresh seed → strength/plyo re-picks; runs stay deterministic.
        _generateSlot(s, null, { reshuffle: true }).then(function () {
          _renderSuggestions(_suggestionsData);
        }).catch(function (e) {
          reshuffleBtn.disabled = false;
          reshuffleBtn.textContent = '⟳ Reshuffle';
          if (window.UIStates && window.UIStates.showToast) {
            window.UIStates.showToast(e.message || 'Reshuffle failed', true);
          }
        });
      });
    }
    return wrap;
  }

  function _addSuggestion(s, btn) {
    if (s._added) return;
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
    if (body.structure) {
      if (s.target_tss != null) body.structure.target_tss = s.target_tss;
      if (s.duration_minutes != null) body.structure.duration_minutes = s.duration_minutes;
      if (s._muscle_footprint) body.structure._muscle_footprint = s._muscle_footprint;
      if (s.subtype) body.structure.subtype = s.subtype;
    }

    function _doAdd() {
      fetch('/api/planned-sessions', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      })
        .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
        .then(function () {
          s._added = true;
          _renderSuggestions(_suggestionsData);
          if (window.TrainingPlan && window.TrainingPlan.reload) window.TrainingPlan.reload();
        })
        .catch(function () {
          btn.disabled = false;
          btn.textContent = 'Retry';
        });
    }

    // Run plan-check before adding; show inline warning and require confirm
    // if the session footprint loads an overused or injured group.
    // _planCheck/_planGuardHtml live in the OTHER closure (the main Plan
    // module) — reach them via the window.TrainingPlan bridge, and treat a
    // missing bridge as "no warnings" so Add can never be bricked by the
    // guard being unavailable.
    if (s._guardConfirmed) {
      _doAdd();
      return;
    }
    var tp = window.TrainingPlan || {};
    if (typeof tp.planCheck !== 'function') {
      _doAdd();
      return;
    }
    tp.planCheck({ session_type: s.workout_type, structure: body.structure || null }, function (result) {
      if (result && result.warnings && result.warnings.length && typeof tp.planGuardHtml === 'function') {
        s._guardConfirmed = true;
        // Show warning inline next to the Add button
        var warnEl = document.createElement('div');
        warnEl.className = 'pl-guard-inline';
        warnEl.setAttribute('aria-live', 'assertive');
        warnEl.setAttribute('role', 'alert');
        warnEl.innerHTML = tp.planGuardHtml(result) +
          '<button class="pl-btn pl-lime pl-tiny pl-guard-proceed">Add anyway</button>';
        btn.parentNode.insertBefore(warnEl, btn.nextSibling);
        btn.disabled = false;
        btn.textContent = 'Cancel';
        btn.onclick = function () { warnEl.remove(); btn.textContent = 'Add'; btn.onclick = function () { _addSuggestion(s, btn); }; s._guardConfirmed = false; btn.disabled = false; };
        warnEl.querySelector('.pl-guard-proceed').onclick = function () { warnEl.remove(); _doAdd(); };
      } else {
        _doAdd();
      }
    });
  }

  // ── Rail 1: the schedule the athlete owns (issue #1417) ─────────────────────
  // Day/type/TSS/duration placement is deterministic and user-controlled;
  // the LLM only ever fills a slot's CONTENT within the budget the slot
  // already carries (see _generateSlot). Chips drag between day columns on
  // desktop; every property is also editable on the rail-2 row below, so
  // touch devices lose nothing.

  var _TYPE_DEFAULTS = {
    run: { tss: 55, min: 45 },
    strength: { tss: 50, min: 45 },
    plyo: { tss: 40, min: 30 },
    stretch: { tss: 15, min: 20 },
  };
  var _SLOT_TYPES = ['run', 'strength', 'plyo', 'stretch'];
  // Optional per-slot flavor, mirrored by SESSION_SUBTYPES on the backend —
  // it becomes a binding prompt rule when the slot is filled.
  var _SLOT_SUBTYPES = {
    run: ['easy', 'long', 'intervals', 'tempo'],
    strength: ['upper', 'lower', 'full', 'light'],
  };

  function _slotSumHtml(data) {
    var sum = 0;
    (data.suggestions || []).forEach(function (s) { sum += s.workout_type !== 'rest' ? (s.target_tss || 0) : 0; });
    var target = data.facts && data.facts.target_tss ? Math.round(data.facts.target_tss) : null;
    if (target == null) return 'Σ ' + Math.round(sum) + ' TSS';
    var cls = sum > target * 1.15 ? 'over' : (sum < target * 0.85 ? 'under' : 'on');
    return 'Σ <b class="' + cls + '">' + Math.round(sum) + '</b> / ' + target + ' TSS target';
  }

  function _renderScheduleRail(data) {
    var host = _el('plan-suggestions-sched');
    if (!host) {
      host = document.createElement('div');
      host.id = 'plan-suggestions-sched';
      var list = _el('plan-suggestions-list');
      list.parentNode.insertBefore(host, list);
    }
    var suggestions = data.suggestions || [];
    var allowed = (data.facts && data.facts.allowed_offsets) || [0, 1, 2, 3, 4, 5, 6];
    var restDays = (data.facts && data.facts.preferred_rest_days) || [];
    var ws = _parseISO(_weekStartISO());

    var cols = '';
    for (var d = 0; d < 7; d++) {
      var open = allowed.indexOf(d) !== -1 || restDays.indexOf(d) !== -1;
      var dayDate = new Date(ws); dayDate.setDate(ws.getDate() + d);
      var chips = '';
      suggestions.forEach(function (s, i) {
        if (s.day_offset !== d) return;
        var wt = (s.workout_type || 'rest').toLowerCase();
        var meta = wt === 'rest' ? '—' : (s.target_tss || 0) + ' TSS · ' + (s.duration_minutes || 0) + 'm';
        var typeLabel = wt + (s.subtype ? ' · ' + s.subtype : '');
        chips += '<div class="pl-slot-chip ' + wt + '" draggable="true" data-idx="' + i + '" title="Drag to another day — details below">' +
          '<span class="pl-slot-line1"><span class="pl-slot-type">' + esc(typeLabel) + '</span>' +
          '<button type="button" class="pl-slot-x" data-idx="' + i + '" title="Remove slot">×</button></span>' +
          '<span class="pl-slot-meta">' + meta + '</span>' +
        '</div>';
      });
      var addSel = '<select class="pl-slot-addsel" data-day="' + d + '" title="Add a slot">' +
        '<option value="">+</option>' +
        _SLOT_TYPES.map(function (t) { return '<option value="' + t + '">' + t + '</option>'; }).join('') +
      '</select>';
      cols += '<div class="pl-sched-day' + (open ? '' : ' is-closed') + '" data-day="' + d + '"' +
        (open ? '' : ' title="Already scheduled, logged, or in the past"') + '>' +
        '<div class="pl-sched-day-h">' + _DAY_NAMES[d] + ' <span>' + dayDate.getDate() + '</span></div>' +
        chips +
        (open ? addSel : '') +
      '</div>';
    }

    var anyUnfilled = _fillableSlots().length > 0;
    var fillDisabled = !anyUnfilled || _fillAllRunning || _draftQueueBusy;
    host.innerHTML =
      '<div class="pl-rail-head">' +
        '<span class="pl-rail-title">Schedule — drag, resize, then fill</span>' +
        '<span class="pl-rail-sum">' + _slotSumHtml(data) + '</span>' +
        '<label class="pl-fill-skiprun" title="Exclude run slots from pattern fill">' +
          '<input type="checkbox" id="pl-skip-run"' + (_skipRunFill ? ' checked' : '') + (_fillAllRunning ? ' disabled' : '') + '/> Skip Run</label>' +
        '<div class="pl-fill-group">' +
          '<button type="button" class="pl-btn pl-lime pl-fill-all"' + (fillDisabled ? ' disabled' : '') + '>' +
            (_fillAllRunning ? '… filling' : 'Fill from patterns') + '</button>' +
          '<button type="button" class="pl-fill-menu-btn" aria-haspopup="true" aria-expanded="false" title="More fill options"' +
            (_fillAllRunning ? ' disabled' : '') + '>▾</button>' +
          '<div class="pl-fill-menu" role="menu">' +
            '<button type="button" data-fill-action="web"' + (fillDisabled ? ' disabled' : '') + '>' +
              'Fill here (patterns)' +
              '<span class="pl-fill-menu-hint">Sync pattern fill per open slot</span>' +
            '</button>' +
            '<button type="button" data-fill-action="worker-draft"' +
              (_draftQueueBusy ? ' disabled' : '') + '>' +
              'Refresh week draft' +
              '<span class="pl-fill-menu-hint">Sync pattern refill of the Plan draft</span>' +
            '</button>' +
          '</div>' +
        '</div>' +
      '</div>' +
      (data._fillNote ? '<div class="pl-rail-note">' + esc(data._fillNote) + '</div>' : '') +
      '<div class="pl-sched-grid">' + cols + '</div>';

    // Drag & drop between day columns.
    host.querySelectorAll('.pl-slot-chip').forEach(function (chip) {
      chip.addEventListener('dragstart', function (e) {
        e.dataTransfer.setData('text/plain', chip.dataset.idx);
        e.dataTransfer.effectAllowed = 'move';
      });
      chip.addEventListener('click', function (e) {
        if (e.target.classList.contains('pl-slot-x')) return;
        var row = document.querySelector('.pl-sug-row-wrap[data-idx="' + chip.dataset.idx + '"]');
        if (row) row.scrollIntoView({ behavior: 'smooth', block: 'center' });
      });
    });
    host.querySelectorAll('.pl-sched-day:not(.is-closed)').forEach(function (col) {
      col.addEventListener('dragover', function (e) { e.preventDefault(); col.classList.add('drop-hover'); });
      col.addEventListener('dragleave', function () { col.classList.remove('drop-hover'); });
      col.addEventListener('drop', function (e) {
        e.preventDefault();
        var idx = parseInt(e.dataTransfer.getData('text/plain'), 10);
        var s = _suggestionsData.suggestions[idx];
        if (s) { s.day_offset = +col.dataset.day; _renderSuggestions(_suggestionsData); }
      });
    });
    host.querySelectorAll('.pl-slot-x').forEach(function (btn) {
      btn.addEventListener('click', function () {
        _suggestionsData.suggestions.splice(+btn.dataset.idx, 1);
        _renderSuggestions(_suggestionsData);
      });
    });
    host.querySelectorAll('.pl-slot-addsel').forEach(function (sel) {
      sel.addEventListener('change', function () {
        var t = sel.value;
        if (!t) return;
        var def = _TYPE_DEFAULTS[t] || _TYPE_DEFAULTS.run;
        _suggestionsData.suggestions.push({
          day_offset: +sel.dataset.day, workout_type: t,
          target_tss: def.tss, duration_minutes: def.min,
          intent: '', notes: null, exercises: null, blocks: null,
        });
        _renderSuggestions(_suggestionsData);
      });
    });
    var fillBtn = host.querySelector('.pl-fill-all');
    if (fillBtn) {
      if (fillDisabled && !_fillAllRunning) {
        // Disabled primary swallows clicks — make it open the ▾ menu so
        // "Queue week draft" stays reachable when slots are already filled.
        fillBtn.removeAttribute('disabled');
        fillBtn.title = 'Open fill options (queue a worker draft from the menu)';
        fillBtn.addEventListener('click', function (e) {
          e.preventDefault();
          e.stopPropagation();
          var menuBtn = host.querySelector('.pl-fill-menu-btn');
          if (menuBtn) menuBtn.click();
        });
      } else {
        fillBtn.addEventListener('click', _fillAllSlots);
      }
    }
    var skipRunChk = host.querySelector('#pl-skip-run');
    if (skipRunChk) skipRunChk.addEventListener('change', function () {
      _skipRunFill = skipRunChk.checked;
      _renderSuggestions(_suggestionsData);
    });
    _wireFillMenu(host);
  }

  function _wireFillMenu(host) {
    var menuBtn = host.querySelector('.pl-fill-menu-btn');
    var menu = host.querySelector('.pl-fill-menu');
    if (!menuBtn || !menu) return;

    function _close() {
      menu.classList.remove('is-open');
      menuBtn.setAttribute('aria-expanded', 'false');
    }

    menuBtn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      var open = !menu.classList.contains('is-open');
      menu.classList.toggle('is-open', open);
      menuBtn.setAttribute('aria-expanded', open ? 'true' : 'false');
    });

    menu.querySelectorAll('[data-fill-action]').forEach(function (btn) {
      btn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (btn.disabled) return;
        var action = btn.getAttribute('data-fill-action');
        _close();
        if (action === 'web') _fillAllSlots();
        else if (action === 'worker-draft') _queueWorkerDraft();
      });
    });

    if (!host._fillMenuDocBound) {
      host._fillMenuDocBound = true;
      document.addEventListener('click', function (e) {
        if (!host.contains(e.target)) _close();
      });
    }
  }

  function _queueWorkerDraft() {
    if (_draftQueueBusy) return;
    _draftQueueBusy = true;
    try {
      _setDraftQueueLock(true, 'Refreshing week draft from patterns…');
    } catch (e3) {
      console.warn('[plan] lock banner failed', e3);
    }

    var ws = _weekStartISO();

    fetch('/api/plan/draft/refresh', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ week_start: ws }),
    })
      .then(function (r) {
        return r.json().then(function (d) {
          if (!r.ok) {
            var detail = d && d.detail;
            throw new Error(
              (detail && (detail.error || detail.message || detail)) || ('HTTP ' + r.status)
            );
          }
          return d;
        });
      })
      .then(function (res) {
        _draftQueueBusy = false;
        try { _setDraftQueueLock(false); } catch (e5) { /* ignore */ }
        if (window.TrainingPlan && window.TrainingPlan.reloadDraft) {
          window.TrainingPlan.reloadDraft();
        }
        if (window.UIStates && window.UIStates.showToast) {
          window.UIStates.showToast('Week draft refreshed', false);
        }
        if (_suggestionsData) {
          _suggestionsData._fillNote = 'Draft refreshed from patterns';
          _renderSuggestions(_suggestionsData);
        }
        return res;
      })
      .catch(function (err) {
        _draftQueueBusy = false;
        try { _setDraftQueueLock(false); } catch (e5) { /* ignore */ }
        if (window.UIStates && window.UIStates.showToast) {
          window.UIStates.showToast((err && err.message) || 'Draft refresh failed', true);
        }
      });
  }

  function _ensureDraftLockBanner() {
    var panel = _el('plan-suggestions-panel');
    if (!panel) return null;
    var ban = panel.querySelector('.pl-draft-lock-banner');
    if (ban) return ban;
    ban = document.createElement('div');
    ban.className = 'pl-draft-lock-banner';
    ban.innerHTML =
      '<i class="pl-gen-spin pl-gen-spin-lg" aria-hidden="true"></i>' +
      '<span class="pl-draft-lock-msg"></span>' +
      '<button type="button" class="pl-draft-lock-open">Open queue</button>';
    var header = panel.querySelector('.pl-sug-header');
    if (header && header.nextSibling) panel.insertBefore(ban, header.nextSibling);
    else panel.insertBefore(ban, panel.firstChild);
    ban.querySelector('.pl-draft-lock-open').addEventListener('click', function () {
      window.location.href = '/settings#queue';
    });
    return ban;
  }

  function _setDraftQueueLock(locked, message) {
    var panel = _el('plan-suggestions-panel');
    if (!panel) return;
    panel.classList.toggle('is-draft-queued', !!locked);
    var ban = _ensureDraftLockBanner();
    if (!ban) return;
    var msg = ban.querySelector('.pl-draft-lock-msg');
    if (msg) msg.textContent = message || 'Worker is building this week draft…';
    var spin = ban.querySelector('.pl-gen-spin');
    if (spin) spin.style.display = locked ? '' : 'none';
  }

  function _closeDraftQueueModal() {
    var el = document.getElementById('pl-draft-q-overlay');
    if (el) el.remove();
  }

  function _showDraftQueueModal(opts) {
    opts = opts || {};
    _closeDraftQueueModal();
    var overlay = document.createElement('div');
    overlay.id = 'pl-draft-q-overlay';
    overlay.className = 'pl-draft-q-overlay';
    overlay.setAttribute('role', 'dialog');
    overlay.setAttribute('aria-modal', 'true');

    var card = document.createElement('div');
    card.className = 'pl-draft-q-card';

    if (opts.queuing) {
      card.innerHTML =
        '<div class="pl-draft-q-spin-wrap">' +
          '<i class="pl-gen-spin pl-gen-spin-lg" aria-hidden="true"></i>' +
          '<span>Adding plan_draft to the worker queue…</span>' +
        '</div>' +
        '<h3>Queuing…</h3>' +
        '<p>Hang on a moment — this is a quick database enqueue, not the full generation.</p>';
      overlay.appendChild(card);
      document.body.appendChild(overlay);
      return;
    }

    if (opts.error) {
      card.innerHTML =
        '<h3>' + esc(opts.title || 'Something went wrong') + '</h3>' +
        '<p>' + esc(opts.body || '') + '</p>' +
        '<div class="pl-draft-q-actions">' +
          '<button type="button" class="pl-btn" data-dq="dismiss">OK</button>' +
        '</div>';
      overlay.appendChild(card);
      document.body.appendChild(overlay);
      card.querySelector('[data-dq="dismiss"]').addEventListener('click', _closeDraftQueueModal);
      overlay.addEventListener('click', function (e) {
        if (e.target === overlay) _closeDraftQueueModal();
      });
      return;
    }

    var jid = opts.jobId || null;
    var title = opts.already ? 'Draft already queued' : 'Week draft is in the queue';
    var body = opts.already
      ? 'A plan_draft job is already in flight for this week. Open the queue to watch it, or stay here.'
      : 'The worker will build the full week draft in the background. Open the queue to watch it, or stay here — this panel will lock until the job finishes.';
    card.innerHTML =
      '<div class="pl-draft-q-spin-wrap">' +
        '<i class="pl-gen-spin pl-gen-spin-lg" aria-hidden="true"></i>' +
        '<span>Queued on zeal-server</span>' +
      '</div>' +
      '<h3>' + esc(title) + '</h3>' +
      '<p>' + esc(body) + '</p>' +
      '<div class="pl-draft-q-actions">' +
        '<a class="pl-btn pl-lime" href="/settings#queue">Open queue</a>' +
        '<button type="button" class="pl-btn" data-dq="stay">Stay here</button>' +
      '</div>' +
      (jid ? '<div class="pl-draft-q-jid">job ' + esc(jid) + '</div>' : '');

    overlay.appendChild(card);
    document.body.appendChild(overlay);

    card.querySelector('[data-dq="stay"]').addEventListener('click', function () {
      _closeDraftQueueModal();
      _setDraftQueueLock(true, 'Worker is building this week draft — buttons paused');
      _startDraftQueuePoll(jid);
    });
    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) {
        card.querySelector('[data-dq="stay"]').click();
      }
    });
  }

  function _stopDraftQueuePoll() {
    if (_draftQueuePollTimer) {
      clearInterval(_draftQueuePollTimer);
      _draftQueuePollTimer = null;
    }
  }

  function _startDraftQueuePoll(jobId) {
    _stopDraftQueuePoll();
    var tries = 0;
    function tick() {
      tries++;
      fetch('/api/queue?limit=40', { credentials: 'same-origin' })
        .then(function (r) { return r.ok ? r.json() : { jobs: [] }; })
        .then(function (data) {
          var jobs = data.jobs || [];
          var job = null;
          if (jobId) {
            job = jobs.filter(function (j) { return String(j.id) === String(jobId); })[0];
          }
          if (!job) {
            job = jobs.filter(function (j) { return j.job_type === 'plan_draft'; })[0];
          }
          if (!job) {
            if (tries > 40) {
              _finishDraftQueueWait('timed out — check Settings → Queue');
            }
            return;
          }
          var st = (job.status || '').toLowerCase();
          if (st === 'queued') {
            _setDraftQueueLock(true, 'Queued — waiting for the worker to claim the job…');
          } else if (st === 'running') {
            _setDraftQueueLock(true, 'Worker is generating the week draft…');
          } else if (st === 'done') {
            _finishDraftQueueWait('Draft ready — refresh Plan or open the draft strip to review');
            if (window.TrainingPlan && window.TrainingPlan.reloadDraft) {
              window.TrainingPlan.reloadDraft();
            }
          } else if (st === 'failed') {
            _finishDraftQueueWait('Draft job failed' + (job.error ? (': ' + job.error) : ''), true);
          }
        })
        .catch(function () { /* keep polling */ });
    }
    tick();
    _draftQueuePollTimer = setInterval(tick, 3000);
  }

  function _finishDraftQueueWait(message, isErr) {
    _stopDraftQueuePoll();
    _draftQueueBusy = false;
    _setDraftQueueLock(false);
    var panel = _el('plan-suggestions-panel');
    if (panel) panel.classList.remove('is-draft-queued');
    if (window.UIStates && window.UIStates.showToast) {
      window.UIStates.showToast(message || 'Done', !!isErr);
    }
    if (_suggestionsData) {
      _suggestionsData._fillNote = message || '';
      _renderSuggestions(_suggestionsData);
    }
  }

  // ── Rail 2: per-slot content generation ─────────────────────────────────────
  // Keeps the slot's own day/type/TSS/duration authoritative — content
  // (intent/notes/exercises/blocks) comes from deterministic pattern fill
  // (POST /api/plan/suggestions/session → plan_pattern_fill). No LLM.
  function _generateSlot(s, statusEl, opts) {
    opts = opts || {};
    var body = {
      date: _formatSugDate(s.day_offset),
      workout_type: s.workout_type,
      note: null,
      target_tss: s.target_tss || null,
      duration_minutes: s.duration_minutes || null,
      subtype: s.subtype || null,
    };
    if (opts.reshuffle) {
      // New seed each click so strength/plyo picks re-roll. Runs ignore RNG.
      body.seed = (Date.now() ^ Math.floor(Math.random() * 0xFFFFFFFF)) >>> 0;
    }
    return fetch('/api/plan/suggestions/session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        return r.json().then(function (d) {
          if (!r.ok) throw new Error((d && d.detail) || ('HTTP ' + r.status));
          return d;
        });
      })
      .then(function (data) {
        var g = data.session || {};
        s.intent = g.intent || s.intent;
        s.notes = g.notes || s.notes;
        s.exercises = g.exercises || null;
        s.blocks = g.blocks || null;
        s.source = g.source || s.source || null;
        s.pattern_name = g.pattern_name || null;
        s.fill_log = g.fill_log || null;
        s._muscle_footprint = g._muscle_footprint || null;
        s.seed = g.seed != null ? g.seed : (body.seed != null ? body.seed : null);
        s._ai = true; // "filled" flag (name is historical; content is pattern-based)
      });
  }

  // True while a fill-all chain is in flight: the fill button renders disabled
  // and _renderSuggestions leaves the progress overlay alone.
  var _fillAllRunning = false;
  // Persists across re-renders within the session (not saved) — exclude run
  // slots from bulk pattern fill when the athlete only wants strength/plyo.
  var _skipRunFill = false;

  function _fillableSlots() {
    return (_suggestionsData.suggestions || []).filter(function (s) {
      return s.workout_type !== 'rest' && !s._ai && !(_skipRunFill && s.workout_type === 'run');
    });
  }

  function _fillAllSlots() {
    if (_fillAllRunning) return;
    var slots = _fillableSlots();
    if (!slots.length) return;
    _fillAllRunning = true;
    _renderSuggestions(_suggestionsData); // repaint with the button disabled
    var loading = _el('plan-suggestions-loading');
    var label = loading ? loading.querySelector('span') : null;
    if (loading) loading.style.display = '';
    if (label) {
      label.textContent = 'Filling ' + slots.length + ' session' +
        (slots.length === 1 ? '' : 's') + ' from patterns…';
    }
    var done = 0, failed = 0;
    // Pattern fill is sync DB work — no provider rate limit. Run in parallel.
    Promise.all(slots.map(function (s) {
      return _generateSlot(s).then(
        function () { done++; },
        function () { failed++; }
      );
    })).then(function () {
      _fillAllRunning = false;
      if (loading) loading.style.display = 'none';
      _suggestionsData._fillNote = failed
        ? 'Filled ' + done + ' of ' + slots.length +
          ' — ' + failed + ' failed. Already-filled sessions are kept; try Fill from patterns again.'
        : '';
      _renderSuggestions(_suggestionsData);
    });
  }

  function _renderSuggestions(data) {
    _suggestionsData = data;
    var panel = _el('plan-suggestions-panel');
    var list = _el('plan-suggestions-list');
    var srcEl = _el('plan-suggestions-source');
    if (!panel || !list) return;

    var src = data.source || 'fallback';
    if (srcEl) {
      srcEl.textContent =
        src === 'llm' ? 'AI'
        : src === 'history' ? 'from your last 3 weeks'
        : src === 'skeleton' ? 'template (no history yet)'
        : 'template';
    }

    _renderScheduleRail(data);

    list.innerHTML = '';
    var suggestions = data.suggestions || [];
    if (!suggestions.length) {
      list.innerHTML = '<span style="font-size:12px;color:var(--text-sub);">Nothing left to suggest — the rest of this week is already scheduled.</span>';
    } else {
      // Rows in the same Mon→Sun order as the schedule grid above — but keep
      // each slot's ORIGINAL index (drag/drop, inputs and generate all key
      // into the suggestions array by it).
      suggestions
        .map(function (s, i) { return { s: s, i: i }; })
        .sort(function (a, b) { return a.s.day_offset - b.s.day_offset || a.i - b.i; })
        .forEach(function (p) {
          if (p.s.workout_type === 'rest') return; // rail 1 shows rest slots
          list.appendChild(_buildSugRow(p.s, p.i));
        });
    }

    panel.style.display = '';
    var prefsEl = _el('plan-suggestions-prefs');
    if (prefsEl) prefsEl.innerHTML = '';
    // Never hide the progress overlay while a fill-all chain is running —
    // unrelated re-renders (a TSS edit, a chip drag) used to blank it.
    var loading = _el('plan-suggestions-loading');
    if (loading && !_fillAllRunning) loading.style.display = 'none';
  }

  // ── Pre-generation preferences form ──────────────────────────────────────────
  // PRD feedback: generating blind (no visibility into what's already on the
  // schedule, no way to say "I want these days off" or "more strength this
  // week") produced suggestions the athlete had to fight with. Ask first.

  function _titleForOpenDays(openDays) {
    var titleEl = _el('plan-suggestions-title');
    if (!titleEl) return;
    var future = openDays.filter(function (d) { return !d.past; });
    if (!future.length) { titleEl.textContent = 'Suggested sessions'; return; }
    var first = _DAY_NAMES_FULL[future[0].day_offset];
    var last = _DAY_NAMES_FULL[future[future.length - 1].day_offset];
    titleEl.textContent = future.length === 7
      ? 'Suggestions for this week'
      : 'Suggestions for ' + (first === last ? first : first + '–' + last);
  }

  function _nestedGet(obj, field) {
    if (!obj) return null;
    if (field.indexOf('.') < 0) return obj[field];
    var parts = field.split('.');
    var cur = obj;
    for (var i = 0; i < parts.length; i++) {
      if (!cur || typeof cur !== 'object') return null;
      cur = cur[parts[i]];
    }
    return cur;
  }

  function _applyPrefsFromApi(data) {
    var p = (data && data.active && data.active.payload) || {};
    var days = _nestedGet(p, 'rest_days') || [];
    _lastPrefs.restDays = days.map(Number).filter(function (d) { return d >= 0 && d <= 6; });
    _lastPrefs.strengthEmphasis = _nestedGet(p, 'strength_emphasis') || 'same';
    _lastPrefs.plyoMode = _nestedGet(p, 'plyo_mode') || 'standalone';
    _lastPrefs.plyoSessions = Number(_nestedGet(p, 'plyo_sessions_per_week') || 0);
    _lastPrefs.mpSegmentMin = Number(_nestedGet(p, 'long_run.mp_segment_min') || 0);
    _habitTargets = data.habit_targets || null;
    // Pending proposals only. GET /api/preferences returns settled ones too
    // (include_settled=True); accepted/declined are history, and a decision
    // surface that shows history is a report, not a decision surface.
    _prefProposals = (data.proposals || []).filter(function (p2) {
      return p2 && p2.status === 'proposed';
    });
  }

  function _collectTrainingPrefsPayload() {
    return {
      rest_days: _lastPrefs.restDays.slice().sort(function (a, b) { return a - b; }),
      strength_emphasis: _lastPrefs.strengthEmphasis || 'same',
      plyo_mode: _lastPrefs.plyoMode || 'off',
      plyo_sessions_per_week: Number(_lastPrefs.plyoSessions) || 0,
      long_run: { mp_segment_min: Number(_lastPrefs.mpSegmentMin) || 0 },
      notes: '',
    };
  }

  function _readPrefsFormIntoState() {
    var countEl = _el('pl-sug-strength-count');
    if (countEl) _lastPrefs.strengthSessions = countEl.value.trim();
    var se = _el('pl-sug-strength-emphasis');
    if (se) _lastPrefs.strengthEmphasis = se.value;
    var pm = _el('pl-sug-plyo-mode');
    if (pm) _lastPrefs.plyoMode = pm.value;
    var ps = _el('pl-sug-plyo-sessions');
    if (ps) _lastPrefs.plyoSessions = Number(ps.value) || 0;
    var mp = _el('pl-sug-mp-segment');
    if (mp) _lastPrefs.mpSegmentMin = Number(mp.value) || 0;
  }

  function _saveTrainingPrefs() {
    return fetch('/api/preferences', {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ payload: _collectTrainingPrefsPayload() }),
    }).then(function (r) {
      return r.json().then(function (body) {
        if (!r.ok) return Promise.reject(body);
        return body;
      });
    });
  }

  function _renderPrefsForm() {
    var host = _el('plan-suggestions-prefs');
    if (!host) return;
    var list = _el('plan-suggestions-list');
    if (list) list.innerHTML = '';
    var sched = _el('plan-suggestions-sched');
    if (sched) sched.innerHTML = '';
    var loading = _el('plan-suggestions-loading');
    if (loading) loading.style.display = 'none';

    host.innerHTML = '<div class="pl-sug-prefs"><span style="font-size:12px;color:var(--text-sub);">Loading preferences…</span></div>';

    fetch('/api/preferences', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        _applyPrefsFromApi(data);
        _paintPrefsForm();
      })
      .catch(function () {
        _paintPrefsForm();
      });
  }

  // ── Preference proposals ledger ────────────────────────────────────────────
  //
  // The gap analyzer watches for persistent findings and proposes a preference
  // change (one catalog step). Accept / Adjust / Not now used to live in the
  // coach brief; they live here now (D6) because deciding "should my plyo
  // sessions go 0 -> 1" is easier with the plyo controls visible directly below.
  //
  // Pending only. Accepted and declined proposals are history and are not shown
  // — the API still returns them, and a later Preferences history view can pick
  // them up from the same payload.

  function _proposalDeltaText(prop) {
    var d = (prop && prop.delta) || {};
    // Server sends a rendered strip when it can (delta_strip); fall back to
    // field: from -> to so an unrecognised shape still reads as something.
    if (d.strip) return String(d.strip);
    if (d.kind === 'add_to_set' && d.to && d.to.exercise_name) {
      return 'Add ' + d.to.exercise_name + ' to strength' +
        (d.muscle_group ? (' (underloaded ' + d.muscle_group + ')') : '');
    }
    var field = d.field || d.key || '';
    if (field && d.from !== undefined && d.to !== undefined) {
      return field + ': ' + d.from + ' → ' + d.to;
    }
    return field || JSON.stringify(d);
  }

  function _isAddToSet(p) {
    return !!(p && p.delta && p.delta.kind === 'add_to_set');
  }

  // "Adjust..." asks for a custom value via window.prompt() and both the
  // frontend parse (Number(raw)) and the backend accept_proposal() adjust
  // path (int(adjusted_to)) are int-only today. plyo_sessions_per_week /
  // long_run.mp_segment_min are ints, so this always worked before — but
  // strength_emphasis (issue #1604 follow-up: muscle_overused/untrained/
  // strength_lapsed proposals) is an enum ("less"/"same"/"more"), and typing
  // that into the numeric prompt fails with a confusing "Enter a number".
  // Hiding Adjust for enum-valued proposals is the honest scoped fix — Accept
  // and Not now both work correctly for enums already (accept applies the
  // pre-computed delta.to with no client parsing). A real enum adjust UI
  // (a 3-way choice instead of free text) is a separate follow-up.
  function _isNumericDelta(p) {
    if (_isAddToSet(p)) return false;
    var to = p && p.delta && p.delta.to;
    return typeof to === 'number' || (typeof to === 'string' && /^-?\d+(\.\d+)?$/.test(to));
  }

  function _proposalsHtml() {
    if (!_prefProposals.length) return '';
    var rows = _prefProposals.map(function (p) {
      var id = esc(p.id || '');
      var expires = (p.expires_at || '').slice(0, 10);
      var actions;
      if (_isAddToSet(p)) {
        actions =
          '<button type="button" class="pl-btn pl-lime pl-prop-try">Try for a week</button>' +
          '<button type="button" class="pl-btn pl-ghost pl-prop-standing">Make it standing</button>' +
          '<button type="button" class="pl-btn pl-ghost pl-prop-decline">Not now</button>';
      } else {
        actions =
          '<button type="button" class="pl-btn pl-lime pl-prop-accept">Accept</button>' +
          (_isNumericDelta(p)
            ? '<button type="button" class="pl-btn pl-ghost pl-prop-adjust">Adjust…</button>'
            : '') +
          '<button type="button" class="pl-btn pl-ghost pl-prop-decline">Not now</button>';
      }
      return (
        '<div class="pl-prop" data-proposal-id="' + id + '">' +
          '<div class="pl-prop-main">' +
            '<div class="pl-prop-delta">' + esc(_proposalDeltaText(p)) + '</div>' +
            (p.rationale
              ? '<div class="pl-prop-why">' + esc(p.rationale) + '</div>' : '') +
            (expires
              ? '<div class="pl-prop-life">expires ' + esc(expires) + ' if ignored</div>' : '') +
          '</div>' +
          '<div class="pl-prop-actions">' + actions + '</div>' +
        '</div>'
      );
    }).join('');
    return (
      '<div class="pl-sug-prefs-row pl-prop-block" style="align-items:start;">' +
        '<label class="pl-sug-prefs-label">Proposals' +
          '<span class="pl-prop-count">' + _prefProposals.length + '</span>' +
        '</label>' +
        '<div class="pl-props">' + rows + '</div>' +
      '</div>'
    );
  }

  function _postProposal(id, action, body) {
    return fetch('/api/preferences/proposals/' + encodeURIComponent(id) + '/' + action, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
      if (r.ok) return r.json();
      return r.json().then(
        function (j) { throw new Error((j && j.detail) || r.statusText); },
        function () { throw new Error(r.statusText); }
      );
    });
  }

  function _bindProposalActions(host) {
    host.querySelectorAll('.pl-prop').forEach(function (row) {
      var id = row.getAttribute('data-proposal-id');
      if (!id) return;

      // Re-fetch rather than reload the page: the coach brief reloaded because
      // it was a modal over the Home page, but here the athlete is mid-edit in
      // the prefs form and a reload would discard unsaved changes.
      function settle(btn, action, body) {
        var buttons = row.querySelectorAll('button');
        buttons.forEach(function (b) { b.disabled = true; });
        _postProposal(id, action, body)
          .then(function () { _renderPrefsForm(); })
          .catch(function (err) {
            buttons.forEach(function (b) { b.disabled = false; });
            var errEl = _el('pl-sug-prefs-err');
            if (errEl) {
              errEl.hidden = false;
              errEl.textContent = err.message || (action + ' failed');
            }
          });
      }

      var accept = row.querySelector('.pl-prop-accept');
      if (accept) accept.addEventListener('click', function () { settle(accept, 'accept'); });

      var tryWeek = row.querySelector('.pl-prop-try');
      if (tryWeek) tryWeek.addEventListener('click', function () {
        settle(tryWeek, 'accept', { action: 'try_week' });
      });
      var standing = row.querySelector('.pl-prop-standing');
      if (standing) standing.addEventListener('click', function () {
        settle(standing, 'accept', { action: 'standing' });
      });

      var decline = row.querySelector('.pl-prop-decline');
      if (decline) decline.addEventListener('click', function () { settle(decline, 'decline'); });

      var adjust = row.querySelector('.pl-prop-adjust');
      if (adjust) adjust.addEventListener('click', function () {
        var raw = window.prompt('New value (one catalog step from current):');
        if (raw == null || raw === '') return;
        var n = Number(raw);
        if (!Number.isFinite(n)) {
          var errEl = _el('pl-sug-prefs-err');
          if (errEl) { errEl.hidden = false; errEl.textContent = 'Enter a number'; }
          return;
        }
        settle(adjust, 'adjust', { to: n });
      });
    });
  }

  function _paintPrefsForm() {
    var host = _el('plan-suggestions-prefs');
    if (!host) return;

    var openDays = (window.TrainingPlan && window.TrainingPlan.getOpenDayInfo)
      ? window.TrainingPlan.getOpenDayInfo() : [];
    _titleForOpenDays(openDays);

    var dayChecks = openDays.map(function (d) {
      var checked = _lastPrefs.restDays.indexOf(d.day_offset) !== -1;
      var past = !!d.past;
      var hasSession = !!d.hasSession;
      var cls = 'pl-sug-daychk' + (past ? ' is-past' : '') + (hasSession && !past ? ' has-session' : '');
      var title = past
        ? 'Past day — cannot change'
        : (hasSession ? 'Has a session — you can still mark it as a preferred rest day' : 'Ask for this day off');
      return '<label class="' + cls + '" title="' + title + '">' +
        '<input type="checkbox" data-restday="' + d.day_offset + '"' +
        (checked ? ' checked' : '') + (past ? ' disabled' : '') + '/>' +
        '<span>' + _DAY_NAMES[d.day_offset] + '</span>' +
        (hasSession && !past ? '<span class="pl-sug-sess-tag">session</span>' : '') +
        (past ? '<span class="pl-sug-sess-tag" style="background:#f1f5f9;color:#64748b;">past</span>' : '') +
        '</label>';
    }).join('');

    var anyFuture = openDays.some(function (d) { return !d.past; });
    var ht = _habitTargets || {};
    var habitsLine =
      'Zone&nbsp;2 / stretch targets live on <a href="/habits">Habits</a>' +
      (ht.zone2_weekly_min != null
        ? (' · Z2 <b>' + esc(ht.zone2_weekly_min) + ' min/wk</b> · stretch <b>' +
          esc(ht.stretch_daily_min != null ? ht.stretch_daily_min : '—') + ' min/day</b>')
        : '');

    host.innerHTML =
      '<div class="pl-sug-prefs">' +
        (anyFuture ? (
          '<div class="pl-sug-prefs-row">' +
            '<label class="pl-sug-prefs-label">Rest days</label>' +
            '<div class="pl-sug-daychks">' + dayChecks + '</div>' +
          '</div>' +
          '<div class="pl-sug-prefs-row pl-sug-prefs-row--inline">' +
            '<label class="pl-sug-prefs-label" for="pl-sug-strength-count">Strength sessions</label>' +
            '<span class="pl-sug-count-wrap"><input id="pl-sug-strength-count" class="pl-sug-count" type="number" min="0" max="7" step="1" placeholder="auto" value="' + esc(_lastPrefs.strengthSessions) + '"/>' +
            '<span class="pl-sug-count-hint">blank = recent weeks</span></span>' +
          '</div>' +
          '<div class="pl-sug-prefs-extra">' +
            '<div class="pl-sug-prefs-row pl-sug-prefs-row--inline">' +
              '<label class="pl-sug-prefs-label" for="pl-sug-strength-emphasis">Strength emphasis</label>' +
              '<select id="pl-sug-strength-emphasis" class="pl-sug-select">' +
                ['less', 'same', 'more'].map(function (v) {
                  return '<option value="' + v + '"' + (_lastPrefs.strengthEmphasis === v ? ' selected' : '') + '>' + v + '</option>';
                }).join('') +
              '</select>' +
            '</div>' +
            '<div class="pl-sug-prefs-row pl-sug-prefs-row--inline">' +
              '<label class="pl-sug-prefs-label" for="pl-sug-plyo-mode">Plyo mode</label>' +
              '<select id="pl-sug-plyo-mode" class="pl-sug-select">' +
                ['standalone', 'superset', 'off'].map(function (v) {
                  return '<option value="' + v + '"' + (_lastPrefs.plyoMode === v ? ' selected' : '') + '>' + v + '</option>';
                }).join('') +
              '</select>' +
            '</div>' +
            '<div class="pl-sug-prefs-row pl-sug-prefs-row--inline">' +
              '<label class="pl-sug-prefs-label" for="pl-sug-plyo-sessions">Plyo / week</label>' +
              '<input id="pl-sug-plyo-sessions" type="number" min="0" max="2" step="1" value="' + esc(_lastPrefs.plyoSessions) + '"/>' +
            '</div>' +
            '<div class="pl-sug-prefs-row pl-sug-prefs-row--inline">' +
              '<label class="pl-sug-prefs-label" for="pl-sug-mp-segment">Long-run MP (min)</label>' +
              '<input id="pl-sug-mp-segment" type="number" min="0" max="30" step="10" value="' + esc(_lastPrefs.mpSegmentMin) + '"/>' +
            '</div>' +
          '</div>' +
          _proposalsHtml() +
          '<div class="pl-sug-habits">' + habitsLine + '</div>' +
          '<div class="pl-sug-prefs-err" id="pl-sug-prefs-err" hidden></div>' +
          '<div class="pl-btnrow" style="margin-top:12px;">' +
            '<button type="button" class="pl-btn pl-lime" id="pl-sug-generate">Build schedule</button>' +
            '<button type="button" class="pl-btn pl-ghost" id="pl-sug-save-prefs">Save preferences</button>' +
            '<button type="button" class="pl-btn pl-ghost" id="pl-sug-cancel">Cancel</button>' +
          '</div>'
        ) : (
          '<div class="pl-infobanner">This week is entirely in the past — use the week arrows to look at the current or next week.</div>' +
          '<div class="pl-btnrow"><button type="button" class="pl-btn pl-ghost" id="pl-sug-cancel">Close</button></div>'
        )) +
      '</div>';

    _bindProposalActions(host);
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
      _readPrefsFormIntoState();
      _loadSuggestions();
    });
    var savePrefsBtn = _el('pl-sug-save-prefs');
    if (savePrefsBtn) savePrefsBtn.addEventListener('click', function () {
      _readPrefsFormIntoState();
      var errEl = _el('pl-sug-prefs-err');
      if (errEl) { errEl.hidden = true; errEl.textContent = ''; }
      savePrefsBtn.disabled = true;
      _saveTrainingPrefs()
        .then(function () {
          savePrefsBtn.textContent = 'Saved';
          setTimeout(function () { savePrefsBtn.textContent = 'Save preferences'; }, 1200);
        })
        .catch(function (body) {
          var msg = 'Save failed';
          if (body && body.detail) {
            msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail, null, 2);
          }
          if (errEl) { errEl.hidden = false; errEl.textContent = msg; }
        })
        .finally(function () { savePrefsBtn.disabled = false; });
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
    var errEl = _el('pl-sug-prefs-err');
    if (!panel) return;
    panel.style.display = '';
    if (errEl) { errEl.hidden = true; errEl.textContent = ''; }
    if (loading) {
      loading.style.display = '';
      var lbl = loading.querySelector('span');
      if (lbl) lbl.textContent = 'Saving preferences…';
    }

    var strengthCount = parseInt(_lastPrefs.strengthSessions, 10);
    _saveTrainingPrefs()
      .catch(function (body) {
        if (loading) loading.style.display = 'none';
        var msg = 'Could not save preferences';
        if (body && body.detail) {
          msg = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail, null, 2);
        }
        if (errEl) { errEl.hidden = false; errEl.textContent = msg; }
        return Promise.reject(body);
      })
      .then(function () {
        if (loading) {
          var lbl2 = loading.querySelector('span');
          if (lbl2) lbl2.textContent = 'Building schedule…';
        }
        return fetch('/api/plan/suggestions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            week_start: _weekStartISO(),
            rest_days: _lastPrefs.restDays,
            skeleton: true,
            strength_sessions: isNaN(strengthCount) ? null : strengthCount,
          }),
        });
      })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(_renderSuggestions)
      .catch(function (err) {
        if (loading) loading.style.display = 'none';
        if (err && err.detail) return; // prefs error already shown
        if (list) list.innerHTML = '<span style="font-size:12px;color:var(--text-sub);">Could not load suggestions.</span>';
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
