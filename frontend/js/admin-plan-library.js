/* Admin plan library — exercises + patterns (/admin/plan-library) */
(function () {
  'use strict';

  // CSRF for standalone admin page (same as admin.html)
  if (!window._csrfFetchPatched) {
    window._csrfFetchPatched = true;
    var _origFetch = window.fetch.bind(window);
    window.fetch = function (url, opts) {
      opts = opts || {};
      var method = (opts.method || 'GET').toUpperCase();
      if (method === 'POST' || method === 'PATCH' || method === 'DELETE' || method === 'PUT') {
        var match = document.cookie.match(/(?:^|;\s*)csrf-token=([^;]*)/);
        if (match) {
          var headers = opts.headers || {};
          if (headers instanceof Headers) {
            headers = new Headers(headers);
            headers.set('X-CSRF-Token', decodeURIComponent(match[1]));
          } else {
            headers = Object.assign({}, headers, { 'X-CSRF-Token': decodeURIComponent(match[1]) });
          }
          opts = Object.assign({}, opts, { headers: headers });
        }
      }
      return _origFetch(url, opts);
    };
  }

  var GROUPS = [
    'warmup', 'heavy_compound', 'superset', 'standalone', 'accessories',
    'cooldown', 'bodyweight', 'plyo', 'isometric',
  ];
  var FOCUS = ['lower', 'upper', 'full', 'core'];
  var BODY_PARTS = [
    'quad', 'glute', 'hamstring', 'calf', 'hip', 'hip_flexor',
    'chest', 'shoulder', 'upper_back', 'lower_back', 'trapezius',
    'biceps', 'triceps', 'core', 'oblique', 'grip',
  ];
  var RUN_PHASES = ['warmup', 'main', 'cooldown', 'mp'];
  var PAT_KINDS = ['run', 'strength'];

  var _tab = 'exercises';
  var _exercisesLoaded = false;
  var _patternsLoaded = false;

  // ── Exercises state ────────────────────────────────────────────────────────
  var _all = [];
  var _selectedId = null;
  var _filterGroup = '';
  var _filterFocus = '';

  // ── Patterns state ─────────────────────────────────────────────────────────
  var _patterns = [];
  var _patSelectedId = null;
  var _patFilterKind = '';
  var _patUseRawRecipe = false;

  function esc(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function api(path, opts) {
    opts = opts || {};
    opts.headers = Object.assign({ Accept: 'application/json' }, opts.headers || {});
    return fetch(path, opts).then(function (r) {
      if (r.status === 204) return { ok: r.ok, status: r.status, data: null };
      return r.json().then(function (d) {
        return { ok: r.ok, status: r.status, data: d };
      }).catch(function () {
        return { ok: r.ok, status: r.status, data: null };
      });
    });
  }

  // ── Tabs ───────────────────────────────────────────────────────────────────

  function tabFromUrl() {
    var hash = (location.hash || '').replace(/^#/, '');
    if (hash === 'patterns' || hash === 'exercises' || hash === 'preview') return hash;
    var params = new URLSearchParams(location.search);
    var t = params.get('tab');
    if (t === 'patterns' || t === 'exercises' || t === 'preview') return t;
    return 'exercises';
  }

  function updateUrlTab(tab) {
    var url = new URL(location.href);
    url.searchParams.set('tab', tab);
    url.hash = tab;
    history.replaceState(null, '', url.pathname + url.search);
  }

  function setTab(tab) {
    if (tab !== 'patterns' && tab !== 'preview') tab = 'exercises';
    _tab = tab;
    ['exercises', 'patterns', 'preview'].forEach(function (name) {
      var on = _tab === name;
      var btn = document.getElementById('tab-' + name);
      var panel = document.getElementById('panel-' + name);
      if (btn) {
        btn.classList.toggle('on', on);
        btn.setAttribute('aria-selected', on ? 'true' : 'false');
      }
      if (panel) panel.hidden = !on;
    });
    var btnNew = document.getElementById('btn-new');
    if (_tab === 'preview') {
      btnNew.hidden = true;
    } else {
      btnNew.hidden = false;
      btnNew.innerHTML = _tab === 'patterns'
        ? '<i class="ti ti-plus" aria-hidden="true"></i> New pattern'
        : '<i class="ti ti-plus" aria-hidden="true"></i> New exercise';
    }
    updateUrlTab(_tab);
    if (_tab === 'patterns' && !_patternsLoaded) loadPatterns();
    if (_tab === 'exercises' && !_exercisesLoaded) loadExercises();
    if (_tab === 'preview' && !_patternsLoaded) loadPatterns();
  }

  // ── Exercise helpers ───────────────────────────────────────────────────────

  function fb(msg, ok) {
    var el = document.getElementById('feedback');
    if (!msg) {
      el.className = 'fb';
      el.textContent = '';
      return;
    }
    el.className = 'fb ' + (ok ? 'ok' : 'err');
    el.textContent = msg;
  }

  function selectedChips(containerId) {
    var out = [];
    document.querySelectorAll('#' + containerId + ' .chip.on').forEach(function (c) {
      out.push(c.getAttribute('data-val'));
    });
    return out;
  }

  function renderToggleChips(containerId, values, selected) {
    var el = document.getElementById(containerId);
    var set = {};
    (selected || []).forEach(function (v) { set[v] = true; });
    el.innerHTML = values.map(function (v) {
      return '<button type="button" class="chip toggle' + (set[v] ? ' on' : '') +
        '" data-val="' + esc(v) + '">' + esc(v) + '</button>';
    }).join('');
    el.querySelectorAll('.chip').forEach(function (btn) {
      btn.addEventListener('click', function () { btn.classList.toggle('on'); });
    });
  }

  function renderFilterChips(containerId, values, current, onPick) {
    var el = document.getElementById(containerId);
    el.innerHTML =
      '<button type="button" class="chip' + (!current ? ' on' : '') + '" data-val="">all</button>' +
      values.map(function (v) {
        return '<button type="button" class="chip' + (current === v ? ' on' : '') +
          '" data-val="' + esc(v) + '">' + esc(v) + '</button>';
      }).join('');
    el.querySelectorAll('.chip').forEach(function (btn) {
      btn.addEventListener('click', function () {
        onPick(btn.getAttribute('data-val') || '');
      });
    });
  }

  function readParts() {
    var rows = [];
    document.querySelectorAll('#body-parts .part-row').forEach(function (row) {
      var part = row.querySelector('[data-f="part"]').value.trim();
      var ratio = parseFloat(row.querySelector('[data-f="ratio"]').value);
      if (!part) return;
      if (!isFinite(ratio) || ratio <= 0) ratio = 0;
      rows.push({ part: part, ratio: Math.round(ratio * 100) / 100 });
    });
    return rows;
  }

  function updatePartsSum() {
    var sum = 0;
    readParts().forEach(function (p) { sum += p.ratio; });
    var el = document.getElementById('parts-sum');
    el.textContent = 'Ratios sum: ' + sum.toFixed(2) + (Math.abs(sum - 1) > 0.05 && sum > 0 ? ' (aim ~1.0)' : '');
    el.className = 'part-sum' + (Math.abs(sum - 1) > 0.05 && sum > 0 ? ' warn' : '');
  }

  function addPartRow(part, ratio) {
    var wrap = document.getElementById('body-parts');
    var row = document.createElement('div');
    row.className = 'part-row';
    var opts = BODY_PARTS.map(function (p) {
      return '<option value="' + esc(p) + '"' + (p === part ? ' selected' : '') + '>' + esc(p) + '</option>';
    }).join('');
    if (part && BODY_PARTS.indexOf(part) === -1) {
      opts = '<option value="' + esc(part) + '" selected>' + esc(part) + '</option>' + opts;
    }
    row.innerHTML =
      '<select data-f="part">' + opts + '</select>' +
      '<input data-f="ratio" type="number" min="0" max="1" step="0.05" value="' +
        esc(ratio != null ? ratio : 0.5) + '" title="Ratio 0–1">' +
      '<button type="button" class="btn part-rm" title="Remove">✕</button>';
    wrap.appendChild(row);
    row.querySelector('.part-rm').onclick = function () {
      row.remove();
      updatePartsSum();
    };
    row.querySelector('[data-f="ratio"]').oninput = updatePartsSum;
    updatePartsSum();
  }

  function setParts(parts) {
    document.getElementById('body-parts').innerHTML = '';
    (parts || []).forEach(function (p) {
      if (!p || typeof p !== 'object') return;
      addPartRow(p.part || '', p.ratio != null ? p.ratio : 0.5);
    });
    if (!(parts || []).length) updatePartsSum();
  }

  function blankExercise() {
    return {
      id: '',
      name: '',
      groups: ['standalone'],
      focus_tags: ['full'],
      body_parts: [],
      tss_weight: 1,
      default_sets: 3,
      default_reps: '10',
      default_load: 'moderate',
      active: true,
    };
  }

  function fillExerciseForm(e) {
    e = e || blankExercise();
    _selectedId = e.id || null;
    document.getElementById('edit-id').value = e.id || '';
    document.getElementById('edit-name').value = e.name || '';
    document.getElementById('edit-sets').value = e.default_sets != null ? e.default_sets : '';
    document.getElementById('edit-reps').value = e.default_reps || '';
    document.getElementById('edit-load').value = e.default_load || '';
    document.getElementById('edit-tss').value = e.tss_weight != null ? e.tss_weight : 1;
    document.getElementById('edit-active').checked = e.active !== false;
    document.getElementById('editor-title').textContent = e.id ? 'Edit exercise' : 'New exercise';
    renderToggleChips('edit-groups', GROUPS, e.groups || []);
    renderToggleChips('edit-focus', FOCUS, e.focus_tags || []);
    setParts(e.body_parts || []);
    fb('', true);
    renderExerciseList();
  }

  function filteredExercises() {
    var q = (document.getElementById('search').value || '').trim().toLowerCase();
    var hideOff = document.getElementById('hide-inactive').checked;
    return _all.filter(function (e) {
      if (hideOff && !e.active) return false;
      if (_filterGroup && (e.groups || []).indexOf(_filterGroup) === -1) return false;
      if (_filterFocus && (e.focus_tags || []).indexOf(_filterFocus) === -1) return false;
      if (q && String(e.name || '').toLowerCase().indexOf(q) === -1) return false;
      return true;
    });
  }

  function renderExerciseList() {
    var rows = filteredExercises();
    document.getElementById('list-count').textContent =
      rows.length + ' of ' + _all.length + ' exercise' + (_all.length === 1 ? '' : 's');
    var list = document.getElementById('ex-list');
    if (!rows.length) {
      list.innerHTML = '<div class="ex-empty">No exercises match these filters.</div>';
      return;
    }
    list.innerHTML = rows.map(function (e) {
      var meta = [
        (e.groups || []).join(', ') || '—',
        (e.focus_tags || []).join(', ') || '—',
        [e.default_sets, e.default_reps].filter(Boolean).join('×') || '',
        e.default_load || '',
      ].filter(Boolean).join(' · ');
      return '<button type="button" class="ex-row' +
        (e.id === _selectedId ? ' selected' : '') +
        (e.active ? '' : ' off') +
        '" data-id="' + esc(e.id) + '">' +
        '<div class="ex-name">' + esc(e.name) + (e.active ? '' : ' (inactive)') + '</div>' +
        '<div class="ex-meta">' + esc(meta) + '</div>' +
      '</button>';
    }).join('');
    list.querySelectorAll('.ex-row').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-id');
        var row = _all.find(function (x) { return x.id === id; });
        if (row) fillExerciseForm(row);
      });
    });
  }

  function loadExercises() {
    return api('/api/admin/plan-exercises').then(function (res) {
      if (res.status === 401) {
        window.location.href = '/admin';
        return;
      }
      if (!res.ok) {
        fb((res.data && res.data.detail) || 'Failed to load exercises', false);
        return;
      }
      _exercisesLoaded = true;
      _all = (res.data && res.data.exercises) || [];
      refreshExerciseFilters();
      renderExerciseList();
      if (_selectedId) {
        var still = _all.find(function (x) { return x.id === _selectedId; });
        if (still) fillExerciseForm(still);
      }
    });
  }

  function refreshExerciseFilters() {
    renderFilterChips('filter-groups', GROUPS, _filterGroup, function (v) {
      _filterGroup = v;
      refreshExerciseFilters();
      renderExerciseList();
    });
    renderFilterChips('filter-focus', FOCUS, _filterFocus, function (v) {
      _filterFocus = v;
      refreshExerciseFilters();
      renderExerciseList();
    });
  }

  function collectExerciseBody() {
    var name = document.getElementById('edit-name').value.trim();
    if (!name) {
      fb('Name is required', false);
      return null;
    }
    var sets = document.getElementById('edit-sets').value;
    return {
      name: name,
      groups: selectedChips('edit-groups'),
      focus_tags: selectedChips('edit-focus'),
      body_parts: readParts(),
      tss_weight: parseFloat(document.getElementById('edit-tss').value) || 1,
      default_sets: sets === '' ? null : parseInt(sets, 10),
      default_reps: document.getElementById('edit-reps').value.trim() || null,
      default_load: document.getElementById('edit-load').value.trim() || null,
      active: document.getElementById('edit-active').checked,
    };
  }

  function saveExercise() {
    var body = collectExerciseBody();
    if (!body) return;
    var id = document.getElementById('edit-id').value.trim();
    var method = id ? 'PATCH' : 'POST';
    var url = id ? ('/api/admin/plan-exercises/' + id) : '/api/admin/plan-exercises';
    api(url, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (res) {
      if (!res.ok) {
        fb((res.data && res.data.detail) || 'Save failed', false);
        return;
      }
      fb('Saved', true);
      fillExerciseForm(res.data);
      loadExercises();
    }).catch(function () { fb('Save failed', false); });
  }

  function removeExercise() {
    var id = document.getElementById('edit-id').value.trim();
    if (!id) return;
    if (!confirm('Delete this exercise from the pool?')) return;
    api('/api/admin/plan-exercises/' + id, { method: 'DELETE' }).then(function (res) {
      if (!res.ok) {
        fb('Delete failed', false);
        return;
      }
      fb('Deleted', true);
      _selectedId = null;
      fillExerciseForm(blankExercise());
      loadExercises();
    });
  }

  function duplicateExercise() {
    var body = collectExerciseBody();
    if (!body) return;
    body.name = body.name + ' (copy)';
    document.getElementById('edit-id').value = '';
    _selectedId = null;
    document.getElementById('edit-name').value = body.name;
    document.getElementById('editor-title').textContent = 'New exercise';
    fb('Duplicated — edit the name and Save', true);
  }

  function formatFillStep(step) {
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
      return op + ': "' + (step.name || '') + '" [' +
        (band[0] != null ? band[0] : '?') + '–' +
        (band[1] != null ? band[1] : '?') + ' min]';
    }
    if (op === 'fill_strength') {
      var head = op + ' · ' + (step.exercise_count || 0) + ' exercises' +
        (step.blocks && step.blocks.length ? ' · ' + step.blocks.join(', ') : '');
      var groups = (step.groups || []).map(function (g) {
        var scale = (g.base_n != null && g.scaled_n != null && g.base_n !== g.scaled_n)
          ? (' n ' + g.base_n + '→' + g.scaled_n)
          : (' n=' + g.n);
        var allot = g.allot_min != null ? (' · ' + g.allot_min + 'm budget') : '';
        var skipped = g.skipped ? ' [skipped]' : '';
        return '  ' + (g.label || '') + ' ← [' + (g.from_tags || []).join(', ') +
          ']' + scale + allot + skipped + ': ' + (g.picked || []).join(', ');
      }).join('\n');
      return groups ? head + '\n' + groups : head;
    }
    if (op === 'validate') {
      if (step.ok) return op + ': ok';
      return op + ': FAILED' +
        ((step.errors && step.errors.length) ? '\n  ' + step.errors.join('\n  ') : '');
    }
    if (op === 'fallback' || op === 'template') {
      return op + (step.to ? ' → ' + step.to : '') +
        (step.reason ? ' (' + step.reason + ')' : '');
    }
    try { return op + ': ' + JSON.stringify(step); }
    catch (e) { return op; }
  }

  function fillLogHtml(log, meta) {
    if (!log || !log.steps || !log.steps.length) return '';
    var lines = log.steps.map(formatFillStep).join('\n');
    var bits = [];
    if (meta && meta.pattern_name) bits.push(meta.pattern_name);
    if (meta && meta.source) bits.push(meta.source);
    if (meta && meta.duration_minutes) bits.push(meta.duration_minutes + ' min');
    return '<details class="fill-log" open>' +
      '<summary>Fill log' + (bits.length ? ' · ' + esc(bits.join(' · ')) : '') + '</summary>' +
      '<pre class="fill-log-pre">' + esc(lines) + '</pre></details>';
  }

  function previewFill() {
    var out = document.getElementById('preview-out');
    var subtype = document.getElementById('preview-subtype').value;
    var minutes = parseInt(document.getElementById('preview-dur').value, 10) || 45;
    var isStrength = subtype.indexOf('strength') === 0;

    if (!isStrength) {
      previewRunSubtype(subtype, minutes, out);
      return;
    }

    out.innerHTML = '<span class="muted">Filling…</span>';
    api('/api/admin/plan-exercises/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        subtype: subtype,
        duration_minutes: minutes,
        target_tss: 40,
      }),
    }).then(function (res) {
      if (!res.ok) {
        out.innerHTML = '<span class="muted">' + esc((res.data && res.data.detail) || 'Preview failed') + '</span>';
        return;
      }
      var d = res.data || {};
      var exs = d.exercises || [];
      var html = '<div class="intent">' + esc(d.intent || 'Session') +
        ' <span class="muted">· ' + esc(d.pattern_name || d.source || '') +
        ' · ' + (d.duration_minutes || minutes) + ' min</span></div>';
      if (d.notes) html += '<div class="muted" style="margin-bottom:8px;">' + esc(d.notes) + '</div>';
      if (!exs.length) {
        html += '<div class="muted">No exercises returned — check group tags on the pool.</div>';
      } else {
        html += exs.map(function (x) {
          var sr = (x.sets != null && x.reps != null) ? (x.sets + ' × ' + x.reps) : '';
          return '<div class="preview-ex"><span>' + esc(x.name || '') +
            '</span><span class="muted">' + esc(x.block || '') + '</span><span>' +
            esc(sr + (x.load ? ' · ' + x.load : '')) + '</span></div>';
        }).join('');
      }
      html += fillLogHtml(d.fill_log, {
        pattern_name: d.pattern_name,
        source: d.source,
        duration_minutes: d.duration_minutes || minutes,
      });
      out.innerHTML = html;
    }).catch(function () {
      out.innerHTML = '<span class="muted">Preview failed</span>';
    });
  }

  function previewRunSubtype(subtype, minutes, out) {
    var pat = null;
    (_patterns || []).forEach(function (p) {
      if (!p.active) return;
      if (p.kind !== 'run') return;
      if (p.subtype !== subtype) return;
      var lo = p.duration_min_lo != null ? p.duration_min_lo : 0;
      var hi = p.duration_min_hi != null ? p.duration_min_hi : 999;
      if (minutes < lo || minutes > hi) return;
      if (!pat || (p.priority || 0) >= (pat.priority || 0)) pat = p;
    });
    if (!pat) {
      out.innerHTML = '<span class="muted">No active run pattern for ' + esc(subtype) +
        ' at ' + minutes + ' min. Seed defaults or widen a pattern’s duration band.</span>';
      return;
    }
    var recipe = pat.recipe || {};
    var blocks = recipe.blocks || [];
    if (!blocks.length) {
      out.innerHTML = '<span class="muted">Pattern "' + esc(pat.name) + '" has no blocks.</span>';
      return;
    }
    var html = '<div class="intent">' + esc(recipe.intent_template || pat.name) +
      ' <span class="muted">· ' + esc(pat.name) + ' (client scaled)</span></div>';
    html += blocks.map(function (b) {
      var mins = Math.max(1, Math.round((b.duration_share || 0) * minutes));
      var detail = b.target || '';
      if (b.repeat) detail = (detail ? detail + ' · ' : '') + b.repeat + '×';
      if (b.rest_min) detail = (detail ? detail + ' · ' : '') + b.rest_min + ' min rest';
      return '<div class="preview-block"><span>' + esc(b.phase || 'block') + '</span><span>' +
        mins + ' min</span><span class="muted">' + esc(detail) + '</span></div>';
    }).join('');
    out.innerHTML = html;
  }

  // ── Pattern helpers ────────────────────────────────────────────────────────

  function patFb(msg, ok) {
    var el = document.getElementById('pat-feedback');
    if (!msg) {
      el.className = 'fb';
      el.textContent = '';
      return;
    }
    el.className = 'fb ' + (ok ? 'ok' : 'err');
    el.textContent = msg;
  }

  function numOrNull(v) {
    if (v === '' || v == null) return null;
    var n = parseFloat(v);
    return isFinite(n) ? n : null;
  }

  function intOrNull(v) {
    if (v === '' || v == null) return null;
    var n = parseInt(v, 10);
    return isFinite(n) ? n : null;
  }

  function parseTags(text) {
    return String(text || '')
      .split(/[,;]+/)
      .map(function (s) { return s.trim(); })
      .filter(Boolean);
  }

  function toggleKindRecipeUI() {
    var kind = document.getElementById('pat-edit-kind').value;
    document.getElementById('recipe-run').hidden = kind !== 'run';
    document.getElementById('recipe-strength').hidden = kind !== 'strength';
  }

  function runPhaseOptions(selected) {
    return RUN_PHASES.map(function (p) {
      return '<option value="' + esc(p) + '"' + (p === selected ? ' selected' : '') + '>' + esc(p) + '</option>';
    }).join('');
  }

  function groupKeyOptions(selected) {
    return GROUPS.map(function (g) {
      return '<option value="' + esc(g) + '"' + (g === selected ? ' selected' : '') + '>' + esc(g) + '</option>';
    }).join('');
  }

  function addRunBlockRow(block) {
    block = block || {};
    var wrap = document.getElementById('run-blocks');
    var row = document.createElement('div');
    row.className = 'run-block-row';
    row.innerHTML =
      '<select data-f="phase">' + runPhaseOptions(block.phase || 'main') + '</select>' +
      '<input data-f="duration_share" type="number" min="0" max="1" step="0.05" value="' +
        esc(block.duration_share != null ? block.duration_share : 0.2) + '">' +
      '<input data-f="repeat" type="number" min="0" step="1" placeholder="—" value="' +
        esc(block.repeat != null ? block.repeat : '') + '">' +
      '<input data-f="rest_min" type="number" min="0" step="1" placeholder="—" value="' +
        esc(block.rest_min != null ? block.rest_min : '') + '">' +
      '<input data-f="target" type="text" placeholder="easy / tempo…" value="' +
        esc(block.target || '') + '">' +
      '<button type="button" class="btn rm" title="Remove">✕</button>';
    wrap.appendChild(row);
    row.querySelector('.rm').onclick = function () { row.remove(); };
  }

  function setRunBlocks(blocks) {
    document.getElementById('run-blocks').innerHTML = '';
    (blocks || []).forEach(addRunBlockRow);
    if (!(blocks || []).length) addRunBlockRow({ phase: 'warmup', duration_share: 0.2 });
  }

  function readRunBlocks() {
    var out = [];
    document.querySelectorAll('#run-blocks .run-block-row').forEach(function (row) {
      out.push({
        phase: row.querySelector('[data-f="phase"]').value,
        duration_share: parseFloat(row.querySelector('[data-f="duration_share"]').value) || 0,
        repeat: intOrNull(row.querySelector('[data-f="repeat"]').value),
        rest_min: intOrNull(row.querySelector('[data-f="rest_min"]').value),
        target: row.querySelector('[data-f="target"]').value.trim() || null,
      });
    });
    return out;
  }

  function addStrengthGroupRow(group) {
    group = group || {};
    var pick = group.pick || {};
    var tags = pick.from_tags || [];
    var wrap = document.getElementById('strength-groups');
    var row = document.createElement('div');
    row.className = 'strength-group-row';
    row.innerHTML =
      '<select data-f="key">' + groupKeyOptions(group.key || 'standalone') + '</select>' +
      '<input data-f="label" type="text" placeholder="Block label" value="' + esc(group.label || '') + '">' +
      '<input data-f="time_share" type="number" min="0" max="1" step="0.01" value="' +
        esc(group.time_share != null ? group.time_share : 0.1) + '">' +
      '<input data-f="tss_share" type="number" min="0" max="1" step="0.01" value="' +
        esc(group.tss_share != null ? group.tss_share : 0.1) + '">' +
      '<input data-f="pick_n" type="number" min="1" max="6" step="1" value="' +
        esc(pick.n != null ? pick.n : 1) + '">' +
      '<input data-f="from_tags" type="text" placeholder="warmup, superset…" value="' +
        esc(tags.join(', ')) + '">' +
      '<button type="button" class="btn rm" title="Remove">✕</button>';
    wrap.appendChild(row);
    row.querySelector('.rm').onclick = function () { row.remove(); };
  }

  function setStrengthGroups(groups) {
    document.getElementById('strength-groups').innerHTML = '';
    (groups || []).forEach(addStrengthGroupRow);
    if (!(groups || []).length) addStrengthGroupRow({ key: 'warmup', label: 'Warm-up', time_share: 0.12, tss_share: 0.08, pick: { n: 2, from_tags: ['warmup'] } });
  }

  function readStrengthGroups() {
    var out = [];
    document.querySelectorAll('#strength-groups .strength-group-row').forEach(function (row) {
      out.push({
        key: row.querySelector('[data-f="key"]').value,
        label: row.querySelector('[data-f="label"]').value.trim() || null,
        time_share: parseFloat(row.querySelector('[data-f="time_share"]').value) || 0,
        tss_share: parseFloat(row.querySelector('[data-f="tss_share"]').value) || 0,
        pick: {
          n: parseInt(row.querySelector('[data-f="pick_n"]').value, 10) || 1,
          from_tags: parseTags(row.querySelector('[data-f="from_tags"]').value),
        },
      });
    });
    return out;
  }

  function buildRecipeFromForm() {
    var notes = document.getElementById('pat-notes').value.trim();
    var recipe = {
      intent_template: document.getElementById('pat-intent').value.trim() || '',
      notes_template: notes || null,
    };
    if (document.getElementById('pat-edit-kind').value === 'run') {
      recipe.blocks = readRunBlocks();
    } else {
      recipe.groups = readStrengthGroups();
      recipe.focus_bias = {
        primary_tag: document.getElementById('pat-focus-tag').value,
        primary: parseFloat(document.getElementById('pat-focus-primary').value) || 0.8,
        accessory: parseFloat(document.getElementById('pat-focus-accessory').value) || 0.2,
      };
    }
    return recipe;
  }

  function syncRawJsonFromForm() {
    document.getElementById('pat-raw-json').value = JSON.stringify(buildRecipeFromForm(), null, 2);
  }

  function fillRecipeEditors(recipe) {
    recipe = recipe || {};
    document.getElementById('pat-intent').value = recipe.intent_template || '';
    document.getElementById('pat-notes').value = recipe.notes_template || '';
    setRunBlocks(recipe.blocks || []);
    setStrengthGroups(recipe.groups || []);
    var bias = recipe.focus_bias || {};
    document.getElementById('pat-focus-tag').value = bias.primary_tag || 'full';
    document.getElementById('pat-focus-primary').value = bias.primary != null ? bias.primary : 0.8;
    document.getElementById('pat-focus-accessory').value = bias.accessory != null ? bias.accessory : 0.2;
    document.getElementById('pat-raw-json').value = JSON.stringify(recipe, null, 2);
    _patUseRawRecipe = false;
  }

  function blankPattern() {
    return {
      id: '',
      kind: 'run',
      subtype: '',
      duration_min_lo: 0,
      duration_min_hi: 120,
      name: '',
      priority: 10,
      recipe: {
        intent_template: '',
        notes_template: null,
        blocks: [
          { phase: 'warmup', duration_share: 0.15, repeat: null, rest_min: null, target: 'easy' },
          { phase: 'main', duration_share: 0.70, repeat: null, rest_min: null, target: 'easy' },
          { phase: 'cooldown', duration_share: 0.15, repeat: null, rest_min: null, target: 'easy' },
        ],
      },
      active: true,
    };
  }

  function fillPatternForm(p) {
    p = p || blankPattern();
    _patSelectedId = p.id || null;
    document.getElementById('pat-edit-id').value = p.id || '';
    document.getElementById('pat-edit-name').value = p.name || '';
    document.getElementById('pat-edit-kind').value = p.kind || 'run';
    document.getElementById('pat-edit-subtype').value = p.subtype || '';
    document.getElementById('pat-edit-lo').value = p.duration_min_lo != null ? p.duration_min_lo : 0;
    document.getElementById('pat-edit-hi').value = p.duration_min_hi != null ? p.duration_min_hi : 120;
    document.getElementById('pat-edit-pri').value = p.priority != null ? p.priority : 10;
    document.getElementById('pat-edit-active').checked = p.active !== false;
    document.getElementById('pat-editor-title').textContent = p.id ? 'Edit pattern' : 'New pattern';
    fillRecipeEditors(p.recipe || {});
    toggleKindRecipeUI();
    patFb('', true);
    renderPatternList();
  }

  function filteredPatterns() {
    var q = (document.getElementById('pat-search').value || '').trim().toLowerCase();
    var hideOff = document.getElementById('pat-hide-inactive').checked;
    return _patterns.filter(function (p) {
      if (hideOff && !p.active) return false;
      if (_patFilterKind && p.kind !== _patFilterKind) return false;
      if (q) {
        var hay = [p.name, p.subtype, p.kind].join(' ').toLowerCase();
        if (hay.indexOf(q) === -1) return false;
      }
      return true;
    });
  }

  function renderPatternList() {
    var rows = filteredPatterns();
    document.getElementById('pat-list-count').textContent =
      rows.length + ' of ' + _patterns.length + ' pattern' + (_patterns.length === 1 ? '' : 's');
    var list = document.getElementById('pat-list');
    if (!rows.length) {
      list.innerHTML = '<div class="ex-empty">No patterns match these filters.</div>';
      return;
    }
    list.innerHTML = rows.map(function (p) {
      var meta = [
        p.kind,
        p.subtype || '—',
        (p.duration_min_lo != null ? p.duration_min_lo : 0) + '–' + (p.duration_min_hi != null ? p.duration_min_hi : 120) + ' min',
        'pri ' + (p.priority != null ? p.priority : 10),
      ].join(' · ');
      return '<button type="button" class="ex-row' +
        (p.id === _patSelectedId ? ' selected' : '') +
        (p.active ? '' : ' off') +
        '" data-id="' + esc(p.id) + '">' +
        '<div class="ex-name">' + esc(p.name) + (p.active ? '' : ' (inactive)') + '</div>' +
        '<div class="ex-meta">' + esc(meta) + '</div>' +
      '</button>';
    }).join('');
    list.querySelectorAll('.ex-row').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-id');
        var row = _patterns.find(function (x) { return x.id === id; });
        if (row) fillPatternForm(row);
      });
    });
  }

  function refreshPatternFilters() {
    renderFilterChips('pat-filter-kind', PAT_KINDS, _patFilterKind, function (v) {
      _patFilterKind = v;
      refreshPatternFilters();
      renderPatternList();
    });
  }

  function loadPatterns() {
    return api('/api/admin/plan-patterns').then(function (res) {
      if (res.status === 401) {
        window.location.href = '/admin';
        return;
      }
      if (!res.ok) {
        patFb((res.data && res.data.detail) || 'Failed to load patterns', false);
        return;
      }
      _patternsLoaded = true;
      _patterns = (res.data && res.data.patterns) || [];
      refreshPatternFilters();
      renderPatternList();
      if (_patSelectedId) {
        var still = _patterns.find(function (x) { return x.id === _patSelectedId; });
        if (still) fillPatternForm(still);
      }
    });
  }

  function collectPatternBody() {
    var name = document.getElementById('pat-edit-name').value.trim();
    if (!name) {
      patFb('Name is required', false);
      return null;
    }
    var subtype = document.getElementById('pat-edit-subtype').value.trim();
    if (!subtype) {
      patFb('Subtype is required', false);
      return null;
    }
    var recipe;
    if (_patUseRawRecipe) {
      try {
        recipe = JSON.parse(document.getElementById('pat-raw-json').value || '{}');
      } catch (err) {
        patFb('Invalid raw recipe JSON', false);
        return null;
      }
    } else {
      recipe = buildRecipeFromForm();
      document.getElementById('pat-raw-json').value = JSON.stringify(recipe, null, 2);
    }
    return {
      kind: document.getElementById('pat-edit-kind').value,
      subtype: subtype,
      duration_min_lo: parseInt(document.getElementById('pat-edit-lo').value, 10) || 0,
      duration_min_hi: parseInt(document.getElementById('pat-edit-hi').value, 10) || 120,
      name: name,
      priority: parseInt(document.getElementById('pat-edit-pri').value, 10) || 10,
      recipe: recipe,
      active: document.getElementById('pat-edit-active').checked,
    };
  }

  function savePattern() {
    var body = collectPatternBody();
    if (!body) return;
    var id = document.getElementById('pat-edit-id').value.trim();
    var method = id ? 'PATCH' : 'POST';
    var url = id ? ('/api/admin/plan-patterns/' + id) : '/api/admin/plan-patterns';
    api(url, {
      method: method,
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (res) {
      if (!res.ok) {
        patFb((res.data && res.data.detail) || 'Save failed', false);
        return;
      }
      patFb('Saved', true);
      _patUseRawRecipe = false;
      fillPatternForm(res.data);
      loadPatterns();
    }).catch(function () { patFb('Save failed', false); });
  }

  function removePattern() {
    var id = document.getElementById('pat-edit-id').value.trim();
    if (!id) return;
    if (!confirm('Delete this pattern?')) return;
    api('/api/admin/plan-patterns/' + id, { method: 'DELETE' }).then(function (res) {
      if (!res.ok) {
        patFb('Delete failed', false);
        return;
      }
      patFb('Deleted', true);
      _patSelectedId = null;
      fillPatternForm(blankPattern());
      loadPatterns();
    });
  }

  function duplicatePattern() {
    var body = collectPatternBody();
    if (!body) return;
    body.name = body.name + ' (copy)';
    document.getElementById('pat-edit-id').value = '';
    _patSelectedId = null;
    document.getElementById('pat-edit-name').value = body.name;
    document.getElementById('pat-editor-title').textContent = 'New pattern';
    patFb('Duplicated — edit the name and Save', true);
  }

  // ── Seed (both) ────────────────────────────────────────────────────────────

  function seed(reset) {
    if (reset && !confirm('Overwrite existing seed exercises/patterns from code defaults?')) return;
    var url = '/api/admin/plan-patterns/seed' + (reset ? '?reset=true' : '');
    var fbEl = _tab === 'patterns' ? patFb : fb;
    if (_tab === 'preview') fbEl = fb;
    api(url, { method: 'POST' }).then(function (res) {
      if (!res.ok) {
        fbEl((res.data && res.data.detail) || 'Seed failed', false);
        return;
      }
      fbEl(reset ? ('Reset: ' + JSON.stringify(res.data)) : ('Seeded: ' + JSON.stringify(res.data)), true);
      loadExercises();
      if (_patternsLoaded || _tab === 'patterns') loadPatterns();
    });
  }

  // ── Wire up ────────────────────────────────────────────────────────────────

  document.getElementById('logout-btn').onclick = function () {
    fetch('/api/admin/logout', { method: 'POST' }).finally(function () {
      window.location.href = '/admin';
    });
  };

  document.getElementById('tab-exercises').onclick = function () { setTab('exercises'); };
  document.getElementById('tab-patterns').onclick = function () { setTab('patterns'); };
  document.getElementById('tab-preview').onclick = function () { setTab('preview'); };

  document.getElementById('btn-new').onclick = function () {
    if (_tab === 'patterns') fillPatternForm(blankPattern());
    else if (_tab === 'exercises') fillExerciseForm(blankExercise());
  };

  document.getElementById('btn-save').onclick = saveExercise;
  document.getElementById('btn-delete').onclick = removeExercise;
  document.getElementById('btn-dup').onclick = duplicateExercise;
  document.getElementById('btn-seed').onclick = function () { seed(false); };
  document.getElementById('btn-reset').onclick = function () { seed(true); };
  document.getElementById('btn-add-part').onclick = function () { addPartRow('glute', 0.5); };
  document.getElementById('btn-preview').onclick = previewFill;
  document.getElementById('search').addEventListener('input', renderExerciseList);
  document.getElementById('hide-inactive').addEventListener('change', renderExerciseList);

  document.getElementById('pat-btn-save').onclick = savePattern;
  document.getElementById('pat-btn-delete').onclick = removePattern;
  document.getElementById('pat-btn-dup').onclick = duplicatePattern;
  document.getElementById('pat-btn-new').onclick = function () { fillPatternForm(blankPattern()); };
  document.getElementById('pat-add-block').onclick = function () { addRunBlockRow(); };
  document.getElementById('pat-add-group').onclick = function () { addStrengthGroupRow(); };
  document.getElementById('pat-search').addEventListener('input', renderPatternList);
  document.getElementById('pat-hide-inactive').addEventListener('change', renderPatternList);
  document.getElementById('pat-edit-kind').addEventListener('change', toggleKindRecipeUI);
  document.getElementById('pat-raw-json').addEventListener('input', function () {
    _patUseRawRecipe = true;
  });
  document.getElementById('pat-raw-wrap').addEventListener('toggle', function (e) {
    if (e.target.open && !_patUseRawRecipe) syncRawJsonFromForm();
  });

  window.addEventListener('hashchange', function () {
    var t = tabFromUrl();
    if (t !== _tab) setTab(t);
  });

  fillExerciseForm(blankExercise());
  fillPatternForm(blankPattern());
  setTab(tabFromUrl());
  loadExercises();
})();
