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
        var res = await fetch('/api/readiness/compute?user_id=' + userId, { method: 'POST' });
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
      todayRes = await fetch('/api/readiness/today?user_id=' + userId);
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
        fetch('/api/readiness?user_id=' + userId + '&from=' + fromStr + '&to=' + todayStr),
        fetch('/api/daily-metrics?user_id=' + userId + '&from=' + fromStr + '&to=' + todayStr)
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
      var r = await fetch('/api/personal-records?user_id=' + userId);
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
        '/api/workouts?user_id=' + userId +
        '&from=' + isoDate(from6m) + '&to=' + isoDate(today)
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
        '/api/workouts?user_id=' + userId +
        '&from=' + isoDate(from14) + '&to=' + isoDate(today)
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

  /* ---- Init ---- */

  async function init() {
    setGreetingDate();
    var userId = null;
    try {
      var res = await fetch('/api/users');
      if (!res.ok) throw new Error('users fetch failed');
      var users = await res.json();
      if (Array.isArray(users) && users.length > 0) {
        var name = users[0].name || '';
        userId = users[0].id;
        setGreetingText(name);
        setNavAvatar(name);
      } else {
        setGreetingText('');
      }
    } catch (_) {
      setGreetingText('');
    }

    if (userId) {
      loadReadinessCard(userId);
      loadSleepCard(userId);
      loadPerformanceCard(userId);
      loadRecentWorkoutsCard(userId);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
