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

  function fmtNextUpDate(iso) {
    var p = isoParts(iso);
    if (!p.m) return iso || '';
    var t = Date.UTC(p.y, p.m - 1, p.d);
    var wd = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][new Date(t).getUTCDay()];
    return wd + ' ' + p.d + ' ' + MONTHS_SHORT[p.m - 1];
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

  function renderCompactNoRace(host, wl) {
    var logged = Math.round((wl && wl.logged_tss) || 0);
    var planned = Math.round((wl && wl.planned_tss) || 0);
    var target = Math.round((wl && wl.target_tss) || 0);
    var total = logged + planned;
    host.innerHTML =
      '<div class="rv-plan-road-head rv-plan-compact-load"><div><h2 class="rv-label">This week</h2>' +
      '<p class="rv-chart-sub">' + esc(String(total)) + ' / ' + esc(String(target)) +
      ' TSS · vs your 28-day average</p></div>' +
      '<a href="/v2/settings/plan" class="rv-plan-settings-link">Add an A race</a></div>';
  }

  function friendlySectionError(r) {
    if (!r) return 'Could not load this section. Check your connection.';
    if (r.status === 401 || r.status === 403) return 'Session expired — refresh and try again.';
    return 'Could not load this section. Try again.';
  }

  function sectionError(host, title, message, onRetry) {
    if (!host) return;
    host.innerHTML =
      '<div class="rv-card rv-plan-section-error" role="alert">' +
      '<p class="rv-subtitle"><strong>' + esc(title) + '</strong> — ' + esc(message) + '</p>' +
      '<button type="button" class="rv-btn rv-btn--secondary" data-section-retry>Retry</button></div>';
    var btn = host.querySelector('[data-section-retry]');
    if (btn && onRetry) btn.onclick = onRetry;
  }

  function readOkJson(r) {
    if (r.status === 204) return null;
    if (!r.ok) throw new Error(friendlySectionError(r));
    return r.json();
  }

  function patchRoadColumn(col) {
    var host = document.getElementById('v2-plan-road');
    if (!host || !col || !host._roadData || !host._roadData.columns) return;
    host._roadData.columns = host._roadData.columns.map(function (c) {
      return c.week_start === col.week_start ? col : c;
    });
    renderRoadChart(host._roadData, host, host._weekLoad);
  }

  function applyMutation(payload) {
    if (!payload) return;
    var road = document.getElementById('v2-plan-road');
    var week = document.getElementById('v2-plan-week-load');
    var warnHost = document.getElementById('v2-plan-warnings');
    var board = document.getElementById('v2-plan-week-board');
    if (payload.road_column) patchRoadColumn(payload.road_column);
    if (payload.week_load !== undefined) {
      if (road) road._weekLoad = payload.week_load;
      renderWeekLoad(week, payload.week_load);
    }
    if (payload.warnings !== undefined) renderWarnings(warnHost, payload.warnings);
    if (board && board._applyWeek) board._applyWeek(payload);
    var ws = (payload.board && payload.board.week_start)
      || (payload.week_load && payload.week_load.week_start);
    if (window.V2TrainingPlan.weekCacheInvalidate) {
      window.V2TrainingPlan.weekCacheInvalidate(ws);
    }
    if (window.V2TrainingPlan.weekCachePut && (payload.board || payload.week_load)) {
      window.V2TrainingPlan.weekCachePut(ws, payload);
    }
  }

  function renderRoadChart(data, host, wl) {
    if (!host) return;
    host._roadData = data;
    if (wl) host._weekLoad = wl;
    if (data && data.mode === 'generic' && !(data.columns && data.columns.length)) {
      renderCompactNoRace(host, wl || host._weekLoad);
      return;
    }
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
    var PLOT = BOX * 0.88;
    var label = generic ? 'Road to race' : ('Road to ' + (data.race_name || 'race'));
    var chronic = data.chronic_baseline != null ? Math.round(data.chronic_baseline) : null;
    var title;
    var subLine = '';
    if (generic) {
      title = chronic != null
        ? ('Recent load · ' + chronic + ' TSS/wk reference')
        : 'Recent load';
      subLine = '<p class="rv-subtitle">28-day chronic</p>';
    } else {
      title = 'Load plan · ' + fmtDayMon(data.block_start) + ' → ' + fmtDayMon(data.race_date);
    }
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
      var bRace = data.b_race_name || (settings.b_race && settings.b_race.name) || '';
      tiles.push('<div class="rv-plan-tile"><span class="rv-chart-sub">B race in block</span><strong>' +
        (bRace ? esc(bRace) : 'None') + '</strong></div>');
      tiles.push('<div class="rv-plan-tile"><span class="rv-chart-sub">Ramp</span><strong>' +
        (settings.ramp_pct != null ? ('+' + Math.round(Number(settings.ramp_pct) * 100) + '% a week') : '—') +
        '</strong></div>');
      tiles.push('<div class="rv-plan-tile"><span class="rv-chart-sub">Peak</span><strong>' +
        (holdWeeks
          ? (holdWeeks + ' week' + (holdWeeks === 1 ? '' : 's') + (peakTss ? ' · ' + Math.round(peakTss) + ' TSS' : ''))
          : '—') +
        '</strong></div>');
      var taper = settings.taper_factors || [];
      var taperLabel = '—';
      if (taper.length) {
        var t0 = Math.round(Number(taper[0]) * 100);
        var t1 = Math.round(Number(taper[taper.length - 1]) * 100);
        taperLabel = taper.length + ' week' + (taper.length === 1 ? '' : 's') + ' · ' + t0 + '% → ' + t1 + '%';
      }
      tiles.push('<div class="rv-plan-tile"><span class="rv-chart-sub">Taper</span><strong>' + taperLabel + '</strong></div>');
    }

    function valBottom(h) {
      return Math.min(h + 4, BOX - 16);
    }

    var bars = cols.map(function (c) {
      var tgt = c.target_tss || 0;
      var act = c.actual_tss || 0;
      var planned = c.planned_tss || 0;
      var race = c.race_tss || 0;
      var tgtH = tgt ? Math.max(8, (tgt / maxT) * PLOT) : 0;
      var actH = act ? Math.max(4, (act / maxT) * PLOT) : 0;
      var plH = planned ? Math.max(4, (planned / maxT) * PLOT) : 0;
      var raceH = race ? Math.max(4, (race / maxT) * PLOT) : 0;
      var isCur = c.state === 'current';
      var isRace = (c.race_items && c.race_items.length) || race;
      var tgtCls = 'rv-road-tgt';
      if (isRace) tgtCls += ' rv-road-tgt--race';
      else if (!generic && String(c.phase || '').indexOf('race') >= 0) tgtCls += ' rv-road-tgt--a-race';
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
          ? '<span class="rv-road-val rv-road-val--over" style="bottom:' + valBottom(actH) + 'px">' + Math.round(act) + ' · +' + delta + '</span>'
          : '<span class="rv-road-val" style="bottom:' + valBottom(actH) + 'px">' + Math.round(act) + '</span>';
      } else if (tgt) {
        var extra = race ? ' + race' : '';
        val = '<span class="rv-road-val" style="bottom:' + valBottom(Math.max(tgtH, plH + raceH)) + 'px">' + Math.round(planned || tgt) + extra + '</span>';
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

    var phaseHtml = '';
    if (!generic) {
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
      if (phaseSpans.length) {
        phaseHtml = '<div class="rv-road-phases" style="grid-template-columns:repeat(' + cols.length + ',minmax(0,1fr))">' + phaseSpans.join('') + '</div>';
      }
    }

    var insight = '';
    (data.phase_overruns || []).forEach(function (ov) {
      insight += phaseName(ov.phase) + ' ran about ' + Math.round(ov.mean_over_pct) + '% over. ';
    });

    var hint = data.plan_hint
      ? '<p class="rv-plan-hint">' + esc(data.plan_hint) + ' <a href="/v2/settings/plan">Add an A race</a></p>'
      : '';
    var chip = data.changed_chip
      ? '<span class="rv-chip rv-chip--warn">' + esc(data.changed_chip) + '</span>'
      : '';

    host.innerHTML =
      '<div class="rv-plan-road-head">' +
      '<div class="rv-plan-head-copy"><h2 class="rv-label">' + esc(label) + '</h2>' +
      '<p class="rv-plan-road-title">' + esc(title) + '</p>' + subLine + '</div>' +
      '<div class="rv-plan-head-actions">' + chip +
      '<a href="/v2/settings/plan" class="rv-plan-settings-link">Change plan settings</a></div></div>' +
      hint +
      (tiles.length ? '<div class="rv-plan-tiles">' + tiles.join('') + '</div>' : '') +
      '<div class="rv-road-grid" style="grid-template-columns:repeat(' + cols.length + ',minmax(0,1fr))">' + bars + '</div>' +
      phaseHtml +
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
      card.innerHTML =
        '<div class="rv-plan-week-head"><div class="rv-plan-head-copy">' +
        '<h2 class="rv-label">This week\'s load</h2>' +
        '<p class="rv-chart-sub">Where the target comes from, and how the planned sessions add up to it</p></div></div>';
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
    var phase = wl.mode === 'generic' ? 'general' : phaseName(wl.phase);
    var ac = window.AppCommon || {};
    var range = wl.week_start
      ? fmtWeekOf(wl.week_start, ac.addDaysISO ? ac.addDaysISO(wl.week_start, 6) : wl.week_start)
      : '';
    card.innerHTML =
      '<div class="rv-plan-week-head">' +
      '<div class="rv-plan-head-copy"><h2 class="rv-label">This week\'s load' + (range ? ' · ' + esc(range) : '') + (phase ? ' · ' + esc(phase) : '') + '</h2>' +
      '<p class="rv-chart-sub">Where the target comes from, and how the planned sessions add up to it</p></div>' +
      '<div class="rv-plan-week-nums">' + statusBadge(wl) +
      '<span class="rv-mono rv-plan-week-tss">' + esc(String(Math.round(total))) + '</span>' +
      '<span class="rv-mono rv-plan-week-den">/ ' + esc(String(Math.round(target))) + ' TSS</span></div></div>' +
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

  function mountWeekBoard(board, ws, weekEl, state, fetchWeek) {
    if (!board || !window.V2PlanWeekBoard) return;
    window.V2PlanWeekBoard.mount(board, {
      weekStart: ws,
      weekLoadEl: weekEl,
      renderWeekLoad: renderWeekLoad,
      onWeekChanged: function (w) { state.ws = w; },
      fetchWeek: fetchWeek,
      skipInitialFetch: true,
    });
  }

  function renderWarnings(host, w) {
    if (!host) return;
    if (!w) {
      host.innerHTML = '';
      host.hidden = true;
      return;
    }
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
    host.innerHTML = parts.length ? parts.join('') : '';
    host.hidden = !parts.length;
    host.querySelectorAll('[data-apply-warning]').forEach(function (btn) {
      btn.onclick = function () {
        fetch('/api/plan/revamp-warnings/apply?return=sections', {
          method: 'POST',
          credentials: 'include',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ warning_id: btn.getAttribute('data-apply-warning') }),
        }).then(function (r) {
          if (!r.ok) throw new Error('Could not reschedule. Try again.');
          return r.json();
        }).then(function (json) {
          if (json.board || json.week_load || json.road_column) {
            applyMutation(json);
          } else {
            renderWarnings(host, json);
          }
          if (window.RevampUI && window.RevampUI.showToast) window.RevampUI.showToast('Rescheduled');
        }).catch(function (e) {
          if (window.RevampUI && window.RevampUI.showToast) {
            window.RevampUI.showToast(e.message || 'Could not reschedule.');
          }
        });
      };
    });
  }

  function renderRail(rail, data, warnings, wl) {
    if (!rail) return;
    var railData = data || {};
    var next = railData.next_up || [];
    var nextHtml = '<p class="rv-subtitle">No upcoming session in the next few days.</p>';
    function kindBar(it) {
      var kind = String((it && (it.kind || it.session_type)) || '').toLowerCase();
      if (kind.indexOf('race') >= 0) return '#c9d400';
      if (kind.indexOf('quality') >= 0) return '#fca5a5';
      if (kind === 'run') return '#86efac';
      return '#c4b5fd';
    }
    if (next.length) {
      var it = next[0];
      nextHtml =
        '<span class="rv-plan-next-bar" style="background:' + kindBar(it) + '"></span>' +
        '<div><p class="rv-plan-next-title">' + esc(it.name || it.title || 'Session') + '</p>' +
        '<p class="rv-subtitle">' + esc(fmtNextUpDate(it.date || it.planned_date || '')) + '</p></div>';
    }
    var ruleRows = [];
    if (wl && wl.mode === 'generic') {
      ruleRows.push('<p class="rv-subtitle">No race plan — rules stay quiet until an A race is set.</p>');
    } else {
      ruleRows.push(
        '<div class="rv-rule-row"><span class="rv-rule-state rv-rule-state--ok">OK</span>' +
        '<span>Weekly training target excludes race-day load when a race is on the plan.</span></div>'
      );
      ((warnings && warnings.clashes) || []).forEach(function (c) {
        ruleRows.push(
          '<div class="rv-rule-row"><span class="rv-rule-state rv-rule-state--warn">WARN</span>' +
          '<span>' + esc(c.message) + '</span></div>'
        );
      });
      if (warnings && warnings.layout_error) {
        ruleRows.push(
          '<div class="rv-rule-row"><span class="rv-rule-state rv-rule-state--block">BLOCK</span>' +
          '<span>' + esc(warnings.layout_error.message || 'Plan layout blocked') + '</span></div>'
        );
      }
    }
    var axis = railData.focus_label ? esc(railData.focus_label) : '—';
    var perf =
      '<p class="rv-subtitle">Most room to grow: <strong>' + axis + '</strong>.</p>' +
      '<p class="rv-subtitle">Queue mobility or drills from Performance when filling the week.</p>';
    var coachChip = railData.coach_imported ? '<span class="rv-chip">IMPORTED</span>' : '';
    var coachNote = wl && wl.mode === 'generic'
      ? '<p class="rv-subtitle">Import coach sessions from the week board when your block is set up.</p>'
      : '<p class="rv-subtitle">Use <strong>Import coach week</strong> on the board when your coach sends a week.</p>';
    var reimport = '<a href="#v2-coach-import-open" class="rv-plan-settings-link" id="v2-rail-reimport">Re-import</a>';
    rail.innerHTML =
      '<section class="rv-card rv-stack rv-plan-rail-card"><span class="rv-label">Next up</span>' +
      '<div class="rv-plan-next">' + nextHtml + '</div></section>' +
      '<section class="rv-card rv-card--soft rv-stack rv-plan-rail-card"><div class="rv-row"><span class="rv-label">Coach week</span>' +
      coachChip + reimport + '</div>' + coachNote + '</section>' +
      '<section class="rv-card rv-stack rv-plan-rail-card"><div class="rv-row"><span class="rv-label">From Performance</span>' +
      '<a href="/v2/performance" class="rv-plan-settings-link">Why</a></div>' + perf + '</section>' +
      '<section class="rv-card rv-card--soft rv-stack rv-plan-rail-card"><span class="rv-label">Rules in play</span>' + ruleRows.join('') + '</section>';
    var re = document.getElementById('v2-rail-reimport');
    if (re) {
      re.onclick = function (ev) {
        ev.preventDefault();
        var open = document.getElementById('v2-coach-import-open');
        if (open) open.click();
      };
    }
  }

  function renderUpcomingSubtitle(races) {
    var sub = document.getElementById('rv-training-subtitle');
    if (!sub) return;
    var ac = window.AppCommon || {};
    var today = ac.todayISO ? ac.todayISO() : new Date().toISOString().slice(0, 10);
    sub.textContent = fmtHeaderDate(today);
    races = races || [];
    if (!races.length) return;
    var extra = races.length > 1 ? ' · ' + (races[1].name || '') + ' also planned' : '';
    sub.textContent = fmtHeaderDate(today) + ' · ' + (races[0].name || 'Race') + extra;
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

    renderUpcomingSubtitle([]);

    if (window.V2SyncToolbar) {
      window.V2SyncToolbar.mount(document.getElementById('v2-sync-toolbar'), {});
    }

    var warnHost = document.getElementById('v2-plan-warnings');
    var rail = document.getElementById('v2-plan-rail');

    var weekCache = {};
    var prefetchOnce = false;

    function cachePut(ws, data) {
      if (!ws || !data) return;
      weekCache[ws] = { board: data.board, week_load: data.week_load };
    }
    function cacheGet(ws) {
      return weekCache[ws] || null;
    }
    function cacheInvalidate(ws) {
      if (ws) delete weekCache[ws];
      else weekCache = {};
    }
    window.V2TrainingPlan.weekCachePut = cachePut;
    window.V2TrainingPlan.weekCacheInvalidate = cacheInvalidate;

    var etags = {};
    function fetchWeek(ws, sections) {
      var q = '/api/plan/revamp-week?week_start=' + encodeURIComponent(ws);
      if (sections) q += '&sections=' + encodeURIComponent(sections);
      var headers = {};
      if (etags[q]) headers['If-None-Match'] = etags[q];
      return fetch(q, { credentials: 'include', headers: headers }).then(function (r) {
        var tag = r.headers.get('ETag');
        if (tag) etags[q] = tag;
        if (r.status === 304) return { _notModified: true };
        return readOkJson(r);
      });
    }

    function applyPage(data) {
      if (!data) return;
      if (data.week_load !== undefined && road) road._weekLoad = data.week_load;
      if (data.road !== undefined) renderRoadChart(data.road, road, data.week_load);
      if (data.week_load !== undefined) renderWeekLoad(week, data.week_load);
      if (data.warnings !== undefined) renderWarnings(warnHost, data.warnings);
      if (data.rail !== undefined) renderRail(rail, data.rail, data.warnings, data.week_load);
      if (data.upcoming_races !== undefined) renderUpcomingSubtitle(data.upcoming_races);
      if (board && board._applyWeek) board._applyWeek(data);
    }

    function navFetch(ws, sections) {
      var cached = cacheGet(ws);
      var req = fetchWeek(ws, sections || 'board,week_load').then(function (data) {
        if (data && data._notModified) return cached || data;
        cachePut(ws, data);
        if (data && data.week_load !== undefined) renderWeekLoad(week, data.week_load);
        if (cached && board && board._applyWeek && state.ws === ws) board._applyWeek(data);
        return data;
      });
      if (cached) {
        if (cached.week_load !== undefined) renderWeekLoad(week, cached.week_load);
        return Promise.resolve(cached);
      }
      return req;
    }

    function prefetchAdj(ws) {
      if (prefetchOnce) return;
      prefetchOnce = true;
      var idle = window.requestIdleCallback || function (cb) { setTimeout(cb, 1); };
      idle(function () {
        var prev = ac.addDaysISO ? ac.addDaysISO(ws, -7) : ws;
        var next = ac.addDaysISO ? ac.addDaysISO(ws, 7) : ws;
        [prev, next].forEach(function (w) {
          if (w && !cacheGet(w)) {
            fetchWeek(w, 'board,week_load').then(function (d) { cachePut(w, d); });
          }
        });
      });
    }

    function loadAll() {
      return fetchWeek(state.ws).then(function (data) {
        if (data && data._notModified) return;
        cachePut(state.ws, data);
        applyPage(data);
        prefetchAdj(state.ws);
      }).catch(function (e) {
        var msg = e.message || friendlySectionError();
        sectionError(road, 'Road to race', msg, loadAll);
        sectionError(week, "This week's load", msg, loadAll);
        if (warnHost) {
          warnHost.hidden = false;
          sectionError(warnHost, 'Warnings', msg, loadAll);
        }
        sectionError(rail, 'Sidebar', msg, loadAll);
      });
    }

    mountWeekBoard(board, state.ws, week, state, navFetch);
    loadAll();
  }

  window.V2TrainingPlan = {
    renderRoadChart: renderRoadChart,
    renderWeekLoad: renderWeekLoad,
    renderWarnings: renderWarnings,
    renderRail: renderRail,
    sectionError: sectionError,
    applyMutation: applyMutation,
    patchRoadColumn: patchRoadColumn,
  };

  document.addEventListener('DOMContentLoaded', init);
})();