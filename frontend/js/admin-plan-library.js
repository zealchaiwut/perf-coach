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
  var BODY_PARTS = Object.keys(PART_COLORS);
  // Keep in sync with backend/services/plan_body_parts.py PLAN_BODY_PART_ALIASES.
  var PART_ALIASES = {
    quads: 'quad', quadriceps: 'quad',
    glutes: 'glute', gluteus: 'glute',
    hamstrings: 'hamstring',
    calves: 'calf', achilles: 'calf',
    hips: 'hip',
    'hip flexor': 'hip_flexor', 'hip flexors': 'hip_flexor', hip_flexors: 'hip_flexor',
    shoulders: 'shoulder', delts: 'shoulder', deltoids: 'shoulder',
    obliques: 'oblique',
    abs: 'core', abdominals: 'core',
    traps: 'trapezius',
    pecs: 'chest', pectorals: 'chest', pectoral: 'chest',
    back: 'upper_back', lats: 'upper_back',
    arms: 'biceps', arm: 'biceps',
    forearms: 'grip', forearm: 'grip',
  };
  BODY_PARTS.forEach(function (k) { PART_ALIASES[k] = k; });

  function normalizeBodyPart(raw) {
    if (raw == null) return null;
    var key = String(raw).trim().toLowerCase().replace(/-/g, '_');
    key = key.replace(/\s+/g, ' ');
    if (PART_ALIASES[key]) return PART_ALIASES[key];
    var under = key.replace(/ /g, '_');
    if (PART_ALIASES[under]) return PART_ALIASES[under];
    var spaced = key.replace(/_/g, ' ');
    if (PART_ALIASES[spaced]) return PART_ALIASES[spaced];
    return null;
  }

  /** Merge [{part,ratio}] through aliases; null if empty/invalid structure. */
  function normalizeBodyPartsList(parts) {
    if (!Array.isArray(parts) || !parts.length) return null;
    var merged = {};
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      if (!p || typeof p !== 'object') return null;
      var canon = normalizeBodyPart(p.part);
      var ratio = Number(p.ratio);
      if (!canon || !isFinite(ratio) || ratio <= 0) return null;
      merged[canon] = (merged[canon] || 0) + ratio;
    }
    return Object.keys(merged).map(function (k) {
      return { part: k, ratio: Math.round(merged[k] * 10000) / 10000 };
    });
  }
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
    return window.AppCommon.escapeHtml(s);
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

    var rawParts = Array.isArray(obj.body_parts) ? obj.body_parts : null;
    var parts = rawParts ? normalizeBodyPartsList(rawParts) : null;
    var partSum = 0;
    var partsOk = !!parts && parts.length > 0;
    if (partsOk) {
      parts.forEach(function (p) { partSum += Number(p.ratio); });
    }
    add(partsOk, 'body_parts — [{ part, ratio }] known part (plurals ok: glutes→glute), ratio > 0');
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
        return { part: p.part, ratio: Math.round(Number(p.ratio) * 100) / 100 };
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
    var normalized = normalizeBodyPartsList(parts) || [];
    var entries = normalized.map(function (p) {
      return [p.part, Number(p.ratio)];
    }).filter(function (x) { return x[0] && isFinite(x[1]) && x[1] > 0; });
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

  // Preview pane HTML — shared with Plan suggestions (js/lib/plan-fill-preview.js)
  var _PFP = window.PlanFillPreview;
  if (!_PFP) {
    console.error('PlanFillPreview missing — load js/lib/plan-fill-preview.js first');
    _PFP = {
      sessionPaneHtml: function () { return '<div class="preview-error">Preview module missing</div>'; },
      budgetTraceHtml: function () { return ''; },
      poolCountIndex: function () { return { byKey: {}, byLabel: {} }; },
      ensureStyles: function () {},
    };
  }
  function budgetTraceHtml(trace, poolCounts) { return _PFP.budgetTraceHtml(trace, poolCounts); }
  function poolCountIndex(poolCounts) { return _PFP.poolCountIndex(poolCounts); }

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
    // Prefer the selected pattern's id when on Patterns (exact matcher);
    // otherwise resolve by subtype via the library-level endpoint.
    var url;
    if (_patSelectedId) {
      url = '/api/admin/plan-patterns/' + encodeURIComponent(_patSelectedId) +
        '/pool-counts?duration_min=' + cfg.duration_minutes;
    } else {
      url = '/api/admin/plan-library/pool-counts?subtype=' +
        encodeURIComponent(cfg.subtype) + '&duration_min=' + cfg.duration_minutes;
    }
    api(url).then(function (res) {
      if (!res.ok) {
        renderPoolSummary(null);
        return;
      }
      _lastPoolCounts = res.data;
      renderPoolSummary(res.data, cfg.subtype);
    }).catch(function () { renderPoolSummary(null); });
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

      html += _PFP.sessionPaneHtml({
        exercises: exs,
        blocks: blocks,
        workout_type: d.workout_type || (isRun ? 'run' : 'strength'),
        muscle_summary: d.muscle_summary,
        muscle_footprint: d.muscle_footprint,
        fill_log: d.fill_log || { budget_trace: d.budget_trace },
        pool_counts: d.pool_counts || _lastPoolCounts,
      }, { alwaysMuscle: true });
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
    return pick.from_tags.every(function (t) {
      return typeof t === 'string' && GROUPS.indexOf(t) !== -1;
    });
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

  function strengthPatternTemplateExample() {
    return {
      kind: 'strength',
      subtype: 'full',
      duration_min_lo: 30,
      duration_min_hi: 75,
      name: 'Full-body strength (band recipe)',
      priority: 20,
      active: true,
      recipe: {
        intent_template: 'Full-body strength',
        notes_template: null,
        focus_bias: { primary_tag: 'full', primary: 0.7, accessory: 0.3 },
        bands: [
          {
            duration_min_lo: 30,
            duration_min_hi: 75,
            groups: [
              { key: 'warmup', pick: { n: 2, from_tags: ['warmup'] } },
              { key: 'main', pick: { n: 2, from_tags: ['heavy_compound'] } },
              { key: 'accessories', pick: { n: 2, from_tags: ['accessories'] } },
              { key: 'cooldown', pick: { n: 1, from_tags: ['cooldown'] } },
            ],
          },
        ],
      },
    };
  }

  function triggerTextDownload(filename, text, mime) {
    var blob = new Blob([text], { type: mime || 'text/plain;charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
  }

  /** LLM paste prompt: template + allowed vocab + current catalog for Bulk import. */
  function buildPlanLibraryLlmPrompt(catalog) {
    var stamp = ((catalog && catalog.exported_at) || '').slice(0, 10) || 'catalog';
    var payload = {
      version: (catalog && catalog.version) || 1,
      exported_at: (catalog && catalog.exported_at) || null,
      exercises: (catalog && catalog.exercises) || [],
      patterns: (catalog && catalog.patterns) || [],
    };
    var lines = [
      '# Plan library — Claude bulk-edit prompt',
      '',
      'You are editing the perf-coach **plan library** (exercise pool + session patterns).',
      '',
      '## How to return your answer',
      '',
      '1. Reply with a **single JSON object** (no markdown fences unless the chat UI needs them).',
      '2. Shape:',
      '```json',
      '{',
      '  "exercises": [ /* exercise objects */ ],',
      '  "patterns": [ /* pattern objects */ ]',
      '}',
      '```',
      '3. You may omit `exercises` or `patterns` if unchanged; include only rows you add or change.',
      '4. Paste that JSON into Admin → Plan library → **Bulk import JSON**.',
      '   Upsert matches exercises by **name**, patterns by **kind + subtype + name**. Omit ids.',
      '',
      '## Allowed vocabularies (invalid values are rejected on import)',
      '',
      '- **groups** (exercise `groups[]` and strength recipe `pick.from_tags[]`): ' + GROUPS.join(', '),
      '- **focus_tags** / focus_bias.primary_tag: ' + FOCUS.join(', '),
      '- **body_parts[].part** (canonical): ' + BODY_PARTS.join(', '),
      '  Plurals / aliases also accepted and normalized: glutes→glute, calves→calf, quads→quad, hamstrings→hamstring, hips→hip, shoulders→shoulder, abs→core, traps→trapezius, pecs→chest, back→upper_back, arms→biceps, …',
      '- **run recipe blocks[].phase**: ' + RUN_PHASES.join(', '),
      '- **pattern kind**: ' + PAT_KINDS.join(', '),
      '',
      '## Exercise rules',
      '',
      '- `groups` and `focus_tags`: non-empty arrays; every value from the allow-lists above.',
      '- `body_parts`: non-empty `[{ "part", "ratio" }]`; ratios > 0 and sum ≈ 1.0 (±0.05). Prefer singular canonical keys; plurals are remapped on import.',
      '- `default_sets`: integer 1–12; `default_reps` / `default_load`: non-empty strings.',
      '- `tss_weight`: number with 0 < n ≤ 3; `active`: boolean (default true).',
      '',
      '### Exercise template',
      '```json',
      JSON.stringify(exerciseTemplateExample(), null, 2),
      '```',
      '',
      '## Pattern rules',
      '',
      '- `kind` is `run` or `strength`; `subtype` + `name` required.',
      '- Run recipes: `blocks` with phases + `duration_share` summing ≈ 1.0.',
      '- Strength recipes: `groups` and/or `bands` of pick groups; `from_tags` must be valid **groups**.',
      '',
      '### Run pattern template',
      '```json',
      JSON.stringify(patternTemplateExample(), null, 2),
      '```',
      '',
      '### Strength pattern template',
      '```json',
      JSON.stringify(strengthPatternTemplateExample(), null, 2),
      '```',
      '',
      '## Current catalog (reference — export ' + stamp + ')',
      '',
      'Use this as context. Prefer editing existing names over inventing duplicates.',
      '```json',
      JSON.stringify(payload, null, 2),
      '```',
      '',
    ];
    return lines.join('\n');
  }

  function downloadLlmPrompt() {
    api('/api/admin/plan-library/export').then(function (res) {
      if (!res.ok || !res.data) {
        alert((res.data && res.data.detail) || 'Download failed');
        return;
      }
      var stamp = (res.data.exported_at || '').slice(0, 10) || 'catalog';
      triggerTextDownload(
        'plan-library-llm-prompt-' + stamp + '.md',
        buildPlanLibraryLlmPrompt(res.data),
        'text/markdown;charset=utf-8'
      );
    }).catch(function () { alert('Download failed'); });
  }

  /** Tab-scoped catalog JSON for Bulk import (exercises | patterns | all). */
  function downloadCatalogJson(scope) {
    api('/api/admin/plan-library/export').then(function (res) {
      if (!res.ok || !res.data) {
        alert((res.data && res.data.detail) || 'Export failed');
        return;
      }
      var stamp = (res.data.exported_at || '').slice(0, 10) || 'catalog';
      var out = {
        version: res.data.version || 1,
        exported_at: res.data.exported_at || null,
      };
      var filename;
      if (scope === 'exercises') {
        out.exercises = res.data.exercises || [];
        filename = 'plan-exercises-' + stamp + '.json';
      } else if (scope === 'patterns') {
        out.patterns = res.data.patterns || [];
        filename = 'plan-patterns-' + stamp + '.json';
      } else {
        out.exercises = res.data.exercises || [];
        out.patterns = res.data.patterns || [];
        filename = 'plan-library-' + stamp + '.json';
      }
      triggerTextDownload(
        filename,
        JSON.stringify(out, null, 2),
        'application/json'
      );
    }).catch(function () { alert('Export failed'); });
  }

  /** Normalize paste/file JSON into { exercises, patterns } for bulk import. */
  function normalizeImportBundle(parsed) {
    var exercises = [];
    var patterns = [];
    if (Array.isArray(parsed)) {
      // Bare array: infer by shape (pattern has kind+subtype+recipe).
      parsed.forEach(function (row) {
        if (!row || typeof row !== 'object') return;
        if (row.kind && row.subtype && row.recipe) patterns.push(row);
        else if (row.name) exercises.push(row);
      });
      return { exercises: exercises, patterns: patterns };
    }
    if (!parsed || typeof parsed !== 'object') {
      return { exercises: [], patterns: [] };
    }
    if (Array.isArray(parsed.exercises)) exercises = parsed.exercises.slice();
    else if (parsed.catalog && Array.isArray(parsed.catalog.exercises)) {
      exercises = parsed.catalog.exercises.slice();
    }
    if (Array.isArray(parsed.patterns)) patterns = parsed.patterns.slice();
    else if (parsed.catalog && Array.isArray(parsed.catalog.patterns)) {
      patterns = parsed.catalog.patterns.slice();
    }
    // Single pattern / exercise object (no wrapper arrays)
    if (!exercises.length && !patterns.length) {
      if (parsed.kind && parsed.subtype && parsed.recipe) patterns = [parsed];
      else if (parsed.name && (parsed.groups || parsed.body_parts || parsed.focus_tags)) {
        exercises = [parsed];
      } else if (parsed.name && !parsed.kind) {
        exercises = [parsed];
      }
    }
    return { exercises: exercises, patterns: patterns };
  }

  function openImportModal() {
    var el = document.getElementById('import-modal');
    var title = document.getElementById('import-title');
    var help = document.getElementById('import-help');
    var ta = document.getElementById('import-json');
    title.textContent = 'Bulk import JSON';
    help.innerHTML =
      'Paste Claude\'s catalog JSON — ' +
      '<code>{ "exercises": [ … ], "patterns": [ … ] }</code>. ' +
      'Either array may be omitted. A bare array or single object is fine too. ' +
      'Upsert matches exercises by <strong>name</strong>, patterns by ' +
      '<strong>kind + subtype + name</strong>. Invalid groups / focus_tags / body parts are rejected. ' +
      'Body-part plurals (glutes, calves, …) are normalized to singular keys.';
    ta.placeholder =
      '{ "exercises": [ { "name": "…" } ], "patterns": [ { "kind": "strength", "subtype": "…", "name": "…" } ] }';
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

  function openBodyPartsModal() {
    var el = document.getElementById('body-parts-modal');
    var list = document.getElementById('body-parts-list');
    var meta = document.getElementById('body-parts-result');
    meta.textContent = '';
    meta.className = 'import-meta';
    list.innerHTML = '<p class="fld-hint">Loading…</p>';
    el.hidden = false;
    el.classList.add('open');
    api('/api/admin/plan-library/body-parts').then(function (res) {
      if (!res.ok || !res.data || !Array.isArray(res.data.parts)) {
        list.innerHTML = '<p class="fld-hint" style="color:#b91c1c;">Failed to load catalog.</p>';
        return;
      }
      list.innerHTML = res.data.parts.map(function (row) {
        var aliases = (row.aliases || []).slice().sort();
        return '<div class="bp-row">' +
          '<span class="bp-swatch" style="background:' + esc(row.color) + '"></span>' +
          '<div class="bp-meta">' +
            '<div class="bp-key">' + esc(row.key) + '</div>' +
            (aliases.length
              ? '<div class="bp-aliases">also: ' + aliases.map(esc).join(', ') + '</div>'
              : '<div class="bp-aliases muted">canonical only</div>') +
          '</div></div>';
      }).join('');
    }).catch(function () {
      list.innerHTML = '<p class="fld-hint" style="color:#b91c1c;">Failed to load catalog.</p>';
    });
  }

  function closeBodyPartsModal() {
    var el = document.getElementById('body-parts-modal');
    el.classList.remove('open');
    el.hidden = true;
  }

  function runNormalizeBodyParts() {
    var meta = document.getElementById('body-parts-result');
    meta.className = 'import-meta';
    meta.textContent = 'Normalizing pool…';
    api('/api/admin/plan-library/normalize-body-parts', { method: 'POST' }).then(function (res) {
      if (!res.ok || !res.data) {
        meta.className = 'import-meta err';
        meta.textContent = (res.data && res.data.detail) || 'Normalize failed';
        return;
      }
      meta.className = 'import-meta ok';
      var errN = (res.data.errors || []).length;
      meta.textContent =
        'Updated ' + res.data.updated + ' exercise(s); skipped ' + res.data.skipped +
        (errN ? ' (' + errN + ' with invalid parts — see server list)' : '') + '.';
      loadExercises();
    }).catch(function () {
      meta.className = 'import-meta err';
      meta.textContent = 'Normalize failed';
    });
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
    var bundle = normalizeImportBundle(parsed);
    if (!bundle.exercises.length && !bundle.patterns.length) {
      resultEl.className = 'import-meta err';
      resultEl.textContent =
        'No exercises or patterns found — use { "exercises": […], "patterns": […] }, ' +
        'a bare array, or one object.';
      return;
    }

    var clientErrors = [];
    var cleanExercises = [];
    bundle.exercises.forEach(function (row, i) {
      var v = validateExerciseDraft(row);
      if (!v.ok) {
        var fails = (v.checks || []).filter(function (c) { return !c.ok; })
          .map(function (c) { return c.label; });
        clientErrors.push('exercise[' + i + '] ' + (row && row.name ? row.name : '') +
          ': ' + (fails[0] || 'invalid'));
        return;
      }
      cleanExercises.push(v.body);
    });
    var cleanPatterns = [];
    bundle.patterns.forEach(function (row, i) {
      var v = validatePatternDraft(row);
      if (!v.ok) {
        var fails = (v.checks || []).filter(function (c) { return !c.ok; })
          .map(function (c) { return c.label; });
        clientErrors.push('pattern[' + i + '] ' + (row && row.name ? row.name : '') +
          ': ' + (fails[0] || 'invalid'));
        return;
      }
      cleanPatterns.push(v.body);
    });
    if (clientErrors.length) {
      resultEl.className = 'import-meta err';
      resultEl.textContent =
        'Validation failed — fix before import (' + clientErrors.length + '):\n' +
        clientErrors.slice(0, 12).map(function (e) { return '  · ' + e; }).join('\n') +
        (clientErrors.length > 12 ? '\n  · …' : '');
      return;
    }

    var payload = {
      exercises: cleanExercises,
      patterns: cleanPatterns,
      mode: document.getElementById('import-upsert').checked ? 'upsert' : 'create',
    };
    resultEl.textContent =
      'Importing ' + cleanExercises.length + ' exercise(s), ' +
      cleanPatterns.length + ' pattern(s)…';
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
      var ex = d.exercises || {};
      var pat = d.patterns || {};
      var lines = [
        'Exercises — created ' + (ex.created || 0) +
          ', updated ' + (ex.updated || 0) +
          ', skipped ' + (ex.skipped || 0),
        'Patterns — created ' + (pat.created || 0) +
          ', updated ' + (pat.updated || 0) +
          ', skipped ' + (pat.skipped || 0),
      ];
      var errs = [].concat(ex.errors || [], pat.errors || []);
      if (errs.length) {
        lines.push('Errors (' + errs.length + '):');
        errs.slice(0, 8).forEach(function (e) {
          lines.push('  · ' + JSON.stringify(e));
        });
        if (errs.length > 8) lines.push('  · …');
      }
      resultEl.className = errs.length ? 'import-meta err' : 'import-meta ok';
      resultEl.textContent = lines.join('\n');
      if (cleanExercises.length) loadExercises();
      if (cleanPatterns.length) loadPatterns();
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
  document.getElementById('btn-ex-download').onclick = downloadLlmPrompt;
  document.getElementById('btn-ex-export-json').onclick = function () { downloadCatalogJson('exercises'); };
  document.getElementById('btn-ex-import').onclick = openImportModal;
  document.getElementById('btn-ex-body-parts').onclick = openBodyPartsModal;
  document.getElementById('btn-pat-download').onclick = downloadLlmPrompt;
  document.getElementById('btn-pat-export-json').onclick = function () { downloadCatalogJson('patterns'); };
  document.getElementById('btn-pat-import').onclick = openImportModal;
  document.getElementById('import-cancel').onclick = closeImportModal;
  document.getElementById('import-run').onclick = runImport;
  document.getElementById('import-modal').addEventListener('click', function (e) {
    if (e.target === e.currentTarget) closeImportModal();
  });
  document.getElementById('body-parts-cancel').onclick = closeBodyPartsModal;
  document.getElementById('body-parts-normalize').onclick = runNormalizeBodyParts;
  document.getElementById('body-parts-modal').addEventListener('click', function (e) {
    if (e.target === e.currentTarget) closeBodyPartsModal();
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
    PART_ALIASES: PART_ALIASES,
    normalizeBodyPart: normalizeBodyPart,
    normalizeBodyPartsList: normalizeBodyPartsList,
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
