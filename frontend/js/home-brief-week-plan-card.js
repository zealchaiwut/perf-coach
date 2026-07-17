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

  function _fmtDuration(min) {
    if (min == null) return '';
    return min + 'min';
  }

  function _capitalize(s) {
    if (!s) return '';
    return s.charAt(0).toUpperCase() + s.slice(1);
  }

  /* Reorder days so today is first, tomorrow second, rest follow in date order. */
  function _sortDays(days) {
    if (!Array.isArray(days) || !days.length) return [];
    var sorted = days.slice().sort(function (a, b) {
      return a.date < b.date ? -1 : a.date > b.date ? 1 : 0;
    });
    return sorted;
  }

  function renderSkeleton(el) {
    if (!el) return;
    el.innerHTML =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-calendar-week"></i>Week plan</div>' +
      '</div>' +
      '<div class="brief-skeleton brief-skeleton--week">' +
        '<div class="brief-skel-row"></div>' +
        '<div class="brief-skel-row"></div>' +
        '<div class="brief-skel-row brief-skel-row--sm"></div>' +
      '</div>';
  }

  function renderUnavailable(el) {
    if (!el) return;
    el.innerHTML =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-calendar-week"></i>Week plan</div>' +
      '</div>' +
      '<div class="brief-unavail">Brief unavailable</div>';
  }

  function render(el, brief) {
    if (!el) return;
    if (!brief) { renderUnavailable(el); return; }

    var weekPlan = brief.week_plan || {};
    var days = _sortDays(weekPlan.days);

    var rowsHTML = days.map(function (d) {
      var dayLabel = esc(d.day || '');
      if (!d.planned) {
        return '<div class="bwp-row bwp-row--rest">' +
          '<span class="bwp-day">' + dayLabel + '</span>' +
          '<span class="bwp-type bwp-type--rest">Rest</span>' +
        '</div>';
      }
      var typeLabel = esc(_capitalize(d.session_type || ''));
      var dur = _fmtDuration(d.duration_min);
      return '<div class="bwp-row">' +
        '<span class="bwp-day">' + dayLabel + '</span>' +
        '<span class="bwp-type">' + typeLabel + '</span>' +
        (dur ? '<span class="bwp-dur">' + esc(dur) + '</span>' : '') +
      '</div>';
    }).join('');

    el.innerHTML =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-calendar-week"></i>Week plan</div>' +
      '</div>' +
      '<div class="bwp-list">' + (rowsHTML || '<div class="brief-unavail">No plan data</div>') + '</div>';
  }

  window.HomeBriefWeekPlanCard = { render: render, renderSkeleton: renderSkeleton, renderUnavailable: renderUnavailable };
})();
