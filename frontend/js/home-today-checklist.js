/**
 * Home "Today · core & fuel" card (WC-27) — replaces home-morning when checklist loads.
 */
(function () {
  'use strict';

  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  function _todayISO() {
    return window.AppCommon.todayISO();
  }

  function _row(item, dayDate) {
    if (window.ChecklistShared) {
      return window.ChecklistShared.itemRowHtml(item, dayDate, { showSubtext: true });
    }
    return '<div class="cl-item">' + esc(item.label) + '</div>';
  }

  function _fuel(day, fuelToday) {
    var fd = (day && day.fuel_detail) || fuelToday || {};
    if (window.ChecklistShared) {
      var fuelItem = day && (day.items || []).find(function (it) { return it.kind === 'fuel'; });
      return window.ChecklistShared.fuelBoxesHtml(fd, fuelItem);
    }
    return '';
  }

  function showLoading(host) {
    if (!host) return;
    host.innerHTML =
      '<div class="htc-card htc-card--loading" aria-busy="true">' +
        '<div class="htc-head"><span class="htc-k">Today · core &amp; fuel</span></div>' +
        '<div class="htc-body">' +
          '<div class="htc-core-col"><div class="htc-skel htc-skel--row"></div>' +
            '<div class="htc-skel htc-skel--row"></div>' +
            '<div class="htc-skel htc-skel--row htc-skel--short"></div></div>' +
          '<div class="htc-fuel-col"><div class="htc-skel htc-skel--fuel"></div></div>' +
        '</div>' +
      '</div>';
  }

  function _emptyState(host) {
    host.innerHTML =
      '<div class="htc-card htc-card--empty">' +
        '<div class="htc-head"><span class="htc-k">Today · checklist</span></div>' +
        '<div class="htc-body htc-body--empty">' +
          '<p class="htc-empty-msg">No checklist for today yet.</p>' +
          '<a href="/habits" class="htc-all-link">Open habits →</a>' +
        '</div>' +
      '</div>';
  }

  function _paint(host, ctx, cl, fuelToday) {
    var today = _todayISO();
    if (!cl || !cl.days) {
      _emptyState(host);
      return 'empty';
    }

    var day = cl.days.find(function (d) { return d.date === today; });
    if (!day) {
      _emptyState(host);
      return 'empty';
    }

      var score = day.score || { core_done: 0, core_total: 0 };
      var items = day.items || [];
      var core = items.filter(function (it) {
        return it.role === 'core' && it.kind !== 'fuel';
      });
      var optional = items.filter(function (it) {
        return it.role === 'optional' && it.kind !== 'fuel';
      });

      host.innerHTML =
        '<div class="htc-card">' +
          '<div class="htc-head">' +
            '<span class="htc-k">Today · ' + score.core_done + ' of ' + score.core_total + ' core</span>' +
            '<a href="/habits" class="htc-all-link">Full checklist →</a>' +
          '</div>' +
          '<div class="htc-body">' +
            '<div class="htc-core-col"><div class="clh-rows">' +
              core.map(function (it) { return _row(it, today); }).join('') +
            '</div></div>' +
            '<div class="htc-fuel-col">' + _fuel(day, fuelToday) + '</div>' +
          '</div>' +
          (optional.length
            ? '<div class="htc-optional">' +
                '<span class="htc-opt-lab">Optional</span>' +
                optional.map(function (it) {
                  var done = it.state === 'done';
                  return '<span class="htc-opt' + (done ? ' htc-opt--done' : '') + '">' +
                    esc(it.label) + '</span>';
                }).join('') +
              '</div>'
            : '') +
          '<div class="htc-foot">' +
            '<span class="htc-foot-tx">Sleep, HRV, energy — log daily metrics</span>' +
            '<button type="button" class="htc-metrics-btn" id="htc-metrics-log">Log metrics</button>' +
          '</div>' +
        '</div>';

      if (window.ChecklistUI && typeof window.ChecklistUI.wireItems === 'function') {
        window.ChecklistUI.wireItems(host, cl, function () {
          if (typeof ctx.onRefresh === 'function') ctx.onRefresh();
          else render(host, ctx);
        });
      }

      var metricsBtn = host.querySelector('#htc-metrics-log');
      if (metricsBtn) {
        metricsBtn.addEventListener('click', function () {
          var row = document.getElementById('row-log');
          if (row) {
            row.hidden = false;
            row.scrollIntoView({ behavior: 'smooth', block: 'start' });
          } else {
            window.location.href = '/home#log-metrics';
          }
        });
      }

      return 'ok';
  }

  function render(host, ctx) {
    if (!host) return Promise.resolve('error');
    ctx = ctx || {};

    var clPromise = (ctx.checklistWeek !== undefined)
      ? Promise.resolve(ctx.checklistWeek)
      : fetch('/api/checklist/week')
          .then(function (r) { return r.ok ? r.json() : null; })
          .catch(function () { return null; });

    var fuelPromise = (ctx.fuelToday !== undefined)
      ? Promise.resolve(ctx.fuelToday)
      : fetch('/api/fuel/today')
          .then(function (r) { return r.ok ? r.json() : null; })
          .catch(function () { return null; });

    return Promise.all([clPromise, fuelPromise]).then(function (res) {
      if (res[0] === null) return 'error';
      return _paint(host, ctx, res[0], res[1]);
    }).catch(function () {
      return 'error';
    });
  }

  window.HomeTodayChecklist = { render: render, showLoading: showLoading };
})();
