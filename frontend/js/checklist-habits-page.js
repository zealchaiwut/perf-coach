/**
 * Habits weekly checklist page (WC-23..28) — mock layout from GET /api/checklist/week.
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

  function _itemRowHtml(item, dayDate) {
    if (window.ChecklistShared) {
      return window.ChecklistShared.itemRowHtml(item, dayDate, { showSubtext: true });
    }
    return '<div class="cl-item">' + esc(item.label) + '</div>';
  }

  function _fuelBoxesHtml(fuelDetail, fuelItem) {
    if (window.ChecklistShared) {
      return window.ChecklistShared.fuelBoxesHtml(fuelDetail, fuelItem);
    }
    return '';
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

  function _fmtGoal(secs) {
    secs = Math.round(secs);
    var h = Math.floor(secs / 3600);
    var m = Math.floor((secs % 3600) / 60);
    var s = secs % 60;
    if (h > 0) return h + ':' + String(m).padStart(2, '0') + ':' + String(s).padStart(2, '0');
    return m + ':' + String(s).padStart(2, '0');
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
          '<div class="clh-title-row">' +
            '<h1 class="clh-title">' + esc(_fmtRange(data.week_start, data.week_end)) + '</h1>' +
            '<div class="clh-week-nav">' +
              '<button type="button" class="clh-week-btn" data-week-nav="prev" aria-label="Previous week">‹</button>' +
              '<button type="button" class="clh-week-btn" data-week-nav="next"' +
                (data.is_current_week ? ' disabled' : '') + ' aria-label="Next week">›</button>' +
            '</div>' +
          '</div>' +
          '<p class="clh-sub">Built from this week\'s Plan</p>' +
        '</div>' +
        '<div class="clh-header-right">' +
          _racePillHtml(bRace, 'b') +
          aPill +
          '<button type="button" class="clh-settings" data-open-checklist-settings title="Manage checklist" aria-label="Manage checklist"><i class="ti ti-settings"></i></button>' +
        '</div>' +
      '</header>'
    );
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

  function _sessionCardHtml(item) {
    if (!item || item.kind !== 'planned_session') return '';
    var sum = item.structure_summary || {};
    var st = (item.session_type || 'session').replace('_', ' ');
    var meta = [];
    if (sum.duration_minutes) meta.push(sum.duration_minutes + ' min');
    if (sum.exercise_count) meta.push(sum.exercise_count + ' exercises');
    if (sum.block_count) meta.push(sum.block_count + ' blocks');
    var link = item.link || (item.id ? '/log?tab=plan&session=' + item.id : '/log?tab=plan');
    return (
      '<div class="clh-session-card clh-session-card--' + esc(_ribbonAccent(item.session_type)) + '">' +
        '<div class="clh-session-top">' +
          '<span class="clh-session-type">' + esc(st.charAt(0).toUpperCase() + st.slice(1)) + '</span>' +
          '<a href="' + esc(link) + '" class="clh-session-link">Open in Plan →</a>' +
        '</div>' +
        '<h3 class="clh-session-name">' + esc(item.label) + '</h3>' +
        (meta.length ? '<p class="clh-session-meta">' + esc(meta.join(' · ')) + '</p>' : '') +
      '</div>'
    );
  }

  function _sectionHtml(title, rowsHtml) {
    if (!rowsHtml) return '';
    return (
      '<div class="clh-section">' +
        '<h3 class="clh-section-title">' + esc(title) + '</h3>' +
        '<div class="clh-rows">' + rowsHtml + '</div>' +
      '</div>'
    );
  }

  function _dayPanelHtml(day) {
    if (!day) {
      return '<div class="clh-panel clh-panel--day"><p class="clh-empty">Select a day</p></div>';
    }
    var score = day.score || { core_done: 0, core_total: 0 };
    var items = day.items || [];
    var optionalDone = items.filter(function (it) {
      return it.role === 'optional' && it.state === 'done';
    }).length;
    var optionalTotal = items.filter(function (it) {
      return it.role === 'optional' && it.kind !== 'fuel';
    }).length;
    var pct = score.core_total ? Math.round((score.core_done / score.core_total) * 100) : 0;

    var coreItems = items.filter(function (it) {
      return it.role === 'core' && it.kind !== 'fuel';
    });
    var sessions = items.filter(function (it) {
      return it.kind === 'planned_session' && it.session_type !== 'rest';
    });
    var optionalItems = items.filter(function (it) {
      return it.role === 'optional' && it.kind !== 'fuel';
    });
    var fuelItem = items.find(function (it) { return it.kind === 'fuel'; });

    var coreRows = coreItems.map(function (it) { return _itemRowHtml(it, day.date); }).join('');
    var optionalRows = optionalItems.map(function (it) { return _itemRowHtml(it, day.date); }).join('');
    var sessionCards = sessions.map(_sessionCardHtml).join('');

    return (
      '<div class="clh-panel clh-panel--day" data-date="' + esc(day.date) + '">' +
        '<div class="clh-day-hdr">' +
          '<div>' +
            '<h2 class="clh-day-title">' + esc(_fmtDayTitle(day.date)) + '</h2>' +
            '<p class="clh-day-meta">Core ' + score.core_done + ' of ' + score.core_total +
              ' · optional ' + optionalDone + ' of ' + optionalTotal + '</p>' +
          '</div>' +
        '</div>' +
        '<div class="clh-progress"><div class="clh-progress-fill" style="width:' + pct + '%"></div></div>' +
        _sectionHtml('Core', coreRows) +
        (sessionCards
          ? '<div class="clh-section"><h3 class="clh-section-title">Session</h3>' + sessionCards + '</div>'
          : '') +
        _fuelBoxesHtml(day.fuel_detail, fuelItem) +
        _sectionHtml('Optional', optionalRows) +
      '</div>'
    );
  }

  function _matrixCellHtml(item) {
    if (!item) return '<span class="clh-mx-cell clh-mx-cell--empty">·</span>';
    if (item.weekly_progress) {
      var v = item.weekly_progress;
      var pct = v.target > 0 ? Math.min(100, Math.round((v.value / v.target) * 100)) : 0;
      return '<span class="clh-mx-cell clh-mx-cell--week" title="' +
        Math.round(v.value) + '/' + Math.round(v.target) + '">' +
        pct + '%</span>';
    }
    if (item.auto_fill_source) {
      return '<span class="clh-mx-cell clh-mx-cell--auto" title="Auto">A</span>';
    }
    var st = item.state || 'pending';
    return '<span class="clh-mx-cell clh-mx-cell--' + esc(st) + '" aria-label="' + esc(st) + '"></span>';
  }

  function _matrixRows(days) {
    var byId = {};
    (days || []).forEach(function (day) {
      (day.items || []).forEach(function (it) {
        if (it.kind !== 'habit') return;
        if (!byId[it.id]) {
          byId[it.id] = { id: it.id, label: it.label, cells: {} };
        }
        byId[it.id].cells[day.date] = it;
      });
    });
    return Object.keys(byId).map(function (k) { return byId[k]; });
  }

  function _matrixHtml(days, selectedDate) {
    if (!days || !days.length) {
      return '<p class="clh-empty">No habits this week</p>';
    }
    var rows = _matrixRows(days);
    if (!rows.length) {
      return '<p class="clh-empty">No habits this week</p>';
    }
    var hdr = '<div class="clh-mx-row clh-mx-row--hdr">' +
      '<span class="clh-mx-lab"></span>' +
      days.map(function (d, i) {
        var sel = d.date === selectedDate ? ' clh-mx-col--sel' : '';
        return '<button type="button" class="clh-mx-col' + sel + '" data-date="' + esc(d.date) + '" ' +
          'title="' + esc(d.date) + '">' + esc(DOW_SHORT[i] || DOW_SHORT[d.day_offset] || '') + '</button>';
      }).join('') +
      '</div>';
    var body = rows.map(function (row) {
      return '<div class="clh-mx-row">' +
        '<span class="clh-mx-lab" title="' + esc(row.label) + '">' + esc(row.label) + '</span>' +
        days.map(function (d) {
          return '<span class="clh-mx-cell-wrap">' + _matrixCellHtml(row.cells[d.date]) + '</span>';
        }).join('') +
        '</div>';
    }).join('');
    return '<div class="clh-matrix">' + hdr + body + '</div>';
  }

  function _sidebarHtml(data, selectedDate) {
    var st = data.build_status || {};
    var stLab = st.status === 'up_to_date' ? 'Up to date'
      : st.status === 'updating' ? 'Updating'
      : (st.status || '—');
    var stCls = st.status === 'up_to_date' ? 'ok' : st.status === 'updating' ? 'warn' : 'muted';
    var fw = data.fuel_week || {};
    var phase = fw.week_phase ? String(fw.week_phase).replace(/_/g, ' ') : '';
    var raceName = (data.a_race && data.a_race.name)
      ? data.a_race.name.split(/\s+\d/)[0].trim()
      : 'your race';
    return (
      '<aside class="clh-sidebar">' +
        '<div class="clh-panel clh-panel--sidebar">' +
          '<h3 class="clh-side-title">Week at a glance</h3>' +
          _matrixHtml(data.days, selectedDate) +
        '</div>' +
        '<div class="clh-panel clh-panel--sidebar">' +
          '<div class="clh-side-hdr">' +
            '<h3 class="clh-side-title">What moves ' + esc(raceName) + '</h3>' +
            '<a href="/log#performance" class="clh-side-link">Performance →</a>' +
          '</div>' +
          ((data.what_moves_estimate || []).slice(0, 4).map(function (ev) {
            var habit = ev.habit ? '<strong>' + esc(ev.habit) + '</strong> — ' : '';
            return '<p class="clh-evidence">' + habit + esc(ev.sentence || '') + '</p>';
          }).join('') || '<p class="clh-empty">No evidence yet</p>') +
        '</div>' +
        '<div class="clh-panel clh-panel--sidebar clh-panel--build">' +
          '<span class="clh-build-badge clh-build-badge--' + stCls + '">' + esc(stLab) + '</span>' +
          '<h3 class="clh-side-title">Checklist build</h3>' +
          (phase ? '<p class="clh-build-phase">Fuel phase: ' + esc(phase) + '</p>' : '') +
          (st.last_built_at
            ? '<p class="clh-build-sub">Built ' + esc(String(st.last_built_at).slice(0, 16)) + '</p>'
            : '<p class="clh-build-sub">Sessions and habits from this week\'s plan.</p>') +
          (fw.week_phase_reason
            ? '<p class="clh-build-reason">' + esc(String(fw.week_phase_reason)) + '</p>'
            : '') +
          '<button type="button" class="clh-manage" data-open-checklist-settings>Manage →</button>' +
        '</div>' +
      '</aside>'
    );
  }

  function _bindInteractions(host, data, opts) {
    var selected = opts.selectedDate || _todayISO();
    host.querySelectorAll('.clh-day').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var dt = btn.getAttribute('data-date');
        if (!dt || dt === selected) return;
        render(host, data, Object.assign({}, opts, { selectedDate: dt }));
      });
    });
    host.querySelectorAll('.clh-mx-col').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var dt = btn.getAttribute('data-date');
        if (!dt || dt === selected) return;
        render(host, data, Object.assign({}, opts, { selectedDate: dt }));
      });
    });
    host.querySelectorAll('[data-week-nav]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (btn.disabled) return;
        var dir = btn.getAttribute('data-week-nav');
        if (dir === 'prev' && typeof opts.onWeekPrev === 'function') opts.onWeekPrev();
        if (dir === 'next' && typeof opts.onWeekNext === 'function') opts.onWeekNext();
      });
    });
    var backBtn = host.querySelector('[data-back-current]');
    if (backBtn) {
      backBtn.addEventListener('click', function () {
        if (typeof opts.onBackCurrent === 'function') opts.onBackCurrent();
      });
    }
    host.querySelectorAll('[data-open-checklist-settings]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (typeof opts.onOpenSettings === 'function') {
          opts.onOpenSettings(data);
        }
      });
    });
    if (window.ChecklistUI && typeof window.ChecklistUI.wireItems === 'function') {
      window.ChecklistUI.wireItems(host, data, opts.onRefresh);
    }
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
        (!data.is_current_week
          ? '<div class="clh-back-wrap"><button type="button" class="clh-back-btn" data-back-current>← Back to this week</button></div>'
          : '') +
        _ribbonHtml(days, selected, today) +
        '<div class="clh-body">' +
          _dayPanelHtml(day) +
          _sidebarHtml(data, selected) +
        '</div>' +
      '</div>';

    _bindInteractions(host, data, Object.assign({}, opts, { selectedDate: selected }));
  }

  window.ChecklistHabitsPage = { render: render, matrixRows: _matrixRows };
})();
