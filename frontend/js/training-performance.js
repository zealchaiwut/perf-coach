/* Training > Performance sub-tab (issue #811)
 * Loads data from existing endpoints and renders:
 *  - Endurance / Speed score rings with direction + sparkline
 *  - CTL/ATL/TSB fitness chart (Chart.js) with date-range selector
 *  - ACWR guidance (computed from daily-load series)
 *  - Personal Records strip
 */
(function () {
  'use strict';

  // ── Constants ───────────────────────────────────────────────────────────────
  var ACWR_LOWER = 0.8;
  var ACWR_UPPER = 1.3;
  var ACWR_HIGH  = 1.5;
  var ACWR_MIN_DAYS = 28;

  var RANGE_DAYS = { '30D': 30, '90D': 90, '6M': 180, '1Y': 365 };
  var DEFAULT_RANGE = '90D';

  // ── State ───────────────────────────────────────────────────────────────────
  var _athleteId   = null;
  var _fitnessChart = null;
  var _activeRange  = DEFAULT_RANGE;
  var _initialized  = false;

  // ── Public API (mirrors TrainingPlan.init pattern) ──────────────────────────
  window.TrainingPerformance = {
    init: function () {
      if (_initialized) return;
      _initialized = true;
      _boot();
    }
  };

  // ── Boot: wait for userReady then load data ─────────────────────────────────
  function _boot() {
    var userId = window.getCurrentUserId ? window.getCurrentUserId() : null;
    if (userId) {
      _athleteId = userId;
      _loadAll();
    } else {
      window.addEventListener('userReady', function (e) {
        _athleteId = e.detail.userId;
        _loadAll();
      }, { once: true });
    }
  }

  function _loadAll() {
    _loadScores();
    _loadFitnessChart(_activeRange);
    _loadAcwr();
    _loadPR();
  }

  // ── Date helpers ─────────────────────────────────────────────────────────────
  function _today() {
    return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' });
  }

  function _dateMinusDays(days) {
    var d = new Date();
    d.setDate(d.getDate() - days);
    return d.toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' });
  }

  // ── Score Cards ──────────────────────────────────────────────────────────────

  function _loadScores() {
    if (!_athleteId) return;
    // Always parse the JSON body — the error state (HTTP 500) also returns JSON with state='error'
    fetch('/api/athletes/' + _athleteId + '/performance')
      .then(function (r) {
        return r.json().then(function (data) { return data; }).catch(function () { return null; });
      })
      .then(function (data) {
        var state = data && typeof data === 'object' ? data.state : null;

        if (state === 'scored') {
          _renderScoreCard('endurance', data.endurance);
          _renderScoreCard('speed',     data.speed);
          return;
        }

        if (state === 'needs_thresholds') {
          _renderThresholdHint('endurance');
          _renderThresholdHint('speed');
          return;
        }

        if (state === 'building_baseline') {
          var reason = data.reason || 'Keep training — your baseline is building.';
          _renderBuildingBaseline('endurance', reason);
          _renderBuildingBaseline('speed',     reason);
          return;
        }

        // state === 'error' or unexpected/null response
        _renderScoreError('endurance');
        _renderScoreError('speed');
      })
      .catch(function () {
        _renderScoreError('endurance');
        _renderScoreError('speed');
      });
  }

  // Render the scored state: ring + numeric score + direction + sparkline
  function _renderScoreCard(type, data) {
    var card = document.getElementById('perf-score-' + type);
    if (!card) return;

    var ringEl   = card.querySelector('.perf-ring');
    var bodyEl   = card.querySelector('.perf-card-body');
    var scoreEl  = card.querySelector('.perf-score-val');
    var dirEl    = card.querySelector('.perf-dir');
    var sparkEl  = card.querySelector('.perf-spark');
    var bbEl     = card.querySelector('.perf-building-baseline');
    var threshEl = card.querySelector('.perf-threshold-hint');
    var errorEl  = card.querySelector('.perf-error');

    // Reset all states
    if (bodyEl)   bodyEl.style.display = 'none';
    if (bbEl)     bbEl.hidden    = true;
    if (threshEl) threshEl.hidden = true;
    if (errorEl)  errorEl.hidden  = true;

    // Only called for state='scored'; treat missing/invalid sub-object as error
    if (!data || typeof data !== 'object' || data.score == null) {
      _renderScoreError(type);
      return;
    }

    var score = data.score;
    var dir   = data.direction || 'flat';
    var trend = Array.isArray(data.trend) ? data.trend : [];

    if (bodyEl) bodyEl.style.display = '';
    if (ringEl) _drawRing(ringEl, score);
    if (scoreEl) scoreEl.textContent = Math.round(score);
    if (dirEl) {
      dirEl.textContent = dir;
      dirEl.className = 'perf-dir perf-dir--' + dir;
    }
    if (sparkEl && trend.length) _drawSparkline(sparkEl, trend);
  }

  // Render the needs_thresholds state: show CTA prompting athlete to set thresholds in Settings
  function _renderThresholdHint(type) {
    var card = document.getElementById('perf-score-' + type);
    if (!card) return;
    var bodyEl   = card.querySelector('.perf-card-body');
    var bbEl     = card.querySelector('.perf-building-baseline');
    var threshEl = card.querySelector('.perf-threshold-hint');
    var errorEl  = card.querySelector('.perf-error');
    if (bodyEl)   bodyEl.style.display = 'none';
    if (bbEl)     bbEl.hidden    = true;
    if (errorEl)  errorEl.hidden  = true;
    if (threshEl) threshEl.hidden = false;
  }

  // Render the building_baseline state: show reason, hide score card body
  function _renderBuildingBaseline(type, reason) {
    var card = document.getElementById('perf-score-' + type);
    if (!card) return;
    var bodyEl   = card.querySelector('.perf-card-body');
    var threshEl = card.querySelector('.perf-threshold-hint');
    var errorEl  = card.querySelector('.perf-error');
    var bbEl     = card.querySelector('.perf-building-baseline');
    if (bodyEl)   bodyEl.style.display = 'none';
    if (threshEl) threshEl.hidden = true;
    if (errorEl)  errorEl.hidden  = true;
    if (bbEl) {
      bbEl.hidden = false;
      var reasonEl = bbEl.querySelector('.perf-bb-reason');
      if (reasonEl) reasonEl.textContent = reason;
    }
  }

  // Render the error state: show error message + retry button, hide score card body
  function _renderScoreError(type) {
    var card = document.getElementById('perf-score-' + type);
    if (!card) return;
    var bodyEl   = card.querySelector('.perf-card-body');
    var bbEl     = card.querySelector('.perf-building-baseline');
    var threshEl = card.querySelector('.perf-threshold-hint');
    var errorEl  = card.querySelector('.perf-error');
    if (bodyEl)   bodyEl.style.display = 'none';
    if (bbEl)     bbEl.hidden    = true;
    if (threshEl) threshEl.hidden = true;
    if (errorEl)  errorEl.hidden  = false;
  }

  function _drawRing(container, score) {
    var SIZE  = 80;
    var R     = 30;
    var CX    = SIZE / 2;
    var CY    = SIZE / 2;
    var CIRC  = 2 * Math.PI * R;
    var fill  = Math.max(0, Math.min(100, score)) / 100;
    var dash  = fill * CIRC;
    var gap   = CIRC - dash;

    var NS = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + SIZE + ' ' + SIZE);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Score: ' + Math.round(score));
    svg.style.cssText = 'width:80px;height:80px;display:block;';

    // Track ring
    var track = document.createElementNS(NS, 'circle');
    track.setAttribute('cx', CX); track.setAttribute('cy', CY);
    track.setAttribute('r', R);
    track.setAttribute('fill', 'none');
    track.setAttribute('stroke', 'var(--shell-2)');
    track.setAttribute('stroke-width', '7');
    svg.appendChild(track);

    // Fill ring (rotate so 0% starts at top)
    var fillEl = document.createElementNS(NS, 'circle');
    fillEl.setAttribute('cx', CX); fillEl.setAttribute('cy', CY);
    fillEl.setAttribute('r', R);
    fillEl.setAttribute('fill', 'none');
    fillEl.setAttribute('stroke', 'var(--bg-1)');
    fillEl.setAttribute('stroke-width', '7');
    fillEl.setAttribute('stroke-linecap', 'round');
    fillEl.setAttribute('stroke-dasharray', dash + ' ' + gap);
    fillEl.setAttribute('transform', 'rotate(-90 ' + CX + ' ' + CY + ')');
    svg.appendChild(fillEl);

    container.innerHTML = '';
    container.appendChild(svg);
  }

  function _drawSparkline(container, trend) {
    if (!trend.length) return;
    var W = 80, H = 28;
    var min = Math.min.apply(null, trend);
    var max = Math.max.apply(null, trend);
    var range = max - min || 1;
    var NS = 'http://www.w3.org/2000/svg';
    var svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('role', 'img');
    svg.setAttribute('aria-label', 'Trend sparkline');
    svg.style.cssText = 'width:80px;height:28px;display:block;';

    var pts = trend.map(function (v, i) {
      var x = (i / (trend.length - 1 || 1)) * (W - 4) + 2;
      var y = H - 4 - ((v - min) / range) * (H - 8);
      return x + ',' + y;
    });

    var poly = document.createElementNS(NS, 'polyline');
    poly.setAttribute('points', pts.join(' '));
    poly.setAttribute('fill', 'none');
    poly.setAttribute('stroke', 'var(--bg-1)');
    poly.setAttribute('stroke-width', '2');
    poly.setAttribute('stroke-linejoin', 'round');
    poly.setAttribute('stroke-linecap', 'round');
    svg.appendChild(poly);

    container.innerHTML = '';
    container.appendChild(svg);
  }

  // ── Fitness Chart ─────────────────────────────────────────────────────────────

  function _loadFitnessChart(rangeKey) {
    _activeRange = rangeKey;
    // Highlight active range button
    document.querySelectorAll('.perf-range-btn').forEach(function (btn) {
      btn.classList.toggle('active', btn.dataset.range === rangeKey);
    });

    var days = RANGE_DAYS[rangeKey] || 90;
    var startDate = _dateMinusDays(days);
    var endDate   = _today();

    var chartCard  = document.getElementById('perf-chart-card');
    var chartBB    = document.getElementById('perf-chart-bb');
    var chartWrap  = document.getElementById('perf-chart-wrap');

    if (!_athleteId) return;

    var url = '/api/performance/chart?athlete_id=' + encodeURIComponent(_athleteId) +
              '&start_date=' + startDate + '&end_date=' + endDate;

    fetch(url)
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        if (data.building_baseline) {
          if (chartBB)   chartBB.hidden   = false;
          if (chartWrap) chartWrap.hidden = true;
          return;
        }
        if (!data.dates || !data.dates.length) {
          if (chartBB)   chartBB.hidden   = false;
          if (chartWrap) chartWrap.hidden = true;
          return;
        }
        if (chartBB)   chartBB.hidden   = true;
        if (chartWrap) chartWrap.hidden = false;
        _renderFitnessChart(data);
      })
      .catch(function () {
        if (chartBB)   chartBB.hidden   = false;
        if (chartWrap) chartWrap.hidden = true;
      });
  }

  function _renderFitnessChart(data) {
    var canvas = document.getElementById('perf-fitness-canvas');
    if (!canvas) return;
    if (!window.Chart) return;

    if (_fitnessChart) {
      _fitnessChart.destroy();
      _fitnessChart = null;
    }

    var todayStr = _today();
    var todayIdx = data.dates ? data.dates.indexOf(todayStr) : -1;

    _fitnessChart = new window.Chart(canvas, {
      type: 'line',
      data: {
        labels: data.dates || [],
        datasets: [
          {
            label: 'CTL (Fitness)',
            data: data.ctl,
            borderColor: 'var(--bg-1)',
            backgroundColor: 'transparent',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
          },
          {
            label: 'ATL (Fatigue)',
            data: data.atl,
            borderColor: '#f59e0b',
            backgroundColor: 'transparent',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
          },
          {
            label: 'TSB (Form)',
            data: data.tsb,
            borderColor: '#10b981',
            backgroundColor: 'transparent',
            borderWidth: 2,
            pointRadius: 0,
            tension: 0.3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            display: true,
            position: 'top',
            labels: {
              font: { size: 11, family: 'Inter Tight, system-ui, sans-serif' },
              color: 'var(--text-secondary)',
              boxWidth: 12,
              padding: 10,
            },
            overflow: 'scroll',
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var v = ctx.parsed.y;
                return ctx.dataset.label + ': ' + (v != null ? v.toFixed(1) : '—');
              },
            },
          },
        },
        scales: {
          x: {
            ticks: {
              maxTicksLimit: 8,
              font: { size: 10 },
              color: 'var(--text-tertiary)',
            },
            grid: { display: false },
          },
          y: {
            ticks: {
              font: { size: 10 },
              color: 'var(--text-tertiary)',
            },
            grid: { color: 'rgba(13,30,67,0.05)' },
          },
        },
      },
      plugins: [
        {
          id: 'todayMarker',
          afterDraw: function (chart) {
            if (todayIdx < 0) return;
            var ctx2 = chart.ctx;
            var meta = chart.getDatasetMeta(0);
            if (!meta || !meta.data || !meta.data[todayIdx]) return;
            var xPos = meta.data[todayIdx].x;
            var yTop = chart.chartArea.top;
            var yBot = chart.chartArea.bottom;
            ctx2.save();
            ctx2.beginPath();
            ctx2.moveTo(xPos, yTop);
            ctx2.lineTo(xPos, yBot);
            ctx2.strokeStyle = 'rgba(234,88,12,0.7)';
            ctx2.lineWidth = 1.5;
            ctx2.setLineDash([4, 3]);
            ctx2.stroke();
            ctx2.restore();
          },
        },
      ],
    });
  }

  // ── ACWR ─────────────────────────────────────────────────────────────────────

  function _loadAcwr() {
    if (!_athleteId) return;
    var endDate   = _today();
    var startDate = _dateMinusDays(35); // need at least 35 days for ACWR windows

    var url = '/api/athletes/' + _athleteId + '/daily-load' +
              '?start_date=' + startDate + '&end_date=' + endDate;

    fetch(url)
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        var series = Array.isArray(data) ? data.map(function (d) { return d.daily_load || 0; }) : [];
        var acwr = _computeAcwr(series);
        _renderAcwr(acwr);
      })
      .catch(function () {
        _renderAcwr({ ratio: null, band: null, guidance: null });
      });
  }

  function _computeAcwr(series) {
    var n = series.length;
    if (n < ACWR_MIN_DAYS) {
      return { ratio: null, band: 'baseline_forming', guidance: null };
    }

    var acute = 0;
    for (var i = n - 7; i < n; i++) acute += (series[i] || 0);

    var priorTotals = [];
    var windows = [
      series.slice(Math.max(0, n - 35), n - 28),
      series.slice(Math.max(0, n - 28), n - 21),
      series.slice(Math.max(0, n - 21), n - 14),
      series.slice(Math.max(0, n - 14), n - 7),
    ];
    windows.forEach(function (w) {
      if (w.length) priorTotals.push(w.reduce(function (a, b) { return a + (b || 0); }, 0));
    });
    var chronic = priorTotals.length
      ? priorTotals.reduce(function (a, b) { return a + b; }, 0) / priorTotals.length
      : 0;

    if (chronic === 0) {
      return { ratio: null, band: null, guidance: null };
    }

    var ratio = acute / chronic;
    var band;
    if (ratio < ACWR_LOWER) {
      band = 'detraining';
    } else if (ratio > ACWR_HIGH) {
      band = 'high_risk';
    } else {
      band = 'productive';
    }

    var GUIDANCE = {
      detraining: 'Acute load is below chronic baseline. Consider gradually increasing volume to maintain fitness.',
      productive:  'Training load is in the optimal range. Continue current stress to build fitness.',
      high_risk:   'Acute load spike is above chronic baseline. Reduce volume to lower injury risk.',
    };

    return { ratio: ratio, band: band, guidance: GUIDANCE[band] };
  }

  function _renderAcwr(acwr) {
    var section    = document.getElementById('perf-acwr');
    var ratioEl    = document.getElementById('perf-acwr-ratio');
    var bandEl     = document.getElementById('perf-acwr-band');
    var guidanceEl = document.getElementById('perf-acwr-guidance');
    var bbEl       = document.getElementById('perf-acwr-bb');

    if (!section) return;

    if (acwr.band === 'baseline_forming' || acwr.ratio === null) {
      if (ratioEl)    ratioEl.style.display = 'none';
      if (bandEl)     bandEl.style.display = 'none';
      if (guidanceEl) guidanceEl.style.display = 'none';
      if (bbEl)       bbEl.hidden = false;
      return;
    }

    if (bbEl)       bbEl.hidden = true;
    if (ratioEl) {
      ratioEl.style.display = '';
      ratioEl.textContent   = acwr.ratio != null ? acwr.ratio.toFixed(2) : '—';
    }
    if (bandEl) {
      bandEl.style.display = '';
      bandEl.textContent   = acwr.band ? acwr.band.replace(/_/g, ' ') : '—';
      bandEl.className = 'perf-acwr-band-badge perf-acwr-band--' + (acwr.band || '');
    }
    if (guidanceEl) {
      guidanceEl.style.display = '';
      guidanceEl.textContent   = acwr.guidance || '—';
    }
  }

  // ── Personal Records strip ────────────────────────────────────────────────────

  var _PR_LABELS = {
    // volume
    longestByDistance:   'Longest run (km)',
    longestByDuration:   'Longest run (time)',
    weeklyDistanceRecord:'Best week (km)',
    weeklyLoadRecord:    'Best week (TSS)',
    // speed
    '1km':          'Best 1 km',
    '1mile':        'Best 1 mile',
    '5km':          'Best 5 km',
    '10km':         'Best 10 km',
    'half_marathon':'Best half marathon',
    'marathon':     'Best marathon',
    // power
    best1Min:  'Best 1-min power',
    best5Min:  'Best 5-min power',
    best20Min: 'Best 20-min power',
  };

  function _loadPR() {
    if (!_athleteId) return;
    fetch('/api/athletes/' + _athleteId + '/run-personal-records')
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) { _renderRunPR(data); })
      .catch(function () { _renderRunPR(null); });
  }

  function _renderRunPR(data) {
    var strip = document.getElementById('perf-pr-strip');
    if (!strip) return;

    if (!data) {
      strip.innerHTML = '<p class="perf-pr-empty">No personal records yet.</p>';
      return;
    }

    var items = [];

    // Gather all detected records from every category in display order
    var categories = [
      { key: 'volumeRecords',  keys: ['longestByDistance','longestByDuration','weeklyDistanceRecord','weeklyLoadRecord'] },
      { key: 'speedRecords',   keys: ['5km','10km','half_marathon','marathon','1mile','1km'] },
      { key: 'powerRecords',   keys: ['best20Min','best5Min','best1Min'] },
    ];

    categories.forEach(function (cat) {
      var group = data[cat.key];
      if (!group || typeof group !== 'object') return;
      if (group.reason) return; // top-level reason means entire category unavailable
      cat.keys.forEach(function (k) {
        var rec = group[k];
        if (!rec || typeof rec !== 'object') return;
        items.push({ label: k, rec: rec });
      });
    });

    if (!items.length) {
      strip.innerHTML = '<p class="perf-pr-empty">No personal records yet.</p>';
      return;
    }

    var html = items.map(function (item) {
      var label = _PR_LABELS[item.label] || item.label;
      var rec   = item.rec;

      if (rec.reason) {
        return (
          '<div class="perf-pr-item perf-pr-item--unavailable">' +
            '<div class="perf-pr-name">' + _esc(label) + '</div>' +
            '<div class="perf-pr-reason">' + _esc(rec.reason) + '</div>' +
          '</div>'
        );
      }

      var val  = _formatRunPrValue(item.label, rec.value);
      var date = rec.date || '—';
      var src  = rec.sourceWorkout && rec.sourceWorkout.id
        ? '<a class="perf-pr-link" href="/log#workout=' + _esc(String(rec.sourceWorkout.id)) + '">View workout</a>'
        : '';

      return (
        '<div class="perf-pr-item">' +
          '<div class="perf-pr-name">' + _esc(label) + '</div>' +
          '<div class="perf-pr-val">' + _esc(val) + '</div>' +
          '<div class="perf-pr-date">' + _esc(date) + '</div>' +
          src +
        '</div>'
      );
    }).join('');

    strip.innerHTML = html;
  }

  function _formatRunPrValue(key, value) {
    if (value == null) return '—';
    // Speed records and duration-based volume: format as M:SS or H:MM:SS
    var timeKeys = ['5km','10km','half_marathon','marathon','1km','1mile','longestByDuration'];
    if (timeKeys.indexOf(key) !== -1) {
      var s   = Math.round(value);
      var h   = Math.floor(s / 3600);
      var m   = Math.floor((s % 3600) / 60);
      var sec = s % 60;
      if (h > 0) return h + ':' + String(m).padStart(2,'0') + ':' + String(sec).padStart(2,'0');
      return m + ':' + String(sec).padStart(2,'0');
    }
    // Power: whole watts
    if (key === 'best1Min' || key === 'best5Min' || key === 'best20Min') {
      return Math.round(value) + ' W';
    }
    // Distance (km): one decimal
    if (key === 'longestByDistance' || key === 'weeklyDistanceRecord') {
      return parseFloat(value).toFixed(1) + ' km';
    }
    // Weekly TSS: integer
    if (key === 'weeklyLoadRecord') {
      return Math.round(value) + ' TSS';
    }
    return String(value);
  }

  function _formatPrValue(r) {
    if (r.track_type === 'time') {
      var s = Math.round(r.value_numeric);
      var m = Math.floor(s / 60);
      var sec = s % 60;
      return m + ':' + String(sec).padStart(2, '0');
    }
    return r.value_numeric != null ? String(r.value_numeric) : '—';
  }

  function _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Wire date-range buttons and retry actions ───────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.perf-range-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        _loadFitnessChart(btn.dataset.range);
      });
    });

    document.querySelectorAll('.perf-retry-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        _loadScores();
      });
    });
  });

}());
