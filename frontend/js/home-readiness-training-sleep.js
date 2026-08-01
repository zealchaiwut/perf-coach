(function () {
  'use strict';

  /* HTML escaping (XSS guard) for the user-generated strings the home v2
     widgets echo — session names, error/reason text from the API. */
  // Delegates to the shared escaper (issue #1603). The local copies
  // disagreed about the apostrophe, so identical content was safe on
  // some pages and attribute-injectable on others.
  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  /* "Log metrics" CTAs used to link to the standalone /calendar page (its
     day-detail modal was the only way to log daily_metrics for a given
     date). Calendar is gone (nav-cleanup) — same reveal as the Today ·
     Coach strip's own "Log metrics" CTA (home-coach-strip.js), so there is
     one fast-log entry point, not two divergent ones. */
  function _wireLogMetricsCtas(el) {
    if (!el) return;
    var btns = el.querySelectorAll('[data-rd-log-metrics]');
    for (var i = 0; i < btns.length; i++) {
      btns[i].addEventListener('click', function () {
        var row = document.getElementById('row-log');
        if (row) row.hidden = false;
        var btn = document.getElementById('lts-cta-btn') || document.querySelector('.lts-cta-btn');
        if (btn) btn.click();
        else if (row) row.scrollIntoView({ behavior: 'smooth', block: 'start' });
      });
    }
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
    sleep_quality: {
      name: 'Sleep quality',
      fmt: function (v) { return v != null ? v + '/5' : '—'; },
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

  /* Returns the stroke/fill color for a given readiness score band.
     AA-safe darkened variants for use on .grp-training's tinted gradient
     background (linear-gradient(150deg, --shell-1 #eaf0fb, --shell-2
     #d8e3f5)) — the raw --readiness-high/-mid/-low values from styles.css
     (#16a34a/#d97706/#dc2626) all fail 4.5:1 against that tint (2.55-4.22:1
     measured against the darker #d8e3f5 end, the harder of the two stops).
     Darkened the same way --text-tertiary was (#8b95ad → #69748c): same
     hue family, luminance lowered until AA passes on the darker gradient
     stop. Measured contrast ratios (WCAG relative-luminance formula)
     against #d8e3f5 / #eaf0fb:
       green #0c6e30 → 4.93:1 / 5.58:1
       amber #8a4a06 → 5.30:1 / 5.99:1
       red   #b91c1c → 5.00:1 / 5.66:1  (matches styles.css --danger-dark) */
  function _rdRingColor(score) {
    if (score >= 70) return '#0c6e30';   /* readiness-high, AA-safe on .grp-training */
    if (score >= 40) return '#8a4a06';   /* readiness-mid, AA-safe on .grp-training */
    return '#b91c1c';                     /* readiness-low, AA-safe on .grp-training (== --danger-dark) */
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

  /* ── CTL/ATL/TSB/ACWR load tiles (shared with Training Log) ───────────────
     Uses window.LoadReadinessTiles — same 2×2 design as the Log readiness
     widget (number / label / band / status + async ACWR). No home-only
     sparkline fork. */
  function _rdLoadTilesHtml(trainingLoad) {
    if (!trainingLoad || !window.LoadReadinessTiles) return '';
    return (
      '<div class="rd-load-tiles">' +
      LoadReadinessTiles.buildGridHtml(trainingLoad) +
      '</div>'
    );
  }

  function renderReadinessTile(el, readiness, trainingLoad) {
    if (!el) return;

    var header =
      '<div class="card-head">' +
        '<h2 class="ttl"><i class="ti ti-heart-rate-monitor"></i>Readiness · today</h2>' +
        '<button type="button" class="rd-tile-log-link" data-rd-log-metrics>Log metrics &#8594;</button>' +
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
          '<p class="rd-tile-msg">No metrics logged yet today. Log to see your readiness score.</p>' +
          '<button type="button" class="rd-tile-cta-btn" data-rd-log-metrics>' +
            '<i class="ti ti-pencil-plus"></i> Log today\'s metrics' +
          '</button>' +
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
          esc(readiness.explanation) +
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

    // Load tiles (CTL/ATL/TSB/ACWR) below the daily-signal block — independent
    // of whether today's wellness metrics were logged.
    el.innerHTML = header + body + _rdLoadTilesHtml(trainingLoad);
    _wireLogMetricsCtas(el);
    if (trainingLoad && window.LoadReadinessTiles) {
      LoadReadinessTiles.loadAcwrTile(el);
    }
  }

  /* ── Training Card ──────────────────────────────────────────────────────── */

  var _TRAINING_DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  function _bangkokTodayStr() {
    return window.AppCommon.todayISO();
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
        '<h2 class="ttl"><i class="ti ti-barbell"></i>Training</h2>' +
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
      '<h2 class="slp-lbl"><i class="ti ti-moon"></i>Sleep · last night</h2>';

    if (!sleep) {
      el.innerHTML = header +
        '<div class="slp-empty">No sleep data available.</div>';
      return;
    }

    if (!sleep.logged) {
      el.innerHTML = header +
        '<div class="slp-empty">' +
          'No sleep logged for last night &middot; ' +
          '<button type="button" class="slp-log-link" data-rd-log-metrics>Add it with today\'s metrics &#8594;</button>' +
        '</div>';
      _wireLogMetricsCtas(el);
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

  /* ── Recent workouts (retrospective, below Training) ─────────────────────
     Used to live in the top-row slot beside Performance/Readiness; moved down
     so that slot could become home-today-plan-card.js's forward-looking
     "what should I do today" focal card instead (Home today-focal-point UX
     review). Function/CSS-class names below keep the old "nw-" (next
     workout) prefix — it was never accurate even before this move (this
     widget only ever rendered *recent*, not *next*, workouts; see the
     historical comment on renderRecentWorkoutsCard below) — renaming the
     shared .nw-* CSS classes isn't worth the diff for a page-internal
     prefix nobody reads as an acronym. */

  function _nwBadgeCls(sessionType) {
    return (sessionType === 'strength' || sessionType === 'plyo') ? 'lift' : 'run';
  }
  function _nwBadgeLabel(sessionType) {
    if (sessionType === 'strength') return 'Strength';
    if (sessionType === 'plyo') return 'Plyo';
    return 'Run';
  }

  /* Recent workouts — 3–5 rows, sized to roughly match Performance next door. */
  var NW_RECENT_MIN = 3;
  var NW_RECENT_MAX = 5;

  function _nwSkeletonHtml() {
    return (
      '<div class="card-head">' +
        '<h2 class="ttl"><i class="ti ti-history"></i>Recent workouts</h2>' +
        '<span style="display:inline-flex;align-items:center;gap:10px;">' +
          '<a href="/training?return=/home">Log workout</a>' +
          '<a href="/log">View all &#8594;</a>' +
        '</span>' +
      '</div>' +
      '<div id="home-recent-workout-section" class="nw-loading">Loading…</div>'
    );
  }

  /* One recent row — badge + name/meta. */
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

  function renderRecentWorkoutsCard(el, recentWorkouts) {
    if (!el) return;
    el.innerHTML = _nwSkeletonHtml();
    var recent = Array.isArray(recentWorkouts) ? recentWorkouts : [];
    var recentSection = document.getElementById('home-recent-workout-section');
    if (!recentSection) return;
    if (!recent.length) {
      recentSection.innerHTML =
        '<div class="workouts-empty">No workouts yet. ' +
        '<a href="/training?return=/home">Log your first</a>.</div>';
      return;
    }
    // Cap at 5; prefer 4 to sit near Performance height (2 score tiles).
    var n = Math.min(NW_RECENT_MAX, Math.max(NW_RECENT_MIN, 4), recent.length);
    recentSection.innerHTML = recent.slice(0, n).map(_nwRecentRowHtml).join('');
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
    // Use history-based block_delta from API when available (issue #1365);
    // fall back to computing from trend[] when history is absent.
    var delta;
    if (data.block_delta != null) {
      delta = Math.round(data.block_delta);
    } else {
      var trend = Array.isArray(data.trend) ? data.trend : [];
      delta = _hpfBlockDelta(trend, data.trend_dates);
    }
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
        '<h2 class="ttl"><i class="ti ti-chart-line"></i>Performance</h2>' +
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

  /* ── Today card — Coach-only (daily narrative + nudge) ───────────────── */

  function loadCoachBrief() {
    var stripEl = document.getElementById('home-coach-today-strip');
    var digestEl = document.getElementById('home-today-rec-card');
    if (stripEl) {
      stripEl.hidden = false;
      stripEl.innerHTML = '<div class="hc-today"><div class="hc-today-head"><h2 class="hc-today-t">TODAY · COACH</h2></div><div class="hc-today-body"><div class="rec-loading">Loading…</div></div></div>';
    }
    if (digestEl) {
      digestEl.innerHTML =
        '<div class="card-head"><h2 class="ttl">Coach</h2></div>' +
        '<div class="rec-loading">Loading…</div>';
    }
    fetch('/api/coach/brief')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        var brief = data && data.brief;
        if (window.HomeCoachStrip) {
          window.HomeCoachStrip.render(stripEl, brief || null);
        }
        if (window.HomeCoachDigest && digestEl) {
          window.HomeCoachDigest.render(digestEl, brief || null);
        }
      })
      .catch(function () {
        if (window.HomeCoachStrip) window.HomeCoachStrip.render(stripEl, null);
        if (window.HomeCoachDigest && digestEl) {
          window.HomeCoachDigest.render(digestEl, null);
        }
      });
  }

  /* ── Render (accepts pre-fetched summary data from home.js) ─────────────── */

  function render(summary, userId) {
    var rdEl  = document.getElementById('home-top-row-right');
    var twEl  = document.getElementById('home-training-card');
    var slpEl = document.getElementById('home-sleep-card');
    var nwEl  = document.getElementById('home-recent-workouts-card');
    var pfEl  = document.getElementById('home-performance-card');

    if (rdEl) {
      rdEl.classList.add('card');
      var readinessData = summary && summary.readiness ? summary.readiness : null;
      // Render immediately from the summary data (daily signal), then again
      // once the separate CTL/ATL/TSB/ACWR fetch resolves — load tiles are a
      // second, independent data source (GET /api/readiness), so they
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
      renderRecentWorkoutsCard(nwEl, summary && summary.recent_workouts ? summary.recent_workouts : []);
    }
    if (pfEl) {
      renderPerformanceCard(pfEl, userId);
    }
    loadCoachBrief();
  }

  /* Expose for home.js to call with pre-fetched summary (+ the session user
     id, needed for the Performance widget's /api/athletes/{id}/performance
     call — home.js resolves it via fetchCurrentUser() before this runs). */
  window.HomeRTS = { render: render };
})();
