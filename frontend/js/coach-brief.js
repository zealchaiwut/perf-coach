/**
 * Home Coach — full brief accordion (brief v4).
 * Opened from strip / digest. Max 3 sections with changed_since_yesterday open.
 * Proposal sections: Accept / Adjust / Not now → /api/preferences/proposals/*.
 */
(function () {
  'use strict';

  var _overlay = null;
  var _lastBrief = null;

  var CARD_HREF = {
    readiness: '/#',
    weight: '/weight',
    performance: '/log#performance',
    plan: '/log#plan',
    preferences: '/preferences',
  };

  function esc(s) {
    if (s == null) return '';
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function hiliteNums(s) {
    var t = esc(s);
    return t.replace(
      /(\d+(?:[.:]\d+)*)/g,
      '<strong class="hc-num">$1</strong>'
    );
  }

  function _badge(cadence) {
    if (cadence === 'today') return 'hc-bsec-badge hc-bsec-badge--daily';
    if (cadence === 'weekly') return 'hc-bsec-badge hc-bsec-badge--wk';
    if (cadence === 'proposal') return 'hc-bsec-badge hc-bsec-badge--proposal';
    return 'hc-bsec-badge';
  }

  function _badgeLabel(cadence, s) {
    if (s && (s.type === 'proposal' || (s.id || '').indexOf('proposal_') === 0)) {
      return 'PROPOSAL';
    }
    if (cadence === 'today') return 'TODAY';
    if (cadence === 'weekly') return 'WEEKLY';
    if (cadence === 'season') return 'SEASON';
    return (cadence || '').toUpperCase();
  }

  function _openIds(sections) {
    var flagged = [];
    var changed = [];
    (sections || []).forEach(function (s, i) {
      if (!s) return;
      var id = s.id || String(i);
      if (s.open_by_default) flagged.push(id);
      else if (s.changed_since_yesterday) changed.push(id);
    });
    if (flagged.length) return flagged.slice(0, 3);
    return changed.slice(0, 3);
  }

  function _isProposal(s) {
    return !!(s && (s.type === 'proposal' || (s.id || '').indexOf('proposal_') === 0));
  }

  function _proposalActions(s) {
    var p = s.proposal || {};
    if (p.status !== 'proposed') return '';
    var id = esc(p.id || '');
    return (
      '<div class="hc-prop-actions" data-proposal-id="' + id + '">' +
        '<button type="button" class="hc-prop-btn hc-prop-accept">Accept</button>' +
        '<button type="button" class="hc-prop-btn hc-prop-adjust">Adjust…</button>' +
        '<button type="button" class="hc-prop-btn hc-prop-decline">Not now</button>' +
      '</div>'
    );
  }

  function _sectionHtml(s, openSet) {
    var id = s.id || '';
    var isProposal = _isProposal(s);
    var isOpen = openSet.indexOf(id) >= 0;
    var link = s.card_link ? CARD_HREF[s.card_link] : null;
    var strip = s.evidence_strip || '';
    var stripHtml = '';
    if (strip) {
      stripHtml =
        '<div class="hc-ev">' +
          hiliteNums(strip) +
          (link && !isProposal
            ? ' → <a href="' + esc(link) + '">' + esc(s.card_link) + ' card</a>'
            : '') +
        '</div>';
    }
    var life = s.lifecycle
      ? '<div class="hc-prop-life">● ' + esc(s.lifecycle) + '</div>'
      : '';
    var unchanged = '';
    if (!s.changed_since_yesterday && s.cadence === 'season') {
      unchanged = '<span class="hc-unchanged">unchanged recently</span>';
    }
    return (
      '<div class="hc-bsec' + (isOpen ? ' open' : '') + (isProposal ? ' hc-bsec--proposal' : '') +
        '" data-sec-id="' + esc(id) + '">' +
        '<div class="hc-bsec-h" role="button" tabindex="0">' +
          '<span class="hc-bsec-dot' + (s.changed_since_yesterday ? ' new' : '') + '"></span>' +
          '<span class="hc-bsec-t">' + esc(s.headline || id) + '</span>' +
          '<span class="' + _badge(isProposal ? 'proposal' : s.cadence) + '">' +
            esc(_badgeLabel(s.cadence, s)) + '</span>' +
          unchanged +
          '<span class="hc-caret">›</span>' +
        '</div>' +
        '<div class="hc-bsec-b">' +
          (s.evidence ? '<p>' + hiliteNums(s.evidence) + '</p>' : '') +
          stripHtml +
          life +
          (isProposal ? _proposalActions(s) : '') +
          (!isProposal && s.do
            ? '<div class="hc-do"><span class="hc-k">DO</span><span>' + hiliteNums(s.do) + '</span></div>'
            : '') +
        '</div>' +
      '</div>'
    );
  }

  function _ensureOverlay() {
    if (_overlay) return _overlay;
    _overlay = document.createElement('div');
    _overlay.id = 'hc-brief-overlay';
    _overlay.className = 'hc-brief-overlay';
    _overlay.hidden = true;
    _overlay.innerHTML =
      '<div class="hc-brief-panel" role="dialog" aria-modal="true" aria-label="Coach brief">' +
        '<button type="button" class="hc-brief-close" aria-label="Close">×</button>' +
        '<div class="hc-brief-mount"></div>' +
      '</div>';
    document.body.appendChild(_overlay);
    _overlay.addEventListener('click', function (e) {
      if (e.target === _overlay) close();
    });
    _overlay.querySelector('.hc-brief-close').addEventListener('click', close);
    return _overlay;
  }

  function _postProposal(id, action, body) {
    var url = '/api/preferences/proposals/' + encodeURIComponent(id) + '/' + action;
    return fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: body ? JSON.stringify(body) : undefined,
    }).then(function (r) {
      if (!r.ok) {
        return r.json().then(function (j) {
          throw new Error((j && j.detail) || r.statusText);
        }).catch(function (e) {
          if (e.message) throw e;
          throw new Error(r.statusText);
        });
      }
      return r.json();
    });
  }

  function _bindProposalActions(root) {
    root.querySelectorAll('.hc-prop-actions').forEach(function (wrap) {
      var id = wrap.getAttribute('data-proposal-id');
      if (!id) return;
      var accept = wrap.querySelector('.hc-prop-accept');
      var adjust = wrap.querySelector('.hc-prop-adjust');
      var decline = wrap.querySelector('.hc-prop-decline');
      if (accept) {
        accept.addEventListener('click', function (e) {
          e.stopPropagation();
          accept.disabled = true;
          _postProposal(id, 'accept')
            .then(function () { window.location.reload(); })
            .catch(function (err) {
              accept.disabled = false;
              window.alert(err.message || 'Accept failed');
            });
        });
      }
      if (adjust) {
        adjust.addEventListener('click', function (e) {
          e.stopPropagation();
          var raw = window.prompt('New value (one catalog step from current):');
          if (raw == null || raw === '') return;
          var n = Number(raw);
          if (!Number.isFinite(n)) {
            window.alert('Enter a number');
            return;
          }
          adjust.disabled = true;
          _postProposal(id, 'adjust', { to: n })
            .then(function () { window.location.reload(); })
            .catch(function (err) {
              adjust.disabled = false;
              window.alert(err.message || 'Adjust failed');
            });
        });
      }
      if (decline) {
        decline.addEventListener('click', function (e) {
          e.stopPropagation();
          decline.disabled = true;
          _postProposal(id, 'decline')
            .then(function () { window.location.reload(); })
            .catch(function (err) {
              decline.disabled = false;
              window.alert(err.message || 'Decline failed');
            });
        });
      }
    });
  }

  function _bindAccordion(root) {
    root.querySelectorAll('.hc-bsec-h').forEach(function (h) {
      h.addEventListener('click', function () {
        h.parentElement.classList.toggle('open');
      });
      h.addEventListener('keydown', function (e) {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault();
          h.parentElement.classList.toggle('open');
        }
      });
    });
  }

  function renderBriefHtml(brief) {
    var sections = brief.sections || [];
    var openSet = _openIds(sections);
    var totalChanged = 0;
    sections.forEach(function (s) {
      if (s && s.changed_since_yesterday) totalChanged += 1;
    });
    var meta = brief.brief_date || '';
    return (
      '<div class="hc-brief">' +
        '<div class="hc-brief-head">' +
          '<div>' +
            '<div class="hc-brief-title">Coach brief</div>' +
            (meta ? '<div class="hc-brief-meta">' + esc(meta) + '</div>' : '') +
          '</div>' +
          (totalChanged
            ? '<span class="hc-diffchip">' + totalChanged + ' CHANGED SINCE YESTERDAY</span>'
            : '') +
        '</div>' +
        sections.map(function (s) {
          return _sectionHtml(s, openSet);
        }).join('') +
        '<div class="hc-brief-foot">' +
          esc(brief.closing_question || '') +
        '</div>' +
      '</div>'
    );
  }

  function open(brief) {
    if (!brief) return;
    _lastBrief = brief;
    var ov = _ensureOverlay();
    var mount = ov.querySelector('.hc-brief-mount');
    mount.innerHTML = renderBriefHtml(brief);
    _bindAccordion(mount);
    _bindProposalActions(mount);
    ov.hidden = false;
    document.body.classList.add('hc-brief-open');
  }

  function close() {
    if (!_overlay) return;
    _overlay.hidden = true;
    document.body.classList.remove('hc-brief-open');
  }

  function openSectionIds(brief) {
    return _openIds((brief && brief.sections) || []);
  }

  window.CoachBrief = {
    open: open,
    close: close,
    renderBriefHtml: renderBriefHtml,
    openSectionIds: openSectionIds,
  };
})();
