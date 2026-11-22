(function () {
  'use strict';

  var esc = window.AppCommon ? window.AppCommon.escapeHtml.bind(window.AppCommon) : function (s) { return String(s); };

  var MONTHS_SHORT = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
  var MONTHS_LONG = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'];
  var WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

  function isoParts(iso) {
    var p = String(iso || '').slice(0, 10).split('-');
    return { y: parseInt(p[0], 10), m: parseInt(p[1], 10), d: parseInt(p[2], 10) };
  }

  function fmtDayMon(iso) {
    var p = isoParts(iso);
    if (!p.m) return iso || '';
    return p.d + ' ' + MONTHS_SHORT[p.m - 1];
  }

  function fmtHeaderDate(iso) {
    var p = isoParts(iso);
    if (!p.m) return iso || '';
    var t = Date.UTC(p.y, p.m - 1, p.d);
    var wd = WEEKDAYS[new Date(t).getUTCDay()];
    return wd + ', ' + p.d + ' ' + MONTHS_LONG[p.m - 1];
  }

  function daysBetween(a, b) {
    var pa = isoParts(a);
    var pb = isoParts(b);
    return Math.round((Date.UTC(pb.y, pb.m - 1, pb.d) - Date.UTC(pa.y, pa.m - 1, pa.d)) / 86400000);
  }

  function fmtWeekOf(start, end) {
    var a = isoParts(start);
    var b = isoParts(end || start);
    if (!a.m) return start;
    if (a.m === b.m) return a.d + ' – ' + b.d + ' ' + MONTHS_SHORT[a.m - 1];
    return a.d + ' ' + MONTHS_SHORT[a.m - 1] + ' – ' + b.d + ' ' + MONTHS_SHORT[b.m - 1];
  }

  function phaseName(phase) {
    return String(phase || '').replace(/_/g, ' ').replace(/\b\w/g, function (c) { return c.toUpperCase(); });
  }

  function phasePillStyle(phase) {
    var p = String(phase || '').toLowerCase();
    if (p === 'peak_hold' || p === 'peak') return 'background:#e3eaf8;color:#1f3b8a';
    if (p === 'taper' || p === 'mini-taper' || p === 'mini_taper') return 'background:#fff4d8;color:#6b4408';
    if (p === 'race_week' || p.indexOf('race') >= 0) return 'background:#fde8e8;color:#7a1a1a';
    if (p === 'recover') return 'background:#e6f6ec;color:#2d5e10';
    if (p === 'rebuild') return 'background:#eef2fb;color:#33405e';
    return 'background:#eef2fb;color:#33405e';
  }

  function emptyPlanCard(host, label, message) {
    host.innerHTML =
      '<div class="rv-plan-road-head"><div><h2 class="rv-label">' + esc(label) + '</h2>' +
      '<p class="rv-chart-sub">' + esc(message) + '</p></div>' +
      '<a href="/v2/settings/plan" class="rv-plan-settings-link">Add an A race</a></div>';
  }

  function renderRoadChart(data, host) {
    if (!host) return;
    if (!data || !data.columns || !data.columns.length) {
      emptyPlanCard(host, 'Road to race', 'Add a planned A race to see the load plan.');
      return;
    }
    var cols = data.columns;
    var generic = data.mode === 'generic';
    var settings = Object.assign({}, data.defaults || {}, data.settings || {});
    var maxT = 1;
    cols.forEach(function (c) {
      maxT = Math.max(
        maxT,
        c.target_tss || 0,
        c.actual_tss || 0,
        (c.planned_tss || 0) + (c.actual_tss || 0) + (c.race_tss || 0)
      );
    });
    var BOX = 230;
    var label = generic ? (data.title || 'Recent training load') : ('Road to ' + (data.race_name || 'race'));
    var title = generic
      ? (data.subtitle || 'Load from your last weeks')
      : ('Load plan · ' + fmtDayMon(data.block_start) + ' → ' + fmtDayMon(data.race_date));
    var peakTss = 0;
    var holdWeeks = 0;
    cols.forEach(function (c) {
      if (String(c.phase || '') === 'peak_hold') {
        holdWeeks += 1;
        if ((c.target_tss || 0) > peakTss) peakTss = c.target_tss;
      }
    });
    var tiles = [];
    if (!generic && data.race_name) {
      var weeksOut = Math.max(0, Math.round(daysBetween(
        (window.AppCommon && window.AppCommon.todayISO ? window.AppCommon.todayISO() : cols[0].week_start),
        data.race_date
      ) / 7));
      tiles.push('<div class="rv-plan-tile"><span class="rv-chart-sub">A race</span><strong>' + esc(data.race_name) + ' · ' + esc(fmtDayMon(data.race_date)) + '</strong></div>');
      tiles.push('<div class="rv-plan-tile"><span class="rv-chart-sub">To A race</span><strong>' + weeksOut + ' weeks</strong></div>');
      if (settings.ramp_pct != null) {
        tiles.push('<div class="rv-plan-tile"><span class="rv-chart-sub">Ramp</span><strong>+' + Math.round(Number(settings.ramp_pct) * 100) + '% a week</strong></div>');
      }
      if (holdWeeks) {
        tiles.push('<div class="rv-plan-tile"><span class="rv-chart-sub">Peak</span><strong>' + holdWeeks + ' week' + (holdWeeks === 1 ? '' : 's') + (peakTss ? ' · ' + Math.round(peakTss) + ' TSS' : '') + '</strong></div>');
      }
      var taper = settings.taper_factors || [];
      if (taper.length) {
        var t0 = Math.round(Number(taper[0]) * 100);
        var t1 = Math.round(Number(taper[taper.length - 1]) * 100);
        tiles.push('<div class="rv-plan-tile"><span class="rv-chart-sub">Taper</span><strong>' + taper.length + ' week' + (taper.length === 1 ? '' : 's') + ' · ' + t0 + '% → ' + t1 + '%</strong></div>');
      }
    }

    var bars = cols.map(function (c) {
      var tgt = c.target_tss || 0;
      var act = c.actual_tss || 0;
      var planned = c.planned_tss || 0;
      var race = c.race_tss || 0;
      var tgtH = tgt ? Math.max(8, (tgt / maxT) * BOX) : 0;
      var actH = act ? Math.max(4, (act / maxT) * BOX) : 0;
      var plH = planned ? Math.max(4, (planned / maxT) * BOX) : 0;
      var raceH = race ? Math.max(4, (race / maxT) * BOX) : 0;
      var isCur = c.state === 'current';
      var isRace = (c.race_items && c.race_items.length) || race;
      var tgtCls = 'rv-road-tgt';
      if (isRace) tgtCls += ' rv-road-tgt--race';
      else if (String(c.phase || '').indexOf('race') >= 0) tgtCls += ' rv-road-tgt--a-race';
      else if (c.state === 'future') tgtCls += ' rv-road-tgt--future';
      var inner = tgtH ? '<div class="' + tgtCls + '" style="height:' + tgtH + 'px"></div>' : '';
      if (c.state === 'done' && actH) {
        inner += '<div class="rv-road-act' + (c.over_target ? ' rv-road-act--over' : '') + '" style="height:' + actH + 'px"></div>';
      } else if (c.state !== 'done') {
        if (plH) inner += '<div class="rv-road-act rv-road-act--planned" style="height:' + plH + 'px"></div>';
        if (raceH) inner += '<div class="rv-road-act rv-road-act--race" style="height:' + raceH + 'px;bottom:' + plH + 'px"></div>';
      }
      var val = '';
      if (c.state === 'done' && act) {
        var delta = tgt ? Math.round(act - tgt) : 0;
        val = c.over_target && delta
          ? '<span class="rv-road-val rv-road-val--over" style="bottom:' + (actH + 4) + 'px">' + Math.round(act) + ' · +' + delta + '</span>'
          : '<span class="rv-road-val" style="bottom:' + (actH + 4) + 'px">' + Math.round(act) + '</span>';
      } else if (tgt) {
        var extra = race ? ' + race' : '';
        val = '<span class="rv-road-val" style="bottom:' + (Math.max(tgtH, plH + raceH) + 4) + 'px">' + Math.round(planned || tgt) + extra + '</span>';
      }
      var call = '';
      if (c.race_items && c.race_items[0] && c.race_items[0].label) {
        call = '<span class="rv-road-call">' + esc(c.race_items[0].label) + '</span>';
      }
      return (
        '<div class="rv-road-col">' +
        '<div class="rv-road-box">' + inner + val + call + '</div>' +
        '<span class="rv-road-x' + (isCur ? ' is-current' : '') + '">' + esc(fmtDayMon(c.week_start)) + '</span></div>'
      );
    }).join('');

    var phaseSpans = [];
    var i = 0;
    while (i < cols.length) {
      var ph = cols[i].phase || '';
      var j = i + 1;
      while (j < cols.length && (cols[j].phase || '') === ph) j += 1;
      if (ph) {
        phaseSpans.push(
          '<div class="rv-road-phase" style="grid-column: span ' + (j - i) + ';' + phasePillStyle(ph) + '">' +
          esc(phaseName(ph).toUpperCase()) + '</div>'
        );
      } else {
        phaseSpans.push('<div style="grid-column: span ' + (j - i) + '"></div>');
      }
      i = j;
    }

    var insight = '';
    (data.phase_overruns || []).forEach(function (ov) {
      insight += phaseName(ov.phase) + ' ran about ' + Math.round(ov.mean_over_pct) + '% over. ';
    });

    var hint = data.plan_hint
      ? '<p class="rv-plan-hint">' + esc(data.plan_hint) + ' <a href="/v2/settings/plan">Add an A race</a></p>'
      : '';

    host.innerHTML =
      '<div class="rv-plan-road-head">' +
      '<div><h2 class="rv-label">' + esc(label) + '</h2><p class="rv-plan-road-title">' + esc(title) + '</p></div>' +
      '<a href="/v2/settings/plan" class="rv-plan-settings-link">Change plan settings</a></div>' +
      hint +
      (tiles.length ? '<div class="rv-plan-tiles">' + tiles.join('') + '</div>' : '') +
      '<div class="rv-road-grid" style="grid-template-columns:repeat(' + cols.length + ',minmax(0,1fr))">' + bars + '</div>' +
      '<div class="rv-road-phases" style="grid-template-columns:repeat(' + cols.length + ',minmax(0,1fr))">' + phaseSpans.join('') + '</div>' +
      '<div class="rv-road-legend">' +
      '<span><i class="rv-road-swatch rv-road-swatch--done"></i>Done, on target</span>' +
      '<span><i class="rv-road-swatch rv-road-swatch--over"></i>Done, over target</span>' +
      '<span><i class="rv-road-swatch rv-road-swatch--planned"></i>Planned</span>' +
      '<span><i class="rv-road-swatch rv-road-swatch--race"></i>Race · estimated TSS</span>' +
      '<span><i class="rv-road-swatch rv-road-swatch--target"></i>Target</span>' +
      (insight ? '<span class="rv-road-insight">' + esc(insight.trim()) + '</span>' : '') +
      '</div>';
  }

  function statusBadge(wl) {
    var total = (wl.logged_tss || 0) + (wl.planned_tss || 0);
    var target = wl.target_tss || 1;
    if (wl.headroom_state === 'over_ceiling') {
      return '<span class="rv-plan-status rv-plan-status--bad">Over ceiling</span>';
    }
    if (wl.headroom_state === 'over_target') {
      return '<span class="rv-plan-status rv-plan-status--warn">Over target</span>';
    }
    if (total <= target) {
      return '<span class="rv-plan-status rv-plan-status--ok">On target</span>';
    }
    return '<span class="rv-plan-status">—</span>';
  }

  function renderWeekLoad(card, wl) {
    if (!card) return;
    if (!wl) {
      emptyPlanCard(card, "This week's load", 'Configure plan settings after you add an A race.');
      return;
    }
    var target = Math.max(wl.target_tss || 0, 1);
    var ceiling = Math.max(wl.acwr_ceiling || target, target);
    var logged = wl.logged_tss || 0;
    var planned = wl.planned_tss || 0;
    var total = logged + planned;
    var scale = Math.max(ceiling, total, target, 1);
    var loggedPct = Math.min(100, (logged / scale) * 100);
    var plannedPct = Math.min(100 - loggedPct, (planned / scale) * 100);
    var targetTick = Math.min(98, (target / scale) * 100);
    var ceilingTick = Math.min(99, (ceiling / scale) * 100);
    var left = wl.headroom_state === 'under_target'
      ? '<span class="rv-plan-headroom rv-plan-headroom--ok">' + Math.abs(Math.round(wl.headroom_tss || 0)) + ' TSS left to fill</span>'
      : wl.headroom_state === 'over_target'
        ? '<span class="rv-plan-headroom rv-plan-headroom--warn">Over target</span>'
        : '<span class="rv-plan-headroom rv-plan-headroom--bad">Over ACWR ceiling</span>';
    var hint = wl.plan_hint
      ? '<p class="rv-plan-hint">' + esc(wl.plan_hint) + ' <a href="/v2/settings/plan">Add an A race</a></p>'
      : '';
    var phase = phaseName(wl.phase);
    var ac = window.AppCommon || {};
    var range = wl.week_start
      ? fmtWeekOf(wl.week_start, ac.addDaysISO ? ac.addDaysISO(wl.week_start, 6) : wl.week_start)
      : '';
    card.innerHTML =
      '<div class="rv-plan-week-head">' +
      '<div><h2 class="rv-label">This week\'s load' + (range ? ' · ' + esc(range) : '') + (phase ? ' · ' + esc(phase) : '') + '</h2>' +
      '<p class="rv-chart-sub">Where the target comes from, and how the planned sessions add up to it</p></div>' +
      '<div class="rv-plan-week-nums">' + statusBadge(wl) +
      '<span class="rv-mono rv-plan-week-tss">' + esc(String(Math.round(total))) + '</span>' +
      '<span class="rv-mono rv-plan-week-den">/ ' + esc(String(Math.round(target))) + ' TSS</span></div></div>' +
      hint +
      '<div class="rv-plan-formula-grid">' +
      '<div class="rv-plan-tile"><span class="rv-chart-sub">Baseline · ' + esc(phase || 'phase') + '</span><strong class="rv-mono">' + esc(String(wl.baseline_tss)) + ' TSS</strong></div>' +
      '<span class="rv-plan-op">×</span>' +
      '<div class="rv-plan-tile"><span class="rv-chart-sub">Factor</span><strong class="rv-mono">' + esc(String(wl.phase_factor_pct)) + '%</strong></div>' +
      '<span class="rv-plan-op">=</span>' +
      '<div class="rv-plan-tile rv-plan-tile--target"><span class="rv-chart-sub">Training target</span><strong class="rv-mono">' + esc(String(wl.target_tss)) + ' TSS</strong>' +
      (wl.race_note ? '<span class="rv-chart-sub">' + esc(wl.race_note) + '</span>' : '') + '</div>' +
      '<div class="rv-plan-tile"><span class="rv-chart-sub">Guardrail · hard ceiling</span><strong class="rv-mono rv-plan-ceiling">' + esc(String(wl.acwr_ceiling)) + '</strong>' +
      '<span class="rv-chart-sub">ACWR · 28-day avg ' + esc(String(wl.trailing_28d_avg)) + '</span></div>' +
      '</div>' +
      '<div class="rv-plan-load-wrap">' +
      '<div class="rv-plan-load-bar" role="presentation">' +
      '<span class="rv-plan-load-bar__logged" style="width:' + loggedPct + '%"></span>' +
      '<span class="rv-plan-load-bar__planned" style="width:' + plannedPct + '%"></span>' +
      '</div>' +
      '<span class="rv-plan-load-bar__tick rv-plan-load-bar__tick--target" style="left:' + targetTick + '%" title="Target"></span>' +
      '<span class="rv-plan-load-bar__tick rv-plan-load-bar__tick--ceiling" style="left:' + ceilingTick + '%" title="Ceiling"></span>' +
      '</div>' +
      '<div class="rv-plan-load-labels">' +
      '<span>Logged <b class="rv-mono">' + esc(String(logged)) + '</b></span>' +
      '<span>Planned <b class="rv-mono">' + esc(String(planned)) + '</b></span>' +
      '<span>Target <b class="rv-mono">' + esc(String(Math.round(target))) + '</b> (black tick)</span>' +
      '<span>Ceiling <b class="rv-mono">' + esc(String(Math.round(ceiling))) + '</b> (amber tick)</span>' +
      left + '</div>';
  }

  function mountWeekBoard(board, ws, weekEl, state) {
    if (!board || !window.V2PlanWeekBoard) return;
    window.V2PlanWeekBoard.mount(board, {
      weekStart: ws,
      weekLoadEl: weekEl,
      renderWeekLoad: renderWeekLoad,
      onWeekChanged: function (w) { state.ws = w; },
    });
  }

  function loadHeaderSubtitle(ws) {
    var sub = document.getElementById('rv-training-subtitle');
    if (!sub) return;
    var ac = window.AppCommon || {};
    var today = ac.todayISO ? ac.todayISO() : new Date().toISOString().slice(0, 10);
    sub.textContent = fmtHeaderDate(today);
    fetch('/api/races', { credentials: 'include' })
      .then(function (r) { return r.ok ? r.json() : []; })
      .then(function (body) {
        var races = (Array.isArray(body) ? body : (body.races || body.items || []))
          .filter(function (race) { return (race.status || 'planned') === 'planned'; });
        if (!races.length) return;
        races.sort(function (a, b) { return (a.race_date || '').localeCompare(b.race_date || ''); });
        var next = races[0];
        var extra = races.length > 1 ? ' · ' + esc(races[1].name) + ' also planned' : '';
        sub.textContent = fmtHeaderDate(today) + ' · ' + (next.name || 'Race') + extra;
      })
      .catch(function () { /* keep date only */ });
  }

  function init() {
    var road = document.getElementById('v2-plan-road');
    var week = document.getElementById('v2-plan-week-load');
    var board = document.getElementById('v2-plan-week-board');
    var shell = document.getElementById('v2-plan-shell');
    var ac = window.AppCommon || {};
    var anchor = ac.nowBangkok ? ac.nowBangkok() : new Date();
    var dow = anchor.getDay();
    var monOffset = dow === 0 ? -6 : 1 - dow;
    var state = { ws: ac.addDaysISO ? ac.addDaysISO(ac.todayISO(), monOffset) : ac.todayISO() };

    loadHeaderSubtitle(state.ws);

    if (window.V2SyncToolbar) {
      window.V2SyncToolbar.mount(document.getElementById('v2-sync-toolbar'), {});
    }

    var warnHost = document.getElementById('v2-plan-warnings');

    function renderWarnings(w) {
      if (!warnHost || !w) return;
      var parts = [];
      if (w.layout_error) {
        parts.push(
          '<p class="rv-hint--amber" role="alert"><strong>Plan layout</strong> — ' +
          esc(w.layout_error.message) + ' ' + esc(w.layout_error.hint_setting || '') + '</p>'
        );
      }
      (w.clashes || []).forEach(function (c) {
        var moveLabel = c.suggested_date ? 'Move to ' + fmtDayMon(c.suggested_date) : 'Move +1 week';
        parts.push(
          '<div class="rv-plan-callout rv-plan-callout--amber">' +
          '<span><b>' + esc(c.message) + '</b></span>' +
          ' <button type="button" class="rv-btn rv-btn--ghost-amber" data-apply-warning="' + esc(c.id) + '">' + esc(moveLabel) + '</button></div>'
        );
      });
      warnHost.innerHTML = parts.length ? parts.join('') : '';
      warnHost.hidden = !parts.length;
      warnHost.querySelectorAll('[data-apply-warning]').forEach(function (btn) {
        btn.onclick = function () {
          fetch('/api/plan/revamp-warnings/apply', {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ warning_id: btn.getAttribute('data-apply-warning') }),
          }).then(function (r) { return r.json(); }).then(function (json) {
            renderWarnings(json);
            toast('Rescheduled');
          });
        };
      });
    }

    function toast(msg) {
      if (window.RevampUI && window.RevampUI.showToast) window.RevampUI.showToast(msg);
    }

    function renderRail(ws, warnings, wl) {
      var rail = document.getElementById('v2-plan-rail');
      if (!rail) return;
      rail.innerHTML = '<p class="rv-subtitle">Loading sidebar…</p>';
      fetch('/api/plan/week-bundle?week_start=' + encodeURIComponent(ws))
        .then(function (r) { return r.ok ? r.json() : {}; })
        .then(function (bundle) {
          var nextHtml = '<p class="rv-subtitle">No upcoming session in the next few days.</p>';
          var days = (bundle.next_up && bundle.next_up.days) || [];
          for (var i = 0; i < days.length; i++) {
            var items = days[i].items || days[i].sessions || [];
            if (items.length) {
              var it = items[0];
              nextHtml =
                '<strong>' + esc(it.name || it.title || 'Session') + '</strong>' +
                '<p class="rv-subtitle" style="margin:4px 0 0">' + esc(days[i].date || days[i].label || '') + '</p>';
              break;
            }
          }
          var rules = '<ul class="rv-plan-rules"><li class="rv-subtitle">Weekly training target excludes race-day load when a race is on the plan.</li></ul>';
          if (warnings && (warnings.clashes || []).length) {
            rules = '<ul class="rv-plan-rules">' + (warnings.clashes || []).map(function (c) {
              return '<li>' + esc(c.message) + '</li>';
            }).join('') + '</ul>';
          } else if (warnings && warnings.race_week_note) {
            rules = '<p class="rv-subtitle">' + esc(warnings.race_week_note) + '</p>';
          }
          return fetch('/api/performance/focus', { credentials: 'include' })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (focus) {
              var axis = focus && focus.focus ? esc(focus.focus.label) : '—';
              var perf =
                '<p class="rv-subtitle" style="margin:0 0 6px">Most room to grow: <strong>' + axis + '</strong>.</p>' +
                '<p class="rv-subtitle" style="margin:0">Queue mobility or drills from Performance when filling the week.</p>';
              var coachNote = wl && wl.mode === 'generic'
                ? '<p class="rv-subtitle">Import coach sessions from the week board when your block is set up.</p>'
                : '<p class="rv-subtitle">Use <strong>Import coach week</strong> on the board when your coach sends a week.</p>';
              rail.innerHTML =
                '<section class="rv-card rv-stack rv-plan-rail-card"><span class="rv-label">Next up</span>' +
                '<div class="rv-plan-next">' + nextHtml + '</div></section>' +
                '<section class="rv-card rv-card--soft rv-stack rv-plan-rail-card"><span class="rv-label">Coach week</span>' + coachNote + '</section>' +
                '<section class="rv-card rv-stack rv-plan-rail-card"><div class="rv-row"><span class="rv-label">From Performance</span>' +
                '<a href="/v2/performance" class="rv-plan-settings-link">Why</a></div>' + perf + '</section>' +
                '<section class="rv-card rv-card--soft rv-stack rv-plan-rail-card"><span class="rv-label">Rules in play</span>' + rules + '</section>';
            });
        })
        .catch(function () {
          rail.innerHTML = '<section class="rv-card rv-plan-rail-card"><p class="rv-subtitle">Sidebar unavailable.</p></section>';
        });
    }

    mountWeekBoard(board, state.ws, week, state);

    function readJson(r) {
      if (r.status === 204) return null;
      return r.ok ? r.json() : null;
    }

    Promise.all([
      fetch('/api/plan/revamp-road-chart', { credentials: 'include' }).then(readJson),
      fetch('/api/plan/revamp-week-load?week_start=' + encodeURIComponent(state.ws), { credentials: 'include' }).then(readJson),
      fetch('/api/plan/revamp-warnings', { credentials: 'include' }).then(function (r) { return r.ok ? r.json() : {}; }),
    ]).then(function (pair) {
      renderRoadChart(pair[0], road);
      renderWeekLoad(week, pair[1]);
      renderWarnings(pair[2]);
      renderRail(state.ws, pair[2], pair[1]);
    }).catch(function () {
      if (road) emptyPlanCard(road, 'Road to race', 'Could not load the load chart — refresh or check your connection.');
      mountWeekBoard(board, state.ws, week, state);
    });
  }

  document.addEventListener('DOMContentLoaded', init);
})();