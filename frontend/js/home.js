(function () {
  /* ---- HTML escaping (XSS guard for user/API strings in innerHTML) ---- */
  function esc(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
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

  function addISODays(isoStr, n) {
    var d = new Date(isoStr + 'T00:00:00');
    d.setDate(d.getDate() + n);
    return isoDate(d);
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
        '<div><div class="trk-name">' + esc(pr.track_name) + '</div>' +
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
        '<div><div class="trk-name">' + esc(pr.track_name) + '</div>' +
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
    var row2 = document.getElementById('home-perf-container') ||
               document.getElementById('row-2');
    if (!row2) return;

    var card = document.getElementById('perf-card');
    if (!card) {
      card = document.createElement('div');
      card.id = 'perf-card';
      card.className = 'card grp-training';
      row2.insertBefore(card, row2.firstChild);
    }

    var perfHeader =
      '<div class="card-head">' +
        '<div class="ttl"><a href="/settings#personal-records" style="color:inherit;text-decoration:none;display:inline-flex;align-items:center;gap:7px;"><i class="ti ti-trophy" style="color:var(--gold);"></i>Personal records</a></div>' +
        '<a href="/settings#personal-records">All tracks →</a>' +
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
        '<a href="/settings#personal-records">Set your personal records →</a>';
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

    var titleText = esc(w.name);
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

    // Zone-2 badge (issue #441): minutes spent in Z2 when the backend reports it
    var z2HTML = '';
    if (w.zone2_minutes != null) {
      z2HTML = '<div class="z2-badge" title="Zone 2 minutes">Z2 ' + w.zone2_minutes + '</div>';
    }

    return '<div class="workout' + (extraCls ? ' ' + extraCls : '') + '">' +
      '<div class="icon-wrap ' + ic.cls + '"><i class="ti ' + ic.icon + '"></i></div>' +
      '<div class="info">' +
        '<div class="ttl">' + titleText + '</div>' +
        '<div class="meta">' + metaParts.join(' · ') + '</div>' +
      '</div>' +
      z2HTML +
      '<div class="sources">' + badgesHTML + '</div>' +
    '</div>';
  }

  /* Recent workout — merged into #home-next-workout-card (home v3, Task 1).
     Fills only its sub-section (#home-recent-workout-section), built by
     home-readiness-training-sleep.js's renderNextWorkoutCard skeleton; the
     "Next workout" sub-section above it is that file's own concern.

     Data source is /api/home/summary's "recent_workouts" block, which is a
     bare array (see backend _build_recent_workouts_block) — NOT
     {workouts:[...]}. The previous code read workoutsBlock.workouts, which
     is always undefined on an array, so this always rendered the empty
     state regardless of real data (pre-existing bug, not introduced by the
     merge — same wrong access was already in the old standalone card).
     Also, that block's items are a lightweight summary shape (name,
     workout_type, relative_day, summary) — not a full Workout row — so this
     builds its own compact row instead of reusing buildWorkoutRow(), which
     expects raw Workout fields (workout_date, distance_km, source, ...)
     that this summary doesn't have. */
  function _recentWorkoutBadgeCls(t) {
    return (t === 'strength' || t === 'plyo') ? 'lift' : 'run';
  }
  function _recentWorkoutBadgeLabel(t) {
    if (t === 'strength') return 'Strength';
    if (t === 'plyo') return 'Plyo';
    return 'Run';
  }
  function loadRecentWorkoutsCard(userId, workoutsBlock) {
    var sectionEl = document.getElementById('home-recent-workout-section');
    if (!sectionEl) return;

    var workouts = Array.isArray(workoutsBlock) ? workoutsBlock : [];

    if (!workouts.length) {
      sectionEl.innerHTML =
        '<div class="workouts-empty">No workouts yet — ' +
        '<a href="/training?return=/home">log your first</a>.</div>';
      return;
    }

    var w = workouts[0];
    var cls = _recentWorkoutBadgeCls(w.workout_type);
    var label = _recentWorkoutBadgeLabel(w.workout_type);
    var metaParts = [w.relative_day];
    if (w.summary) metaParts.push(w.summary);

    sectionEl.innerHTML =
      '<div class="nw-row">' +
        '<span class="nw-badge nw-badge--' + cls + '">' + label + '</span>' +
        '<span class="nw-info">' +
          '<span class="nw-name">' + esc(w.name || 'Workout') + '</span>' +
          '<span class="nw-meta">' + esc(metaParts.filter(Boolean).join(' · ')) + '</span>' +
        '</span>' +
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
    { inputId: 'fm-rhr',    minusId: 'fm-rhr-minus',    plusId: 'fm-rhr-plus',    min: 30,  max: 120,   step: 1   },
    { inputId: 'fm-hrv',    minusId: 'fm-hrv-minus',    plusId: 'fm-hrv-plus',    min: 0,   max: 200,   step: 1   },
    { inputId: 'fm-sleep',  minusId: 'fm-sleep-minus',  plusId: 'fm-sleep-plus',  min: 0,   max: 12,    step: 0.5 },
    { inputId: 'fm-kcal',   minusId: 'fm-kcal-minus',   plusId: 'fm-kcal-plus',   min: 1,   max: 10000, step: 50  },
    { inputId: 'fm-weight', minusId: 'fm-weight-minus', plusId: 'fm-weight-plus', min: 30,  max: 200,   step: 1   },
  ];

  function _fmBuildPayload() {
    var rhr    = document.getElementById('fm-rhr')   ? document.getElementById('fm-rhr').value.trim()   : '';
    var hrv    = document.getElementById('fm-hrv')   ? document.getElementById('fm-hrv').value.trim()   : '';
    var sleep  = document.getElementById('fm-sleep') ? document.getElementById('fm-sleep').value.trim() : '';
    var kcal   = document.getElementById('fm-kcal')  ? document.getElementById('fm-kcal').value.trim()  : '';
    var energy = document.getElementById('fm-energy-val') ? document.getElementById('fm-energy-val').value : '';
    var mood   = document.getElementById('fm-mood-val')   ? document.getElementById('fm-mood-val').value   : '';
    var notes  = document.getElementById('fm-notes') ? document.getElementById('fm-notes').value.trim()  : '';

    var payload = {};
    if (rhr    !== '') payload.resting_hr  = parseInt(rhr, 10);
    if (hrv    !== '') payload.hrv         = parseInt(hrv, 10);
    if (sleep  !== '') payload.sleep_hours = parseFloat(sleep);
    if (kcal   !== '') payload.kcal_intake = parseInt(kcal, 10);
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
    if (existing.kcal_intake != null) { var el = document.getElementById('fm-kcal');  if (el) el.value = existing.kcal_intake; }
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

  /* ---- Home Weight Widget ----
     The "current weight" stat block is rendered by the shared component
     js/lib/weight-current-card.js (same one the weight tab uses). This file
     only owns the quick-log stepper below. */

  function _hwwInitStepper(el, summary, userId) {
    var stepperArea = el.querySelector('#hww-stepper-area');
    if (!stepperArea) return;

    var prefill = summary && summary.last_entry_kg != null ? Number(summary.last_entry_kg).toFixed(1) : '';
    var loggedEntryId = null;

    function _renderStepper(currentVal) {
      stepperArea.innerHTML =
        '<div class="hww-stepper-label">Log today</div>' +
        '<div class="hww-step-row">' +
          '<button type="button" class="hww-step-btn" id="hww-minus">−</button>' +
          '<input id="hww-input" class="hww-step-input" type="number"' +
            ' inputmode="decimal" step="0.1" min="20" max="300"' +
            ' value="' + (currentVal != null ? currentVal : '') + '"' +
            ' placeholder="—">' +
          '<button type="button" class="hww-step-btn" id="hww-plus">+</button>' +
        '</div>' +
        '<button type="button" class="hww-log-btn" id="hww-log-btn">' +
          'Log ' + (currentVal != null ? currentVal + ' kg' : '—') +
        '</button>';

      var input = stepperArea.querySelector('#hww-input');
      var logBtn = stepperArea.querySelector('#hww-log-btn');
      var minusBtn = stepperArea.querySelector('#hww-minus');
      var plusBtn = stepperArea.querySelector('#hww-plus');

      function _updateLabel() {
        var v = parseFloat(input.value);
        logBtn.textContent = (!isNaN(v) && v >= 20 && v <= 300) ? 'Log ' + v.toFixed(1) + ' kg' : 'Log —';
      }

      function _step(delta) {
        var cur = input.value === '' ? NaN : parseFloat(input.value);
        var next;
        if (isNaN(cur)) {
          next = delta > 0 ? 20 : 300;
        } else {
          next = Math.min(300, Math.max(20, Math.round((cur + delta) * 10) / 10));
        }
        input.value = next.toFixed(1);
        _updateLabel();
      }

      minusBtn.addEventListener('click', function () { _step(-0.1); });
      plusBtn.addEventListener('click',  function () { _step( 0.1); });
      input.addEventListener('input', _updateLabel);

      logBtn.addEventListener('click', async function () {
        var raw = input.value.trim();
        if (raw === '' || isNaN(parseFloat(raw))) return;
        var val = parseFloat(raw);
        if (val < 20 || val > 300) return;
        logBtn.disabled = true;
        var todayStr = bangkokTodayStr();
        try {
          var res = await fetch('/api/weight-entries', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              user_id: userId,
              entry_date: todayStr,
              weight_kg: val
            })
          });
          var entryId = null;
          if (res.status === 409) {
            var conflictData = null;
            try { conflictData = await res.json(); } catch (_) {}
            entryId = conflictData && conflictData.existing_id ? conflictData.existing_id : null;
            if (entryId) {
              var patchRes = await fetch('/api/weight-entries/' + entryId, {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ weight_kg: val })
              });
              if (!patchRes.ok) { logBtn.disabled = false; return; }
            }
          } else if (res.ok) {
            var created = null;
            try { created = await res.json(); } catch (_) {}
            entryId = created && created.id ? created.id : null;
          } else {
            logBtn.disabled = false;
            return;
          }
          loggedEntryId = entryId;
          _renderCompact(val.toFixed(1));
          // Refresh the shared current-weight block after logging.
          _hwwLoadCurrentCard();
        } catch (_) {
          logBtn.disabled = false;
        }
      });
    }

    function _renderCompact(kgStr) {
      stepperArea.innerHTML =
        '<div class="hww-compact">' +
          '<span>✓ Logged today · ' + kgStr + ' kg</span>' +
          '<button type="button" class="hww-compact-edit">edit</button>' +
        '</div>';
      var editBtn = stepperArea.querySelector('.hww-compact-edit');
      if (editBtn) {
        editBtn.addEventListener('click', function () {
          _renderStepper(parseFloat(kgStr));
        });
      }
    }

    _renderStepper(prefill !== '' ? parseFloat(prefill) : null);
  }

  async function _renderBodyModifierGuardrail() {
    var el = document.getElementById('body-modifier-guardrail');
    if (!el) return;
    try {
      var res = await fetch('/api/body-modifier/guardrail');
      if (!res.ok) { el.innerHTML = ''; return; }
      var data = await res.json();
      if (data.guardrail_state !== 'warn') {
        el.innerHTML = '';
        return;
      }
      var msg = data.guardrail_message || 'You are in the penalty region — this is a performance and health risk.';
      el.innerHTML =
        '<div class="bm-guardrail">' +
          '<span class="bm-guardrail-icon" aria-hidden="true">&#9888;</span>' +
          '<span><span class="bm-guardrail-label">Performance risk:</span>' +
          '<span class="bm-guardrail-msg"> ' + _escHtml(msg) + '</span></span>' +
        '</div>';
    } catch (_) {
      el.innerHTML = '';
    }
  }

  function _escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function _weightSummaryAdapter(wBlock) {
    if (!wBlock) return null;
    return {
      current_weight: wBlock.current_kg,
      avg_7d:         wBlock.seven_day_avg,
      weekly_rate_kg: wBlock.weekly_rate_kg,
      sparkline:      wBlock.sparkline,
      plan:           wBlock.plan_sparkline,
      status_label:   wBlock.gap_direction,
      gap_kg:         wBlock.gap_kg,
      last_entry_kg:  wBlock.last_entry_kg,
      logged_today:   wBlock.logged_today,
      target: (wBlock.target_kg != null ? {
        weight_kg:    wBlock.target_kg,
        date:         wBlock.target_date,
        progress_pct: wBlock.progress_pct,
        direction:    wBlock.gap_direction === 'below' ? 'down' : 'up',
      } : null),
    };
  }

  function _renderHomeWeightWidget(weightBlock, userId) {
    var container = document.getElementById('home-weight-widget');
    if (!container) return;

    var card = container.querySelector('.card.hww-card');
    if (!card) {
      card = document.createElement('div');
      card.className = 'card hww-card grp-weight';
      container.appendChild(card);
    }

    // Left: shared "current weight" block (same component as the weight tab,
    // js/lib/weight-current-card.js). Right: home's own quick-log stepper.
    var header =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-scale" style="color:var(--blue-text);font-size:16px;"></i>Weight</div>' +
        '<a href="/weight">Open →</a>' +
      '</div>';
    card.innerHTML = header +
      '<div class="hww-layout">' +
        '<div class="hww-main">' + WeightCurrentCard.MARKUP + '</div>' +
        '<div class="hww-stepper" id="hww-stepper-area"></div>' +
      '</div>';

    _hwwInitStepper(card, _weightSummaryAdapter(weightBlock), userId);
    _hwwLoadCurrentCard();
  }

  // Populate the shared current-weight block from the SAME endpoints the
  // weight tab uses, so the two widgets stay byte-for-byte identical.
  function _hwwLoadCurrentCard() {
    if (!window.WeightCurrentCard) return;
    var to = new Date().toISOString().slice(0, 10);
    var f = new Date();
    f.setDate(f.getDate() - 90);
    var from = f.toISOString().slice(0, 10);
    Promise.all([
      fetch('/api/weight-chart?from=' + from + '&to=' + to + '&include_target=true')
        .then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
      fetch('/api/weight-targets/active')
        .then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; })
    ]).then(function (res) {
      WeightCurrentCard.render(res[0], res[1]);
    });
  }

  /* ---- Init ---- */

  async function init() {
    setGreetingDate();
    var userId = null;

    // /api/home/summary resolves the user from the session cookie, not a
    // userId param, so it doesn't actually depend on fetchCurrentUser()'s
    // result — fire both immediately instead of waiting on auth first.
    var summaryPromise = fetch('/api/home/summary')
      .then(function (r) { return r.ok ? r.json() : {}; })
      .catch(function () { return {}; });

    try {
      var user = await window.fetchCurrentUser();
      if (!user) { window.location.href = '/login'; return; }
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

      /* Single summary fetch — distribute to all widget renderers */
      var summary = await summaryPromise;

      /* Habits strip + log-today strip */
      if (window.HomeStripHabits) {
        HomeStripHabits.render(summary);
      }

      /* Readiness tile + training card + sleep card + next-workout +
         performance widget (home v2) */
      if (window.HomeRTS) {
        HomeRTS.render(summary, userId);
      }

      /* Body-modifier guardrail warning (issue #1161) */
      _renderBodyModifierGuardrail();

      /* Weight widget (using summary.weight block) */
      _renderHomeWeightWidget(summary.weight, userId);

      /* Performance card (fetches own data, uses summary.performance for context) */
      var _perfBlock = summary.performance;
      loadPerformanceCard(userId, _perfBlock);

      /* Recent workouts card (fetches own data, uses summary.recent_workouts for context) */
      var _workoutsBlock = summary.recent_workouts;
      loadRecentWorkoutsCard(userId, _workoutsBlock);

      initFastLogForm(userId);


    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
