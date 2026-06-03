(function () {
  /* ---- Greeting ---- */

  function getGreetingPrefix() {
    var h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 17) return 'Good afternoon';
    return 'Good evening';
  }

  function formatDateSubtitle() {
    var d = new Date();
    var days = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
    var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return days[d.getDay()] + ', ' + d.getDate() + ' ' + months[d.getMonth()];
  }

  function setGreetingText(name) {
    var el = document.getElementById('greeting-text');
    if (!el) return;
    el.textContent = getGreetingPrefix() + (name ? ', ' + name : '');
  }

  function setGreetingDate() {
    var el = document.getElementById('greeting-date');
    if (el) el.textContent = formatDateSubtitle();
  }

  function setNavAvatar(name) {
    var el = document.getElementById('nav-avatar');
    if (el && name) el.textContent = name.charAt(0).toUpperCase();
  }

  /* ---- Readiness card helpers ---- */

  function isoDate(d) {
    return d.getFullYear() + '-' +
      String(d.getMonth() + 1).padStart(2, '0') + '-' +
      String(d.getDate()).padStart(2, '0');
  }

  function avgOf(arr) {
    var vals = arr.filter(function (v) { return v != null && !isNaN(v); });
    if (!vals.length) return null;
    return vals.reduce(function (a, b) { return a + b; }, 0) / vals.length;
  }

  function deltaClass(delta, higherIsBetter) {
    if (delta == null || Math.abs(delta) < 0.05) return 'flat';
    if (higherIsBetter) return delta > 0 ? 'up' : 'down';
    return delta < 0 ? 'up' : 'down';
  }

  function fmtDelta(delta, useDecimal) {
    if (delta == null || Math.abs(delta) < 0.05) return '—';
    var n = useDecimal ? delta.toFixed(1) : String(Math.round(delta));
    return (delta > 0 ? '+' : '') + n;
  }

  function readinessHeadline(score) {
    if (score >= 75) return "You’re ready to push today";
    if (score >= 60) return 'Take it steady today';
    return 'Rest up — your body needs recovery';
  }

  function readinessSub(score, todayM, avgs) {
    var dHrv = (todayM.hrv != null && avgs.hrv != null) ? todayM.hrv - avgs.hrv : null;
    var dRhr = (todayM.resting_hr != null && avgs.rhr != null) ? todayM.resting_hr - avgs.rhr : null;
    var dSlp = (todayM.sleep_hours != null && avgs.sleep != null) ? todayM.sleep_hours - avgs.sleep : null;
    var dEng = (todayM.energy != null && avgs.energy != null) ? todayM.energy - avgs.energy : null;

    var signals = [];
    if (dHrv != null) signals.push({ name: 'HRV',        delta: dHrv, good: dHrv > 0, pct: avgs.hrv   ? Math.abs(dHrv / avgs.hrv)   : 0 });
    if (dRhr != null) signals.push({ name: 'Resting HR', delta: dRhr, good: dRhr < 0, pct: avgs.rhr   ? Math.abs(dRhr / avgs.rhr)   : 0 });
    if (dSlp != null) signals.push({ name: 'Sleep',      delta: dSlp, good: dSlp > 0, pct: avgs.sleep ? Math.abs(dSlp / avgs.sleep) : 0 });
    if (dEng != null) signals.push({ name: 'Energy',     delta: dEng, good: dEng > 0, pct: avgs.energy ? Math.abs(dEng / avgs.energy) : 0 });

    if (!signals.length) {
      if (score >= 75) return 'All metrics are dialled in — a solid window for quality work.';
      if (score >= 60) return 'Mixed signals today — go by feel and adjust on the fly.';
      return 'Rest and recovery is the priority today.';
    }

    signals.sort(function (a, b) { return b.pct - a.pct; });
    var top = signals[0];

    var copy = {
      HRV:          { pos: 'HRV is up — a good sign for aerobic output today.',          neg: 'HRV is suppressed — consider backing off intensity.' },
      'Resting HR': { pos: 'Resting HR is low — your body is well-recovered.',            neg: 'Elevated resting HR suggests your body is still recovering.' },
      Sleep:        { pos: 'Good sleep last night is driving today’s readiness.',         neg: 'Short sleep is the main drag on today’s score.' },
      Energy:       { pos: 'High self-reported energy — take advantage of it.',           neg: 'Low energy reported — take it easier than planned.' }
    };

    var set = copy[top.name];
    if (!set) return 'Your metrics are shaping today’s readiness score.';
    return top.good ? set.pos : set.neg;
  }

  function pillInfo(score) {
    if (score >= 75) return { icon: 'ti-check',          label: 'Green · go',       cls: 'pill-green' };
    if (score >= 60) return { icon: 'ti-alert-triangle', label: 'Amber · caution', cls: 'pill-amber' };
    return              { icon: 'ti-x',               label: 'Red · rest',      cls: 'pill-red'   };
  }

  /* ---- Readiness card state renderers ---- */

  function renderScored(card, todayData, rangeData, metrics) {
    var score = Math.round(todayData.score);

    var scores = rangeData.filter(function (r) { return r != null; }).map(function (r) { return r.score; });
    var avgScore = avgOf(scores);
    var avgRounded = avgScore != null ? Math.round(avgScore) : null;

    var trending = 'flat';
    if (avgScore != null) {
      if (score > avgScore + 2) trending = 'up';
      else if (score < avgScore - 2) trending = 'down';
    }
    var trendLabel = { up: 'trending up', down: 'trending down', flat: 'flat' }[trending];

    /* most-recent metric entry = today's chip values */
    var sorted = metrics.slice().sort(function (a, b) {
      return b.metric_date < a.metric_date ? -1 : 1;
    });
    var tm = sorted[0] || {};

    var avgs = {
      hrv:    avgOf(metrics.map(function (m) { return m.hrv; })),
      rhr:    avgOf(metrics.map(function (m) { return m.resting_hr; })),
      sleep:  avgOf(metrics.map(function (m) { return m.sleep_hours; })),
      energy: avgOf(metrics.map(function (m) { return m.energy; }))
    };

    var dHrv = (tm.hrv != null && avgs.hrv != null) ? tm.hrv - avgs.hrv : null;
    var dRhr = (tm.resting_hr != null && avgs.rhr != null) ? tm.resting_hr - avgs.rhr : null;
    var dSlp = (tm.sleep_hours != null && avgs.sleep != null) ? tm.sleep_hours - avgs.sleep : null;
    var dEng = (tm.energy != null && avgs.energy != null) ? tm.energy - avgs.energy : null;

    var pill     = pillInfo(score);
    var headline = readinessHeadline(score);
    var sub      = readinessSub(score, tm, avgs);

    var avgLine = avgRounded != null
      ? '<div class="score-avg">7d avg ' + avgRounded + ' · ' + trendLabel + '</div>'
      : '';

    function chip(label, val, delta, higherIsBetter, useDecimal) {
      var valStr = val != null ? (useDecimal ? Number(val).toFixed(1) + 'h' : String(Math.round(val))) : '—';
      var dc  = deltaClass(delta, higherIsBetter);
      var df  = fmtDelta(delta, useDecimal);
      var dEl = delta != null ? ' <span class="delta ' + dc + '">' + df + '</span>' : '';
      return '<div class="component"><div class="l">' + label + '</div><div class="v">' + valStr + dEl + '</div></div>';
    }

    var engVal = tm.energy != null
      ? String(tm.energy) + '<span style="font-size:11px;opacity:0.5;">/5</span>'
      : '—';
    var engDelta = dEng != null
      ? ' <span class="delta ' + deltaClass(dEng, true) + '">' + fmtDelta(dEng, false) + '</span>'
      : '';

    card.innerHTML =
      '<div class="lbl">Readiness · today</div>' +
      '<h2>' + headline + '</h2>' +
      '<p class="sub">' + sub + '</p>' +
      '<span class="status-pill ' + pill.cls + '"><i class="ti ' + pill.icon + '"></i>' + pill.label + '</span>' +
      '<div class="score-block">' +
        '<div class="score-label">SCORE</div>' +
        '<div class="score">' + score + '<small>/100</small></div>' +
        avgLine +
      '</div>' +
      '<div class="components">' +
        chip('HRV',   tm.hrv,         dHrv, true,  false) +
        chip('RHR',   tm.resting_hr,  dRhr, false, false) +
        chip('Sleep', tm.sleep_hours, dSlp, true,  true)  +
        '<div class="component"><div class="l">Energy</div><div class="v">' + engVal + engDelta + '</div></div>' +
      '</div>';
  }

  function renderCTA(card, userId, onSuccess) {
    card.innerHTML =
      '<div class="lbl">Readiness · today</div>' +
      '<div class="readiness-cta-body">' +
        '<p class="readiness-cta-msg">No readiness score has been computed for today yet.</p>' +
        '<button class="readiness-cta-btn" id="readiness-compute-btn" type="button">' +
          '<i class="ti ti-calculator"></i>Compute today’s readiness' +
        '</button>' +
      '</div>';

    var btn = document.getElementById('readiness-compute-btn');
    btn.addEventListener('click', async function () {
      btn.disabled = true;
      btn.innerHTML = '<i class="ti ti-loader-2"></i>Computing…';
      try {
        var res = await fetch('/api/readiness/compute', { method: 'POST' });
        if (res.ok) {
          await onSuccess();
        } else if (res.status === 404) {
          renderEmpty(card);
        } else {
          btn.disabled = false;
          btn.innerHTML = '<i class="ti ti-calculator"></i>Compute today’s readiness';
        }
      } catch (_) {
        btn.disabled = false;
        btn.innerHTML = '<i class="ti ti-calculator"></i>Compute today’s readiness';
      }
    });
  }

  function renderEmpty(card) {
    card.innerHTML =
      '<div class="lbl">Readiness · today</div>' +
      '<div class="readiness-empty-body">' +
        '<p class="readiness-empty-msg">No metrics yet — log your first day to see readiness</p>' +
      '</div>';
  }

  async function loadReadinessCard(userId) {
    var row1 = document.getElementById('row-1');
    if (!row1) return;

    var card = document.getElementById('readiness-hero-card');
    if (!card) {
      card = document.createElement('div');
      card.id = 'readiness-hero-card';
      card.className = 'card readiness';
      row1.insertBefore(card, row1.firstChild);
    }

    var today = new Date();
    var from = new Date(today);
    from.setDate(from.getDate() - 6);
    var todayStr = isoDate(today);
    var fromStr  = isoDate(from);

    var todayRes;
    try {
      todayRes = await fetch('/api/readiness/today');
    } catch (_) {
      renderEmpty(card);
      return;
    }

    if (todayRes.status === 404) {
      renderCTA(card, userId, function () { return loadReadinessCard(userId); });
      return;
    }

    if (!todayRes.ok) {
      renderEmpty(card);
      return;
    }

    var todayData;
    try {
      todayData = await todayRes.json();
    } catch (_) {
      renderEmpty(card);
      return;
    }

    var rangeData = [];
    var metricsData = [];
    try {
      var pair = await Promise.all([
        fetch('/api/readiness?from=' + fromStr + '&to=' + todayStr),
        fetch('/api/daily-metrics?from=' + fromStr + '&to=' + todayStr)
      ]);
      if (pair[0].ok) rangeData   = await pair[0].json();
      if (pair[1].ok) metricsData = await pair[1].json();
    } catch (_) {
      /* continue with whatever we have */
    }

    if (!metricsData.length) {
      renderEmpty(card);
      return;
    }

    renderScored(card, todayData, rangeData, metricsData);
  }

  /* ---- Sleep card helpers ---- */

  /*
   * Sleep score formula:
   * clip(((sleep_hours - 4) / 5) * 60 + ((sleep_quality - 1) / 4) * 40, 0, 100)
   * Example: sleep_hours = 7.4, sleep_quality = 4 → score = 82
   */
  function computeSleepScore(hours, quality) {
    var raw = ((hours - 4) / 5) * 60 + ((quality - 1) / 4) * 40;
    return Math.round(Math.min(100, Math.max(0, raw)));
  }

  function fmtHoursAsleep(hours) {
    var h = Math.floor(hours);
    var m = Math.round((hours - h) * 60);
    return h + 'h ' + m + 'm';
  }

  async function loadSleepCard(userId) {
    var row1 = document.getElementById('row-1');
    if (!row1) return;

    var card = document.getElementById('sleep-hero-card');
    if (!card) {
      card = document.createElement('div');
      card.id = 'sleep-hero-card';
      card.className = 'card sleep-card';
      row1.appendChild(card);
    }

    var today = isoDate(new Date());
    var data = null;
    try {
      var res = await fetch('/api/daily-metrics/' + encodeURIComponent(userId) + '/' + today);
      if (res.ok) data = await res.json();
    } catch (_) { /* fall through to empty state */ }

    var lbl = '<div class="slp-lbl"><i class="ti ti-moon"></i>Sleep · last night</div>';

    if (!data || data.sleep_hours == null) {
      card.innerHTML = lbl +
        '<div class="slp-empty">No sleep logged for last night</div>';
      return;
    }

    var score   = computeSleepScore(data.sleep_hours, data.sleep_quality != null ? data.sleep_quality : 0);
    var timeStr = fmtHoursAsleep(data.sleep_hours);
    var hrvStr  = data.hrv != null ? data.hrv + ' ms' : '—';
    var qualStr = data.sleep_quality != null ? 'Quality ' + data.sleep_quality + '/5' : '—';

    card.innerHTML = lbl +
      '<div class="slp-body">' +
        '<div class="slp-top">' +
          '<div class="slp-score">' + score + '<small>/100</small></div>' +
          '<div class="slp-quality">' + qualStr + '</div>' +
        '</div>' +
        '<div class="slp-meta">' +
          '<div><div class="slp-m-l">Time asleep</div><div class="slp-m-v">' + timeStr + '</div></div>' +
          '<div><div class="slp-m-l">HRV during</div><div class="slp-m-v">' + hrvStr + '</div></div>' +
        '</div>' +
        '<div class="slp-stages">' +
          '<div class="slp-stages-lbl">Stages</div>' +
          '<div class="slp-stages-bar">' +
            '<div class="slp-seg-deep" style="width:22%"></div>' +
            '<div class="slp-seg-rem" style="width:28%"></div>' +
            '<div class="slp-seg-light" style="width:50%"></div>' +
          '</div>' +
          '<div class="slp-legend">' +
            '<div class="slp-legend-item"><span class="slp-dot" style="background:#1f6feb"></span>Deep<span class="slp-pct">22%</span></div>' +
            '<div class="slp-legend-item"><span class="slp-dot" style="background:#a86eff"></span>REM<span class="slp-pct">28%</span></div>' +
            '<div class="slp-legend-item"><span class="slp-dot" style="background:rgba(255,255,255,0.5)"></span>Light<span class="slp-pct">50%</span></div>' +
          '</div>' +
          '<div class="slp-demo-note">demo data</div>' +
        '</div>' +
      '</div>';
  }

  /* ---- Performance card helpers ---- */

  var TRACK_CONFIGS = {
    'half_marathon': {
      workout_type_re: /run/i,
      dist_min: 20, dist_max: 22,
      value_source: 'duration',
      icon_cls: 'run', icon: 'ti-run', sub: '21.1 km'
    },
    '10k': {
      workout_type_re: /run/i,
      dist_min: 9, dist_max: 11,
      value_source: 'duration',
      icon_cls: 'run', icon: 'ti-run', sub: '10.0 km'
    },
    'squat_1rm': {
      workout_type_re: /strength/i,
      dist_min: null, dist_max: null,
      value_source: 'exercise_weight',
      exercise_re: /squat/i,
      icon_cls: 'lift', icon: 'ti-barbell', sub: '1-rep max'
    }
  };

  function fmtSeconds(sec) {
    var s = Math.round(sec);
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var ss = s % 60;
    if (h > 0) {
      return h + ':' + String(m).padStart(2, '0') + ':' + String(ss).padStart(2, '0');
    }
    return String(m).padStart(2, '0') + ':' + String(ss).padStart(2, '0');
  }

  function fmtTimeDelta(diffSec) {
    var abs = Math.abs(Math.round(diffSec));
    var h = Math.floor(abs / 3600);
    var m = Math.floor((abs % 3600) / 60);
    var s = abs % 60;
    var sign = diffSec >= 0 ? '+' : '−';
    if (h > 0) {
      return sign + h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0') + ' from PR';
    }
    if (m > 0) {
      return sign + m + ':' + String(s).padStart(2, '0') + ' from PR';
    }
    return sign + s + 's from PR';
  }

  function fmtWeightDelta(diff) {
    var sign = diff >= 0 ? '+' : '−';
    return sign + Math.abs(diff).toFixed(diff % 1 === 0 ? 0 : 1) + ' kg from PR';
  }

  function fmtDate(isoStr) {
    if (!isoStr) return '';
    var parts = isoStr.split('-');
    var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return months[parseInt(parts[1], 10) - 1] + ' ' + parseInt(parts[2], 10) + ', ' + parts[0];
  }

  function fmtDateShort(isoStr) {
    if (!isoStr) return '';
    var parts = isoStr.split('-');
    var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return months[parseInt(parts[1], 10) - 1] + ' ' + parseInt(parts[2], 10);
  }

  function matchesTrack(workout, cfg) {
    if (!cfg.workout_type_re.test(workout.workout_type || '')) return false;
    if (cfg.dist_min !== null) {
      var d = workout.distance_km;
      if (d == null || d < cfg.dist_min || d > cfg.dist_max) return false;
    }
    return true;
  }

  /* Returns {value, date} or null for a given track + sorted workouts list.
     For exercise_weight tracks, fetches the workout detail. */
  async function resolveRecentValue(cfg, sortedWorkouts) {
    var match = null;
    for (var i = 0; i < sortedWorkouts.length; i++) {
      if (matchesTrack(sortedWorkouts[i], cfg)) { match = sortedWorkouts[i]; break; }
    }
    if (!match) return null;

    if (cfg.value_source === 'duration') {
      if (match.duration_seconds == null) return null;
      return { value: match.duration_seconds, date: match.workout_date };
    }

    if (cfg.value_source === 'exercise_weight') {
      var detail = null;
      try {
        var r = await fetch('/api/workouts/' + match.id);
        if (r.ok) detail = await r.json();
      } catch (_) { return null; }
      if (!detail || !Array.isArray(detail.exercises)) return null;
      var maxW = null;
      detail.exercises.forEach(function (ex) {
        if (cfg.exercise_re.test(ex.name || '') && ex.weight_kg != null) {
          if (maxW === null || ex.weight_kg > maxW) maxW = ex.weight_kg;
        }
      });
      if (maxW === null) return null;
      return { value: maxW, date: match.workout_date };
    }

    return null;
  }

  function buildPrValueHTML(pr) {
    if (pr.track_type === 'time') {
      return '<span class="pc-value">' + fmtSeconds(pr.value_numeric) + '</span>';
    }
    return '<span class="pc-value">' + pr.value_numeric + '<span class="pc-unit">kg</span></span>';
  }

  function buildRecentValueHTML(pr, recent) {
    if (!recent) {
      return '<span class="pc-dash">—</span>';
    }
    var valHTML, delta, deltaClass;
    if (pr.track_type === 'time') {
      valHTML = '<span class="pc-value">' + fmtSeconds(recent.value) + '</span>';
      delta   = recent.value - pr.value_numeric;
      deltaClass = delta > 0 ? 'behind' : 'ahead';
    } else {
      valHTML = '<span class="pc-value">' + recent.value + '<span class="pc-unit">kg</span></span>';
      delta   = recent.value - pr.value_numeric;
      deltaClass = delta < 0 ? 'behind' : 'ahead';
    }
    var deltaText = pr.track_type === 'time' ? fmtTimeDelta(delta) : fmtWeightDelta(delta);
    return valHTML +
      '<div class="pc-date">' + fmtDateShort(recent.date) + '</div>' +
      '<div class="pc-delta ' + deltaClass + '">' + deltaText + '</div>';
  }

  function buildRecentValueMobileHTML(pr, recent) {
    if (!recent) return '<div class="mc-value">—</div>';
    var valHTML, delta, deltaClass, deltaText;
    if (pr.track_type === 'time') {
      valHTML    = '<div class="mc-value">' + fmtSeconds(recent.value) + '</div>';
      delta      = recent.value - pr.value_numeric;
      deltaClass = delta > 0 ? 'behind' : 'ahead';
      deltaText  = fmtTimeDelta(delta);
    } else {
      valHTML    = '<div class="mc-value">' + recent.value + '<span class="mc-unit">kg</span></div>';
      delta      = recent.value - pr.value_numeric;
      deltaClass = delta < 0 ? 'behind' : 'ahead';
      deltaText  = fmtWeightDelta(delta);
    }
    return valHTML +
      '<div class="mc-meta">' + fmtDateShort(recent.date) + '</div>' +
      '<div class="mc-delta ' + deltaClass + '">' + deltaText + '</div>';
  }

  function buildDesktopRow(pr, cfg, recent, isLast) {
    var rowCls = 'perf-row' + (isLast ? ' perf-row-last' : '');
    var predicted =
      '<span class="pc-dash" title="Prediction model not yet built">—</span>';
    return '<div class="' + rowCls + '">' +
      '<div class="perf-track">' +
        '<div class="icon-wrap ' + cfg.icon_cls + '"><i class="ti ' + cfg.icon + '"></i></div>' +
        '<div><div class="trk-name">' + pr.track_name + '</div>' +
             '<div class="trk-sub">' + cfg.sub + '</div></div>' +
      '</div>' +
      '<div>' +
        buildPrValueHTML(pr) +
        '<div class="pc-trophy"><i class="ti ti-trophy-filled"></i>' + fmtDate(pr.achieved_on) + '</div>' +
      '</div>' +
      '<div>' + buildRecentValueHTML(pr, recent) + '</div>' +
      '<div>' + predicted + '</div>' +
    '</div>';
  }

  function buildMobileBlock(pr, cfg, recent) {
    var blockCls = 'perf-track-block';
    var prVal    = pr.track_type === 'time'
      ? fmtSeconds(pr.value_numeric)
      : pr.value_numeric + '<span class="mc-unit">kg</span>';

    return '<div class="' + blockCls + '">' +
      '<div class="perf-track-head">' +
        '<div class="icon-wrap ' + cfg.icon_cls + '"><i class="ti ' + cfg.icon + '"></i></div>' +
        '<div><div class="trk-name">' + pr.track_name + '</div>' +
             '<div class="trk-sub">' + cfg.sub + '</div></div>' +
      '</div>' +
      '<div class="perf-cells">' +
        '<div class="perf-cell-m pr-cell-m">' +
          '<div class="mc-label"><i class="ti ti-trophy-filled"></i>PR</div>' +
          '<div class="mc-value">' + prVal + '</div>' +
          '<div class="mc-meta">' + fmtDateShort(pr.achieved_on) + '</div>' +
        '</div>' +
        '<div class="perf-cell-m">' +
          '<div class="mc-label">Current</div>' +
          buildRecentValueMobileHTML(pr, recent) +
        '</div>' +
        '<div class="perf-cell-m pred-cell-m">' +
          '<div class="mc-label">Predicted</div>' +
          '<div class="mc-value" title="Prediction model not yet built">—</div>' +
        '</div>' +
      '</div>' +
    '</div>';
  }

  async function loadPerformanceCard(userId) {
    var row2 = document.getElementById('row-2');
    if (!row2) return;

    var card = document.getElementById('perf-card');
    if (!card) {
      card = document.createElement('div');
      card.id = 'perf-card';
      card.className = 'card';
      row2.insertBefore(card, row2.firstChild);
    }

    card.innerHTML =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-trophy" style="color:var(--gold);"></i>Performance</div>' +
        '<a href="#">All tracks</a>' +
      '</div>' +
      '<div class="perf-loading" style="font-size:13px;color:var(--text-tertiary);padding:16px 4px;">Loading…</div>';

    var prs = [];
    try {
      var r = await fetch('/api/personal-records');
      if (r.ok) prs = await r.json();
    } catch (_) { prs = []; }

    var configuredPrs = prs.filter(function (pr) { return TRACK_CONFIGS[pr.track_key]; });

    if (configuredPrs.length === 0) {
      var emptyLoading = card.querySelector('.perf-loading');
      if (emptyLoading) emptyLoading.remove();
      var emptyEl = document.createElement('div');
      emptyEl.className = 'perf-empty';
      emptyEl.innerHTML =
        'No tracked performances yet — add one from the <a href="#">Performance page</a>';
      card.appendChild(emptyEl);
      return;
    }

    /* Fetch 6 months of workouts once */
    var today = new Date();
    var from6m = new Date(today);
    from6m.setMonth(from6m.getMonth() - 6);
    var allWorkouts = [];
    try {
      var wr = await fetch(
        '/api/workouts?from=' + isoDate(from6m) + '&to=' + isoDate(today)
      );
      if (wr.ok) allWorkouts = await wr.json();
    } catch (_) { allWorkouts = []; }

    allWorkouts.sort(function (a, b) {
      return a.workout_date < b.workout_date ? 1 : -1;
    });

    /* Resolve most-recent values (may involve detail fetches for weight tracks) */
    var recentValues = [];
    for (var i = 0; i < configuredPrs.length; i++) {
      var cfg = TRACK_CONFIGS[configuredPrs[i].track_key];
      var rv = await resolveRecentValue(cfg, allWorkouts);
      recentValues.push(rv);
    }

    /* Build HTML */
    var desktopRows = '';
    var mobileBlocks = '';
    for (var j = 0; j < configuredPrs.length; j++) {
      var pr  = configuredPrs[j];
      var cfgJ = TRACK_CONFIGS[pr.track_key];
      var rv2  = recentValues[j];
      var last = j === configuredPrs.length - 1;
      desktopRows  += buildDesktopRow(pr, cfgJ, rv2, last);
      mobileBlocks += buildMobileBlock(pr, cfgJ, rv2);
    }

    var loadingEl = card.querySelector('.perf-loading');
    if (loadingEl) loadingEl.remove();

    var contentEl = document.createElement('div');
    contentEl.innerHTML =
      '<div class="perf-grid">' +
        '<div class="perf-hdr">' +
          '<div>Track</div><div>Personal best</div>' +
          '<div>Most recent</div><div>Predicted next</div>' +
        '</div>' +
        desktopRows +
      '</div>' +
      '<div class="perf-mobile">' + mobileBlocks + '</div>';

    card.appendChild(contentEl.firstChild);
    card.appendChild(contentEl.firstChild);
  }

  /* ---- Recent Workouts card helpers ---- */

  var WORKOUT_TYPE_ICON = {
    run:      { cls: 'run',  icon: 'ti-run' },
    ride:     { cls: 'bike', icon: 'ti-bike' },
    bike:     { cls: 'bike', icon: 'ti-bike' },
    cycle:    { cls: 'bike', icon: 'ti-bike' },
    lift:     { cls: 'lift', icon: 'ti-barbell' },
    strength: { cls: 'lift', icon: 'ti-barbell' },
    wod:      { cls: 'wod',  icon: 'ti-flame' },
    crossfit: { cls: 'wod',  icon: 'ti-flame' },
  };

  function workoutTypeIcon(type) {
    return WORKOUT_TYPE_ICON[(type || '').toLowerCase()] || { cls: 'run', icon: 'ti-run' };
  }

  function fmtWorkoutDuration(seconds) {
    if (seconds == null) return null;
    var s = Math.round(seconds);
    if (s < 3600) {
      return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
    }
    return Math.floor(s / 3600) + ':' + String(Math.floor((s % 3600) / 60)).padStart(2, '0');
  }

  function workoutDayOfWeek(isoStr) {
    var p = isoStr.split('-');
    var d = new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
    return ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()];
  }

  function buildWorkoutRow(w, extraCls) {
    var ic = workoutTypeIcon(w.workout_type);

    var titleText = w.name;
    if (w.distance_km != null) {
      titleText += ' · ' + Number(w.distance_km).toFixed(1) + ' km';
    }

    var metaParts = [workoutDayOfWeek(w.workout_date)];
    var dur = fmtWorkoutDuration(w.duration_seconds);
    if (dur) metaParts.push(dur);
    if (w.tss != null) metaParts.push('TSS ' + Math.round(w.tss));

    var src = w.source || '';
    var hasStrava = src.indexOf('strava') !== -1 || !!w.strava_activity_url;
    var hasStryd  = src.indexOf('stryd')  !== -1;
    var isManual  = !hasStrava && !hasStryd;

    var badgesHTML = '';
    if (isManual) {
      badgesHTML = '<div class="src-badge manual" title="Manual"><i class="ti ti-pencil" style="font-size:12px;"></i></div>';
    } else {
      if (hasStryd)  badgesHTML += '<div class="src-badge stryd"  title="Stryd">S</div>';
      if (hasStrava) badgesHTML += '<div class="src-badge strava" title="Strava">St</div>';
    }

    return '<div class="workout' + (extraCls ? ' ' + extraCls : '') + '">' +
      '<div class="icon-wrap ' + ic.cls + '"><i class="ti ' + ic.icon + '"></i></div>' +
      '<div class="info">' +
        '<div class="ttl">' + titleText + '</div>' +
        '<div class="meta">' + metaParts.join(' · ') + '</div>' +
      '</div>' +
      '<div class="sources">' + badgesHTML + '</div>' +
    '</div>';
  }

  async function loadRecentWorkoutsCard(userId) {
    var row2 = document.getElementById('row-2');
    if (!row2) return;

    var card = document.getElementById('workouts-card');
    if (!card) {
      card = document.createElement('div');
      card.id = 'workouts-card';
      card.className = 'card workouts';
      row2.appendChild(card);
    }

    var today = new Date();
    var from14 = new Date(today);
    from14.setDate(from14.getDate() - 14);

    var workouts = [];
    try {
      var res = await fetch(
        '/api/workouts?from=' + isoDate(from14) + '&to=' + isoDate(today)
      );
      if (res.ok) workouts = await res.json();
    } catch (_) { workouts = []; }

    workouts.sort(function (a, b) {
      if (b.workout_date > a.workout_date) return 1;
      if (b.workout_date < a.workout_date) return -1;
      return 0;
    });

    var header =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-run"></i>Recent workouts</div>' +
        '<a href="/log">View all</a>' +
      '</div>';

    if (!workouts.length) {
      card.innerHTML = header +
        '<div class="workouts-empty">No workouts in the last 14 days — log one.</div>';
      return;
    }

    var top4 = workouts.slice(0, 4);
    var listHTML = '';
    top4.forEach(function (w, i) {
      listHTML += buildWorkoutRow(w, i === 3 ? 'workout-desktop-only' : '');
    });

    card.innerHTML = header + '<div class="list">' + listHTML + '</div>';
  }

  /* ---- Habits Day-Grid card ---- */

  function isoWeekMonday(d) {
    var day = d.getDay();
    var diff = (day === 0) ? -6 : 1 - day;
    return new Date(d.getFullYear(), d.getMonth(), d.getDate() + diff);
  }

  function addDays(d, n) {
    return new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
  }

  function buildHabitRow(habit, weekDates, todayStr, logsByHabit, userId, streakNum) {
    var logsForHabit = logsByHabit[habit.id] || {};
    var cellsHTML = '';
    weekDates.forEach(function (dateStr) {
      var isFuture = dateStr > todayStr;
      var log = logsForHabit[dateStr];
      var isDone = !!log;
      var isToday = dateStr === todayStr;
      var cls = 'day-cell' + (isDone ? ' done' : '') + (isToday ? ' today' : '') + (isFuture ? ' future' : '');
      var inner = isDone ? '<i class="ti ti-check"></i>' : '';
      cellsHTML +=
        '<div class="' + cls + '"' +
        ' data-habit-id="' + habit.id + '"' +
        ' data-date="' + dateStr + '"' +
        ' data-log-id="' + (log ? log.id : '') + '">' +
        inner + '</div>';
    });
    return '<div class="week-row" data-habit-row="' + habit.id + '">' +
      '<div class="habit-name" title="' + habit.name + '">' + habit.name + '</div>' +
      cellsHTML +
      '<div class="streak-col"><span class="num">' + streakNum + '</span>d</div>' +
    '</div>';
  }

  async function refreshHabitRow(card, habit, weekDates, todayStr, userId) {
    var logs = [];
    try {
      var lr = await fetch('/api/habits/logs?from=' + weekDates[0] + '&to=' + weekDates[6]);
      if (lr.ok) logs = await lr.json();
    } catch (_) {}

    var logsForHabit = {};
    logs.forEach(function (l) {
      if (l.habit_id === habit.id) logsForHabit[l.logged_date] = l;
    });

    var streakNum = 0;
    try {
      var sr = await fetch('/api/habits/stats?habit_id=' + habit.id + '&days=30');
      if (sr.ok) { var sd = await sr.json(); streakNum = sd.streak || 0; }
    } catch (_) {}

    var tmp = document.createElement('div');
    tmp.innerHTML = buildHabitRow(habit, weekDates, todayStr, { [habit.id]: logsForHabit }, userId, streakNum);
    var newRow = tmp.firstChild;
    var existingRow = card.querySelector('[data-habit-row="' + habit.id + '"]');
    if (existingRow) existingRow.parentNode.replaceChild(newRow, existingRow);

    var footerBadge = card.querySelector('[data-streak-badge="' + habit.id + '"]');
    if (footerBadge) footerBadge.textContent = habit.name.split(' ')[0] + ' ' + streakNum + 'd';

    attachHabitCellListeners(card, [habit], weekDates, todayStr, userId);
  }

  function attachHabitCellListeners(card, habits, weekDates, todayStr, userId) {
    var habitMap = {};
    habits.forEach(function (h) { habitMap[h.id] = h; });
    card.querySelectorAll('.day-cell:not(.future)').forEach(function (cell) {
      if (cell._hasListener) return;
      cell._hasListener = true;
      cell.addEventListener('click', async function () {
        var hid = cell.getAttribute('data-habit-id');
        var dateStr = cell.getAttribute('data-date');
        var logId = cell.getAttribute('data-log-id');
        var habit = habitMap[hid];
        if (!habit) return;
        try {
          if (logId) {
            await fetch('/api/habits/logs/' + logId, { method: 'DELETE' });
          } else {
            await fetch('/api/habits/logs', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ habit_id: hid, logged_date: dateStr })
            });
          }
        } catch (_) { return; }
        await refreshHabitRow(card, habit, weekDates, todayStr, userId);
      });
    });
  }

  async function loadHabitsCard(userId) {
    var row4 = document.getElementById('row-4');
    if (!row4) return;

    var card = document.getElementById('habits-card');
    if (!card) {
      card = document.createElement('div');
      card.id = 'habits-card';
      card.className = 'card habits';
      row4.insertBefore(card, row4.firstChild);
    }

    var header =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-checkbox"></i>Habits · this week</div>' +
        '<a href="/habits">All</a>' +
      '</div>';

    card.innerHTML = header + '<div style="font-size:13px;color:var(--text-tertiary);padding:8px 4px;">Loading…</div>';

    var habits = [];
    try {
      var hr = await fetch('/api/habits');
      if (hr.ok) habits = await hr.json();
    } catch (_) {}

    if (!habits.length) {
      card.innerHTML = header +
        '<div class="habits-empty">Add a habit to start tracking your week — <a href="/habits">go to Habits</a></div>';
      return;
    }

    var today = new Date();
    var todayStr = isoDate(today);
    var monday = isoWeekMonday(today);
    var weekDates = [];
    for (var i = 0; i < 7; i++) weekDates.push(isoDate(addDays(monday, i)));

    var allLogs = [];
    try {
      var lr2 = await fetch('/api/habits/logs?from=' + weekDates[0] + '&to=' + weekDates[6]);
      if (lr2.ok) allLogs = await lr2.json();
    } catch (_) {}

    var logsByHabit = {};
    allLogs.forEach(function (l) {
      if (!logsByHabit[l.habit_id]) logsByHabit[l.habit_id] = {};
      logsByHabit[l.habit_id][l.logged_date] = l;
    });

    var streaks = {};
    await Promise.all(habits.map(async function (h) {
      try {
        var sr = await fetch('/api/habits/stats?habit_id=' + h.id + '&days=30');
        if (sr.ok) { var sd = await sr.json(); streaks[h.id] = sd.streak || 0; }
        else streaks[h.id] = 0;
      } catch (_) { streaks[h.id] = 0; }
    }));

    var headerRowHTML =
      '<div class="week-row">' +
        '<div class="week-header first">Habit</div>' +
        '<div class="week-header">M</div><div class="week-header">T</div><div class="week-header">W</div>' +
        '<div class="week-header">T</div><div class="week-header">F</div><div class="week-header">S</div>' +
        '<div class="week-header">S</div>' +
        '<div class="week-header streak-hdr">Streak</div>' +
      '</div>';

    var rowsHTML = '';
    habits.forEach(function (h) {
      rowsHTML += buildHabitRow(h, weekDates, todayStr, logsByHabit, userId, streaks[h.id] || 0);
    });

    var footerBadges = habits
      .filter(function (h) { return (streaks[h.id] || 0) > 0; })
      .map(function (h) {
        return '<span class="badge" data-streak-badge="' + h.id + '">' +
          h.name.split(' ')[0] + ' ' + (streaks[h.id] || 0) + 'd</span>';
      })
      .join('');

    card.innerHTML = header +
      '<div class="week-grid">' + headerRowHTML + rowsHTML + '</div>' +
      '<div class="habits-streak-footer">Streaks: ' + footerBadges + '</div>';

    attachHabitCellListeners(card, habits, weekDates, todayStr, userId);
  }

  /* ---- Habits Stats Graph card ---- */

  async function loadHabitsStatsCard(userId) {
    var row4 = document.getElementById('row-4');
    if (!row4) return;

    var today = new Date();
    var todayStr = isoDate(today);
    var monday = isoWeekMonday(today);
    var weekDates = [];
    for (var i = 0; i < 7; i++) weekDates.push(isoDate(addDays(monday, i)));

    var DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];
    var DOW_LABELS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];

    var habits = [], logs = [], allStats = [];
    try {
      var results = await Promise.all([
        fetch('/api/habits'),
        fetch('/api/habits/logs?from=' + weekDates[0] + '&to=' + weekDates[6]),
        fetch('/api/habits/stats?days=30')
      ]);
      if (results[0].ok) habits = await results[0].json();
      if (results[1].ok) logs = await results[1].json();
      if (results[2].ok) allStats = await results[2].json();
    } catch (_) {}

    var activeCount = habits.length;

    // Zero-habits: hide the card entirely
    if (activeCount === 0) return;

    var card = document.getElementById('habits-stats-card');
    if (!card) {
      card = document.createElement('div');
      card.id = 'habits-stats-card';
      card.className = 'card habits-graph';
      row4.appendChild(card);
    }

    // Compute habitsCompletedByDay — count distinct (habit_id, day) log entries per day
    var habitsCompletedByDay = {};
    DAY_NAMES.forEach(function (d) { habitsCompletedByDay[d] = 0; });
    var seen = {};
    logs.forEach(function (l) {
      var key = l.habit_id + '|' + l.logged_date;
      if (seen[key]) return;
      seen[key] = true;
      var parts = l.logged_date.split('-');
      var d = new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
      var idx = d.getDay() === 0 ? 6 : d.getDay() - 1; // Mon=0 … Sun=6
      habitsCompletedByDay[DAY_NAMES[idx]]++;
    });

    var totalCompleted = DAY_NAMES.reduce(function (s, d) { return s + habitsCompletedByDay[d]; }, 0);
    var totalPossible = activeCount * 7;
    var completionRate = totalPossible > 0 ? Math.round(totalCompleted / totalPossible * 100) : 0;

    // bestDay: day name(s) with the highest N; supports ties
    var maxN = Math.max.apply(null, DAY_NAMES.map(function (d) { return habitsCompletedByDay[d]; }));
    var bestDayNames;
    if (maxN === 0) {
      bestDayNames = '—';
    } else {
      bestDayNames = DAY_NAMES.filter(function (d) { return habitsCompletedByDay[d] === maxN; }).join(' & ');
    }

    // longestStreak: max streak across all habits from /api/habits/stats list response
    var longestStreakNum = 0;
    var longestStreakHabit = '—';
    if (Array.isArray(allStats)) {
      allStats.forEach(function (s) {
        if (s.streak > longestStreakNum) {
          longestStreakNum = s.streak;
          longestStreakHabit = s.habit_name;
        }
      });
    }
    var streakText = longestStreakNum > 0
      ? longestStreakNum + ' days · ' + longestStreakHabit
      : '—';

    // Build 7-bar chart
    var barsHTML = '';
    weekDates.forEach(function (dateStr, i) {
      var dayName = DAY_NAMES[i];
      var n = habitsCompletedByDay[dayName];
      var isFuture = dateStr > todayStr;
      var isToday = dateStr === todayStr;
      var cls = 'hg-day' + (isToday ? ' today' : '') + (isFuture ? ' future' : '');
      var pct = isFuture ? 8 : (activeCount > 0 ? Math.round(n / activeCount * 100) : 0);
      var label = isFuture ? '—' : String(n);
      barsHTML +=
        '<div class="' + cls + '">' +
          '<div class="bar-val">' + label + '</div>' +
          '<div class="bar-wrap"><div class="bar" style="height:' + Math.max(8, pct) + '%;"></div></div>' +
          '<div class="dow">' + DOW_LABELS[i] + '</div>' +
        '</div>';
    });

    var fillPct = totalPossible > 0 ? Math.round(totalCompleted / totalPossible * 100) : 0;

    card.innerHTML =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-chart-bar"></i>Habits · stats</div>' +
        '<span class="meta">This week</span>' +
      '</div>' +
      '<div class="hg-body">' +
        '<div class="hg-bars">' +
          '<div class="hg-label">Completed per day</div>' +
          '<div class="hg-chart">' + barsHTML + '</div>' +
        '</div>' +
        '<div class="hg-stats">' +
          '<div class="hg-stat">' +
            '<div class="l">This week</div>' +
            '<div class="v bar-stat">' + totalCompleted +
              '<span class="sub">/ ' + totalPossible + ' possible</span>' +
              '<span class="pct-bar"><span class="fill" style="width:' + fillPct + '%;"></span></span>' +
            '</div>' +
          '</div>' +
          '<div class="hg-stat">' +
            '<div class="l">Best day</div>' +
            '<div class="v">' + bestDayNames + '</div>' +
          '</div>' +
          '<div class="hg-stat">' +
            '<div class="l">Completion rate</div>' +
            '<div class="v">' + completionRate + '%</div>' +
          '</div>' +
          '<div class="hg-stat">' +
            '<div class="l">Longest streak</div>' +
            '<div class="v">' + streakText + '</div>' +
          '</div>' +
        '</div>' +
      '</div>';
  }

  /* ---- Row 3: Trend cards (HRV · Weekly TSS · RHR · Weight) ---- */

  function _trendAreaSpark(vals, strokeColor, fillColor, baselineVal) {
    var W = 200, H = 48, PAD = 4;
    var nonNull = vals.filter(function (v) { return v != null; });
    if (!nonNull.length) {
      return '<svg class="trend-sparkline" viewBox="0 0 200 48" preserveAspectRatio="none"></svg>';
    }
    var minV = Math.min.apply(null, nonNull);
    var maxV = Math.max.apply(null, nonNull);
    if (baselineVal != null) {
      minV = Math.min(minV, baselineVal);
      maxV = Math.max(maxV, baselineVal);
    }
    if (minV === maxV) { minV -= 1; maxV += 1; }

    function normY(v) {
      return H - PAD - ((v - minV) / (maxV - minV)) * (H - 2 * PAD);
    }

    var pts = [];
    for (var i = 0; i < vals.length; i++) {
      if (vals[i] == null) continue;
      var x = vals.length > 1 ? (i / (vals.length - 1)) * W : W / 2;
      pts.push({ x: x, y: normY(vals[i]) });
    }
    if (!pts.length) {
      return '<svg class="trend-sparkline" viewBox="0 0 200 48" preserveAspectRatio="none"></svg>';
    }

    var linePath = pts.map(function (p, idx) {
      return (idx === 0 ? 'M' : 'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1);
    }).join(' ');

    var lastPt = pts[pts.length - 1];
    var areaPath = linePath +
      ' L' + lastPt.x.toFixed(1) + ',' + H +
      ' L' + pts[0].x.toFixed(1) + ',' + H + ' Z';

    var uid = 'tg' + Math.random().toString(36).slice(2, 7);
    var gradDef = '<defs><linearGradient id="' + uid + '" x1="0" y1="0" x2="0" y2="1">' +
      '<stop offset="0%" stop-color="' + fillColor + '" stop-opacity="0.45"/>' +
      '<stop offset="100%" stop-color="' + fillColor + '" stop-opacity="0"/>' +
      '</linearGradient></defs>';

    var out = '<svg class="trend-sparkline" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">' + gradDef;
    out += '<path d="' + areaPath + '" fill="url(#' + uid + ')" stroke="none"/>';
    out += '<path d="' + linePath + '" fill="none" stroke="' + strokeColor + '" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>';
    if (baselineVal != null) {
      var by = normY(baselineVal);
      out += '<line x1="0" y1="' + by.toFixed(1) + '" x2="' + W + '" y2="' + by.toFixed(1) + '" stroke="' + strokeColor + '" stroke-width="1" stroke-dasharray="3 4" opacity="0.4"/>';
    }
    out += '<circle cx="' + lastPt.x.toFixed(1) + '" cy="' + lastPt.y.toFixed(1) + '" r="3" fill="' + strokeColor + '"/>';
    out += '</svg>';
    return out;
  }

  function _trendBarSpark(vals, peakIdx) {
    var W = 200, H = 48, GAP = 3;
    var nonNull = vals.filter(function (v) { return v != null && v > 0; });
    if (!nonNull.length) {
      return '<svg class="trend-sparkline" viewBox="0 0 200 48" preserveAspectRatio="none"></svg>';
    }
    var maxV = Math.max.apply(null, nonNull);
    var n = vals.length;
    var barW = Math.max(4, Math.floor((W - GAP * (n - 1)) / n));
    var step = barW + GAP;
    var startX = (W - (barW * n + GAP * (n - 1))) / 2;

    var out = '<svg class="trend-sparkline" viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="none">';
    for (var i = 0; i < vals.length; i++) {
      var v = vals[i];
      var x = startX + i * step;
      if (!v) {
        out += '<rect x="' + x.toFixed(1) + '" y="' + (H - 2) + '" width="' + barW + '" height="2" rx="1" fill="#e5e7eb"/>';
        continue;
      }
      var barH = Math.max(4, (v / maxV) * (H - 4));
      var y = (H - barH).toFixed(1);
      var fill = i === peakIdx ? '#f97316' : '#fdba74';
      out += '<rect x="' + x.toFixed(1) + '" y="' + y + '" width="' + barW + '" height="' + barH.toFixed(1) + '" rx="2" fill="' + fill + '"/>';
    }
    out += '</svg>';
    return out;
  }

  function _trendDeltaPill(text, direction) {
    var dirClass = { up: 'trend-delta-pill--up', down: 'trend-delta-pill--down', flat: 'trend-delta-pill--flat' };
    return '<span class="trend-delta-pill ' + (dirClass[direction] || dirClass.flat) + '">' + (text || '—') + '</span>';
  }

  function _trendCardInnerHTML(iconHTML, title, period, bigVal, unit, pillHTML, sparkSVG, footLeft, footRight, extraHTML) {
    return '<div class="trend-card-header">' +
        iconHTML +
        '<span class="trend-card-title">' + title + '</span>' +
        '<span class="trend-card-period">' + period + '</span>' +
      '</div>' +
      '<div class="trend-card-stat">' +
        '<span class="trend-card-big">' + bigVal + '</span>' +
        '<span class="trend-card-unit">' + unit + '</span>' +
        pillHTML +
      '</div>' +
      sparkSVG +
      '<div class="trend-card-footer">' +
        '<span>' + footLeft + '</span>' +
        '<span>' + footRight + '</span>' +
      '</div>' +
      (extraHTML || '');
  }

  function _trendCardErrorHTML(iconHTML, title, period) {
    return '<div class="trend-card-header">' +
        iconHTML +
        '<span class="trend-card-title">' + title + '</span>' +
        '<span class="trend-card-period">' + period + '</span>' +
      '</div>' +
      "<div class=\"trend-card-error\">Couldn't load data</div>";
  }

  function renderHRVTrendCard(el, summary) {
    var iconHTML = '<i class="ti ti-heart-rate-monitor" style="font-size:16px;color:var(--teal-text);"></i>';
    if (!summary) {
      el.innerHTML = _trendCardErrorHTML(iconHTML, 'HRV', '30d');
      return;
    }
    var series = (summary.hrv && summary.hrv.series) || [];
    var baseline = summary.hrv ? summary.hrv.baseline_mean : null;
    var sparkVals = series.map(function (d) { return d.value; });
    var latest = null;
    for (var i = series.length - 1; i >= 0; i--) {
      if (series[i].value != null) { latest = series[i].value; break; }
    }
    if (latest === null) {
      el.innerHTML = _trendCardErrorHTML(iconHTML, 'HRV', '30d');
      return;
    }
    var pillHTML;
    if (baseline != null) {
      var delta = latest - baseline;
      var absD = Math.abs(delta);
      var dir = absD < 2 ? 'flat' : (delta > 0 ? 'up' : 'down');
      var sign = delta > 0 ? '+' : '−';
      pillHTML = _trendDeltaPill(sign + Math.round(absD) + ' ms', dir);
    } else {
      pillHTML = _trendDeltaPill('—', 'flat');
    }
    el.innerHTML = _trendCardInnerHTML(iconHTML, 'HRV', '30d',
      Math.round(latest), 'ms', pillHTML,
      _trendAreaSpark(sparkVals, '#1e6438', '#1e6438', baseline),
      baseline != null ? 'Baseline ' + Math.round(baseline) + ' ms' : '30d avg',
      'Today ' + Math.round(latest) + ' ms', '');
  }

  function renderRHRTrendCard(el, summary) {
    var iconHTML = '<i class="ti ti-heart" style="font-size:16px;color:#dc2626;"></i>';
    if (!summary) {
      el.innerHTML = _trendCardErrorHTML(iconHTML, 'RHR', '30d');
      return;
    }
    var series = (summary.rhr && summary.rhr.series) || [];
    var baseline = summary.rhr ? summary.rhr.baseline_mean : null;
    var sparkVals = series.map(function (d) { return d.value; });
    var latest = null;
    for (var i = series.length - 1; i >= 0; i--) {
      if (series[i].value != null) { latest = series[i].value; break; }
    }
    if (latest === null) {
      el.innerHTML = _trendCardErrorHTML(iconHTML, 'RHR', '30d');
      return;
    }
    var pillHTML;
    if (baseline != null) {
      var delta = latest - baseline;
      var absD = Math.abs(delta);
      var dir = absD < 1 ? 'flat' : (delta < 0 ? 'up' : 'down');
      var sign = delta > 0 ? '+' : '−';
      pillHTML = _trendDeltaPill(sign + Math.round(absD) + ' bpm', dir);
    } else {
      pillHTML = _trendDeltaPill('—', 'flat');
    }
    el.innerHTML = _trendCardInnerHTML(iconHTML, 'RHR', '30d',
      Math.round(latest), 'bpm', pillHTML,
      _trendAreaSpark(sparkVals, '#dc2626', '#dc2626', baseline),
      baseline != null ? 'Baseline ' + Math.round(baseline) + ' bpm' : '30d avg',
      'Today ' + Math.round(latest) + ' bpm', '');
  }

  function renderWeeklyTSSTrendCard(el, summary) {
    var iconHTML = '<i class="ti ti-flame" style="font-size:16px;color:var(--orange-text);"></i>';
    if (!summary) {
      el.innerHTML = _trendCardErrorHTML(iconHTML, 'Weekly TSS', '8d');
      return;
    }
    var series = (summary.tss && summary.tss.series) || [];
    var last8 = series.slice(-8);
    if (!last8.length) {
      el.innerHTML = _trendCardErrorHTML(iconHTML, 'Weekly TSS', '8d');
      return;
    }
    var sparkVals = last8.map(function (d) { return d.value; });
    var weekTotal = last8.reduce(function (s, d) { return s + (d.value || 0); }, 0);
    var peakIdx = -1, peakVal = -Infinity;
    sparkVals.forEach(function (v, i) {
      if (v != null && v > peakVal) { peakVal = v; peakIdx = i; }
    });
    var bigDay = null;
    if (peakIdx >= 0 && last8[peakIdx]) {
      var p = last8[peakIdx].date.split('-');
      var d = new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
      bigDay = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][d.getDay()];
    }
    var pillHTML;
    var prev8 = series.slice(-16, -8);
    if (prev8.length) {
      var prevTotal = prev8.reduce(function (s, d) { return s + (d.value || 0); }, 0);
      if (prevTotal > 0) {
        var pct = ((weekTotal - prevTotal) / prevTotal) * 100;
        var absP = Math.abs(pct);
        var dir = absP < 5 ? 'flat' : (pct > 0 ? 'up' : 'down');
        var sign = pct > 0 ? '+' : '−';
        pillHTML = _trendDeltaPill(sign + absP.toFixed(0) + '%', dir);
      } else {
        pillHTML = _trendDeltaPill('—', 'flat');
      }
    } else {
      pillHTML = _trendDeltaPill('—', 'flat');
    }
    el.innerHTML = _trendCardInnerHTML(iconHTML, 'Weekly TSS', '8d',
      Math.round(weekTotal), 'TSS', pillHTML,
      _trendBarSpark(sparkVals, peakIdx),
      'Last 8 days',
      bigDay ? 'Peak: ' + bigDay : '—', '');
  }

  function _buildWeightQuickInput() {
    return '<div class="trend-quick-input">' +
      '<input type="number" class="trend-weight-input" step="0.1" min="20" max="300"' +
        ' placeholder="kg" inputmode="decimal" aria-label="Weight in kg">' +
      '<button type="button" class="trend-quick-save-btn" data-save="weight">Save</button>' +
    '</div>';
  }

  function _wireWeightSave(cardEl, userId) {
    var btn = cardEl.querySelector('[data-save="weight"]');
    var inp = cardEl.querySelector('.trend-weight-input');
    if (!btn || !inp) return;
    btn.addEventListener('click', async function () {
      var val = parseFloat(inp.value);
      if (!val || val < 20 || val > 300) { inp.focus(); return; }
      btn.disabled = true;
      try {
        var todayStr = isoDate(new Date());
        var res = await fetch('/api/weight', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ weight_kg: val, recorded_date: todayStr })
        });
        if (res.ok || res.status === 409) {
          inp.value = '';
          var wRes = await fetch('/api/weight');
          if (wRes.ok) {
            var entries = await wRes.json();
            renderWeightTrendCard(cardEl, entries, userId);
          }
        }
      } catch (_) { /* silent */ }
      btn.disabled = false;
    });
  }

  function renderWeightTrendCard(el, weightEntries, userId) {
    var iconHTML = '<i class="ti ti-scale" style="font-size:16px;color:var(--blue-text);"></i>';
    var quickInput = _buildWeightQuickInput();

    if (!weightEntries || !weightEntries.length) {
      el.innerHTML = _trendCardErrorHTML(iconHTML, 'Weight', '30d') + quickInput;
      _wireWeightSave(el, userId);
      return;
    }

    var sorted = weightEntries.slice().sort(function (a, b) {
      return a.recorded_date.localeCompare(b.recorded_date);
    });
    var cutoffD = new Date();
    cutoffD.setDate(cutoffD.getDate() - 29);
    var cutoffStr = isoDate(cutoffD);
    var recent = sorted.filter(function (e) { return e.recorded_date >= cutoffStr; });
    if (!recent.length) recent = sorted.slice(-1);

    var latest = recent[recent.length - 1];
    var sparkVals = recent.map(function (e) { return e.weight_kg; });

    var pillHTML;
    if (recent.length >= 2) {
      var delta = latest.weight_kg - recent[0].weight_kg;
      var absD = Math.abs(delta);
      if (absD < 0.1) {
        pillHTML = _trendDeltaPill('—', 'flat');
      } else {
        var sign = delta > 0 ? '+' : '−';
        pillHTML = _trendDeltaPill(sign + absD.toFixed(1) + ' kg', 'flat');
      }
    } else {
      pillHTML = _trendDeltaPill('—', 'flat');
    }

    el.innerHTML = _trendCardInnerHTML(iconHTML, 'Weight', '30d',
      latest.weight_kg.toFixed(1), 'kg', pillHTML,
      _trendAreaSpark(sparkVals, '#2b4ca8', '#2b4ca8', null),
      '30d trend',
      'Latest: ' + latest.weight_kg.toFixed(1) + ' kg',
      quickInput);
    _wireWeightSave(el, userId);
  }

  async function loadRow3(userId) {
    var row3 = document.getElementById('row-3');
    if (!row3) return;

    var cardDefs = [
      { id: 'trend-card-hrv' },
      { id: 'trend-card-tss' },
      { id: 'trend-card-rhr' },
      { id: 'trend-card-weight' },
    ];

    row3.innerHTML = '';
    cardDefs.forEach(function (c) {
      var el = document.createElement('div');
      el.id = c.id;
      el.className = 'trend-card';
      el.innerHTML =
        '<div style="display:flex;flex-direction:column;gap:10px;">' +
        '<div class="trend-skeleton-line" style="height:16px;width:50%"></div>' +
        '<div class="trend-skeleton-line" style="height:28px;width:65%"></div>' +
        '<div class="trend-skeleton-line" style="height:48px"></div>' +
        '<div class="trend-skeleton-line" style="height:12px;width:80%"></div>' +
        '</div>';
      row3.appendChild(el);
    });

    var summary = null;
    var summaryFailed = false;
    var weightEntries = null;

    var results = await Promise.allSettled([
      fetch('/trends/summary?range=30d'),
      fetch('/api/weight')
    ]);

    var tResult = results[0];
    if (tResult.status === 'fulfilled' && tResult.value.ok) {
      try { summary = await tResult.value.json(); } catch (_) { summaryFailed = true; }
    } else {
      summaryFailed = true;
    }

    var wResult = results[1];
    if (wResult.status === 'fulfilled' && wResult.value.ok) {
      try { weightEntries = await wResult.value.json(); } catch (_) {}
    }

    var passedSummary = summaryFailed ? null : summary;
    renderHRVTrendCard(document.getElementById('trend-card-hrv'), passedSummary);
    renderWeeklyTSSTrendCard(document.getElementById('trend-card-tss'), passedSummary);
    renderRHRTrendCard(document.getElementById('trend-card-rhr'), passedSummary);
    renderWeightTrendCard(document.getElementById('trend-card-weight'), weightEntries, userId);
  }

  /* ---- Log Today card ---- */

  function renderLogTodayCard(card, existing, userId, today) {
    var v = existing || {};

    function field(id, label, required, value, placeholder) {
      var req = required ? '<span class="lt-required">*</span>' : '';
      var val = value != null ? ' value="' + value + '"' : '';
      return '<div class="lt-field">' +
        '<label class="lt-label" for="lt-' + id + '">' + label + req + '</label>' +
        '<input class="lt-input" type="number" id="lt-' + id + '" name="' + id + '"' +
          (required ? ' data-required="1"' : '') +
          (placeholder ? ' placeholder="' + placeholder + '"' : '') +
          val + ' step="any">' +
        '<div class="lt-error" id="lt-err-' + id + '"></div>' +
      '</div>';
    }

    card.innerHTML =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-pencil-plus"></i>Log Today</div>' +
        '<span class="lt-date-lbl">' + today + '</span>' +
      '</div>' +
      '<form class="lt-form" id="lt-form" novalidate>' +
        '<div class="lt-grid">' +
          field('sleep_hours',   'Sleep hours',   true,  v.sleep_hours,   '0–24') +
          field('sleep_quality', 'Sleep quality', true,  v.sleep_quality, '1–5') +
          field('energy',        'Energy',        true,  v.energy,        '1–5') +
          field('mood',          'Mood',          true,  v.mood,          '1–5') +
          field('resting_hr',    'Resting HR',    false, v.resting_hr,    'bpm') +
          field('hrv',           'HRV',           false, v.hrv,           'ms') +
        '</div>' +
        '<div class="lt-actions">' +
          '<button class="lt-save-btn" type="submit" id="lt-save-btn">Save</button>' +
          '<div class="lt-feedback" id="lt-feedback"></div>' +
        '</div>' +
      '</form>';

    card.querySelector('#lt-form').addEventListener('submit', async function (e) {
      e.preventDefault();
      card.querySelectorAll('.lt-error').forEach(function (el) { el.textContent = ''; });

      var valid = true;

      function val(name) {
        var el = card.querySelector('#lt-' + name);
        return el ? el.value.trim() : '';
      }
      function err(name, msg) { var el = card.querySelector('#lt-err-' + name); if (el) el.textContent = msg; valid = false; }

      var shStr  = val('sleep_hours');
      var sqStr  = val('sleep_quality');
      var enStr  = val('energy');
      var moStr  = val('mood');
      var rhrStr = val('resting_hr');
      var hrvStr = val('hrv');

      if (shStr === '') {
        err('sleep_hours', 'Required');
      } else {
        var sh = parseFloat(shStr);
        if (isNaN(sh) || sh < 0 || sh > 24) err('sleep_hours', 'Must be 0–24');
      }
      if (sqStr === '') {
        err('sleep_quality', 'Required');
      } else {
        var sq = parseInt(sqStr, 10);
        if (isNaN(sq) || sq < 1 || sq > 5) err('sleep_quality', 'Must be 1–5');
      }
      if (enStr === '') {
        err('energy', 'Required');
      } else {
        var en = parseInt(enStr, 10);
        if (isNaN(en) || en < 1 || en > 5) err('energy', 'Must be 1–5');
      }
      if (moStr === '') {
        err('mood', 'Required');
      } else {
        var mo = parseInt(moStr, 10);
        if (isNaN(mo) || mo < 1 || mo > 5) err('mood', 'Must be 1–5');
      }
      if (rhrStr !== '') {
        var rhr = parseInt(rhrStr, 10);
        if (isNaN(rhr) || rhr < 1 || String(rhr) !== rhrStr) err('resting_hr', 'Positive integer');
      }
      if (hrvStr !== '') {
        var hrv2 = parseInt(hrvStr, 10);
        if (isNaN(hrv2) || hrv2 < 1 || String(hrv2) !== hrvStr) err('hrv', 'Positive integer');
      }

      if (!valid) return;

      var btn = card.querySelector('#lt-save-btn');
      var feedback = card.querySelector('#lt-feedback');
      btn.disabled = true;
      btn.textContent = 'Saving…';
      feedback.className = 'lt-feedback';
      feedback.textContent = '';

      var payload = {
        sleep_hours:   parseFloat(shStr),
        sleep_quality: parseInt(sqStr, 10),
        energy:        parseInt(enStr, 10),
        mood:          parseInt(moStr, 10)
      };
      if (rhrStr !== '') payload.resting_hr = parseInt(rhrStr, 10);
      if (hrvStr !== '') payload.hrv = parseInt(hrvStr, 10);

      try {
        var res = await fetch('/api/daily-metrics/' + encodeURIComponent(userId) + '/' + today, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          feedback.className = 'lt-feedback lt-feedback--ok';
          feedback.textContent = 'Saved';
          setTimeout(function () { feedback.textContent = ''; }, 3000);
          loadSleepCard(userId);
          loadReadinessCard(userId);
          loadRow3(userId);
        } else {
          var errData = null;
          try { errData = await res.json(); } catch (_) {}
          feedback.className = 'lt-feedback lt-feedback--err';
          feedback.textContent = (errData && errData.detail) ? String(errData.detail) : 'Save failed (' + res.status + ')';
        }
      } catch (_) {
        feedback.className = 'lt-feedback lt-feedback--err';
        feedback.textContent = 'Network error — try again';
      }

      btn.disabled = false;
      btn.textContent = 'Save';
    });
  }

  async function loadLogTodayCard(userId) {
    var rowLog = document.getElementById('row-log');
    if (!rowLog) return;

    var card = document.getElementById('log-today-card');
    if (!card) {
      card = document.createElement('div');
      card.id = 'log-today-card';
      card.className = 'card log-today';
      rowLog.appendChild(card);
    }

    var today = isoDate(new Date());
    var existing = null;
    try {
      var res = await fetch('/api/daily-metrics/' + encodeURIComponent(userId) + '/' + today);
      if (res.ok) existing = await res.json();
    } catch (_) {}

    renderLogTodayCard(card, existing, userId, today);
  }

  /* ---- Init ---- */

  async function init() {
    setGreetingDate();
    var userId = null;
    try {
      var res = await fetch('/api/auth/me');
      if (res.status === 401 || res.status === 403) { window.location.href = '/login'; return; }
      if (!res.ok) throw new Error('auth/me failed');
      var user = await res.json();
      var name = user.name || '';
      userId = user.id;
      setGreetingText(name);
      setNavAvatar(name);
    } catch (_) {
      setGreetingText('');
    }

    if (userId) {
      loadReadinessCard(userId);
      loadSleepCard(userId);
      loadPerformanceCard(userId);
      loadRecentWorkoutsCard(userId);
      loadLogTodayCard(userId);
      loadRow3(userId);
      loadHabitsCard(userId);
      loadHabitsStatsCard(userId);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
