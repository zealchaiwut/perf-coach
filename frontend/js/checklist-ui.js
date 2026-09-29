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

  function _buildStatusHtml(st, opts) {
    opts = opts || {};
    if (!st) return '';
    var lab = st.status === 'updating' ? 'Updating plan…' :
      st.status === 'up_to_date' ? 'Up to date' : (st.status || '—');
    var sub = st.last_built_at ? 'Last built ' + esc(String(st.last_built_at).slice(0, 16)) : '';
    var cls = 'cl-build-status cl-build-' + esc(st.status || 'unknown') +
      (opts.light ? ' cl-build-status--light' : '');
    return (
      '<div class="' + cls + '">' +
        '<span class="cl-build-lab">' + esc(lab) + '</span>' +
        (sub ? '<span class="cl-build-sub">' + sub + '</span>' : '') +
      '</div>'
    );
  }

  function _raceStripHtml(aRace, opts) {
    opts = opts || {};
    if (!aRace || !aRace.name) return '';
    var date = aRace.race_date ? esc(aRace.race_date) : '';
    var cls = 'cl-race-strip' + (opts.light ? ' cl-race-strip--light' : '');
    return (
      '<div class="' + cls + '">' +
        '<i class="ti ti-flag-2"></i>' +
        '<span>This week serves the A race · <strong>' + esc(aRace.name) + '</strong>' +
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
    if (!data || !data.checklist_enabled) {
      host.innerHTML = '';
      host.hidden = true;
      return;
    }
    host.hidden = false;
    host.innerHTML =
      _raceStripHtml(data.a_race, { light: true }) +
      _buildStatusHtml(data.build_status, { light: true });
  }

  function _planColCell(label, sub, state, role) {
    if (!label) {
      return '<div class="cl-plan-col cl-plan-col--empty"><span class="cl-plan-col-k">—</span></div>';
    }
    var cls = _stateClass(state, role);
    return (
      '<div class="cl-plan-col ' + cls + '">' +
        '<span class="cl-plan-col-k">' + esc(label) + '</span>' +
        (sub ? '<span class="cl-plan-col-s">' + esc(sub) + '</span>' : '') +
      '</div>'
    );
  }

  function _planDayChip(dayData, today, raceDates) {
    if (!dayData || !dayData.date) return '';
    if (dayData.date === today) return 'TODAY';
    if (raceDates && raceDates.indexOf(dayData.date) >= 0) return 'RACE DAY';
    if (dayData.date > today) return 'PLANNED';
    return '';
  }

  function renderPlanWeekHeader(host) {
    if (!host) return;
    var list = host.querySelector('#plan-week-list');
    if (!list) return;
    var hdr = host.querySelector('.cl-plan-week-hdr');
    if (!hdr) {
      hdr = document.createElement('div');
      hdr.className = 'cl-plan-week-hdr';
      hdr.innerHTML =
        '<span class="cl-plan-week-hdr-gut"></span>' +
        '<span class="cl-plan-week-hdr-cols">' +
          '<span>Session</span><span>Mobility</span><span>Fuel</span>' +
        '</span>';
      list.parentNode.insertBefore(hdr, list);
    }
    hdr.hidden = false;
  }

  function hidePlanWeekHeader(host) {
    if (!host) return;
    var hdr = host.querySelector('.cl-plan-week-hdr');
    if (hdr) hdr.hidden = true;
  }

  function renderPlanDayExtras(dayEl, dayData, ctx) {
    if (!dayEl || !dayData) return;
    ctx = ctx || {};
    var today = ctx.today || _todayISO();
    var raceDates = ctx.raceDates || [];
    var chipLab = _planDayChip(dayData, today, raceDates);
    var gut = dayEl.querySelector('.pl-gut');
    if (gut) {
      var chip = gut.querySelector('.cl-day-chip');
      if (chipLab) {
        if (!chip) {
          chip = document.createElement('span');
          chip.className = 'cl-day-chip';
          gut.appendChild(chip);
        }
        chip.textContent = chipLab;
        chip.className = 'cl-day-chip cl-day-chip--' + chipLab.toLowerCase().replace(/\s+/g, '-');
      } else if (chip) {
        chip.remove();
      }
    }

    var items = dayData.items || [];
    var sessionItem = items.find(function (it) {
      return it.kind === 'planned_session' && (it.session_type || '').toLowerCase() !== 'mobility';
    });
    var mobilityItem = items.find(function (it) {
      return it.kind === 'planned_session' && (it.session_type || '').toLowerCase() === 'mobility';
    });
    var fuelItem = items.find(function (it) { return it.kind === 'fuel'; });
    var ribbon = dayData.ribbon || {};

    if (!sessionItem && ribbon.label && ribbon.session_type !== 'rest') {
      sessionItem = {
        label: ribbon.label,
        state: ribbon.core_done >= ribbon.core_total && ribbon.core_total > 0 ? 'done' : 'pending',
        role: 'core',
      };
    }

    var sessionSub = sessionItem && sessionItem.state ? sessionItem.state.replace(/_/g, ' ') : '';
    var mobSub = mobilityItem && mobilityItem.state ? mobilityItem.state.replace(/_/g, ' ') : '';
    var fuelType = fuelItem && fuelItem.fuel && fuelItem.fuel.day_type
      ? String(fuelItem.fuel.day_type).replace(/_/g, ' ')
      : (fuelItem ? fuelItem.label.replace(/^Fuel ·\s*/i, '') : '');

    var box = dayEl.querySelector('.cl-plan-cols');
    if (!box) {
      box = document.createElement('div');
      box.className = 'cl-plan-cols';
      dayEl.appendChild(box);
    }
    box.innerHTML =
      _planColCell(sessionItem ? sessionItem.label : (ribbon.label === 'Rest' ? 'Rest' : ''), sessionSub, sessionItem && sessionItem.state, sessionItem && sessionItem.role) +
      _planColCell(mobilityItem ? mobilityItem.label : '', mobSub, mobilityItem && mobilityItem.state, mobilityItem && mobilityItem.role) +
      _planColCell(fuelType ? 'Fuel' : '', fuelType, fuelItem && fuelItem.state, fuelItem && fuelItem.role);
  }

  function renderWhatMoves(host, items, opts) {
    opts = opts || {};
    if (!host) return;
    if (!items || !items.length) {
      host.hidden = true;
      host.innerHTML = '';
      return;
    }
    host.hidden = false;
    host.classList.remove('cl-hidden');
    var title = opts.title || 'What moves the estimate';
    host.innerHTML =
      '<h2 class="pm-sectitle pm-sectitle--plain">' + esc(title) + '</h2>' +
      items.map(function (ev) {
        var habit = ev.habit
          ? '<span class="cl-evidence-habit">' + esc(String(ev.habit).replace(/_/g, ' ')) + '</span>'
          : '';
        return '<div class="cl-evidence-row">' + habit + esc(ev.sentence || '') + '</div>';
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

  function showChecklistError(host, message) {
    if (!host) return;
    host.hidden = false;
    host.removeAttribute('aria-busy');
    host.innerHTML =
      '<div class="clh-page clh-page--error" role="alert">' +
        '<p class="clh-error-title">Could not load checklist</p>' +
        '<p class="clh-error-msg">' + esc(message || 'Try refreshing the page.') + '</p>' +
        '<button type="button" class="clh-error-retry">Try again</button>' +
      '</div>';
    var btn = host.querySelector('.clh-error-retry');
    if (btn) {
      btn.addEventListener('click', function () {
        if (window.HabitsPage && typeof window.HabitsPage.loadAndRender === 'function') {
          window.HabitsPage.loadAndRender();
        } else {
          window.location.reload();
        }
      });
    }
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
    renderPlanWeekHeader: renderPlanWeekHeader,
    hidePlanWeekHeader: hidePlanWeekHeader,
    renderPlanDayExtras: renderPlanDayExtras,
    renderWhatMoves: renderWhatMoves,
    renderHomeWeekPlan: renderHomeWeekPlan,
    showChecklistLoading: showChecklistLoading,
    hideLegacyHabits: hideLegacyHabits,
    showChecklistError: showChecklistError,
    raceStripHtml: _raceStripHtml,
    stateClass: _stateClass,
  };

  if (document.body.classList.contains('habits-checklist-first')) {
    var bootRoot = document.getElementById('checklist-root');
    if (bootRoot) showChecklistLoading(bootRoot);
  }
})();
