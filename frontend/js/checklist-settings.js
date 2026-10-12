/**
 * Manage checklist modal — habit settings from gear / Manage → (WC-16).
 */
(function () {
  'use strict';

  var _opts = {};
  var _prefsPayload = {};
  var _habits = [];
  var _archivedStretch = null;
  var _saving = false;

  function esc(s) {
    return window.AppCommon ? window.AppCommon.escapeHtml(s) : String(s);
  }

  function overlay() {
    return document.getElementById('checklist-settings-overlay');
  }

  function bodyEl() {
    return document.getElementById('checklist-settings-body');
  }

  function errEl() {
    return document.getElementById('checklist-settings-error');
  }

  function setError(msg) {
    var el = errEl();
    if (!el) return;
    if (!msg) {
      el.hidden = true;
      el.textContent = '';
      return;
    }
    el.hidden = false;
    el.textContent = msg;
  }

  function roleSegHtml(prefix, value, disabled) {
    var roles = ['core', 'optional', 'off'];
    var labels = { core: 'Core', optional: 'Optional', off: 'Off' };
    return (
      '<div class="cl-set-seg" role="group" aria-label="Checklist role">' +
        roles.map(function (r) {
          return (
            '<button type="button" data-role-target="' + esc(prefix) + '"' +
              ' data-role="' + r + '"' +
              ' aria-pressed="' + (value === r ? 'true' : 'false') + '"' +
              (disabled ? ' disabled' : '') + '>' +
              esc(labels[r]) +
            '</button>'
          );
        }).join('') +
      '</div>'
    );
  }

  function habitBadge(h) {
    if (h.is_archived) return '<span class="cl-set-badge cl-set-badge--archived">Archive</span>';
    var src = h.auto_fill_source || '';
    if (src === 'weight.logged' || src === 'long_run.fuelled' || src === 'sleep.hours_min') {
      return '<span class="cl-set-badge cl-set-badge--auto">Auto</span>';
    }
    if (src === 'workout.zone2_minutes') {
      return '<span class="cl-set-badge cl-set-badge--coach">Coach</span>';
    }
    if (!src && (h.name || '').toLowerCase().indexOf('protein') >= 0) {
      return '<span class="cl-set-badge cl-set-badge--tap">Tap</span>';
    }
    if (src === 'coach.stretch_daily') {
      return '<span class="cl-set-badge cl-set-badge--archived">Archive</span>';
    }
    return '<span class="cl-set-badge cl-set-badge--yours">Yours</span>';
  }

  function isGoalHabit(h) {
    var src = h.auto_fill_source || '';
    if (src === 'weight.logged' || src === 'long_run.fuelled') return true;
    return !src && (h.name || '').toLowerCase().indexOf('protein') >= 0;
  }

  function isRecoveryHabit(h) {
    return !isGoalHabit(h) && (h.auto_fill_source || '') !== 'coach.stretch_daily';
  }

  function mobilityRole() {
    var stretch = Number(_prefsPayload.stretch_daily_min || 0);
    var role = _prefsPayload.mobility_checklist_role || 'optional';
    if (stretch <= 0 || role === 'off') return 'off';
    return role === 'core' ? 'core' : 'optional';
  }

  function mobilityMinutes() {
    var n = Number(_prefsPayload.stretch_daily_min || 0);
    return n > 0 ? n : 15;
  }

  function formatBuiltAt(iso) {
    if (!iso) return '—';
    try {
      var d = new Date(iso);
      var days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
      var mo = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
      return days[d.getDay()] + ' ' + d.getDate() + ' ' + mo[d.getMonth()];
    } catch (_) {
      return String(iso).slice(0, 10);
    }
  }

  function habitTargetInput(h) {
    if (h.auto_fill_source === 'sleep.hours_min') {
      var tv = h.target_value != null ? h.target_value : 7.5;
      return (
        '<div class="cl-set-habit-target">' +
          '<input type="number" class="cl-set-input" min="4" max="12" step="0.5"' +
            ' data-habit-target="' + esc(h.id) + '" value="' + esc(String(tv)) + '">' +
          '<span class="cl-set-input-unit">h</span>' +
        '</div>'
      );
    }
    if (h.auto_fill_source === 'workout.zone2_minutes' || h.tracking_type === 'weekly_minutes') {
      var wt = h.weekly_target != null ? h.weekly_target : (h.target_value != null ? h.target_value : 150);
      return (
        '<div class="cl-set-habit-target">' +
          '<input type="number" class="cl-set-input" min="0" step="5"' +
            ' data-habit-weekly="' + esc(h.id) + '" value="' + esc(String(Math.round(wt))) + '">' +
          '<span class="cl-set-input-unit">min/wk</span>' +
        '</div>'
      );
    }
    if (h.schedule_type === 'times_per_week' && h.target_value != null) {
      return (
        '<div class="cl-set-habit-target">' +
          '<input type="number" class="cl-set-input" min="1" step="1"' +
            ' data-habit-weekly="' + esc(h.id) + '" value="' + esc(String(h.target_value)) + '">' +
          '<span class="cl-set-input-unit">×/wk</span>' +
        '</div>'
      );
    }
    return '';
  }

  function habitRowHtml(h, opts) {
    opts = opts || {};
    var role = h.checklist_role || 'core';
    var archived = !!h.is_archived;
    return (
      '<div class="cl-set-habit-row' + (archived ? ' cl-set-habit-row--archived' : '') + '">' +
        '<div>' +
          '<div class="cl-set-habit-meta">' +
            habitBadge(h) +
            '<span class="cl-set-row-label">' + esc(h.name) + '</span>' +
          '</div>' +
          (opts.note ? '<p class="cl-set-row-desc">' + esc(opts.note) + '</p>' : '') +
          (!archived ? habitTargetInput(h) : '') +
        '</div>' +
        (archived ? '' : roleSegHtml('habit:' + h.id, role, !!opts.lockRole)) +
      '</div>'
    );
  }

  function buildStatusBanner(st) {
    st = st || {};
    if (st.status !== 'updating' && st.state !== 'updating') return '';
    return (
      '<div class="cl-set-banner" role="status">' +
        'Rebuilding on the worker. Mobility and plan-linked sessions update in the background. ' +
        'The Plan tab shows them as updating until done.' +
      '</div>'
    );
  }

  function render() {
    var host = bodyEl();
    if (!host) return;

    var checklistOn = _opts.forceChecklistOn || _prefsPayload.weekly_checklist_enabled !== false;
    var fuelOn = _prefsPayload.checklist_fuel_enabled !== false;
    var mobRole = mobilityRole();
    var mobMin = mobilityMinutes();
    var st = _opts.buildStatus || {};
    var built = formatBuiltAt(st.last_built_at || st.last_built);

    var goalHabits = _habits.filter(function (h) {
      return !h.is_archived && isGoalHabit(h);
    });
    var recoveryHabits = _habits.filter(function (h) {
      return !h.is_archived && isRecoveryHabit(h);
    });

    host.innerHTML =
      '<div class="cl-set-col">' +
        '<div class="cl-set-section">' +
          '<div class="cl-set-row">' +
            '<div class="cl-set-row-main">' +
              '<div class="cl-set-row-label">Weekly checklist</div>' +
              '<p class="cl-set-row-desc">Builds each week from your Plan. Turn off to get the plain habits list back; Plan and fuel keep working.</p>' +
            '</div>' +
            '<button type="button" class="cl-set-toggle" id="cl-set-checklist-toggle"' +
              ' aria-checked="' + (checklistOn ? 'true' : 'false') + '"' +
              ' aria-label="Weekly checklist"></button>' +
          '</div>' +
        '</div>' +
        '<div class="cl-set-section">' +
          '<h3 class="cl-set-section-title">From your plan</h3>' +
          '<div class="cl-set-row">' +
            '<div class="cl-set-row-main">' +
              '<span class="cl-set-badge cl-set-badge--locked">Locked</span>' +
              '<span class="cl-set-row-label">Planned sessions</span>' +
            '</div>' +
            '<a href="/log?tab=plan" class="cl-set-link">Edit in Plan →</a>' +
          '</div>' +
          '<div class="cl-set-row" style="flex-wrap:wrap">' +
            '<div class="cl-set-row-main">' +
              '<span class="cl-set-badge cl-set-badge--plan">Plan</span>' +
              '<span class="cl-set-row-label">Mobility block</span>' +
            '</div>' +
            '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">' +
              roleSegHtml('mobility', mobRole, false) +
              '<span><input type="number" class="cl-set-input" id="cl-set-mobility-min"' +
                ' min="5" max="60" step="5" value="' + esc(String(mobMin)) + '"' +
                (mobRole === 'off' ? ' disabled' : '') + '>' +
              '<span class="cl-set-input-unit">min/day</span></span>' +
            '</div>' +
          '</div>' +
          buildStatusBanner(st) +
          '<div class="cl-set-row">' +
            '<div class="cl-set-row-main">' +
              '<div class="cl-set-row-label">Fuel card</div>' +
              '<p class="cl-set-row-desc">Targets from the fuel plan, shown and never ticked.</p>' +
            '</div>' +
            '<button type="button" class="cl-set-toggle" id="cl-set-fuel-toggle"' +
              ' aria-checked="' + (fuelOn ? 'true' : 'false') + '"' +
              ' aria-label="Fuel card"></button>' +
          '</div>' +
        '</div>' +
        '<div class="cl-set-section">' +
          '<h3 class="cl-set-section-title">When changes apply</h3>' +
          '<p class="cl-set-apply-note">' +
            '<strong class="cl-set-tag-instant">Instantly</strong> — master switches and habit roles. ' +
            '<strong class="cl-set-tag-worker">Rebuilt on the worker</strong> — mobility minutes and plan pipeline changes.' +
          '</p>' +
          '<p class="cl-set-row-desc">Last build: <strong>' + esc(built) + '</strong></p>' +
          '<button type="button" class="cl-set-rebuild" id="cl-set-rebuild"' +
            ((st.status === 'updating' || st.state === 'updating') ? ' disabled' : '') +
            '>Rebuild this week</button>' +
        '</div>' +
      '</div>' +
      '<div class="cl-set-col">' +
        '<div class="cl-set-section">' +
          '<h3 class="cl-set-section-title">Goal habits</h3>' +
          '<p class="cl-set-row-desc" style="margin:-4px 0 8px">Created automatically · lean program</p>' +
          goalHabits.map(function (h) { return habitRowHtml(h); }).join('') +
        '</div>' +
        '<div class="cl-set-section">' +
          '<h3 class="cl-set-section-title">Recovery and yours</h3>' +
          recoveryHabits.map(function (h) { return habitRowHtml(h); }).join('') +
          (_archivedStretch
            ? habitRowHtml(_archivedStretch, {
              note: 'Replaced by the mobility block in your Plan.',
            })
            : '') +
          '<button type="button" class="cl-set-add" id="cl-set-add-habit">+ Add a habit</button>' +
        '</div>' +
      '</div>';

    wireInteractions();
  }

  async function mergeSavePrefs(partial) {
    if (_saving) return;
    _saving = true;
    setError('');
    try {
      var merged = Object.assign({}, _prefsPayload, partial);
      var res = await fetch('/api/preferences', {
        method: 'PUT',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ payload: merged }),
      });
      var body = await res.json().catch(function () { return {}; });
      if (!res.ok) {
        throw new Error(body.detail ? JSON.stringify(body.detail) : 'Could not save preferences');
      }
      _prefsPayload = (body.payload || merged);
      if (typeof _opts.onSaved === 'function') _opts.onSaved();
      render();
    } catch (e) {
      setError(e.message || 'Save failed');
    } finally {
      _saving = false;
    }
  }

  async function patchHabit(habitId, patch) {
    setError('');
    var res = await fetch('/api/habits/' + encodeURIComponent(habitId), {
      method: 'PATCH',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(patch),
    });
    if (!res.ok) {
      var body = await res.json().catch(function () { return {}; });
      throw new Error(body.detail || 'Could not update habit');
    }
    return res.json();
  }

  async function refreshBuildStatus() {
    try {
      var url = '/api/plan/build-status';
      if (_opts.weekStart) {
        url += '?week_start=' + encodeURIComponent(_opts.weekStart);
      }
      var res = await fetch(url, { credentials: 'same-origin' });
      if (res.ok) _opts.buildStatus = await res.json();
    } catch (_) { /* optional poll */ }
  }

  async function reloadHabits() {
    var res = await fetch('/api/habits?include_archived=true', { credentials: 'same-origin' });
    if (!res.ok) throw new Error('Could not load habits');
    var all = await res.json();
    _archivedStretch = all.find(function (h) {
      return h.auto_fill_source === 'coach.stretch_daily' && h.is_archived;
    }) || null;
    _habits = all.filter(function (h) {
      return !h.is_archived && (h.auto_fill_source || '') !== 'coach.stretch_daily';
    });
  }

  function setMobility(role, minutes) {
    var stretch = role === 'off' ? 0 : Math.max(5, Math.min(60, Number(minutes) || 15));
    var mobRole = role === 'off' ? 'off' : role;
    _prefsPayload.stretch_daily_min = stretch;
    _prefsPayload.mobility_checklist_role = mobRole;
    return mergeSavePrefs({
      stretch_daily_min: stretch,
      mobility_checklist_role: mobRole,
    });
  }

  function wireInteractions() {
    var host = bodyEl();
    if (!host) return;

    var checklistToggle = host.querySelector('#cl-set-checklist-toggle');
    if (checklistToggle) {
      checklistToggle.addEventListener('click', function () {
        var on = checklistToggle.getAttribute('aria-checked') !== 'true';
        mergeSavePrefs({ weekly_checklist_enabled: on }).then(function () {
          if (on && typeof _opts.onChecklistEnabled === 'function') {
            _opts.onChecklistEnabled();
          } else if (!on && typeof _opts.onChecklistDisabled === 'function') {
            _opts.onChecklistDisabled();
          }
        });
      });
    }

    var fuelToggle = host.querySelector('#cl-set-fuel-toggle');
    if (fuelToggle) {
      fuelToggle.addEventListener('click', function () {
        var on = fuelToggle.getAttribute('aria-checked') !== 'true';
        mergeSavePrefs({ checklist_fuel_enabled: on });
      });
    }

    host.querySelectorAll('[data-role-target="mobility"]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var role = btn.getAttribute('data-role');
        var minEl = host.querySelector('#cl-set-mobility-min');
        var min = minEl ? Number(minEl.value) : mobilityMinutes();
        setMobility(role, min);
      });
    });

    var minEl = host.querySelector('#cl-set-mobility-min');
    if (minEl) {
      minEl.addEventListener('change', function () {
        if (mobilityRole() === 'off') return;
        setMobility(mobilityRole(), Number(minEl.value));
      });
    }

    host.querySelectorAll('[data-role-target^="habit:"]').forEach(function (btn) {
      btn.addEventListener('click', async function () {
        var id = btn.getAttribute('data-role-target').slice(6);
        var role = btn.getAttribute('data-role');
        try {
          await patchHabit(id, { checklist_role: role });
          await reloadHabits();
          if (typeof _opts.onSaved === 'function') _opts.onSaved();
          render();
        } catch (e) {
          setError(e.message);
        }
      });
    });

    host.querySelectorAll('[data-habit-target]').forEach(function (input) {
      input.addEventListener('change', async function () {
        var id = input.getAttribute('data-habit-target');
        var val = parseFloat(input.value);
        if (isNaN(val)) return;
        try {
          await patchHabit(id, { target_value: val });
          if (typeof _opts.onSaved === 'function') _opts.onSaved();
        } catch (e) {
          setError(e.message);
        }
      });
    });

    host.querySelectorAll('[data-habit-weekly]').forEach(function (input) {
      input.addEventListener('change', async function () {
        var id = input.getAttribute('data-habit-weekly');
        var val = parseFloat(input.value);
        if (isNaN(val)) return;
        try {
          await patchHabit(id, { weekly_target: val, target_value: val });
          if (typeof _opts.onSaved === 'function') _opts.onSaved();
        } catch (e) {
          setError(e.message);
        }
      });
    });

    var rebuildBtn = host.querySelector('#cl-set-rebuild');
    if (rebuildBtn) {
      rebuildBtn.addEventListener('click', async function () {
        rebuildBtn.disabled = true;
        setError('');
        try {
          var body = {};
          if (_opts.weekStart) body.week_start = _opts.weekStart;
          var res = await fetch('/api/plan/rebuild-week', {
            method: 'POST',
            credentials: 'same-origin',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
          });
          var data = await res.json().catch(function () { return {}; });
          if (!res.ok) throw new Error(data.detail || 'Rebuild failed');
          _opts.buildStatus = data;
          await refreshBuildStatus();
          if (typeof _opts.onSaved === 'function') _opts.onSaved();
          render();
        } catch (e) {
          setError(e.message || 'Rebuild failed');
          rebuildBtn.disabled = false;
        }
      });
    }

    var addBtn = host.querySelector('#cl-set-add-habit');
    if (addBtn) {
      addBtn.addEventListener('click', function () {
        close();
        if (window.HabitsPage && typeof window.HabitsPage.openHabitForm === 'function') {
          window.HabitsPage.openHabitForm(null);
        }
      });
    }
  }

  async function loadAndRender() {
    var host = bodyEl();
    if (host) host.innerHTML = '<div class="cl-set-loading">Loading settings…</div>';
    setError('');
    try {
      var prefRes = await fetch('/api/preferences', { credentials: 'same-origin' });
      if (!prefRes.ok) throw new Error('Could not load preferences');
      var prefData = await prefRes.json();
      _prefsPayload = Object.assign({}, (prefData.active && prefData.active.payload) || {});
      await refreshBuildStatus();
      await reloadHabits();
      render();
    } catch (e) {
      if (host) {
        host.innerHTML = '<div class="cl-set-loading">' + esc(e.message || 'Load failed') + '</div>';
      }
    }
  }

  function open(opts) {
    _opts = opts || {};
    var el = overlay();
    if (!el) return;
    el.classList.add('open');
    document.body.style.overflow = 'hidden';
    loadAndRender();
  }

  function close() {
    var el = overlay();
    if (!el) return;
    el.classList.remove('open');
    document.body.style.overflow = '';
    setError('');
  }

  function init() {
    var el = overlay();
    if (!el) return;
    el.querySelector('.cl-set-close').addEventListener('click', close);
    el.addEventListener('click', function (e) {
      if (e.target === el) close();
    });
    document.addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && el.classList.contains('open')) close();
    });
  }

  document.addEventListener('DOMContentLoaded', init);

  window.ChecklistSettings = { open: open, close: close };
})();
