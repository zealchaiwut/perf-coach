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
    'cooldown', 'bodyweight', 'plyo', 'isometric', 'emom',
  ];
  // Recipe-block display order for the Exercises card grid (variation C).
  var GROUP_SECTION_ORDER = [
    'heavy_compound', 'superset', 'accessories', 'warmup', 'cooldown',
    'bodyweight', 'isometric', 'plyo', 'standalone', 'emom',
  ];
  var GROUP_LABELS = {
    heavy_compound: 'Heavy compound',
    superset: 'Superset',
    accessories: 'Accessories',
    warmup: 'Warm-up',
    cooldown: 'Stretch',
    bodyweight: 'Bodyweight',
    isometric: 'Isometrics',
    plyo: 'Plyometrics',
    standalone: 'Standalone',
    emom: 'EMOM',
  };
  var FOCUS = ['lower', 'upper', 'full', 'core'];
  var PART_COLORS = {
    quad: '#4f6ef7', glute: '#7c3aed', hamstring: '#0ea5e9', calf: '#f97316',
    hip: '#14b8a6', hip_flexor: '#06b6d4', chest: '#ec4899', shoulder: '#f59e0b',
    upper_back: '#8b5cf6', lower_back: '#ef4444', trapezius: '#a855f7',
    biceps: '#22c55e', triceps: '#10b981', core: '#eab308', oblique: '#facc15',
    grip: '#64748b',
  };
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
    var pageSub = document.getElementById('page-sub');
    if (_tab === 'preview') {
      btnNew.hidden = true;
      if (pageSub) {
        pageSub.textContent = 'Dry-run pattern fill — pool depth and pick-by-pick budget.';
      }
    } else {
      btnNew.hidden = false;
      btnNew.textContent = _tab === 'patterns' ? '+ New pattern' : '+ New exercise';
      if (pageSub) {
        pageSub.innerHTML = _tab === 'patterns'
          ? 'Run and strength recipes. Pool-size badges come from the same matcher Preview uses.'
          : 'Grouped by recipe block, so the pool reads the way patterns consume it.';
      }
    }
    updateUrlTab(_tab);
    if (_tab === 'patterns' && !_patternsLoaded) loadPatterns();
    if (_tab === 'exercises' && !_exercisesLoaded) loadExercises();
    if (_tab === 'preview') {
      if (!_patternsLoaded) loadPatterns();
      refreshPoolSummary();
    }
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

  function exercisePayload(e) {
    return {
      name: e.name || '',
      groups: e.groups || [],
      focus_tags: e.focus_tags || [],
      body_parts: e.body_parts || [],
      tss_weight: e.tss_weight != null ? e.tss_weight : 1,
      default_sets: e.default_sets != null ? e.default_sets : null,
      default_reps: e.default_reps || null,
      default_load: e.default_load || null,
      active: e.active !== false,
    };
  }

  function blankExercise(groupKey) {
    return {
      id: '',
      name: '',
      groups: [groupKey || 'standalone'],
      focus_tags: ['full'],
      body_parts: [{ part: 'core', ratio: 1.0 }],
      tss_weight: 1,
      default_sets: 3,
      default_reps: '10',
      default_load: 'moderate',
      active: true,
    };
  }

  function unwrapExerciseJson(raw) {
    if (raw == null) return null;
    if (Array.isArray(raw)) {
      return raw.length === 1 && raw[0] && typeof raw[0] === 'object' ? raw[0] : null;
    }
    if (typeof raw !== 'object') return null;
    if (Array.isArray(raw.exercises)) {
      if (raw.exercises.length === 1 && raw.exercises[0] && typeof raw.exercises[0] === 'object') {
        return raw.exercises[0];
      }
      return null;
    }
    return raw;
  }

  function validateExerciseDraft(obj) {
    var checks = [];
    function add(ok, label) { checks.push({ ok: !!ok, label: label }); }

    if (!obj || typeof obj !== 'object' || Array.isArray(obj)) {
      add(false, 'Root must be one exercise object (or { "exercises": [ … ] } with a single item)');
      return { ok: false, checks: checks, body: null, preview: null };
    }

    var name = typeof obj.name === 'string' ? obj.name.trim() : '';
    add(!!name, 'name — non-empty string');

    var groups = Array.isArray(obj.groups) ? obj.groups : null;
    var groupsOk = !!groups && groups.length > 0 && groups.every(function (g) {
      return typeof g === 'string' && GROUPS.indexOf(g) !== -1;
    });
    add(groupsOk, 'groups — non-empty, each in: ' + GROUPS.join(', '));

    var focus = Array.isArray(obj.focus_tags) ? obj.focus_tags : null;
    var focusOk = !!focus && focus.length > 0 && focus.every(function (f) {
      return typeof f === 'string' && FOCUS.indexOf(f) !== -1;
    });
    add(focusOk, 'focus_tags — non-empty, each in: ' + FOCUS.join(', '));

    var parts = Array.isArray(obj.body_parts) ? obj.body_parts : null;
    var partSum = 0;
    var partsOk = !!parts && parts.length > 0 && parts.every(function (p) {
      if (!p || typeof p !== 'object') return false;
      var part = typeof p.part === 'string' ? p.part.trim() : '';
      var ratio = Number(p.ratio);
      if (!part || !isFinite(ratio) || ratio <= 0) return false;
      partSum += ratio;
      return true;
    });
    add(partsOk, 'body_parts — [{ part, ratio }] with ratio > 0');
    add(partsOk && Math.abs(partSum - 1) <= 0.05, 'body_parts ratios sum ≈ 1.0 (now ' +
      (partsOk ? partSum.toFixed(2) : '—') + ')');

    var setsRaw = obj.default_sets;
    var sets = typeof setsRaw === 'number' ? setsRaw : Number(setsRaw);
    var setsOk = isFinite(sets) && Math.floor(sets) === sets && sets >= 1 && sets <= 12;
    add(setsOk, 'default_sets — integer 1–12');

    var reps = typeof obj.default_reps === 'string' ? obj.default_reps.trim() : '';
    add(!!reps, 'default_reps — non-empty string');

    var load = typeof obj.default_load === 'string' ? obj.default_load.trim() : '';
    add(!!load, 'default_load — non-empty string');

    var tw = Number(obj.tss_weight);
    add(isFinite(tw) && tw > 0 && tw <= 3, 'tss_weight — number 0 < n ≤ 3');

    var active = obj.active === undefined ? true : obj.active;
    var activeOk = typeof active === 'boolean';
    add(activeOk, 'active — boolean (defaults true if omitted)');

    var ok = checks.every(function (c) { return c.ok; });
    var body = ok ? {
      name: name,
      groups: groups.slice(),
      focus_tags: focus.slice(),
      body_parts: parts.map(function (p) {
        return { part: String(p.part).trim(), ratio: Math.round(Number(p.ratio) * 100) / 100 };
      }),
      tss_weight: tw,
      default_sets: sets,
      default_reps: reps,
      default_load: load,
      active: active,
    } : null;

    var preview = {
      id: _selectedId || '',
      name: name || '(unnamed)',
      groups: groupsOk ? groups : [],
      focus_tags: focusOk ? focus : [],
      body_parts: partsOk ? parts : [],
      tss_weight: isFinite(tw) ? tw : 1,
      default_sets: setsOk ? sets : null,
      default_reps: reps || null,
      default_load: load || null,
      active: activeOk ? active : true,
    };

    return { ok: ok, checks: checks, body: body, preview: preview };
  }

  function parseExerciseEditor() {
    var ta = document.getElementById('ex-json');
    var rawText = (ta.value || '').trim();
    if (!rawText) {
      return {
        ok: false,
        parseError: 'Paste exercise JSON',
        checks: [{ ok: false, label: 'JSON — paste a complete exercise object' }],
        body: null,
        preview: null,
      };
    }
    var parsed;
    try {
      parsed = JSON.parse(rawText);
    } catch (err) {
      return {
        ok: false,
        parseError: 'Invalid JSON: ' + (err && err.message ? err.message : 'parse error'),
        checks: [{ ok: false, label: 'JSON — must parse (fix / trailing commas / quotes)' }],
        body: null,
        preview: null,
      };
    }
    var unwrapped = unwrapExerciseJson(parsed);
    if (!unwrapped) {
      return {
        ok: false,
        parseError: 'Expected one exercise object (or catalog with a single exercises[] item)',
        checks: [{ ok: false, label: 'Shape — one exercise object, not an empty / multi-item catalog' }],
        body: null,
        preview: null,
      };
    }
    return validateExerciseDraft(unwrapped);
  }

  function renderExerciseEditorPreview() {
    var result = parseExerciseEditor();
    var ta = document.getElementById('ex-json');
    var previewEl = document.getElementById('ex-card-preview');
    var metaEl = document.getElementById('ex-json-meta');
    var checksEl = document.getElementById('ex-json-checks');
    var saveBtn = document.getElementById('btn-save');

    ta.classList.toggle('invalid', !result.ok);

    if (result.preview) {
      var card = exerciseCardHtml(result.preview, (result.preview.groups || [])[0] || 'standalone');
      previewEl.innerHTML = card
        .replace('<button type="button"', '<div role="img"')
        .replace(/<\/button>\s*$/, '</div>');
    } else {
      previewEl.innerHTML = '<div class="ex-json-placeholder">' +
        esc(result.parseError || 'Paste exercise JSON to preview the card.') +
        '</div>';
    }

    if (result.preview && ((result.preview.groups || []).length || (result.preview.focus_tags || []).length)) {
      metaEl.hidden = false;
      var bits = [];
      if ((result.preview.groups || []).length) {
        bits.push('<span class="mk">Groups</span>');
        result.preview.groups.forEach(function (g) {
          bits.push('<span class="chip">' + esc(GROUP_LABELS[g] || g) + '</span>');
        });
      }
      if ((result.preview.focus_tags || []).length) {
        bits.push('<span class="mk">Focus</span>');
        result.preview.focus_tags.forEach(function (f) {
          bits.push('<span class="tg ' + esc(f) + '">' + esc(f) + '</span>');
        });
      }
      metaEl.innerHTML = bits.join('');
    } else {
      metaEl.hidden = true;
      metaEl.innerHTML = '';
    }

    checksEl.innerHTML = (result.checks || []).map(function (c) {
      return '<li class="' + (c.ok ? 'ok' : 'bad') + '">' +
        '<span class="mark">' + (c.ok ? '✓' : '✗') + '</span>' +
        '<span>' + esc(c.label) + '</span></li>';
    }).join('');

    saveBtn.disabled = !result.ok;
    return result;
  }

  function fillExerciseForm(e) {
    e = e || blankExercise();
    _selectedId = e.id || null;
    document.getElementById('edit-id').value = e.id || '';
    document.getElementById('editor-title').textContent = e.id ? 'Edit exercise' : 'New exercise';
    document.getElementById('ex-json').value = JSON.stringify(exercisePayload(e), null, 2);
    fb('', true);
    renderExerciseEditorPreview();
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

  function partBarHtml(parts) {
    var entries = [];
    (parts || []).forEach(function (p) {
      if (!p || typeof p !== 'object') return;
      var key = String(p.part || '');
      var ratio = Number(p.ratio);
      if (!key || !isFinite(ratio) || ratio <= 0) return;
      entries.push([key, ratio]);
    });
    if (!entries.length) {
      return '<span class="tinybar" title="No body parts"></span>';
    }
    var tot = entries.reduce(function (s, x) { return s + x[1]; }, 0) || 1;
    return '<span class="tinybar">' + entries.map(function (x) {
      var pct = Math.max(2, Math.round(x[1] / tot * 100));
      var color = PART_COLORS[x[0]] || '#9ca3af';
      return '<i style="width:' + pct + '%;background:' + color + '" title="' +
        esc(x[0]) + ' ' + Math.round(x[1] / tot * 100) + '%"></i>';
    }).join('') + '</span>';
  }

  function exerciseCardHtml(e, sectionKey) {
    var groups = e.groups || [];
    var extra = Math.max(0, groups.length - 1);
    var rx = [
      (e.default_sets != null ? e.default_sets : '?'),
      ' × ',
      (e.default_reps || '?'),
      (e.default_load ? ' · ' + e.default_load : ''),
    ].join('');
    var tags = (e.focus_tags || []).map(function (f) {
      return '<span class="tg ' + esc(f) + '">' + esc(f) + '</span>';
    }).join('');
    return '<button type="button" class="exc' +
      (e.id === _selectedId ? ' selected' : '') +
      (e.active ? '' : ' off') +
      '" data-id="' + esc(e.id) + '" data-section="' + esc(sectionKey) + '">' +
      '<span class="n">' + esc(e.name) +
        (extra ? '<span class="multi">+' + extra + ' group' + (extra > 1 ? 's' : '') + '</span>' : '') +
      '</span>' +
      '<span class="r">' + esc(rx) + '</span>' +
      (tags ? '<span class="tags">' + tags + '</span>' : '') +
      partBarHtml(e.body_parts) +
      '</button>';
  }

  function renderExerciseList() {
    var rows = filteredExercises();
    var countEl = document.getElementById('list-count');
    if (countEl) {
      countEl.textContent =
        rows.length + ' of ' + _all.length + ' exercise' + (_all.length === 1 ? '' : 's');
    }
    var grid = document.getElementById('ex-grid');
    if (!grid) return;

    if (!rows.length) {
      grid.innerHTML = '<div class="ex-empty">No exercises match these filters.</div>';
      return;
    }

    var byGroup = {};
    rows.forEach(function (e) {
      var gs = e.groups || [];
      if (!gs.length) gs = ['standalone'];
      gs.forEach(function (g) {
        if (!byGroup[g]) byGroup[g] = [];
        byGroup[g].push(e);
      });
    });

    var order = GROUP_SECTION_ORDER.slice();
    Object.keys(byGroup).forEach(function (g) {
      if (order.indexOf(g) === -1) order.push(g);
    });

    var html = '';
    order.forEach(function (key) {
      var list = byGroup[key];
      if (!list || !list.length) return;
      list = list.slice().sort(function (a, b) {
        return String(a.name || '').localeCompare(String(b.name || ''));
      });
      var label = GROUP_LABELS[key] || key;
      html += '<div class="gsec" data-group="' + esc(key) + '">' +
        '<div class="gsech">' +
          '<span class="t">' + esc(label) + '</span>' +
          '<span class="c">' + list.length + '</span>' +
          '<span class="ln"></span>' +
          '<button type="button" class="btn btn-add-group" data-add-group="' +
            esc(key) + '">+ Add to ' + esc(label.toLowerCase()) + '</button>' +
        '</div>' +
        '<div class="ex-card-grid">' +
          list.map(function (e) { return exerciseCardHtml(e, key); }).join('') +
        '</div></div>';
    });
    grid.innerHTML = html || '<div class="ex-empty">No exercises in these groups.</div>';

    grid.querySelectorAll('.exc').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var id = btn.getAttribute('data-id');
        var row = _all.find(function (x) { return x.id === id; });
        if (row) fillExerciseForm(row);
      });
      btn.addEventListener('mouseenter', function () {
        var id = btn.getAttribute('data-id');
        grid.querySelectorAll('.exc').forEach(function (el) {
          el.classList.toggle('sib-hl', el.getAttribute('data-id') === id && el !== btn);
        });
      });
      btn.addEventListener('mouseleave', function () {
        grid.querySelectorAll('.exc.sib-hl').forEach(function (el) {
          el.classList.remove('sib-hl');
        });
      });
    });
    grid.querySelectorAll('[data-add-group]').forEach(function (btn) {
      btn.addEventListener('click', function (ev) {
        ev.stopPropagation();
        addExerciseForGroup(btn.getAttribute('data-add-group'));
      });
    });
  }

  function addExerciseForGroup(groupKey) {
    fillExerciseForm(blankExercise(groupKey));
    var ta = document.getElementById('ex-json');
    if (ta) {
      ta.focus();
      ta.select();
    }
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
    var result = renderExerciseEditorPreview();
    if (!result.ok) {
      fb(result.parseError || 'Fix the checklist before saving', false);
      return null;
    }
    return result.body;
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
    var result = parseExerciseEditor();
    var base = result.body || (result.preview ? exercisePayload(result.preview) : null);
    if (!base || !base.name) {
      fb('Need a named exercise to duplicate', false);
      return;
    }
    base.name = String(base.name).replace(/\s*\(copy\)\s*$/, '') + ' (copy)';
    document.getElementById('edit-id').value = '';
    _selectedId = null;
    document.getElementById('editor-title').textContent = 'New exercise';
    document.getElementById('ex-json').value = JSON.stringify(exercisePayload(base), null, 2);
    renderExerciseEditorPreview();
    fb('Duplicated — edit the name and Save', true);
  }

  function formatExerciseJson() {
    var ta = document.getElementById('ex-json');
    var raw = (ta.value || '').trim();
    if (!raw) return;
    try {
      var parsed = JSON.parse(raw);
      ta.value = JSON.stringify(parsed, null, 2);
      renderExerciseEditorPreview();
      fb('Formatted', true);
    } catch (err) {
      fb('Cannot format — fix JSON first', false);
      renderExerciseEditorPreview();
    }
  }

  var PREVIEW_STORAGE_KEY = 'planLibPreview.v1';
  var _previewHasRun = false;
  var _lastPreviewCfg = null;
  var _lastPoolCounts = null;
  var _lastPreviewBody = '';

  function budgetRemainHtml(tss, mins, note) {
    return '<div class="bt-remain">remaining ' + esc(tss) + ' TSS · ' + esc(mins) + ' min' +
      (note ? ' <span class="bt-note">[' + esc(note) + ']</span>' : '') +
      '</div>';
  }

  function poolCountIndex(poolCounts) {
    var byKey = {};
    var byLabel = {};
    ((poolCounts && poolCounts.blocks) || []).forEach(function (b) {
      if (b.key) byKey[b.key] = b;
      if (b.label) byLabel[b.label] = b;
    });
    return { byKey: byKey, byLabel: byLabel };
  }

  function poolInCount(idx, ev) {
    var b = null;
    if (ev.key && idx.byKey[ev.key]) b = idx.byKey[ev.key];
    else if (ev.label && idx.byLabel[ev.label]) b = idx.byLabel[ev.label];
    return b && b.matched_count != null ? b.matched_count : null;
  }

  function pickSpendLine(ev) {
    var spend = '<span class="bt-spend-val">' + esc(ev.spend_min) + ' min, ' +
      esc(ev.spend_tss) + ' TSS</span>';
    var isRun = ev.kind === 'run' || (ev.sets == null && (ev.pace_mult != null || ev.duration_min != null));
    if (isRun) {
      var bits = [];
      var rep = ev.repeat != null ? Number(ev.repeat) : 0;
      var per = ev.duration_min != null ? Number(ev.duration_min) : null;
      if (rep > 1 && per != null) bits.push(rep + ' × ' + per + ' min');
      else if (per != null) bits.push(per + ' min');
      else if (ev.block_min != null) bits.push(ev.block_min + ' min');
      if (ev.target) bits.push(String(ev.target));
      if (ev.rest_min != null && rep > 1) bits.push(ev.rest_min + ' min rest');
      return bits.join(' · ') + ' → ' + spend;
    }
    return (ev.sets != null ? ev.sets : '?') + ' × ' + (ev.reps || '?') +
      (ev.load ? ' · ' + ev.load : '') + ' → ' + spend;
  }

  function pickScoreLine(ev) {
    if (ev.score != null && ev.bias != null && ev.random != null) {
      return '<div class="bt-score-line">score <span class="bt-score">' + esc(ev.score) +
        '</span> = bias ' + esc(ev.bias) + ' × random ' + esc(ev.random) + '</div>';
    }
    if (ev.pace_mult != null) {
      var pace = Number(ev.pace_mult);
      var line = 'pace ×' + (isFinite(pace) ? pace.toFixed(2) : esc(ev.pace_mult)) + ' threshold';
      if (ev.target) line += ' · ' + ev.target;
      return '<div class="bt-score-line">' + esc(line) + '</div>';
    }
    return '';
  }

  function budgetTraceHtml(trace, poolCounts) {
    if (!trace || !trace.length) return '';
    var idx = poolCountIndex(poolCounts);
    var html = [];
    var groupOpen = false;
    var pickBuf = [];

    function flushPicks() {
      if (!pickBuf.length) return;
      html.push('<div class="bt-picks">' + pickBuf.join('') + '</div>');
      pickBuf = [];
    }
    function closeGroup() {
      flushPicks();
      if (groupOpen) {
        html.push('</div>');
        groupOpen = false;
      }
    }

    trace.forEach(function (ev) {
      var op = ev.op || '';
      if (op === 'budget_start') {
        html.push('<div class="bt-start">session ' + esc(ev.remain_tss) + ' TSS · ' +
          esc(ev.remain_min) + ' min</div>');
        return;
      }
      if (op === 'group_open') {
        closeGroup();
        var inPool = poolInCount(idx, ev);
        var meta = esc(ev.group_tss) + ' TSS / ' + esc(ev.group_min) + ' min';
        if (inPool != null) meta += ' · ' + inPool + ' in pool';
        html.push('<div class="bt-group">' +
          '<div class="bt-group-h">' +
          '<span class="bt-group-label">' + esc(ev.label || 'Group') +
          ' · pick ' + esc(ev.n) + '</span>' +
          '<span class="bt-group-meta">' + meta + '</span>' +
          '</div>');
        groupOpen = true;
        return;
      }
      if (op === 'group_skip') {
        closeGroup();
        html.push('<div class="bt-group bt-group-skip">' +
          '<div class="bt-group-h"><span class="bt-group-label">skip ' +
          esc(ev.label || '') + '</span>' +
          (ev.reason ? '<span class="bt-group-meta">' + esc(ev.reason) + '</span>' : '') +
          '</div></div>');
        return;
      }
      if (op === 'budget_remain') {
        if (ev.note) {
          pickBuf.push('<div class="bt-inline">' + budgetRemainHtml(ev.remain_tss, ev.remain_min, ev.note) + '</div>');
        }
        return;
      }
      if (op === 'budget_pick') {
        var alts = '';
        if (ev.top && ev.top.length > 1) {
          alts = '<div class="bt-alts">runners-up: ' +
            ev.top.slice(1, 3).map(function (t) {
              return esc(t.name) + ' ' + esc(t.score);
            }).join(', ') + '</div>';
        }
        pickBuf.push(
          '<div class="bt-pick">' +
            '<span class="bt-name">' + esc(ev.name || '?') + '</span>' +
            '<span class="bt-rx">' + pickSpendLine(ev) + '</span>' +
            pickScoreLine(ev) +
            alts +
            budgetRemainHtml(ev.remain_tss_after, ev.remain_min_after, ev.note || null) +
          '</div>'
        );
        return;
      }
      if (op === 'budget_exhausted') {
        flushPicks();
        html.push('<div class="bt-exhausted">Budget exhausted · ' +
          esc(ev.remain_tss) + ' TSS, ' + esc(ev.remain_min) + ' min left</div>');
        return;
      }
      if (op === 'budget_end') {
        closeGroup();
        var nLabel = ev.kind === 'run' ? 'blocks' : 'exercises';
        html.push('<div class="bt-end">Done · ' + esc(ev.exercise_count) + ' ' + nLabel +
          ' · leftover ' + esc(ev.remain_tss) + ' TSS, ' + esc(ev.remain_min) + ' min</div>');
      }
    });
    closeGroup();
    return html.join('');
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
      return op + ' · ' + (step.exercise_count || 0) + ' exercises' +
        (step.blocks && step.blocks.length ? ' · ' + step.blocks.join(', ') : '');
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

  function fillLogHtml(log, poolCounts) {
    if (!log) return '';
    var trace = log.budget_trace || [];
    var budgetBody = budgetTraceHtml(trace, poolCounts);
    if (!budgetBody) return '';
    return '<div class="budget-trace-block">' +
      '<div class="budget-trace-list">' + budgetBody + '</div></div>';
  }

  function renderPoolSummary(poolCounts, subtype) {
    var el = document.getElementById('pool-summary');
    if (!el) return;
    if (!poolCounts) {
      el.className = 'pool-summary';
      el.innerHTML = '<span class="muted">Pick a subtype to see pool depth.</span>';
      return;
    }
    if (poolCounts.kind === 'run') {
      el.className = 'pool-summary';
      el.textContent = 'Run subtype — phases scale by duration (no exercise pool).';
      return;
    }
    var total = poolCounts.matched_total || 0;
    var thin = poolCounts.thin_blocks || [];
    var sub = subtype || poolCounts.subtype || 'pattern';
    if (total === 0) {
      el.className = 'pool-summary err';
      el.textContent = 'No exercises match this subtype — fill would return an empty session.';
      return;
    }
    var thinHtml = 'none';
    if (thin.length) {
      thinHtml = thin.map(function (b) {
        return '<b>' + esc(b.label || b.key) + ' only ' + esc(b.matched_count) + '</b>';
      }).join(', ');
      el.className = 'pool-summary warn';
    } else {
      el.className = 'pool-summary';
    }
    el.innerHTML = '<b>' + total + ' exercises</b> match <span class="mono">' +
      esc(sub) + '</span> — thin blocks: ' + thinHtml;
  }

  function readPreviewConfig() {
    return {
      subtype: document.getElementById('preview-subtype').value,
      duration_minutes: parseInt(document.getElementById('preview-dur').value, 10) || 45,
      target_tss: parseFloat(document.getElementById('preview-tss').value) || 40,
    };
  }

  function applyPreviewConfig(cfg) {
    if (!cfg) return;
    if (cfg.subtype) document.getElementById('preview-subtype').value = cfg.subtype;
    if (cfg.duration_minutes != null) document.getElementById('preview-dur').value = cfg.duration_minutes;
    if (cfg.target_tss != null) document.getElementById('preview-tss').value = cfg.target_tss;
  }

  function savePreviewConfig(cfg) {
    try { sessionStorage.setItem(PREVIEW_STORAGE_KEY, JSON.stringify(cfg)); }
    catch (e) { /* ignore */ }
  }

  function loadPreviewConfig() {
    try {
      var raw = sessionStorage.getItem(PREVIEW_STORAGE_KEY);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { return null; }
  }

  function setReshuffleEnabled(on) {
    var btn = document.getElementById('btn-reshuffle');
    if (btn) btn.disabled = !on;
  }

  function refreshPoolSummary() {
    var cfg = readPreviewConfig();
    var url = '/api/admin/plan-library/pool-counts?subtype=' +
      encodeURIComponent(cfg.subtype) + '&duration_min=' + cfg.duration_minutes;
    api(url).then(function (res) {
      if (!res.ok) {
        renderPoolSummary(null);
        return;
      }
      _lastPoolCounts = res.data;
      renderPoolSummary(res.data, cfg.subtype);
    }).catch(function () { renderPoolSummary(null); });
  }

  function muscleSummaryHtml(summary, footprint) {
    var rows = summary && summary.length
      ? summary
      : Object.keys(footprint || {}).map(function (p) {
          return { part: p, tss: footprint[p] };
        }).sort(function (a, b) { return b.tss - a.tss; });
    if (!rows.length) {
      return '<div class="muted">No muscle TSS yet — exercises need body_parts.</div>';
    }
    var max = rows.reduce(function (m, r) { return Math.max(m, Number(r.tss) || 0); }, 0);
    var total = rows.reduce(function (s, r) { return s + (Number(r.tss) || 0); }, 0);
    var PART_LABEL = {
      calf: 'calf / shin',
      quad: 'quad',
      hamstring: 'hamstring',
      glute: 'glute',
      hip: 'hip',
      core: 'core',
      back: 'back',
      shoulder: 'shoulder',
      chest: 'chest',
      arm: 'arm',
      other: 'other',
    };

    var table = '<table class="muscle-tss-table"><thead><tr>' +
      '<th>Muscle</th><th class="num">TSS</th><th class="num">%</th></tr></thead><tbody>' +
      rows.map(function (r) {
        var tss = Number(r.tss) || 0;
        var pct = total > 0 ? Math.round(tss / total * 100) : 0;
        var w = max > 0 ? Math.round(tss / max * 100) : 0;
        var label = PART_LABEL[r.part] || r.part;
        return '<tr><td>' + esc(label) +
          '<span class="muscle-bar" style="width:' + w + '%"></span></td>' +
          '<td class="num">' + tss.toFixed(1) + '</td>' +
          '<td class="num">' + pct + '%</td></tr>';
      }).join('') +
      '</tbody><tfoot><tr><td>Total</td><td class="num">' + total.toFixed(1) +
      '</td><td class="num">100%</td></tr></tfoot></table>';

    return table;
  }

  function exerciseTableHtml(exs) {
    var totalTss = 0;
    var totalMin = 0;
    var rows = exs.map(function (x) {
      var tss = x.spend_tss != null ? Number(x.spend_tss) : null;
      var mins = x.spend_min != null ? Number(x.spend_min) : null;
      if (tss != null) totalTss += tss;
      if (mins != null) totalMin += mins;
      var sr = (x.sets != null && x.reps != null) ? (x.sets + ' × ' + x.reps) : '';
      return '<tr><td>' + esc(x.name || '') + '</td>' +
        '<td class="muted">' + esc(x.block || '') + '</td>' +
        '<td>' + esc(sr + (x.load ? ' · ' + x.load : '')) + '</td>' +
        '<td class="num">' + (mins != null ? mins.toFixed(1) : '—') + '</td>' +
        '<td class="num">' + (tss != null ? tss.toFixed(1) : '—') + '</td></tr>';
    }).join('');
    return '<table class="preview-ex-table"><thead><tr>' +
      '<th>Exercise</th><th>Block</th><th>Prescription</th>' +
      '<th class="num">Min</th><th class="num">TSS</th></tr></thead><tbody>' + rows +
      '</tbody><tfoot><tr><td colspan="3">Session spend</td>' +
      '<td class="num">' + totalMin.toFixed(1) + '</td>' +
      '<td class="num">' + totalTss.toFixed(1) + '</td></tr></tfoot></table>';
  }

  function runBlockPrescription(b) {
    var bits = [];
    var rep = b.repeat != null ? Number(b.repeat) : 0;
    var per = b.duration_min != null ? Number(b.duration_min) : null;
    var rest = b.rest_min != null ? Number(b.rest_min) : null;
    var pace = b.pace_mult != null ? Number(b.pace_mult) : null;
    if (rep > 1 && per != null) {
      bits.push(rep + ' × ' + per + ' min');
    } else if (per != null) {
      bits.push(per + ' min');
    }
    if (b.target) bits.push(String(b.target));
    if (pace != null && isFinite(pace)) {
      bits.push('@ ×' + pace.toFixed(2) + ' threshold');
    }
    if (rep > 1 && rest != null) bits.push(rest + ' min rest');
    return bits.join(' · ');
  }

  function blocksTableHtml(blocks) {
    var totalTss = 0;
    var totalMin = 0;
    var rows = (blocks || []).map(function (b) {
      var tss = b.spend_tss != null ? Number(b.spend_tss) : null;
      var mins = b.block_min != null ? Number(b.block_min) : (
        b.duration_min != null ? Number(b.duration_min) : null
      );
      // Wall time for repeats: work×rep + rest×(rep−1)
      var rep = b.repeat != null ? Number(b.repeat) : 0;
      if (rep > 1 && b.duration_min != null) {
        var rest = b.rest_min != null ? Number(b.rest_min) : 0;
        mins = Number(b.duration_min) * rep + rest * Math.max(0, rep - 1);
      }
      if (tss != null) totalTss += tss;
      if (mins != null) totalMin += mins;
      return '<tr><td>' + esc(b.phase || '') + '</td>' +
        '<td>' + esc(runBlockPrescription(b)) + '</td>' +
        '<td class="num">' + (mins != null ? mins.toFixed(0) : '—') + '</td>' +
        '<td class="num">' + (tss != null ? tss.toFixed(1) : '—') + '</td></tr>';
    }).join('');
    return '<table class="preview-ex-table"><thead><tr>' +
      '<th>Phase</th><th>Prescription</th>' +
      '<th class="num">Min</th><th class="num">TSS</th></tr></thead><tbody>' + rows +
      '</tbody><tfoot><tr><td colspan="2">Session spend</td>' +
      '<td class="num">' + totalMin.toFixed(0) + '</td>' +
      '<td class="num">' + totalTss.toFixed(1) + '</td></tr></tfoot></table>';
  }

  function previewFill(opts) {
    opts = opts || {};
    var reshuffle = !!opts.reshuffle;
    var out = document.getElementById('preview-out');
    var cfg = reshuffle && _lastPreviewCfg ? _lastPreviewCfg : readPreviewConfig();
    if (!reshuffle) {
      applyPreviewConfig(cfg);
      savePreviewConfig(cfg);
      _lastPreviewCfg = cfg;
    }
    var body = {
      subtype: cfg.subtype,
      duration_minutes: cfg.duration_minutes,
      target_tss: cfg.target_tss,
    };
    // Loading state — keep prior body on reshuffle failure
    if (!_lastPreviewBody) {
      out.innerHTML = '<span class="muted">Filling…</span>';
    }
    api('/api/admin/plan-exercises/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    }).then(function (res) {
      if (!res.ok) {
        var err = (res.data && res.data.detail) || 'Preview failed';
        if (_lastPreviewBody) {
          out.innerHTML = _lastPreviewBody + '<div class="preview-error">' + esc(err) + '</div>';
        } else {
          out.innerHTML = '<div class="preview-error">' + esc(err) + '</div>';
        }
        return;
      }
      var d = res.data || {};
      if (d.pool_counts) {
        _lastPoolCounts = d.pool_counts;
        renderPoolSummary(d.pool_counts, cfg.subtype);
      } else {
        refreshPoolSummary();
      }
      var exs = d.exercises || [];
      var blocks = d.blocks || [];
      var isRun = (d.workout_type || '') === 'run' || (!exs.length && blocks.length);
      var html = '<div class="intent">' + esc(d.intent || 'Session') +
        ' <span class="muted">· ' + esc(d.pattern_name || d.source || '') +
        ' · ' + (d.duration_minutes || cfg.duration_minutes) + ' min · ' +
        (d.target_tss != null ? d.target_tss : cfg.target_tss) + ' TSS' +
        (d.seed != null ? ' · seed ' + d.seed : '') + '</span></div>';
      if (d.notes) html += '<div class="muted" style="margin-bottom:8px;">' + esc(d.notes) + '</div>';

      if (d.pool_counts && (d.pool_counts.matched_total === 0) && !isRun) {
        html += '<div class="muted">No content — empty pool for this subtype.</div>';
        _lastPreviewBody = html;
        out.innerHTML = html;
        _previewHasRun = true;
        setReshuffleEnabled(true);
        return;
      }

      var main = '';
      if (isRun && blocks.length) {
        main = blocksTableHtml(blocks);
      } else if (exs.length) {
        main = exerciseTableHtml(exs);
      } else {
        main = '<div class="muted">No content returned — check patterns / pool.</div>';
      }
      html += '<div class="preview-layout">' +
        '<div class="preview-pane preview-pane-ex">' +
          '<div class="preview-pane-h">' + (isRun ? 'Session blocks' : 'Exercises') + '</div>' +
          main +
        '</div>' +
        '<aside class="preview-pane preview-side">' +
          '<div class="preview-pane-h">Muscle TSS</div>' +
          muscleSummaryHtml(d.muscle_summary, d.muscle_footprint) +
        '</aside></div>';

      html += fillLogHtml(d.fill_log || { budget_trace: d.budget_trace }, d.pool_counts || _lastPoolCounts);
      _lastPreviewBody = html;
      out.innerHTML = html;
      _previewHasRun = true;
      setReshuffleEnabled(true);
    }).catch(function () {
      if (_lastPreviewBody) {
        out.innerHTML = _lastPreviewBody + '<div class="preview-error">Preview failed</div>';
      } else {
        out.innerHTML = '<div class="preview-error">Preview failed</div>';
      }
    });
  }

  function previewRunSubtype(subtype, minutes, out) {
    // Legacy client path — kept as unused fallback; previewFill uses the API.
    out.innerHTML = '<span class="muted">Use Preview (server fill).</span>';
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

  function intish(v) {
    var n = typeof v === 'number' ? v : Number(v);
    if (!isFinite(n) || Math.floor(n) !== n) return null;
    return n;
  }

  function patternPayload(p) {
    return {
      kind: p.kind || 'run',
      subtype: p.subtype || '',
      duration_min_lo: p.duration_min_lo != null ? p.duration_min_lo : 0,
      duration_min_hi: p.duration_min_hi != null ? p.duration_min_hi : 120,
      name: p.name || '',
      priority: p.priority != null ? p.priority : 10,
      recipe: p.recipe || {},
      active: p.active !== false,
    };
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
          { phase: 'warmup', duration_share: 0.15, repeat: null, rest_min: null, target: 'easy', pace_mult: 1.2 },
          { phase: 'main', duration_share: 0.70, repeat: null, rest_min: null, target: 'easy', pace_mult: 1.2 },
          { phase: 'cooldown', duration_share: 0.15, repeat: null, rest_min: null, target: 'easy', pace_mult: 1.2 },
        ],
      },
      active: true,
    };
  }

  function unwrapPatternJson(raw) {
    if (raw == null) return null;
    if (Array.isArray(raw)) {
      return raw.length === 1 && raw[0] && typeof raw[0] === 'object' ? raw[0] : null;
    }
    if (typeof raw !== 'object') return null;
    if (Array.isArray(raw.patterns)) {
      if (raw.patterns.length === 1 && raw.patterns[0] && typeof raw.patterns[0] === 'object') {
        return raw.patterns[0];
      }
      return null;
    }
    return raw;
  }

  function validateStrengthGroup(g) {
    if (!g || typeof g !== 'object') return false;
    if (typeof g.key !== 'string' || !g.key.trim()) return false;
    var pick = g.pick;
    if (!pick || typeof pick !== 'object') return false;
    var n = Number(pick.n);
    if (!isFinite(n) || Math.floor(n) !== n || n < 1) return false;
    if (!Array.isArray(pick.from_tags) || !pick.from_tags.length) return false;
    return pick.from_tags.every(function (t) { return typeof t === 'string' && t.trim(); });
  }

  function validateRecipe(kind, recipe) {
    var checks = [];
    function add(ok, label) { checks.push({ ok: !!ok, label: label }); }

    if (!recipe || typeof recipe !== 'object' || Array.isArray(recipe)) {
      add(false, 'recipe — object required');
      return { ok: false, checks: checks };
    }

    var intent = typeof recipe.intent_template === 'string' ? recipe.intent_template.trim() : '';
    add(!!intent, 'recipe.intent_template — non-empty string');

    var notesOk = recipe.notes_template == null || typeof recipe.notes_template === 'string';
    add(notesOk, 'recipe.notes_template — string or null');

    if (kind === 'run') {
      var blocks = Array.isArray(recipe.blocks) ? recipe.blocks : null;
      var blocksOk = !!blocks && blocks.length > 0;
      add(blocksOk, 'recipe.blocks — non-empty array for run');
      var shareSum = 0;
      var phasesOk = blocksOk && blocks.every(function (b) {
        if (!b || typeof b !== 'object') return false;
        if (RUN_PHASES.indexOf(b.phase) === -1) return false;
        var share = Number(b.duration_share);
        if (!isFinite(share) || share <= 0) return false;
        shareSum += share;
        return true;
      });
      add(phasesOk, 'blocks — each phase in ' + RUN_PHASES.join('/') + ' with duration_share > 0');
      add(phasesOk && Math.abs(shareSum - 1) <= 0.05, 'block duration_share sum ≈ 1.0 (now ' +
        (phasesOk ? shareSum.toFixed(2) : '—') + ')');
    } else if (kind === 'strength') {
      var groups = Array.isArray(recipe.groups) ? recipe.groups : [];
      var bands = Array.isArray(recipe.bands) ? recipe.bands : [];
      var hasGroups = groups.length > 0 && groups.every(validateStrengthGroup);
      var hasBands = bands.length > 0 && bands.every(function (band) {
        if (!band || typeof band !== 'object') return false;
        var lo = intish(band.duration_min_lo);
        var hi = intish(band.duration_min_hi);
        if (lo == null || hi == null || hi < lo) return false;
        return Array.isArray(band.groups) && band.groups.length > 0 &&
          band.groups.every(validateStrengthGroup);
      });
      add(hasGroups || hasBands, 'recipe.groups and/or recipe.bands — at least one valid set');
      if (recipe.focus_bias != null) {
        var bias = recipe.focus_bias;
        var biasOk = bias && typeof bias === 'object' &&
          typeof bias.primary_tag === 'string' && FOCUS.indexOf(bias.primary_tag) !== -1 &&
          isFinite(Number(bias.primary)) && isFinite(Number(bias.accessory));
        add(biasOk, 'recipe.focus_bias — primary_tag + primary/accessory fractions');
      }
    }

    return { ok: checks.every(function (c) { return c.ok; }), checks: checks };
  }

  function validatePatternDraft(obj) {
    var checks = [];
    function add(ok, label) { checks.push({ ok: !!ok, label: label }); }

    if (!obj || typeof obj !== 'object' || Array.isArray(obj)) {
      add(false, 'Root must be one pattern object (or { "patterns": [ … ] } with a single item)');
      return { ok: false, checks: checks, body: null, preview: null };
    }

    var name = typeof obj.name === 'string' ? obj.name.trim() : '';
    add(!!name, 'name — non-empty string');

    var kind = typeof obj.kind === 'string' ? obj.kind.trim() : '';
    add(kind === 'run' || kind === 'strength', 'kind — run or strength');

    var subtype = typeof obj.subtype === 'string' ? obj.subtype.trim() : '';
    add(!!subtype, 'subtype — non-empty string');

    var lo = intish(obj.duration_min_lo);
    var hi = intish(obj.duration_min_hi);
    add(lo != null && lo >= 0, 'duration_min_lo — integer ≥ 0');
    add(hi != null && hi >= 0 && (lo == null || hi >= lo), 'duration_min_hi — integer ≥ duration_min_lo');

    var pri = intish(obj.priority);
    add(pri != null && pri >= 0 && pri <= 999, 'priority — integer 0–999');

    var active = obj.active === undefined ? true : obj.active;
    add(typeof active === 'boolean', 'active — boolean (defaults true if omitted)');

    var recipeRes = validateRecipe(kind, obj.recipe);
    checks = checks.concat(recipeRes.checks);

    var ok = checks.every(function (c) { return c.ok; });
    var body = ok ? {
      kind: kind,
      subtype: subtype,
      duration_min_lo: lo,
      duration_min_hi: hi,
      name: name,
      priority: pri,
      recipe: obj.recipe,
      active: active,
    } : null;

    var preview = {
      id: _patSelectedId || '',
      name: name || '(unnamed)',
      kind: kind || '—',
      subtype: subtype || '—',
      duration_min_lo: lo != null ? lo : 0,
      duration_min_hi: hi != null ? hi : 120,
      priority: pri != null ? pri : 10,
      recipe: obj.recipe && typeof obj.recipe === 'object' ? obj.recipe : {},
      active: typeof active === 'boolean' ? active : true,
    };

    return { ok: ok, checks: checks, body: body, preview: preview };
  }

  function parsePatternEditor() {
    var ta = document.getElementById('pat-json');
    var rawText = (ta.value || '').trim();
    if (!rawText) {
      return {
        ok: false,
        parseError: 'Paste pattern JSON',
        checks: [{ ok: false, label: 'JSON — paste a complete pattern object' }],
        body: null,
        preview: null,
      };
    }
    var parsed;
    try {
      parsed = JSON.parse(rawText);
    } catch (err) {
      return {
        ok: false,
        parseError: 'Invalid JSON: ' + (err && err.message ? err.message : 'parse error'),
        checks: [{ ok: false, label: 'JSON — must parse (fix / trailing commas / quotes)' }],
        body: null,
        preview: null,
      };
    }
    var unwrapped = unwrapPatternJson(parsed);
    if (!unwrapped) {
      return {
        ok: false,
        parseError: 'Expected one pattern object (or catalog with a single patterns[] item)',
        checks: [{ ok: false, label: 'Shape — one pattern object, not an empty / multi-item catalog' }],
        body: null,
        preview: null,
      };
    }
    return validatePatternDraft(unwrapped);
  }

  function strengthGroupPreviewRow(g) {
    if (!g) return '';
    var pick = g.pick || {};
    var detail = [
      'n=' + (pick.n != null ? pick.n : '?'),
      (pick.from_tags || []).join(', '),
      g.time_share != null ? 't ' + g.time_share : '',
      g.tss_share != null ? 'tss ' + g.tss_share : '',
      Array.isArray(g.format_choices) ? g.format_choices.join('/') : '',
    ].filter(Boolean).join(' · ');
    return '<div class="prow"><span class="pk">' + esc(g.label || g.key || '?') +
      '</span><span class="pd">' + esc(detail) + '</span></div>';
  }

  function patternPreviewHtml(p) {
    var recipe = p.recipe || {};
    var html = '<div class="pat-json-preview' + (p.active ? '' : ' off') + '">' +
      '<div class="ph">' + esc(p.name || '(unnamed)') + '</div>' +
      '<div class="meta">' +
        esc(p.kind) + ' · ' + esc(p.subtype) + ' · ' +
        esc(p.duration_min_lo) + '–' + esc(p.duration_min_hi) + ' min · pri ' + esc(p.priority) +
        (p.active ? '' : ' · inactive') +
      '</div>';
    if (recipe.intent_template) {
      html += '<div class="intent">' + esc(recipe.intent_template) + '</div>';
    }
    if (p.kind === 'run' && Array.isArray(recipe.blocks)) {
      recipe.blocks.forEach(function (b) {
        if (!b) return;
        var detail = [
          (b.duration_share != null ? (Number(b.duration_share) * 100).toFixed(0) + '%' : ''),
          b.repeat != null ? '×' + b.repeat : '',
          b.rest_min != null ? 'rest ' + b.rest_min + 'm' : '',
          b.target || '',
          b.pace_mult != null ? 'pace ×' + b.pace_mult : '',
        ].filter(Boolean).join(' · ');
        html += '<div class="prow"><span class="pk">' + esc(b.phase || '?') +
          '</span><span class="pd">' + esc(detail) + '</span></div>';
      });
    } else if (p.kind === 'strength') {
      if (Array.isArray(recipe.bands) && recipe.bands.length) {
        recipe.bands.forEach(function (band, i) {
          html += '<div class="bandh">Band ' + (i + 1) + ': ' +
            esc(band.duration_min_lo) + '–' + esc(band.duration_min_hi) + ' min</div>';
          (band.groups || []).forEach(function (g) {
            html += strengthGroupPreviewRow(g);
          });
        });
      } else if (Array.isArray(recipe.groups)) {
        recipe.groups.forEach(function (g) {
          html += strengthGroupPreviewRow(g);
        });
      }
      if (recipe.focus_bias && recipe.focus_bias.primary_tag) {
        html += '<div class="prow"><span class="pk">focus</span><span class="pd">' +
          esc(recipe.focus_bias.primary_tag) + ' ' +
          esc(recipe.focus_bias.primary) + '/' + esc(recipe.focus_bias.accessory) +
          '</span></div>';
      }
    }
    html += '</div>';
    return html;
  }

  function renderPatternEditorPreview() {
    var result = parsePatternEditor();
    var ta = document.getElementById('pat-json');
    var previewEl = document.getElementById('pat-card-preview');
    var checksEl = document.getElementById('pat-json-checks');
    var saveBtn = document.getElementById('pat-btn-save');

    ta.classList.toggle('invalid', !result.ok);

    if (result.preview) {
      var tmp = document.createElement('div');
      tmp.innerHTML = patternPreviewHtml(result.preview);
      var built = tmp.firstChild;
      previewEl.className = built.className;
      previewEl.innerHTML = built.innerHTML;
    } else {
      previewEl.className = 'pat-json-preview';
      previewEl.innerHTML = '<div class="ex-json-placeholder">' +
        esc(result.parseError || 'Paste pattern JSON to preview the recipe.') +
        '</div>';
    }

    checksEl.innerHTML = (result.checks || []).map(function (c) {
      return '<li class="' + (c.ok ? 'ok' : 'bad') + '">' +
        '<span class="mark">' + (c.ok ? '✓' : '✗') + '</span>' +
        '<span>' + esc(c.label) + '</span></li>';
    }).join('');

    saveBtn.disabled = !result.ok;
    return result;
  }

  function fillPatternForm(p) {
    p = p || blankPattern();
    _patSelectedId = p.id || null;
    document.getElementById('pat-edit-id').value = p.id || '';
    document.getElementById('pat-editor-title').textContent = p.id ? 'Edit pattern' : 'New pattern';
    document.getElementById('pat-json').value = JSON.stringify(patternPayload(p), null, 2);
    patFb('', true);
    renderPatternEditorPreview();
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
    var result = renderPatternEditorPreview();
    if (!result.ok) {
      patFb(result.parseError || 'Fix the checklist before saving', false);
      return null;
    }
    return result.body;
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
    var result = parsePatternEditor();
    var base = result.body || (result.preview ? patternPayload(result.preview) : null);
    if (!base || !base.name) {
      patFb('Need a named pattern to duplicate', false);
      return;
    }
    base.name = String(base.name).replace(/\s*\(copy\)\s*$/, '') + ' (copy)';
    document.getElementById('pat-edit-id').value = '';
    _patSelectedId = null;
    document.getElementById('pat-editor-title').textContent = 'New pattern';
    document.getElementById('pat-json').value = JSON.stringify(patternPayload(base), null, 2);
    renderPatternEditorPreview();
    patFb('Duplicated — edit the name and Save', true);
  }

  function formatPatternJson() {
    var ta = document.getElementById('pat-json');
    var raw = (ta.value || '').trim();
    if (!raw) return;
    try {
      var parsed = JSON.parse(raw);
      ta.value = JSON.stringify(parsed, null, 2);
      renderPatternEditorPreview();
      patFb('Formatted', true);
    } catch (err) {
      patFb('Cannot format — fix JSON first', false);
      renderPatternEditorPreview();
    }
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

  function exerciseTemplateExample() {
    return {
      name: 'Bulgarian split squat',
      groups: ['superset', 'emom'],
      focus_tags: ['lower', 'full'],
      body_parts: [
        { part: 'quad', ratio: 0.5 },
        { part: 'glute', ratio: 0.5 },
      ],
      tss_weight: 1.1,
      default_sets: 3,
      default_reps: '8/side',
      default_load: 'moderate DB',
      active: true,
    };
  }

  function patternTemplateExample() {
    return {
      kind: 'run',
      subtype: 'easy_run',
      duration_min_lo: 0,
      duration_min_hi: 120,
      name: 'Easy aerobic (scaled)',
      priority: 10,
      active: true,
      recipe: {
        intent_template: 'Easy aerobic run',
        notes_template: null,
        blocks: [
          { phase: 'warmup', duration_share: 0.15, repeat: null, rest_min: null, target: 'easy', pace_mult: 1.2 },
          { phase: 'main', duration_share: 0.7, repeat: null, rest_min: null, target: 'easy, conversational', pace_mult: 1.2 },
          { phase: 'cooldown', duration_share: 0.15, repeat: null, rest_min: null, target: 'easy', pace_mult: 1.2 },
        ],
      },
    };
  }

  function triggerJsonDownload(filename, data) {
    var blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }

  function downloadExercisesJson() {
    api('/api/admin/plan-library/export').then(function (res) {
      if (!res.ok || !res.data) {
        alert((res.data && res.data.detail) || 'Download failed');
        return;
      }
      var stamp = (res.data.exported_at || '').slice(0, 10) || 'catalog';
      triggerJsonDownload('plan-exercises-' + stamp + '.json', {
        version: res.data.version || 1,
        scope: 'exercises',
        exported_at: res.data.exported_at || null,
        instructions:
          'Ask Claude to return JSON with an exercises array (same fields as example). ' +
          'Upsert matches by name. Omit ids. Keep groups/focus_tags from the allowed sets; body_parts ratios ≈ 1.0.',
        example: exerciseTemplateExample(),
        exercises: res.data.exercises || [],
      });
    }).catch(function () { alert('Download failed'); });
  }

  function downloadPatternsJson() {
    api('/api/admin/plan-library/export').then(function (res) {
      if (!res.ok || !res.data) {
        alert((res.data && res.data.detail) || 'Download failed');
        return;
      }
      var stamp = (res.data.exported_at || '').slice(0, 10) || 'catalog';
      triggerJsonDownload('plan-patterns-' + stamp + '.json', {
        version: res.data.version || 1,
        scope: 'patterns',
        exported_at: res.data.exported_at || null,
        instructions:
          'Ask Claude to return JSON with a patterns array (same fields as example). ' +
          'Upsert matches by kind + subtype + name. Omit ids. Run recipes use blocks; strength recipes use bands and/or groups.',
        example: patternTemplateExample(),
        patterns: res.data.patterns || [],
      });
    }).catch(function () { alert('Download failed'); });
  }

  var _importScope = 'exercises';

  function openImportModal(scope) {
    _importScope = scope === 'patterns' ? 'patterns' : 'exercises';
    var el = document.getElementById('import-modal');
    var title = document.getElementById('import-title');
    var help = document.getElementById('import-help');
    var ta = document.getElementById('import-json');
    if (_importScope === 'patterns') {
      title.textContent = 'Import patterns JSON';
      help.innerHTML =
        'Paste Claude output (or a downloaded template). Shape: ' +
        '<code>{ "patterns": [ … ] }</code> or a bare array. ' +
        'Upsert matches by <strong>kind + subtype + name</strong>.';
      ta.placeholder = '{ "patterns": [ … ] }';
    } else {
      title.textContent = 'Import exercises JSON';
      help.innerHTML =
        'Paste Claude output (or a downloaded template). Shape: ' +
        '<code>{ "exercises": [ … ] }</code> or a bare array. ' +
        'Upsert matches by <strong>name</strong>.';
      ta.placeholder = '{ "exercises": [ … ] }';
    }
    el.hidden = false;
    el.classList.add('open');
    document.getElementById('import-result').textContent = '';
    document.getElementById('import-result').className = 'import-meta';
  }

  function closeImportModal() {
    var el = document.getElementById('import-modal');
    el.classList.remove('open');
    el.hidden = true;
  }

  function runImport() {
    var raw = (document.getElementById('import-json').value || '').trim();
    var resultEl = document.getElementById('import-result');
    resultEl.className = 'import-meta';
    if (!raw) {
      resultEl.className = 'import-meta err';
      resultEl.textContent = 'Paste JSON first (or choose a file).';
      return;
    }
    var parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (e) {
      resultEl.className = 'import-meta err';
      resultEl.textContent = 'Invalid JSON: ' + e.message;
      return;
    }
    var payload = { exercises: [], patterns: [], mode: 'upsert' };
    if (Array.isArray(parsed)) {
      if (_importScope === 'patterns') payload.patterns = parsed;
      else payload.exercises = parsed;
    } else if (parsed && typeof parsed === 'object') {
      if (_importScope === 'patterns') {
        if (Array.isArray(parsed.patterns)) payload.patterns = parsed.patterns;
        else if (parsed.catalog && Array.isArray(parsed.catalog.patterns)) {
          payload.patterns = parsed.catalog.patterns;
        }
      } else {
        if (Array.isArray(parsed.exercises)) payload.exercises = parsed.exercises;
        else if (parsed.catalog && Array.isArray(parsed.catalog.exercises)) {
          payload.exercises = parsed.catalog.exercises;
        }
      }
    }
    var items = _importScope === 'patterns' ? payload.patterns : payload.exercises;
    if (!items.length) {
      resultEl.className = 'import-meta err';
      resultEl.textContent = _importScope === 'patterns'
        ? 'No patterns found in JSON.'
        : 'No exercises found in JSON.';
      return;
    }
    payload.mode = document.getElementById('import-upsert').checked ? 'upsert' : 'create';
    resultEl.textContent = 'Importing…';
    api('/api/admin/plan-library/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }).then(function (res) {
      if (!res.ok) {
        resultEl.className = 'import-meta err';
        resultEl.textContent = (res.data && res.data.detail) || 'Import failed';
        return;
      }
      var d = res.data || {};
      var bucket = _importScope === 'patterns' ? (d.patterns || {}) : (d.exercises || {});
      var label = _importScope === 'patterns' ? 'Patterns' : 'Exercises';
      var lines = [
        label + ' — created ' + (bucket.created || 0) +
          ', updated ' + (bucket.updated || 0) +
          ', skipped ' + (bucket.skipped || 0),
      ];
      var errs = bucket.errors || [];
      if (errs.length) {
        lines.push('Errors (' + errs.length + '):');
        errs.slice(0, 8).forEach(function (e) {
          lines.push('  · ' + JSON.stringify(e));
        });
        if (errs.length > 8) lines.push('  · …');
      }
      resultEl.className = errs.length ? 'import-meta err' : 'import-meta ok';
      resultEl.textContent = lines.join('\n');
      if (_importScope === 'patterns') loadPatterns();
      else loadExercises();
    }).catch(function () {
      resultEl.className = 'import-meta err';
      resultEl.textContent = 'Import failed';
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
  document.getElementById('btn-format-json').onclick = formatExerciseJson;
  document.getElementById('ex-json').addEventListener('input', function () {
    renderExerciseEditorPreview();
  });
  document.getElementById('btn-seed').onclick = function () { seed(false); };
  document.getElementById('btn-reset').onclick = function () { seed(true); };
  document.getElementById('btn-ex-download').onclick = downloadExercisesJson;
  document.getElementById('btn-ex-import').onclick = function () { openImportModal('exercises'); };
  document.getElementById('btn-pat-download').onclick = downloadPatternsJson;
  document.getElementById('btn-pat-import').onclick = function () { openImportModal('patterns'); };
  document.getElementById('import-cancel').onclick = closeImportModal;
  document.getElementById('import-run').onclick = runImport;
  document.getElementById('import-modal').addEventListener('click', function (e) {
    if (e.target === e.currentTarget) closeImportModal();
  });
  document.getElementById('import-file').addEventListener('change', function (e) {
    var file = e.target.files && e.target.files[0];
    if (!file) return;
    var reader = new FileReader();
    reader.onload = function () {
      document.getElementById('import-json').value = String(reader.result || '');
    };
    reader.readAsText(file);
    e.target.value = '';
  });
  document.getElementById('btn-preview').onclick = function () { previewFill({ reshuffle: false }); };
  document.getElementById('btn-reshuffle').onclick = function () { previewFill({ reshuffle: true }); };
  document.getElementById('preview-subtype').addEventListener('change', refreshPoolSummary);
  document.getElementById('preview-dur').addEventListener('change', refreshPoolSummary);
  document.getElementById('search').addEventListener('input', renderExerciseList);
  document.getElementById('hide-inactive').addEventListener('change', renderExerciseList);

  document.getElementById('pat-btn-save').onclick = savePattern;
  document.getElementById('pat-btn-delete').onclick = removePattern;
  document.getElementById('pat-btn-dup').onclick = duplicatePattern;
  document.getElementById('pat-btn-new').onclick = function () { fillPatternForm(blankPattern()); };
  document.getElementById('pat-btn-format-json').onclick = formatPatternJson;
  document.getElementById('pat-json').addEventListener('input', function () {
    renderPatternEditorPreview();
  });
  document.getElementById('pat-search').addEventListener('input', renderPatternList);
  document.getElementById('pat-hide-inactive').addEventListener('change', renderPatternList);

  window.addEventListener('hashchange', function () {
    var t = tabFromUrl();
    if (t !== _tab) setTab(t);
  });

  fillExerciseForm(blankExercise());
  fillPatternForm(blankPattern());
  applyPreviewConfig(loadPreviewConfig());
  setReshuffleEnabled(false);
  setTab(tabFromUrl());
  loadExercises();

  // Test hooks (Preview tab unit checks)
  window.__planLibraryPreview = {
    budgetTraceHtml: budgetTraceHtml,
    poolCountIndex: poolCountIndex,
    renderPoolSummary: renderPoolSummary,
  };
  window.__planLibraryExercises = {
    renderExerciseList: renderExerciseList,
    GROUP_SECTION_ORDER: GROUP_SECTION_ORDER,
    PART_COLORS: PART_COLORS,
    validateExerciseDraft: validateExerciseDraft,
    unwrapExerciseJson: unwrapExerciseJson,
    parseExerciseEditor: parseExerciseEditor,
  };
  window.__planLibraryPatterns = {
    validatePatternDraft: validatePatternDraft,
    unwrapPatternJson: unwrapPatternJson,
    parsePatternEditor: parsePatternEditor,
  };
})();
