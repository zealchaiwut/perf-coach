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

  // Returns today's date string (YYYY-MM-DD) in Asia/Bangkok timezone.
  function bangkokTodayStr() {
    return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' });
  }

  /* ---- Personal records card helpers (home v3, Task 6) ----
     Pulls the SAME auto-computed run PRs the Performance tab shows (10K /
     Half marathon / Marathon), via /api/athletes/{id}/run-personal-records
     — NOT the old /api/personal-records + TRACK_CONFIGS custom-track
     widget this replaced (that was user-configured "which tracks do you
     care about" data, a different concept, and had drifted from what the
     Performance tab actually surfaces). athleteId === userId in this app
     (single athlete per user), matching the convention already used by
     renderPerformanceCard's own /api/athletes/{userId}/performance call. */
  var PR_TILES = [
    { key: '10km', label: '10K' },
    { key: 'half_marathon', label: 'Half' },
    { key: 'marathon', label: 'Marathon' }
  ];

  function formatRunPrValue(value) {
    if (value == null) return '—';
    var s = Math.round(value);
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = s % 60;
    if (h > 0) return h + ':' + String(m).padStart(2, '0') + ':' + String(sec).padStart(2, '0');
    return m + ':' + String(sec).padStart(2, '0');
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

    var header =
      '<div class="card-head">' +
        '<div class="ttl"><a href="/log#performance" style="color:inherit;text-decoration:none;display:inline-flex;align-items:center;gap:7px;"><i class="ti ti-trophy" style="color:var(--gold);"></i>Personal records</a></div>' +
        '<a href="/log#performance">All PRs &#8594;</a>' +
      '</div>';
    card.innerHTML = header + UIStates.loadingHTML();

    var data = null;
    try {
      var r = await fetch('/api/athletes/' + userId + '/run-personal-records');
      if (r.ok) data = await r.json();
    } catch (_) { data = null; }

    var speed = data && data.speedRecords && !data.speedRecords.reason ? data.speedRecords : null;
    var tiles = PR_TILES
      .map(function (t) { return { label: t.label, rec: speed ? speed[t.key] : null }; })
      .filter(function (t) { return t.rec && t.rec.value != null; });

    var loadingEl = card.querySelector('.ui-loading');
    if (loadingEl) loadingEl.remove();

    if (!tiles.length) {
      var emptyEl = document.createElement('div');
      emptyEl.className = 'perf-empty';
      emptyEl.innerHTML = '<a href="/log#performance">Set your personal records &#8594;</a>';
      card.appendChild(emptyEl);
      return;
    }

    var grid = document.createElement('div');
    grid.className = 'pr-grid';
    grid.innerHTML = tiles.map(function (t) {
      return '<div class="pr-tile">' +
        '<div class="pr-lbl">' + esc(t.label) + '</div>' +
        '<div class="pr-val">' + esc(formatRunPrValue(t.rec.value)) + '</div>' +
        '<div class="pr-date">' + esc(t.rec.date || '—') + '</div>' +
      '</div>';
    }).join('');
    card.appendChild(grid);
  }


  /* Recent workouts are now rendered by home-readiness-training-sleep.js's
     renderNextWorkoutCard, which owns the whole merged "Next + Recent" card so
     it can budget Next vs Recent rows against one shared capacity (see
     _nwFill / _nwFillCounts there). home.js passes summary.recent_workouts in
     via HomeRTS.render(summary, userId); it no longer fills the section here. */

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

  /* ---- Race goal card (issue #1501) ---- */

  var _GOAL_DISTANCE_LABELS = {
    '5k': '5K',
    '10k': '10K',
    'half': 'Half Marathon',
    'marathon': 'Marathon'
  };

  function _fmtGoalTime(secs) {
    var h = Math.floor(secs / 3600);
    var m = Math.floor((secs % 3600) / 60);
    var s = secs % 60;
    if (h > 0) return h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    return m + ':' + String(s).padStart(2, '0');
  }

  function _fmtGoalDate(isoDate) {
    var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    var parts = isoDate.split('-');
    return months[parseInt(parts[1], 10) - 1] + ' ' + parts[0];
  }

  function _parseGoalTime(timeStr) {
    var parts = timeStr.trim().split(':');
    if (parts.length === 3) {
      var h = parseInt(parts[0], 10);
      var m = parseInt(parts[1], 10);
      var s = parseInt(parts[2], 10);
      if (isNaN(h) || isNaN(m) || isNaN(s)) return null;
      return h * 3600 + m * 60 + s;
    }
    if (parts.length === 2) {
      var m2 = parseInt(parts[0], 10);
      var s2 = parseInt(parts[1], 10);
      if (isNaN(m2) || isNaN(s2)) return null;
      return m2 * 60 + s2;
    }
    return null;
  }

  function _goalCardHead() {
    return '<div class="card-head"><div class="ttl"><i class="ti ti-flag-2" style="color:#5a8dee;font-size:16px;"></i>Race goal</div></div>';
  }

  function _showGoalPrompt(card) {
    card.innerHTML =
      _goalCardHead() +
      '<div class="goal-card__prompt">' +
        '<div class="goal-card__sub">Tell the coach what you\'re training for.</div>' +
        '<button type="button" class="goal-card__cta" id="goal-cta-btn">Set your goal &#8594;</button>' +
      '</div>';

    card.querySelector('#goal-cta-btn').addEventListener('click', function () {
      _showGoalForm(card, null);
    });
  }

  function _showGoalForm(card, existingGoal) {
    var timeVal = existingGoal ? _fmtGoalTime(existingGoal.target_time) : '';
    var dateVal = existingGoal ? existingGoal.race_date : '';
    var distVal = existingGoal ? existingGoal.race_distance : '';

    card.innerHTML =
      _goalCardHead() +
      '<form id="goal-form" class="goal-form" autocomplete="off">' +
        '<div class="goal-form__field">' +
          '<label class="goal-form__label" for="goal-distance">Distance</label>' +
          '<select id="goal-distance" class="goal-form__select">' +
            '<option value="">Choose distance…</option>' +
            '<option value="5k"' + (distVal === '5k' ? ' selected' : '') + '>5K</option>' +
            '<option value="10k"' + (distVal === '10k' ? ' selected' : '') + '>10K</option>' +
            '<option value="half"' + (distVal === 'half' ? ' selected' : '') + '>Half Marathon</option>' +
            '<option value="marathon"' + (distVal === 'marathon' ? ' selected' : '') + '>Marathon</option>' +
          '</select>' +
        '</div>' +
        '<div class="goal-form__field">' +
          '<label class="goal-form__label" for="goal-time">Target time (H:MM:SS or M:SS)</label>' +
          '<input id="goal-time" class="goal-form__input" type="text"' +
            ' placeholder="1:45:00" value="' + esc(timeVal) + '">' +
        '</div>' +
        '<div class="goal-form__field">' +
          '<label class="goal-form__label" for="goal-date">Race date</label>' +
          '<input id="goal-date" class="goal-form__input" type="date" value="' + esc(dateVal) + '">' +
        '</div>' +
        '<div class="goal-form__err" id="goal-form-err"></div>' +
        '<div class="goal-form__actions">' +
          '<button type="submit" class="goal-form__submit" id="goal-submit">Save goal</button>' +
          '<button type="button" class="goal-form__cancel" id="goal-cancel">Cancel</button>' +
        '</div>' +
      '</form>';

    var errEl = card.querySelector('#goal-form-err');
    var submitBtn = card.querySelector('#goal-submit');

    card.querySelector('#goal-cancel').addEventListener('click', function () {
      if (existingGoal) {
        _showGoalDisplay(card, existingGoal);
      } else {
        _showGoalPrompt(card);
      }
    });

    card.querySelector('#goal-form').addEventListener('submit', async function (e) {
      e.preventDefault();
      var distance = card.querySelector('#goal-distance').value;
      var timeStr = (card.querySelector('#goal-time').value || '').trim();
      var dateStr = card.querySelector('#goal-date').value;

      errEl.textContent = '';
      if (!distance) { errEl.textContent = 'Please choose a distance.'; return; }
      var secs = _parseGoalTime(timeStr);
      if (!secs || secs <= 0) { errEl.textContent = 'Enter target time as H:MM:SS (e.g. 1:45:00).'; return; }
      if (!dateStr) { errEl.textContent = 'Please enter the race date.'; return; }

      submitBtn.disabled = true;
      submitBtn.textContent = 'Saving…';

      try {
        var res = await fetch('/api/coach/goal', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ race_distance: distance, target_time: secs, race_date: dateStr })
        });
        var body = await res.json();
        if (res.ok) {
          _showGoalDisplay(card, body);
        } else {
          var detail = body.detail;
          if (Array.isArray(detail)) {
            errEl.textContent = detail.map(function (d) { return d.msg || JSON.stringify(d); }).join('; ');
          } else {
            errEl.textContent = typeof detail === 'string' ? detail : 'Save failed (' + res.status + ')';
          }
          submitBtn.disabled = false;
          submitBtn.textContent = 'Save goal';
        }
      } catch (_) {
        errEl.textContent = 'Network error — try again';
        submitBtn.disabled = false;
        submitBtn.textContent = 'Save goal';
      }
    });
  }

  function _showGoalDisplay(card, goal) {
    var distLabel = _GOAL_DISTANCE_LABELS[goal.race_distance] || goal.race_distance;
    var timeLabel = _fmtGoalTime(goal.target_time);
    var dateLabel = _fmtGoalDate(goal.race_date);

    card.innerHTML =
      _goalCardHead() +
      '<div class="goal-display">' +
        '<div class="goal-display__main">' +
          '<div class="goal-display__title">' + esc(distLabel) + '</div>' +
          '<div class="goal-display__sub">' + esc(timeLabel) + ' · ' + esc(dateLabel) + '</div>' +
        '</div>' +
        '<button type="button" class="goal-display__edit" id="goal-edit-btn" aria-label="Edit race goal">' +
          '<i class="ti ti-pencil" aria-hidden="true"></i> Edit' +
        '</button>' +
      '</div>';

    card.querySelector('#goal-edit-btn').addEventListener('click', function () {
      _showGoalForm(card, goal);
    });
  }

  async function _renderGoalCard() {
    var card = document.getElementById('home-goal-card');
    if (!card) return;
    if (window.UIStates) card.innerHTML = UIStates.loadingHTML();

    var data = null;
    try {
      var r = await fetch('/api/coach/goal');
      if (r.ok) data = await r.json();
    } catch (_) {}

    if (!data || data.goal === null) {
      _showGoalPrompt(card);
    } else {
      _showGoalDisplay(card, data.goal);
    }
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

      /* Personal records card (fetches its own data — see loadPerformanceCard) */
      loadPerformanceCard(userId);

      /* Recent workouts are rendered inside the merged Next+Recent card by
         HomeRTS.render (called just above with summary.recent_workouts). */

      initFastLogForm(userId);

      /* Race goal card (issue #1501) */
      _renderGoalCard();

    }
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
