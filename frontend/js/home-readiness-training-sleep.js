(function () {
  'use strict';

  /* HTML escaping (XSS guard) for the user-generated strings the home v2
     widgets echo — session names, error/reason text from the API. */
  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

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

  /* ── CTL/ATL/TSB training-load trio (home v2) ──────────────────────────────
     Second section of the Readiness card, below the existing daily-signal
     block. Ported from training-log.js's private _lrxReadStatus/_lrxMarkerPct/
     _lrxTrendLine/_LRX_BAND/_LRX_TREND_COLOR (~line 682-711) — DUPLICATED, not
     imported (that IIFE doesn't export them), at the exact same band
     thresholds. Status colors are ported as literal hex (the --lrx-* CSS vars
     they reference don't exist on this page) matching the Log tab's rendered
     colors exactly. */
  function _rdCtlStatus(metric, v) {
    if (metric === 'ctl') {
      if (v < 20) return { word: 'DETRAINING', color: '#d97706' };
      if (v < 40) return { word: 'STEADY', color: '#6366f1' };
      return { word: 'STRONG', color: '#16a34a' };
    }
    if (metric === 'atl') {
      if (v < 25) return { word: 'LOW', color: '#16a34a' };
      if (v < 45) return { word: 'MODERATE', color: '#6366f1' };
      return { word: 'HIGH', color: '#d97706' };
    }
    // tsb
    if (v < -10) return { word: 'OVERREACHED', color: '#d97706' };
    if (v <= 5) return { word: 'OPTIMAL', color: '#16a34a' };
    return { word: 'FRESH', color: '#4f6ef7' };
  }

  function _rdCtlMarkerPct(metric, v) {
    var min = metric === 'tsb' ? -25 : 0;
    var max = metric === 'tsb' ? 15 : 60;
    var pct = ((v - min) / (max - min)) * 100;
    return Math.max(2, Math.min(98, pct));
  }

  var _RD_CTL_BAND = {
    ctl: 'linear-gradient(90deg,#fbbf24,#60a5fa,#22c55e)',
    atl: 'linear-gradient(90deg,#22c55e,#eab308,#ef4444)',
    tsb: 'linear-gradient(90deg,#f59e0b,#22c55e,#60a5fa)',
  };
  var _RD_CTL_TREND_COLOR = { ctl: '#4f6ef7', atl: '#dc2626', tsb: '#16a34a' };

  function _rdCtlFmt(v) {
    if (v === null || v === undefined || isNaN(v)) return '—';
    return String(Math.round(v * 10) / 10);
  }

  /* Small sparkline (~100×24, matching the mock's .ctlspark) — same draw
     algorithm as _lrxTrendLine, scaled down. */
  function _rdCtlSpark(svgId, pts, color) {
    var svg = document.getElementById(svgId);
    if (!svg || !pts || pts.length < 2) return;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var W = 100, H = 24;
    var mn = Math.min.apply(null, pts), mx = Math.max.apply(null, pts);
    var d = pts
      .map(function (v, i) {
        var x = (i / (pts.length - 1)) * W;
        var y = H - ((v - mn) / (mx - mn + 0.001)) * (H - 4) - 2;
        return (i ? 'L' : 'M') + x.toFixed(1) + ' ' + y.toFixed(1);
      })
      .join(' ');
    svg.setAttribute('viewBox', '0 0 ' + W + ' ' + H);
    var NS = 'http://www.w3.org/2000/svg';
    var path = document.createElementNS(NS, 'path');
    path.setAttribute('d', d);
    path.setAttribute('fill', 'none');
    path.setAttribute('stroke', color);
    path.setAttribute('stroke-width', '1.6');
    svg.appendChild(path);
  }

  function _rdCtlCardHtml(metric, val, abbr, label, sparkId) {
    var st = _rdCtlStatus(metric, val);
    var pct = _rdCtlMarkerPct(metric, val);
    return '<div class="rd-ctl-card">' +
      '<div class="rd-ctl-v">' + _rdCtlFmt(val) + '</div>' +
      '<div class="rd-ctl-l">' + abbr + ' ' + label + '</div>' +
      '<div class="rd-ctl-band" style="background:' + _RD_CTL_BAND[metric] + '">' +
        '<div class="rd-ctl-mk" style="left:' + pct.toFixed(0) + '%"></div></div>' +
      '<div class="rd-ctl-stat" style="color:' + st.color + '">' + st.word + '</div>' +
      '<svg class="rd-ctl-spark" id="' + sparkId + '"></svg>' +
    '</div>';
  }

  /* trainingLoad is the raw GET /api/readiness (no query params) response —
     a SEPARATE fetch from the /api/home/summary that feeds the rest of this
     tile (wired once in render(), see below). Returns '' when not yet loaded
     (renderReadinessTile is still called immediately with the summary data,
     so the daily-signal block isn't blocked on this extra request). */
  function _rdCtlRowHtml(trainingLoad) {
    if (!trainingLoad) return '';
    if (trainingLoad.building_baseline) {
      return '<div class="rd-ctl-bb">Still building your training-load baseline.</div>';
    }
    return '<div class="rd-ctl-row">' +
      _rdCtlCardHtml('ctl', trainingLoad.ctl, 'CTL', 'Fitness', 'rd-ctl-spark-ctl') +
      _rdCtlCardHtml('atl', trainingLoad.atl, 'ATL', 'Fatigue', 'rd-ctl-spark-atl') +
      _rdCtlCardHtml('tsb', trainingLoad.tsb, 'TSB', 'Freshness', 'rd-ctl-spark-tsb') +
    '</div>';
  }

  function _rdCtlDrawSparks(trainingLoad) {
    if (!trainingLoad || trainingLoad.building_baseline) return;
    var series = Array.isArray(trainingLoad.series) ? trainingLoad.series : [];
    var last9 = series.slice(-9);
    _rdCtlSpark('rd-ctl-spark-ctl', last9.map(function (d) { return d.ctl; }), _RD_CTL_TREND_COLOR.ctl);
    _rdCtlSpark('rd-ctl-spark-atl', last9.map(function (d) { return d.atl; }), _RD_CTL_TREND_COLOR.atl);
    _rdCtlSpark('rd-ctl-spark-tsb', last9.map(function (d) { return d.tsb; }), _RD_CTL_TREND_COLOR.tsb);
  }

  function renderReadinessTile(el, readiness, trainingLoad) {
    if (!el) return;

    var header =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-heart-rate-monitor"></i>Readiness · today</div>' +
        '<a href="/calendar">Log metrics &#8594;</a>' +
      '</div>';

    var body;

    /* Null block — render minimal fallback without errors */
    if (!readiness) {
      body =
        '<div class="rd-tile-empty">' +
          '<p class="rd-tile-msg">No readiness data available.</p>' +
        '</div>';

    /* logged === false → empty state */
    } else if (!readiness.logged) {
      body =
        '<div class="rd-tile-empty">' +
          '<i class="ti ti-moon-stars rd-tile-icon"></i>' +
          '<p class="rd-tile-msg">No metrics logged yet today — log to see your readiness score</p>' +
          '<a href="/calendar" class="rd-tile-cta-btn">' +
            '<i class="ti ti-pencil-plus"></i> Log today\'s metrics' +
          '</a>' +
        '</div>';

    /* logged === true → score ring + top 3 factors */
    } else {
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

      var explanationHTML = '';
      if (readiness.explanation) {
        explanationHTML = '<p class="rd-tile-explanation">' +
          readiness.explanation.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;') +
        '</p>';
      }

      body =
        '<div class="rd-tile-body">' +
          '<div class="rd-tile-ring-wrap">' +
            _rdRingSVG(score, color) +
            '<div class="rd-tile-score-label" style="color:' + color + ';">' + label + '</div>' +
          '</div>' +
          '<div class="rd-tile-factors">' + factorsHTML + '</div>' +
        '</div>' +
        explanationHTML;
    }

    // CTL/ATL/TSB trio appended below the daily-signal block, inside the same
    // card, in every branch above (it's a separate data source — training
    // load exists whether or not today's wellness metrics were logged).
    el.innerHTML = header + body + _rdCtlRowHtml(trainingLoad);
    _rdCtlDrawSparks(trainingLoad);
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
        '<div class="ttl"><i class="ti ti-barbell"></i>Training</div>' +
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

    // Link out to the Log tab's Weekly Volume (8-week TSS-bars + distance-line)
    // chart — no second copy of that chart built here (home v2).
    var trendLinkHTML =
      '<a class="tw-trendlink" href="/log#volume-chart-card">View 8-week trend &#8594;</a>';

    el.innerHTML = header + statsHTML + chartHTML + trendLinkHTML;
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

  /* ── Next workout (home v2) ─────────────────────────────────────────────── */

  var _NW_DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
  var _NW_MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];

  function _nwAddDaysISO(isoStr, n) {
    var d = new Date(isoStr + 'T00:00:00');
    d.setDate(d.getDate() + n);
    return d.getFullYear() + '-' +
      String(d.getMonth() + 1).padStart(2, '0') + '-' +
      String(d.getDate()).padStart(2, '0');
  }

  function _nwFmtDate(isoStr) {
    var p = isoStr.split('-');
    var d = new Date(parseInt(p[0], 10), parseInt(p[1], 10) - 1, parseInt(p[2], 10));
    return _NW_DOW[d.getDay()] + ', ' + _NW_MONTHS[d.getMonth()] + ' ' + d.getDate();
  }

  // Cheap structure summary — NOT the full Plan-tab structure renderer, just
  // enough for a one-line meta string (e.g. "100min" / "5 exercises").
  function _nwStructureSummary(structure) {
    var s = structure || {};
    if (Array.isArray(s.blocks) && s.blocks.length) {
      var tot = 0;
      s.blocks.forEach(function (b) {
        var d = Number(b.duration_min) || 0, r = Math.max(1, Number(b.repeat) || 1);
        tot += d * r + (Number(b.rest_min) || 0) * (r - 1);
      });
      return tot ? tot + 'min' : '';
    }
    if (Array.isArray(s.exercises) && s.exercises.length) {
      return s.exercises.length + ' exercise' + (s.exercises.length > 1 ? 's' : '');
    }
    return '';
  }

  function _nwBadgeCls(sessionType) {
    return (sessionType === 'strength' || sessionType === 'plyo') ? 'lift' : 'run';
  }
  function _nwBadgeLabel(sessionType) {
    if (sessionType === 'strength') return 'Strength';
    if (sessionType === 'plyo') return 'Plyo';
    return 'Run';
  }

  // Iterate days[] in order, collecting up to `limit` upcoming non-rest
  // sessions (one per day — prefer status==='planned' when a day has more
  // than one, else planned[0]). Rest-only/empty days are skipped (kept
  // scanning) rather than counted — if nothing non-rest exists anywhere in
  // the window, the caller falls through to the empty state.
  function _nwFindUpcoming(bundle, limit) {
    var days = (bundle && Array.isArray(bundle.days)) ? bundle.days : [];
    var out = [];
    for (var i = 0; i < days.length && out.length < limit; i++) {
      var planned = Array.isArray(days[i].planned) ? days[i].planned : [];
      var nonRest = planned.filter(function (p) { return p.session_type !== 'rest'; });
      if (!nonRest.length) continue;
      var preferred = nonRest.find(function (p) { return p.status === 'planned'; });
      out.push(preferred || nonRest[0]);
    }
    return out;
  }

  function _nwEmptyHtml() {
    return '<div class="nw-empty"><a href="/log#plan">No upcoming session — plan your week &#8594;</a></div>';
  }

  /* Skeleton for the merged Next+Recent card — both sub-headers and two empty
     section placeholders (#home-next-workout-section /
     #home-recent-workout-section). Both are filled by _nwFill once the planned
     fetch resolves, so Next and Recent counts share one capacity budget. */
  function _nwSkeletonHtml() {
    return (
      '<div class="nw-worksub">' +
        '<div class="nw-subhead">Next workout</div>' +
        '<a href="/log#plan">Plan &#8594;</a>' +
      '</div>' +
      '<div id="home-next-workout-section" class="nw-loading">Loading…</div>' +
      '<div class="nw-sep"></div>' +
      '<div class="nw-worksub">' +
        '<div class="nw-subhead">Recent workout</div>' +
        '<span style="display:inline-flex;align-items:center;gap:10px;">' +
          '<a href="/training?return=/home">Log workout</a>' +
          '<a href="/log">View all &#8594;</a>' +
        '</span>' +
      '</div>' +
      '<div id="home-recent-workout-section" class="nw-loading">Loading…</div>'
    );
  }

  /* One "Recent workout" row — same grid/markup as a Next row but a plain div
     (no /plan link, no trailing arrow). recent items come from the home
     summary block: {name, workout_type, relative_day, summary}. */
  function _nwRecentRowHtml(w) {
    var cls = _nwBadgeCls(w.workout_type);
    var label = _nwBadgeLabel(w.workout_type);
    var metaParts = [w.relative_day];
    if (w.summary) metaParts.push(w.summary);
    return '<div class="nw-row nw-row--recent">' +
        '<span class="nw-badge nw-badge--' + cls + '">' + label + '</span>' +
        '<span class="nw-info">' +
          '<span class="nw-name">' + esc(w.name || 'Workout') + '</span>' +
          '<span class="nw-meta">' + esc(metaParts.filter(Boolean).join(' · ')) + '</span>' +
        '</span>' +
      '</div>';
  }

  function _nwNextRowHtml(next) {
    var cls = _nwBadgeCls(next.session_type);
    var label = _nwBadgeLabel(next.session_type);
    var metaParts = [_nwFmtDate(next.planned_date)];
    var summary = _nwStructureSummary(next.structure);
    if (summary) metaParts.push(summary);
    return '<a class="nw-row" href="/log#plan">' +
        '<span class="nw-badge nw-badge--' + cls + '">' + label + '</span>' +
        '<span class="nw-info">' +
          '<span class="nw-name">' + esc(next.name || 'Session') + '</span>' +
          '<span class="nw-meta">' + esc(metaParts.join(' · ')) + '</span>' +
        '</span>' +
        '<span class="nw-arrow">&#8594;</span>' +
      '</a>';
  }

  /* Decide how many Next vs Recent rows to show so the card fills its grid
     track without overflowing. Capacity is measured from the (stretched) card
     height at render time; Next is capped at half the card so a couple of
     planned sessions can't crowd out the recent history (the common case is
     few Next + many Recent). Returns {next, recent} counts. */
  function _nwFillCounts(el, nextAvail, recentAvail) {
    var h = el ? el.clientHeight : 0;
    // Below ~260px the card isn't stretched (mobile flex column, or measured
    // before layout settled) — fall back to a sensible fixed capacity.
    var capacity = h < 260 ? 8
      : Math.max(4, Math.min(12, Math.floor((h - 120) / 40)));
    var next = Math.min(nextAvail, Math.floor(capacity / 2));
    var recent = Math.min(recentAvail, capacity - next);
    // Rule: Next may not exceed 50% of what's shown. When recent is plentiful
    // this is already satisfied; when recent is scarce, shrink next to match so
    // it never dominates (unless there's no recent at all to pair against).
    if (recent > 0) next = Math.min(next, recent);
    return { next: Math.max(next, nextAvail ? 1 : 0), recent: recent };
  }

  function renderNextWorkoutCard(el, recentWorkouts) {
    if (!el) return;

    el.innerHTML = _nwSkeletonHtml();
    var recent = Array.isArray(recentWorkouts) ? recentWorkouts : [];

    var today = _bangkokTodayStr();
    var to = _nwAddDaysISO(today, 13);
    fetch('/api/planned-sessions?from=' + today + '&to=' + to)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (bundle) { _nwFill(el, _nwFindUpcoming(bundle, 6), recent); })
      .catch(function () { _nwFill(el, [], recent); });
  }

  function _nwFill(el, upcoming, recent) {
    var nextSection = document.getElementById('home-next-workout-section');
    var recentSection = document.getElementById('home-recent-workout-section');

    var counts = _nwFillCounts(el, upcoming.length, recent.length);

    if (nextSection) {
      nextSection.innerHTML = counts.next
        ? upcoming.slice(0, counts.next).map(_nwNextRowHtml).join('')
        : _nwEmptyHtml();
    }
    if (recentSection) {
      recentSection.innerHTML = counts.recent
        ? recent.slice(0, counts.recent).map(_nwRecentRowHtml).join('')
        : '<div class="workouts-empty">No workouts yet — ' +
          '<a href="/training?return=/home">log your first</a>.</div>';
    }
  }

  /* ── Performance (Endurance/Speed) widget (home v2) ─────────────────────── */
  /* ⚠️ Single source of truth: GET /api/athletes/{id}/performance — the SAME
     endpoint the Performance tab and Plan tab's projection cards read. Do not
     compute or mock a score here. */

  // Block-delta — DUPLICATED exactly from training-performance.js's private
  // _blockDelta (~line 226-248, not exported). Finds the latest trend point
  // whose date is ~28 days before the last date, by DATE via the parallel
  // trend_dates array (the trend is step-like/irregular, so an index offset
  // is wrong — see the source comment). Returns null (hide the pill) when no
  // such point exists.
  function _hpfBlockDelta(trend, trendDates) {
    if (!Array.isArray(trend) || trend.length < 2) return null;
    var last = trend[trend.length - 1];
    if (last == null) return null;

    var base = null;
    if (Array.isArray(trendDates) && trendDates.length === trend.length) {
      var lastMs = Date.parse(trendDates[trendDates.length - 1] + 'T00:00:00');
      var cutoff = lastMs - 28 * 86400000; // ~4 weeks back
      for (var i = trend.length - 1; i >= 0; i--) {
        var ms = Date.parse(trendDates[i] + 'T00:00:00');
        if (!isNaN(ms) && ms <= cutoff) { base = trend[i]; break; }
      }
      if (base == null) return null;
    } else {
      base = trend[0];
    }
    if (base == null) return null;
    return Math.round(last - base);
  }

  function _hpfTileHtml(label, cls, data) {
    if (!data || typeof data !== 'object' || data.score == null) {
      return '<div class="hperf-tile hperf-tile--' + cls + '">' +
        '<div class="hperf-lbl">' + label + '</div>' +
        '<div class="hperf-val hperf-dash">—</div>' +
      '</div>';
    }
    var score = Math.round(data.score);
    var trend = Array.isArray(data.trend) ? data.trend : [];
    var delta = _hpfBlockDelta(trend, data.trend_dates);
    var deltaHtml = '';
    if (delta !== null) {
      var dcls = delta > 0 ? 'up' : (delta < 0 ? 'down' : 'flat');
      var dtxt = delta > 0
        ? '&#8593; +' + delta + ' this block'
        : delta < 0
          ? '&#8595; &minus;' + Math.abs(delta) + ' this block'
          : 'flat this block';
      deltaHtml = '<div class="hperf-delta hperf-delta--' + dcls + '">' + dtxt + '</div>';
    }
    return '<div class="hperf-tile hperf-tile--' + cls + '">' +
      '<div class="hperf-lbl">' + label + '</div>' +
      '<div class="hperf-val">' + score + '</div>' +
      deltaHtml +
    '</div>';
  }

  function renderPerformanceCard(el, athleteId) {
    if (!el) return;

    var header =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-chart-line"></i>Performance</div>' +
        '<a href="/log#performance">View trends &#8594;</a>' +
      '</div>';
    el.innerHTML = header + '<div class="hperf-loading">Loading…</div>';

    if (!athleteId) {
      el.innerHTML = header + '<div class="hperf-msg">Could not load score.</div>';
      return;
    }

    fetch('/api/athletes/' + athleteId + '/performance')
      .then(function (r) {
        return r.json().then(function (d) { return d; }).catch(function () { return null; });
      })
      .then(function (data) {
        var state = data && typeof data === 'object' ? data.state : null;

        if (state === 'scored') {
          el.innerHTML = header +
            '<div class="hperf-grid">' +
              _hpfTileHtml('Endurance', 'e', data.endurance) +
              _hpfTileHtml('Speed', 's', data.speed) +
            '</div>';
          return;
        }
        // Mirror the Performance tab's own phrasing for these sub-states
        // (frontend/pages/training-log.html .perf-threshold-hint / .perf-bb-reason).
        if (state === 'needs_thresholds') {
          el.innerHTML = header +
            '<div class="hperf-msg">To compute your score, set your FTP, threshold HR, ' +
              'and threshold pace in <a href="/settings#thresholds">Settings → Thresholds</a>.</div>';
          return;
        }
        if (state === 'building_baseline') {
          var reason = (data && data.reason) || 'Keep training: your baseline is building.';
          el.innerHTML = header + '<div class="hperf-msg">' + esc(reason) + '</div>';
          return;
        }
        el.innerHTML = header + '<div class="hperf-msg">Could not load score.</div>';
      })
      .catch(function () {
        el.innerHTML = header + '<div class="hperf-msg">Could not load score.</div>';
      });
  }

  /* ── Render (accepts pre-fetched summary data from home.js) ─────────────── */

  function render(summary, userId) {
    var rdEl  = document.getElementById('home-top-row-right');
    var twEl  = document.getElementById('home-training-card');
    var slpEl = document.getElementById('home-sleep-card');
    var nwEl  = document.getElementById('home-next-workout-card');
    var pfEl  = document.getElementById('home-performance-card');

    if (rdEl) {
      rdEl.classList.add('card');
      var readinessData = summary && summary.readiness ? summary.readiness : null;
      // Render immediately from the summary data (daily signal), then again
      // once the separate CTL/ATL/TSB fetch resolves — the trio is a second,
      // independent data source (GET /api/readiness, no query params), so it
      // shouldn't block the rest of this tile.
      renderReadinessTile(rdEl, readinessData, null);
      fetch('/api/readiness')
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (trainingLoad) {
          renderReadinessTile(rdEl, readinessData, trainingLoad);
        })
        .catch(function () { /* trio stays omitted; daily-signal block is unaffected */ });
    }
    if (twEl) {
      renderTrainingCard(twEl, summary && summary.training_week ? summary.training_week : null);
    }
    if (slpEl) {
      renderSleepCard(slpEl, summary && summary.sleep ? summary.sleep : null);
    }
    if (nwEl) {
      renderNextWorkoutCard(nwEl, summary && summary.recent_workouts ? summary.recent_workouts : []);
    }
    if (pfEl) {
      renderPerformanceCard(pfEl, userId);
    }
  }

  /* Expose for home.js to call with pre-fetched summary (+ the session user
     id, needed for the Performance widget's /api/athletes/{id}/performance
     call — home.js resolves it via fetchCurrentUser() before this runs). */
  window.HomeRTS = { render: render };
})();
