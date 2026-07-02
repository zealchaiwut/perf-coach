/* Training > Plan sub-tab — weekly training schedule (window.TrainingPlan).
 *
 * Ported from the interactive mock (plan-tab-mock.html): a single scrolling
 * page with three regions — Week plan (always), Add panel (collapsed), Detail
 * panel (collapsed) as a mutually-exclusive accordion. Wired to the live
 * /api/planned-sessions endpoints. Distinct from Projection's ramp/taper model.
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

  // ── Public API ──────────────────────────────────────────────────────────────
  window.TrainingPlan = {
    init: function () {
      _injectStyles();
      if (!_weekStart) _weekStart = _mondayOf(new Date());
      // Idempotent: always re-render the shell + reload the current week.
      _renderAll();
      _loadWeek();
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
  function _loadWeek() {
    var from = _iso(_weekStart), to = _iso(_addDays(_weekStart, 6));
    var host = document.getElementById('plan-week-list');
    if (host) host.innerHTML = '<div class="pl-loading">Loading week…</div>';
    _api('GET', '/api/planned-sessions?from=' + from + '&to=' + to)
      .then(function (data) { _bundle = data; _renderWeekList(); })
      .catch(function () {
        if (host) host.innerHTML = '<div class="pl-loading">Could not load the week.</div>';
      });
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
          '<button class="pl-btn pl-ghost pl-soonbtn" disabled title="Coming soon — will use your current performance + training history">Suggest sessions<span class="pl-soontag">Soon</span></button>' +
          '<button class="pl-btn pl-ghost" id="pl-addweek">+ Add week</button>' +
          '<button class="pl-btn pl-dark" id="pl-addsession">+ Add session</button>' +
        '</div></div>' +
        '<div class="pl-infobanner" style="margin-bottom:12px;">Synced workouts from Strava/Stryd auto-match to planned sessions. Drag a <b>planned</b> or <b>missed</b> card to reschedule; ambiguous or missing matches need a quick confirm below. These planned sessions <b>don’t feed Projection’s ramp/taper load model</b> — separate systems.</div>' +
        '<div class="pl-weeklist" id="plan-week-list"></div>' +
        '<div class="pl-legend">' +
          '<span><b style="background:var(--pl-run)"></b>Run</span><span><b style="background:var(--pl-lift)"></b>Strength / Plyo</span>' +
          '<span style="color:var(--pl-faint);margin:0 2px;">·</span>' +
          '<span><b style="background:var(--pl-green)"></b>Done</span><span><b style="background:var(--pl-amber)"></b>Needs review</span><span><b style="background:var(--pl-red)"></b>Missed</span>' +
        '</div>' +
      '</div>';
    document.getElementById('pl-prev').onclick = function () { _weekStart = _addDays(_weekStart, -7); _renderWeekSection(); _loadWeek(); };
    document.getElementById('pl-next').onclick = function () { _weekStart = _addDays(_weekStart, 7); _renderWeekSection(); _loadWeek(); };
    document.getElementById('pl-addweek').onclick = function () { _openAdd('bulk'); };
    document.getElementById('pl-addsession').onclick = function () { _openAdd('single'); };
    if (_bundle) _renderWeekList();
  }

  function _renderWeekList() {
    var host = document.getElementById('plan-week-list');
    if (!host || !_bundle) return;
    var todayStr = _todayISO();
    host.innerHTML = (_bundle.days || []).map(function (day) {
      var cls = day.date === todayStr ? 'today' : (day.date < todayStr ? 'past' : '');
      var cards = (day.planned || []).map(function (p) { return _plannedCardHtml(p, day); }).join('');
      var ghosts = (day.unplanned || []).filter(function (u) { return !_dismissedGhosts[u.id]; })
        .map(function (u) { return _ghostCardHtml(u, day); }).join('');
      var hasContent = (day.planned || []).length || ghosts;
      var rest = !hasContent ? '<div class="pl-restday">Rest day</div>' : '';
      return '<div class="pl-dayrow ' + cls + '" data-date="' + day.date + '">' +
        '<div class="pl-daylabel"><span class="pl-dname">' + day.dow + '</span><span class="pl-dnum">' + _parseISO(day.date).getDate() + '</span></div>' +
        '<div class="pl-daybody">' + cards + ghosts + rest +
          '<div class="pl-addday" data-add-date="' + day.date + '">+ add</div>' +
        '</div>' +
      '</div>';
    }).join('');
    _wireWeekEvents();
  }

  function _statusTag(status) {
    if (status === 'missed') return '<span class="pl-stat-tag missed">MISSED</span>';
    if (status === 'needs_review') return '<span class="pl-stat-tag review">NEEDS REVIEW</span>';
    if (status === 'done_auto') return '<span class="pl-stat-tag done">AUTO-MATCHED</span>';
    if (status === 'done_manual') return '<span class="pl-stat-tag done">MANUALLY LINKED</span>';
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
      body = '<div class="pl-diffline">Planned ' + esc((_plannedMeta(p) || '').split('·')[0].trim() || p.session_type) +
        ' → Actual ' + esc(actMeta) + '</div>' +
        _viewFullLinkHtml(mwid) +
        _feelRowHtml(mwid, feel) +
        '<div class="pl-matchbtns">' +
          '<button class="pl-unlink" data-unlink="' + p.id + '">unlink match</button>' +
          '<button class="pl-pickbtn" data-pick="' + p.id + '" data-pick-mode="override">Change matched workout</button>' +
        '</div>' +
        '<div class="pl-picker" data-pickerfor="' + p.id + '" hidden></div>';
    } else if (p.status === 'planned' || p.status === 'missed') {
      body = '<button class="pl-pickbtn pl-pick-attach" data-pick="' + p.id + '" data-pick-mode="attach">🔗 Attach a recent workout</button>' +
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
      '<div class="pl-sesstop"><span class="pl-stypetag ' + fam + '">' + (fam === 'run' ? 'run' : 'lift') + '</span>' + _statusTag(p.status) + '</div>' +
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
    var opts = (day.planned || []).filter(function (p) {
      return p.status !== 'done_auto' && p.status !== 'done_manual' && p.session_type !== 'rest';
    }).map(function (p) { return '<option value="' + p.id + '">' + esc(p.name || '(untitled)') + '</option>'; }).join('');
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
    host.querySelectorAll('.pl-addday').forEach(function (el) {
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

  // ══ ADD PANEL ═══════════════════════════════════════════════════════════════
  function _openAdd(topMode, presetDate) {
    _panel.open = 'add';
    _addState.top = topMode; _addState.sub = 'form';
    _addState.presetDate = presetDate || _iso(_weekStart);
    _renderAddSection(); _renderDetailSection();
    var el = document.getElementById('plan-add-section');
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }
  function _closeAdd() { _panel.open = null; _renderAddSection(); }

  function _renderAddSection() {
    var host = document.getElementById('plan-add-section');
    if (!host) return;
    if (_panel.open !== 'add') { host.innerHTML = ''; return; }
    host.innerHTML = '<div class="pl-card pl-panelcard">' +
      '<div class="pl-panelhead"><span class="pl-sectitle">Add session(s)</span><button class="pl-closepanel" id="pl-addclose">✕</button></div>' +
      '<div class="pl-modetoggle" id="pl-addmode"><button data-m="single">Single session</button><button data-m="bulk">Bulk-add a week</button></div>' +
      '<div id="pl-addbody"></div>' +
    '</div>';
    document.getElementById('pl-addclose').onclick = _closeAdd;
    _renderAddBody();
  }

  function _renderAddBody() {
    var subs = _addState.top === 'single' ? [['form', 'Form'], ['json', 'JSON']]
      : [['form', 'Form'], ['json', 'JSON'], ['sep', 'Separator']];
    var subHtml = '<div class="pl-subtoggle" id="pl-addsub">' + subs.map(function (x) {
      return '<button class="' + (x[0] === _addState.sub ? 'on' : '') + '" data-sm="' + x[0] + '">' + x[1] + '</button>';
    }).join('') + '</div>';
    var content;
    if (_addState.top === 'single') content = _addState.sub === 'form' ? _singleFormHtml() : _singleJSONHtml();
    else content = _addState.sub === 'form' ? _bulkFormHtml() : (_addState.sub === 'json' ? _bulkJSONHtml() : _bulkSepHtml());
    document.getElementById('pl-addbody').innerHTML = subHtml + content;
    [].forEach.call(document.getElementById('pl-addmode').children, function (b) {
      b.classList.toggle('on', b.dataset.m === _addState.top);
    });
    _wireAddBody();
  }

  // ── Single Form (adaptive: run block builder vs strength exercise rows) ─────
  function _singleFormHtml() {
    return '<div class="pl-frow">' +
        '<div class="pl-fld"><label>Date</label><input type="date" id="pl-sf-date" value="' + esc(_addState.presetDate) + '"/></div>' +
        '<div class="pl-fld"><label>Type</label><select id="pl-sf-type"><option value="run">Run</option><option value="strength">Strength</option><option value="plyo">Plyo</option><option value="rest">Rest</option></select></div>' +
        '<div class="pl-fld"><label>Session name</label><input id="pl-sf-name" placeholder="Sustained Tempo"/></div>' +
      '</div>' +
      '<div id="pl-sf-structure"></div>' +
      '<div class="pl-fld" style="margin-top:14px;"><label>Notes from coach</label><textarea id="pl-sf-notes" placeholder="e.g. hold 92% CP even on the 3rd rep"></textarea></div>' +
      '<div class="pl-btnrow" style="margin-top:14px;"><button class="pl-btn pl-lime" id="pl-sf-save">Save session</button><button class="pl-btn pl-ghost" id="pl-sf-cancel">Cancel</button></div>';
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
  var _sfStrengthMode = 'detailed'; // 'simple' | 'detailed'

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
        '</div>' +
        (_sfStrengthMode === 'simple'
          ? '<div class="pl-fld"><label>Focus</label><input id="pl-str-focus" placeholder="Lower / posterior chain"/></div>'
          : '<div class="pl-fld" style="margin-bottom:6px;"><label>Exercises</label></div>' +
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
      if (add) add.onclick = function () { _sfExercises.push({ name: '', sets: 3, reps: 10, load: '' }); _renderStructureBuilder(); };
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
        _api('POST', '/api/planned-sessions', payload)
          .then(function () { _toast('Session saved'); _closeAdd(); _loadWeek(); })
          .catch(function (e) { _toast(e.message || 'Save failed', true); });
      };
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
    if (editBtn) editBtn.onclick = function () { _openAdd('single', p.planned_date); };
    var copyBtn = document.getElementById('pl-det-copy');
    if (copyBtn) copyBtn.onclick = function () {
      var pre = document.getElementById('pl-stryd-pre');
      var text = pre ? pre.textContent : '';
      _copyText(text, copyBtn);
    };
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

  function _phaseLabel(ph) { return ph === 'warmup' ? 'Warmup' : (ph === 'cooldown' ? 'Cooldown' : (ph === 'main' ? 'Main set' : (ph || 'Block'))); }
  function _phaseCls(ph) { return ph === 'warmup' ? 'warm' : (ph === 'cooldown' ? 'cool' : 'main'); }

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
        '<span style="flex:1"></span><button class="pl-btn pl-ghost" id="pl-det-edit">Edit</button></div>' +
      '<div class="pl-dettitle">' + esc(p.name || '(untitled)') + '</div>' +
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
    var s = p.structure || {}, exs = Array.isArray(s.exercises) ? s.exercises : [];
    var focus = s.focus || '';
    var typeLabel = p.session_type === 'plyo' ? 'Plyo' : 'Strength';
    var exHtml = exs.length ? exs.map(function (x) {
      var sr = (x.sets != null && x.reps != null) ? (x.sets + ' × ' + x.reps) : (x.sets != null ? x.sets + ' sets' : '');
      return '<div class="pl-exd"><span class="pl-en">' + esc(x.name || 'Exercise') + '</span><span class="pl-es">' + esc(sr) + '</span><span class="pl-es" style="color:var(--pl-faint)">' + esc(x.load || '') + '</span></div>';
    }).join('') : (focus ? '' : '<div class="pl-exd"><span class="pl-en" style="color:var(--pl-faint)">No exercises listed.</span></div>');

    return '<div class="pl-dethead"><span class="pl-dettag lift">' + typeLabel + '</span>' +
        '<span style="font-size:11px;color:var(--pl-faint);font-family:var(--pl-mono)">' + esc(_fmtDayDate(p.planned_date)) + '</span>' +
        '<span style="flex:1"></span><button class="pl-btn pl-ghost" id="pl-det-edit">Edit</button></div>' +
      '<div class="pl-dettitle">' + esc(p.name || '(untitled)') + '</div>' +
      '<div class="pl-dettiles">' +
        '<div class="pl-dettile"><div class="l">Type</div><div class="v" style="font-size:14px;">' + typeLabel + '</div></div>' +
        (focus ? '<div class="pl-dettile"><div class="l">Focus</div><div class="v" style="font-size:14px;">' + esc(focus) + '</div></div>' : '') +
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
    '.plan-panel .pl-btn.pl-dark{background:var(--pl-ink);color:#fff;border-color:var(--pl-ink);}',
    '.plan-panel .pl-btn.pl-lime{background:var(--pl-lime);color:var(--pl-ink);border-color:var(--pl-lime);}',
    '.plan-panel .pl-btn.pl-ghost{background:none;border:1px solid var(--pl-line);}',
    '.plan-panel .pl-btn.pl-tiny{font-size:10px;padding:5px 9px;}',
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
    '.plan-panel .pl-pick-attach{margin-top:6px;font-weight:600;}',
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
    '.plan-panel .pl-restday{font-size:11px;color:var(--pl-faint);font-style:italic;align-self:center;padding:6px 4px;}',
    '.plan-panel .pl-legend{display:flex;gap:14px;margin-top:12px;font-size:11px;color:var(--pl-muted);flex-wrap:wrap;}',
    '.plan-panel .pl-legend b{display:inline-block;width:8px;height:8px;border-radius:2px;margin-right:5px;}',
    '.plan-panel .pl-soonbtn{position:relative;opacity:0.7;cursor:not-allowed;}',
    '.plan-panel .pl-soontag{font-size:8px;font-weight:800;background:var(--pl-amberSoft);color:var(--pl-amber);padding:1px 5px;border-radius:4px;margin-left:6px;vertical-align:middle;}',
    '.plan-panel .pl-modetoggle{display:flex;background:var(--pl-tile);border:1px solid var(--pl-line);border-radius:9px;padding:3px;gap:2px;width:fit-content;margin-bottom:16px;}',
    '.plan-panel .pl-modetoggle button{font-size:12px;font-weight:600;color:var(--pl-muted);background:none;border:none;padding:6px 13px;border-radius:7px;cursor:pointer;font-family:inherit;}',
    '.plan-panel .pl-modetoggle button.on{background:#fff;color:var(--pl-ink);box-shadow:0 1px 2px rgba(0,0,0,0.06);}',
    '.plan-panel .pl-subtoggle{display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap;}',
    '.plan-panel .pl-subtoggle button{font-size:11.5px;font-weight:700;color:var(--pl-muted);background:var(--pl-tile);border:1px solid var(--pl-line);padding:6px 12px;border-radius:7px;cursor:pointer;font-family:inherit;}',
    '.plan-panel .pl-subtoggle button.on{background:var(--pl-ink);color:#fff;border-color:var(--pl-ink);}',
    '.plan-panel .pl-jsontools{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap;align-items:center;}',
    '.plan-panel .pl-jsonta{width:100%;min-height:230px;font-family:var(--pl-mono);font-size:12px;line-height:1.65;border:1px solid var(--pl-line);background:#0f1330;color:#cfe0ff;border-radius:10px;padding:14px;resize:vertical;white-space:pre;}',
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
    '@media(max-width:560px){.plan-panel .pl-dayrow{flex-direction:column;gap:8px;}.plan-panel .pl-daylabel{width:auto;display:flex;align-items:baseline;gap:6px;padding-top:0;}}'
  ].join('');

}());
