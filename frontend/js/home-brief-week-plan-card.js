/**
 * Home week plan — same data as Training > Plan (`/api/planned-sessions`),
 * read-only teaser of the current Mon–Sun week. Edit on Plan tab.
 */
(function () {
  'use strict';

  var DOW = ['MON', 'TUE', 'WED', 'THU', 'FRI', 'SAT', 'SUN'];

  // Delegates to the shared escaper (issue #1603). The local copies
  // disagreed about the apostrophe, so identical content was safe on
  // some pages and attribute-injectable on others.
  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  function _iso(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + day;
  }

  function _mondayOf(d) {
    var x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    var dow = (x.getDay() + 6) % 7; // 0=Mon
    x.setDate(x.getDate() - dow);
    return x;
  }

  function _addDays(d, n) {
    var x = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    x.setDate(x.getDate() + n);
    return x;
  }

  function _parseISO(iso) {
    var p = iso.split('-');
    return new Date(+p[0], +p[1] - 1, +p[2]);
  }

  function _fam(t) {
    if (t === 'run') return 'run';
    if (t === 'plyo') return 'plyo';
    if (t === 'stretch') return 'stretch';
    return 'lift';
  }

  // Precedence: matched actual → server estimated_tss (pin/spend/history already
  // applied server-side). Never re-prefer structure.target_tss — that diverged
  // from week-load / Next-up.
  function _sessionTss(p) {
    if (p && p.actual && p.actual.tss != null) return { value: p.actual.tss, estimated: false };
    if (p && p.estimated_tss != null && isFinite(Number(p.estimated_tss))) {
      return { value: Number(p.estimated_tss), estimated: true };
    }
    return null;
  }

  function _sessionMeta(p) {
    var s = p.structure || {};
    var pinnedDur = (s.duration_minutes != null && isFinite(Number(s.duration_minutes))
      && Number(s.duration_minutes) > 0)
      ? Math.round(Number(s.duration_minutes))
      : null;
    if (pinnedDur != null || (Array.isArray(s.blocks) && s.blocks.length)) {
      var tot = pinnedDur;
      if (tot == null) {
        tot = 0;
        s.blocks.forEach(function (b) {
          var d = Number(b.duration_min) || 0;
          var r = Math.max(1, Number(b.repeat) || 1);
          tot += d * r + (Number(b.rest_min) || 0) * (r - 1);
        });
      }
      var tgt = (Array.isArray(s.blocks) && s.blocks.length)
        ? ((s.blocks.find(function (b) { return b.target; }) || {}).target)
        : null;
      return (tot ? tot + 'min' : '') + (tgt ? ' · ' + tgt : '');
    }
    if (Array.isArray(s.exercises) && s.exercises.length) {
      return s.exercises.length + ' exercise' + (s.exercises.length > 1 ? 's' : '');
    }
    return p.notes ? String(p.notes).slice(0, 40) : '';
  }

  // `/api/planned-sessions` returns both the prescribed plan (`planned`) and
  // any logged workouts that aren't linked to a plan slot (`unplanned` —
  // same "ghost" workouts the full Plan tab offers to map or ignore). This
  // teaser used to read only `planned`, so a day with a real logged workout
  // but no plan slot rendered as "Rest" — indistinguishable from a day the
  // athlete genuinely did nothing. Render the ghost as what actually
  // happened instead; still read-only (mapping/ignoring stays on Plan tab).
  function _ghostCardHtml(u) {
    var fam = _fam(u.workout_type);
    var name = u.name || '(untitled)';
    if (name.length > 42) name = name.slice(0, 40) + '…';
    return (
      '<div class="hpl-sess hpl-sess--' + fam + ' hpl-sess--unplanned">' +
        '<div class="hpl-sess-top">' +
          '<span class="hpl-tag hpl-tag--' + fam + '">' + esc(fam) + '</span>' +
          '<span class="hpl-tag hpl-tag--unplanned">not planned</span>' +
        '</div>' +
        '<div class="hpl-name">' + esc(name) + '</div>' +
        (u.meta ? '<div class="hpl-meta">' + esc(u.meta) + '</div>' : '') +
      '</div>'
    );
  }

  function renderSkeleton(el) {
    if (!el) return;
    el.innerHTML =
      '<div class="card-head">' +
        '<h2 class="ttl"><i class="ti ti-calendar-week"></i>Week plan</h2>' +
        '<a href="/log#plan">Full plan &#8594;</a>' +
      '</div>' +
      '<div class="brief-skeleton brief-skeleton--week">' +
        '<div class="brief-skel-row"></div>' +
        '<div class="brief-skel-row"></div>' +
        '<div class="brief-skel-row brief-skel-row--sm"></div>' +
      '</div>';
  }

  function renderUnavailable(el, msg) {
    if (!el) return;
    el.innerHTML =
      '<div class="card-head">' +
        '<h2 class="ttl"><i class="ti ti-calendar-week"></i>Week plan</h2>' +
        '<a href="/log#plan">Full plan &#8594;</a>' +
      '</div>' +
      '<div class="brief-unavail">' + esc(msg || 'Could not load week plan') + '</div>';
  }

  function _checklistDayMap(checklist) {
    var map = {};
    if (!checklist || !checklist.days) return map;
    checklist.days.forEach(function (d) {
      map[d.date] = d;
    });
    return map;
  }

  function _sessionState(p, clDay) {
    if (!clDay || !clDay.items) return '';
    var hit = clDay.items.find(function (it) {
      return it.kind === 'planned_session' && it.id === String(p.id);
    });
    if (!hit) return '';
    if (hit.state === 'done') return 'done';
    if (hit.state === 'missed') return 'missed';
    if (hit.state === 'skipped') return 'skipped';
    return 'pending';
  }

  function _fuelChip(clDay) {
    if (!clDay || !clDay.items) return '';
    var fuel = clDay.items.find(function (it) { return it.kind === 'fuel'; });
    if (!fuel || !fuel.fuel) return '';
    var dt = fuel.fuel.day_type || (fuel.label ? fuel.label.replace(/^Fuel · /, '') : '');
    return '<span class="hpl-chip hpl-chip--fuel">' + esc(dt.replace(/_/g, ' ')) + '</span>';
  }

  var _DAY_TYPE_LABEL = {
    lift: 'Lift day',
    easy_run: 'Easy day',
    long_run: 'Long run day',
    quality: 'Quality day',
    race: 'Race day',
    pre_race: 'Pre-race',
    carb_load: 'Carb load'
  };

  function _dayTypeChip(clDay) {
    var dt = clDay && clDay.fuel_detail && clDay.fuel_detail.day_type;
    if (!dt || dt === 'rest') return '';
    var label = _DAY_TYPE_LABEL[dt] || String(dt).replace(/_/g, ' ');
    return '<span class="hpl-day-type">' + esc(label) + '</span>';
  }

  function _extraChips(clDay) {
    if (!clDay || !clDay.items) return '';
    return clDay.items.filter(function (it) {
      return it.kind === 'planned_session' && it.session_type === 'mobility';
    }).map(function (it) {
      var st = it.state === 'done' ? ' hpl-chip--done' : '';
      return '<span class="hpl-chip hpl-chip--mobility' + st + '">' + esc(it.label) + '</span>';
    }).join('');
  }

  function _weekPlanSubtitle(checklist) {
    var fw = checklist && checklist.fuel_week;
    if (!fw) return '';
    var reason = fw.week_phase_reason ||
      (fw.week_phase ? String(fw.week_phase).replace(/_/g, ' ') : '');
    if (!reason) return '';
    return '<p class="hpl-phase">' + esc(reason) + '</p>';
  }

  function _dayRowHtml(day, todayStr, clMap) {
    var isToday = day.date === todayStr;
    var planned = day.planned || [];
    var unplanned = day.unplanned || [];
    var dow = day.dow || DOW[(_parseISO(day.date).getDay() + 6) % 7];
    var dnum = _parseISO(day.date).getDate();
    var clDay = clMap[day.date];

    var body;
    if (!planned.length && unplanned.length) {
      body = unplanned.map(_ghostCardHtml).join('');
    } else if (!planned.length) {
      body = '<div class="hpl-rest">Rest</div>';
    } else {
      body = planned.filter(function (p) {
        return (p.session_type || '').toLowerCase() !== 'mobility';
      }).map(function (p) {
        var fam = _fam(p.session_type);
        var meta = _sessionMeta(p);
        var name = p.name || '(untitled)';
        if (name.length > 42) name = name.slice(0, 40) + '…';
        var st = _sessionState(p, clDay);
        var stHtml = st
          ? '<span class="hpl-state hpl-state--' + st + '">' + esc(st) + '</span>'
          : '';
        return (
          '<div class="hpl-sess hpl-sess--' + fam + (st === 'done' ? ' hpl-sess--done' : '') + '">' +
            '<div class="hpl-sess-top">' +
              '<span class="hpl-tag hpl-tag--' + fam + '">' + esc(fam) + '</span>' +
              stHtml +
            '</div>' +
            '<div class="hpl-name">' + esc(name) + '</div>' +
            (meta ? '<div class="hpl-meta">' + esc(meta) + '</div>' : '') +
          '</div>'
        );
      }).join('');
    }

    var extras = _extraChips(clDay) + _fuelChip(clDay);

    var dayType = _dayTypeChip(clDay);

    return (
      '<div class="hpl-day' + (isToday ? ' hpl-day--today' : '') + '">' +
        '<div class="hpl-label">' +
          '<span class="hpl-dow">' + esc(dow) + '</span>' +
          '<span class="hpl-dnum">' + dnum + '</span>' +
        '</div>' +
        '<div class="hpl-body">' + body + (extras ? '<div class="hpl-extras">' + extras + '</div>' : '') + '</div>' +
        (dayType ? dayType : '') +
      '</div>'
    );
  }

  function _renderDays(el, days, checklist) {
    var todayStr = window.AppCommon.todayISO();
    var clMap = _checklistDayMap(checklist);
    var totalPlanned = days.reduce(function (n, d) {
      return n + (d.planned || []).filter(function (p) {
        return (p.session_type || '').toLowerCase() !== 'mobility';
      }).length;
    }, 0);
    // Zero planned sessions across the whole week almost always means no
    // plan has ever been drafted for this athlete (no A-race set, or a
    // plan that was never applied) rather than a genuine all-rest week —
    // say so plainly instead of letting seven "Rest" rows imply the
    // planner looked at the week and recommended nothing. Matches the
    // wording already used on the full Plan tab when there's no A race.
    var notice = !totalPlanned
      ? '<div class="hpl-noplan">No sessions planned this week. Set a ' +
          'goal race on <a href="/log#performance">Performance</a> to generate one.</div>'
      : '';
    el.innerHTML =
      '<div class="card-head">' +
        '<h2 class="ttl"><i class="ti ti-calendar-week"></i>Week plan</h2>' +
        '<a href="/log#plan">Full plan &#8594;</a>' +
      '</div>' +
      _weekPlanSubtitle(checklist) +
      notice +
      '<div class="hpl-list">' +
        days.map(function (d) { return _dayRowHtml(d, todayStr, clMap); }).join('') +
      '</div>';
  }

  // `days` — pre-fetched week; `checklist` — optional GET /api/checklist/week payload.
  function render(el, days, checklist) {
    if (!el) return;
    if (Array.isArray(days)) {
      _renderDays(el, days, checklist);
      return;
    }

    renderSkeleton(el);

    var monday = _mondayOf(new Date());
    var from = _iso(monday);
    var to = _iso(_addDays(monday, 6));

    Promise.all([
      fetch('/api/planned-sessions?from=' + from + '&to=' + to).then(function (r) {
        return r.ok ? r.json() : Promise.reject(r.status);
      }),
      fetch('/api/checklist/week').then(function (r) { return r.ok ? r.json() : null; }),
    ])
      .then(function (res) {
        _renderDays(el, (res[0] && res[0].days) || [], res[1]);
      })
      .catch(function () {
        renderUnavailable(el);
      });
  }

  window.HomeBriefWeekPlanCard = {
    render: render,
    renderSkeleton: renderSkeleton,
    renderUnavailable: renderUnavailable,
  };
})();
