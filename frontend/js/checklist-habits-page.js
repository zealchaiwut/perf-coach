/**
 * Habits weekly checklist page shell (WC-23) — mock layout: header, week ribbon,
 * selected-day panel (stub), sidebar stubs. Data from GET /api/checklist/week.
 */
(function () {
  'use strict';

  var DOW_SHORT = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  function _todayISO() {
    return window.AppCommon.todayISO();
  }

  function _fmtRange(weekStart, weekEnd) {
    if (!weekStart) return '';
    var a = new Date(weekStart + 'T12:00:00');
    var b = weekEnd ? new Date(weekEnd + 'T12:00:00') : a;
    var mo = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    if (a.getMonth() === b.getMonth()) {
      return a.getDate() + ' ' + mo[a.getMonth()] + ' – ' + b.getDate() + ' ' + mo[b.getMonth()];
    }
    return a.getDate() + ' ' + mo[a.getMonth()] + ' – ' + b.getDate() + ' ' + mo[b.getMonth()];
  }

  function _fmtDayTitle(iso) {
    var d = new Date(iso + 'T12:00:00');
    var mo = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
    return DOW_SHORT[(d.getDay() + 6) % 7] + 'day ' + d.getDate() + ' ' + mo[d.getMonth()];
  }

  function _ribbonAccent(sessionType) {
    var t = (sessionType || 'rest').toLowerCase();
    if (t === 'run') return 'run';
    if (t === 'strength') return 'lift';
    if (t === 'mobility') return 'mobility';
    if (t === 'rest') return 'rest';
    return 'other';
  }

  function _racePillHtml(race, variant) {
    if (!race || !race.name) return '';
    var bits = [esc(race.name)];
    if (race.race_date) {
      var d = new Date(race.race_date + 'T12:00:00');
      bits.push(DOW_SHORT[(d.getDay() + 6) % 7]);
    }
    if (variant === 'a' && race.goal_time_seconds) {
      var s = race.goal_time_seconds;
      var h = Math.floor(s / 3600);
      var m = Math.floor((s % 3600) / 60);
      bits.push('goal ' + (h ? h + ':' + String(m).padStart(2, '0') : m + ' min'));
    }
    return '<span class="clh-pill clh-pill--' + variant + '">' + bits.join(' · ') + '</span>';
  }

  function _headerHtml(data) {
    var rh = data.races_header || {};
    var aRace = rh.a_race || data.a_race;
    var bRace = rh.b_race;
    var aPill = '';
    if (aRace && aRace.name) {
      var bits = [esc(aRace.name)];
      if (aRace.race_date) {
        var today = new Date(_todayISO() + 'T00:00:00');
        var rd = new Date(aRace.race_date + 'T00:00:00');
        var diff = Math.round((rd - today) / 86400000);
        if (diff >= 0) bits.push(diff + ' days');
      }
      if (aRace.goal_time_seconds) bits.push('goal ' + esc(_fmtGoal(aRace.goal_time_seconds)));
      aPill = '<span class="clh-pill clh-pill--a-meta">' + bits.join(' · ') + '</span>';
    }
    return (
      '<header class="clh-header">' +
        '<div class="clh-header-left">' +
          '<div class="clh-kicker">Habits · Week ' + esc(String(data.week_number || '')) + '</div>' +
          '<h1 class="clh-title">' + esc(_fmtRange(data.week_start, data.week_end)) + '</h1>' +
          '<p class="clh-sub">Built from this week\'s Plan</p>' +
        '</div>' +
        '<div class="clh-header-right">' +
          _racePillHtml(bRace, 'b') +
          aPill +
          '<a href="/settings" class="clh-settings" title="Checklist settings"><i class="ti ti-settings"></i></a>' +
        '</div>' +
      '</header>'
    );
  }

  function _fmtGoal(secs) {
    secs = Math.round(secs);
    var h = Math.floor(secs / 3600);
    var m = Math.floor((secs % 3600) / 60);
    var s = secs % 60;
    if (h > 0) return h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    return m + ':' + String(s).padStart(2, '0');
  }

  function _ribbonHtml(days, selectedDate, today) {
    return (
      '<div class="clh-ribbon" role="tablist" aria-label="Week days">' +
        (days || []).map(function (day) {
          var rb = day.ribbon || {};
          var accent = _ribbonAccent(rb.session_type);
          var isSel = day.date === selectedDate;
          var isToday = day.date === today;
          var d = new Date(day.date + 'T12:00:00');
          var score = day.score || { core_done: 0, core_total: 0 };
          return (
            '<button type="button" class="clh-day' +
              (isSel ? ' clh-day--selected' : '') +
              (isToday ? ' clh-day--today' : '') + '"' +
              ' role="tab" aria-selected="' + (isSel ? 'true' : 'false') + '"' +
              ' data-date="' + esc(day.date) + '">' +
              '<span class="clh-day-accent clh-day-accent--' + accent + '"></span>' +
              '<span class="clh-day-top">' +
                '<span class="clh-day-dow">' + esc(DOW_SHORT[day.day_offset] || DOW_SHORT[(d.getDay() + 6) % 7]) + '</span>' +
                '<span class="clh-day-num">' + d.getDate() + '</span>' +
              '</span>' +
              '<span class="clh-day-sess">' + esc(rb.label || 'Rest') + '</span>' +
              (score.core_total
                ? '<span class="clh-day-score">' + score.core_done + '/' + score.core_total + ' core</span>'
                : '') +
            '</button>'
          );
        }).join('') +
      '</div>'
    );
  }

  function _dayPanelHtml(day) {
    if (!day) {
      return '<div class="clh-panel clh-panel--day"><p class="clh-empty">Select a day</p></div>';
    }
    var score = day.score || { core_done: 0, core_total: 0 };
    var optionalDone = (day.items || []).filter(function (it) {
      return it.role === 'optional' && it.state === 'done';
    }).length;
    var optionalTotal = (day.items || []).filter(function (it) {
      return it.role === 'optional' && it.kind !== 'fuel';
    }).length;
    var pct = score.core_total ? Math.round((score.core_done / score.core_total) * 100) : 0;

    return (
      '<div class="clh-panel clh-panel--day">' +
        '<div class="clh-day-hdr">' +
          '<div>' +
            '<h2 class="clh-day-title">' + esc(_fmtDayTitle(day.date)) + '</h2>' +
            '<p class="clh-day-meta">Core ' + score.core_done + ' of ' + score.core_total +
              ' · optional ' + optionalDone + ' of ' + optionalTotal + '</p>' +
          '</div>' +
        '</div>' +
        '<div class="clh-progress"><div class="clh-progress-fill" style="width:' + pct + '%"></div></div>' +
        '<p class="clh-slice-note">Day detail (core rows, session card, fuel boxes) — slice B</p>' +
        '<div class="clh-day-preview">' +
          (day.items || []).filter(function (it) { return it.kind !== 'fuel'; }).slice(0, 8).map(function (it) {
            return '<div class="clh-preview-row">' +
              '<span class="clh-preview-state clh-preview-state--' + esc(it.state) + '"></span>' +
              '<span>' + esc(it.label) + '</span></div>';
          }).join('') +
        '</div>' +
      '</div>'
    );
  }

  function _sidebarHtml(data) {
    var st = data.build_status || {};
    var stLab = st.status === 'up_to_date' ? 'Up to date'
      : st.status === 'updating' ? 'Updating'
      : (st.status || '—');
    var stCls = st.status === 'up_to_date' ? 'ok' : st.status === 'updating' ? 'warn' : 'muted';
    return (
      '<aside class="clh-sidebar">' +
        '<div class="clh-panel clh-panel--sidebar">' +
          '<h3 class="clh-side-title">Week at a glance</h3>' +
          '<p class="clh-slice-note">Habit × day matrix — slice B</p>' +
        '</div>' +
        '<div class="clh-panel clh-panel--sidebar">' +
          '<div class="clh-side-hdr">' +
            '<h3 class="clh-side-title">What moves ' +
              esc((data.a_race && data.a_race.name) ? data.a_race.name.split(/\s+\d/)[0].trim() : 'your race') +
            '</h3>' +
            '<a href="/log#performance" class="clh-side-link">Performance →</a>' +
          '</div>' +
          ((data.what_moves_estimate || []).slice(0, 3).map(function (ev) {
            return '<p class="clh-evidence">' + esc(ev.sentence || '') + '</p>';
          }).join('') || '<p class="clh-slice-note">No evidence yet</p>') +
        '</div>' +
        '<div class="clh-panel clh-panel--sidebar clh-panel--build">' +
          '<span class="clh-build-badge clh-build-badge--' + stCls + '">' + esc(stLab) + '</span>' +
          '<h3 class="clh-side-title">Checklist build</h3>' +
          (st.last_built_at
            ? '<p class="clh-build-sub">Built ' + esc(String(st.last_built_at).slice(0, 16)) + '</p>'
            : '<p class="clh-build-sub">Plan checklist from this week\'s sessions + habits.</p>') +
          '<a href="/settings" class="clh-manage">Manage →</a>' +
        '</div>' +
      '</aside>'
    );
  }

  function render(host, data, opts) {
    if (!host || !data) return;
    opts = opts || {};
    var today = _todayISO();
    var selected = opts.selectedDate || today;
    var days = data.days || [];
    if (!days.find(function (d) { return d.date === selected; })) {
      selected = days.length ? days[0].date : today;
    }
    var day = days.find(function (d) { return d.date === selected; });

    host.hidden = false;
    host.innerHTML =
      '<div class="clh-page">' +
        _headerHtml(data) +
        _ribbonHtml(days, selected, today) +
        '<div class="clh-body">' +
          _dayPanelHtml(day) +
          _sidebarHtml(data) +
        '</div>' +
      '</div>';

    host.querySelectorAll('.clh-day').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var dt = btn.getAttribute('data-date');
        if (!dt || dt === selected) return;
        render(host, data, Object.assign({}, opts, { selectedDate: dt }));
      });
    });
  }

  window.ChecklistHabitsPage = { render: render };
})();
