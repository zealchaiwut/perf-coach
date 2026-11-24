(function (global) {
  'use strict';

  var TYPE_OPTIONS = [
    { key: 'easy', label: 'Easy', cls: 'is-easy', color: '#2d5e10' },
    { key: 'longrun', label: 'Long', cls: 'is-long', color: '#1f3b8a' },
    { key: 'tempo', label: 'Tempo', cls: 'is-tempo', color: '#7a3a10' },
    { key: 'interval', label: 'Intervals', cls: 'is-interval', color: '#7a1a1a' },
    { key: 'race', label: 'Race', cls: 'is-race', color: '#e4ff52' },
  ];
  var TYPE_BY_KEY = {};
  TYPE_OPTIONS.forEach(function (t) { TYPE_BY_KEY[t.key] = t; });

  var RPE_ANCHORS = {
    1: 'very easy',
    3: 'easy',
    5: 'steady',
    7: 'hard',
    9: 'very hard',
    10: 'max',
  };

  var openMenu = null;

  function typeLabelFor(subtype) {
    var t = TYPE_BY_KEY[subtype];
    return t ? t.label : 'Type';
  }

  function rpeLabelFor(rpe) {
    return rpe == null || rpe === '' ? 'RPE' : ('RPE ' + Number(rpe));
  }

  function rpeBand(n) {
    var v = Number(n);
    if (!isFinite(v)) return '';
    if (v <= 3) return 'easy';
    if (v <= 6) return 'steady';
    return 'hard';
  }

  function rpeColors(n) {
    var band = rpeBand(n);
    if (band === 'easy') return { bg: '#dff5d6', fg: '#2d5e10' };
    if (band === 'steady') return { bg: '#fff1dc', fg: '#7a3a10' };
    return { bg: '#fde8e8', fg: '#7a1a1a' };
  }

  function parseRpe(raw) {
    if (raw == null || raw === '') return null;
    var n = Number(raw);
    if (!isFinite(n) || n < 1 || n > 10) return null;
    return n;
  }

  function preview(opts) {
    opts = opts || {};
    var showType = !!opts.isRun;
    var typeLabel = showType ? typeLabelFor(opts.runSubtype) : null;
    var rpeLabel = rpeLabelFor(opts.rpe);
    return {
      showType: showType,
      typeLabel: typeLabel,
      typeText: showType ? (typeLabel + ' ▾') : null,
      rpeLabel: rpeLabel,
      rpeText: rpeLabel + ' ▾',
    };
  }

  function closeOpenMenu() {
    if (!openMenu) return;
    if (openMenu.onDocClick) document.removeEventListener('mousedown', openMenu.onDocClick, true);
    if (openMenu.onKey) document.removeEventListener('keydown', openMenu.onKey, true);
    if (openMenu.el && openMenu.el.parentNode) openMenu.el.parentNode.removeChild(openMenu.el);
    if (openMenu.pill) {
      openMenu.pill.setAttribute('aria-expanded', 'false');
      openMenu.pill.removeAttribute('aria-controls');
    }
    openMenu = null;
  }

  function positionMenu(menu, pill) {
    var rect = pill.getBoundingClientRect();
    var mw = menu.offsetWidth || 170;
    var mh = menu.offsetHeight || 0;
    var gap = 6;
    var left = Math.round(rect.right - mw);
    if (left < 8) left = 8;
    if (left + mw > window.innerWidth - 8) left = Math.max(8, window.innerWidth - mw - 8);
    var below = rect.bottom + gap;
    var above = rect.top - mh - gap;
    var top = below;
    if (below + mh > window.innerHeight - 8 && above > 8) top = above;
    menu.style.left = left + 'px';
    menu.style.top = Math.max(8, top) + 'px';
  }

  function patchFields(workoutId, body, onDone) {
    return fetch('/api/workouts/' + encodeURIComponent(workoutId), {
      method: 'PATCH',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
      .then(function (r) {
        if (!r.ok) throw new Error();
        return r.json();
      })
      .then(function (json) {
        if (onDone) onDone(json, false);
      })
      .catch(function () {
        if (onDone) onDone(undefined, true);
      });
  }

  function patchFeeling(workoutId, value, onDone) {
    return patchFields(workoutId, { feeling: value }, function (body, err) {
      if (err) {
        if (onDone) onDone(undefined, true);
        return;
      }
      var feeling = body && Object.prototype.hasOwnProperty.call(body, 'feeling')
        ? body.feeling
        : value;
      if (onDone) onDone(feeling, false, body);
    });
  }

  function showError(host, msg) {
    var err = host.querySelector('.rv-tag-err');
    if (!err) {
      err = document.createElement('span');
      err.className = 'rv-tag-err';
      err.setAttribute('role', 'alert');
      host.appendChild(err);
    }
    err.hidden = false;
    err.textContent = msg || 'Could not save';
  }

  function hideError(host) {
    var err = host.querySelector('.rv-tag-err');
    if (err) {
      err.hidden = true;
      err.textContent = '';
    }
  }

  function paintPills(host, state) {
    var typeBtn = host.querySelector('[data-tag="type"]');
    var rpeBtn = host.querySelector('[data-tag="rpe"]');
    if (typeBtn) {
      var t = TYPE_BY_KEY[state.runSubtype];
      typeBtn.className = 'rv-tag-pill rv-tag-pill--type' + (t ? (' ' + t.cls) : '');
      typeBtn.innerHTML = '<span class="rv-tag-label">' + (t ? t.label : 'Type') +
        '</span><span class="rv-tag-caret" aria-hidden="true">▾</span>';
    }
    if (rpeBtn) {
      var set = state.rpe != null;
      var band = set ? rpeBand(state.rpe) : '';
      rpeBtn.className = 'rv-tag-pill rv-tag-pill--rpe' + (band ? (' is-rpe-' + band) : '');
      rpeBtn.innerHTML = '<span class="rv-tag-label">' + rpeLabelFor(state.rpe) +
        '</span><span class="rv-tag-caret" aria-hidden="true">▾</span>';
    }
  }

  function menuItem(opts) {
    var btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'rv-tag-item' + (opts.current ? ' is-current' : '') + (opts.clear ? ' rv-tag-item--clear' : '');
    btn.setAttribute('role', opts.clear ? 'menuitem' : 'menuitemradio');
    if (!opts.clear) btn.setAttribute('aria-checked', opts.current ? 'true' : 'false');
    if (opts.html) btn.innerHTML = opts.html;
    else btn.textContent = opts.label || '';
    btn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (opts.onPick) opts.onPick();
    });
    return btn;
  }

  function focusItem(menu, index) {
    var items = menu.querySelectorAll('[role="menuitemradio"], [role="menuitem"]');
    if (!items.length) return;
    var i = (index + items.length) % items.length;
    items[i].focus();
  }

  function itemIndex(menu, el) {
    var items = menu.querySelectorAll('[role="menuitemradio"], [role="menuitem"]');
    for (var i = 0; i < items.length; i += 1) if (items[i] === el) return i;
    return 0;
  }

  function openTypeMenu(host, pill, state, apply) {
    closeOpenMenu();
    var menu = document.createElement('div');
    menu.className = 'rv-tag-menu rv-tag-menu--type';
    menu.setAttribute('role', 'menu');
    menu.id = 'rv-tag-menu-' + String(state.workoutId || 'x');
    TYPE_OPTIONS.forEach(function (t) {
      menu.appendChild(menuItem({
        current: state.runSubtype === t.key,
        html: '<span class="rv-tag-dot rv-tag-dot--' + t.key + '" style="background:' + t.color + '"></span>' +
          '<span>' + t.label + '</span>',
        onPick: function () { apply({ run_subtype: t.key }); },
      }));
    });
    if (state.runSubtype) {
      var div = document.createElement('div');
      div.className = 'rv-tag-menu-div';
      menu.appendChild(div);
      menu.appendChild(menuItem({
        clear: true,
        label: 'Clear type',
        onPick: function () { apply({ run_subtype: null }); },
      }));
    }
    document.body.appendChild(menu);
    pill.setAttribute('aria-expanded', 'true');
    pill.setAttribute('aria-controls', menu.id);
    positionMenu(menu, pill);
    var current = menu.querySelector('.is-current') || menu.querySelector('[role="menuitemradio"]');
    if (current) current.focus();
    bindMenuChrome(menu, pill, null);
  }

  function openRpeMenu(host, pill, state, apply) {
    closeOpenMenu();
    var menu = document.createElement('div');
    menu.className = 'rv-tag-menu rv-tag-menu--rpe';
    menu.setAttribute('role', 'menu');
    menu.id = 'rv-tag-menu-rpe-' + String(state.workoutId || 'x');
    var n;
    for (n = 1; n <= 10; n += 1) {
      (function (val) {
        var c = rpeColors(val);
        var anchor = RPE_ANCHORS[val] || '';
        menu.appendChild(menuItem({
          current: Number(state.rpe) === val,
          html: '<span class="rv-tag-sq" style="background:' + c.bg + ';color:' + c.fg + '">' + val + '</span>' +
            '<span class="rv-tag-anchor">' + anchor + '</span>',
          onPick: function () { apply({ session_effort: val }); },
        }));
      })(n);
    }
    if (state.rpe != null) {
      var div = document.createElement('div');
      div.className = 'rv-tag-menu-div';
      menu.appendChild(div);
      menu.appendChild(menuItem({
        clear: true,
        label: 'Clear RPE',
        onPick: function () { apply({ session_effort: null }); },
      }));
    }
    document.body.appendChild(menu);
    pill.setAttribute('aria-expanded', 'true');
    pill.setAttribute('aria-controls', menu.id);
    positionMenu(menu, pill);
    var current = menu.querySelector('.is-current');
    if (current && current.scrollIntoView) {
      current.scrollIntoView({ block: 'nearest' });
      current.focus();
    } else {
      var first = menu.querySelector('[role="menuitemradio"]');
      if (first) first.focus();
    }
    bindMenuChrome(menu, pill, function (key) {
      if (key === '0') { apply({ session_effort: 10 }); return true; }
      if (key >= '1' && key <= '9') { apply({ session_effort: Number(key) }); return true; }
      return false;
    });
  }

  function bindMenuChrome(menu, pill, onDigit) {
    function onDocClick(e) {
      if (menu.contains(e.target) || pill.contains(e.target)) return;
      closeOpenMenu();
    }
    function onKey(e) {
      if (e.key === 'Escape') {
        e.preventDefault();
        e.stopPropagation();
        closeOpenMenu();
        pill.focus();
        return;
      }
      if (onDigit && onDigit(e.key)) {
        e.preventDefault();
        e.stopPropagation();
        return;
      }
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        e.stopPropagation();
        var dir = e.key === 'ArrowDown' ? 1 : -1;
        focusItem(menu, itemIndex(menu, document.activeElement) + dir);
      }
      if (e.key === 'Enter' || e.key === ' ') {
        if (document.activeElement && menu.contains(document.activeElement)) {
          e.preventDefault();
          e.stopPropagation();
          document.activeElement.click();
        }
      }
    }
    document.addEventListener('mousedown', onDocClick, true);
    document.addEventListener('keydown', onKey, true);
    openMenu = { el: menu, pill: pill, onDocClick: onDocClick, onKey: onKey };
  }

  function mount(host, opts) {
    if (!host) return null;
    if (typeof opts !== 'object' || opts === null) return null;
    var workoutId = opts.workoutId;
    if (!workoutId) return null;
    var state = {
      workoutId: workoutId,
      isRun: !!opts.isRun,
      runSubtype: opts.runSubtype || null,
      rpe: parseRpe(opts.rpe),
    };
    var onChange = opts.onChange;
    closeOpenMenu();
    host.classList.add('rv-feel', 'rv-session-tags');
    host.setAttribute('role', 'group');
    host.setAttribute('aria-label', 'Session type and RPE');
    host.innerHTML = '';
    if (!host._rvTagBound) {
      host._rvTagBound = true;
      host.addEventListener('click', function (e) { e.stopPropagation(); });
      host.addEventListener('mousedown', function (e) { e.stopPropagation(); });
      host.addEventListener('keydown', function (e) { e.stopPropagation(); });
    }

    function apply(body) {
      var prevSubtype = state.runSubtype;
      var prevRpe = state.rpe;
      hideError(host);
      if (Object.prototype.hasOwnProperty.call(body, 'run_subtype')) {
        state.runSubtype = body.run_subtype;
      }
      if (Object.prototype.hasOwnProperty.call(body, 'session_effort')) {
        state.rpe = body.session_effort;
      }
      paintPills(host, state);
      closeOpenMenu();
      patchFields(workoutId, body, function (json, err) {
        if (err) {
          state.runSubtype = prevSubtype;
          state.rpe = prevRpe;
          paintPills(host, state);
          showError(host);
          return;
        }
        if (json && Object.prototype.hasOwnProperty.call(json, 'run_subtype')) {
          state.runSubtype = json.run_subtype;
        }
        if (json && Object.prototype.hasOwnProperty.call(json, 'session_effort')) {
          state.rpe = json.session_effort;
        }
        paintPills(host, state);
        if (onChange) {
          onChange({
            field: Object.prototype.hasOwnProperty.call(body, 'run_subtype') ? 'run_subtype' : 'session_effort',
            runSubtype: state.runSubtype,
            rpe: state.rpe,
            tss: json && json.tss,
            body: json,
          });
        }
      });
    }

    if (state.isRun) {
      var typeBtn = document.createElement('button');
      typeBtn.type = 'button';
      typeBtn.setAttribute('data-tag', 'type');
      typeBtn.setAttribute('aria-haspopup', 'menu');
      typeBtn.setAttribute('aria-expanded', 'false');
      typeBtn.setAttribute('aria-label', 'Run type');
      typeBtn.addEventListener('click', function (e) {
        e.preventDefault();
        e.stopPropagation();
        if (openMenu && openMenu.pill === typeBtn) { closeOpenMenu(); return; }
        openTypeMenu(host, typeBtn, state, apply);
      });
      host.appendChild(typeBtn);
    }

    var rpeBtn = document.createElement('button');
    rpeBtn.type = 'button';
    rpeBtn.setAttribute('data-tag', 'rpe');
    rpeBtn.setAttribute('aria-haspopup', 'menu');
    rpeBtn.setAttribute('aria-expanded', 'false');
    rpeBtn.setAttribute('aria-label', 'Session RPE');
    rpeBtn.addEventListener('click', function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (openMenu && openMenu.pill === rpeBtn) { closeOpenMenu(); return; }
      openRpeMenu(host, rpeBtn, state, apply);
    });
    host.appendChild(rpeBtn);
    paintPills(host, state);
    return host;
  }

  function mountAlias(host, workoutIdOrOpts, current, onChange) {
    if (workoutIdOrOpts && typeof workoutIdOrOpts === 'object') {
      return mount(host, workoutIdOrOpts);
    }
    return mount(host, {
      workoutId: workoutIdOrOpts,
      isRun: !!(host && host.getAttribute('data-is-run') === '1'),
      runSubtype: host ? (host.getAttribute('data-run-subtype') || null) : null,
      rpe: host ? parseRpe(host.getAttribute('data-rpe')) : null,
      onChange: onChange,
    });
  }

  global.V2SessionTags = {
    mount: mount,
    preview: preview,
    patch: patchFields,
    typeLabelFor: typeLabelFor,
    rpeLabelFor: rpeLabelFor,
  };
  global.V2FeelButtons = { mount: mountAlias, patch: patchFeeling };

  var RUN_TYPES = [
    { key: 'easy', label: 'Easy' },
    { key: 'tempo', label: 'Tempo' },
    { key: 'interval', label: 'Intervals' },
    { key: 'longrun', label: 'Long run' },
    { key: 'race', label: 'Race' },
  ];
  var RUN_TYPE_TOAST = {
    easy: 'Marked as easy',
    tempo: 'Marked as tempo',
    interval: 'Marked as intervals',
    longrun: 'Marked as long run',
    race: 'Marked as race',
  };

  function patchRunType(workoutId, value, onDone) {
    return fetch('/api/workouts/' + encodeURIComponent(workoutId), {
      method: 'PATCH',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_subtype: value }),
    })
      .then(function (r) {
        if (!r.ok) throw new Error();
        return r.json();
      })
      .then(function (body) {
        var subtype = body && Object.prototype.hasOwnProperty.call(body, 'run_subtype')
          ? body.run_subtype
          : value;
        if (onDone) onDone(subtype, false, body);
      })
      .catch(function () {
        if (onDone) onDone(undefined, true);
      });
  }

  function paintTypeBadge(subtype) {
    var group = document.querySelector('.rd4-typebadges');
    if (!group) return;
    var subLabel = null;
    RUN_TYPES.forEach(function (t) {
      if (t.key === subtype && t.key !== 'race') subLabel = t.label.toLowerCase();
    });
    group.innerHTML = subtype === 'race'
      ? '<span class="rd4-typebadge rd4-typebadge--race">RACE</span>'
      : '<span class="rd4-typebadge">RUN</span>' +
        (subLabel
          ? '<span class="rd4-typebadge rd4-subtypebadge">' + subLabel + '</span>'
          : '');
  }

  function renderTypeButtons(wrap, workoutId, current, onChange) {
    wrap.innerHTML = '';
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'Session type');
    var lab = document.createElement('span');
    lab.className = 'rd4-runtype-label';
    lab.textContent = 'Type';
    wrap.appendChild(lab);
    RUN_TYPES.forEach(function (t) {
      var on = current === t.key;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'rv-feel-btn' + (t.key === 'race' ? ' rv-feel-btn--race' : '') + (on ? ' is-on' : '');
      btn.textContent = t.label;
      btn.title = on ? t.label + ' — tap to clear' : t.label;
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        patchRunType(workoutId, on ? null : t.key, function (val, err) {
          if (err) return;
          renderTypeButtons(wrap, workoutId, val, onChange);
          paintTypeBadge(val);
          if (onChange) onChange(val);
          if (typeof window !== 'undefined' && window.dispatchEvent) {
            window.dispatchEvent(new CustomEvent('v2:log-refresh'));
          }
        });
      });
      wrap.appendChild(btn);
    });
  }

  function mountRunType(host, workoutId, current, onChange) {
    if (!host || !workoutId) return null;
    host.classList.add('rd4-runtype');
    renderTypeButtons(host, workoutId, current, onChange);
    return host;
  }

  global.V2RunTypeButtons = {
    mount: mountRunType,
    patch: patchRunType,
    toast: RUN_TYPE_TOAST,
  };
})(window);
