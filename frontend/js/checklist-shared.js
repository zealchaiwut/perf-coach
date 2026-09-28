/**
 * Shared checklist row + fuel rendering (WC-27) — used by Habits mock and Home card.
 */
(function () {
  'use strict';

  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  function stateClass(state, role) {
    if (window.ChecklistUI && window.ChecklistUI.stateClass) {
      return window.ChecklistUI.stateClass(state, role);
    }
    if (state === 'done') return 'cl-done';
    if (state === 'missed') return 'cl-missed';
    if (state === 'skipped') return 'cl-skipped';
    if (state === 'upcoming') return 'cl-upcoming';
    if (role === 'optional') return 'cl-optional';
    return 'cl-pending';
  }

  function stateIcon(state) {
    if (state === 'done') return '<i class="ti ti-check"></i>';
    if (state === 'missed') return '<i class="ti ti-x"></i>';
    if (state === 'skipped') return '<span class="cl-skip-lab">skip</span>';
    return '';
  }

  function autoFillLink(item) {
    var src = (item && item.auto_fill_source) || '';
    if (src.indexOf('sleep') >= 0 || src.indexOf('weight') >= 0 || src.indexOf('metrics') >= 0) {
      return '/log#metrics';
    }
    if (src.indexOf('workout') >= 0 || src.indexOf('long_run') >= 0) {
      return '/log';
    }
    return (item && item.link) || '/habits';
  }

  function itemRowHtml(item, dayDate, opts) {
    opts = opts || {};
    var cls = stateClass(item.state, item.role);
    var isAuto = !!item.auto_fill_source;
    var tickable = !!(item.tick && item.state !== 'done' && item.state !== 'shown' && !isAuto);
    var link = isAuto ? autoFillLink(item) : (item.link || '');
    var href = link ? ' href="' + esc(link) + '"' : '';
    var tag = item.role === 'optional' ? '<span class="cl-role-tag">optional</span>' : '';
    var autoTag = isAuto ? '<span class="clh-auto-tag">AUTO</span>' : '';
    var prog = '';
    if (item.weekly_progress) {
      prog = '<span class="cl-week-prog">' +
        Math.round(item.weekly_progress.value) + '/' +
        Math.round(item.weekly_progress.target) + '</span>';
    }
    var sub = '';
    if (opts.showSubtext && item.kind === 'planned_session') {
      sub = '<span class="clh-row-sub">' +
        esc((item.session_type || '').replace(/_/g, ' ')) + '</span>';
    }
    return (
      '<div class="cl-item ' + cls + '" data-kind="' + esc(item.kind) + '" data-id="' + esc(item.id) + '"' +
        ' data-date="' + esc(dayDate) + '">' +
        (isAuto
          ? '<span class="cl-tick cl-tick--static clh-tick-auto" title="Auto-filled">&#8226;</span>'
          : tickable
            ? '<button type="button" class="cl-tick" aria-label="Mark done">' + stateIcon(item.state) + '</button>'
            : '<span class="cl-tick cl-tick--static">' + stateIcon(item.state) + '</span>') +
        '<a class="cl-label"' + href + '>' + esc(item.label) + tag + autoTag + prog + sub + '</a>' +
        (item.tick && item.tick.skip_url && item.state === 'pending'
          ? '<button type="button" class="cl-skip-btn">Skip</button>' : '') +
      '</div>'
    );
  }

  function fuelBoxesHtml(fuelDetail, fuelItem) {
    var fd = fuelDetail || {};
    var targets = fd.targets || {};
    var fp = fd.food_portions || {};
    var budget = (fuelItem && fuelItem.fuel && fuelItem.fuel.budget) || fd.budget;
    var dayType = fd.day_type || (fuelItem && fuelItem.fuel && fuelItem.fuel.day_type) || 'rest';
    var phase = fd.week_phase_reason || (fd.week_phase ? String(fd.week_phase).replace(/_/g, ' ') : '');
    var deficitLab = fd.auto_periodize && fd.effective_deficit_kcal === 0
      ? 'Paused'
      : ('-' + (fd.deficit_applied || 0) + ' kcal');

    function box(lab, main, eq) {
      if (!main && !eq) return '';
      return '<div class="clh-fuel-box">' +
        '<span class="clh-fuel-val">' + esc(main) + '</span>' +
        '<span class="clh-fuel-lab">' + esc(lab) + '</span>' +
        (eq ? '<span class="clh-fuel-eq">' + esc(eq) + '</span>' : '') +
      '</div>';
    }

    var meatEq = fp.meat_g ? '≈ ' + fp.meat_g + ' g meat' : '';
    var riceEq = fp.rice_g ? '≈ ' + fp.rice_g + ' g rice' : '';
    var boxes = [
      targets.protein_g != null ? box('Protein', Math.round(targets.protein_g) + 'g', meatEq) : '',
      targets.carbs_g != null ? box('Carbs', Math.round(targets.carbs_g) + 'g', riceEq) : '',
      box('Deficit', deficitLab, ''),
    ].filter(Boolean).join('');

    if (!boxes && budget == null) return '';
    return (
      '<div class="clh-section">' +
        '<h3 class="clh-section-title">Fuel</h3>' +
        (phase ? '<p class="clh-fuel-daytype">' + esc(String(dayType).replace(/_/g, ' ')) +
          ' · ' + esc(phase) + '</p>' : '<p class="clh-fuel-daytype">' + esc(String(dayType).replace(/_/g, ' ')) + '</p>') +
        (budget != null
          ? '<p class="clh-fuel-budget">Budget <strong>' + Math.round(budget) + '</strong> kcal</p>'
          : '') +
        (boxes ? '<div class="clh-fuel-grid">' + boxes + '</div>' : '') +
        (fp.rice_carbs_per_100g
          ? '<p class="clh-fuel-note">Rice ≈ ' + fp.rice_carbs_per_100g + ' g carbs per 100 g cooked.</p>'
          : '<p class="clh-fuel-note">Fuel targets are informational — not ticked.</p>') +
      '</div>'
    );
  }

  window.ChecklistShared = {
    itemRowHtml: itemRowHtml,
    fuelBoxesHtml: fuelBoxesHtml,
    autoFillLink: autoFillLink,
    stateClass: stateClass,
  };
})();
