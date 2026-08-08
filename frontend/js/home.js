(function () {
  /* ---- HTML escaping (XSS guard for user/API strings in innerHTML) ---- */
  // Delegates to the shared escaper (issue #1603). The local copies
  // disagreed about the apostrophe, so identical content was safe on
  // some pages and attribute-injectable on others.
  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  /* ---- Greeting ---- */

  function getGreetingPrefix() {
    var h = new Date().getHours();
    if (h < 12) return 'Good morning';
    if (h < 17) return 'Good afternoon';
    return 'Good evening';
  }

  function formatDateSubtitle() {
    var d = window.AppCommon.nowBangkok();
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

  // Returns today's date string (YYYY-MM-DD) in Asia/Bangkok timezone.
  function bangkokTodayStr() {
    return window.AppCommon.todayISO();
  }

  /* Recent workouts are rendered by home-readiness-training-sleep.js's
     renderRecentWorkoutsCard, into #home-recent-workouts-card (bottom of the
     right column — the top of that column is #home-next-up's forward-looking
     "what should I do today" card instead, see NextUpCard). home.js passes
     summary.recent_workouts in via HomeRTS.render(summary, userId); it no
     longer fills the section here. */

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
        feedback.textContent = 'Network error. Try again.';
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
      var isSelected = pill.dataset.val === String(val);
      pill.classList.toggle('active', isSelected);
      pill.setAttribute('aria-pressed', isSelected ? 'true' : 'false');
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

  /* ---- Threshold banner ----
     Was its own raw-hex amber family (#fffbeb/#fcd34d/#b45309/#92400e/
     #78350f) — consolidated onto home.html's own --amber/--amber-soft
     tokens (re-audit #8), with --gold (the existing trophy-icon token)
     reused for the border so a third amber family doesn't get invented.
     tbanner-dismiss grows to a 44px hit area via padding + an equal
     negative margin (re-audit #9), same trick as .hc-brief-close, so the
     visible × glyph doesn't get bigger. */
  var _THRESHOLD_BANNER_CSS = [
    '#threshold-banner{display:flex;align-items:center;gap:8px;padding:9px 24px;',
      "background:var(--amber-soft,#fff0c4);border-bottom:1px solid var(--gold,#a67a2e);font-size:13px;font-weight:500;",
      "font-family:'Inter Tight',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;}",
    '#threshold-banner .tbanner-msg{flex:1;}',
    '#threshold-banner a{color:var(--amber,#6b4408);font-weight:600;text-decoration:underline;}',
    '#threshold-banner .tbanner-dismiss{margin-left:auto;background:none;border:none;',
      'cursor:pointer;font-size:16px;color:var(--amber,#6b4408);line-height:1;flex-shrink:0;',
      'padding:14px 8px;margin:-14px -4px;}',
    '#threshold-banner .tbanner-dismiss:hover{filter:brightness(0.75);}',
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
    // The container starts `hidden` in home.html (frontend/pages/home.html)
    // so it takes no layout space until a stale sync is actually detected —
    // this is the call that's supposed to reveal it. Bailing out because it
    // was still hidden (found live during the S1 UX review) meant this
    // banner could never render for anyone: nothing else ever cleared the
    // attribute, so every call hit this guard and returned immediately.
    if (!container) return;
    container.hidden = false;
    var days = Math.floor(hoursAgo / 24);
    var staleText = hoursAgo > 48
      ? (days + ' day' + (days === 1 ? '' : 's'))
      : (Math.round(hoursAgo) + ' hour' + (Math.round(hoursAgo) === 1 ? '' : 's'));
    container.innerHTML =
      '<div class="strava-stale-banner" id="strava-stale-banner-inner">' +
        '<span aria-hidden="true">&#9888;</span>' +
        '<span class="strava-stale-msg"><b>Strava hasn\'t synced in ' + staleText + '.</b> ' +
          'Every load number below is stale until it does.</span>' +
        '<button type="button" id="strava-stale-refresh">Sync now</button>' +
      '</div>';
    var btn = document.getElementById('strava-stale-refresh');
    if (btn) {
      btn.addEventListener('click', function () {
        btn.disabled = true;
        btn.textContent = 'Syncing…';
        fetch('/api/strava/sync', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
          .then(function (r) { return r.ok ? r.json() : Promise.reject(); })
          .then(function () {
            container.innerHTML = '<div class="strava-stale-banner strava-stale-banner--syncing">Sync started…</div>';
          })
          .catch(function () { container.innerHTML = ''; container.hidden = true; });
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
     The old full-width "current weight + stepper" card (#home-weight-widget,
     built on the shared weight-current-card.js component used elsewhere) is
     retired in home revamp v2 — its two jobs split into #home-morning's
     weigh-in row (quick-log stepper, same POST /api/weight-entries +
     PATCH-on-409 logic, now in home-morning.js) and the new
     #home-weight-trend card (trend/rate/coverage, home-weight-trend.js). */

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
      var msg = data.guardrail_message || 'You are in the penalty region. This is a performance and health risk.';
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

  // Delegates to the shared escaper (issue #1603).
  function _escHtml(s) {
    return window.AppCommon.escapeHtml(s);
  }

  /* ---- Weekly planned-sessions fetch (shared) ----
     One GET /api/planned-sessions for the current Mon–Sun week, distributed
     to #home-morning's session row, #home-next-up (NextUpCard), and
     #home-brief-week-plan-card — per the revamp v2 spec, no widget fetches
     its own copy of this week's plan. */

  function _mondayOf(d) {
    var day = d.getDay(); // 0=Sun..6=Sat
    var diff = (day === 0 ? -6 : 1 - day);
    var m = new Date(d);
    m.setDate(d.getDate() + diff);
    m.setHours(0, 0, 0, 0);
    return m;
  }

  function _isoDate(d) {
    return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
  }

  function _fetchWeekPlannedSessions() {
    // Anchor the week on Bangkok "today" (same clock as AppCommon.todayISO /
    // the morning session filter), not the browser's local Date — otherwise
    // a laptop in UTC-5 can ask for the wrong Mon–Sun window near midnight.
    var todayIso = window.AppCommon.todayISO();
    var parts = todayIso.split('-');
    var today = new Date(+parts[0], +parts[1] - 1, +parts[2]);
    var monday = _mondayOf(today);
    var sunday = new Date(monday);
    sunday.setDate(monday.getDate() + 6);
    var from = _isoDate(monday);
    var to = _isoDate(sunday);
    return fetch('/api/planned-sessions?from=' + from + '&to=' + to)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { return (data && data.days) || []; })
      .catch(function () { return []; });
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

      /* Single summary fetch — distribute to all widget renderers. One more
         GET /api/planned-sessions for the current week, shared across the
         morning session row, Today's workout (NextUpCard), and Week plan —
         per the revamp v2 spec, no widget below fetches its own copy. */
      var results = await Promise.all([summaryPromise, _fetchWeekPlannedSessions()]);
      var summary = results[0];
      var weekDays = results[1];

      /* Readiness tile + training card + recent-workouts + performance
         widget + coach digest (home v2 / revamp v2) */
      if (window.HomeRTS) {
        HomeRTS.render(summary, userId);
      }

      /* This morning — weigh-in, today's session, habits (home-morning.js).
         Re-render after a weight/habit log so the "N of 3 done" progress
         and all-done state reflect the just-saved change; the session row's
         own optimistic UI handles itself without a re-render. */
      var morningEl = document.getElementById('home-morning');
      var nextUpEl = document.getElementById('home-next-up');
      var weekPlanEl = document.getElementById('home-brief-week-plan-card');

      function _renderNextUpCard() {
        if (window.NextUpCard && nextUpEl) {
          NextUpCard.render(nextUpEl, {
            days: weekDays,
            title: "Today's workout",
            onOpen: function () { window.location.href = '/log#plan'; },
            onMarkDone: function (sessionId) {
              fetch('/api/planned-sessions/' + sessionId + '/mark-done', { method: 'POST' })
                .then(function (r) {
                  if (!r.ok) return;
                  return _fetchWeekPlannedSessions().then(function (fresh) {
                    weekDays = fresh;
                    _renderMorning();
                    _renderNextUpCard();
                    if (window.HomeBriefWeekPlanCard && weekPlanEl) {
                      HomeBriefWeekPlanCard.render(weekPlanEl, weekDays);
                    }
                  });
                })
                .catch(function () {});
            },
            onSuggest: function () { window.location.href = '/log#plan'; }
          });
        }
      }

      function _renderMorning() {
        if (window.HomeMorning && morningEl) {
          HomeMorning.render(morningEl, {
            summary: summary,
            weekDays: weekDays,
            onOpenSession: function () { window.location.href = '/log#plan'; },
            onMarkDone: function (sessionId) {
              fetch('/api/planned-sessions/' + sessionId + '/mark-done', { method: 'POST' })
                .then(function (r) {
                  if (!r.ok) return;
                  return _fetchWeekPlannedSessions().then(function (fresh) {
                    weekDays = fresh;
                    _renderNextUpCard();
                    if (window.HomeBriefWeekPlanCard && weekPlanEl) {
                      HomeBriefWeekPlanCard.render(weekPlanEl, weekDays);
                    }
                  });
                })
                .catch(function () {});
            },
            onWeightLogged: function () {
              fetch('/api/home/summary').then(function (r) { return r.ok ? r.json() : null; })
                .then(function (fresh) { if (fresh) { summary = fresh; _renderMorning(); } })
                .catch(function () {});
              if (window.HomeWeightTrend) HomeWeightTrend.render(document.getElementById('home-weight-trend'));
            },
            onHabitToggle: function () {}
          });
        }
      }
      _renderMorning();
      _renderNextUpCard();

      /* Week plan teaser — same shared week fetch. */
      if (window.HomeBriefWeekPlanCard && weekPlanEl) HomeBriefWeekPlanCard.render(weekPlanEl, weekDays);

      /* Weight trend + Race — home revamp v2 (each fetches its own data). */
      if (window.HomeWeightTrend) HomeWeightTrend.render(document.getElementById('home-weight-trend'));
      if (window.HomeRaceCard) HomeRaceCard.render(document.getElementById('home-race-card'));

      /* Body-modifier guardrail warning (issue #1161) */
      _renderBodyModifierGuardrail();

      /* Recent workouts (#home-recent-workouts-card) are rendered by
         HomeRTS.render (called above with summary.recent_workouts). */

      initFastLogForm(userId);
    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
