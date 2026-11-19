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
        if (onDone) onDone(value);
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
})(window);