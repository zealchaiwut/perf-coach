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

  var _WARN_GLYPH = '&#9888;&#xFE0E;';

  function renderSkeleton(el) {
    if (!el) return;
    el.innerHTML =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-bell"></i>Advisories</div>' +
      '</div>' +
      '<div class="brief-skeleton brief-skeleton--adv">' +
        '<div class="brief-skel-row"></div>' +
        '<div class="brief-skel-row brief-skel-row--sm"></div>' +
      '</div>';
  }

  function renderUnavailable(el) {
    if (!el) return;
    el.innerHTML =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-bell"></i>Advisories</div>' +
      '</div>' +
      '<div class="brief-unavail">Brief unavailable</div>';
  }

  function render(el, brief) {
    if (!el) return;
    if (!brief) { renderUnavailable(el); return; }

    var advisories = Array.isArray(brief.advisories) ? brief.advisories : [];

    var bodyHTML;
    if (!advisories.length) {
      bodyHTML = '<div class="bac-none">(none)</div>';
    } else {
      bodyHTML = '<ul class="bac-list">' +
        advisories.map(function (a) {
          var prefix = a.severity === 'warn'
            ? '<span class="bac-warn-glyph" aria-label="warning">' + _WARN_GLYPH + '</span> '
            : '';
          return '<li class="bac-item bac-item--' + esc(a.severity || 'info') + '">' +
            prefix + esc(a.text) +
          '</li>';
        }).join('') +
      '</ul>';
    }

    el.innerHTML =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-bell"></i>Advisories</div>' +
      '</div>' +
      bodyHTML;
  }

  window.HomeBriefAdvisoriesCard = { render: render, renderSkeleton: renderSkeleton, renderUnavailable: renderUnavailable };
})();
