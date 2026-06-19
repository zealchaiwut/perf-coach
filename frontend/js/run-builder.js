(function () {
  'use strict';

  // ── Preset definitions ────────────────────────────────────────────────────
  // Each preset gives a default set of effort segments.

  var PRESETS = {
    'easy run': [
      { name: 'Easy', effort: 'easy', distance_km: 5, duration_seconds: 1800 },
    ],
    'intervals': [
      { name: 'Warm-up', effort: 'warmup', distance_km: 1, duration_seconds: 360 },
      { name: 'Intervals', effort: 'hard', distance_km: 4, duration_seconds: 1200 },
      { name: 'Cool-down', effort: 'cooldown', distance_km: 1, duration_seconds: 360 },
    ],
    'tempo': [
      { name: 'Warm-up', effort: 'warmup', distance_km: 1, duration_seconds: 360 },
      { name: 'Tempo', effort: 'tempo', distance_km: 4, duration_seconds: 1200 },
      { name: 'Cool-down', effort: 'cooldown', distance_km: 1, duration_seconds: 360 },
    ],
    'long run': [
      { name: 'Easy', effort: 'easy', distance_km: 15, duration_seconds: 5400 },
    ],
    'race': [
      { name: 'Warm-up', effort: 'warmup', distance_km: 2, duration_seconds: 720 },
      { name: 'Race', effort: 'race', distance_km: 10, duration_seconds: 2400 },
      { name: 'Cool-down', effort: 'cooldown', distance_km: 1, duration_seconds: 360 },
    ],
  };

  var EFFORT_COLORS = {
    easy:     '#86efac',
    tempo:    '#fcd34d',
    hard:     '#fb923c',
    race:     '#f87171',
    recovery: '#cbd5e1',
    warmup:   '#bfdbfe',
    cooldown: '#a5f3fc',
  };

  // ── State ─────────────────────────────────────────────────────────────────
  var _segments = [{ name: 'Easy', effort: 'easy', distance_km: 5, duration_seconds: 1800 }];
  var _lapMode = 'auto'; // 'auto' | 'manual'
  var _manualLaps = [];
  var _workoutType = 'run';

  // ── Helpers ────────────────────────────────────────────────────────────────

  function pad(n) { return String(n).padStart(2, '0'); }

  function fmtDuration(sec) {
    if (!sec) return '';
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = sec % 60;
    if (h > 0) return h + ':' + pad(m) + ':' + pad(s);
    return m + ':' + pad(s);
  }

  function sumSegDist() {
    return _segments.reduce(function (a, s) { return a + (parseFloat(s.distance_km) || 0); }, 0);
  }

  function sumSegDur() {
    return _segments.reduce(function (a, s) { return a + (parseInt(s.duration_seconds, 10) || 0); }, 0);
  }

  function avgPaceFmt(dist, dur) {
    if (!dist || !dur) return '—';
    var sPerKm = dur / dist;
    var m = Math.floor(sPerKm / 60);
    var s = Math.round(sPerKm % 60);
    return m + ':' + pad(s) + ' /km';
  }

  // ── Segment bar ────────────────────────────────────────────────────────────

  function renderSegmentBar() {
    var total = sumSegDist() || 1;
    return _segments.map(function (seg) {
      var pct = ((parseFloat(seg.distance_km) || 0) / total) * 100;
      var eff = (seg.effort || 'easy').toLowerCase();
      var color = EFFORT_COLORS[eff] || EFFORT_COLORS.easy;
      var h = eff === 'hard' || eff === 'race' ? 100
            : eff === 'tempo' ? 70
            : eff === 'recovery' ? 30
            : 50;
      return '<div class="rb-seg-block" style="width:' + pct.toFixed(1) + '%;background:' + color + ';height:' + h + '%"></div>';
    }).join('');
  }

  function updateSegmentBar() {
    var bar = document.getElementById('rb-seg-bar');
    if (bar) bar.innerHTML = renderSegmentBar();
  }

  // ── Segment rows ───────────────────────────────────────────────────────────

  function renderSegmentRows() {
    return _segments.map(function (seg, i) {
      var eff = (seg.effort || 'easy').toLowerCase();
      var color = EFFORT_COLORS[eff] || EFFORT_COLORS.easy;
      return '<div class="rb-seg-row" data-idx="' + i + '">'
        + '<div class="rb-seg-border" style="background:' + color + '"></div>'
        + '<span class="rb-seg-bullet" style="background:' + color + '"></span>'
        + '<select class="rb-seg-effort" data-field="effort" data-idx="' + i + '">'
        + ['easy','tempo','hard','race','recovery','warmup','cooldown'].map(function (e) {
            return '<option value="' + e + '"' + (eff === e ? ' selected' : '') + '>' + (e.charAt(0).toUpperCase() + e.slice(1)) + '</option>';
          }).join('')
        + '</select>'
        + '<label class="rb-seg-label">Dist</label>'
        + '<input class="rb-seg-input rb-seg-dist" type="number" min="0.1" step="0.1" value="' + (seg.distance_km || '') + '" data-field="distance_km" data-idx="' + i + '">'
        + '<span class="rb-unit">km</span>'
        + '<label class="rb-seg-label">Time</label>'
        + '<input class="rb-seg-input rb-seg-dur" type="text" placeholder="m:ss" value="' + fmtDuration(seg.duration_seconds) + '" data-field="duration_text" data-idx="' + i + '">'
        + '<label class="rb-seg-label">Pace</label>'
        + '<input class="rb-seg-input rb-seg-pace" type="text" placeholder="m:ss /km" data-field="pace" data-idx="' + i + '">'
        + '<button class="rb-seg-del" type="button" data-idx="' + i + '" title="Remove segment">&#x2715;</button>'
        + '</div>';
    }).join('');
  }

  function refreshSegments() {
    var container = document.getElementById('rb-seg-rows');
    if (container) container.innerHTML = renderSegmentRows();
    updateSegmentBar();
    updateTotals();
    attachSegmentListeners();
  }

  function attachSegmentListeners() {
    document.querySelectorAll('.rb-seg-dist').forEach(function (inp) {
      inp.addEventListener('input', function () {
        var idx = parseInt(this.dataset.idx, 10);
        _segments[idx].distance_km = parseFloat(this.value) || 0;
        updateSegmentBar();
        updateTotals();
        if (_lapMode === 'auto') updateAutoLapPreview();
      });
    });
    document.querySelectorAll('.rb-seg-dur').forEach(function (inp) {
      inp.addEventListener('input', function () {
        var idx = parseInt(this.dataset.idx, 10);
        var parts = this.value.split(':');
        var secs = 0;
        if (parts.length === 2) secs = (parseInt(parts[0], 10) || 0) * 60 + (parseInt(parts[1], 10) || 0);
        else if (parts.length === 3) secs = (parseInt(parts[0], 10) || 0) * 3600 + (parseInt(parts[1], 10) || 0) * 60 + (parseInt(parts[2], 10) || 0);
        _segments[idx].duration_seconds = secs;
        updateTotals();
      });
    });
    document.querySelectorAll('.rb-seg-effort').forEach(function (sel) {
      sel.addEventListener('change', function () {
        var idx = parseInt(this.dataset.idx, 10);
        _segments[idx].effort = this.value;
        refreshSegments();
      });
    });
    document.querySelectorAll('.rb-seg-del').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var idx = parseInt(this.dataset.idx, 10);
        _segments.splice(idx, 1);
        refreshSegments();
      });
    });
  }

  // ── Totals ─────────────────────────────────────────────────────────────────

  function updateTotals() {
    var dist = sumSegDist();
    var dur = sumSegDur();
    var el = document.getElementById('rb-totals');
    if (!el) return;
    el.innerHTML =
      '<div class="rb-total-tile"><div class="rb-total-val rb-mono">' + (dist > 0 ? dist.toFixed(2) + ' km' : '—') + '</div><div class="rb-total-label">Distance <span class="rb-label-tag">AUTO</span></div></div>'
      + '<div class="rb-total-tile"><div class="rb-total-val rb-mono">' + (dur > 0 ? fmtDuration(dur) : '—') + '</div><div class="rb-total-label">Duration <span class="rb-label-tag">AUTO</span></div></div>'
      + '<div class="rb-total-tile"><div class="rb-total-val rb-mono">' + avgPaceFmt(dist, dur) + '</div><div class="rb-total-label">Avg Pace <span class="rb-label-tag">AUTO</span></div></div>'
      + '<div class="rb-total-tile"><div class="rb-total-val rb-mono" id="rb-total-avg-hr">—</div><div class="rb-total-label">Avg HR <span class="rb-label-tag rb-label-tag--sync">SYNC</span></div></div>'
      + '<div class="rb-total-tile"><div class="rb-total-val rb-mono" id="rb-total-max-hr">—</div><div class="rb-total-label">Max HR <span class="rb-label-tag rb-label-tag--sync">SYNC</span></div></div>'
      + '<div class="rb-total-tile"><div class="rb-total-val rb-mono" id="rb-total-elev">—</div><div class="rb-total-label">Elevation <span class="rb-label-tag rb-label-tag--sync">SYNC</span></div></div>'
      + '<div class="rb-total-tile"><div class="rb-total-val rb-mono" id="rb-total-avg-power">—</div><div class="rb-total-label">Avg Power <span class="rb-label-tag rb-label-tag--sync">SYNC</span></div></div>'
      + '<div class="rb-total-tile"><div class="rb-total-val rb-mono" id="rb-total-cad">—</div><div class="rb-total-label">Cadence <span class="rb-label-tag rb-label-tag--sync">SYNC</span></div></div>'
      + '<div class="rb-total-tile"><div class="rb-total-val rb-mono" id="rb-total-stride">—</div><div class="rb-total-label">Stride <span class="rb-label-tag rb-label-tag--sync">SYNC</span></div></div>';
  }

  // ── Lap mode ───────────────────────────────────────────────────────────────

  function updateAutoLapPreview() {
    var el = document.getElementById('rb-auto-lap-preview');
    if (!el) return;
    var totalDist = sumSegDist();
    var count = Math.ceil(totalDist);
    el.textContent = totalDist > 0
      ? 'Will generate ~' + count + ' auto split' + (count !== 1 ? 's' : '') + ' of 1 km'
      : 'Enter segment distances above';
  }

  function renderManualLapRows() {
    if (!_manualLaps.length) {
      return '<p class="rb-empty">No laps yet. Click "+ Add lap" to start.</p>';
    }
    return _manualLaps.map(function (lap, i) {
      return '<div class="rb-mlap-row" data-idx="' + i + '">'
        + '<span class="rb-mlap-num">' + (i + 1) + '</span>'
        + '<label>Dist</label><input class="rb-mlap-dist" type="number" min="0.01" step="0.01" value="' + (lap.distance_km || '') + '" data-idx="' + i + '"> km'
        + '<label>Time</label><input class="rb-mlap-dur" type="text" placeholder="m:ss" value="' + fmtDuration(lap.duration_seconds) + '" data-idx="' + i + '">'
        + '<label>HR</label><input class="rb-mlap-hr" type="number" placeholder="—" value="' + (lap.avg_hr || '') + '" data-idx="' + i + '">'
        + '<label>Pwr</label><input class="rb-mlap-pwr" type="number" placeholder="—" value="' + (lap.avg_power || '') + '" data-idx="' + i + '">'
        + '<label>Cad</label><input class="rb-mlap-cad" type="number" placeholder="—" value="' + (lap.cadence_spm || '') + '" data-idx="' + i + '">'
        + '<label>Stride</label><input class="rb-mlap-stride" type="number" step="0.01" placeholder="—" value="' + (lap.stride_length_m || '') + '" data-idx="' + i + '">'
        + '<button class="rb-mlap-del" type="button" data-idx="' + i + '">&#x2715;</button>'
        + '</div>';
    }).join('');
  }

  function refreshManualLaps() {
    var el = document.getElementById('rb-manual-laps');
    if (el) el.innerHTML = renderManualLapRows();
    attachManualLapListeners();
  }

  function attachManualLapListeners() {
    var fields = {
      '.rb-mlap-dist': 'distance_km',
      '.rb-mlap-hr': 'avg_hr',
      '.rb-mlap-pwr': 'avg_power',
      '.rb-mlap-cad': 'cadence_spm',
      '.rb-mlap-stride': 'stride_length_m',
    };
    Object.keys(fields).forEach(function (sel) {
      var field = fields[sel];
      document.querySelectorAll(sel).forEach(function (inp) {
        inp.addEventListener('input', function () {
          var idx = parseInt(this.dataset.idx, 10);
          _manualLaps[idx][field] = parseFloat(this.value) || null;
        });
      });
    });
    document.querySelectorAll('.rb-mlap-dur').forEach(function (inp) {
      inp.addEventListener('input', function () {
        var idx = parseInt(this.dataset.idx, 10);
        var parts = this.value.split(':');
        var secs = 0;
        if (parts.length >= 2) secs = (parseInt(parts[0], 10) || 0) * 60 + (parseInt(parts[1], 10) || 0);
        _manualLaps[idx].duration_seconds = secs || null;
      });
    });
    document.querySelectorAll('.rb-mlap-del').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var idx = parseInt(this.dataset.idx, 10);
        _manualLaps.splice(idx, 1);
        refreshManualLaps();
      });
    });
  }

  // ── Zone 2 lap check (delegates to zone2-constants.js for dynamic bounds) ──
  function isZone2Lap(avgHr) {
    return window.Zone2.isZone2Lap(avgHr);
  }

  // ── Save ───────────────────────────────────────────────────────────────────

  function collectFormData() {
    return {
      name: (document.getElementById('rb-name') || {}).value || '',
      workout_date: (document.getElementById('rb-date') || {}).value || '',
      workout_type: _workoutType,
      remarks: (document.getElementById('rb-remarks') || {}).value || null,
      tss: parseFloat((document.getElementById('rb-tss') || {}).value) || null,
      distance_km: sumSegDist() || null,
      duration_seconds: sumSegDur() || null,
      avg_hr: parseInt((document.getElementById('rb-sync-avg-hr') || {}).value, 10) || null,
      max_hr: parseInt((document.getElementById('rb-sync-max-hr') || {}).value, 10) || null,
      elevation_m: parseInt((document.getElementById('rb-sync-elev') || {}).value, 10) || null,
      avg_power: parseInt((document.getElementById('rb-sync-avg-power') || {}).value, 10) || null,
      max_power: parseInt((document.getElementById('rb-sync-max-power') || {}).value, 10) || null,
      np: parseInt((document.getElementById('rb-sync-np') || {}).value, 10) || null,
      avg_cadence_spm: parseInt((document.getElementById('rb-sync-cad') || {}).value, 10) || null,
      avg_stride_m: parseFloat((document.getElementById('rb-sync-stride') || {}).value) || null,
    };
  }

  function buildSplitsPayload() {
    if (_lapMode === 'manual') {
      return _manualLaps.map(function (lap, i) {
        return {
          split_index: i + 1,
          distance_km: lap.distance_km || 0,
          duration_seconds: lap.duration_seconds || 0,
          avg_hr: lap.avg_hr || null,
          avg_power: lap.avg_power || null,
          cadence_spm: lap.cadence_spm || null,
          stride_length_m: lap.stride_length_m || null,
          lap_type: 'manual',
        };
      });
    }
    // Auto: generate 1-km splits from segments
    var totalDist = sumSegDist();
    if (!totalDist) return [];
    var autoSplits = [];
    var remaining = totalDist;
    var idx = 1;
    while (remaining >= 1) {
      var dur = sumSegDur() > 0 ? Math.round(sumSegDur() / totalDist) : 300;
      autoSplits.push({
        split_index: idx++,
        distance_km: 1.0,
        duration_seconds: dur,
        lap_type: 'auto',
      });
      remaining -= 1;
    }
    if (remaining > 0.01) {
      var partDur = sumSegDur() > 0 ? Math.round((remaining / totalDist) * sumSegDur()) : 60;
      autoSplits.push({
        split_index: idx,
        distance_km: parseFloat(remaining.toFixed(3)),
        duration_seconds: partDur,
        lap_type: 'auto',
      });
    }
    return autoSplits;
  }

  async function saveRun(e) {
    e.preventDefault();
    var errEl = document.getElementById('rb-form-error');
    if (errEl) errEl.textContent = '';

    var data = collectFormData();
    if (!data.name.trim()) {
      if (errEl) errEl.textContent = 'Workout name is required.';
      return;
    }
    if (!data.workout_date) {
      if (errEl) errEl.textContent = 'Date is required.';
      return;
    }

    try {
      var wRes = await fetch('/api/workouts', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!wRes.ok) {
        var wErr = await wRes.json().catch(function () { return {}; });
        throw new Error(wErr.detail || 'Failed to save workout');
      }
      var workout = await wRes.json();

      var splits = buildSplitsPayload();
      if (splits.length) {
        var sRes = await fetch('/api/workouts/' + workout.id + '/splits', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ splits: splits }),
        });
        if (!sRes.ok) {
          var sErr = await sRes.json().catch(function () { return {}; });
          throw new Error(sErr.detail || 'Workout saved but splits failed');
        }
      }

      window.location.href = '/run-view?id=' + workout.id;
    } catch (err) {
      if (errEl) errEl.textContent = err.message;
    }
  }

  // ── Init ───────────────────────────────────────────────────────────────────

  function init() {
    // Preset selector
    var presetSel = document.getElementById('rb-preset');
    if (presetSel) {
      presetSel.addEventListener('change', function () {
        var key = this.value.toLowerCase();
        if (PRESETS[key]) {
          _segments = PRESETS[key].map(function (s) { return Object.assign({}, s); });
        }
        refreshSegments();
      });
    }

    // Add segment
    var addSegBtn = document.getElementById('rb-add-segment');
    if (addSegBtn) {
      addSegBtn.addEventListener('click', function () {
        _segments.push({ name: 'Segment', effort: 'easy', distance_km: 1, duration_seconds: 360 });
        refreshSegments();
      });
    }

    // Lap mode toggle
    document.querySelectorAll('[name="rb-lap-mode"]').forEach(function (radio) {
      radio.addEventListener('change', function () {
        _lapMode = this.value;
        var autoSection = document.getElementById('rb-auto-lap-section');
        var manualSection = document.getElementById('rb-manual-lap-section');
        if (autoSection) autoSection.style.display = _lapMode === 'auto' ? '' : 'none';
        if (manualSection) manualSection.style.display = _lapMode === 'manual' ? '' : 'none';
      });
    });

    // Add lap (manual mode)
    var addLapBtn = document.getElementById('rb-add-lap');
    if (addLapBtn) {
      addLapBtn.addEventListener('click', function () {
        _manualLaps.push({ distance_km: 1, duration_seconds: 300, avg_hr: null, avg_power: null, cadence_spm: null, stride_length_m: null });
        refreshManualLaps();
      });
    }

    // Workout type pills
    document.querySelectorAll('.rb-type-pill').forEach(function (btn) {
      btn.addEventListener('click', function () {
        _workoutType = this.dataset.type;
        document.querySelectorAll('.rb-type-pill').forEach(function (b) { b.classList.remove('rb-type-pill--active'); });
        this.classList.add('rb-type-pill--active');
      });
    });

    // Form submit
    var form = document.getElementById('rb-form');
    if (form) form.addEventListener('submit', saveRun);

    // Set today's date by default
    var dateInput = document.getElementById('rb-date');
    if (dateInput && !dateInput.value) {
      var d = new Date();
      dateInput.value = d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
    }

    // Initial render
    refreshSegments();
    updateAutoLapPreview();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}());
