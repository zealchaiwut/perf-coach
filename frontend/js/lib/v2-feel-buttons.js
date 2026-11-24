(function (global) {
  'use strict';

  var FEELINGS = [
    { key: 'hard', label: 'Hard', text: 'Hard' },
    { key: 'ok', label: 'OK', text: 'OK' },
    { key: 'easy', label: 'Easy', text: 'Easy' },
  ];

  function patchFeeling(workoutId, value, onDone) {
    return fetch('/api/workouts/' + encodeURIComponent(workoutId), {
      method: 'PATCH',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ feeling: value }),
    })
      .then(function (r) {
        if (!r.ok) throw new Error();
        return r.json();
      })
      .then(function (body) {
        var feeling = body && Object.prototype.hasOwnProperty.call(body, 'feeling')
          ? body.feeling
          : value;
        if (onDone) onDone(feeling, false, body);
      })
      .catch(function () {
        if (onDone) onDone(undefined, true);
      });
  }

  function renderButtons(wrap, workoutId, current, onChange) {
    var tagged = current === 'hard' || current === 'ok' || current === 'easy';
    wrap.innerHTML = '';
    wrap.setAttribute('role', 'group');
    wrap.setAttribute('aria-label', 'How it felt');
    FEELINGS.forEach(function (f) {
      var on = current === f.key;
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'rv-feel-btn' + (on ? ' is-on' : '');
      btn.textContent = f.text;
      btn.title = on ? f.label + ' — tap to clear' : f.label;
      btn.setAttribute('aria-pressed', on ? 'true' : 'false');
      btn.addEventListener('click', function (e) {
        e.stopPropagation();
        patchFeeling(workoutId, on ? null : f.key, function (val, err) {
          if (err) return;
          renderButtons(wrap, workoutId, val, onChange);
          if (onChange) onChange(val);
        });
      });
      wrap.appendChild(btn);
    });
    if (tagged) wrap.classList.add('is-tagged');
    else wrap.classList.remove('is-tagged');
  }

  function mount(host, workoutId, current, onChange) {
    if (!host || !workoutId) return null;
    host.classList.add('rv-feel');
    renderButtons(host, workoutId, current, onChange);
    return host;
  }

  global.V2FeelButtons = { mount: mount, patch: patchFeeling };

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