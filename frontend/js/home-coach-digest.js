/**
 * Home Coach — digest card (brief v4). Week verdict + Full brief only.
 * Numbered focus rows are hidden for now (still in JSON for Hermes / later).
 */
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

  function _changedCount(brief) {
    var n = 0;
    (brief.sections || []).forEach(function (s) {
      if (s && s.changed_since_yesterday) n += 1;
    });
    return n;
  }

  function render(el, brief) {
    if (!el) return;
    if (!brief) {
      el.innerHTML =
        '<div class="card-head"><div class="ttl">Coach</div></div>' +
        '<div class="rec-empty">No coach brief yet — set an A-race on Plan.</div>';
      return;
    }
    var dig = brief.digest || {};
    var changed = _changedCount(brief);

    el.innerHTML =
      '<div class="hc-digest">' +
        '<div class="hc-dg-head">' +
          '<span class="hc-lbl">Coach · this week</span>' +
          '<button type="button" class="hc-link" data-hc-open-brief>Full brief →</button>' +
        '</div>' +
        '<div class="hc-dg-verdict">' + esc(dig.week_verdict || '') + '</div>' +
        '<div class="hc-dg-sub">' + esc(dig.week_verdict_sub || '') + '</div>' +
        '<div class="hc-dg-foot">' +
          '<span class="hc-dg-upd">' +
            (changed
              ? changed + ' section' + (changed === 1 ? '' : 's') + ' changed since yesterday'
              : 'No sections changed since yesterday') +
          '</span>' +
          '<button type="button" class="hc-link" data-hc-open-brief>Read →</button>' +
        '</div>' +
      '</div>';

    el.querySelectorAll('[data-hc-open-brief]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        if (window.CoachBrief && typeof window.CoachBrief.open === 'function') {
          window.CoachBrief.open(brief);
        }
      });
    });
  }

  window.HomeCoachDigest = { render: render };
})();
