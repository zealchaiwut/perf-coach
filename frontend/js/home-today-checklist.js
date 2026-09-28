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

  function render(host, ctx) {
    if (!host) return Promise.resolve(false);
    ctx = ctx || {};
    var today = _todayISO();

    return Promise.all([
      fetch('/api/checklist/week').then(function (r) { return r.ok ? r.json() : null; }),
      fetch('/api/fuel/today').then(function (r) { return r.ok ? r.json() : null; }),
    ]).then(function (res) {
      var cl = res[0];
      var fuelToday = res[1];
      if (!cl || !cl.days) return false;

      var day = cl.days.find(function (d) { return d.date === today; });
      if (!day) return false;

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
            window.location.href = '/log#metrics';
          }
        });
      }

      return true;
    }).catch(function () {
      return false;
    });
  }

  window.HomeTodayChecklist = { render: render };
})();
