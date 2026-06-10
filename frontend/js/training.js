(function () {
  'use strict';

  var currentUserId = null;
  var currentView = 'new';
  var editingWorkoutId = null;
  var dragSrcIdx = null;
  var WORKOUT_TYPES = ['Strength', 'Running', 'Race', 'Yoga'];

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

  function initChips() {
    var container = document.getElementById('type-chips');
    var customInput = document.getElementById('custom-type-input');
    container.innerHTML = '';
    WORKOUT_TYPES.forEach(function (type) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'type-chip';
      btn.dataset.value = type;
      btn.textContent = type;
      btn.addEventListener('click', function () { selectChip(type); });
      container.appendChild(btn);
    });
    var customBtn = document.createElement('button');
    customBtn.type = 'button';
    customBtn.className = 'type-chip';
    customBtn.dataset.value = '__custom__';
    customBtn.textContent = '+ Custom';
    customBtn.addEventListener('click', function () { selectChip('__custom__'); });
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
    var known = WORKOUT_TYPES.indexOf(type) !== -1;
    if (known) {
      selectChip(type);
    } else {
      selectChip('__custom__');
      document.getElementById('custom-type-input').value = type;
    }
  }

  // ── Exercise table ─────────────────────────────────────────────────────────────

  function getExerciseRows() {
    var rows = document.querySelectorAll('#exercises-tbody tr');
    var result = [];
    rows.forEach(function (row, i) {
      result.push({
        display_order: i,
        name: row.querySelector('.ex-name').value.trim(),
        sets: parseInt(row.querySelector('.ex-sets').value, 10) || null,
        reps: parseInt(row.querySelector('.ex-reps').value, 10) || null,
        weight_kg: parseFloat(row.querySelector('.ex-weight').value) || null,
        duration: row.querySelector('.ex-duration').value.trim() || null,
        rpe: parseInt(row.querySelector('.ex-rpe').value, 10) || null,
      });
    });
    return result;
  }

  function addExerciseRow(data) {
    var tbody = document.getElementById('exercises-tbody');
    var tr = document.createElement('tr');
    tr.draggable = true;
    tr.innerHTML =
      '<td class="drag-handle" title="Drag to reorder">⠿</td>' +
      '<td><input type="text" class="ex-input ex-name" placeholder="Exercise name" list="exercise-name-suggestions" value="' + (data && data.name ? escapeAttr(data.name) : '') + '"></td>' +
      '<td><input type="number" class="ex-input ex-sets" placeholder="—" min="1" value="' + (data && data.sets != null ? data.sets : '') + '"></td>' +
      '<td><input type="number" class="ex-input ex-reps" placeholder="—" min="1" value="' + (data && data.reps != null ? data.reps : '') + '"></td>' +
      '<td><input type="number" class="ex-input ex-weight" placeholder="—" min="0" step="0.5" value="' + (data && data.weight_kg != null ? data.weight_kg : '') + '"></td>' +
      '<td><input type="text" class="ex-input ex-duration" placeholder="—" value="' + (data && data.duration ? escapeAttr(data.duration) : '') + '"></td>' +
      '<td><input type="number" class="ex-input ex-rpe" placeholder="—" min="1" max="10" value="' + (data && data.rpe != null ? data.rpe : '') + '"></td>' +
      '<td><button type="button" class="remove-row-btn" title="Remove exercise">✕</button></td>';

    tr.querySelector('.remove-row-btn').addEventListener('click', function () {
      tr.remove();
    });

    // Tab key advances cells within the row, then jumps to next row's first input
    tr.querySelectorAll('.ex-input').forEach(function (inp, idx, all) {
      inp.addEventListener('keydown', function (e) {
        if (e.key === 'Tab' && !e.shiftKey && idx === all.length - 1) {
          var next = tr.nextElementSibling;
          if (next) {
            e.preventDefault();
            var firstInput = next.querySelector('.ex-input');
            if (firstInput) firstInput.focus();
          }
        }
      });
    });

    // Drag-and-drop reordering
    tr.addEventListener('dragstart', function (e) {
      dragSrcIdx = rowIndex(tr);
      e.dataTransfer.effectAllowed = 'move';
      tr.classList.add('dragging');
    });
    tr.addEventListener('dragend', function () {
      tr.classList.remove('dragging');
      document.querySelectorAll('#exercises-tbody tr').forEach(function (r) {
        r.classList.remove('drag-over');
      });
    });
    tr.addEventListener('dragover', function (e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      document.querySelectorAll('#exercises-tbody tr').forEach(function (r) { r.classList.remove('drag-over'); });
      tr.classList.add('drag-over');
    });
    tr.addEventListener('drop', function (e) {
      e.preventDefault();
      var destIdx = rowIndex(tr);
      if (dragSrcIdx === null || dragSrcIdx === destIdx) return;
      var tbody = document.getElementById('exercises-tbody');
      var rows = Array.from(tbody.querySelectorAll('tr'));
      var srcRow = rows[dragSrcIdx];
      tbody.removeChild(srcRow);
      var refRow = tbody.querySelectorAll('tr')[destIdx] || null;
      tbody.insertBefore(srcRow, refRow);
      dragSrcIdx = null;
    });

    tbody.appendChild(tr);
    tr.querySelector('.ex-name').focus();
  }

  function rowIndex(tr) {
    return Array.from(tr.parentElement.children).indexOf(tr);
  }

  function escapeAttr(s) {
    return String(s).replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ── Run details: structured segment builder ───────────────────────────────────

  function isRunType(t) {
    return /^run(ning)?$/i.test((t || '').trim());
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

  function fmtPace(distKm, durSec) {
    if (!distKm || !durSec || distKm <= 0 || durSec <= 0) return null;
    var secPerKm = durSec / distKm;
    var m = Math.floor(secPerKm / 60);
    var s = Math.round(secPerKm % 60);
    if (s === 60) { m += 1; s = 0; }
    return m + ':' + String(s).padStart(2, '0');
  }

  function recomputeRunPace() {
    var el = document.getElementById('run-pace');
    if (!el) return;
    var pace = fmtPace(getRunDistanceKm(), getRunDurationSeconds());
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

  // Segment types: label + which inputs the row shows.
  // mode 'span'  = distance (km) OR duration (min)
  // mode 'block' = sets × rep distance (m) + rest (m)
  var SEG_TYPES = {
    warmup:    { label: 'Warm-up',   mode: 'span'  },
    easy:      { label: 'Easy run',  mode: 'span'  },
    tempo:     { label: 'Tempo',     mode: 'span'  },
    intervals: { label: 'Intervals', mode: 'block' },
    rest:      { label: 'Rest',      mode: 'span'  },
    cooldown:  { label: 'Cool-down', mode: 'span'  },
  };

  // Built-in starting points; users tweak then "Save as template" for their own.
  var RUN_TEMPLATES = {
    easy: [
      { type: 'warmup',   minutes: 10 },
      { type: 'easy',     km: 5 },
      { type: 'cooldown', minutes: 5 },
    ],
    intervals: [
      { type: 'warmup',    km: 1 },
      { type: 'intervals', sets: 4, repM: 400, restM: 200 },
      { type: 'cooldown',  km: 1 },
    ],
    tempo: [
      { type: 'warmup',   minutes: 10 },
      { type: 'tempo',    minutes: 20 },
      { type: 'cooldown', minutes: 10 },
    ],
  };

  // When the user types totals directly, segment sums stop overwriting them.
  var _totalsTouched = false;
  var _segDragSrc = null;

  function addSegmentRow(type, data) {
    var cfg = SEG_TYPES[type];
    if (!cfg) return;
    data = data || {};
    var list = document.getElementById('segments-list');
    var row = document.createElement('div');
    row.className = 'seg-row';
    row.draggable = true;
    row.dataset.segType = type;

    var inputs;
    if (cfg.mode === 'block') {
      inputs =
        '<input type="number" class="seg-sets" inputmode="numeric" min="1" placeholder="4" value="' + (data.sets != null ? data.sets : '') + '"> ×' +
        ' <input type="number" class="seg-repm" inputmode="numeric" min="50" step="50" placeholder="400" value="' + (data.repM != null ? data.repM : '') + '"> m' +
        ' <span class="seg-or">·</span> rest' +
        ' <input type="number" class="seg-restm" inputmode="numeric" min="0" step="50" placeholder="200" value="' + (data.restM != null ? data.restM : '') + '"> m';
    } else {
      inputs =
        '<input type="number" class="seg-dist" inputmode="decimal" min="0" step="0.1" placeholder="—" value="' + (data.km != null ? data.km : '') + '"> km' +
        ' <span class="seg-or">or</span> ' +
        '<input type="number" class="seg-min" inputmode="numeric" min="0" step="1" placeholder="—" value="' + (data.minutes != null ? data.minutes : '') + '"> min';
    }

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
    if (cfg.mode === 'block') {
      return { type: type, sets: num('.seg-sets'), repM: num('.seg-repm'), restM: num('.seg-restm') };
    }
    return { type: type, km: num('.seg-dist', true), minutes: num('.seg-min') };
  }

  function getSegmentObjects() {
    var out = [];
    document.querySelectorAll('#segments-list .seg-row').forEach(function (row) {
      out.push(readSegmentRow(row));
    });
    return out;
  }

  // Segment sums: distance (km) + duration (s) from whatever is specified.
  function segmentTotals() {
    var km = 0, sec = 0;
    getSegmentObjects().forEach(function (s) {
      if (s.type && SEG_TYPES[s.type].mode === 'block') {
        if (s.sets && s.repM) km += s.sets * (s.repM + (s.restM || 0)) / 1000;
      } else {
        if (s.km) km += s.km;
        if (s.minutes) sec += s.minutes * 60;
      }
    });
    return { km: km, sec: sec };
  }

  function recomputeSegments() {
    var sumEl = document.getElementById('segments-sum');
    if (!sumEl) return;
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

  // Serialize segments into workout_exercises payload rows.
  function getSegments() {
    var out = [];
    getSegmentObjects().forEach(function (s, i) {
      var cfg = SEG_TYPES[s.type];
      var row = { display_order: i, name: cfg.label, sets: null, reps: null, weight_kg: null, duration: null, rpe: null, distance_km: null, duration_seconds: null };
      if (cfg.mode === 'block') {
        if (!s.sets && !s.repM) return; // empty row, skip
        row.sets = s.sets;
        row.distance_km = s.repM != null ? s.repM / 1000 : null;
        if (s.restM != null) row.duration = 'rest ' + s.restM + 'm';
      } else {
        if (s.km == null && s.minutes == null) return; // empty row, skip
        row.distance_km = s.km;
        row.duration_seconds = s.minutes != null ? s.minutes * 60 : null;
      }
      out.push(row);
    });
    return out;
  }

  // Map a stored exercise row back to a segment descriptor (for edit/repeat).
  function exerciseToSegment(ex) {
    var name = (ex.name || '').toLowerCase();
    var type = null;
    Object.keys(SEG_TYPES).forEach(function (k) {
      if (SEG_TYPES[k].label.toLowerCase() === name) type = k;
    });
    if (!type) return null; // not a run segment row (e.g. legacy strength exercise)
    if (SEG_TYPES[type].mode === 'block') {
      var rest = null;
      var m = /rest\s+(\d+)\s*m/i.exec(ex.duration || '');
      if (m) rest = parseInt(m[1], 10);
      return { type: type, sets: ex.sets, repM: ex.distance_km != null ? Math.round(ex.distance_km * 1000) : null, restM: rest };
    }
    return {
      type: type,
      km: ex.distance_km != null ? parseFloat(ex.distance_km) : null,
      minutes: ex.duration_seconds != null ? Math.round(ex.duration_seconds / 60) : null,
    };
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

  function resetForm() {
    editingWorkoutId = null;
    document.getElementById('workout-name').value = '';
    document.getElementById('workout-date').value = todayIso();
    document.getElementById('workout-remarks').value = '';
    document.getElementById('workout-tss').value = '';
    document.getElementById('exercises-tbody').innerHTML = '';
    document.getElementById('exercises-error').textContent = '';
    document.getElementById('name-error').textContent = '';
    document.getElementById('save-workout-btn').textContent = 'Save workout';
    resetRunFields();
    setSelectedType('Strength');
    addExerciseRow(null);
  }

  function fillForm(workout) {
    editingWorkoutId = workout.id;
    document.getElementById('workout-name').value = workout.name;
    document.getElementById('workout-date').value = workout.workout_date;
    document.getElementById('workout-remarks').value = workout.remarks || '';
    document.getElementById('workout-tss').value = workout.tss != null ? workout.tss : '';
    document.getElementById('exercises-tbody').innerHTML = '';
    document.getElementById('exercises-error').textContent = '';
    document.getElementById('name-error').textContent = '';
    document.getElementById('save-workout-btn').textContent = 'Save changes';
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
        var empty = s.sets == null && s.repM == null && s.restM == null;
        if (!empty && (!s.sets || s.sets < 1 || !s.repM || s.repM <= 0)) {
          segIssue = 'Intervals need sets ≥ 1 and a rep distance.';
        }
      } else {
        if (s.km != null && s.km < 0) segIssue = 'Segment distance must be ≥ 0.';
        if (s.minutes != null && s.minutes < 0) segIssue = 'Segment minutes must be ≥ 0.';
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

      var res = await fetch('/api/workouts?from=' + from + '&to=' + to);
      if (!res.ok) return;
      var workouts = await res.json();
      if (!workouts.length) return;

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

      var detailIds = workouts.slice(0, 10).map(function (w) { return w.id; });
      var details = await Promise.all(detailIds.map(function (id) {
        return fetch('/api/workouts/' + id).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; });
      }));

      var exSeen = {};
      var exNames = [];
      details.forEach(function (w) {
        if (!w || !w.exercises) return;
        w.exercises.forEach(function (ex) {
          var n = ex.name;
          if (n && !exSeen[n]) { exSeen[n] = true; exNames.push(n); }
        });
      });

      var exDL = document.getElementById('exercise-name-suggestions');
      if (exDL) {
        exDL.innerHTML = '';
        exNames.forEach(function (name) {
          var opt = document.createElement('option');
          opt.value = name;
          exDL.appendChild(opt);
        });
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
    var exercises = getExerciseRows().filter(function (r) { return r.name; });
    if (!exercises.length) {
      showToast('Add at least one exercise before saving a template.', true);
      return;
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
        var btn = document.createElement('button');
        btn.type = 'button';
        btn.style.cssText = 'display:block;width:100%;text-align:left;padding:0.65rem 0.75rem;margin-bottom:0.4rem;border:1px solid #e5e5e5;border-radius:6px;background:#fff;cursor:pointer;font-size:0.9375rem;';
        btn.textContent = t.name;
        btn.addEventListener('mouseover', function () { btn.style.background = '#f8f9ff'; btn.style.borderColor = '#b3c0f0'; });
        btn.addEventListener('mouseout', function () { btn.style.background = '#fff'; btn.style.borderColor = '#e5e5e5'; });
        btn.addEventListener('click', function () {
          modal.style.display = 'none';
          applyTemplate(t);
        });
        listEl.appendChild(btn);
      });
    } catch (e) {
      listEl.innerHTML = '<p class="error-msg">Failed to load templates: ' + e.message + '</p>';
    }
  }

  function applyTemplate(template) {
    document.getElementById('exercises-tbody').innerHTML = '';
    document.getElementById('exercises-error').textContent = '';
    (template.exercises || []).forEach(function (ex) { addExerciseRow(ex); });
    if (!template.exercises || !template.exercises.length) addExerciseRow(null);
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

    var btn = document.getElementById('save-workout-btn');
    btn.disabled = true;

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

      showToast(editingWorkoutId ? 'Workout updated!' : 'Workout saved!');
      resetForm();
      var returnParam = new URLSearchParams(location.search).get('return');
      var dest = (returnParam && /^\//.test(returnParam)) ? returnParam : '/log';
      setTimeout(function () { window.location.replace(dest); }, 700);
    } catch (e) {
      showToast('Save failed: ' + e.message, true);
    } finally {
      btn.disabled = false;
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

  // ── Init ──────────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    initChips();
    document.getElementById('workout-date').value = todayIso();
    addExerciseRow(null);

    var editId = new URLSearchParams(location.search).get('edit');
    if (editId) {
      fetch('/api/workouts/' + encodeURIComponent(editId))
        .then(function (res) { if (!res.ok) throw new Error('not found'); return res.json(); })
        .then(function (workout) { fillForm(workout); })
        .catch(function () { /* leave default new-workout form */ });
    }

    document.querySelectorAll('.training-tab').forEach(function (btn) {
      btn.addEventListener('click', function () { switchTab(btn.dataset.tab); });
    });

    document.getElementById('add-exercise-btn').addEventListener('click', function () {
      addExerciseRow(null);
    });

    // Run details: live pace; typing totals directly stops segment auto-fill
    ['run-distance', 'run-dur-h', 'run-dur-m', 'run-dur-s'].forEach(function (id) {
      var e = document.getElementById(id);
      if (e) e.addEventListener('input', function () {
        _totalsTouched = true;
        recomputeRunPace();
        recomputeSegments();
      });
    });

    // Segment builder: template chips + add-segment menu
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

    document.getElementById('custom-type-input').addEventListener('input', updateRunVisibility);

    document.getElementById('repeat-last-btn').addEventListener('click', repeatLastWorkout);

    document.getElementById('save-template-btn').addEventListener('click', saveTemplate);

    document.getElementById('template-picker-btn').addEventListener('click', openTemplatePicker);

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

    document.getElementById('template-modal-close').addEventListener('click', function () {
      document.getElementById('template-modal').style.display = 'none';
    });

    document.getElementById('template-modal').addEventListener('click', function (e) {
      if (e.target === this) this.style.display = 'none';
    });

    document.getElementById('save-workout-btn').addEventListener('click', saveWorkout);

    document.getElementById('cancel-btn').addEventListener('click', function () {
      resetForm();
    });

    document.getElementById('detail-close-btn').addEventListener('click', function () {
      document.getElementById('detail-modal').style.display = 'none';
    });

    document.getElementById('detail-modal').addEventListener('click', function (e) {
      if (e.target === this) this.style.display = 'none';
    });
  });

  window.addEventListener('userReady', function (e) {
    currentUserId = e.detail.userId;
    loadSuggestions();
  });

  window.addEventListener('userChanged', function (e) {
    currentUserId = e.detail.userId;
    loadSuggestions();
    if (currentView === 'history') {
      loadHistory();
    } else {
      resetForm();
    }
  });
}());
