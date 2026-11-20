(function () {
  'use strict';

  var esc = window.AppCommon ? window.AppCommon.escapeHtml.bind(window.AppCommon) : function (s) { return String(s); };

  function section(el, html) {
    if (el) el.innerHTML = html;
  }

  function renderRoadChart(data, host) {
    if (!host || !data.columns || !data.columns.length) return;
    var cols = data.columns;
    var maxT = 1;
    cols.forEach(function (c) {
      maxT = Math.max(maxT, c.target_tss || 0, c.actual_tss || 0, (c.planned_tss || 0) + (c.actual_tss || 0));
    });
    var h = 180;
    var pad = 8;
    var bw = Math.max(12, Math.floor(600 / cols.length) - 4);
    var parts = ['<svg class="rv-road-chart" viewBox="0 0 ' + (cols.length * (bw + pad) + pad) + ' ' + (h + 40) + '" role="img" aria-label="Load plan chart">'];
    cols.forEach(function (c, i) {
      var x = pad + i * (bw + pad);
      var tgtH = c.target_tss ? (c.target_tss / maxT) * (h - 20) : 0;
      var fill = c.over_target ? '#f59e0b' : (c.state === 'done' ? '#1f3b8a' : '#c9d2e3');
      parts.push('<rect x="' + x + '" y="' + (h - tgtH) + '" width="' + bw + '" height="' + tgtH + '" fill="none" stroke="#8ba7e6" stroke-dasharray="4 3"/>');
      if (c.state === 'done' && c.actual_tss) {
        var actH = (c.actual_tss / maxT) * (h - 20);
        parts.push('<rect x="' + x + '" y="' + (h - actH) + '" width="' + bw + '" height="' + actH + '" fill="' + fill + '" rx="3"/>');
      } else if (c.state !== 'done') {
        var pl = (c.planned_tss || 0) + (c.race_tss || 0);
        var plH = pl ? (pl / maxT) * (h - 20) : 0;
        parts.push('<rect x="' + x + '" y="' + (h - plH) + '" width="' + bw + '" height="' + plH + '" fill="#e8ecf4" stroke="#c9d2e3" stroke-dasharray="3 2"/>');
        if (c.race_tss) {
          var rh = (c.race_tss / maxT) * (h - 20);
          parts.push('<rect x="' + x + '" y="' + (h - plH) + '" width="' + bw + '" height="' + rh + '" fill="#bef264" opacity="0.9"/>');
        }
      }
      if (c.phase) {
        parts.push('<text x="' + (x + bw / 2) + '" y="' + (h + 14) + '" text-anchor="middle" font-size="9" fill="#56627f">' + esc(c.phase).slice(0, 6) + '</text>');
      }
      parts.push('<title>Week ' + esc(c.week_start) + ' target ' + esc(String(c.target_tss || '—')) + '</title>');
    });
    parts.push('</svg>');
    if (data.phase_overruns && data.phase_overruns.length) {
      data.phase_overruns.forEach(function (p) {
        parts.push('<p class="rv-subtitle">Phase ' + esc(p.phase) + ' ran ~' + esc(String(p.mean_over_pct)) + '% over target on average.</p>');
      });
    }
    host.innerHTML = '<h2 class="rv-label">Road to ' + esc(data.race_name) + '</h2>' +
      '<p class="rv-subtitle">' + esc(data.block_start) + ' → ' + esc(data.race_date) + '</p>' + parts.join('');
  }

  function renderWeekLoad(card, wl) {
    if (!card || !wl) return;
    var headroom = wl.headroom_state === 'under_target'
      ? '<span style="color:#15803d">About ' + Math.abs(Math.round(wl.headroom_tss)) + ' TSS left to target</span>'
      : wl.headroom_state === 'over_target'
        ? '<span style="color:#b45309">Over target</span>'
        : '<span style="color:#b91c1c">Over ACWR ceiling</span>';
    card.innerHTML =
      '<h2 class="rv-label">This week</h2>' +
      '<div class="rv-row" style="flex-wrap:wrap;gap:10px">' +
      '<div class="rv-card rv-stack" style="flex:1;min-width:120px"><span class="rv-subtitle">Baseline</span><strong>' + esc(String(wl.baseline_tss)) + '</strong></div>' +
      '<div class="rv-card rv-stack" style="flex:1;min-width:120px"><span class="rv-subtitle">' + esc(wl.phase) + '</span><strong>' + esc(String(wl.phase_factor_pct)) + '%</strong></div>' +
      '<div class="rv-card rv-stack" style="flex:1;min-width:120px"><span class="rv-subtitle">Target</span><strong>' + esc(String(wl.target_tss)) + '</strong></div>' +
      '<div class="rv-card rv-stack" style="flex:1;min-width:120px"><span class="rv-subtitle">Ceiling</span><strong>' + esc(String(wl.acwr_ceiling)) + '</strong><span class="rv-subtitle">28d ' + esc(String(wl.trailing_28d_avg)) + '</span></div>' +
      '</div>' +
      '<div class="rv-load-bar" style="position:relative;height:28px;background:#eef2fb;border-radius:8px;margin:12px 0">' +
      '<span style="position:absolute;left:' + Math.min(95, (wl.logged_tss / wl.target_tss) * 100) + '%;top:-6px;font-size:10px">▼ target</span>' +
      '<span style="display:block;height:100%;width:' + Math.min(100, (wl.logged_tss / Math.max(wl.acwr_ceiling, wl.target_tss)) * 100) + '%;background:#1f3b8a;border-radius:8px"></span></div>' +
      (wl.race_note ? '<p class="rv-subtitle">' + esc(wl.race_note) + '</p>' : '') +
      headroom;
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
    var ws = ac.addDaysISO ? ac.addDaysISO(ac.todayISO(), monOffset) : ac.todayISO();
    if (window.V2SyncToolbar) {
      window.V2SyncToolbar.mount(document.getElementById('v2-sync-toolbar'), {});
    }
    var warnHost = document.createElement('section');
    warnHost.className = 'rv-card rv-stack';
    warnHost.id = 'v2-plan-warnings';
    warnHost.setAttribute('aria-label', 'Plan warnings');
    if (shell && shell.firstChild) shell.insertBefore(warnHost, shell.firstChild);

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

    Promise.all([
      fetch('/api/plan/revamp-road-chart', { credentials: 'include' }),
      fetch('/api/plan/revamp-week-load?week_start=' + encodeURIComponent(ws), { credentials: 'include' }),
      fetch('/api/plan/revamp-warnings', { credentials: 'include' }),
    ]).then(function (res) {
      return Promise.all([
        res[0].status === 204 ? null : res[0].json(),
        res[1].status === 204 ? null : res[1].json(),
        res[2].json(),
      ]);
    }).then(function (pair) {
      if (!pair[0] && !pair[1]) {
        section(shell, '<p class="rv-section-state">Add a planned A race to see the load plan.</p>');
        return;
      }
      if (pair[2]) renderWarnings(pair[2]);
      if (pair[0]) renderRoadChart(pair[0], road);
      if (pair[1]) renderWeekLoad(week, pair[1]);
      if (board && window.V2PlanWeekBoard) {
        window.V2PlanWeekBoard.mount(board, {
          weekStart: ws,
          weekLoadEl: week,
          renderWeekLoad: renderWeekLoad,
          onWeekChanged: function (w) { ws = w; },
        });
      }
    }).catch(function () {
      section(shell, '<p class="rv-section-state" role="alert">Could not load plan.</p>');
    });
  }

  document.addEventListener('DOMContentLoaded', init);
})();