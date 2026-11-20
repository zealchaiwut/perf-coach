(function (global) {
  'use strict';

  var esc = global.AppCommon ? global.AppCommon.escapeHtml.bind(global.AppCommon) : function (s) { return String(s); };
  var MODE_KEY = 'v2-strength-editor-mode';
  var validateTimer = null;
  var dirty = false;
  var state = {
    mode: 'edit',
    workout: null,
    savedJson: '[]',
    jsonText: '[]',
    valid: false,
    errors: [],
    resolutions: [],
    dry: null,
    versions: [],
    viewOnly: false,
  };

  function els() {
    return {
      backdrop: document.getElementById('v2-drawer-backdrop'),
      drawer: document.getElementById('v2-drawer'),
      body: document.getElementById('v2-drawer-body'),
    };
  }

  function loadMode() {
    try {
      var m = localStorage.getItem(MODE_KEY);
      if (m === 'form' || m === 'json') return m;
    } catch (e) { /* ignore */ }
    return 'json';
  }

  function saveMode(m) {
    try { localStorage.setItem(MODE_KEY, m); } catch (e) { /* ignore */ }
  }

  function toast(msg) {
    var el = document.getElementById('v2-toast');
    if (!el) return;
    el.textContent = msg;
    el.classList.add('is-visible');
    setTimeout(function () { el.classList.remove('is-visible'); }, 2800);
  }

  function close() {
    if (dirty && !confirm('Discard unsaved changes?')) return;
    var e = els();
    if (e.drawer) {
      e.drawer.classList.remove('is-open');
      e.drawer.hidden = true;
    }
    if (e.backdrop) {
      e.backdrop.classList.remove('is-open');
      e.backdrop.hidden = true;
    }
    document.removeEventListener('keydown', onKey);
    dirty = false;
  }

  function onKey(ev) {
    if (ev.key === 'Escape') close();
  }

  function fmtDur(sec) {
    if (!sec) return '—';
    var m = Math.round(sec / 60);
    return m + ' min';
  }

  function scheduleValidate() {
    if (validateTimer) clearTimeout(validateTimer);
    validateTimer = setTimeout(runValidate, 500);
  }

  function runValidate() {
    return fetch('/api/sessions/validate-exercises', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ text: state.jsonText }),
    }).then(function (r) { return r.json(); }).then(function (payload) {
      state.valid = !!payload.valid;
      state.errors = payload.errors || [];
      state.resolutions = payload.resolutions || [];
      if (payload.valid && payload.formatted) {
        state.jsonText = payload.formatted;
      }
      return runDryRun();
    }).then(function () {
      render();
    });
  }

  function runDryRun() {
    if (!state.valid) { state.dry = null; return Promise.resolve(); }
    var body = {
      text: state.jsonText,
      duration_seconds: state.workout ? state.workout.duration_seconds : (52 * 60),
      session_effort: state.workout ? state.workout.session_effort : 7,
      strength_tss_method: state.workout ? state.workout.strength_tss_method : null,
    };
    if (state.workout && state.workout.id) body.workout_id = state.workout.id;
    else body.workout_date = state.workout ? state.workout.workout_date : (global.AppCommon && global.AppCommon.todayISO ? global.AppCommon.todayISO() : new Date().toISOString().slice(0, 10));
    return fetch('/api/sessions/dry-run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(body),
    }).then(function (r) { return r.ok ? r.json() : null; }).then(function (d) { state.dry = d; });
  }

  function renderTssPanel() {
    if (!state.dry) return '<p class="rv-subtitle">TSS preview loads after valid JSON.</p>';
    var d = state.dry;
    var oldTss = state.workout && state.workout.tss != null ? state.workout.tss : '—';
    var newTss = d.session_tss != null ? d.session_tss : '—';
    var week = d.week_tss_total != null ? d.week_tss_total : '—';
    var ctl = d.ctl != null ? d.ctl : '—';
    var dual = '';
    if (d.tss_exercises != null && d.tss_effort_time != null && Math.abs(d.tss_exercises - d.tss_effort_time) <= 1) {
      dual = '<p class="rv-hint">Exercise and effort×time methods differ by ≤1 TSS.</p>';
    }
    return (
      '<div class="rv-strength-tss-panel">' +
      '<p><strong>Session</strong> <s>' + esc(String(oldTss)) + '</s> → <strong>' + esc(String(newTss)) + '</strong></p>' +
      '<p><strong>Week</strong> ' + esc(String(week)) + (d.week_target_tss != null ? ' / ' + esc(String(d.week_target_tss)) : '') + '</p>' +
      '<p><strong>CTL</strong> ' + esc(String(ctl)) + ' (after replay)</p>' +
      dual +
      '</div>'
    );
  }

  function renderFormMode() {
    var data;
    try { data = JSON.parse(state.jsonText); } catch (e) { return '<p class="rv-section-state">Fix JSON to use form mode.</p>'; }
    if (!Array.isArray(data)) return '<p class="rv-section-state">Root must be an array.</p>';
    var parts = ['<div class="rv-form-exercises">'];
    data.forEach(function (ex, ei) {
      parts.push('<div class="rv-card rv-stack rv-form-exercise" data-ex="' + ei + '">');
      parts.push('<h4>' + esc(ex.name || 'Exercise') + '</h4>');
      (ex.sets || []).forEach(function (st, si) {
        parts.push('<div class="rv-row rv-form-set" data-ex="' + ei + '" data-set="' + si + '">');
        if (st.kg != null) parts.push('<label>kg <input type="number" data-field="kg" value="' + esc(String(st.kg)) + '"></label>');
        if (st.reps != null) parts.push('<label>reps <input type="text" data-field="reps" value="' + esc(String(st.reps)) + '"></label>');
        if (st.hold != null) parts.push('<label>hold <input type="text" data-field="hold" value="' + esc(String(st.hold)) + '"></label>');
        if (st.time != null) parts.push('<label>time <input type="text" data-field="time" value="' + esc(String(st.time)) + '"></label>');
        parts.push('</div>');
      });
      parts.push('</div>');
    });
    parts.push('</div>');
    return parts.join('');
  }

  function bindFormInputs(root) {
    root.querySelectorAll('.rv-form-set input').forEach(function (inp) {
      inp.addEventListener('change', function () {
        var data = JSON.parse(state.jsonText);
        var ex = parseInt(inp.closest('.rv-form-set').getAttribute('data-ex'), 10);
        var si = parseInt(inp.closest('.rv-form-set').getAttribute('data-set'), 10);
        var field = inp.getAttribute('data-field');
        var val = inp.value;
        if (field === 'kg') val = parseFloat(val);
        data[ex].sets[si][field] = val;
        state.jsonText = JSON.stringify(data, null, 2);
        dirty = true;
        scheduleValidate();
      });
    });
  }

  function renderView() {
    var w = state.workout;
  if (!w) return '';
    var custom = (state.resolutions.length ? state.resolutions : []).filter(function (r) { return r.custom; });
    var rows = (w.strength_tss_per_exercise || []).map(function (row) {
      var res = (state.resolutions || []).find(function (r) { return r.name === row.name; }) || {};
      var match = res.custom ? 'Custom (×1.0)' : ((res.library_name || row.name) + ' ×' + (row.multiplier != null ? row.multiplier : '1'));
      return '<tr><td>' + esc(row.name) + '</td><td>' + esc(match) + '</td><td>' + esc(String(row.set_count)) + '</td><td>' + esc(String(row.tss)) + '</td></tr>';
    }).join('');
    var hist = state.versions.map(function (v) {
      return '<li>' + esc(v.saved_at || '') + ' — ' + esc(v.summary_line || '') + ' (TSS ' + esc(String(v.tss)) + ')</li>';
    }).join('');
    return (
      '<header class="rv-drawer-head"><h2 id="v2-drawer-title">' + esc(w.name) + '</h2>' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="v2-str-close">Close</button></header>' +
      '<div class="rv-strength-tiles rv-row">' +
      '<span>TSS <strong>' + esc(String(w.tss != null ? w.tss : '—')) + '</strong></span>' +
      '<span>Duration <strong>' + esc(fmtDur(w.duration_seconds)) + '</strong></span>' +
      '<span>Effort <strong>' + esc(String(w.session_effort != null ? w.session_effort : '—')) + '</strong></span>' +
      '</div>' +
      (w.recompute_pending ? '<p class="rv-hint rv-hint--pending">Fitness replay pending…</p>' : '') +
      (custom.length ? '<p class="rv-hint rv-hint--amber">Custom exercises count at 1.0 until an admin maps them.</p>' : '') +
      '<table class="rv-table"><thead><tr><th>Exercise</th><th>Matched</th><th>Sets</th><th>TSS</th></tr></thead><tbody>' + rows +
      '<tr><td colspan="3"><strong>Total</strong></td><td><strong>' + esc(String(w.tss != null ? w.tss : '—')) + '</strong></td></tr></tbody></table>' +
      (w.remarks ? '<p class="rv-notes">' + esc(w.remarks) + '</p>' : '') +
      '<details class="rv-card"><summary>History</summary><ul>' + (hist || '<li>No versions yet</li>') + '</ul></details>' +
      '<footer class="rv-drawer-foot"><button type="button" class="rv-btn rv-btn--primary" id="v2-str-edit">Edit</button></footer>'
    );
  }

  function renderEdit() {
    var w = state.workout || {};
    var editorMode = loadMode();
    var customLine = state.resolutions.filter(function (r) { return r.custom; }).map(function (r) {
      return r.name + ' <span class="rv-badge rv-badge--custom">CUSTOM</span>';
    }).join(', ');
    return (
      '<header class="rv-drawer-head"><h2 id="v2-drawer-title">' + esc(w.name || 'New strength session') + '</h2>' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="v2-str-close">Close</button></header>' +
      renderTssPanel() +
      '<div class="rv-card rv-stack">' +
      '<div class="rv-row"><label>Name <input id="v2-str-name" value="' + esc(w.name || 'Strength session') + '"></label></div>' +
      '<div class="rv-row"><label>Date <input type="date" id="v2-str-date" value="' + esc(w.workout_date || '') + '"></label>' +
      '<label>Duration (min) <input type="number" id="v2-str-dur" value="' + esc(String(w.duration_seconds ? Math.round(w.duration_seconds / 60) : 52)) + '"></label></div>' +
      '<div class="rv-effort-row" id="v2-str-effort"></div>' +
      '</div>' +
      '<div class="rv-card rv-stack">' +
      '<div class="rv-row" style="justify-content:space-between">' +
      '<span>Exercises</span>' +
      '<div class="rv-row"><button type="button" class="rv-btn rv-btn--secondary' + (editorMode === 'json' ? ' is-active' : '') + '" data-mode="json">JSON</button>' +
      '<button type="button" class="rv-btn rv-btn--secondary' + (editorMode === 'form' ? ' is-active' : '') + '" data-mode="form">Form</button></div></div>' +
      (editorMode === 'json'
        ? '<textarea id="v2-str-json" class="rv-json-editor" rows="14" spellcheck="false">' + esc(state.jsonText) + '</textarea>'
        : renderFormMode()) +
      '<p class="rv-hint" id="v2-str-status">' + (state.valid ? 'Valid' : 'Invalid') + '</p>' +
      (state.errors[0] ? '<p class="rv-section-state" role="alert">' + esc(state.errors[0].message) + ' (line ' + esc(String(state.errors[0].line)) + ')</p>' : '') +
      (customLine ? '<p class="rv-hint rv-hint--amber">' + customLine + '</p>' : '') +
      '<div class="rv-row"><input id="v2-str-lib-q" placeholder="Add from library…" style="flex:1">' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="v2-str-format">Format</button></div>' +
      '</div>' +
      '<label>Notes <textarea id="v2-str-notes" rows="2">' + esc(w.remarks || '') + '</textarea></label>' +
      '<footer class="rv-drawer-foot">' +
      '<button type="button" class="rv-btn rv-btn--primary" id="v2-str-save"' + (state.valid ? '' : ' disabled') + '>Save</button>' +
      (w.id ? '<button type="button" class="rv-btn rv-btn--danger" id="v2-str-del">Delete</button>' : '') +
      '</footer>'
    );
  }

  function render() {
    var e = els();
    if (!e.body) return;
    e.body.innerHTML = state.viewOnly ? renderView() : renderEdit();
    e.body.querySelector('#v2-str-close').onclick = close;
    if (state.viewOnly) {
      var editBtn = e.body.querySelector('#v2-str-edit');
      if (editBtn) editBtn.onclick = function () { state.viewOnly = false; render(); bindEdit(); };
      return;
    }
    bindEdit();
  }

  function bindEdit() {
    var e = els();
    var ta = e.body.querySelector('#v2-str-json');
    if (ta) {
      ta.addEventListener('input', function () {
        state.jsonText = ta.value;
        dirty = true;
        scheduleValidate();
      });
    }
    e.body.querySelectorAll('[data-mode]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        saveMode(btn.getAttribute('data-mode'));
        render();
        bindEdit();
      });
    });
    bindFormInputs(e.body);
    var fmt = e.body.querySelector('#v2-str-format');
    if (fmt) fmt.onclick = function () { scheduleValidate(); };
    var libQ = e.body.querySelector('#v2-str-lib-q');
    if (libQ) {
      libQ.addEventListener('keydown', function (ev) {
        if (ev.key !== 'Enter') return;
        var q = libQ.value.trim();
        if (!q) return;
        fetch('/api/exercises/library-search?q=' + encodeURIComponent(q), { credentials: 'include' })
          .then(function (r) { return r.json(); })
          .then(function (rows) {
            if (!rows.length) return;
            var block = rows[0];
            var data = [];
            try { data = JSON.parse(state.jsonText); } catch (err) { data = []; }
            data.push({ name: block.name, sets: 3, reps: 10, kg: 20 });
            state.jsonText = JSON.stringify(data, null, 2);
            dirty = true;
            libQ.value = '';
            scheduleValidate();
          });
      });
    }
    var effortHost = e.body.querySelector('#v2-str-effort');
    if (effortHost) {
      effortHost.innerHTML = '';
      effortHost.setAttribute('aria-label', 'Session effort');
      var cur = state.workout && state.workout.session_effort ? state.workout.session_effort : 7;
      for (var n = 1; n <= 10; n++) {
        var eb = document.createElement('button');
        eb.type = 'button';
        eb.className = 'rv-btn rv-btn--secondary rv-effort-btn' + (n === cur ? ' is-active' : '');
        eb.textContent = String(n);
        eb.setAttribute('data-effort', String(n));
        eb.addEventListener('click', function (ev) {
          var val = parseInt(ev.target.getAttribute('data-effort'), 10);
          if (!state.workout) state.workout = {};
          state.workout.session_effort = val;
          dirty = true;
          scheduleValidate();
        });
        effortHost.appendChild(eb);
      }
    }
    var save = e.body.querySelector('#v2-str-save');
    if (save) save.onclick = saveWorkout;
    var del = e.body.querySelector('#v2-str-del');
    if (del) del.onclick = deleteWorkout;
  }

  function patchBody() {
    var durMin = parseInt(document.getElementById('v2-str-dur').value, 10) || 0;
    var body = {
      name: document.getElementById('v2-str-name').value.trim(),
      duration_seconds: durMin * 60,
      session_effort: state.workout.session_effort,
      remarks: document.getElementById('v2-str-notes').value,
      exercises_json: JSON.parse(state.jsonText),
    };
    return body;
  }

  function saveWorkout() {
    if (!state.valid) return;
    var isNew = !state.workout || !state.workout.id;
    if (isNew) {
      var dateEl = document.getElementById('v2-str-date');
      var postBody = patchBody();
      postBody.workout_date = dateEl ? dateEl.value : state.workout.workout_date;
      postBody.workout_type = 'strength';
      return fetch('/api/workouts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'include',
        body: JSON.stringify(postBody),
      }).then(function (r) {
        if (!r.ok) throw new Error('Save failed');
        return r.json();
      }).then(function (w) {
        dirty = false;
        toast('Session saved');
        close();
        if (global.V2TrainingLogReload) global.V2TrainingLogReload();
        openView(w.id);
      }).catch(function () { toast('Save failed'); });
    }
    return fetch('/api/workouts/' + state.workout.id, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify(patchBody()),
    }).then(function (r) {
      if (!r.ok) throw new Error('Save failed');
      return r.json();
    }).then(function (w) {
      dirty = false;
      toast('Saved');
      state.workout = w;
      state.savedJson = JSON.stringify(w.exercises_json || JSON.parse(state.jsonText), null, 2);
      if (global.V2TrainingLogReload) global.V2TrainingLogReload();
      openView(w.id);
    }).catch(function () { toast('Save failed'); });
  }

  function deleteWorkout() {
    if (!state.workout || !state.workout.id) return;
    if (!confirm('Delete this session?')) return;
    fetch('/api/workouts/' + state.workout.id, { method: 'DELETE', credentials: 'include' }).then(function () {
      close();
      if (global.V2TrainingLogReload) global.V2TrainingLogReload();
    });
  }

  function loadWorkout(id) {
    return fetch('/api/workouts/' + id, { credentials: 'include' }).then(function (r) { return r.json(); });
  }

  function loadVersions(id) {
    return fetch('/api/workouts/' + id + '/session-versions', { credentials: 'include' })
      .then(function (r) { return r.ok ? r.json() : { versions: [] }; })
      .then(function (p) { state.versions = p.versions || []; });
  }

  function openView(id) {
    state.viewOnly = true;
    state.mode = 'view';
    loadWorkout(id).then(function (w) {
      state.workout = w;
      state.resolutions = w.strength_tss_per_exercise ? w.strength_tss_per_exercise.map(function (r) {
        return { name: r.name, custom: r.multiplier === 1 && !r.library_name };
      }) : [];
      return loadVersions(id);
    }).then(function () {
      var e = els();
      if (e.backdrop) { e.backdrop.hidden = false; e.backdrop.classList.add('is-open'); }
      if (e.drawer) { e.drawer.hidden = false; e.drawer.classList.add('is-open'); }
      document.addEventListener('keydown', onKey);
      render();
    });
  }

  function openEdit(idOrNull, defaults) {
    state.viewOnly = false;
    state.mode = 'edit';
    dirty = false;
    var chain = idOrNull
      ? loadWorkout(idOrNull).then(function (w) {
        state.workout = w;
        state.jsonText = w.exercises_json
          ? JSON.stringify(w.exercises_json, null, 2)
          : (w.exercises && w.exercises.length ? '[]' : '[{"name":"Goblet squat","sets":3,"reps":10,"kg":24}]');
        state.savedJson = state.jsonText;
        return runValidate();
      })
      : Promise.resolve().then(function () {
        state.workout = defaults || { name: 'Strength session', workout_date: global.AppCommon.todayISO(), session_effort: 7, duration_seconds: 52 * 60 };
        state.jsonText = '[{"name":"Goblet squat","sets":3,"reps":10,"kg":24}]';
        return runValidate();
      });
    chain.then(function () {
      var e = els();
      if (e.backdrop) { e.backdrop.hidden = false; e.backdrop.classList.add('is-open'); }
      if (e.drawer) { e.drawer.hidden = false; e.drawer.classList.add('is-open'); }
      document.addEventListener('keydown', onKey);
      render();
    });
  }

  global.V2StrengthDrawer = {
    openView: openView,
    openEdit: openEdit,
    close: close,
    isStrengthType: function (t) {
      t = (t || '').toLowerCase();
      return t.indexOf('strength') >= 0 || t.indexOf('lift') >= 0 || t.indexOf('plyo') >= 0 || t.indexOf('mobility') >= 0;
    },
  };
})(window);