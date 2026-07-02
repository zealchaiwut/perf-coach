/* Training > Performance sub-tab (reworked: feature/performance-tab-rework)
 *
 * Sections (top → bottom):
 *   1. Score cards (Endurance | Speed) — score from /api/athletes/{id}/performance
 *      (one-source-of-truth, same as Log cards), block-delta + insight derived
 *      from the trend series, feeding list from /api/training-log.
 *   2. What's moving your scores — honest composition rows from recent training.
 *   3. Fitness · Fatigue · Form chart (reused) + ACWR (reused) + Projected
 *      checkpoint (from /plans/{id}/projection).
 *   4. Personal records grid (reused).
 *
 * No fabricated correlations or fake per-session contributions — where the
 * backend does not expose a figure we omit it or derive an honest one.
 */
(function () {
  'use strict';

  var NS = 'http://www.w3.org/2000/svg';

  // ── Constants ───────────────────────────────────────────────────────────────
  var ACWR_LOWER = 0.8;
  var ACWR_UPPER = 1.3;
  var ACWR_HIGH  = 1.5;
  var ACWR_MIN_DAYS = 28;

  var RANGE_DAYS = { '30D': 30, '90D': 90, '6M': 180, '1Y': 365 };
  var DEFAULT_RANGE = '90D';

  var TREND_COLOR = { endurance: '#16a34a', speed: '#ea580c' };

  // ── State ───────────────────────────────────────────────────────────────────
  var _athleteId    = null;
  var _fitnessChart = null;
  var _activeRange  = DEFAULT_RANGE;
  var _initialized  = false;
  var _planEntityId = null;

  // ── Public API (mirrors the tab init pattern) ───────────────────────────────
  window.TrainingPerformance = {
    init: function () {
      if (_initialized) return;
      _initialized = true;
      _boot();
    }
  };

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
    _loadFeeds();
    _loadMoves();
    _loadFitnessChart(_activeRange);
    _loadAcwr();
    _loadProjection();
    _loadPR();
  }

  // ── Small helpers ─────────────────────────────────────────────────────────

  function _today() {
    return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' });
  }
  function _dateMinusDays(days) {
    var d = new Date();
    d.setDate(d.getDate() - days);
    return d.toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' });
  }
  function _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  function _svgEl(t, a) {
    var e = document.createElementNS(NS, t);
    for (var k in a) if (a.hasOwnProperty(k)) e.setAttribute(k, a[k]);
    return e;
  }
  function _fmtMmmD(iso) {
    var parts = String(iso).split('-');
    if (parts.length !== 3) return iso;
    var d = new Date(Date.UTC(+parts[0], +parts[1] - 1, +parts[2]));
    var mon = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'][d.getUTCMonth()];
    return mon + ' ' + d.getUTCDate();
  }
  function _fmtPace(secPerKm) {
    if (secPerKm == null) return null;
    var s = Math.round(secPerKm);
    var m = Math.floor(s / 60);
    var sec = s % 60;
    return m + ':' + String(sec).padStart(2, '0') + ' /km';
  }

  // ── Section 1: Score cards ────────────────────────────────────────────────

  function _loadScores() {
    if (!_athleteId) return;
    fetch('/api/athletes/' + _athleteId + '/performance')
      .then(function (r) {
        return r.json().then(function (d) { return d; }).catch(function () { return null; });
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
          var reason = (data && data.reason) || 'Keep training: your baseline is building.';
          _renderBuildingBaseline('endurance', reason);
          _renderBuildingBaseline('speed',     reason);
          return;
        }
        _renderScoreError('endurance');
        _renderScoreError('speed');
      })
      .catch(function () {
        _renderScoreError('endurance');
        _renderScoreError('speed');
      });
  }

  function _cardParts(type) {
    var card = document.getElementById('perf-score-' + type);
    if (!card) return null;
    return {
      card: card,
      body:   card.querySelector('.perf-card-body'),
      score:  card.querySelector('.perf-score-val'),
      blk:    card.querySelector('.perf-blk'),
      insight:card.querySelector('.perf-insight'),
      spark:  card.querySelector('.perf-spark'),
      bb:     card.querySelector('.perf-building-baseline'),
      thresh: card.querySelector('.perf-threshold-hint'),
      error:  card.querySelector('.perf-error')
    };
  }

  function _resetStates(p) {
    if (p.body)   p.body.style.display = 'none';
    if (p.bb)     p.bb.hidden = true;
    if (p.thresh) p.thresh.hidden = true;
    if (p.error)  p.error.hidden = true;
  }

  function _renderScoreCard(type, data) {
    var p = _cardParts(type);
    if (!p) return;
    _resetStates(p);

    if (!data || typeof data !== 'object' || data.score == null) {
      _renderScoreError(type);
      return;
    }

    var score = data.score;
    var dir   = data.direction || 'flat';
    var trend = Array.isArray(data.trend) ? data.trend : [];

    if (p.body) p.body.style.display = '';
    if (p.score) p.score.textContent = Math.round(score);

    // Block-delta: derived from the trend series (last vs. ~8 points back).
    if (p.blk) {
      var delta = _blockDelta(trend);
      if (delta === null) {
        p.blk.hidden = true;
      } else {
        p.blk.hidden = false;
        p.blk.classList.remove('perf-blk--down', 'perf-blk--flat');
        if (delta > 0) {
          p.blk.textContent = '↑ +' + delta + ' this block';
        } else if (delta < 0) {
          p.blk.textContent = '↓ −' + Math.abs(delta) + ' this block';
          p.blk.classList.add('perf-blk--down');
        } else {
          p.blk.textContent = 'flat this block';
          p.blk.classList.add('perf-blk--flat');
        }
      }
    }

    // Insight: factual, derived from direction only.
    if (p.insight) p.insight.textContent = _insightText(type, dir, trend);

    // Trend sparkline (green endurance / orange speed).
    if (p.spark && trend.length >= 2) {
      _drawTrend(p.spark, trend, TREND_COLOR[type]);
    } else if (p.spark) {
      p.spark.innerHTML = '';
    }
  }

  // delta = round(last − value ~8 points back / start of the trend window).
  function _blockDelta(trend) {
    if (!Array.isArray(trend) || trend.length < 3) return null;
    var last = trend[trend.length - 1];
    var backIdx = Math.max(0, trend.length - 1 - 8);
    var base = trend[backIdx];
    if (last == null || base == null) return null;
    return Math.round(last - base);
  }

  function _insightText(type, dir, trend) {
    var n = trend.length;
    var span = n >= 2 ? ' over the last ' + Math.min(n, 8) + ' sessions' : '';
    if (dir === 'improving') return 'Trending up' + span + '.';
    if (dir === 'declining') return 'Easing off — trending down' + span + '.';
    return 'Holding steady' + span + '.';
  }

  // Trend sparkline — ported from the mock's trend() SVG helper.
  function _drawTrend(svg, pts, color) {
    var W = 340, H = 56;
    var mn = Math.min.apply(null, pts), mx = Math.max.apply(null, pts);
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.innerHTML = '';
    var P2 = pts.map(function (v, i) {
      return [i / (pts.length - 1) * W, H - (v - mn) / (mx - mn + 0.001) * (H - 10) - 5];
    });
    var d = P2.map(function (p, i) {
      return (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1);
    }).join(' ');
    svg.appendChild(_svgEl('path', {
      d: d, fill: 'none', stroke: color, 'stroke-width': 2.2, 'stroke-linejoin': 'round'
    }));
    var last = P2[P2.length - 1];
    svg.appendChild(_svgEl('circle', { cx: last[0], cy: last[1], r: 3.5, fill: color }));
  }

  function _renderThresholdHint(type) {
    var p = _cardParts(type);
    if (!p) return;
    _resetStates(p);
    if (p.thresh) p.thresh.hidden = false;
    _emptyFeed(type, 'Set thresholds to see the sessions feeding this score.');
  }

  function _renderBuildingBaseline(type, reason) {
    var p = _cardParts(type);
    if (!p) return;
    _resetStates(p);
    if (p.bb) {
      p.bb.hidden = false;
      var reasonEl = p.bb.querySelector('.perf-bb-reason');
      if (reasonEl) reasonEl.textContent = reason;
    }
  }

  function _renderScoreError(type) {
    var p = _cardParts(type);
    if (!p) return;
    _resetStates(p);
    if (p.error) p.error.hidden = false;
  }

  // ── Section 1b: Feeding lists (real sessions from /api/training-log) ─────────

  function _emptyFeed(type, msg) {
    var host = document.getElementById('perf-feed-' + type);
    if (host) host.innerHTML = '<p class="perf-feed-empty">' + _esc(msg) + '</p>';
  }

  function _loadFeeds() {
    if (!_athleteId) return;
    var from = _dateMinusDays(120);
    var to   = _today();
    fetch('/api/training-log?from=' + from + '&to=' + to + '&include_rest=false',
      { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        var entries = _flattenEntries(data);
        _renderFeed('endurance', _pickEndurance(entries));
        _renderFeed('speed',     _pickSpeed(entries));
      })
      .catch(function () {
        _emptyFeed('endurance', 'Could not load recent sessions.');
        _emptyFeed('speed',     'Could not load recent sessions.');
      });
  }

  function _flattenEntries(data) {
    var out = [];
    var weeks = (data && data.weeks) || [];
    weeks.forEach(function (wk) {
      (wk.entries || wk.workouts || []).forEach(function (e) {
        if (e && e.type !== 'rest') out.push(e);
      });
    });
    // Sort newest-first (weeks already are, but entries within may not be).
    out.sort(function (a, b) { return (a.date < b.date) ? 1 : (a.date > b.date ? -1 : 0); });
    return out;
  }

  // Endurance card = last 5 runs, longest distance / long-run type.
  function _pickEndurance(entries) {
    var runs = entries.filter(function (e) {
      var t = (e.type || '').toLowerCase();
      return (t === 'run' || t === 'long_run' || t === 'longrun') &&
             (e.distance_km || 0) >= 8;
    });
    if (!runs.length) {
      runs = entries.filter(function (e) { return (e.type || '').toLowerCase().indexOf('run') !== -1; });
    }
    return runs.slice(0, 5);
  }

  // Speed card = last 5 interval / workout sessions.
  function _pickSpeed(entries) {
    return entries.filter(function (e) {
      var t = (e.type || '').toLowerCase();
      return t === 'interval' || t === 'intervals' || t === 'workout' ||
             t === 'track' || t === 'tempo';
    }).slice(0, 5);
  }

  function _renderFeed(type, rows) {
    var host = document.getElementById('perf-feed-' + type);
    if (!host) return;
    if (!rows.length) {
      _emptyFeed(type, type === 'endurance'
        ? 'No long runs in the last 120 days.'
        : 'No interval sessions in the last 120 days.');
      return;
    }
    host.innerHTML = rows.map(function (w) {
      var meta = [];
      if (w.distance_km != null) meta.push(w.distance_km.toFixed(1) + ' km');
      var pace = _fmtPace(w.average_pace_seconds_per_km);
      if (pace) meta.push(pace);
      if (w.avg_hr != null) meta.push('HR ' + w.avg_hr);
      var src = w.has_stryd ? 'st' : (w.has_strava ? 's' : '');
      var srcHtml = src
        ? '<span class="perf-src perf-src--' + src + '">' + (src === 's' ? 'S' : 'St') + '</span>'
        : '';
      // Honest chip: session TSS (a real neutral figure), never a fabricated contribution.
      var chipHtml = (w.tss != null)
        ? '<span class="perf-dchip">' + Math.round(w.tss) + ' TSS</span>'
        : '';
      var href = '/log?workout=' + encodeURIComponent(w.id);
      return '<a class="perf-frow" href="' + href + '">' +
        '<span class="perf-fdate">' + _esc(_fmtMmmD(w.date)) + '</span>' +
        '<span class="perf-fmain">' +
          '<span class="perf-fn">' + _esc(w.title || 'Workout') + '</span>' +
          '<span class="perf-fm">' + _esc(meta.join(' · ') || '—') + '</span>' +
        '</span>' + srcHtml + chipHtml +
        '<span class="perf-farr">→</span>' +
      '</a>';
    }).join('');
  }

  // ── Section 2: What's moving your scores ────────────────────────────────────
  // TODO(assoc): real association+lag model. This is honest composition only —
  // counts of recent training, not proof of cause.

  function _loadMoves() {
    if (!_athleteId) return;
    var from = _dateMinusDays(56); // last 8 weeks
    var to   = _today();
    fetch('/api/training-log?from=' + from + '&to=' + to + '&include_rest=false',
      { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) { _renderMoves(_flattenEntries(data)); })
      .catch(function () {
        var host = document.getElementById('perf-moves');
        if (host) host.innerHTML = '<p class="perf-feed-empty">Could not load recent training.</p>';
      });
  }

  function _renderMoves(entries) {
    var host = document.getElementById('perf-moves');
    if (!host) return;

    function count(pred) { return entries.filter(pred).length; }

    var longRuns = count(function (e) {
      return (e.type || '').toLowerCase().indexOf('run') !== -1 && (e.distance_km || 0) >= 12;
    });
    var intervals = count(function (e) {
      var t = (e.type || '').toLowerCase();
      return t === 'interval' || t === 'intervals' || t === 'workout' || t === 'track' || t === 'tempo';
    });
    var strength = count(function (e) {
      var t = (e.type || '').toLowerCase();
      return t === 'strength' || t === 'gym' || t === 'plyo' || t === 'plyometric';
    });

    var rows = [
      // [label, detail, chip-class, chip-text, filter-type]
      ['Long runs', longRuns + ' in last 8 wks', 'g', '→ endurance', 'run'],
      ['Intervals', intervals + ' sessions', 'g', '→ speed', 'interval'],
      ['Strength & plyo', strength + ' sessions', 'b', 'lagged → economy', 'strength']
    ];

    host.innerHTML = rows.map(function (m) {
      return '<button type="button" class="perf-arow" data-filter-type="' + _esc(m[4]) + '">' +
        '<span class="perf-an">' + _esc(m[0]) + ' <span class="perf-a">→</span></span>' +
        '<span class="perf-aright">' +
          '<span class="perf-adet">' + _esc(m[1]) + '</span>' +
          '<span class="perf-achip perf-achip--' + m[2] + '">' + _esc(m[3]) + '</span>' +
        '</span>' +
      '</button>';
    }).join('');

    // Each row filters the Log to those sessions: switch to Log tab scoped by type.
    Array.prototype.forEach.call(host.querySelectorAll('.perf-arow'), function (btn) {
      btn.addEventListener('click', function () {
        var t = btn.getAttribute('data-filter-type');
        window.location.href = '/log?types=' + encodeURIComponent(t);
      });
    });
  }

  // ── Section 3a: Fitness chart (reused) ───────────────────────────────────────

  function _loadFitnessChart(rangeKey) {
    _activeRange = rangeKey;
    document.querySelectorAll('.perf-range-btn').forEach(function (btn) {
      btn.classList.toggle('active', btn.dataset.range === rangeKey);
    });

    var days = RANGE_DAYS[rangeKey] || 90;
    var startDate = _dateMinusDays(days);
    var endDate   = _today();

    var chartBB   = document.getElementById('perf-chart-bb');
    var chartWrap = document.getElementById('perf-chart-wrap');

    if (!_athleteId) return;

    var url = '/api/performance/chart?athlete_id=' + encodeURIComponent(_athleteId) +
              '&start_date=' + startDate + '&end_date=' + endDate;

    fetch(url)
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        if (data.building_baseline || !data.dates || !data.dates.length) {
          if (chartBB)   chartBB.hidden = false;
          if (chartWrap) chartWrap.hidden = true;
          return;
        }
        if (chartBB)   chartBB.hidden = true;
        if (chartWrap) chartWrap.hidden = false;
        _renderFitnessChart(data);
      })
      .catch(function () {
        if (chartBB)   chartBB.hidden = false;
        if (chartWrap) chartWrap.hidden = true;
      });
  }

  function _renderFitnessChart(data) {
    var canvas = document.getElementById('perf-fitness-canvas');
    if (!canvas || !window.Chart) return;

    if (_fitnessChart) { _fitnessChart.destroy(); _fitnessChart = null; }

    var todayStr = _today();
    var todayIdx = data.dates ? data.dates.indexOf(todayStr) : -1;

    _fitnessChart = new window.Chart(canvas, {
      type: 'line',
      data: {
        labels: data.dates || [],
        datasets: [
          { label: 'CTL (Fitness)', data: data.ctl, borderColor: '#1b2340', backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.3 },
          { label: 'ATL (Fatigue)', data: data.atl, borderColor: '#f59e0b', backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.3 },
          { label: 'TSB (Form)',    data: data.tsb, borderColor: '#10b981', backgroundColor: 'transparent', borderWidth: 2, pointRadius: 0, tension: 0.3 }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: {
            display: true, position: 'top',
            labels: { font: { size: 11, family: 'Inter Tight, system-ui, sans-serif' }, color: '#6b7280', boxWidth: 12, padding: 10 }
          },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var v = ctx.parsed.y;
                return ctx.dataset.label + ': ' + (v != null ? v.toFixed(1) : '—');
              }
            }
          }
        },
        scales: {
          x: { ticks: { maxTicksLimit: 8, font: { size: 10 }, color: '#9aa3b8' }, grid: { display: false } },
          y: { ticks: { font: { size: 10 }, color: '#9aa3b8' }, grid: { color: 'rgba(13,30,67,0.05)' } }
        }
      },
      plugins: [{
        id: 'todayMarker',
        afterDraw: function (chart) {
          if (todayIdx < 0) return;
          var ctx2 = chart.ctx;
          var meta = chart.getDatasetMeta(0);
          if (!meta || !meta.data || !meta.data[todayIdx]) return;
          var xPos = meta.data[todayIdx].x;
          ctx2.save();
          ctx2.beginPath();
          ctx2.moveTo(xPos, chart.chartArea.top);
          ctx2.lineTo(xPos, chart.chartArea.bottom);
          ctx2.strokeStyle = 'rgba(234,88,12,0.7)';
          ctx2.lineWidth = 1.5;
          ctx2.setLineDash([4, 3]);
          ctx2.stroke();
          ctx2.restore();
        }
      }]
    });
  }

  // ── Section 3b: ACWR (reused) ────────────────────────────────────────────────

  function _loadAcwr() {
    if (!_athleteId) return;
    var endDate   = _today();
    var startDate = _dateMinusDays(35);
    var url = '/api/athletes/' + _athleteId + '/daily-load' +
              '?start_date=' + startDate + '&end_date=' + endDate;
    fetch(url)
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        var series = Array.isArray(data) ? data.map(function (d) { return d.daily_load || 0; }) : [];
        _renderAcwr(_computeAcwr(series));
      })
      .catch(function () { _renderAcwr({ ratio: null, band: null, guidance: null }); });
  }

  function _computeAcwr(series) {
    var n = series.length;
    if (n < ACWR_MIN_DAYS) return { ratio: null, band: 'baseline_forming', guidance: null };
    var acute = 0;
    for (var i = n - 7; i < n; i++) acute += (series[i] || 0);
    var priorTotals = [];
    [
      series.slice(Math.max(0, n - 35), n - 28),
      series.slice(Math.max(0, n - 28), n - 21),
      series.slice(Math.max(0, n - 21), n - 14),
      series.slice(Math.max(0, n - 14), n - 7)
    ].forEach(function (w) {
      if (w.length) priorTotals.push(w.reduce(function (a, b) { return a + (b || 0); }, 0));
    });
    var chronic = priorTotals.length
      ? priorTotals.reduce(function (a, b) { return a + b; }, 0) / priorTotals.length : 0;
    if (chronic === 0) return { ratio: null, band: null, guidance: null };
    var ratio = acute / chronic;
    var band = ratio < ACWR_LOWER ? 'detraining' : (ratio > ACWR_HIGH ? 'high_risk' : 'productive');
    var GUIDANCE = {
      detraining: 'Acute load is below chronic baseline. Consider gradually increasing volume to maintain fitness.',
      productive: 'Training load is in the optimal range. Continue current stress to build fitness.',
      high_risk:  'Acute load spike is above chronic baseline. Reduce volume to lower injury risk.'
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
    if (bbEl) bbEl.hidden = true;
    if (ratioEl) { ratioEl.style.display = ''; ratioEl.textContent = acwr.ratio.toFixed(2); }
    if (bandEl) {
      bandEl.style.display = '';
      bandEl.textContent = acwr.band ? acwr.band.replace(/_/g, ' ') : '—';
      bandEl.className = 'perf-acwr-band-badge perf-acwr-band--' + (acwr.band || '');
    }
    if (guidanceEl) { guidanceEl.style.display = ''; guidanceEl.textContent = acwr.guidance || '—'; }
  }

  // ── Section 3c: Projected at next checkpoint ─────────────────────────────────

  function _loadProjection() {
    if (!_athleteId) return;
    // Resolve the plan entity id (like training-projection.js) from /api/plans.
    fetch('/api/plans', { credentials: 'same-origin' })
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (plans) {
        var plan = Array.isArray(plans) && plans.length ? plans[0] : null;
        if (!plan || !plan.id) { _renderProjEmpty(); return; }
        _planEntityId = plan.id;
        return fetch('/plans/' + _planEntityId + '/projection', { credentials: 'same-origin' })
          .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
          .then(function (data) { _renderProjection(data); });
      })
      .catch(function () { _renderProjEmpty(); });
  }

  function _renderProjEmpty() {
    var body  = document.getElementById('perf-proj-body');
    var empty = document.getElementById('perf-proj-empty');
    if (body)  body.hidden = true;
    if (empty) empty.hidden = false;
  }

  function _renderProjection(data) {
    var body    = document.getElementById('perf-proj-body');
    var empty   = document.getElementById('perf-proj-empty');
    var metaEl  = document.getElementById('perf-proj-meta');
    var endEl   = document.getElementById('perf-proj-endurance');
    var spdEl   = document.getElementById('perf-proj-speed');

    var races = (data && Array.isArray(data.races)) ? data.races : [];
    // Next upcoming checkpoint/race = earliest race dated today-or-later.
    var todayStr = _today();
    var upcoming = races
      .filter(function (r) { return r.date && r.date >= todayStr; })
      .sort(function (a, b) { return a.date < b.date ? -1 : (a.date > b.date ? 1 : 0); });
    var next = upcoming.length ? upcoming[0] : null;

    if (!next) { _renderProjEmpty(); return; }

    if (empty) empty.hidden = true;
    if (body)  body.hidden = false;

    if (metaEl) {
      var label = next.name || 'Checkpoint';
      metaEl.textContent = label + ' · ' + _fmtMmmD(next.date);
    }
    // The projection endpoint exposes estimated finish time per race, not
    // per-checkpoint endurance/speed scores. Show the honest figures we have:
    // estimated finish (and half-equivalent) rather than fabricated scores.
    // TODO(proj-scores): surface per-checkpoint endurance/speed when the
    // projection payload exposes them.
    if (endEl) {
      endEl.innerHTML = next.estimated_time
        ? _esc(next.estimated_time)
        : '—';
      var tile = endEl.closest('.perf-projtile');
      var lbl = tile ? tile.querySelector('.perf-projtile-l') : null;
      if (lbl) lbl.textContent = 'Est. finish';
    }
    if (spdEl) {
      spdEl.innerHTML = (next.half_equivalent)
        ? _esc(next.half_equivalent)
        : '—';
      var tile2 = spdEl.closest('.perf-projtile');
      var lbl2 = tile2 ? tile2.querySelector('.perf-projtile-l') : null;
      if (lbl2) lbl2.textContent = 'Half equiv.';
    }
  }

  // ── Section 4: Personal records grid (reused, mock tile layout) ──────────────

  var _PR_LABELS = {
    longestByDistance:   'Longest run (km)',
    longestByDuration:   'Longest run (time)',
    weeklyDistanceRecord:'Best week (km)',
    weeklyLoadRecord:    'Best week (TSS)',
    '1km':          'Best 1 km',
    '1mile':        'Best 1 mile',
    '5km':          'Best 5 km',
    '10km':         'Best 10 km',
    'half_marathon':'Best half marathon',
    'marathon':     'Best marathon',
    best1Min:  'Best 1-min power',
    best5Min:  'Best 5-min power',
    best20Min: 'Best 20-min power'
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
    if (!data) { strip.innerHTML = '<p class="perf-pr-empty">No personal records yet.</p>'; return; }

    var items = [];
    [
      { key: 'volumeRecords', keys: ['longestByDistance','longestByDuration','weeklyDistanceRecord','weeklyLoadRecord'] },
      { key: 'speedRecords',  keys: ['5km','10km','half_marathon','marathon','1mile','1km'] },
      { key: 'powerRecords',  keys: ['best20Min','best5Min','best1Min'] }
    ].forEach(function (cat) {
      var group = data[cat.key];
      if (!group || typeof group !== 'object' || group.reason) return;
      cat.keys.forEach(function (k) {
        var rec = group[k];
        if (rec && typeof rec === 'object') items.push({ label: k, rec: rec });
      });
    });

    if (!items.length) { strip.innerHTML = '<p class="perf-pr-empty">No personal records yet.</p>'; return; }

    strip.innerHTML = items.map(function (item) {
      var label = _PR_LABELS[item.label] || item.label;
      var rec = item.rec;
      if (rec.reason) {
        return '<div class="perf-prtile perf-prtile--unavailable">' +
          '<div class="perf-pr-name">' + _esc(label) + '</div>' +
          '<div class="perf-pr-reason">' + _esc(rec.reason) + '</div></div>';
      }
      var v = _formatRunPrValue(item.label, rec.value);
      var date = rec.date || '—';
      var src = rec.sourceWorkout && rec.sourceWorkout.id
        ? '<a class="perf-pr-link" href="/log?workout=' + _esc(String(rec.sourceWorkout.id)) + '">View workout</a>'
        : '';
      return '<div class="perf-prtile">' +
        '<div class="perf-pr-name">' + _esc(label) + '</div>' +
        '<div class="perf-pr-val">' + v + '</div>' +
        '<div class="perf-pr-date">' + _esc(date) + '</div>' + src + '</div>';
    }).join('');
  }

  function _formatRunPrValue(key, value) {
    if (value == null) return '—';
    var timeKeys = ['5km','10km','half_marathon','marathon','1km','1mile','longestByDuration'];
    if (timeKeys.indexOf(key) !== -1) {
      var s = Math.round(value);
      var h = Math.floor(s / 3600);
      var m = Math.floor((s % 3600) / 60);
      var sec = s % 60;
      if (h > 0) return h + ':' + String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
      return m + ':' + String(sec).padStart(2, '0');
    }
    if (key === 'best1Min' || key === 'best5Min' || key === 'best20Min') {
      return Math.round(value) + '<small> W</small>';
    }
    if (key === 'longestByDistance' || key === 'weeklyDistanceRecord') {
      return parseFloat(value).toFixed(1) + '<small> km</small>';
    }
    if (key === 'weeklyLoadRecord') {
      return Math.round(value) + '<small> TSS</small>';
    }
    return _esc(String(value));
  }

  // ── Wire date-range buttons + retry ─────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.perf-range-btn').forEach(function (btn) {
      btn.addEventListener('click', function () { _loadFitnessChart(btn.dataset.range); });
    });
    document.querySelectorAll('.perf-retry-btn').forEach(function (btn) {
      btn.addEventListener('click', function () { _loadScores(); });
    });
  });

  // "Full projection on Projection →" links: switch to the Projection sub-tab
  // in-page (delegated; links may be rendered after DOMContentLoaded).
  document.addEventListener('click', function (e) {
    var link = e.target && e.target.closest ? e.target.closest('.perf-plink') : null;
    if (!link) return;
    var tabBtn = document.querySelector('.training-sub-tab[data-tab="projection"]');
    if (tabBtn) { e.preventDefault(); tabBtn.click(); }
  });

}());
