(function () {
  'use strict';

  /* ── Compact Readiness Tile ─────────────────────────────────────────────── */

  var _RD_TILE_FACTOR_META = {
    sleep_hours: {
      name: 'Sleep',
      fmt: function (v) { return v != null ? Number(v).toFixed(1) + 'h' : '—'; },
    },
    hrv: {
      name: 'HRV',
      fmt: function (v) { return v != null ? Math.round(v) + ' ms' : '—'; },
    },
    rhr: {
      name: 'RHR',
      fmt: function (v) { return v != null ? Math.round(v) + ' bpm' : '—'; },
    },
    mood: {
      name: 'Mood',
      fmt: function (v) { return v != null ? v + '/5' : '—'; },
    },
    energy: {
      name: 'Energy',
      fmt: function (v) { return v != null ? v + '/5' : '—'; },
    },
  };

  /* Returns the stroke/fill color for a given readiness score band. */
  function _rdRingColor(score) {
    if (score >= 70) return '#16a34a';   /* readiness-high */
    if (score >= 40) return '#d97706';   /* readiness-mid */
    return '#dc2626';                     /* readiness-low */
  }

  /* Builds a compact SVG score ring (60×60). */
  function _rdRingSVG(score, color) {
    var radius = 24;
    var cx = 30, cy = 30;
    var circ = 2 * Math.PI * radius;
    var dash = Math.max(0, Math.min(circ, (score / 100) * circ));
    return (
      '<svg class="rd-tile-ring" width="60" height="60" viewBox="0 0 60 60" aria-hidden="true">' +
        '<circle cx="' + cx + '" cy="' + cy + '" r="' + radius + '"' +
          ' fill="none" stroke="rgba(0,0,0,0.08)" stroke-width="5"/>' +
        '<circle cx="' + cx + '" cy="' + cy + '" r="' + radius + '"' +
          ' fill="none" stroke="' + color + '" stroke-width="5"' +
          ' stroke-dasharray="' + dash.toFixed(1) + ' ' + circ.toFixed(1) + '"' +
          ' stroke-linecap="round"' +
          ' transform="rotate(-90 ' + cx + ' ' + cy + ')"/>' +
        '<text x="' + cx + '" y="' + (cy + 5) + '" text-anchor="middle"' +
          ' font-size="13" font-weight="700" fill="' + color + '"' +
          ' font-family="\'JetBrains Mono\',monospace">' + score + '</text>' +
      '</svg>'
    );
  }

  function renderReadinessTile(el, readiness) {
    if (!el) return;

    var header =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-heart-rate-monitor"></i>Readiness · today</div>' +
        '<a href="/calendar">Log metrics &#8594;</a>' +
      '</div>';

    /* Null block — render minimal fallback without errors */
    if (!readiness) {
      el.innerHTML = header +
        '<div class="rd-tile-empty">' +
          '<p class="rd-tile-msg">No readiness data available.</p>' +
        '</div>';
      return;
    }

    /* logged === false → empty state */
    if (!readiness.logged) {
      el.innerHTML = header +
        '<div class="rd-tile-empty">' +
          '<i class="ti ti-moon-stars rd-tile-icon"></i>' +
          '<p class="rd-tile-msg">No metrics logged yet today — log to see your readiness score</p>' +
          '<a href="/calendar" class="rd-tile-cta-btn">' +
            '<i class="ti ti-pencil-plus"></i> Log today\'s metrics' +
          '</a>' +
        '</div>';
      return;
    }

    /* logged === true → score ring + top 3 factors */
    var score = readiness.score || 0;
    var label = readiness.label || '';
    var color = _rdRingColor(score);
    var top_factors = readiness.top_factors || [];

    var factorsHTML = top_factors.slice(0, 3).map(function (f) {
      var meta = _RD_TILE_FACTOR_META[f.factor] ||
        { name: f.factor, fmt: function (v) { return String(v != null ? v : '—'); } };
      var valStr = meta.fmt(f.value);
      var arrow = f.impact === 'positive' ? '↑' : (f.impact === 'negative' ? '↓' : '→');
      var arrowCls = f.impact === 'positive' ? 'rd-arrow--positive' :
        (f.impact === 'negative' ? 'rd-arrow--negative' : 'rd-arrow--neutral');
      return '<div class="rd-tile-factor">' +
        '<span class="rd-tile-factor-name">' + meta.name + '</span>' +
        '<span class="rd-arrow ' + arrowCls + '">' + arrow + '</span>' +
        '<span class="rd-tile-factor-val">' + valStr + '</span>' +
      '</div>';
    }).join('');

    el.innerHTML = header +
      '<div class="rd-tile-body">' +
        '<div class="rd-tile-ring-wrap">' +
          _rdRingSVG(score, color) +
          '<div class="rd-tile-score-label" style="color:' + color + ';">' + label + '</div>' +
        '</div>' +
        '<div class="rd-tile-factors">' + factorsHTML + '</div>' +
      '</div>';
  }

  /* ── Training Card ──────────────────────────────────────────────────────── */

  var _TRAINING_DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  function _bangkokTodayStr() {
    return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' });
  }

  function _deltaCls(n) {
    if (n == null) return 'tw-delta--flat';
    return n > 0 ? 'tw-delta--green' : (n < 0 ? 'tw-delta--red' : 'tw-delta--flat');
  }

  function _deltaText(n, unit) {
    if (n == null) return '—';
    var sign = n > 0 ? '+' : '';
    return sign + n + (unit ? ' ' + unit : '');
  }

  function _twBarChart(dailyLoad) {
    var today = _bangkokTodayStr();
    var maxTss = 1;
    dailyLoad.forEach(function (d) {
      if (d.tss && d.tss > maxTss) maxTss = d.tss;
    });

    return '<div class="tw-bar-chart" aria-label="Daily training load Mon–Sun">' +
      dailyLoad.map(function (d, i) {
        var isToday = d.date === today;
        var isRest = d.is_rest;
        var pct = isRest ? 6 : (d.tss ? Math.max(8, Math.round((d.tss / maxTss) * 100)) : 6);
        var barCls = 'tw-bar' +
          (isToday ? ' tw-bar--today' : '') +
          (isRest  ? ' tw-bar--rest'  : '');
        return '<div class="tw-bar-col">' +
          '<div class="tw-bar-wrap">' +
            '<div class="' + barCls + '" style="height:' + pct + '%;' + (isToday ? 'background:var(--accent);' : '') + '" ' +
              'aria-label="' + _TRAINING_DAY_LABELS[i] + (isRest ? ' rest' : '') + '"></div>' +
          '</div>' +
          '<div class="tw-bar-lbl">' + _TRAINING_DAY_LABELS[i].charAt(0) + '</div>' +
        '</div>';
      }).join('') +
    '</div>';
  }

  function renderTrainingCard(el, training_week) {
    if (!el) return;

    var header =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-barbell"></i>This Week\'s Training</div>' +
        '<a href="/log">Training log &#8594;</a>' +
      '</div>';

    if (!training_week) {
      el.innerHTML = header +
        '<div class="tw-empty">No training data available.</div>';
      return;
    }

    var tw = training_week;
    var vl = tw.vs_last_week || {};

    var wkDelta = vl.workouts_count != null ? vl.workouts_count : null;
    var distDelta = vl.distance_km != null ? vl.distance_km : null;
    var z2Delta = vl.zone2_minutes != null ? vl.zone2_minutes : null;

    var distStr = tw.distance_km != null ? tw.distance_km.toFixed(1) : '—';
    var z2Str   = tw.zone2_minutes != null ? tw.zone2_minutes : '—';

    var statsHTML =
      '<div class="tw-stats">' +
        '<div class="tw-stat">' +
          '<div class="tw-stat-val">' + (tw.workouts_count != null ? tw.workouts_count : '—') + '</div>' +
          '<div class="tw-stat-lbl">Workouts</div>' +
          '<div class="tw-delta ' + _deltaCls(wkDelta) + '">' +
            (wkDelta != null ? (wkDelta > 0 ? '+' : '') + wkDelta + ' wk' : '—') +
          '</div>' +
        '</div>' +
        '<div class="tw-stat">' +
          '<div class="tw-stat-val">' + distStr + '</div>' +
          '<div class="tw-stat-lbl">Distance <span class="tw-unit">km</span></div>' +
          '<div class="tw-delta ' + _deltaCls(distDelta) + '">' + _deltaText(distDelta != null ? Number(distDelta.toFixed(1)) : null) + '</div>' +
        '</div>' +
        '<div class="tw-stat">' +
          '<div class="tw-stat-val">' + z2Str + '</div>' +
          '<div class="tw-stat-lbl">Zone 2 <span class="tw-unit">min</span></div>' +
          '<div class="tw-delta ' + _deltaCls(z2Delta) + '">' + _deltaText(z2Delta) + '</div>' +
        '</div>' +
      '</div>';

    var chartHTML = '';
    if (Array.isArray(tw.daily_load) && tw.daily_load.length === 7) {
      chartHTML = _twBarChart(tw.daily_load);
    }

    el.innerHTML = header + statsHTML + chartHTML;
  }

  /* ── Sleep Card ─────────────────────────────────────────────────────────── */

  function _fmtSleepHours(hours) {
    var h = Math.floor(hours);
    var m = Math.round((hours - h) * 60);
    return h + 'h' + (m > 0 ? ' ' + m + 'm' : '');
  }

  function _sleepQualityLabel(q) {
    if (q == null) return null;
    var labels = { 1: 'poor', 2: 'fair', 3: 'okay', 4: 'good', 5: 'great' };
    return labels[q] || null;
  }

  function renderSleepCard(el, sleep) {
    if (!el) return;

    var header =
      '<div class="slp-lbl"><i class="ti ti-moon"></i>Sleep · last night</div>';

    if (!sleep) {
      el.innerHTML = header +
        '<div class="slp-empty">No sleep data available.</div>';
      return;
    }

    if (!sleep.logged) {
      el.innerHTML = header +
        '<div class="slp-empty">' +
          'No sleep logged for last night &middot; ' +
          '<a href="/calendar">Add it with today\'s metrics &#8594;</a>' +
        '</div>';
      return;
    }

    /* logged === true */
    var hoursStr = _fmtSleepHours(sleep.hours);
    var qualLabel = _sleepQualityLabel(sleep.quality);
    var qualHtml = qualLabel
      ? '<div class="slp-quality">' + qualLabel + '</div>'
      : '';

    el.innerHTML = header +
      '<div class="slp-body">' +
        '<div class="slp-top">' +
          '<div class="slp-score">' + hoursStr + '</div>' +
          qualHtml +
        '</div>' +
        (sleep.quality != null
          ? '<div class="slp-quality-detail">Quality ' + sleep.quality + '/5</div>'
          : '') +
      '</div>';
  }

  /* ── Render (accepts pre-fetched summary data from home.js) ─────────────── */

  function render(summary) {
    var rdEl  = document.getElementById('home-top-row-right');
    var twEl  = document.getElementById('home-training-card');
    var slpEl = document.getElementById('home-sleep-card');

    if (rdEl) {
      if (!rdEl.classList.contains('card')) {
        rdEl.className = 'card';
      }
      renderReadinessTile(rdEl, summary && summary.readiness ? summary.readiness : null);
    }
    if (twEl) {
      renderTrainingCard(twEl, summary && summary.training_week ? summary.training_week : null);
    }
    if (slpEl) {
      renderSleepCard(slpEl, summary && summary.sleep ? summary.sleep : null);
    }
  }

  /* Expose for home.js to call with pre-fetched summary */
  window.HomeRTS = { render: render };
})();
