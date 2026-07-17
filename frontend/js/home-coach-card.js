(function () {
  'use strict';

  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  var _HEADER =
    '<div class="card-head">' +
      '<div class="ttl"><i class="ti ti-brain"></i>Coach</div>' +
      '<a href="/log#plan">Full plan &#8594;</a>' +
    '</div>';

  function _skeletonHtml() {
    return _HEADER +
      '<div class="coach-skeleton">' +
        '<div class="coach-skel-line coach-skel-line--wide"></div>' +
        '<div class="coach-skel-line"></div>' +
        '<div class="coach-skel-pills">' +
          '<div class="coach-skel-pill"></div>' +
          '<div class="coach-skel-pill"></div>' +
        '</div>' +
        '<div class="coach-skel-line coach-skel-line--narrow"></div>' +
      '</div>';
  }

  function _unavailableHtml() {
    return _HEADER +
      '<div class="coach-unavail">' +
        '<p class="coach-unavail__msg">No active race goal.</p>' +
        '<p class="coach-unavail__hint">' +
          'Set a goal in the <a href="#home-goal-card">Race goal card</a> ' +
          'to unlock your coaching plan.' +
        '</p>' +
      '</div>';
  }

  function _goalLine(goal) {
    if (!goal) return '';
    var distMap = { '5k': '5 K', '10k': '10 K', half: 'HM', marathon: 'Marathon' };
    var distLabel = distMap[goal.race_distance] || esc(goal.race_distance);
    var raceDate = goal.race_date ? new Date(goal.race_date + 'T00:00:00') : null;
    var dateStr = '';
    if (raceDate) {
      var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
      dateStr = ' · ' + months[raceDate.getMonth()] + ' ' + raceDate.getDate();
    }
    var timeStr = goal.target_time ? _fmtSeconds(goal.target_time) : '';
    return '<div class="coach-goal-line">' +
      (timeStr ? esc(timeStr) + ' ' : '') + esc(distLabel) + esc(dateStr) +
    '</div>';
  }

  function _fmtSeconds(s) {
    s = Math.max(0, Math.round(s));
    var h = Math.floor(s / 3600);
    var m = Math.floor((s % 3600) / 60);
    var sec = s % 60;
    if (sec === 0) return h + ':' + (m < 10 ? '0' : '') + m;
    return h + ':' + (m < 10 ? '0' : '') + m + ':' + (sec < 10 ? '0' : '') + sec;
  }

  function _leverPillsHtml(levers) {
    if (!Array.isArray(levers) || !levers.length) return '';
    return '<div class="coach-levers">' +
      levers.map(function (lever) {
        var isLocked = lever.indexOf('locked') !== -1;
        var cls = 'coach-lever-pill' + (isLocked ? ' coach-lever-pill--locked' : '');
        return '<span class="' + cls + '">' + esc(lever) + '</span>';
      }).join('') +
    '</div>';
  }

  function _directiveHtml(directive) {
    return '<p class="coach-directive">' + esc(directive) + '</p>';
  }

  function _projectionHtml(projection) {
    return '<div class="coach-projection">' + esc(projection) + '</div>';
  }

  function _fullMessageHtml(text) {
    return '<div class="coach-full-msg" hidden>' +
      '<pre class="coach-full-pre">' + esc(text) + '</pre>' +
    '</div>';
  }

  function _expandBtnHtml() {
    return '<button type="button" class="coach-expand-btn" aria-expanded="false">' +
      'Full message &#8594;' +
    '</button>';
  }

  function _wireExpand(el) {
    var btn = el.querySelector('.coach-expand-btn');
    var full = el.querySelector('.coach-full-msg');
    if (!btn || !full) return;
    btn.addEventListener('click', function () {
      var expanded = full.hasAttribute('hidden');
      if (expanded) {
        full.removeAttribute('hidden');
        btn.setAttribute('aria-expanded', 'true');
        btn.textContent = 'Hide message ↑';
      } else {
        full.setAttribute('hidden', '');
        btn.setAttribute('aria-expanded', 'false');
        btn.innerHTML = 'Full message &#8594;';
      }
    });
  }

  function renderCoachCard(el) {
    if (!el) return;
    el.innerHTML = _skeletonHtml();

    var goalData = null;
    var msgData = null;
    var gotGoal = false;
    var gotMsg = false;

    function _tryRender() {
      if (!gotGoal || !gotMsg) return;

      if (!goalData || !goalData.goal) {
        el.innerHTML = _unavailableHtml();
        return;
      }

      var goal = goalData.goal;
      var msg = msgData && msgData.message ? msgData.message : null;
      var planState = msg && msg.plan_state_snapshot ? msg.plan_state_snapshot : null;

      var directive = '';
      var projection = '';
      var levers = [];

      if (planState) {
        var loadLever = ((planState.levers || {}).load) || {};
        var weightLever = ((planState.levers || {}).weight) || {};

        if (loadLever.state === 'locked') {
          var unlockDate = loadLever.unlock_date;
          if (unlockDate) {
            var ud = new Date(unlockDate + 'T00:00:00');
            var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
            levers.push('load: locked until ' + ud.getDate() + ' ' + months[ud.getMonth()]);
          } else {
            levers.push('load: locked');
          }
        } else if (loadLever.state === 'available') {
          levers.push('load: available to ramp');
        }

        if (typeof weightLever.logged_days === 'number') {
          levers.push('weight: measurement ' + weightLever.logged_days + '/' + (weightLever.total_days || 14) + ' days');
        }
      }

      if (msg && msg.text) {
        var paragraphs = msg.text.split(/\n\n+/).map(function (p) { return p.trim(); }).filter(Boolean);
        directive = paragraphs[0] || '';
        var projPara = paragraphs.filter(function (p) { return p.indexOf('Projection:') === 0; })[0] || '';
        if (projPara) {
          projection = projPara.replace(/^Projection:\s*/, '');
        }
      }

      el.innerHTML = _HEADER +
        _goalLine(goal) +
        (projection ? _projectionHtml(projection) : '') +
        (levers.length ? _leverPillsHtml(levers) : '') +
        (directive ? _directiveHtml(directive) : '') +
        (msg && msg.text ? _expandBtnHtml() + _fullMessageHtml(msg.text) : '');

      _wireExpand(el);
    }

    fetch('/api/coach/goal')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { goalData = data; gotGoal = true; _tryRender(); })
      .catch(function () { gotGoal = true; _tryRender(); });

    fetch('/api/coach/weekly-message')
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) { msgData = data; gotMsg = true; _tryRender(); })
      .catch(function () { gotMsg = true; _tryRender(); });
  }

  window.HomeCoachCard = { render: renderCoachCard };
})();
