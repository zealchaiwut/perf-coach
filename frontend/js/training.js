(function () {
  'use strict';

  // Shared format helpers (issue #531) — single home for type normalization,
  // pace formatting, and segment↔exercise mapping. training.html loads
  // lib/training-format.js before this script.
  var TF = window.TrainingFormat;

  var currentUserId = null;
  var currentView = 'new';
  var editingWorkoutId = null;
  var dragSrcIdx = null;
  var WORKOUT_TYPES = ['Strength', 'Running', 'Race', 'Yoga'];

  function isEmbedded() {
    return !!document.getElementById('dp-form-wrap');
  }

  function getSaveBtn() {
    return document.getElementById('dp-save-btn') || document.getElementById('save-workout-btn');
  }

  function setSaveBtnLabel(text) {
    var btn = getSaveBtn();
    if (btn) btn.textContent = text;
  }

  // ── Helpers ──────────────────────────────────────────────────────────────────

  function todayIso() {
    var d = new Date();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return d.getFullYear() + '-' + m + '-' + day;
  }

  function relativeDate(iso) {
    var now = new Date();
    var then = new Date(iso + 'T00:00:00');
    var diffDays = Math.round((new Date(todayIso() + 'T00:00:00') - then) / 86400000);
    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return diffDays + ' days ago';
    return then.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  function typeIcon(t) {
    var icons = { Strength: '🏋', Running: '🏃', Race: '🏁', Yoga: '🧘' };
    return icons[t] || '⚡';
  }

  function showToast(msg, isError) {
    UIStates.showToast(msg, isError);
  }

  // ── Tab switching ─────────────────────────────────────────────────────────────

  function switchTab(name) {
    currentView = name;
    document.querySelectorAll('.training-tab').forEach(function (btn) {
      btn.classList.toggle('active', btn.dataset.tab === name);
    });
    document.getElementById('view-new').style.display = name === 'new' ? '' : 'none';
    document.getElementById('view-history').style.display = name === 'history' ? '' : 'none';
    if (name === 'history' && currentUserId) loadHistory();
  }

  // ── Type chips ────────────────────────────────────────────────────────────────

  // Only Strength + Running are active for now; the rest are greyed out.
  var DISABLED_TYPES = { 'Race': 1, 'Yoga': 1 };

  function initChips() {
    var container = document.getElementById('type-chips');
    var customInput = document.getElementById('custom-type-input');
    container.innerHTML = '';
    WORKOUT_TYPES.forEach(function (type) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'type-chip' + (DISABLED_TYPES[type] ? ' type-chip-disabled' : '');
      btn.dataset.value = type;
      btn.textContent = type;
      if (DISABLED_TYPES[type]) {
        btn.disabled = true;
        btn.title = 'Coming soon';
      } else {
        btn.addEventListener('click', function () { selectChip(type); });
      }
      container.appendChild(btn);
    });
    var customBtn = document.createElement('button');
    customBtn.type = 'button';
    customBtn.className = 'type-chip type-chip-disabled';
    customBtn.dataset.value = '__custom__';
    customBtn.textContent = '+ Custom';
    customBtn.disabled = true;
    customBtn.title = 'Coming soon';
    container.appendChild(customBtn);
    selectChip('Strength');
    customInput.addEventListener('input', function () {});
  }

  function selectChip(value) {
    var customInput = document.getElementById('custom-type-input');
    document.querySelectorAll('.type-chip').forEach(function (b) {
      b.classList.toggle('active', b.dataset.value === value);
    });
    customInput.style.display = value === '__custom__' ? 'block' : 'none';
    if (value !== '__custom__') customInput.value = '';
    updateRunVisibility();
    maybeRefreshAutoName();
  }

  function getSelectedType() {
    var active = document.querySelector('.type-chip.active');
    if (!active) return 'Strength';
    if (active.dataset.value === '__custom__') {
      return document.getElementById('custom-type-input').value.trim() || 'Custom';
    }
    return active.dataset.value;
  }

  function setSelectedType(type) {
    var key = TF.normalizeType(type);
    if (key === 'run') type = 'Running';
    else if (key === 'lift') type = 'Strength';
    var known = WORKOUT_TYPES.indexOf(type) !== -1;
    if (known) {
      selectChip(type);
    } else {
      selectChip('__custom__');
      document.getElementById('custom-type-input').value = type;
    }
  }

  // ── Exercise table ─────────────────────────────────────────────────────────────

  // ── Strength exercise builder (per-set) ──────────────────────────────────────
  var SET_TYPES = {
    warmup:  { cls: 'warmup',  badge: 'W', working: false },
    working: { cls: 'working', badge: '',  working: true  },
    drop:    { cls: 'drop',    badge: 'D', working: true  },
    failure: { cls: 'failure', badge: 'F', working: true  },
  };
  var SET_TYPE_ORDER = ['working', 'warmup', 'drop', 'failure'];

  // One payload row per exercise: sets_json detail + a summary from the top
  // working set (back-compat + PR detection).
  function getExerciseRows() {
    var cards = document.querySelectorAll('#exercises-tbody .exercise');
    var result = [];
    cards.forEach(function (card, i) {
      var sets = [];
      card.querySelectorAll('.set-row').forEach(function (r) {
        var w = parseFloat(r.querySelector('.set-weight').value);
        var reps = parseInt(r.querySelector('.set-reps').value, 10);
        var rpe = parseFloat(r.querySelector('.set-rpe').value);
        var rest = parseInt(r.querySelector('.set-rest').value, 10);
        sets.push({
          type: r.dataset.setType || 'working',
          weight: isFinite(w) ? w : null,
          reps: isFinite(reps) ? reps : null,
          rpe: isFinite(rpe) ? rpe : null,
          rest: isFinite(rest) ? rest : null,
        });
      });
      var working = sets.filter(function (s) { return SET_TYPES[s.type] && SET_TYPES[s.type].working; });
      var top = null;
      working.forEach(function (s) { if (s.weight != null && (!top || s.weight > top.weight)) top = s; });
      var first = sets[0] || {};
      result.push({
        display_order: i,
        name: card.querySelector('.ex-name').value.trim(),
        sets: working.length || null,
        reps: top ? top.reps : (first.reps != null ? first.reps : null),
        weight_kg: top ? top.weight : (first.weight != null ? first.weight : null),
        rpe: (top && top.rpe != null) ? Math.round(top.rpe) : null,
        duration: null,
        sets_json: sets.length ? JSON.stringify(sets) : null,
      });
    });
    return result;
  }

  function _relabelSets(card) {
    if (!card) return;
    var workingIdx = 0;
    card.querySelectorAll('.set-row').forEach(function (r) {
      var type = r.dataset.setType || 'working';
      var cfg = SET_TYPES[type] || SET_TYPES.working;
      var badge = r.querySelector('.set-badge');
      badge.className = 'set-badge ' + cfg.cls;
      if (type === 'working') { workingIdx += 1; badge.textContent = String(workingIdx); }
      else badge.textContent = cfg.badge;
    });
  }

  function _updateExerciseVolume(card) {
    if (!card) return;
    var vol = 0;
    card.querySelectorAll('.set-row').forEach(function (r) {
      var w = parseFloat(r.querySelector('.set-weight').value) || 0;
      var reps = parseInt(r.querySelector('.set-reps').value, 10) || 0;
      vol += w * reps;
    });
    var el = card.querySelector('.ex-vol strong');
    if (el) el.textContent = vol ? (Math.round(vol).toLocaleString() + ' kg') : '—';
  }

  function recomputeStrengthTotals() {
    var vol = 0, total = 0, working = 0, topW = 0, topReps = 0;
    document.querySelectorAll('#exercises-tbody .exercise').forEach(function (card) {
      card.querySelectorAll('.set-row').forEach(function (r) {
        var w = parseFloat(r.querySelector('.set-weight').value) || 0;
        var reps = parseInt(r.querySelector('.set-reps').value, 10) || 0;
        vol += w * reps; total += 1;
        var type = r.dataset.setType || 'working';
        if (SET_TYPES[type] && SET_TYPES[type].working) working += 1;
        if (w > topW) { topW = w; topReps = reps; }
      });
      _updateExerciseVolume(card);
    });
    var set = function (id, t) { var e = document.getElementById(id); if (e) e.textContent = t; };
    set('str-volume', vol ? Math.round(vol).toLocaleString() : '0');
    set('str-sets', String(total));
    set('str-sets-sub', working + ' working');
    var e1 = (topW && topReps) ? Math.round(topW * (1 + topReps / 30)) : null;
    set('str-e1rm', e1 ? (e1 + ' kg') : '—');
  }

  function addSetRow(setTable, sd) {
    sd = sd || {};
    var card = setTable.closest('.exercise');
    var row = document.createElement('div');
    row.className = 'set-row';
    row.dataset.setType = SET_TYPES[sd.type] ? sd.type : 'working';
    function v(x) { return (x != null && x !== '') ? x : ''; }
    row.innerHTML =
      '<button type="button" class="set-badge" title="Cycle set type"></button>' +
      '<div class="set-cell"><input type="number" class="set-in set-weight" inputmode="decimal" step="0.5" min="0" placeholder="—" value="' + v(sd.weight) + '"></div>' +
      '<div class="set-cell"><input type="number" class="set-in set-reps" inputmode="numeric" min="0" placeholder="—" value="' + v(sd.reps) + '"></div>' +
      '<div class="set-cell rpe-cell"><input type="number" class="set-in set-rpe" inputmode="decimal" min="1" max="10" step="0.5" placeholder="—" value="' + v(sd.rpe) + '"></div>' +
      '<div class="set-cell"><input type="number" class="set-in set-rest" inputmode="numeric" min="0" placeholder="—" value="' + v(sd.rest) + '"><span class="u">s</span></div>' +
      '<button type="button" class="set-x" title="Remove set">✕</button>';
    row.querySelector('.set-badge').addEventListener('click', function () {
      var idx = SET_TYPE_ORDER.indexOf(row.dataset.setType);
      row.dataset.setType = SET_TYPE_ORDER[(idx + 1) % SET_TYPE_ORDER.length];
      _relabelSets(card); recomputeStrengthTotals();
    });
    row.querySelector('.set-x').addEventListener('click', function () {
      row.remove(); _relabelSets(card); recomputeStrengthTotals();
    });
    row.querySelectorAll('input').forEach(function (inp) { inp.addEventListener('input', recomputeStrengthTotals); });
    setTable.insertBefore(row, setTable.querySelector('.add-set'));
  }

  function addExerciseRow(data) {
    var list = document.getElementById('exercises-tbody');
    var card = document.createElement('div');
    card.className = 'exercise';
    card.innerHTML =
      '<div class="exercise-head">' +
        '<span class="grip" title="Reorder">⠿</span>' +
        '<div class="ex-icon">🏋</div>' +
        '<div class="ex-name-wrap"><input type="text" class="ex-input ex-name" placeholder="Exercise name" list="exercise-name-suggestions" value="' + (data && data.name ? escapeAttr(data.name) : '') + '"></div>' +
        '<div class="ex-vol">volume<strong>—</strong></div>' +
        '<button type="button" class="remove-row-btn ex-remove" title="Remove exercise">✕</button>' +
      '</div>' +
      '<div class="set-table">' +
        '<div class="set-cols"><span>Set</span><span class="r">Weight</span><span class="r">Reps</span><span class="r rpe-cell">RPE</span><span class="r">Rest</span><span></span></div>' +
        '<button type="button" class="add-set"><span aria-hidden="true">+</span> Add set</button>' +
      '</div>';
    list.appendChild(card);
    var setTable = card.querySelector('.set-table');
    card.querySelector('.add-set').addEventListener('click', function () { addSetRow(setTable, { type: 'working' }); _relabelSets(card); recomputeStrengthTotals(); });
    card.querySelector('.ex-remove').addEventListener('click', function () { card.remove(); recomputeStrengthTotals(); });
    card.querySelector('.ex-name').addEventListener('input', recomputeStrengthTotals);

    var seeded = false;
    if (data && data.sets_json) {
      try { var arr = JSON.parse(data.sets_json); if (Array.isArray(arr) && arr.length) { arr.forEach(function (sd) { addSetRow(setTable, sd); }); seeded = true; } } catch (e) {}
    }
    if (!seeded && data && (data.sets != null || data.weight_kg != null || data.reps != null)) {
      var n = (data.sets != null && data.sets > 0) ? data.sets : 1;
      for (var k = 0; k < n; k++) addSetRow(setTable, { type: 'working', weight: data.weight_kg, reps: data.reps, rpe: data.rpe });
      seeded = true;
    }
    if (!seeded) addSetRow(setTable, { type: 'working' });
    _relabelSets(card);
    recomputeStrengthTotals();
    if (!data || !data.name) card.querySelector('.ex-name').focus();
  }

  function rowIndex(tr) {
    return Array.from(tr.parentElement.children).indexOf(tr);
  }

  function escapeAttr(s) {
    return String(s).replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ── Run details: structured segment builder ───────────────────────────────────

  // Run detection routes through the shared normalizeType so the editor and
  // the log agree on what counts as a run (issue #531; "Race" normalizes to
  // "run" just as the log already treats it).
  function isRunType(t) {
    return TF.normalizeType(t) === 'run';
  }

  function runActive() { return isRunType(getSelectedType()); }

  function updateRunVisibility() {
    var run = runActive();
    var runSec = document.getElementById('run-section');
    var exSec = document.querySelector('.exercises-section');
    if (runSec) runSec.style.display = run ? '' : 'none';
    if (exSec) exSec.style.display = run ? 'none' : '';
    if (run) { recomputeRunPace(); recomputeSegments(); }
  }

  function intFieldVal(id) {
    var el = document.getElementById(id);
    if (!el) return null;
    var v = el.value.trim();
    if (v === '') return null;
    var n = parseInt(v, 10);
    return isNaN(n) ? null : n;
  }

  function getRunDistanceKm() {
    var v = document.getElementById('run-distance').value.trim();
    if (v === '') return null;
    var n = parseFloat(v);
    return isNaN(n) ? null : n;
  }

  function getRunDurationSeconds() {
    var h = intFieldVal('run-dur-h') || 0;
    var m = intFieldVal('run-dur-m') || 0;
    var s = intFieldVal('run-dur-s') || 0;
    var total = h * 3600 + m * 60 + s;
    return total > 0 ? total : null;
  }

  function recomputeRunPace() {
    var el = document.getElementById('run-pace');
    if (!el) return;
    var pace = TF.formatPace(getRunDurationSeconds(), getRunDistanceKm());
    if (pace) {
      el.textContent = pace + ' /km';
      el.classList.remove('is-empty');
    } else {
      el.textContent = '—';
      el.classList.add('is-empty');
    }
  }

  function trimNum(n) {
    return parseFloat(n.toFixed(2)).toString();
  }

  // Segment types come from the shared module (issue #531). Every row carries:
  // value + km/min unit toggle + pace + HR. 'block' rows (Intervals) add a
  // sets× multiplier; drag a standalone Rest segment where needed.
  var SEG_TYPES = TF.SEG_TYPES;

  // Built-in starting points; users tweak then "Save as template" for their own.
  var RUN_TEMPLATES = {
    easy: [
      { type: 'warmup',   value: 10,  unit: 'min' },
      { type: 'easy',     value: 5,   unit: 'km'  },
      { type: 'cooldown', value: 5,   unit: 'min' },
    ],
    intervals: [
      { type: 'warmup',    value: 1,   unit: 'km' },
      { type: 'intervals', sets: 4, value: 0.4, unit: 'km' },
      { type: 'cooldown',  value: 1,   unit: 'km' },
    ],
    tempo: [
      { type: 'warmup',   value: 10, unit: 'min' },
      { type: 'tempo',    value: 20, unit: 'min' },
      { type: 'cooldown', value: 10, unit: 'min' },
    ],
  };

  // When the user types totals directly, segment sums stop overwriting them.
  var _totalsTouched = false;
  var _segDragSrc = null;

  // "5:30" → 330 s/km; bare number → minutes/km. null = empty, NaN = invalid.
  function parsePaceInput(str) {
    str = (str || '').trim();
    if (str === '') return null;
    var m = /^(\d+):([0-5]\d)$/.exec(str);
    if (m) return parseInt(m[1], 10) * 60 + parseInt(m[2], 10);
    if (/^\d+(\.\d+)?$/.test(str)) return Math.round(parseFloat(str) * 60);
    return NaN;
  }

  // Format an already-computed seconds-per-km value (issue #531: delegates to
  // the shared pace formatter; empty string keeps the segment input blank).
  function fmtPaceSec(sec) {
    return TF.formatPace(sec, 1) || '';
  }

  function addSegmentRow(type, data) {
    var cfg = SEG_TYPES[type];
    if (!cfg) return;
    data = data || {};
    var list = document.getElementById('segments-list');
    var row = document.createElement('div');
    row.className = 'seg-row';
    row.draggable = true;
    row.dataset.segType = type;

    var unit = data.unit === 'min' ? 'min' : 'km';
    row.dataset.unit = unit;

    var inputs = '';
    if (cfg.mode === 'block') {
      inputs +=
        '<input type="number" class="seg-sets" inputmode="numeric" min="1" placeholder="4" value="' + (data.sets != null ? data.sets : '') + '"> ×';
    }
    inputs +=
      '<input type="number" class="seg-val" inputmode="decimal" min="0" step="' + (unit === 'min' ? '1' : '0.1') + '" placeholder="—" value="' + (data.value != null ? data.value : '') + '">' +
      '<span class="seg-unit-toggle" role="group" aria-label="Unit">' +
        '<button type="button" class="seg-unit' + (unit === 'km' ? ' active' : '') + '" data-unit="km">km</button>' +
        '<button type="button" class="seg-unit' + (unit === 'min' ? ' active' : '') + '" data-unit="min">min</button>' +
      '</span>' +
      '<input type="text" class="seg-pace" inputmode="numeric" placeholder="pace" title="Pace min/km, e.g. 5:30" value="' + (data.paceSec != null ? fmtPaceSec(data.paceSec) : '') + '">' +
      '<span class="seg-suffix">/km</span>' +
      '<input type="number" class="seg-hr" inputmode="numeric" min="20" max="250" placeholder="HR" title="Avg heart rate" value="' + (data.hr != null ? data.hr : '') + '">';

    row.innerHTML =
      '<span class="seg-handle" title="Drag to reorder">⠿</span>' +
      '<span class="seg-type">' + cfg.label + '</span>' +
      '<span class="seg-inputs">' + inputs + '</span>' +
      '<button type="button" class="remove-row-btn" title="Remove segment">✕</button>';

    row.querySelector('.remove-row-btn').addEventListener('click', function () {
      row.remove();
      recomputeSegments();
    });
    row.querySelectorAll('input').forEach(function (inp) {
      inp.addEventListener('input', recomputeSegments);
    });
    row.querySelectorAll('.seg-unit').forEach(function (ub) {
      ub.addEventListener('click', function () {
        row.dataset.unit = ub.dataset.unit;
        row.querySelectorAll('.seg-unit').forEach(function (b) {
          b.classList.toggle('active', b === ub);
        });
        var valEl = row.querySelector('.seg-val');
        if (valEl) valEl.step = ub.dataset.unit === 'min' ? '1' : '0.1';
        recomputeSegments();
      });
    });

    // Drag-and-drop reordering (same affordance as the exercise table)
    row.addEventListener('dragstart', function (e) {
      _segDragSrc = row;
      e.dataTransfer.effectAllowed = 'move';
      row.classList.add('dragging');
    });
    row.addEventListener('dragend', function () {
      row.classList.remove('dragging');
      document.querySelectorAll('.seg-row').forEach(function (r) { r.classList.remove('drag-over'); });
      _segDragSrc = null;
    });
    row.addEventListener('dragover', function (e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      document.querySelectorAll('.seg-row').forEach(function (r) { r.classList.remove('drag-over'); });
      row.classList.add('drag-over');
    });
    row.addEventListener('drop', function (e) {
      e.preventDefault();
      if (!_segDragSrc || _segDragSrc === row) return;
      var rect = row.getBoundingClientRect();
      var after = e.clientY > rect.top + rect.height / 2;
      row.parentNode.insertBefore(_segDragSrc, after ? row.nextSibling : row);
      recomputeSegments();
    });

    list.appendChild(row);
    return row;
  }

  function seedTemplate(key) {
    var tpl = RUN_TEMPLATES[key];
    if (!tpl) return;
    var list = document.getElementById('segments-list');
    if (list.children.length &&
        !confirm('Replace the current segments with the ' + key + ' template?')) {
      return;
    }
    list.innerHTML = '';
    tpl.forEach(function (seg) { addSegmentRow(seg.type, seg); });
    recomputeSegments();
  }

  // Read one segment row back into a plain object.
  function readSegmentRow(row) {
    var type = row.dataset.segType;
    var cfg = SEG_TYPES[type];
    function num(sel, float) {
      var el = row.querySelector(sel);
      if (!el || el.value.trim() === '') return null;
      var n = float ? parseFloat(el.value) : parseInt(el.value, 10);
      return isNaN(n) ? null : n;
    }
    var paceEl = row.querySelector('.seg-pace');
    return {
      type: type,
      sets: cfg.mode === 'block' ? num('.seg-sets') : null,
      value: num('.seg-val', true),
      unit: row.dataset.unit === 'min' ? 'min' : 'km',
      paceSec: parsePaceInput(paceEl ? paceEl.value : ''),
      hr: num('.seg-hr'),
    };
  }

  function getSegmentObjects() {
    var out = [];
    document.querySelectorAll('#segments-list .seg-row').forEach(function (row) {
      out.push(readSegmentRow(row));
    });
    return out;
  }

  // Resolve one segment to per-unit km + seconds (issue #531: shared helper).
  var segmentDims = TF.segmentDims;

  function segmentTotals() {
    var km = 0, sec = 0;
    getSegmentObjects().forEach(function (s) {
      var d = segmentDims(s);
      if (d.km) km += d.km;
      if (d.sec) sec += d.sec;
    });
    return { km: km, sec: sec };
  }

  // Session profile: one bar per segment, height = effort, width ~ duration.
  var _RL_EFFORT = { warmup: 'easy', easy: 'easy', cooldown: 'easy', tempo: 'tempo', intervals: 'hard', rest: 'recovery' };
  var _RL_EFFORT_H = { easy: 40, tempo: 72, hard: 92, recovery: 26 };

  function renderProfile() {
    var wrap = document.getElementById('run-profile');
    if (!wrap) return;
    var segs = getSegmentObjects();
    if (!segs.length) { wrap.className = 'rl-profile'; wrap.innerHTML = ''; return; }
    var bars = segs.map(function (s) {
      var d = segmentDims(s);
      var w = (d.sec && d.sec > 0) ? d.sec : (d.km && d.km > 0 ? d.km * 300 : 60);
      var eff = _RL_EFFORT[s.type] || 'easy';
      var h = _RL_EFFORT_H[eff] || 40;
      return '<div class="rl-pseg ' + eff + '" style="flex:' + w.toFixed(2) + ';height:' + h + '%"></div>';
    }).join('');
    wrap.className = 'rl-profile has-segs';
    wrap.innerHTML =
      '<div class="rl-profile-bars">' + bars + '</div>' +
      '<div class="rl-profile-legend">' +
        '<span class="rl-zlg"><span class="d" style="background:var(--rl-easy)"></span>Easy</span>' +
        '<span class="rl-zlg"><span class="d" style="background:var(--rl-tempo)"></span>Tempo</span>' +
        '<span class="rl-zlg"><span class="d" style="background:var(--rl-hard)"></span>Hard</span>' +
        '<span class="rl-zlg"><span class="d" style="background:var(--rl-recovery)"></span>Recovery</span>' +
      '</div>';
  }

  function recomputeSegments() {
    var sumEl = document.getElementById('segments-sum');
    if (!sumEl) return;
    renderProfile();
    var rows = document.querySelectorAll('#segments-list .seg-row');
    if (!rows.length) { sumEl.textContent = ''; sumEl.classList.remove('is-mismatch'); return; }

    var t = segmentTotals();

    // Auto-fill totals while the user hasn't taken them over.
    if (!_totalsTouched) {
      if (t.km > 0) document.getElementById('run-distance').value = trimNum(t.km);
      if (t.sec > 0) {
        document.getElementById('run-dur-h').value = Math.floor(t.sec / 3600) || '';
        document.getElementById('run-dur-m').value = Math.floor((t.sec % 3600) / 60) || '';
        document.getElementById('run-dur-s').value = Math.round(t.sec % 60) || '';
      }
      recomputeRunPace();
    }

    var parts = [];
    if (t.km > 0) parts.push(trimNum(t.km) + ' km');
    if (t.sec > 0) parts.push(Math.round(t.sec / 60) + ' min');
    var txt = 'Σ segments: ' + (parts.length ? parts.join(' · ') : '—');

    var total = getRunDistanceKm();
    var mismatch = _totalsTouched && total != null && t.km > 0 && Math.abs(t.km - total) > 0.05;
    if (mismatch) txt = 'Σ segments: ' + trimNum(t.km) + ' of ' + trimNum(total) + ' km total';
    sumEl.textContent = txt;
    sumEl.classList.toggle('is-mismatch', mismatch);
  }

  // Serialize segments into workout_exercises payload rows (issue #531:
  // shared mapping so the editor and the log round-trip segments identically).
  function getSegments() {
    return TF.mapSegmentsToExercises(getSegmentObjects());
  }

  // Map a stored exercise row back to a segment descriptor (for edit/repeat).
  function exerciseToSegment(ex) {
    var name = (ex.name || '').toLowerCase();
    var type = null;
    Object.keys(SEG_TYPES).forEach(function (k) {
      if (SEG_TYPES[k].label.toLowerCase() === name) type = k;
    });
    if (!type) return null; // not a run segment row (e.g. legacy strength exercise)
    var km = ex.distance_km != null ? parseFloat(ex.distance_km) : null;
    var sec = ex.duration_seconds != null ? ex.duration_seconds : null;
    var seg = {
      type: type,
      sets: ex.sets != null ? ex.sets : null,
      hr: ex.avg_hr != null ? ex.avg_hr : null,
      paceSec: (km && sec) ? sec / km : null,
    };
    if (km != null) { seg.value = km; seg.unit = 'km'; }
    else if (sec != null) { seg.value = Math.round(sec / 60); seg.unit = 'min'; }
    else { seg.value = null; seg.unit = 'km'; }
    return seg;
  }

  function resetRunFields() {
    ['run-distance', 'run-dur-h', 'run-dur-m', 'run-dur-s', 'run-avg-hr', 'run-max-hr', 'run-elevation']
      .forEach(function (id) { var e = document.getElementById(id); if (e) e.value = ''; });
    var list = document.getElementById('segments-list');
    if (list) list.innerHTML = '';
    _totalsTouched = false;
    var runErr = document.getElementById('run-error');
    if (runErr) runErr.textContent = '';
    recomputeRunPace();
    recomputeSegments();
  }

  function fillRunFields(workout) {
    document.getElementById('run-distance').value = workout.distance_km != null ? workout.distance_km : '';
    var dur = workout.duration_seconds;
    if (dur != null) {
      var h = Math.floor(dur / 3600);
      var m = Math.floor((dur % 3600) / 60);
      var s = Math.round(dur % 60);
      document.getElementById('run-dur-h').value = h || '';
      document.getElementById('run-dur-m').value = (h || m) ? m : '';
      document.getElementById('run-dur-s').value = s || '';
    }
    document.getElementById('run-avg-hr').value = workout.avg_hr != null ? workout.avg_hr : '';
    document.getElementById('run-max-hr').value = workout.max_hr != null ? workout.max_hr : '';
    document.getElementById('run-elevation').value = workout.elevation_m != null ? workout.elevation_m : '';
    // Stored totals win over segment sums when editing.
    _totalsTouched = true;
    var list = document.getElementById('segments-list');
    list.innerHTML = '';
    (workout.exercises || []).forEach(function (ex) {
      var seg = exerciseToSegment(ex);
      if (seg) addSegmentRow(seg.type, seg);
    });
    recomputeRunPace();
    recomputeSegments();
  }

  // ── Form reset / fill ─────────────────────────────────────────────────────────

  function formatDateForWorkoutName(isoDate) {
    if (!isoDate || !/^\d{4}-\d{2}-\d{2}$/.test(isoDate)) return isoDate || '';
    var p = isoDate.split('-');
    return p[2] + '-' + p[1] + '-' + p[0];
  }

  function defaultWorkoutName(type, isoDate) {
    var d = isoDate || todayIso();
    return (type || 'Workout') + ' ' + formatDateForWorkoutName(d);
  }

  function applyDefaultWorkoutName() {
    var dateEl = document.getElementById('workout-date');
    var nameEl = document.getElementById('workout-name');
    if (!nameEl) return;
    var iso = dateEl && dateEl.value ? dateEl.value : todayIso();
    nameEl.value = defaultWorkoutName(getSelectedType(), iso);
    nameEl.dataset.autoName = '1';
  }

  function maybeRefreshAutoName() {
    var nameEl = document.getElementById('workout-name');
    if (nameEl && nameEl.dataset.autoName === '1') applyDefaultWorkoutName();
  }

  function resetForm() {
    editingWorkoutId = null;
    document.getElementById('workout-name').value = '';
    document.getElementById('workout-date').value = todayIso();
    document.getElementById('workout-remarks').value = '';
    document.getElementById('workout-tss').value = '';
    document.getElementById('exercises-tbody').innerHTML = '';
    document.getElementById('exercises-error').textContent = '';
    document.getElementById('name-error').textContent = '';
    setSaveBtnLabel('Save workout');
    resetRunFields();
    setSelectedType('Strength');
    addExerciseRow(null);
    applyDefaultWorkoutName();
  }

  function fillForm(workout) {
    editingWorkoutId = workout.id;
    var nameEl = document.getElementById('workout-name');
    nameEl.value = workout.name;
    delete nameEl.dataset.autoName;
    document.getElementById('workout-date').value = workout.workout_date;
    document.getElementById('workout-remarks').value = workout.remarks || '';
    document.getElementById('workout-tss').value = workout.tss != null ? workout.tss : '';
    document.getElementById('exercises-tbody').innerHTML = '';
    document.getElementById('exercises-error').textContent = '';
    document.getElementById('name-error').textContent = '';
    setSaveBtnLabel('Save changes');
    resetRunFields();
    setSelectedType(workout.workout_type);
    if (isRunType(workout.workout_type)) {
      fillRunFields(workout);
    } else {
      (workout.exercises || []).forEach(function (ex) { addExerciseRow(ex); });
      if (!workout.exercises || !workout.exercises.length) addExerciseRow(null);
    }
  }

  // ── Validation ────────────────────────────────────────────────────────────────

  function validateRunForm() {
    var valid = true;
    var nameEl = document.getElementById('workout-name');
    var nameErr = document.getElementById('name-error');
    var runErr = document.getElementById('run-error');
    nameErr.textContent = '';
    runErr.textContent = '';

    if (!nameEl.value.trim()) {
      nameErr.textContent = 'Workout name is required.';
      nameEl.focus();
      valid = false;
    }

    var dateVal = document.getElementById('workout-date').value;
    if (!dateVal || !/^\d{4}-\d{2}-\d{2}$/.test(dateVal)) {
      nameErr.textContent = (nameErr.textContent ? nameErr.textContent + ' ' : '') + 'Invalid date.';
      valid = false;
    }

    var dist = getRunDistanceKm();
    var dur = getRunDurationSeconds();
    if (dist == null || dist <= 0) {
      runErr.textContent = 'Enter a distance greater than 0.';
      valid = false;
    } else if (dur == null) {
      runErr.textContent = 'Enter a duration.';
      valid = false;
    }

    ['run-avg-hr', 'run-max-hr'].forEach(function (id) {
      var v = document.getElementById(id).value.trim();
      if (v !== '') {
        var n = parseInt(v, 10);
        if (isNaN(n) || n < 20 || n > 250) {
          runErr.textContent = 'Heart rate must be between 20 and 250.';
          valid = false;
        }
      }
    });

    var segIssue = null;
    getSegmentObjects().forEach(function (s) {
      var cfg = SEG_TYPES[s.type];
      if (cfg.mode === 'block') {
        var empty = s.sets == null && s.value == null;
        if (!empty && (!s.sets || s.sets < 1 || s.value == null || s.value <= 0)) {
          segIssue = 'Intervals need sets ≥ 1 and a rep value.';
        }
      } else if (s.value != null && s.value < 0) {
        segIssue = 'Segment values must be ≥ 0.';
      }
      if (s.paceSec != null && isNaN(s.paceSec)) {
        segIssue = 'Pace must be m:ss per km (e.g. 5:30).';
      }
      if (s.hr != null && (s.hr < 20 || s.hr > 250)) {
        segIssue = 'Segment HR must be between 20 and 250.';
      }
    });
    if (segIssue) {
      runErr.textContent = (runErr.textContent ? runErr.textContent + ' ' : '') + segIssue;
      valid = false;
    }

    return valid;
  }

  function validateForm() {
    if (runActive()) return validateRunForm();

    var valid = true;
    var nameEl = document.getElementById('workout-name');
    var nameErr = document.getElementById('name-error');
    var exErr = document.getElementById('exercises-error');

    nameErr.textContent = '';
    exErr.textContent = '';

    if (!nameEl.value.trim()) {
      nameErr.textContent = 'Workout name is required.';
      nameEl.focus();
      valid = false;
    }

    var rows = getExerciseRows();
    if (!rows.length || !rows.some(function (r) { return r.name; })) {
      exErr.textContent = 'Add at least one exercise.';
      valid = false;
    }

    rows.forEach(function (r) {
      if (r.rpe !== null && (r.rpe < 1 || r.rpe > 10)) {
        exErr.textContent = 'RPE must be between 1 and 10.';
        valid = false;
      }
    });

    var dateVal = document.getElementById('workout-date').value;
    if (!dateVal || !/^\d{4}-\d{2}-\d{2}$/.test(dateVal)) {
      document.getElementById('name-error').textContent = (document.getElementById('name-error').textContent ? document.getElementById('name-error').textContent + ' ' : '') + 'Invalid date.';
      valid = false;
    }

    return valid;
  }

  // ── Type-ahead suggestions ────────────────────────────────────────────────────

  async function loadSuggestions() {
    try {
      var to = todayIso();
      var d = new Date();
      d.setFullYear(d.getFullYear() - 1);
      var from = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');

      // Workout-name datalist from the list endpoint (one request).
      var res = await fetch('/api/workouts?from=' + from + '&to=' + to);
      if (res.ok) {
        var workouts = await res.json();
        if (!workouts.length) {
          // No workout history yet; leave the workout-name datalist empty.
        } else {
          var workoutNames = [];
          var seen = {};
          workouts.forEach(function (w) {
            var n = w.name;
            if (n && !seen[n]) { seen[n] = true; workoutNames.push(n); }
          });

          var wDL = document.getElementById('workout-name-suggestions');
          if (wDL) {
            wDL.innerHTML = '';
            workoutNames.forEach(function (name) {
              var opt = document.createElement('option');
              opt.value = name;
              wDL.appendChild(opt);
            });
          }
        }
      }

      // Exercise-name datalist from the dedicated endpoint (issue #531): a
      // single request replaces the ~10 full workout-detail fetches that used
      // to scale with the number of workouts.
      var exRes = await fetch('/api/exercises/names');
      if (exRes.ok) {
        var exNames = await exRes.json();
        var exDL = document.getElementById('exercise-name-suggestions');
        if (exDL) {
          exDL.innerHTML = '';
          exNames.forEach(function (name) {
            var opt = document.createElement('option');
            opt.value = name;
            exDL.appendChild(opt);
          });
        }
      }
    } catch (e) { /* suggestions are best-effort; never block the form */ }
  }

  // ── Repeat last workout ───────────────────────────────────────────────────────

  async function repeatLastWorkout() {
    var btn = document.getElementById('repeat-last-btn');
    btn.disabled = true;
    try {
      var to = todayIso();
      var d = new Date();
      d.setFullYear(d.getFullYear() - 3);
      var from = d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');

      var res = await fetch('/api/workouts?from=' + from + '&to=' + to);
      if (!res.ok) throw new Error('Server error ' + res.status);
      var workouts = await res.json();

      if (!workouts.length) {
        showToast('No previous workout found.');
        return;
      }

      var fullRes = await fetch('/api/workouts/' + workouts[0].id);
      if (!fullRes.ok) throw new Error('Server error ' + fullRes.status);
      var w = await fullRes.json();

      editingWorkoutId = null;
      document.getElementById('workout-name').value = w.name;
      document.getElementById('workout-date').value = todayIso();
      document.getElementById('workout-remarks').value = w.remarks || '';
      document.getElementById('workout-tss').value = w.tss != null ? w.tss : '';
      document.getElementById('exercises-tbody').innerHTML = '';
      document.getElementById('exercises-error').textContent = '';
      document.getElementById('name-error').textContent = '';
      document.getElementById('save-workout-btn').textContent = 'Save workout';
      setSelectedType(w.workout_type);
      (w.exercises || []).forEach(function (ex) { addExerciseRow(ex); });
      if (!w.exercises || !w.exercises.length) addExerciseRow(null);
      showToast('“' + w.name + '” prefilled — date set to today.');
    } catch (e) {
      showToast('Could not load last workout: ' + e.message, true);
    } finally {
      btn.disabled = false;
    }
  }

  // ── Workout templates ─────────────────────────────────────────────────────────

  async function saveTemplate() {
    var exercises;
    if (runActive()) {
      exercises = getSegments();
      if (!exercises.length) {
        showToast('Add at least one segment before saving a template.', true);
        return;
      }
    } else {
      exercises = getExerciseRows().filter(function (r) { return r.name; });
      if (!exercises.length) {
        showToast('Add at least one exercise before saving a template.', true);
        return;
      }
    }
    var tplName = prompt('Template name:');
    if (!tplName || !tplName.trim()) return;
    try {
      var res = await fetch('/api/workout-templates', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: tplName.trim(), exercises: exercises }),
      });
      if (!res.ok) {
        var err = await res.json().catch(function () { return {}; });
        showToast('Could not save template: ' + (err.detail || res.status), true);
        return;
      }
      showToast('Template "' + tplName.trim() + '" saved!');
    } catch (e) {
      showToast('Could not save template: ' + e.message, true);
    }
  }

  async function openTemplatePicker() {
    var modal = document.getElementById('template-modal');
    var listEl = document.getElementById('template-list');
    listEl.innerHTML = '<p class="loading-msg">Loading…</p>';
    modal.style.display = 'flex';
    try {
      var res = await fetch('/api/workout-templates');
      if (!res.ok) throw new Error('Server error ' + res.status);
      var templates = await res.json();
      if (!templates.length) {
        listEl.innerHTML = '<p class="empty-msg">No templates saved yet.</p>';
        return;
      }
      listEl.innerHTML = '';
      templates.forEach(function (t) {
        var row = document.createElement('div');
        row.style.cssText = 'display:flex;align-items:stretch;gap:0.35rem;margin-bottom:0.4rem;';
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.style.cssText = 'flex:1;text-align:left;padding:0.65rem 0.75rem;border:1px solid var(--border);border-radius:6px;background:#fff;cursor:pointer;font-size:0.9375rem;';
        btn.textContent = t.name + (isRunTemplate(t) ? '  🏃' : '');
        btn.addEventListener('mouseover', function () { btn.style.background = '#f8f9ff'; btn.style.borderColor = '#b3c0f0'; });
        btn.addEventListener('mouseout', function () { btn.style.background = '#fff'; btn.style.borderColor = ''; });
        btn.addEventListener('click', function () {
          modal.style.display = 'none';
          applyTemplate(t);
        });
        var del = document.createElement('button');
        del.type = 'button';
        del.className = 'remove-row-btn';
        del.title = 'Delete template';
        del.textContent = '✕';
        del.addEventListener('click', async function () {
          if (!confirm('Delete template "' + t.name + '"?')) return;
          try {
            var dres = await fetch('/api/workout-templates/' + t.id, { method: 'DELETE' });
            if (!dres.ok && dres.status !== 204) throw new Error('Server error ' + dres.status);
            row.remove();
            if (!listEl.querySelector('div')) {
              listEl.innerHTML = '<p class="empty-msg">No templates saved yet.</p>';
            }
          } catch (de) {
            showToast('Could not delete template: ' + de.message, true);
          }
        });
        row.appendChild(btn);
        row.appendChild(del);
        listEl.appendChild(row);
      });
    } catch (e) {
      listEl.innerHTML = '<p class="error-msg">Failed to load templates: ' + e.message + '</p>';
    }
  }

  // A template is a run template when every row maps to a known segment label.
  function isRunTemplate(template) {
    var exs = template.exercises || [];
    if (!exs.length) return false;
    return exs.every(function (ex) { return exerciseToSegment(ex) !== null; });
  }

  function applyTemplate(template) {
    if (isRunTemplate(template)) {
      setSelectedType('Running');
      var list = document.getElementById('segments-list');
      list.innerHTML = '';
      _totalsTouched = false;
      (template.exercises || []).forEach(function (ex) {
        var seg = exerciseToSegment(ex);
        if (seg) addSegmentRow(seg.type, seg);
      });
      recomputeSegments();
    } else {
      document.getElementById('exercises-tbody').innerHTML = '';
      document.getElementById('exercises-error').textContent = '';
      (template.exercises || []).forEach(function (ex) { addExerciseRow(ex); });
      if (!template.exercises || !template.exercises.length) addExerciseRow(null);
    }
    showToast('Prefilled from template "' + template.name + '".');
  }

  // ── Save workout ──────────────────────────────────────────────────────────────

  async function saveWorkout() {
    if (!validateForm()) return;

    var run = runActive();
    var tssRaw = document.getElementById('workout-tss').value.trim();
    var tssVal = tssRaw !== '' ? parseFloat(tssRaw) : null;
    var payload = {
      name: document.getElementById('workout-name').value.trim(),
      workout_date: document.getElementById('workout-date').value,
      workout_type: getSelectedType(),
      remarks: document.getElementById('workout-remarks').value.trim() || null,
      tss: tssVal,
    };

    if (run) {
      payload.distance_km = getRunDistanceKm();
      payload.duration_seconds = getRunDurationSeconds();
      payload.avg_hr = intFieldVal('run-avg-hr');
      payload.max_hr = intFieldVal('run-max-hr');
      payload.elevation_m = intFieldVal('run-elevation');
      // Run structure (segments) rides in exercises rows; the training-log
      // detail panel renders distance-bearing exercises as intervals.
      payload.exercises = getSegments();
    } else {
      payload.exercises = getExerciseRows().filter(function (r) { return r.name; });
    }

    var btn = getSaveBtn();
    if (btn) btn.disabled = true;

    try {
      var res;
      if (editingWorkoutId) {
        res = await fetch('/api/workouts/' + editingWorkoutId, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        res = await fetch('/api/workouts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }

      if (!res.ok) {
        var err = await res.json().catch(function () { return {}; });
        showToast('Save failed: ' + (err.detail || res.status), true);
        return;
      }

      var saved = await res.json().catch(function () { return {}; });
      showToast(editingWorkoutId ? 'Workout updated!' : 'Workout saved!');

      if (isEmbedded() && window.TrainingEditor && window.TrainingEditor._hooks.onSaved) {
        window.TrainingEditor._hooks.onSaved({
          ok: true,
          data: saved,
          isEdit: !!editingWorkoutId,
        });
        return;
      }

      resetForm();
      var returnParam = new URLSearchParams(location.search).get('return');
      var dest = (returnParam && /^\//.test(returnParam)) ? returnParam : '/log';
      setTimeout(function () { window.location.replace(dest); }, 700);
    } catch (e) {
      showToast('Save failed: ' + e.message, true);
    } finally {
      if (btn) btn.disabled = false;
    }
  }

  // ── History view ──────────────────────────────────────────────────────────────

  async function loadHistory() {
    if (!currentUserId) return;
    var list = document.getElementById('history-list');
    UIStates.setLoading(list);
    try {
      // /api/workouts takes a from/to range (YYYY-MM-DD), not a day count.
      function ymd(d) {
        return d.getFullYear() + '-' +
          String(d.getMonth() + 1).padStart(2, '0') + '-' +
          String(d.getDate()).padStart(2, '0');
      }
      var to = new Date();
      var from = new Date();
      from.setDate(from.getDate() - 30);
      var res = await fetch('/api/workouts?from=' + ymd(from) + '&to=' + ymd(to));
      if (!res.ok) throw new Error('Server error ' + res.status);
      var workouts = await res.json();
      renderHistory(workouts);
    } catch (_) {
      UIStates.setError(list, 'Something went wrong. Please try again.');
    }
  }

  function renderHistory(workouts) {
    var list = document.getElementById('history-list');
    if (!workouts.length) {
      UIStates.setEmpty(list, 'No workouts yet.', '<a href="/training">Log a workout</a>');
      return;
    }
    list.innerHTML = '';
    workouts.forEach(function (w) {
      var row = document.createElement('div');
      row.className = 'history-row';
      var count = w.exercise_count || 0;
      row.innerHTML =
        '<div class="history-main">' +
          '<span class="history-name">' + escapeHtml(w.name) + '</span>' +
          '<span class="history-meta">' +
            '<span class="history-date">' + relativeDate(w.workout_date) + '</span>' +
            '<span class="history-type">' + typeIcon(w.workout_type) + ' ' + escapeHtml(w.workout_type) + '</span>' +
            '<span class="history-count">' + count + ' exercise' + (count !== 1 ? 's' : '') + '</span>' +
          '</span>' +
        '</div>' +
        '<span class="history-chevron">›</span>';
      row.addEventListener('click', function () { openDetail(w); });
      list.appendChild(row);
    });
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Detail modal ──────────────────────────────────────────────────────────────

  async function openDetail(listItem) {
    // The history list omits exercises; fetch the full workout for the modal + edit.
    var workout = listItem;
    try {
      var full = await fetch('/api/workouts/' + listItem.id);
      if (full.ok) workout = await full.json();
    } catch (e) { /* fall back to the list item */ }

    var modal = document.getElementById('detail-modal');
    document.getElementById('detail-title').textContent = workout.name;
    document.getElementById('detail-meta').textContent =
      workout.workout_date + ' · ' + workout.workout_type +
      (workout.remarks ? ' · ' + workout.remarks : '');

    var tbody = document.getElementById('detail-exercises-tbody');
    tbody.innerHTML = '';
    (workout.exercises || []).forEach(function (ex) {
      var tr = document.createElement('tr');
      tr.innerHTML =
        '<td>' + escapeHtml(ex.name) + '</td>' +
        '<td>' + (ex.sets != null ? ex.sets : '—') + '</td>' +
        '<td>' + (ex.reps != null ? ex.reps : '—') + '</td>' +
        '<td>' + (ex.weight_kg != null ? ex.weight_kg + ' kg' : '—') + '</td>' +
        '<td>' + (ex.duration || '—') + '</td>' +
        '<td>' + (ex.rpe != null ? ex.rpe : '—') + '</td>';
      tbody.appendChild(tr);
    });

    modal.dataset.workoutId = workout.id;
    modal.style.display = 'flex';
    document.getElementById('detail-delete-btn').onclick = function () { deleteWorkout(workout.id); };
    document.getElementById('detail-edit-btn').onclick = function () {
      modal.style.display = 'none';
      fillForm(workout);
      switchTab('new');
    };
  }

  async function deleteWorkout(id) {
    if (!confirm('Delete this workout?')) return;
    try {
      var res = await fetch('/api/workouts/' + id, { method: 'DELETE' });
      if (!res.ok) throw new Error('Server error ' + res.status);
      document.getElementById('detail-modal').style.display = 'none';
      showToast('Workout deleted.');
      loadHistory();
    } catch (e) {
      showToast('Delete failed: ' + e.message, true);
    }
  }

  // ── Form wiring (shared by /training page and /log side pane) ───────────────

  function wireFormEvents() {
    var addExBtn = document.getElementById('add-exercise-btn');
    if (addExBtn) addExBtn.addEventListener('click', function () { addExerciseRow(null); });

    ['run-distance', 'run-dur-h', 'run-dur-m', 'run-dur-s'].forEach(function (id) {
      var e = document.getElementById(id);
      if (e) e.addEventListener('input', function () {
        _totalsTouched = true;
        recomputeRunPace();
        recomputeSegments();
      });
    });

    document.querySelectorAll('.seg-tpl-chip').forEach(function (chip) {
      chip.addEventListener('click', function () { seedTemplate(chip.dataset.tpl); });
    });

    var addSegMenu = document.getElementById('add-segment-menu');
    if (addSegMenu) {
      addSegMenu.querySelectorAll('[data-seg]').forEach(function (b) {
        b.addEventListener('click', function () {
          addSegMenu.removeAttribute('open');
          var row = addSegmentRow(b.dataset.seg, null);
          recomputeSegments();
          if (row) { var first = row.querySelector('input'); if (first) first.focus(); }
        });
      });
      document.addEventListener('click', function (e) {
        if (addSegMenu.hasAttribute('open') && !addSegMenu.contains(e.target)) {
          addSegMenu.removeAttribute('open');
        }
      });
    }

    var customType = document.getElementById('custom-type-input');
    if (customType) {
      customType.addEventListener('input', function () {
        updateRunVisibility();
        maybeRefreshAutoName();
      });
    }

    var dateEl = document.getElementById('workout-date');
    if (dateEl) dateEl.addEventListener('change', maybeRefreshAutoName);

    var nameEl = document.getElementById('workout-name');
    if (nameEl) {
      nameEl.addEventListener('input', function () {
        if (nameEl.dataset.autoName === '1') delete nameEl.dataset.autoName;
      });
    }
  }

  function initFormCore() {
    initChips();
    var dateEl = document.getElementById('workout-date');
    if (dateEl && !dateEl.value) dateEl.value = todayIso();
    var exList = document.getElementById('exercises-tbody');
    if (exList && !exList.children.length) addExerciseRow(null);
  }

  window.TrainingEditor = {
    _hooks: {},
    setHooks: function (hooks) { this._hooks = hooks || {}; },
    resetForm: resetForm,
    fillForm: fillForm,
    applyDefaultWorkoutName: applyDefaultWorkoutName,
    defaultWorkoutName: defaultWorkoutName,
    saveWorkout: saveWorkout,
    setEditingId: function (id) { editingWorkoutId = id; },
    init: function () { initFormCore(); wireFormEvents(); },
    loadSuggestions: loadSuggestions,
  };

  // ── Init ──────────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    var onTrainingPage = !!document.getElementById('view-new');
    var onLogPane      = !!document.getElementById('dp-form-wrap');

    if (onTrainingPage || onLogPane) {
      initFormCore();
      wireFormEvents();
    }

    if (!onTrainingPage) return;

    var editId = new URLSearchParams(location.search).get('edit');
    if (editId) {
      fetch('/api/workouts/' + encodeURIComponent(editId))
        .then(function (res) { if (!res.ok) throw new Error('not found'); return res.json(); })
        .then(function (workout) { fillForm(workout); })
        .catch(function () { /* leave default new-workout form */ });
    }

    // Entry point for the /log "Repeat last" action (issue #524): auto-run the
    // existing prefill flow when arriving via /training?repeat=1.
    if (new URLSearchParams(location.search).get('repeat')) {
      repeatLastWorkout();
    }

    document.querySelectorAll('.training-tab').forEach(function (btn) {
      btn.addEventListener('click', function () { switchTab(btn.dataset.tab); });
    });

    var repeatBtn = document.getElementById('repeat-last-btn');
    if (repeatBtn) repeatBtn.addEventListener('click', repeatLastWorkout);

    var saveTemplateBtn = document.getElementById('save-template-btn');
    if (saveTemplateBtn) saveTemplateBtn.addEventListener('click', saveTemplate);

    var templatePickerBtn = document.getElementById('template-picker-btn');
    if (templatePickerBtn) templatePickerBtn.addEventListener('click', openTemplatePicker);

    // More menu: close after choosing an item or clicking outside
    var moreMenu = document.getElementById('more-menu');
    if (moreMenu) {
      moreMenu.querySelectorAll('.more-menu-list button').forEach(function (b) {
        b.addEventListener('click', function () { moreMenu.removeAttribute('open'); });
      });
      document.addEventListener('click', function (e) {
        if (moreMenu.hasAttribute('open') && !moreMenu.contains(e.target)) {
          moreMenu.removeAttribute('open');
        }
      });
    }

    var templateModalClose = document.getElementById('template-modal-close');
    if (templateModalClose) {
      templateModalClose.addEventListener('click', function () {
        document.getElementById('template-modal').style.display = 'none';
      });
    }

    var templateModal = document.getElementById('template-modal');
    if (templateModal) {
      templateModal.addEventListener('click', function (e) {
        if (e.target === this) this.style.display = 'none';
      });
    }

    var saveWorkoutBtn = document.getElementById('save-workout-btn');
    if (saveWorkoutBtn) saveWorkoutBtn.addEventListener('click', saveWorkout);

    var cancelBtn = document.getElementById('cancel-btn');
    if (cancelBtn) cancelBtn.addEventListener('click', function () { resetForm(); });

    var detailCloseBtn = document.getElementById('detail-close-btn');
    if (detailCloseBtn) {
      detailCloseBtn.addEventListener('click', function () {
        document.getElementById('detail-modal').style.display = 'none';
      });
    }

    var detailModal = document.getElementById('detail-modal');
    if (detailModal) {
      detailModal.addEventListener('click', function (e) {
        if (e.target === this) this.style.display = 'none';
      });
    }
  });

  window.addEventListener('userReady', function (e) {
    currentUserId = e.detail.userId;
    loadSuggestions();
  });

  window.addEventListener('userChanged', function (e) {
    currentUserId = e.detail.userId;
    loadSuggestions();
    if (isEmbedded()) return;
    if (currentView === 'history') {
      loadHistory();
    } else {
      resetForm();
    }
  });
}());
