(function (global) {
  'use strict';

  /** @type {'planned'|'logged'} */
  var SESSION_EDITOR_MODE_PLANNED = 'planned';
  var SESSION_EDITOR_MODE_LOGGED = 'logged';
  var LOGGED_DELEGATE_MARKER = 'v2-strength-editor-mode';

  var esc = global.AppCommon ? global.AppCommon.escapeHtml.bind(global.AppCommon) : function (s) { return String(s); };
  var state = { ctx: null, onSaved: null };

  function els() {
    return {
      backdrop: document.getElementById('v2-session-editor-backdrop'),
      drawer: document.getElementById('v2-session-editor'),
      body: document.getElementById('v2-session-editor-body'),
    };
  }

  function close() {
    var e = els();
    if (e.drawer) {
      e.drawer.classList.remove('is-open');
      e.drawer.hidden = true;
    }
    if (e.backdrop) {
      e.backdrop.classList.remove('is-open');
      e.backdrop.hidden = true;
    }
    document.removeEventListener('keydown', onKey);
    state.ctx = null;
  }

  function onKey(ev) {
    if (ev.key === 'Escape') close();
  }

  function renderRules(ctx) {
    var rules = (ctx.rules && ctx.rules.results) || [];
    if (!rules.length) return '<p class="rv-subtitle">No rule warnings for this day.</p>';
    return rules.map(function (r) {
      var col = r.level === 'block' ? '#b91c1c' : '#b45309';
      return '<p class="rv-subtitle" style="color:' + col + '">' + esc(r.message || r.rule_id) + '</p>';
    }).join('');
  }

  function renderLibrary(ctx) {
    return (ctx.library || []).map(function (ex) {
      var dis = ex.blocked ? ' disabled aria-disabled="true" tabindex="-1"' : '';
      var reason = ex.blocked ? ' title="' + esc(ex.block_reason || 'Blocked by plan rules') + '"' : '';
      var delta = ex.week_delta_tss != null ? ('+' + ex.week_delta_tss + ' wk') : '';
      return (
        '<button type="button" class="rv-btn rv-btn--secondary rv-btn--small v2-lib-pick" data-name="' + esc(ex.name) + '"' +
        dis + reason + ' style="justify-content:space-between;width:100%">' +
        '<span>' + esc(ex.name) + '</span><span class="rv-subtitle">' + esc(delta) + '</span></button>'
      );
    }).join('');
  }

  function render(ctx) {
    var e = els();
    if (!e.body) return;
    var t = ctx.tiles || {};
    var chips =
      '<span class="rv-chip">PLANNED</span>' +
      '<span class="rv-chip">' + esc((ctx.plan_source || 'support').toUpperCase()) + '</span>';
    e.body.innerHTML =
      '<h2 class="rv-label" id="v2-session-editor-title">Plan session</h2>' +
      '<div class="rv-row" style="flex-wrap:wrap;gap:6px">' + chips + '</div>' +
      '<label class="rv-label">Name<input class="rv-input" id="v2-se-name" value="' + esc(ctx.name || '') + '"></label>' +
      '<div class="rv-card" style="background:#0b1530;color:#fff;padding:14px">' +
      '<p class="rv-subtitle" style="color:#c9d5ef">TSS for this plan</p>' +
      '<div class="rv-row" style="gap:12px;flex-wrap:wrap">' +
      '<form class="rv-subtitle">Session <strong>' + esc(String(t.session_tss)) + '</strong></form>' +
      '<form class="rv-subtitle">Day <strong>' + esc(String(t.day_tss)) + '</strong></form>' +
      '<form class="rv-subtitle">Week <strong>' + esc(String(t.week_planned)) + ' / ' + esc(String(t.week_target)) + '</strong></form>' +
      '</div></div>' +
      '<section class="rv-card rv-stack"><h3 class="rv-label">Rules for this day</h3>' + renderRules(ctx) + '</section>' +
      '<section class="rv-card rv-stack"><h3 class="rv-label">Add from library</h3>' +
      '<div class="rv-stack" id="v2-se-library">' + renderLibrary(ctx) + '</div></section>' +
      '<div class="rv-row">' +
      '<button type="button" class="rv-btn rv-btn--secondary" id="v2-se-cancel">Cancel</button>' +
      '<button type="button" class="rv-btn" id="v2-se-save">Save</button></div>';

    e.body.querySelector('#v2-se-cancel').onclick = close;
    e.body.querySelector('#v2-se-save').onclick = save;
    e.body.querySelectorAll('.v2-lib-pick').forEach(function (btn) {
      btn.onclick = function (ev) {
        if (btn.disabled || btn.getAttribute('aria-disabled') === 'true') {
          ev.preventDefault();
          return;
        }
        var n = btn.getAttribute('data-name');
        if (!n) return;
        var structure = Object.assign({}, ctx.structure || {});
        var exercises = structure.exercises ? structure.exercises.slice() : [];
        exercises.push({ name: n, sets: 3, reps: '10' });
        structure.exercises = exercises;
        reloadContext(Object.assign({}, ctx, { structure: structure, name: e.body.querySelector('#v2-se-name').value }));
      };
      btn.onkeydown = function (ev) {
        if ((ev.key === 'Enter' || ev.key === ' ') && (btn.disabled || btn.getAttribute('aria-disabled') === 'true')) {
          ev.preventDefault();
        }
      };
    });
  }

  function reloadContext(partial) {
    var q =
      '?planned_date=' + encodeURIComponent(partial.planned_date) +
      '&week_start=' + encodeURIComponent(partial.week_start);
    if (partial.session_id) q += '&session_id=' + encodeURIComponent(partial.session_id);
    var fetchFn = window.AppCommon && window.AppCommon.fetchWithCsrf
      ? window.AppCommon.fetchWithCsrf
      : function (u, o) { return fetch(u, Object.assign({ credentials: 'include' }, o || {})); };
    fetchFn('/api/plan/revamp-planned-editor/context' + q, { credentials: 'include' })
      .then(function (r) {
        if (!r.ok) throw new Error('Could not load editor (' + r.status + ')');
        return r.json();
      })
      .then(function (ctx) {
        ctx.structure = partial.structure || ctx.structure;
        ctx.name = partial.name || ctx.name;
        state.ctx = ctx;
        render(ctx);
      })
      .catch(function (e) {
        if (window.RevampUI && window.RevampUI.showToast) {
          window.RevampUI.showToast(e.message || 'Could not load session editor');
        }
      });
  }

  function save() {
    var ctx = state.ctx;
    if (!ctx) return;
    var e = els();
    var name = e.body && e.body.querySelector('#v2-se-name') ? e.body.querySelector('#v2-se-name').value : ctx.name;
    var payload = {
      planned_date: ctx.planned_date,
      session_type: ctx.session_type || 'mobility',
      name: name,
      structure: ctx.structure || {},
      plan_source: 'support',
    };
    var req = ctx.session_id
      ? fetch('/api/planned-sessions/' + encodeURIComponent(ctx.session_id), {
        method: 'PATCH',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      : fetch('/api/planned-sessions', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      });
    req.then(function (r) {
      if (!r.ok) throw new Error('save failed');
      return r.json();
    }).then(function () {
      if (state.onSaved) state.onSaved();
      close();
    });
  }

  function openPlanned(opts) {
    state.onSaved = opts.onSaved || null;
    var q =
      '?planned_date=' + encodeURIComponent(opts.plannedDate) +
      '&week_start=' + encodeURIComponent(opts.weekStart || opts.plannedDate);
    if (opts.sessionId) q += '&session_id=' + encodeURIComponent(opts.sessionId);
    var fetchFn = window.AppCommon && window.AppCommon.fetchWithCsrf
      ? window.AppCommon.fetchWithCsrf
      : function (u, o) { return fetch(u, Object.assign({ credentials: 'include' }, o || {})); };
    fetchFn('/api/plan/revamp-planned-editor/context' + q, { credentials: 'include' })
      .then(function (r) {
        if (!r.ok) throw new Error('Could not open editor (' + r.status + ')');
        return r.json();
      })
      .then(function (ctx) {
        state.ctx = ctx;
        var e = els();
        if (e.backdrop) { e.backdrop.hidden = false; e.backdrop.classList.add('is-open'); }
        if (e.drawer) { e.drawer.hidden = false; e.drawer.classList.add('is-open'); }
        document.addEventListener('keydown', onKey);
        render(ctx);
      })
      .catch(function (e) {
        if (window.RevampUI && window.RevampUI.showToast) {
          window.RevampUI.showToast(e.message || 'Could not open session editor');
        }
      });
  }

  function openLogged(opts) {
    if (global.V2StrengthDrawer && global.V2StrengthDrawer.openEdit) {
      global.V2StrengthDrawer.openEdit(opts.workoutId);
      return;
    }
    if (global.V2StrengthDrawer && global.V2StrengthDrawer.openView) {
      global.V2StrengthDrawer.openView(opts.workoutId);
    }
  }

  global.V2SessionEditor = {
    MODES: { PLANNED: SESSION_EDITOR_MODE_PLANNED, LOGGED: SESSION_EDITOR_MODE_LOGGED },
    LOGGED_DELEGATE_MARKER: LOGGED_DELEGATE_MARKER,
    openPlanned: openPlanned,
    openLogged: openLogged,
    close: close,
  };
})(window);