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
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
