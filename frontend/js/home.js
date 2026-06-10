(function () {
  /* ---- Centralized fetch helper ---- */

  async function _homeFetch(url) {
    try {
      var r = await fetch(url);
      if (!r.ok) return { ok: false, data: null, status: r.status };
      var data = await r.json();
      return { ok: true, data: data, status: r.status };
    } catch (_) {
      return { ok: false, data: null, status: 0 };
    }
  }

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

  // Returns today's date string (YYYY-MM-DD) in Asia/Bangkok timezone.
  function bangkokTodayStr() {
    return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' });
  }

  // Returns a Date object whose local year/month/day matches Bangkok's current date.
  function bangkokToday() {
    var s = bangkokTodayStr();
    var p = s.split('-');
    return new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
  }

  function addISODays(isoStr, n) {
    var d = new Date(isoStr + 'T00:00:00');
    d.setDate(d.getDate() + n);
    return isoDate(d);
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

  /* ---- Readiness card ---- */

  var _RD_FACTOR_META = {
    sleep_hours: {
      name: 'Sleep',
      fmt: function (v) { return v != null ? Number(v).toFixed(1) + 'h' : '—'; },
      baseline_key: 'sleep_7d_avg_hours',
    },
    hrv: {
      name: 'HRV',
      fmt: function (v) { return v != null ? Math.round(v) + ' ms' : '—'; },
      baseline_key: 'hrv_7d_avg',
    },
    rhr: {
      name: 'RHR',
      fmt: function (v) { return v != null ? Math.round(v) + ' bpm' : '—'; },
      baseline_key: 'rhr_7d_avg',
    },
    mood: {
      name: 'Mood',
      fmt: function (v) { return v != null ? v + '/5' : '—'; },
      baseline_key: null,
    },
    energy: {
      name: 'Energy',
      fmt: function (v) { return v != null ? v + '/5' : '—'; },
      baseline_key: null,
    },
  };

  var _RD_LABEL_COLOR = {
    'Excellent': 'var(--green)',
    'Good':      'var(--blue-text)',
    'OK':        'var(--text-secondary)',
    'Caution':   'var(--amber)',
    'Recovery':  'var(--red)',
  };

  function _rdImpactNumeric(impact) {
    return (impact === 'positive' || impact === 'negative') ? 1 : 0;
  }

  function _rdContributorRow(c, baseline) {
    var meta = _RD_FACTOR_META[c.factor] ||
      { name: c.factor, fmt: function (v) { return String(v != null ? v : '—'); }, baseline_key: null };
    var valStr = meta.fmt(c.value);
    var arrow = c.impact === 'positive' ? '↑' : (c.impact === 'negative' ? '↓' : '→');
    var arrowCls = c.impact === 'positive' ? 'rd-arrow--positive' :
      (c.impact === 'negative' ? 'rd-arrow--negative' : 'rd-arrow--neutral');

    var avgCmp = '';
    if (meta.baseline_key && baseline && baseline[meta.baseline_key] != null && c.value != null) {
      avgCmp = parseFloat(c.value) > parseFloat(baseline[meta.baseline_key])
        ? ' (above avg)' : ' (below avg)';
    }

    return '<div class="rd-contributor">' +
      '<span class="rd-factor-name">' + meta.name + '</span>' +
      '<span class="rd-arrow ' + arrowCls + '">' + arrow + '</span>' +
      '<span class="rd-factor-val">' + valStr + avgCmp + '</span>' +
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

    card.innerHTML = '<div class="lbl">Readiness · today</div>' + UIStates.loadingHTML();

    var _rdResult = await _homeFetch('/api/home/readiness?user_id=' + encodeURIComponent(userId));
    if (!_rdResult.ok) {
      card.innerHTML = '<div class="lbl">Readiness · today</div>' +
        UIStates.errorHTML('Could not load readiness data');
      return;
    }
    var data = _rdResult.data;

    /* Null score → no metrics logged today */
    if (data.score === null) {
      card.innerHTML =
        '<div class="lbl">Readiness · today</div>' +
        UIStates.emptyHTML(
          'No metrics logged for today.',
          '<a href="/home#log-today">Log today\'s metrics →</a>'
        );
      return;
    }

    /* Sort contributors by |weight × impact| descending, take top 3 */
    var sortedContributors = (data.contributors || []).slice().sort(function (a, b) {
      var ka = a.weight * _rdImpactNumeric(a.impact);
      var kb = b.weight * _rdImpactNumeric(b.impact);
      return kb - ka;
    });
    var top3 = sortedContributors.slice(0, 3);
    var baseline = data.rolling_baseline || {};

    var labelColor = _RD_LABEL_COLOR[data.score_label] || 'var(--text-secondary)';
    var contributorsHTML = top3.map(function (c) {
      return _rdContributorRow(c, baseline);
    }).join('');

    card.innerHTML =
      '<div class="lbl">Readiness · today</div>' +
      '<div class="score-block">' +
        '<div class="score-label">Score</div>' +
        '<div class="score">' + data.score + '<small>/100</small></div>' +
        '<div class="rd-score-label" style="color:' + labelColor + ';font-size:13px;font-weight:600;margin-top:6px;">' +
          data.score_label +
        '</div>' +
      '</div>' +
      '<div class="rd-contributors">' + contributorsHTML + '</div>';
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

    card.innerHTML = UIStates.loadingHTML();

    var today = bangkokTodayStr();
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

  /* ── PR track icon map ── */
  var _PR_TRACK_ICON = {
    'half_marathon': { cls: 'run',   icon: 'ti-run',     sub: '21.1 km' },
    '10k':           { cls: 'run',   icon: 'ti-run',     sub: '10.0 km' },
    'squat_1rm':     { cls: 'lift',  icon: 'ti-barbell', sub: '1-rep max' },
  };

  function _prTrendIcon(trend) {
    if (trend === 'improving') {
      return '<span class="pr-trend pr-trend--green"><i class="ti ti-arrow-up"></i></span>';
    }
    if (trend === 'declining') {
      return '<span class="pr-trend pr-trend--red"><i class="ti ti-arrow-down"></i></span>';
    }
    /* stable or no_data */
    return '<span class="pr-trend pr-trend--flat" data-trend="' + (trend === 'stable' ? 'stable' : trend) + '">—</span>';
  }

  function _prFmtAchievedOn(isoStr) {
    if (!isoStr) return '';
    var parts = isoStr.split('-');
    var months = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
                  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return months[parseInt(parts[1], 10) - 1] + ' ' + parseInt(parts[2], 10);
  }

  function _buildPrRow(track, isLast) {
    var ic = _PR_TRACK_ICON[track.track_key] || { cls: 'run', icon: 'ti-run', sub: '' };
    var predictedHTML = track.predicted_value_formatted
      ? track.predicted_value_formatted
      : '<span class="pr-dash">—</span>';

    return '<div class="perf-row' + (isLast ? ' perf-row-last' : '') + '" data-pr-row>' +
      '<div class="perf-track">' +
        '<div class="icon-wrap ' + ic.cls + '"><i class="ti ' + ic.icon + '"></i></div>' +
        '<div>' +
          '<div class="trk-name">' + track.track_name + '</div>' +
          '<div class="trk-sub">' + ic.sub + '</div>' +
        '</div>' +
      '</div>' +
      '<div>' +
        '<span class="pc-value">' + (track.current_value_formatted || '—') + '</span>' +
        (track.achieved_on
          ? '<div class="pc-trophy"><i class="ti ti-trophy-filled"></i>' +
            _prFmtAchievedOn(track.achieved_on) + '</div>'
          : '') +
      '</div>' +
      '<div>' + predictedHTML + '</div>' +
      '<div>' + _prTrendIcon(track.trend) + '</div>' +
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

    var perfHeader =
      '<div class="card-head">' +
        '<div class="ttl"><a href="/settings#personal-records" style="color:inherit;text-decoration:none;display:inline-flex;align-items:center;gap:7px;"><i class="ti ti-trophy" style="color:var(--gold);"></i>Performance</a></div>' +
        '<a href="/settings#personal-records">All tracks</a>' +
      '</div>';
    card.innerHTML = perfHeader + UIStates.loadingHTML();

    var prs = [];
    try {
      var r = await fetch('/api/personal-records');
      if (r.ok) prs = await r.json();
    } catch (_) { prs = []; }

    var configuredPrs = prs.filter(function (pr) { return TRACK_CONFIGS[pr.track_key]; });

    if (configuredPrs.length === 0) {
      var emptyLoading = card.querySelector('.ui-loading');
      if (emptyLoading) emptyLoading.remove();
      var emptyEl = document.createElement('div');
      emptyEl.className = 'perf-empty';
      emptyEl.innerHTML =
        'No tracked performances yet — <a href="/settings#personal-records">add your first PR in Settings</a>';
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

    var loadingEl = card.querySelector('.ui-loading');
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

    card.innerHTML = UIStates.loadingHTML();

    var _rwResult = await _homeFetch(
      '/api/home/recent-workouts?user_id=' + encodeURIComponent(userId) + '&limit=4'
    );
    var workouts = _rwResult.ok ? (_rwResult.data.workouts || []) : [];

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
    } catch (_) { /* network error, leave logs empty */ }

    var logsForHabit = {};
    logs.forEach(function (l) {
      if (l.habit_id === habit.id) logsForHabit[l.logged_date] = l;
    });

    var streakNum = 0;
    try {
      var sr = await fetch('/api/habits/stats?habit_id=' + habit.id + '&days=30');
      if (sr.ok) { var sd = await sr.json(); streakNum = sd.streak || 0; }
    } catch (_) { /* network error, streak stays 0 */ }

    var tmp = document.createElement('div');
    tmp.innerHTML = buildHabitRow(habit, weekDates, todayStr, { [habit.id]: logsForHabit }, userId, streakNum);
    var newRow = tmp.firstChild;
    var existingRow = card.querySelector('[data-habit-row="' + habit.id + '"]');
    if (existingRow) existingRow.parentNode.replaceChild(newRow, existingRow);

    var footerBadge = card.querySelector('[data-streak-badge="' + habit.id + '"]');
    if (footerBadge) footerBadge.textContent = habit.name.split(' ')[0] + ' ' + streakNum + 'd';

    attachHabitCellListeners(card, [habit], weekDates, todayStr, userId);
  }

  function showHabitError(card, msg) {
    var existing = card.querySelector('.habit-inline-error');
    if (existing) existing.remove();
    var el = document.createElement('div');
    el.className = 'habit-inline-error';
    el.textContent = msg;
    var footer = card.querySelector('.habits-streak-footer');
    if (footer) footer.insertAdjacentElement('beforebegin', el);
    else card.appendChild(el);
    setTimeout(function () { if (el.parentNode) el.parentNode.removeChild(el); }, 4000);
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

        var wasLogged = !!logId;
        if (wasLogged) {
          cell.classList.remove('done');
          cell.innerHTML = '';
          cell.removeAttribute('data-log-id');
        } else {
          cell.classList.add('done');
          cell.innerHTML = '<i class="ti ti-check"></i>';
        }

        try {
          if (wasLogged) {
            var delRes = await fetch('/api/habits/logs/' + logId, { method: 'DELETE' });
            if (!delRes.ok) throw new Error('delete failed');
          } else {
            var postRes = await fetch('/api/habits/logs', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ habit_id: hid, logged_date: dateStr })
            });
            if (!postRes.ok) throw new Error('post failed');
            var newLog = await postRes.json();
            cell.setAttribute('data-log-id', String(newLog.id));
          }
        } catch (_) {
          if (wasLogged) {
            cell.classList.add('done');
            cell.innerHTML = '<i class="ti ti-check"></i>';
            cell.setAttribute('data-log-id', logId);
          } else {
            cell.classList.remove('done');
            cell.innerHTML = '';
            cell.removeAttribute('data-log-id');
          }
          showHabitError(card, 'Could not save — try again');
          return;
        }

        try {
          var sr = await fetch('/api/habits/stats?habit_id=' + hid + '&days=30');
          if (sr.ok) {
            var sd = await sr.json();
            var badge = card.querySelector('[data-streak-badge="' + hid + '"]');
            if (badge) badge.textContent = habit.name.split(' ')[0] + ' ' + (sd.streak || 0) + 'd';
            var streakCell = card.querySelector('[data-habit-row="' + hid + '"] .streak-col .num');
            if (streakCell) streakCell.textContent = sd.streak || 0;
          }
        } catch (_) { /* network error, badge stays stale */ }
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

    card.innerHTML = header + UIStates.loadingHTML();

    var habits = [];
    try {
      var hr = await fetch('/api/habits');
      if (hr.ok) habits = await hr.json();
    } catch (_) { /* network error, leave habits empty */ }

    if (!habits.length) {
      card.innerHTML = header +
        '<div class="habits-empty">Add a habit to start tracking your week — <a href="/habits">go to Habits</a></div>';
      return;
    }

    var today = bangkokToday();
    var todayStr = bangkokTodayStr();
    var monday = isoWeekMonday(today);
    var weekDates = [];
    for (var i = 0; i < 7; i++) weekDates.push(isoDate(addDays(monday, i)));

    var allLogs = [];
    try {
      var lr2 = await fetch('/api/habits/logs?from=' + weekDates[0] + '&to=' + weekDates[6]);
      if (lr2.ok) allLogs = await lr2.json();
    } catch (_) { /* network error, leave logs empty */ }

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

    var today = bangkokToday();
    var todayStr = bangkokTodayStr();
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
    } catch (_) { /* network error, leave collections empty */ }

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

  function _buildWeightQuickInput(prefillValue) {
    var valAttr = (prefillValue != null) ? ' value="' + prefillValue + '"' : '';
    return '<div class="trend-quick-input">' +
      '<input type="number" class="trend-weight-input" step="0.1" min="20" max="300"' +
        ' placeholder="kg" inputmode="decimal" aria-label="Weight in kg"' + valAttr + '>' +
      '<button type="button" class="trend-quick-save-btn" data-save="weight">Save</button>' +
      '<span class="trend-weight-error" style="display:none;font-size:11px;color:#dc2626;margin-left:6px;"></span>' +
    '</div>';
  }

  function _wireWeightSave(cardEl, userId) {
    var btn = cardEl.querySelector('[data-save="weight"]');
    var inp = cardEl.querySelector('.trend-weight-input');
    var errEl = cardEl.querySelector('.trend-weight-error');
    if (!btn || !inp) return;

    function showWeightErr(msg) {
      if (!errEl) return;
      errEl.textContent = msg;
      errEl.style.display = 'inline';
      setTimeout(function () { errEl.style.display = 'none'; }, 4000);
    }

    btn.addEventListener('click', async function () {
      var raw = inp.value.trim();
      if (errEl) errEl.style.display = 'none';
      if (raw === '' || isNaN(Number(raw))) { showWeightErr('Enter a number'); inp.focus(); return; }
      var val = parseFloat(raw);
      if (val < 20 || val > 300) { showWeightErr('Must be 20–300 kg'); inp.focus(); return; }
      btn.disabled = true;
      try {
        var todayStr = bangkokTodayStr();
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
        } else {
          showWeightErr('Save failed — try again');
        }
      } catch (_) {
        showWeightErr('Network error — try again');
      }
      btn.disabled = false;
    });
  }

  /* ---- Weight widget sparkline (40px height, blue accent) ---- */

  function _weightSparkline(ma30) {
    var W = 200, H = 40, PAD = 3;
    if (!ma30 || !ma30.length) {
      return '<svg class="ww-sparkline" viewBox="0 0 200 40" preserveAspectRatio="none"></svg>';
    }
    var vals = ma30.map(function (d) { return d.value; }).filter(function (v) { return v != null; });
    if (!vals.length) {
      return '<svg class="ww-sparkline" viewBox="0 0 200 40" preserveAspectRatio="none"></svg>';
    }
    var minV = Math.min.apply(null, vals);
    var maxV = Math.max.apply(null, vals);
    if (minV === maxV) { minV -= 0.5; maxV += 0.5; }

    function normY(v) {
      return H - PAD - ((v - minV) / (maxV - minV)) * (H - 2 * PAD);
    }

    var pts = ma30.filter(function (d) { return d.value != null; }).map(function (d, i) {
      var x = ma30.length > 1 ? (i / (ma30.length - 1)) * W : W / 2;
      return { x: x, y: normY(d.value) };
    });

    if (!pts.length) {
      return '<svg class="ww-sparkline" viewBox="0 0 200 40" preserveAspectRatio="none"></svg>';
    }

    var linePath = pts.map(function (p, idx) {
      return (idx === 0 ? 'M' : 'L') + p.x.toFixed(1) + ',' + p.y.toFixed(1);
    }).join(' ');
    var last = pts[pts.length - 1];
    var areaPath = linePath + ' L' + last.x.toFixed(1) + ',' + H + ' L' + pts[0].x.toFixed(1) + ',' + H + ' Z';
    var uid = 'wwg' + Math.random().toString(36).slice(2, 7);

    return '<svg class="ww-sparkline" viewBox="0 0 200 40" preserveAspectRatio="none">' +
      '<defs><linearGradient id="' + uid + '" x1="0" y1="0" x2="0" y2="1">' +
        '<stop offset="0%" stop-color="#2b4ca8" stop-opacity="0.3"/>' +
        '<stop offset="100%" stop-color="#2b4ca8" stop-opacity="0"/>' +
      '</linearGradient></defs>' +
      '<path d="' + areaPath + '" fill="url(#' + uid + ')" stroke="none"/>' +
      '<path d="' + linePath + '" fill="none" stroke="#2b4ca8" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>' +
      '<circle cx="' + last.x.toFixed(1) + '" cy="' + last.y.toFixed(1) + '" r="3" fill="#2b4ca8"/>' +
    '</svg>';
  }

  /* ---- Delta pill color logic (direction-aware) ---- */

  function _weightDeltaPillClass(delta, direction) {
    if (delta == null || Math.abs(delta) < 0.05) return 'ww-pill--flat';
    var isLoss = delta < 0;
    if (direction === 'down') {
      return isLoss ? 'ww-pill--green' : 'ww-pill--red';
    }
    if (direction === 'up') {
      return isLoss ? 'ww-pill--red' : 'ww-pill--green';
    }
    // No target: neutral
    return isLoss ? 'ww-pill--green' : 'ww-pill--red';
  }

  function _weightDeltaPillText(delta) {
    if (delta == null || Math.abs(delta) < 0.05) return '—';
    var sign = delta > 0 ? '+' : '−';
    return sign + Math.abs(delta).toFixed(1) + ' kg';
  }

  function _wwStatusPillClass(statusLabel) {
    if (statusLabel === 'on_track') return 'ww-status--green';
    if (statusLabel === 'behind')   return 'ww-status--amber';
    if (statusLabel === 'ahead')    return 'ww-status--blue';
    return 'ww-status--amber';
  }

  function _wwStatusLabel(statusLabel) {
    if (statusLabel === 'on_track') return 'On track';
    if (statusLabel === 'behind')   return 'Behind';
    if (statusLabel === 'ahead')    return 'Ahead';
    return statusLabel;
  }

  /* ---- Weight widget renderer (wires to /api/home/weight-summary) ---- */

  function renderWeightWidget(el, summary) {
    var iconHTML = '<i class="ti ti-scale" style="font-size:16px;color:var(--blue-text);"></i>';
    var header =
      '<div class="trend-card-header">' +
        iconHTML +
        '<span class="trend-card-title">Weight</span>' +
        '<span class="trend-card-period">30d</span>' +
      '</div>';

    if (!summary || summary.current_weight == null) {
      // Empty state
      el.innerHTML = header +
        '<div class="ww-empty">' +
          'No weight logged yet — log your first weigh-in on the ' +
          '<a href="/weight" style="color:#2b4ca8;text-decoration:none;">Weight page</a>' +
        '</div>';
      el.style.cursor = 'default';
      return;
    }

    var direction = summary.target ? summary.target.direction : null;
    var weekPillCls = _weightDeltaPillClass(summary.delta_week, direction);
    var monthPillCls = _weightDeltaPillClass(summary.delta_month, direction);

    var targetBlock = '';
    if (summary.target) {
      var pct = Math.max(0, Math.min(100, summary.target.progress_pct || 0));
      var statusCls = _wwStatusPillClass(summary.target.status_label);
      var statusTxt = _wwStatusLabel(summary.target.status_label);
      targetBlock =
        '<div class="ww-progress-row">' +
          '<div class="ww-progress-bar"><div class="ww-progress-fill" style="width:' + pct.toFixed(1) + '%"></div></div>' +
          '<span class="ww-status-pill ' + statusCls + '">' + statusTxt + '</span>' +
        '</div>';
    } else {
      targetBlock =
        '<div class="ww-set-target">' +
          '<a href="/weight/targets" style="color:#2b4ca8;text-decoration:none;font-size:12px;">' +
            'Set a target →' +
          '</a>' +
        '</div>';
    }

    el.innerHTML = header +
      '<div class="ww-stat">' +
        '<span class="ww-current">' + summary.current_weight.toFixed(1) + '</span>' +
        '<span class="ww-unit">kg</span>' +
      '</div>' +
      '<div class="ww-avg">' + (summary.avg_7d != null ? summary.avg_7d.toFixed(1) + ' kg avg' : '—') + '</div>' +
      '<div class="ww-pills">' +
        '<span class="ww-pill ' + weekPillCls + '">' + _weightDeltaPillText(summary.delta_week) + ' wk</span>' +
        '<span class="ww-pill ' + monthPillCls + '">' + _weightDeltaPillText(summary.delta_month) + ' mo</span>' +
      '</div>' +
      _weightSparkline(summary.ma30) +
      targetBlock;

    el.style.cursor = 'pointer';
  }

  async function loadWeightWidget(el) {
    var iconHTML = '<i class="ti ti-scale" style="font-size:16px;color:var(--blue-text);"></i>';
    var header =
      '<div class="trend-card-header">' +
        iconHTML +
        '<span class="trend-card-title">Weight</span>' +
        '<span class="trend-card-period">30d</span>' +
      '</div>';

    // Skeleton loading state
    el.innerHTML = header +
      '<div style="display:flex;flex-direction:column;gap:8px;margin-top:4px;">' +
        '<div class="trend-skeleton-line" style="height:28px;width:55%"></div>' +
        '<div class="trend-skeleton-line" style="height:12px;width:40%"></div>' +
        '<div class="trend-skeleton-line" style="height:12px;width:70%"></div>' +
        '<div class="trend-skeleton-line" style="height:40px"></div>' +
      '</div>';

    var _wwResult = await _homeFetch('/api/home/weight-summary');
    if (!_wwResult.ok) {
      el.innerHTML = header +
        '<div class="ww-error">' +
          'Could not load weight data' +
          '<button type="button" class="ww-retry-btn" style="margin-left:10px;padding:3px 10px;font-size:11px;font-family:inherit;border:1px solid var(--card-border);border-radius:6px;background:var(--chip-bg);cursor:pointer;">Retry</button>' +
        '</div>';
      var retryBtn = el.querySelector('.ww-retry-btn');
      if (retryBtn) {
        retryBtn.addEventListener('click', function () { loadWeightWidget(el); });
      }
      return;
    }
    var summary = _wwResult.data;

    renderWeightWidget(el, summary);

    // Click navigates to /weight (but not if clicking the "Set a target" or "Weight page" links)
    el.addEventListener('click', function (e) {
      if (e.target.tagName === 'A' || e.target.closest('a')) return;
      window.location.href = '/weight';
    });
  }

  function renderWeightTrendCard(el, weightEntries, userId) {
    var iconHTML = '<i class="ti ti-scale" style="font-size:16px;color:var(--blue-text);"></i>';

    if (!weightEntries || !weightEntries.length) {
      var quickInput = _buildWeightQuickInput(null);
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

    var quickInput = _buildWeightQuickInput(latest.weight_kg.toFixed(1));
    el.innerHTML = _trendCardInnerHTML(iconHTML, 'Weight', '30d',
      latest.weight_kg.toFixed(1), 'kg', pillHTML,
      _trendAreaSpark(sparkVals, '#2b4ca8', '#2b4ca8', null),
      '30d trend',
      '<a href="/weight" style="color:#2b4ca8;text-decoration:none;font-size:11px;">View all →</a>',
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

    var results = await Promise.allSettled([
      fetch('/trends/summary?range=30d'),
    ]);

    var tResult = results[0];
    if (tResult.status === 'fulfilled' && tResult.value.ok) {
      try { summary = await tResult.value.json(); } catch (_) { summaryFailed = true; }
    } else {
      summaryFailed = true;
    }

    var passedSummary = summaryFailed ? null : summary;
    renderHRVTrendCard(document.getElementById('trend-card-hrv'), passedSummary);
    renderWeeklyTSSTrendCard(document.getElementById('trend-card-tss'), passedSummary);
    renderRHRTrendCard(document.getElementById('trend-card-rhr'), passedSummary);
    // Weight widget is fired separately from init() as part of the parallel home fetches
  }

  /* ---- Weekly Summary card ---- */

  var _WKS_TYPE_ICONS = {
    run:  { icon: 'ti-run',     label: 'Run' },
    lift: { icon: 'ti-barbell', label: 'Lift' },
    wod:  { icon: 'ti-flame',   label: 'WOD' },
    bike: { icon: 'ti-bike',    label: 'Bike' },
  };

  function _wksDeltaPill(value, unit) {
    var num = Number(value);
    var cls = num > 0 ? 'wks-pill--green' : (num < 0 ? 'wks-pill--red' : 'wks-pill--flat');
    var sign = num > 0 ? '+' : '';
    return '<span class="wks-pill ' + cls + '">' + sign + value + ' ' + unit + '</span>';
  }

  function _wksTssBarChart(dailyLoad) {
    var W = 280, H = 90, LABEL_H = 16, GAP = 4;
    var chartH = H - LABEL_H;
    var n = dailyLoad.length;
    var barW = Math.max(8, Math.floor((W - GAP * (n - 1)) / n));
    var step = barW + GAP;
    var startX = (W - (barW * n + GAP * (n - 1))) / 2;
    var today = bangkokTodayStr();

    var maxTss = 1;
    dailyLoad.forEach(function (d) { if (d.tss && d.tss > maxTss) maxTss = d.tss; });

    var DAY_LABELS = ['M', 'T', 'W', 'T', 'F', 'S', 'S'];
    var out = '<svg class="wks-bar-chart" viewBox="0 0 ' + W + ' ' + H + '" xmlns="http://www.w3.org/2000/svg">';

    dailyLoad.forEach(function (d, i) {
      var x = startX + i * step;
      var isToday = d.date === today;
      var isRest = d.is_rest;

      var barColor = isToday ? 'var(--accent)' : (isRest ? 'var(--chip-bg)' : '#5a8dee');
      var tssVal = d.tss || 0;
      var barH = isRest ? 4 : Math.max(4, (tssVal / maxTss) * (chartH - 8));
      var y = chartH - barH;

      out += '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + barW + '" height="' + barH.toFixed(1) + '" rx="3" fill="' + barColor + '"/>';
      out += '<text x="' + (x + barW / 2).toFixed(1) + '" y="' + (H - 2) + '" text-anchor="middle" font-size="10" fill="#8b95ad" font-family="Inter Tight, sans-serif">' + DAY_LABELS[i] + '</text>';
    });

    out += '</svg>';
    return out;
  }

  async function loadWeeklySummaryCard(userId) {
    var row5 = document.getElementById('row-5');
    if (!row5) return;

    var card = document.getElementById('weekly-summary-card');
    if (!card) {
      card = document.createElement('div');
      card.id = 'weekly-summary-card';
      card.className = 'card wks-card';
      row5.appendChild(card);
    }

    var header = '<div class="card-head"><div class="ttl"><i class="ti ti-calendar-week"></i>This week</div></div>';
    card.innerHTML = header + UIStates.loadingHTML();

    var result = await _homeFetch('/api/home/weekly-summary?user_id=' + encodeURIComponent(userId));
    if (!result.ok) {
      card.innerHTML = header + UIStates.errorHTML('Could not load weekly summary');
      return;
    }

    var data = result.data;
    var total = data.workouts.total;

    if (total === 0) {
      card.innerHTML = header +
        UIStates.emptyHTML('No workouts this week', '<a href="/log">Log a workout →</a>');
      return;
    }

    // Type breakdown icons
    var typeHTML = '';
    Object.keys(_WKS_TYPE_ICONS).forEach(function (t) {
      var n = data.workouts.by_type[t] || 0;
      if (n > 0) {
        var ic = _WKS_TYPE_ICONS[t];
        typeHTML += '<span class="wks-type"><i class="ti ' + ic.icon + '"></i>' + n + '</span>';
      }
    });
    if (!typeHTML) typeHTML = '<span class="wks-type-none">—</span>';

    // Totals
    var durStr = '—';
    if (data.duration_minutes != null) {
      var h = Math.floor(data.duration_minutes / 60);
      var m = Math.round(data.duration_minutes % 60);
      durStr = h > 0 ? h + 'h ' + m + 'm' : m + 'm';
    }
    var distStr = data.distance_km != null ? data.distance_km.toFixed(1) + ' km' : null;
    var tssStr  = data.total_tss   != null ? Math.round(data.total_tss) + ' TSS' : null;

    // Delta pills (vs previous week)
    var vp = data.vs_prev_week;
    var deltaHTML =
      _wksDeltaPill(vp.total_delta, 'wk') +
      _wksDeltaPill(Number(vp.distance_km_delta).toFixed(1), 'km') +
      _wksDeltaPill(Math.round(vp.tss_delta), 'TSS');

    card.innerHTML = header +
      '<div class="wks-body">' +
        '<div class="wks-stats">' +
          '<div class="wks-count-row">' +
            '<span class="wks-count">' + total + '</span>' +
            '<span class="wks-count-lbl">workouts</span>' +
            '<span class="wks-rest">' + data.rest_days + ' rest days</span>' +
          '</div>' +
          '<div class="wks-types">' + typeHTML + '</div>' +
          '<div class="wks-totals">' +
            (distStr ? '<span class="wks-total-item"><span class="wks-v">' + distStr + '</span></span>' : '') +
            '<span class="wks-total-item"><span class="wks-v">' + durStr + '</span></span>' +
            (tssStr  ? '<span class="wks-total-item"><span class="wks-v">' + tssStr + '</span></span>' : '') +
          '</div>' +
          '<div class="wks-deltas">' + deltaHTML + '</div>' +
        '</div>' +
        '<div class="wks-chart">' + _wksTssBarChart(data.daily_load) + '</div>' +
      '</div>';
  }

  /* ---- Log Today card ---- */

  function renderLogTodayCard(card, existing, userId, selectedDate, todayStr) {
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

    var isOnToday = selectedDate === todayStr;
    card.innerHTML =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-pencil-plus"></i>Log Today</div>' +
        '<div class="lt-date-nav">' +
          '<button class="lt-nav-btn" id="lt-prev-btn" type="button" aria-label="Previous day">&#8249;</button>' +
          '<input type="date" id="lt-date-picker" class="lt-date-input"' +
            ' value="' + selectedDate + '" max="' + todayStr + '">' +
          '<button class="lt-today-btn' + (isOnToday ? ' lt-today-btn--active' : '') + '"' +
            ' id="lt-today-btn" type="button"' + (isOnToday ? ' disabled' : '') + '>Today</button>' +
          '<button class="lt-nav-btn" id="lt-next-btn" type="button" aria-label="Next day"' +
            (isOnToday ? ' disabled' : '') + '>&#8250;</button>' +
        '</div>' +
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

    var initialValues = {
      sleep_hours:   v.sleep_hours   != null ? String(v.sleep_hours)   : '',
      sleep_quality: v.sleep_quality != null ? String(v.sleep_quality) : '',
      energy:        v.energy        != null ? String(v.energy)        : '',
      mood:          v.mood          != null ? String(v.mood)          : '',
      resting_hr:    v.resting_hr    != null ? String(v.resting_hr)    : '',
      hrv:           v.hrv           != null ? String(v.hrv)           : ''
    };

    async function navigateDateTo(newDate) {
      if (!newDate || newDate > todayStr || newDate === selectedDate) return;
      var newExisting = null;
      try {
        var r = await fetch('/api/daily-metrics/' + encodeURIComponent(userId) + '/' + newDate);
        if (r.ok) newExisting = await r.json();
      } catch (_) { /* network error, render with no existing data */ }
      renderLogTodayCard(card, newExisting, userId, newDate, todayStr);
    }

    var datePicker = card.querySelector('#lt-date-picker');
    datePicker.addEventListener('change', function () { navigateDateTo(this.value); });

    var prevBtn = card.querySelector('#lt-prev-btn');
    if (prevBtn) prevBtn.addEventListener('click', function () { navigateDateTo(addISODays(selectedDate, -1)); });

    var nextBtn = card.querySelector('#lt-next-btn');
    if (nextBtn) nextBtn.addEventListener('click', function () { navigateDateTo(addISODays(selectedDate, 1)); });

    var todayNavBtn = card.querySelector('#lt-today-btn');
    if (todayNavBtn) todayNavBtn.addEventListener('click', function () { navigateDateTo(todayStr); });


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
        var res = await fetch('/api/daily-metrics/' + encodeURIComponent(userId) + '/' + selectedDate, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        if (res.ok) {
          UIStates.showToast('Saved');
          feedback.className = 'lt-feedback lt-feedback--ok';
          feedback.textContent = 'Saved';
          setTimeout(function () { feedback.textContent = ''; }, 3000);
          initialValues = { sleep_hours: shStr, sleep_quality: sqStr, energy: enStr, mood: moStr, resting_hr: rhrStr, hrv: hrvStr };
          if (selectedDate === todayStr) {
            loadSleepCard(userId);
            loadReadinessCard(userId);
            loadRow3(userId);
          }
        } else {
          var errData = null;
          try { errData = await res.json(); } catch (_) { /* non-JSON response body is fine */ }
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

  /* ---- Fast-log form (issue #394: mobile-optimised daily metrics) ---- */

  var _fastLogUserId = null;
  var _autoSaveTimer = null;

  var _FM_STEPPERS = [
    { inputId: 'fm-rhr',    minusId: 'fm-rhr-minus',    plusId: 'fm-rhr-plus',    min: 30,  max: 120, step: 1   },
    { inputId: 'fm-hrv',    minusId: 'fm-hrv-minus',    plusId: 'fm-hrv-plus',    min: 0,   max: 200, step: 1   },
    { inputId: 'fm-sleep',  minusId: 'fm-sleep-minus',  plusId: 'fm-sleep-plus',  min: 0,   max: 12,  step: 0.5 },
    { inputId: 'fm-weight', minusId: 'fm-weight-minus', plusId: 'fm-weight-plus', min: 30,  max: 200, step: 1   },
  ];

  function _fmBuildPayload() {
    var rhr    = document.getElementById('fm-rhr')   ? document.getElementById('fm-rhr').value.trim()   : '';
    var hrv    = document.getElementById('fm-hrv')   ? document.getElementById('fm-hrv').value.trim()   : '';
    var sleep  = document.getElementById('fm-sleep') ? document.getElementById('fm-sleep').value.trim() : '';
    var energy = document.getElementById('fm-energy-val') ? document.getElementById('fm-energy-val').value : '';
    var mood   = document.getElementById('fm-mood-val')   ? document.getElementById('fm-mood-val').value   : '';
    var notes  = document.getElementById('fm-notes') ? document.getElementById('fm-notes').value.trim()  : '';

    var payload = {};
    if (rhr    !== '') payload.resting_hr  = parseInt(rhr, 10);
    if (hrv    !== '') payload.hrv         = parseInt(hrv, 10);
    if (sleep  !== '') payload.sleep_hours = parseFloat(sleep);
    if (energy !== '') payload.energy      = parseInt(energy, 10);
    if (mood   !== '') payload.mood        = parseInt(mood, 10);
    if (notes  !== '') payload.notes       = notes;
    return payload;
  }

  async function _fmDoSave(userId, todayStr, silent) {
    var btn      = document.getElementById('fm-save');
    var feedback = document.getElementById('fm-feedback');
    var payload  = _fmBuildPayload();

    if (!silent && btn) { btn.disabled = true; btn.textContent = 'Saving…'; }
    if (feedback)       { feedback.className = 'fm-feedback'; feedback.textContent = ''; }

    try {
      var res = await fetch('/api/daily-metrics/' + encodeURIComponent(userId) + '/' + todayStr, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload)
      });
      if (res.ok) {
        var banner = document.getElementById('log-today-banner');
        if (banner) banner.style.display = 'none';
        if (window.UIStates) UIStates.showToast('Saved');
        if (feedback) {
          feedback.className = 'fm-feedback';
          feedback.textContent = 'Saved';
          setTimeout(function () { if (feedback) feedback.textContent = ''; }, 2000);
        }
        if (todayStr === bangkokTodayStr()) {
          loadSleepCard(userId);
          loadReadinessCard(userId);
          loadRow3(userId);
        }
      } else {
        var errData = null;
        try { errData = await res.json(); } catch (_) { /* non-JSON response body is fine */ }
        if (feedback) {
          feedback.className = 'fm-feedback fm-feedback--err';
          feedback.textContent = (errData && errData.detail)
            ? (typeof errData.detail === 'string' ? errData.detail : JSON.stringify(errData.detail))
            : 'Save failed (' + res.status + ')';
        }
      }
    } catch (_) {
      if (feedback) {
        feedback.className = 'fm-feedback fm-feedback--err';
        feedback.textContent = 'Network error — try again';
      }
    }

    if (!silent && btn) { btn.disabled = false; btn.textContent = 'Save'; }
  }

  function _fmScheduleAutoSave(userId, todayStr) {
    clearTimeout(_autoSaveTimer);
    _autoSaveTimer = setTimeout(function () {
      _fmDoSave(userId, todayStr, true);
    }, 800);
  }

  function _fmSelectPill(groupEl, val) {
    groupEl.querySelectorAll('.fm-pill').forEach(function (pill) {
      pill.classList.toggle('active', pill.dataset.val === String(val));
    });
  }

  function _fmInitPills(groupId, hiddenId, userId, todayStr) {
    var group  = document.getElementById(groupId);
    var hidden = document.getElementById(hiddenId);
    if (!group || !hidden) return;
    group.querySelectorAll('.fm-pill').forEach(function (pill) {
      pill.addEventListener('click', function () {
        hidden.value = pill.dataset.val;
        _fmSelectPill(group, pill.dataset.val);
        _fmScheduleAutoSave(userId, todayStr);
      });
    });
  }

  function _fmInitStepper(cfg, userId, todayStr) {
    var input    = document.getElementById(cfg.inputId);
    var minusBtn = document.getElementById(cfg.minusId);
    var plusBtn  = document.getElementById(cfg.plusId);
    if (!input || !minusBtn || !plusBtn) return;

    function _step(delta) {
      var cur  = input.value === '' ? NaN : parseFloat(input.value);
      var next;
      if (isNaN(cur)) {
        next = delta > 0 ? cfg.min : cfg.max;
      } else {
        next = Math.min(cfg.max, Math.max(cfg.min, cur + delta));
        next = Math.round(next / cfg.step) * cfg.step;
        next = parseFloat(next.toFixed(2));
      }
      input.value = next;
      _fmScheduleAutoSave(userId, todayStr);
    }

    minusBtn.addEventListener('click', function () { _step(-cfg.step); });
    plusBtn.addEventListener('click',  function () { _step( cfg.step); });
    input.addEventListener('blur', function () { _fmScheduleAutoSave(userId, todayStr); });
  }

  function _fmPrefill(existing) {
    if (!existing) return;
    if (existing.resting_hr  != null) { var el = document.getElementById('fm-rhr');   if (el) el.value = existing.resting_hr; }
    if (existing.hrv         != null) { var el = document.getElementById('fm-hrv');   if (el) el.value = existing.hrv; }
    if (existing.sleep_hours != null) { var el = document.getElementById('fm-sleep'); if (el) el.value = existing.sleep_hours; }
    if (existing.energy != null) {
      var hidden = document.getElementById('fm-energy-val'); if (hidden) hidden.value = existing.energy;
      var group  = document.getElementById('fm-energy-pills'); if (group) _fmSelectPill(group, existing.energy);
    }
    if (existing.mood != null) {
      var hidden = document.getElementById('fm-mood-val'); if (hidden) hidden.value = existing.mood;
      var group  = document.getElementById('fm-mood-pills'); if (group) _fmSelectPill(group, existing.mood);
    }
    if (existing.notes) { var el = document.getElementById('fm-notes'); if (el) el.value = existing.notes; }
  }

  async function initFastLogForm(userId) {
    _fastLogUserId = userId;
    var todayStr = bangkokTodayStr();

    var label = document.getElementById('fast-log-date-label');
    if (label) label.textContent = todayStr;

    var existing = null;
    try {
      var r = await fetch('/api/daily-metrics/' + encodeURIComponent(userId) + '/' + todayStr);
      if (r.ok) existing = await r.json();
    } catch (_) { /* network error, prefill with empty state */ }
    _fmPrefill(existing);

    _FM_STEPPERS.forEach(function (cfg) { _fmInitStepper(cfg, userId, todayStr); });
    _fmInitPills('fm-energy-pills', 'fm-energy-val', userId, todayStr);
    _fmInitPills('fm-mood-pills',   'fm-mood-val',   userId, todayStr);

    var notesEl = document.getElementById('fm-notes');
    if (notesEl) notesEl.addEventListener('blur', function () { _fmScheduleAutoSave(userId, todayStr); });

    var form = document.getElementById('fast-log-form');
    if (form) {
      form.addEventListener('submit', function (e) {
        e.preventDefault();
        clearTimeout(_autoSaveTimer);
        _fmDoSave(userId, todayStr, false);
      });
    }
  }

  /* ---- Log today banner (issue #394) ---- */

  async function loadLogTodayBanner(userId) {
    var banner = document.getElementById('log-today-banner');
    if (!banner) return;
    var todayStr = bangkokTodayStr();
    var hasRow = false;
    try {
      var r = await fetch('/api/daily-metrics/' + encodeURIComponent(userId) + '/' + todayStr);
      hasRow = r.ok;
    } catch (_) { /* network error, hasRow stays false */ }
    banner.style.display = hasRow ? 'none' : 'block';

    var ctaBtn = document.getElementById('log-today-cta-btn');
    if (ctaBtn) {
      ctaBtn.addEventListener('click', function () {
        var section = document.getElementById('fast-log-section');
        if (section) {
          section.scrollIntoView({ behavior: 'smooth', block: 'start' });
          var firstInput = section.querySelector('.fm-input, .fm-textarea');
          if (firstInput) setTimeout(function () { firstInput.focus(); }, 400);
        }
        banner.style.display = 'none';
      });
    }
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

    var todayStr = bangkokTodayStr();
    var existing = null;
    try {
      var res = await fetch('/api/daily-metrics/' + encodeURIComponent(userId) + '/' + todayStr);
      if (res.ok) existing = await res.json();
    } catch (_) { /* network error, render with no existing data */ }

    renderLogTodayCard(card, existing, userId, todayStr, todayStr);
  }

  /* ---- Threshold banner ---- */

  var _THRESHOLD_BANNER_CSS = [
    '#threshold-banner{display:flex;align-items:center;gap:8px;padding:9px 24px;',
      "background:#fffbeb;border-bottom:1px solid #fcd34d;font-size:13px;font-weight:500;",
      "font-family:'Inter Tight',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;}",
    '#threshold-banner .tbanner-msg{flex:1;}',
    '#threshold-banner a{color:#b45309;font-weight:600;text-decoration:underline;}',
    '#threshold-banner .tbanner-dismiss{margin-left:auto;background:none;border:none;',
      'cursor:pointer;font-size:16px;color:#92400e;padding:0 4px;line-height:1;flex-shrink:0;}',
    '#threshold-banner .tbanner-dismiss:hover{color:#78350f;}',
    '@media(max-width:880px){#threshold-banner{padding:9px 14px;}}'
  ].join('');

  function _showThresholdBanner() {
    if (document.getElementById('threshold-banner')) return;
    if (!document.getElementById('threshold-banner-styles')) {
      var style = document.createElement('style');
      style.id = 'threshold-banner-styles';
      style.textContent = _THRESHOLD_BANNER_CSS;
      document.head.appendChild(style);
    }
    var banner = document.createElement('div');
    banner.id = 'threshold-banner';
    banner.setAttribute('role', 'alert');
    banner.innerHTML =
      '<span class="tbanner-msg">Tip: set your FTP and threshold values in ' +
        '<a href="/settings#thresholds">Settings</a> for accurate training load</span>' +
      '<button class="tbanner-dismiss" type="button" aria-label="Dismiss">&#x2715;</button>';
    var syncBar = document.getElementById('sync-status-bar');
    var nav = document.querySelector('.global-nav');
    var ref = syncBar || nav;
    if (ref && ref.parentNode) {
      ref.parentNode.insertBefore(banner, ref.nextSibling);
    } else {
      document.body.insertBefore(banner, document.body.firstChild);
    }
    banner.querySelector('.tbanner-dismiss').addEventListener('click', function () {
      sessionStorage.setItem('threshold-banner-dismissed', '1');
      banner.remove();
    });
  }

  async function _checkThresholdBanner() {
    if (sessionStorage.getItem('threshold-banner-dismissed')) return;
    try {
      var r = await fetch('/api/user-preferences');
      if (!r.ok) return;
      var data = await r.json();
      var row = data.row;
      var needsBanner = !row
        || row.ftp_w == null
        || row.threshold_hr == null
        || row.threshold_pace_seconds_per_km == null;
      if (needsBanner) _showThresholdBanner();
    } catch (_) { /* network error, skip banner check */ }
  }

  /* ---- Strava stale sync banner ---- */

  function _showStravaStaleBanner(hoursAgo) {
    var container = document.getElementById('strava-stale-banner');
    if (!container) return;
    var h = Math.round(hoursAgo);
    container.innerHTML =
      '<div class="strava-stale-banner" id="strava-stale-banner-inner">' +
        '<span class="strava-stale-msg">Last Strava sync was ' + h + ' hours ago — ' +
          '<a href="#" id="strava-stale-refresh">refresh?</a>' +
        '</span>' +
      '</div>';
    var link = document.getElementById('strava-stale-refresh');
    if (link) {
      link.addEventListener('click', function (e) {
        e.preventDefault();
        link.textContent = 'Syncing…';
        link.style.pointerEvents = 'none';
        fetch('/api/strava/sync', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
          .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
          .then(function () {
            container.innerHTML = '<div class="strava-stale-banner strava-stale-banner--syncing">Sync started…</div>';
          })
          .catch(function () { container.innerHTML = ''; });
      });
    }
  }

  async function _checkStravaStaleBanner() {
    try {
      var statusRes = await fetch('/api/strava/status');
      if (!statusRes.ok) return;
      var status = await statusRes.json();
      if (!status.connected) return;
      var latestRes = await fetch('/api/sync/strava/latest');
      if (!latestRes.ok) return;
      var latest = await latestRes.json();
      if (!latest.synced_at) return;
      var diffMs = Date.now() - new Date(latest.synced_at).getTime();
      var hoursAgo = diffMs / 3600000;
      if (hoursAgo > 24) {
        _showStravaStaleBanner(hoursAgo);
      }
    } catch (_) { /* network error, skip stale banner check */ }
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
      _checkThresholdBanner();
      _checkStravaStaleBanner();

      // Set up row-3 containers synchronously (weight widget fired below)
      loadRow3(userId);

      // Fire all 5 /api/home/* widget fetches simultaneously
      var weightEl = document.getElementById('trend-card-weight');
      Promise.all([
        loadReadinessCard(userId),
        loadPerformanceCard(userId),
        loadRecentWorkoutsCard(userId),
        loadWeeklySummaryCard(userId),
        loadWeightWidget(weightEl),
      ]);

      loadSleepCard(userId);
      loadLogTodayCard(userId);
      initFastLogForm(userId);
      loadLogTodayBanner(userId);
      loadHabitsCard(userId);
      loadHabitsStatsCard(userId);
    }
  }

  function wireLogWorkoutButtons() {
    function openForm() { if (window.WorkoutForm) WorkoutForm.open(); }
    var homeBtn = document.getElementById('home-log-workout-btn');
    var stickyBtn = document.getElementById('sticky-log-workout-btn');
    if (homeBtn) homeBtn.addEventListener('click', openForm);
    if (stickyBtn) stickyBtn.addEventListener('click', openForm);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(); wireLogWorkoutButtons(); });
  } else {
    init();
    wireLogWorkoutButtons();
  }
})();
