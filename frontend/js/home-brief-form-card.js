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

  function _acwrPillVar(state) {
    if (state === 'caution') return 'var(--amber-soft)';
    if (state === 'high')    return 'var(--red-soft)';
    return 'var(--green-soft)';
  }

  function _acwrLabel(state) {
    if (state === 'caution') return 'Caution';
    if (state === 'high')    return 'High';
    return 'OK';
  }

  function _fmtLoad(v) {
    if (v == null) return '—';
    return String(Math.round(Number(v) * 10) / 10);
  }

  function renderSkeleton(el) {
    if (!el) return;
    el.innerHTML =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-activity"></i>Form</div>' +
      '</div>' +
      '<div class="brief-skeleton brief-skeleton--form">' +
        '<div class="brief-skel-row"></div>' +
        '<div class="brief-skel-row brief-skel-row--sm"></div>' +
      '</div>';
  }

  function renderUnavailable(el) {
    if (!el) return;
    el.innerHTML =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-activity"></i>Form</div>' +
      '</div>' +
      '<div class="brief-unavail">Brief unavailable</div>';
  }

  function render(el, brief) {
    if (!el) return;
    if (!brief) { renderUnavailable(el); return; }

    var form = brief.form || {};
    var flags = form.flags || {};
    var acwrState = flags.acwr_state || 'ok';
    var pillBg = _acwrPillVar(acwrState);

    el.innerHTML =
      '<div class="card-head">' +
        '<div class="ttl"><i class="ti ti-activity"></i>Form</div>' +
      '</div>' +
      '<div class="bfc-metrics">' +
        '<div class="bfc-tile">' +
          '<div class="bfc-val">' + esc(_fmtLoad(form.ctl)) + '</div>' +
          '<div class="bfc-lbl">CTL</div>' +
        '</div>' +
        '<div class="bfc-tile">' +
          '<div class="bfc-val">' + esc(_fmtLoad(form.atl)) + '</div>' +
          '<div class="bfc-lbl">ATL</div>' +
        '</div>' +
        '<div class="bfc-tile">' +
          '<div class="bfc-val">' + esc(_fmtLoad(form.tsb)) + '</div>' +
          '<div class="bfc-lbl">TSB</div>' +
        '</div>' +
        '<div class="bfc-tile">' +
          '<div class="bfc-pill" style="background:' + pillBg + '">' +
            'ACWR&nbsp;' + esc(_acwrLabel(acwrState)) +
          '</div>' +
        '</div>' +
      '</div>' +
      '<div class="bfc-interp">' + esc(form.interpretation || '') + '</div>';
  }

  window.HomeBriefFormCard = { render: render, renderSkeleton: renderSkeleton, renderUnavailable: renderUnavailable };
})();
