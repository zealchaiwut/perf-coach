(function () {
  /* ---- Helpers ---- */

  function isoDate(d) {
    return d.getFullYear() + '-' +
      String(d.getMonth() + 1).padStart(2, '0') + '-' +
      String(d.getDate()).padStart(2, '0');
  }

  function currentMonday() {
    var bangkokDate = new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' });
    var parts = bangkokDate.split('-');
    var y = parseInt(parts[0], 10);
    var m = parseInt(parts[1], 10) - 1;
    var d = parseInt(parts[2], 10);
    var dow = new Date(y, m, d).getDay();
    var diff = (dow === 0) ? -6 : 1 - dow;
    return new Date(y, m, d + diff);
  }

  function daysRemainingInWeek() {
    var today = new Date();
    var day = today.getDay();
    /* weekday: Monday=0 … Sunday=6 */
    var weekday = (day === 0) ? 6 : day - 1;
    return 7 - weekday;
  }

  function _esc(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /* ---- Skeleton ---- */

  function _skeletonHTML() {
    var row =
      '<div class="hp-skel-row">' +
        '<div class="hp-skel hp-skel--icon"></div>' +
        '<div class="hp-skel-info">' +
          '<div class="hp-skel hp-skel--name"></div>' +
          '<div class="hp-skel hp-skel--bar"></div>' +
        '</div>' +
      '</div>';
    return row + row + row;
  }

  /* ---- Error ---- */

  function _showError(body) {
    body.innerHTML =
      '<div class="hp-error">Could not load habit progress. ' +
      '<button class="hp-retry" type="button">Retry</button></div>';
    var btn = body.querySelector('.hp-retry');
    if (btn) {
      btn.addEventListener('click', function () {
        var container = btn.closest('.hp-widget');
        if (container) _load(container);
      });
    }
  }

  /* ---- Render ---- */

  function _renderRows(container, habits, progressMap) {
    var body = container.querySelector('.hp-body');
    if (!body) return;

    if (habits.length === 0) {
      body.innerHTML =
        '<div class="hp-empty">Add habits to track your weekly goals — ' +
        '<a href="/habits">Add habits</a></div>';
      return;
    }

    var daysLeft = daysRemainingInWeek();

    /* Sort: incomplete first, completed last */
    var sorted = habits.slice().sort(function (a, b) {
      var ac = (progressMap[a.id] && progressMap[a.id].is_complete) ? 1 : 0;
      var bc = (progressMap[b.id] && progressMap[b.id].is_complete) ? 1 : 0;
      return ac - bc;
    });

    var rows = sorted.map(function (habit) {
      var prog = progressMap[habit.id] || {};
      var current = prog.current_value != null ? prog.current_value : 0;
      var target = prog.target;
      var rawPct = prog.percentage != null ? prog.percentage : 0;
      var pct = Math.min(100, rawPct);
      var isComplete = !!prog.is_complete;
      var unit = habit.unit ? ' ' + habit.unit : '';
      var icon = habit.icon || 'ti-checkbox';

      var valStr = target != null
        ? (Number.isInteger(current) ? current : current.toFixed(1)) +
          ' / ' + target + unit
        : '— / —';

      var checkHTML = isComplete
        ? '<span class="hp-check"><i class="ti ti-check"></i></span>'
        : '';

      return '<a class="hp-row' + (isComplete ? ' hp-row--complete' : '') +
        '" href="/habits#' + _esc(String(habit.id)) + '">' +
        '<span class="hp-icon"><i class="ti ' + _esc(icon) + '"></i></span>' +
        '<span class="hp-info">' +
          '<span class="hp-name-row">' +
            '<span class="hp-name">' + _esc(habit.name) + '</span>' +
            checkHTML +
            '<span class="hp-days">' + daysLeft + 'd left</span>' +
          '</span>' +
          '<span class="hp-meta">' + valStr + '</span>' +
          '<span class="hp-bar-outer">' +
            '<span class="hp-bar-inner" style="width:' + pct.toFixed(1) + '%"></span>' +
          '</span>' +
        '</span>' +
      '</a>';
    }).join('');

    body.innerHTML = rows;
  }

  /* ---- Load ---- */

  async function _load(container) {
    var body = container.querySelector('.hp-body');
    if (!body) return;

    body.innerHTML = _skeletonHTML();

    var habitsRes;
    try {
      habitsRes = await fetch('/api/habits');
    } catch (_) {
      _showError(body);
      return;
    }
    if (!habitsRes.ok) {
      if (habitsRes.status === 401) { window.location.href = '/login'; return; }
      _showError(body);
      return;
    }

    var habits;
    try { habits = await habitsRes.json(); } catch (_) { _showError(body); return; }

    if (habits.length === 0) {
      body.innerHTML =
        '<div class="hp-empty">Add habits to track your weekly goals — ' +
        '<a href="/habits">Add habits</a></div>';
      return;
    }

    var weekStart = isoDate(currentMonday());
    var progressResults = await Promise.all(
      habits.map(function (h) {
        return fetch('/api/habits/' + encodeURIComponent(h.id) + '/progress?week_start=' + weekStart)
          .then(function (r) { return r.ok ? r.json() : null; })
          .catch(function () { return null; });
      })
    );

    var progressMap = {};
    habits.forEach(function (h, i) {
      if (progressResults[i]) progressMap[h.id] = progressResults[i];
    });

    _renderRows(container, habits, progressMap);
  }

  /* ---- Init ---- */

  var _TITLE = "This week's progress";

  function init() {
    var container = document.getElementById('habits-progress-widget');
    if (!container) return;

    var ttl = container.querySelector('.hp-title');
    if (ttl) ttl.textContent = _TITLE;

    _load(container);

    document.addEventListener('visibilitychange', function () {
      if (document.visibilityState === 'visible') _load(container);
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
