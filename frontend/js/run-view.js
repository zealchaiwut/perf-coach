(function () {
  'use strict';

  var ZONE2_HR_MIN = window.Zone2.ZONE2_HR_MIN;
  var ZONE2_HR_MAX = window.Zone2.ZONE2_HR_MAX;

  // ── Helpers ────────────────────────────────────────────────────────────────

  function dash(v) { return (v == null || v === '') ? '—' : v; }

  function fmtPace(distKm, durSec) {
    if (!distKm || !durSec) return '—';
    var secPerKm = durSec / distKm;
    var m = Math.floor(secPerKm / 60);
    var s = Math.round(secPerKm % 60);
    return m + ':' + String(s).padStart(2, '0') + ' /km';
  }

  function fmtDuration(sec) {
    if (!sec) return '—';
    var h = Math.floor(sec / 3600);
    var m = Math.floor((sec % 3600) / 60);
    var s = sec % 60;
    if (h > 0) return h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    return m + ':' + String(s).padStart(2, '0');
  }

  function copyToClipboard(text) {
    if (navigator.clipboard) {
      navigator.clipboard.writeText(text).catch(function () {});
    }
  }

  // ── State ──────────────────────────────────────────────────────────────────

  var _workoutId = null;
  var _fullData = null;
  var _lapMetric = 'pace'; // 'pace' | 'hr' | 'power'

  // ── URL param parsing ─────────────────────────────────────────────────────

  function getWorkoutId() {
    var params = new URLSearchParams(window.location.search);
    return params.get('id');
  }

  // ── Segment-effort profile ─────────────────────────────────────────────────

  var EFFORT_COLORS = {
    easy:     '#86efac',  // green
    tempo:    '#fcd34d',  // amber
    hard:     '#fb923c',  // orange
    race:     '#f87171',  // red-ish
    recovery: '#cbd5e1',  // grey
    warmup:   '#bfdbfe',  // light blue
    cooldown: '#a5f3fc',  // cyan
  };

  function segmentColor(effort) {
    return EFFORT_COLORS[effort] || EFFORT_COLORS.easy;
  }

  function renderSegmentBar(segments, totalDist) {
    if (!segments || !segments.length) return '';
    var bars = segments.map(function (seg) {
      var pct = totalDist ? (seg.distance_km / totalDist) * 100 : (100 / segments.length);
      var effort = (seg.effort || 'easy').toLowerCase();
      var color = segmentColor(effort);
      var heightPct = effort === 'hard' || effort === 'race' ? 100
                    : effort === 'tempo' ? 70
                    : effort === 'recovery' ? 30
                    : 50;
      return '<div class="rv-seg-bar-block" style="width:' + pct.toFixed(1) + '%;background:' + color + ';height:' + heightPct + '%"></div>';
    });
    return '<div class="rv-seg-bar">' + bars.join('') + '</div>';
  }

  function renderSegmentRows(segments) {
    if (!segments || !segments.length) return '<p class="rv-empty">No segment data</p>';
    return segments.map(function (seg) {
      var effort = (seg.effort || 'easy').toLowerCase();
      var color = segmentColor(effort);
      return '<div class="rv-seg-row">'
        + '<span class="rv-seg-bullet" style="background:' + color + '"></span>'
        + '<span class="rv-seg-name">' + (seg.name || effort) + '</span>'
        + '<span class="rv-seg-dist">' + dash(seg.distance_km ? seg.distance_km.toFixed(2) + ' km' : null) + '</span>'
        + '<span class="rv-seg-dur">' + fmtDuration(seg.duration_seconds) + '</span>'
        + '<span class="rv-seg-pace">' + fmtPace(seg.distance_km, seg.duration_seconds) + '</span>'
        + '</div>';
    }).join('');
  }

  // ── Lap bar chart ─────────────────────────────────────────────────────────

  function lapMetricValue(lap, metric) {
    if (metric === 'hr') return lap.avg_hr;
    if (metric === 'power') return lap.avg_power;
    // pace = seconds per km (lower = faster)
    if (!lap.distance_km || !lap.duration_seconds) return null;
    return lap.duration_seconds / parseFloat(lap.distance_km);
  }

  function renderLapChart(splits, metric) {
    if (!splits || !splits.length) return '';
    var values = splits.map(function (s) { return lapMetricValue(s, metric); });
    var validVals = values.filter(function (v) { return v != null && v > 0; });
    if (!validVals.length) return '';
    var maxVal = Math.max.apply(null, validVals);
    var minVal = Math.min.apply(null, validVals);
    var range = maxVal - minVal || 1;

    var bars = splits.map(function (s, i) {
      var v = values[i];
      var pct, color, isZ2;
      if (v == null) {
        pct = 0; color = '#e2e8f0';
      } else {
        // For pace: faster (lower secPerKm) = taller bar; invert.
        var normalized = metric === 'pace'
          ? 1 - (v - minVal) / range
          : (v - minVal) / range;
        pct = Math.max(10, Math.round(normalized * 90) + 10);
        color = pct < 40 ? '#86efac' : pct < 70 ? '#fcd34d' : '#fb923c';
      }
      isZ2 = s.avg_hr != null && s.avg_hr >= ZONE2_HR_MIN && s.avg_hr <= ZONE2_HR_MAX;
      var ring = isZ2 ? ' rv-bar--z2' : '';
      return '<div class="rv-bar-col">'
        + '<div class="rv-bar' + ring + '" style="height:' + pct + '%;background:' + color + '"></div>'
        + '<div class="rv-bar-label">' + (i + 1) + '</div>'
        + '</div>';
    });
    return '<div class="rv-lap-chart">' + bars.join('') + '</div>';
  }

  // ── Lap table ─────────────────────────────────────────────────────────────

  function renderLapTable(splits, hasStryd) {
    if (!splits || !splits.length) return '<p class="rv-empty">No lap data</p>';
    var allAuto = splits.every(function (s) { return (s.lap_type || 'auto') === 'auto'; });
    var header = allAuto
      ? 'Laps · 1 km splits'
      : 'Laps';

    var rows = splits.map(function (s, i) {
      var isZ2 = s.avg_hr != null && s.avg_hr >= ZONE2_HR_MIN && s.avg_hr <= ZONE2_HR_MAX;
      var lapNum = isZ2
        ? '<span class="rv-lap-num">' + (i + 1) + '</span><span class="rv-z2-pill">Z2</span>'
        : '<span class="rv-lap-num">' + (i + 1) + '</span>';
      var dist = parseFloat(s.distance_km);
      var distLabel = isNaN(dist) ? '—' : dist.toFixed(2) + ' km';
      var rowClass = isZ2 ? ' rv-lap-row--z2' : '';
      return '<tr class="rv-lap-row' + rowClass + '">'
        + '<td class="rv-td">' + lapNum + '</td>'
        + '<td class="rv-td rv-mono">' + distLabel + '</td>'
        + '<td class="rv-td rv-mono">' + fmtPace(dist, s.duration_seconds) + '</td>'
        + '<td class="rv-td rv-mono">' + dash(s.avg_hr ? s.avg_hr + ' bpm' : null) + '</td>'
        + '<td class="rv-td rv-mono rv-col-len">' + dash(s.stride_length_m != null ? s.stride_length_m + ' m' : null) + '</td>'
        + '<td class="rv-td rv-mono rv-col-cad">' + dash(s.cadence_spm ? s.cadence_spm + ' spm' : null) + '</td>'
        + '<td class="rv-td rv-mono">' + dash(s.avg_power ? s.avg_power + ' W' : null) + '</td>'
        + '</tr>';
    });

    return '<div class="rv-laps-header">'
      + '<h3 class="rv-section-title">' + header + '</h3>'
      + '</div>'
      + '<div class="rv-lap-chart-wrap">'
      + renderLapChart(splits, _lapMetric)
      + '</div>'
      + '<div class="rv-metric-toggle" role="group" aria-label="Lap chart metric">'
      + '<button class="rv-mtog' + (_lapMetric === 'pace' ? ' rv-mtog--active' : '') + '" data-metric="pace">Pace</button>'
      + '<button class="rv-mtog' + (_lapMetric === 'hr' ? ' rv-mtog--active' : '') + '" data-metric="hr">HR</button>'
      + '<button class="rv-mtog' + (_lapMetric === 'power' ? ' rv-mtog--active' : '') + '" data-metric="power">Power</button>'
      + '</div>'
      + '<div class="rv-lap-table-wrap">'
      + '<table class="rv-lap-table">'
      + '<thead><tr>'
      + '<th class="rv-th">Lap</th>'
      + '<th class="rv-th">Dist</th>'
      + '<th class="rv-th">Pace</th>'
      + '<th class="rv-th">HR</th>'
      + '<th class="rv-th rv-col-len">Len (m)</th>'
      + '<th class="rv-th rv-col-cad">Cad (spm)</th>'
      + '<th class="rv-th">Pwr (W)</th>'
      + '</tr></thead>'
      + '<tbody>' + rows.join('') + '</tbody>'
      + '</table>'
      + '</div>';
  }

  // ── Tile helpers ──────────────────────────────────────────────────────────

  function tile(label, value, extra) {
    return '<div class="rv-tile' + (extra || '') + '">'
      + '<div class="rv-tile-val rv-mono">' + dash(value) + '</div>'
      + '<div class="rv-tile-label">' + label + '</div>'
      + '</div>';
  }

  function heroTile(label, value) {
    return tile(label, value, ' rv-tile--hero');
  }

  // ── Source strip ──────────────────────────────────────────────────────────

  function renderSourceStrip(workout, strydPresent) {
    var parts = [];
    if (workout.strava_activity_url) {
      parts.push('<a class="rv-src-link" href="' + workout.strava_activity_url + '" target="_blank" rel="noopener">View on Strava</a>');
    }
    if (strydPresent) {
      parts.push('<span class="rv-src-badge rv-src-badge--stryd">Stryd</span>');
    }
    return '<div class="rv-source-strip">' + (parts.length ? parts.join(' ') : '<span class="rv-src-manual">Manual entry</span>') + '</div>';
  }

  // ── Main render ───────────────────────────────────────────────────────────

  function renderView(data) {
    var w = data.workout;
    var splits = data.splits || [];
    var strydPresent = !!(data.field_coverage && data.field_coverage.stryd);
    var stravaSrc = !!(data.field_coverage && data.field_coverage.strava);

    // Header
    var shortId = w.id ? w.id.slice(-8) : '—';
    var badges = '';
    if (stravaSrc) badges += '<span class="rv-src-badge rv-src-badge--strava">Strava</span>';
    if (strydPresent) badges += '<span class="rv-src-badge rv-src-badge--stryd">Stryd</span>';

    var header = '<div class="rv-card rv-header">'
      + '<div class="rv-header-left">'
      + '<span class="rv-badge">RUN</span>'
      + '<h1 class="rv-workout-name">' + (w.name || 'Untitled Run') + '</h1>'
      + '<div class="rv-short-id">'
      + '<code class="rv-mono rv-id-code">' + shortId + '</code>'
      + '<button class="rv-copy-btn" title="Copy ID" onclick="(function(){' +
        'navigator.clipboard && navigator.clipboard.writeText(\'' + shortId + '\');})()">&#x2398;</button>'
      + '</div>'
      + '<div class="rv-date">' + (w.workout_date || '—') + '</div>'
      + '</div>'
      + '<div class="rv-header-right">' + badges + '</div>'
      + '</div>';

    // Hero tiles (distance + pace)
    var dist = w.distance_km ? w.distance_km.toFixed(2) + ' km' : null;
    var pace = fmtPace(w.distance_km, w.duration_seconds);
    var dur = fmtDuration(w.duration_seconds);
    var heroSection = '<div class="rv-card rv-hero-row">'
      + tile('Distance', dist, ' rv-tile--lg')
      + tile('Avg Pace', pace !== '—' ? pace : null, ' rv-tile--lg')
      + '<div class="rv-duration-line rv-mono">' + dur + '</div>'
      + '</div>';

    // Load & Intensity tiles
    var z2min = w.zone2_minutes != null ? w.zone2_minutes + ' min' : null;
    var elev = w.elevation_m != null ? w.elevation_m + ' m' : null;
    var avgHr = w.avg_hr != null ? w.avg_hr + ' bpm' : null;
    var maxHr = w.max_hr != null ? w.max_hr + ' bpm' : null;
    var avgPwr = strydPresent && w.avg_power != null ? w.avg_power + ' W' : null;
    var maxPwr = strydPresent && w.max_power != null ? w.max_power + ' W' : null;
    var stride = strydPresent && w.avg_stride_m != null ? w.avg_stride_m + ' m' : null;
    var cad = strydPresent && w.avg_cadence_spm != null ? w.avg_cadence_spm + ' spm' : null;

    var intensitySection = '<div class="rv-card rv-intensity">'
      + '<h2 class="rv-section-title">Load &amp; Intensity</h2>'
      + '<div class="rv-tile-grid">'
      + heroTile('TSS', w.tss != null ? Math.round(w.tss) : null)
      + tile('Zone 2', z2min)
      + tile('Elevation', elev)
      + tile('Avg HR', avgHr)
      + tile('Max HR', maxHr)
      + tile('Avg Power', avgPwr)
      + tile('Max Power', maxPwr)
      + tile('Stride Length', stride)
      + tile('Cadence', cad)
      + '</div>'
      + '<p class="rv-footnote">NP · stride = avg per step · cadence = steps/min</p>'
      + '</div>';

    // Session Profile
    var segments = (data.unified && data.unified.segments) || [];
    var totalDist = w.distance_km || 0;
    var profileSection = '<div class="rv-card rv-profile">'
      + '<h2 class="rv-section-title">Session Profile · Effort</h2>'
      + renderSegmentBar(segments, totalDist)
      + '<div class="rv-seg-rows">' + renderSegmentRows(segments) + '</div>'
      + '</div>';

    // Laps section
    var lapsSection = '<div class="rv-card rv-laps" id="rv-laps">'
      + renderLapTable(splits, strydPresent)
      + '</div>';

    // Route placeholder
    var routeSection = '<div class="rv-card rv-route">'
      + '<h2 class="rv-section-title">Route</h2>'
      + '<div class="rv-map-placeholder">Map appears once GPS sync is added</div>'
      + '</div>';

    // Source strip
    var sourceSection = '<div class="rv-card rv-source">'
      + renderSourceStrip(w, strydPresent)
      + '</div>';

    document.getElementById('rv-root').innerHTML =
      header + heroSection + intensitySection + profileSection + lapsSection + routeSection + sourceSection;

    // Lap metric toggle
    document.querySelectorAll('.rv-mtog').forEach(function (btn) {
      btn.addEventListener('click', function () {
        _lapMetric = btn.dataset.metric;
        var lapsEl = document.getElementById('rv-laps');
        if (lapsEl) lapsEl.innerHTML = renderLapTable(splits, strydPresent);
        // Re-attach toggle listeners after re-render
        attachToggleListeners(splits, strydPresent);
      });
    });
  }

  function attachToggleListeners(splits, strydPresent) {
    document.querySelectorAll('.rv-mtog').forEach(function (btn) {
      btn.addEventListener('click', function () {
        _lapMetric = btn.dataset.metric;
        var lapsEl = document.getElementById('rv-laps');
        if (lapsEl) lapsEl.innerHTML = renderLapTable(splits, strydPresent);
        attachToggleListeners(splits, strydPresent);
      });
    });
  }

  // ── Bootstrap ─────────────────────────────────────────────────────────────

  function init() {
    _workoutId = getWorkoutId();
    if (!_workoutId) {
      document.getElementById('rv-root').innerHTML =
        '<div class="rv-error">No workout ID supplied. Add ?id=&lt;workout-id&gt; to the URL.</div>';
      return;
    }
    fetch('/api/workouts/' + _workoutId + '/full', { credentials: 'include' })
      .then(function (r) {
        if (r.status === 404) throw new Error('Workout not found');
        if (!r.ok) throw new Error('Failed to load workout (' + r.status + ')');
        return r.json();
      })
      .then(function (data) {
        _fullData = data;
        renderView(data);
      })
      .catch(function (err) {
        document.getElementById('rv-root').innerHTML =
          '<div class="rv-error">' + err.message + '</div>';
      });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
}());
