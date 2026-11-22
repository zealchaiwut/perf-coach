(function () {
  'use strict';

  var esc = window.AppCommon ? window.AppCommon.escapeHtml.bind(window.AppCommon) : function (s) { return String(s); };

  function fmtHeaderDate(iso) {
    try {
      var d = new Date(iso + 'T12:00:00');
      return d.toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'long' });
    } catch (e) {
      return iso;
    }
  }

  function renderRoadChart(data, host) {
    if (!host || !data.columns || !data.columns.length) return;
    var cols = data.columns;
    var maxT = 1;
    cols.forEach(function (c) {
      maxT = Math.max(
        maxT,
        c.target_tss || 0,
        c.actual_tss || 0,
        (c.planned_tss || 0) + (c.actual_tss || 0) + (c.race_tss || 0)
      );
    });
    var h = 200;
    var pad = 6;
    var bw = Math.max(14, Math.floor(Math.min(720, cols.length * 26) / cols.length) - pad);
    var w = cols.length * (bw + pad) + pad * 2;
    var parts = ['<svg class="rv-road-chart" viewBox="0 0 ' + w + ' ' + (h + 36) + '" role="img" aria-label="Load plan chart">'];
    cols.forEach(function (c, i) {
      var x = pad + i * (bw + pad);
      var tgtH = c.target_tss ? (c.target_tss / maxT) * (h - 24) : 0;
      var fill = c.over_target ? '#f59e0b' : (c.state === 'done' ? '#1f3b8a' : '#c9d2e3');
      parts.push(
        '<rect class="rv-road-target" x="' + x + '" y="' + (h - tgtH) + '" width="' + bw + '" height="' + tgtH + '" fill="none" stroke="#8ba7e6" stroke-dasharray="4 3" rx="2"/>'
      );
      if (c.state === 'done' && c.actual_tss) {
        var actH = (c.actual_tss / maxT) * (h - 24);
        parts.push('<rect x="' + x + '" y="' + (h - actH) + '" width="' + bw + '" height="' + actH + '" fill="' + fill + '" rx="4"/>');
      } else if (c.state !== 'done') {
        var pl = (c.planned_tss || 0);
        var plH = pl ? (pl / maxT) * (h - 24) : 0;
        if (plH) {
          parts.push(
            '<rect x="' + x + '" y="' + (h - plH) + '" width="' + bw + '" height="' + plH + '" fill="#e8ecf4" stroke="#c9d2e3" stroke-dasharray="3 2" rx="4"/>'
          );
        }
        if (c.race_tss) {
          var base = plH;
          var rh = (c.race_tss / maxT) * (h - 24);
          parts.push('<rect x="' + x + '" y="' + (h - base - rh) + '" width="' + bw + '" height="' + rh + '" fill="#bef264" rx="4"/>');
        }
      }
      if (c.phase) {
        parts.push(
          '<text x="' + (x + bw / 2) + '" y="' + (h + 16) + '" text-anchor="middle" font-size="9" fill="#56627f">' +
          esc(String(c.phase).slice(0, 8)) + '</text>'
        );
      }
      parts.push('<title>Week ' + esc(c.week_start) + ' · target ' + esc(String(c.target_tss || '—')) + ' TSS</title>');
    });
    parts.push('</svg>');
    var title = data.mode === 'generic'
      ? esc(data.title || 'Recent training load')
      : 'Road to ' + esc(data.race_name || 'race');
    var sub = data.mode === 'generic'
      ? esc(data.subtitle || '')
      : esc(data.block_start) + ' → ' + esc(data.race_date);
    var hint = data.plan_hint
      ? '<p class="rv-plan-hint">' + esc(data.plan_hint) + ' <a href="/v2/settings/plan">Open plan settings</a></p>'
      : '';
    var legend =
      '<div class="rv-road-legend">' +
      '<span><i class="rv-road-swatch rv-road-swatch--done"></i>Done</span>' +
      '<span><i class="rv-road-swatch rv-road-swatch--planned"></i>Planned</span>' +
      '<span><i class="rv-road-swatch rv-road-swatch--target"></i>Target</span>' +
      '<span><i class="rv-road-swatch rv-road-swatch--race"></i>Race</span></div>';
    host.innerHTML =
      '<div class="rv-plan-road-head">' +
      '<div><h2 class="rv-label">' + title + '</h2><p class="rv-subtitle">' + sub + '</p></div>' +
      '<a href="/v2/settings/plan" class="rv-plan-settings-link">Change plan settings</a></div>' +
      hint +
      '<div class="rv-road-chart-wrap">' + parts.join('') + '</div>' +
      legend;
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
    if (!card || !wl) return;
    var target = Math.max(wl.target_tss || 0, 1);
    var ceiling = Math.max(wl.acwr_ceiling || target, target);
    var logged = wl.logged_tss || 0;
    var planned = wl.planned_tss || 0;
    var total = logged + planned;
    var scale = Math.max(ceiling, total, target);
    var loggedPct = Math.min(100, (logged / scale) * 100);
    var plannedPct = Math.min(100 - loggedPct, (planned / scale) * 100);
    var targetTick = Math.min(98, (target / scale) * 100);
    var ceilingTick = Math.min(99, (ceiling / scale) * 100);
    var headroom = wl.headroom_state === 'under_target'
      ? '<span class="rv-plan-headroom rv-plan-headroom--ok">About ' + Math.abs(Math.round(wl.headroom_tss)) + ' TSS left to target</span>'
      : wl.headroom_state === 'over_target'
        ? '<span class="rv-plan-headroom rv-plan-headroom--warn">Over target</span>'
        : '<span class="rv-plan-headroom rv-plan-headroom--bad">Over ACWR ceiling</span>';
    var formula =
      '<p class="rv-plan-formula rv-mono">' +
      'Baseline <strong>' + esc(String(wl.baseline_tss)) + ' TSS</strong> × ' +
      esc(String(wl.phase).replace(/_/g, ' ')) + ' <strong>' + esc(String(wl.phase_factor_pct)) + '%</strong> = ' +
      'target <strong>' + esc(String(wl.target_tss)) + ' TSS</strong></p>';
    var hint = wl.plan_hint
      ? '<p class="rv-plan-hint">' + esc(wl.plan_hint) + '</p>'
      : '';
    card.innerHTML =
      '<div class="rv-plan-week-head">' +
      '<h2 class="rv-label">This week\'s load</h2>' +
      statusBadge(wl) +
      '<span class="rv-mono rv-plan-week-tss">' + esc(String(Math.round(total))) + ' / ' + esc(String(Math.round(target))) + ' TSS</span></div>' +
      hint +
      formula +
      '<div class="rv-plan-kpis">' +
      '<div class="rv-plan-kpi"><span class="rv-subtitle">Baseline</span><strong class="rv-mono">' + esc(String(wl.baseline_tss)) + '</strong></div>' +
      '<div class="rv-plan-kpi"><span class="rv-subtitle">Phase</span><strong>' + esc(String(wl.phase).replace(/_/g, ' ')) + '</strong></div>' +
      '<div class="rv-plan-kpi"><span class="rv-subtitle">Target</span><strong class="rv-mono">' + esc(String(wl.target_tss)) + '</strong></div>' +
      '<div class="rv-plan-kpi"><span class="rv-subtitle">Ceiling</span><strong class="rv-mono">' + esc(String(wl.acwr_ceiling)) + '</strong><span class="rv-subtitle">28d ' + esc(String(wl.trailing_28d_avg)) + '</span></div>' +
      '</div>' +
      '<div class="rv-plan-load-bar" role="presentation">' +
      '<span class="rv-plan-load-bar__logged" style="width:' + loggedPct + '%"></span>' +
      '<span class="rv-plan-load-bar__planned" style="width:' + plannedPct + '%"></span>' +
      '<span class="rv-plan-load-bar__tick rv-plan-load-bar__tick--target" style="left:' + targetTick + '%" title="Target"></span>' +
      '<span class="rv-plan-load-bar__tick rv-plan-load-bar__tick--ceiling" style="left:' + ceilingTick + '%" title="Ceiling"></span>' +
      '</div>' +
      '<div class="rv-plan-load-labels rv-mono rv-subtitle">' +
      '<span>Logged ' + esc(String(logged)) + '</span><span>Planned ' + esc(String(planned)) + '</span></div>' +
      (wl.race_note ? '<p class="rv-subtitle">' + esc(wl.race_note) + '</p>' : '') +
      headroom;
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

    var warnHost = document.createElement('section');
    warnHost.className = 'rv-card rv-stack rv-plan-warnings';
    warnHost.id = 'v2-plan-warnings';
    warnHost.hidden = true;
    warnHost.setAttribute('aria-label', 'Plan warnings');
    if (shell && shell.firstChild) {
      shell.insertBefore(warnHost, shell.firstChild);
    }

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
        parts.push(
          '<p class="rv-hint--amber">' + esc(c.message) +
          ' <button type="button" class="rv-btn rv-btn--secondary" data-apply-warning="' + esc(c.id) + '">Move +1 week</button></p>'
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
                '<section class="rv-card rv-stack rv-plan-rail-card"><span class="rv-label">Next up</span>' + nextHtml + '</section>' +
                '<section class="rv-card rv-stack rv-plan-rail-card"><span class="rv-label">Coach week</span>' + coachNote + '</section>' +
                '<section class="rv-card rv-stack rv-plan-rail-card"><span class="rv-label">From Performance</span>' + perf +
                ' <a href="/v2/performance" class="rv-plan-settings-link">Open Performance</a></section>' +
                '<section class="rv-card rv-stack rv-plan-rail-card"><span class="rv-label">Rules in play</span>' + rules + '</section>';
            });
        })
        .catch(function () {
          rail.innerHTML = '<section class="rv-card rv-plan-rail-card"><p class="rv-subtitle">Sidebar unavailable.</p></section>';
        });
    }

    mountWeekBoard(board, state.ws, week, state);

    Promise.all([
      fetch('/api/plan/revamp-road-chart', { credentials: 'include' }).then(function (r) { return r.json(); }),
      fetch('/api/plan/revamp-week-load?week_start=' + encodeURIComponent(state.ws), { credentials: 'include' }).then(function (r) { return r.json(); }),
      fetch('/api/plan/revamp-warnings', { credentials: 'include' }).then(function (r) { return r.ok ? r.json() : {}; }),
    ]).then(function (pair) {
      if (pair[0]) renderRoadChart(pair[0], road);
      if (pair[1]) renderWeekLoad(week, pair[1]);
      renderWarnings(pair[2]);
      renderRail(state.ws, pair[2], pair[1]);
    }).catch(function () {
      if (road) {
        road.innerHTML = '<p class="rv-section-state" role="alert">Could not load load chart — refresh or check your connection.</p>';
      }
      mountWeekBoard(board, state.ws, week, state);
    });
  }

  document.addEventListener('DOMContentLoaded', init);
})();