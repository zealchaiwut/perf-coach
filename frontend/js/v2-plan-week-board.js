(function () {
  'use strict';

  var esc = window.AppCommon ? window.AppCommon.escapeHtml.bind(window.AppCommon) : function (s) { return String(s); };

  function toast(msg) {
    if (window.RevampUI && window.RevampUI.showToast) {
      window.RevampUI.showToast(msg);
    }
  }

  function cardClass(item) {
    if (item.kind === 'rest') return 'rv-session--rest';
    if (item.kind === 'run') return 'rv-session--run';
    return 'rv-session--support';
  }

  function sessionCard(item) {
    var locked = item.locked || item.plan_source === 'coach';
    var cls = 'rv-session ' + cardClass(item) + (locked ? ' rv-session--locked' : '');
    var drag = locked ? '' : ' draggable="true"';
    var coach = locked ? '<span class="rv-coach-label">Coach</span>' : '';
    return (
      '<article class="' + cls + '"' + drag +
      ' data-id="' + esc(item.id) + '" data-date="' + esc(item.planned_date) + '"' +
      ' data-locked="' + (locked ? '1' : '0') + '" tabindex="0">' +
      coach +
      '<div class="rv-label">' + esc(item.name) + '</div>' +
      (item.estimated_tss != null ? '<span class="rv-subtitle">' + esc(String(item.estimated_tss)) + ' TSS</span>' : '') +
      (!locked ? (
        '<div class="rv-week-card-actions">' +
        '<label class="rv-subtitle">Move <select class="rv-move-select" data-move-id="' + esc(item.id) + '" aria-label="Move to day">' +
        '</select></label>' +
        '</div>'
      ) : '') +
      '</article>'
    );
  }

  function mount(host, options) {
    var state = { weekStart: options.weekStart, dragId: null, onWeekChanged: options.onWeekChanged };

    function weekQuery() {
      return '?week_start=' + encodeURIComponent(state.weekStart);
    }

    function load() {
      return fetch('/api/plan/revamp-week-board' + weekQuery(), { credentials: 'include' })
        .then(function (r) { return r.json(); });
    }

    function loadWeekLoad() {
      if (!options.weekLoadEl) return Promise.resolve();
      return fetch('/api/plan/revamp-week-load' + weekQuery(), { credentials: 'include' })
        .then(function (r) { return r.status === 204 ? null : r.json(); })
        .then(function (wl) {
          if (wl && options.renderWeekLoad) options.renderWeekLoad(options.weekLoadEl, wl);
        });
    }

    function render(data) {
      var head =
        '<div class="rv-row" style="justify-content:space-between;align-items:center;margin-bottom:12px">' +
        '<h2 class="rv-label">Week plan</h2>' +
        '<div class="rv-row">' +
        '<button type="button" class="rv-btn rv-btn--secondary" id="v2-week-prev" aria-label="Previous week">‹</button>' +
        '<span class="rv-subtitle" style="min-width:90px;text-align:center">' + esc(data.week_start) + '</span>' +
        '<button type="button" class="rv-btn rv-btn--secondary" id="v2-week-next" aria-label="Next week">›</button>' +
        '</div></div>';
      var cols = data.days.map(function (day) {
        var colCls = 'rv-week-col' + (day.rest_placeholder ? ' rv-week-col--rest' : '');
        var body = day.items.map(sessionCard).join('');
        if (day.rest_placeholder && !day.items.length) {
          body += '<div class="rv-session rv-session--rest">Rest</div>';
        }
        return (
          '<div class="' + colCls + '" data-date="' + esc(day.date) + '" data-weekday="' + day.weekday + '">' +
          '<div class="rv-week-col-head"><span>' + esc(day.label) + '</span>' +
          '<button type="button" class="rv-btn rv-btn--secondary rv-btn--small" data-add-date="' + esc(day.date) + '" title="Add session">+</button></div>' +
          '<div class="rv-week-col-body">' + body + '</div></div>'
        );
      }).join('');
      host.innerHTML = head + '<div class="rv-week-board">' + cols + '</div>';

      host.querySelectorAll('.rv-move-select').forEach(function (sel) {
        data.days.forEach(function (d) {
          var opt = document.createElement('option');
          opt.value = d.date;
          opt.textContent = d.label;
          sel.appendChild(opt);
        });
      });

      host.querySelector('#v2-week-prev').onclick = function () { shiftWeek(-7); };
      host.querySelector('#v2-week-next').onclick = function () { shiftWeek(7); };
      host.querySelectorAll('[data-add-date]').forEach(function (btn) {
        btn.onclick = function () {
          toast('Session editor (P3-8) opens on ' + btn.getAttribute('data-add-date'));
        };
      });
      bindDnD(host, data);
      bindCoachPopover(host);
      bindKeyboardMove(host);
    }

    function shiftWeek(days) {
      var ac = window.AppCommon || {};
      state.weekStart = ac.addDaysISO ? ac.addDaysISO(state.weekStart, days) : state.weekStart;
      if (state.onWeekChanged) state.onWeekChanged(state.weekStart);
      refresh();
    }

    function refresh() {
      load().then(render).then(loadWeekLoad);
    }

    function ruleEvaluate(id, targetDate, cb) {
      fetch('/api/plan/rule-evaluate', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'move', session_id: id, planned_date: targetDate }),
      }).then(function (r) { return r.json().then(function (b) { return { status: r.status, body: b }; }); })
        .then(cb);
    }

    function patchMove(id, targetDate, confirmWarnings, cb) {
      fetch('/api/planned-sessions/' + id, {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ planned_date: targetDate, confirm_warnings: !!confirmWarnings }),
      }).then(function (r) { return r.json().then(function (b) { return { status: r.status, body: b }; }); })
        .then(cb);
    }

    function applyMove(id, targetDate) {
      ruleEvaluate(id, targetDate, function (ev) {
        if (ev.body.level === 'block') {
          var msg = (ev.body.results && ev.body.results[0] && ev.body.results[0].message) || 'Move blocked';
          toast(msg);
          refresh();
          return;
        }
        function doPatch(confirm) {
          patchMove(id, targetDate, confirm, function (res) {
            if (res.status === 409 && res.body.needs_confirm) {
              var warn = (res.body.plan_rules && res.body.plan_rules[0] && res.body.plan_rules[0].message) || 'Confirm move?';
              if (window.confirm(warn)) doPatch(true);
              else refresh();
              return;
            }
            if (res.status >= 400) {
              toast('Could not move session');
              refresh();
              return;
            }
            refresh();
          });
        }
        doPatch(ev.body.level !== 'warn');
      });
    }

    function bindDnD(host, data) {
      host.querySelectorAll('.rv-session[draggable="true"]').forEach(function (card) {
        card.addEventListener('dragstart', function (ev) {
          state.dragId = card.getAttribute('data-id');
          ev.dataTransfer.setData('text/plain', state.dragId);
        });
      });
      host.querySelectorAll('.rv-week-col').forEach(function (col) {
        col.addEventListener('dragover', function (ev) { ev.preventDefault(); });
        col.addEventListener('drop', function (ev) {
          ev.preventDefault();
          var id = ev.dataTransfer.getData('text/plain') || state.dragId;
          var target = col.getAttribute('data-date');
          if (id && target) applyMove(id, target);
        });
      });
    }

    function bindCoachPopover(host) {
      var backdrop = document.getElementById('v2-coach-popover-backdrop');
      var pop = document.getElementById('v2-coach-popover');
      var body = document.getElementById('v2-coach-popover-body');
      var closeBtn = document.getElementById('v2-coach-popover-close');
      function close() {
        if (backdrop) backdrop.hidden = true;
        if (pop) pop.hidden = true;
      }
      if (closeBtn) closeBtn.onclick = close;
      if (backdrop) backdrop.onclick = close;
      host.querySelectorAll('.rv-session--locked').forEach(function (card) {
        card.addEventListener('click', function () {
          var id = card.getAttribute('data-id');
          var item = null;
          data.days.forEach(function (d) {
            d.items.forEach(function (it) { if (it.id === id) item = it; });
          });
          if (!item) return;
          if (body) body.textContent = item.notes || 'No notes for this coach session.';
          if (backdrop) backdrop.hidden = false;
          if (pop) pop.hidden = false;
        });
      });
    }

    function bindKeyboardMove(host) {
      host.querySelectorAll('.rv-move-select').forEach(function (sel) {
        sel.addEventListener('change', function () {
          var id = sel.getAttribute('data-move-id');
          var target = sel.value;
          var card = host.querySelector('[data-id="' + id + '"]');
          var origin = card ? card.getAttribute('data-date') : null;
          if (target && id && target !== origin) {
            applyMove(id, target);
          }
          sel.selectedIndex = 0;
        });
      });
    }

    refresh();
  }

  window.V2PlanWeekBoard = { mount: mount };
})();