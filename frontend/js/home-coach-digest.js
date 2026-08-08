/**
 * Home Coach — digest card (brief v4). Week verdict + numbered focus rows
 * (digest.focus, up to 3 — see backend/services/coach_brief.py's
 * _digest_focus) + Full brief.
 */
(function () {
  'use strict';

  // Delegates to the shared escaper (issue #1603). The local copies
  // disagreed about the apostrophe, so identical content was safe on
  // some pages and attribute-injectable on others.
  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  function _changedCount(brief) {
    var n = 0;
    (brief.sections || []).forEach(function (s) {
      if (s && s.changed_since_yesterday) n += 1;
    });
    return n;
  }

  // One numbered focus row: rank badge + title, with a trailing progress
  // pill when digest.focus[i].progress is present (e.g. "6 / 12"), or a
  // plain "on track" pill once state reaches "done" — same vocabulary as
  // home-coach-strip.js's .hc-focus-item/.hc-f-n/.hc-q markup, extended
  // with a progress pill for the digest's roomier layout.
  function _focusRowHtml(row) {
    if (!row || !row.title) return '';
    var pillHtml = '';
    if (row.progress && row.progress.label) {
      pillHtml = '<span class="hc-f-p' + (row.state === 'done' ? ' ok' : '') + '">' + esc(row.progress.label) + '</span>';
    } else if (row.state === 'done') {
      pillHtml = '<span class="hc-f-p ok">on track</span>';
    }
    return (
      '<div class="hc-focus-item">' +
        '<span class="hc-f-n">' + esc(row.rank != null ? row.rank : '') + '</span>' +
        '<span class="hc-q">' + esc(row.title) + '</span>' +
        pillHtml +
      '</div>'
    );
  }

  function render(el, brief) {
    if (!el) return;
    if (!brief) {
      // "Plan" used to be plain text, not a link, and named the wrong tab —
      // races are created/edited on Performance (see the Race goal card's
      // own "/log#performance" link), not Plan. A user following this
      // literally would land on the Plan tab and not find anywhere to set
      // a race.
      el.innerHTML =
        '<div class="card-head"><h2 class="ttl">Coach</h2></div>' +
        '<div class="rec-empty">No coach brief yet. Set an A-race on ' +
          '<a href="/log#performance">Performance</a>.</div>';
      return;
    }
    var dig = brief.digest || {};
    var changed = _changedCount(brief);
    var focusHtml = (dig.focus || []).slice(0, 3).map(_focusRowHtml).join('');

    el.innerHTML =
      '<div class="hc-digest">' +
        '<div class="hc-dg-head">' +
          '<h2 class="hc-lbl">Coach · this week</h2>' +
          '<button type="button" class="hc-link" data-hc-open-brief>Full brief →</button>' +
        '</div>' +
        '<div class="hc-dg-verdict">' + esc(dig.week_verdict || '') + '</div>' +
        '<div class="hc-dg-sub">' + esc(dig.week_verdict_sub || '') + '</div>' +
        (focusHtml ? '<div class="hc-dg-focus">' + focusHtml + '</div>' : '') +
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
