(function () {
  'use strict';

  var DAY_NAMES = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

  var TYPE_COLORS = {
    run: '#3b82f6',
    lift: '#8b5cf6',
    wod: '#f97316',
    bike: '#14b8a6',
  };

  var TYPE_ORDER = ['run', 'lift', 'wod', 'bike'];

  var USER_KEY = 'perf-coach.current-user-id';

  function toISODate(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return y + '-' + m + '-' + day;
  }

  function getMondayOf(d) {
    var date = new Date(d);
    date.setHours(0, 0, 0, 0);
    var dow = date.getDay();
    var diff = dow === 0 ? -6 : 1 - dow;
    date.setDate(date.getDate() + diff);
    return date;
  }

  function parseWeekParam() {
    var params = new URLSearchParams(window.location.search);
    var w = params.get('week');
    if (w && /^\d{4}-\d{2}-\d{2}$/.test(w)) {
      var d = new Date(w + 'T00:00:00');
      if (!isNaN(d.getTime())) return getMondayOf(d);
    }
    return getMondayOf(new Date());
  }

  function pushWeekParam(monday) {
    var params = new URLSearchParams(window.location.search);
    params.set('week', toISODate(monday));
    history.pushState({}, '', window.location.pathname + '?' + params);
  }

  function weekContainsToday(monday) {
    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var sunday = new Date(monday);
    sunday.setDate(sunday.getDate() + 6);
    return today >= monday && today <= sunday;
  }

  function buildWeekLabel(monday) {
    if (weekContainsToday(monday)) return 'This week';
    var sunday = new Date(monday);
    sunday.setDate(sunday.getDate() + 6);
    var month = monday.toLocaleDateString('en-US', { month: 'short' });
    return month + ' ' + monday.getDate() + ' – ' + sunday.getDate();
  }

  function getCurrentUserId() {
    return localStorage.getItem(USER_KEY) || null;
  }

  var currentMonday = parseWeekParam();
  var currentUserId = null;

  async function loadAndRender(monday, userId) {
    var sunday = new Date(monday);
    sunday.setDate(sunday.getDate() + 6);

    var fromStr = toISODate(monday);
    var toStr = toISODate(sunday);

    var url = '/api/training-log?from=' + fromStr + '&to=' + toStr + '&include_rest=false';
    if (userId) url += '&user_id=' + encodeURIComponent(userId);

    var dotsByDate = {};
    try {
      var res = await fetch(url);
      if (res.ok) {
        var data = await res.json();
        (data.weeks || []).forEach(function (week) {
          (week.entries || []).forEach(function (entry) {
            var t = (entry.type || '').toLowerCase();
            if (TYPE_COLORS[t]) {
              if (!dotsByDate[entry.date]) dotsByDate[entry.date] = [];
              if (dotsByDate[entry.date].indexOf(t) === -1) dotsByDate[entry.date].push(t);
            }
          });
        });
      }
    } catch (_) {
      // network error — render with empty dots
    }

    render(monday, dotsByDate);
  }

  function render(monday, dotsByDate) {
    var strip = document.getElementById('week-strip');
    if (!strip) return;

    var today = new Date();
    today.setHours(0, 0, 0, 0);
    var todayStr = toISODate(today);

    var pillsHtml = '';
    for (var i = 0; i < 7; i++) {
      var d = new Date(monday);
      d.setDate(d.getDate() + i);
      var dateStr = toISODate(d);
      var isToday = dateStr === todayStr;

      var typesForDay = dotsByDate[dateStr] || [];
      var dotsHtml = TYPE_ORDER
        .filter(function (t) { return typesForDay.indexOf(t) !== -1; })
        .map(function (t) {
          return '<span class="wd-dot" style="background:' + TYPE_COLORS[t] + '"></span>';
        })
        .join('');

      pillsHtml +=
        '<div class="day-pill' + (isToday ? ' today' : '') + '">' +
          '<span class="day-name">' + DAY_NAMES[i] + '</span>' +
          '<span class="day-num">' + d.getDate() + '</span>' +
          '<div class="wd-dots">' + dotsHtml + '</div>' +
        '</div>';
    }

    strip.innerHTML =
      '<div class="ws-nav">' +
        '<button id="week-prev" class="ws-chevron" aria-label="Previous week">&#8249;</button>' +
        '<span id="week-label" class="ws-label">' + buildWeekLabel(monday) + '</span>' +
        '<button id="week-next" class="ws-chevron" aria-label="Next week">&#8250;</button>' +
      '</div>' +
      '<div class="ws-pills">' + pillsHtml + '</div>';

    document.getElementById('week-prev').addEventListener('click', function () {
      currentMonday = new Date(currentMonday);
      currentMonday.setDate(currentMonday.getDate() - 7);
      pushWeekParam(currentMonday);
      loadAndRender(currentMonday, currentUserId);
    });

    document.getElementById('week-next').addEventListener('click', function () {
      currentMonday = new Date(currentMonday);
      currentMonday.setDate(currentMonday.getDate() + 7);
      pushWeekParam(currentMonday);
      loadAndRender(currentMonday, currentUserId);
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    currentUserId = getCurrentUserId();
    loadAndRender(currentMonday, currentUserId);
  });

  window.addEventListener('userReady', function (e) {
    var newId = (e.detail && e.detail.userId) ? e.detail.userId : null;
    if (newId !== currentUserId) {
      currentUserId = newId;
      loadAndRender(currentMonday, currentUserId);
    }
  });

  window.addEventListener('userChanged', function (e) {
    currentUserId = (e.detail && e.detail.userId) ? e.detail.userId : getCurrentUserId();
    loadAndRender(currentMonday, currentUserId);
  });
}());
