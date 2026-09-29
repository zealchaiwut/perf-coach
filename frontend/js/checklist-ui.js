/**
 * Weekly checklist UI (WC-14..WC-20) — read model from GET /api/checklist/week.
 * Ticks POST to the owning endpoint (planned session / habit log); no local store.
 */
(function () {
  'use strict';

  var DOW = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  function _todayISO() {
    return window.AppCommon.todayISO();
  }

  function _stateClass(state, role) {
    if (state === 'done') return 'cl-done';
    if (state === 'missed') return 'cl-missed';
    if (state === 'skipped') return 'cl-skipped';
    if (state === 'shown') return 'cl-shown';
    if (state === 'upcoming') return 'cl-upcoming';
    if (role === 'optional') return 'cl-optional';
    return 'cl-pending';
  }

  function _stateIcon(state) {
    if (state === 'done') return '<i class="ti ti-check"></i>';
    if (state === 'missed') return '<i class="ti ti-x"></i>';
    if (state === 'skipped') return '<span class="cl-skip-lab">skip</span>';
    return '';
  }

  async function fetchWeek(weekStart) {
    var url = weekStart ? '/api/checklist/week?week_start=' + encodeURIComponent(weekStart) : '/api/checklist/week';
    var res = await fetch(url);
    if (!res.ok) throw new Error('checklist ' + res.status);
    return res.json();
  }

  async function tickItem(item, opts) {
    opts = opts || {};
    if (!item || !item.tick) return false;
    var t = item.tick;
    var url = opts.skip ? t.skip_url : t.url;
    if (!url) return false;
    var init = { method: t.method || 'POST', credentials: 'same-origin' };
    if (t.body) {
      init.headers = { 'Content-Type': 'application/json' };
      init.body = JSON.stringify(t.body);
    }
    var res = await fetch(url, init);
    return res.ok;
  }

  function _buildStatusHtml(st) {
    if (!st) return '';
    var lab = st.status === 'updating' ? 'Updating plan…' :
      st.status === 'up_to_date' ? 'Up to date' : (st.status || '—');
    var sub = st.last_built_at ? 'Last built ' + esc(String(st.last_built_at).slice(0, 16)) : '';
    return (
      '<div class="cl-build-status cl-build-' + esc(st.status || 'unknown') + '">' +
        '<span class="cl-build-lab">' + esc(lab) + '</span>' +
        (sub ? '<span class="cl-build-sub">' + sub + '</span>' : '') +
      '</div>'
    );
  }

  function _raceStripHtml(aRace) {
    if (!aRace || !aRace.name) return '';
    var date = aRace.race_date ? esc(aRace.race_date) : '';
    return (
      '<div class="cl-race-strip">' +
        '<i class="ti ti-flag-2"></i>' +
        '<span>This week serves <strong>' + esc(aRace.name) + '</strong>' +
        (date ? ' · ' + date : '') + '</span>' +
      '</div>'
    );
  }

  function _whatMovesHtml(items) {
    if (!items || !items.length) return '';
    return (
      '<div class="card cl-what-moves">' +
        '<h2 class="cl-card-title">What moves the A-race estimate</h2>' +
        items.map(function (ev) {
          return '<div class="cl-evidence-row">' + esc(ev.sentence || '') + '</div>';
        }).join('') +
      '</div>'
    );
  }

  function _fuelCardHtml(fuelWeek) {
    if (!fuelWeek) return '';
    var phase = fuelWeek.week_phase ? esc(String(fuelWeek.week_phase)) : '';
    var reason = fuelWeek.week_phase_reason ? esc(String(fuelWeek.week_phase_reason)) : '';
    return (
      '<div class="card cl-fuel-card">' +
        '<h2 class="cl-card-title">Fuel this week</h2>' +
        (phase ? '<div class="cl-fuel-phase">' + phase + '</div>' : '') +
        (reason ? '<div class="cl-fuel-reason">' + reason + '</div>' : '') +
        '<p class="cl-fuel-note">Targets are shown per day — fuel is never ticked.</p>' +
      '</div>'
    );
  }

  function _dayScoreHtml(score) {
    if (!score) return '';
    return esc(String(score.core_done)) + '/' + esc(String(score.core_total)) + ' core';
  }

  function _itemRowHtml(item, dayDate) {
    var cls = _stateClass(item.state, item.role);
    var tickable = !!(item.tick && item.state !== 'done' && item.state !== 'shown');
    var link = item.link ? ' href="' + esc(item.link) + '"' : '';
    var tag = item.role === 'optional' ? '<span class="cl-role-tag">optional</span>' : '';
    var fuelMeta = '';
    if (item.kind === 'fuel' && item.fuel) {
      var b = item.fuel.budget;
      fuelMeta = b && b.carbs_g != null
        ? '<span class="cl-fuel-meta">' + Math.round(b.carbs_g) + 'g carbs</span>'
        : '';
    }
    var prog = '';
    if (item.weekly_progress) {
      prog = '<span class="cl-week-prog">' +
        Math.round(item.weekly_progress.value) + '/' +
        Math.round(item.weekly_progress.target) + '</span>';
    }
    return (
      '<div class="cl-item ' + cls + '" data-kind="' + esc(item.kind) + '" data-id="' + esc(item.id) + '"' +
        ' data-date="' + esc(dayDate) + '">' +
        (tickable
          ? '<button type="button" class="cl-tick" aria-label="Mark done">' + _stateIcon(item.state) + '</button>'
          : '<span class="cl-tick cl-tick--static">' + _stateIcon(item.state) + '</span>') +
        '<a class="cl-label"' + link + '>' + esc(item.label) + tag + prog + fuelMeta + '</a>' +
        (item.tick && item.tick.skip_url && item.state === 'pending'
          ? '<button type="button" class="cl-skip-btn">Skip</button>' : '') +
      '</div>'
    );
  }

  function _dayBlockHtml(day, today) {
    var isToday = day.date === today;
    var core = (day.items || []).filter(function (it) { return it.role === 'core' && it.kind !== 'fuel'; });
    var optional = (day.items || []).filter(function (it) { return it.role === 'optional'; });
    var fuel = (day.items || []).filter(function (it) { return it.kind === 'fuel'; });
    function rows(items) {
      return items.map(function (it) { return _itemRowHtml(it, day.date); }).join('');
    }
    return (
      '<div class="cl-day' + (isToday ? ' cl-day--today' : '') + '" data-date="' + esc(day.date) + '">' +
        '<div class="cl-day-hdr">' +
          '<span class="cl-dow">' + esc(DOW[day.day_offset] || '') + '</span>' +
          '<span class="cl-date">' + esc(day.date.slice(5)) + '</span>' +
          '<span class="cl-score">' + _dayScoreHtml(day.score) + '</span>' +
        '</div>' +
        '<div class="cl-day-items">' + rows(core) + rows(optional) + rows(fuel) + '</div>' +
      '</div>'
    );
  }

  function _wireTicks(host, onRefresh) {
    if (!host) return;
    host.querySelectorAll('.cl-tick:not(.cl-tick--static)').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        var row = btn.closest('.cl-item');
        if (!row) return;
        var id = row.getAttribute('data-id');
        var date = row.getAttribute('data-date');
        var day = (_cache && _cache.days || []).find(function (d) { return d.date === date; });
        var item = day && (day.items || []).find(function (it) { return it.id === id; });
        if (!item) return;
        btn.disabled = true;
        try {
          var ok = await tickItem(item);
          if (ok && typeof onRefresh === 'function') await onRefresh();
        } finally {
          btn.disabled = false;
        }
      });
    });
    host.querySelectorAll('.cl-skip-btn').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        var row = btn.closest('.cl-item');
        if (!row) return;
        var id = row.getAttribute('data-id');
        var date = row.getAttribute('data-date');
        var day = (_cache && _cache.days || []).find(function (d) { return d.date === date; });
        var item = day && (day.items || []).find(function (it) { return it.id === id; });
        if (!item) return;
        btn.disabled = true;
        try {
          var ok = await tickItem(item, { skip: true });
          if (ok && typeof onRefresh === 'function') await onRefresh();
        } finally {
          btn.disabled = false;
        }
      });
    });
  }

  var _cache = null;

  function renderHabitsPage(host, data, opts) {
    if (!host || !data) return;
    host.removeAttribute('aria-busy');
    _cache = data;
    opts = opts || {};
    if (window.ChecklistHabitsPage && typeof window.ChecklistHabitsPage.render === 'function') {
      window.ChecklistHabitsPage.render(host, data, opts);
      return;
    }
    var today = _todayISO();
    var weekLabel = data.week_start ? 'Week of ' + data.week_start : 'This week';
    host.hidden = false;
    host.innerHTML =
      _raceStripHtml(data.a_race) +
      _buildStatusHtml(data.build_status) +
      '<div class="cl-habits-toolbar">' +
        '<span class="cl-week-label">' + esc(weekLabel) + '</span>' +
        '<button type="button" class="cl-manage-btn" data-open-checklist-settings title="Manage checklist"><i class="ti ti-settings"></i> Manage</button>' +
      '</div>' +
      '<div class="cl-days-grid">' +
        (data.days || []).map(function (d) { return _dayBlockHtml(d, today); }).join('') +
      '</div>' +
      _fuelCardHtml(data.fuel_week) +
      _whatMovesHtml(data.what_moves_estimate);

    _wireTicks(host, opts.onRefresh);
  }

  function renderPlanStrip(host, data) {
    if (!host) return;
    host.innerHTML = _raceStripHtml(data && data.a_race) + _buildStatusHtml(data && data.build_status);
  }

  function renderPlanDayExtras(dayEl, dayData) {
    if (!dayEl || !dayData || !dayData.items) return;
    var extras = dayData.items.filter(function (it) {
      return it.kind === 'mobility' || it.kind === 'fuel' ||
        (it.kind === 'planned_session' && it.session_type === 'mobility');
    });
    if (!extras.length) return;
    var box = dayEl.querySelector('.cl-plan-extras');
    if (!box) {
      box = document.createElement('div');
      box.className = 'cl-plan-extras';
      dayEl.appendChild(box);
    }
    box.innerHTML = extras.map(function (it) {
      var cls = _stateClass(it.state, it.role);
      return '<span class="cl-plan-chip ' + cls + '">' + esc(it.label) + '</span>';
    }).join('');
  }

  function renderWhatMoves(host, items) {
    if (!host) return;
    if (!items || !items.length) {
      host.hidden = true;
      host.innerHTML = '';
      return;
    }
    host.hidden = false;
    host.innerHTML =
      '<h2 class="pm-sectitle pm-sectitle--plain">What moves the estimate</h2>' +
      items.map(function (ev) {
        return '<div class="cl-evidence-row">' + esc(ev.sentence || '') + '</div>';
      }).join('');
  }

  function renderHomeWeekPlan(host, data) {
    if (!host || !data || !data.days) return;
    var today = _todayISO();
    var todayDay = data.days.find(function (d) { return d.date === today; });
    if (!todayDay) return;
    var core = (todayDay.items || []).filter(function (it) {
      return it.role === 'core' && it.kind !== 'fuel';
    });
    var done = core.filter(function (it) { return it.state === 'done'; }).length;
    var html = '<div class="cl-home-teaser">' +
      '<span class="cl-home-score">' + done + '/' + core.length + ' core today</span>';
    core.slice(0, 4).forEach(function (it) {
      html += '<span class="cl-home-chip ' + _stateClass(it.state, it.role) + '">' + esc(it.label) + '</span>';
    });
    html += '<a href="/habits" class="cl-home-link">Checklist →</a></div>';
    host.insertAdjacentHTML('beforeend', html);
  }

  function showChecklistLoading(host) {
    if (!host) return;
    host.hidden = false;
    host.setAttribute('aria-busy', 'true');
    var daySkels = '';
    for (var i = 0; i < 7; i++) daySkels += '<div class="clh-skel clh-skel--day"></div>';
    host.innerHTML =
      '<div class="clh-page clh-page--loading">' +
        '<div class="clh-loading-hdr">' +
          '<div class="clh-skel clh-skel--title"></div>' +
          '<div class="clh-skel clh-skel--sub"></div>' +
        '</div>' +
        '<div class="clh-loading-ribbon">' + daySkels + '</div>' +
        '<div class="clh-loading-body">' +
          '<div class="clh-skel clh-skel--panel"></div>' +
          '<div class="clh-skel clh-skel--panel clh-skel--narrow"></div>' +
        '</div>' +
      '</div>';
  }

  function hideLegacyHabits() {
    document.body.classList.add('habits-checklist-first');
    ['hero-row', 'habits-day-grid-card', 'weekly-habits-card', 'insights-panel',
      'nudges-panel', 'habits-history-cal', 'habit-evidence', 'starter-section',
      'back-current-wrap'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.style.display = 'none';
    });
    var hdr = document.querySelector('.habits-page-header');
    if (hdr) hdr.style.display = 'none';
    var addBtn = document.getElementById('add-habit-btn');
    if (addBtn) addBtn.style.display = 'none';
    var root = document.getElementById('checklist-root');
    if (root) root.hidden = false;
  }

  function showLegacyHabits() {
    document.body.classList.remove('habits-checklist-first');
    var root = document.getElementById('checklist-root');
    if (root) {
      root.hidden = true;
      root.innerHTML = '';
      root.removeAttribute('aria-busy');
    }
    ['hero-row', 'habits-day-grid-card', 'weekly-habits-card', 'insights-panel',
      'nudges-panel', 'habits-history-cal', 'habit-evidence', 'starter-section',
      'back-current-wrap'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.style.display = '';
    });
    var hdr = document.querySelector('.habits-page-header');
    if (hdr) hdr.style.display = '';
    var addBtn = document.getElementById('add-habit-btn');
    if (addBtn) addBtn.style.display = '';
  }

  function wireItems(host, data, onRefresh) {
    if (data) _cache = data;
    _wireTicks(host, onRefresh);
  }

  window.ChecklistUI = {
    fetchWeek: fetchWeek,
    tickItem: tickItem,
    wireItems: wireItems,
    renderHabitsPage: renderHabitsPage,
    renderPlanStrip: renderPlanStrip,
    renderPlanDayExtras: renderPlanDayExtras,
    renderWhatMoves: renderWhatMoves,
    renderHomeWeekPlan: renderHomeWeekPlan,
    showChecklistLoading: showChecklistLoading,
    hideLegacyHabits: hideLegacyHabits,
    showLegacyHabits: showLegacyHabits,
    raceStripHtml: _raceStripHtml,
    stateClass: _stateClass,
  };

  if (document.body.classList.contains('habits-checklist-first')) {
    var bootRoot = document.getElementById('checklist-root');
    if (bootRoot) showChecklistLoading(bootRoot);
  }
})();
