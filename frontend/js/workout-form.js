(function (global) {
  'use strict';

  function getBangkokDate() {
    return new Date().toLocaleDateString('en-CA', { timeZone: 'Asia/Bangkok' });
  }

  function showToast(msg, isError) {
    var t = document.createElement('div');
    t.className = 'wf-toast' + (isError ? ' wf-toast-error' : '');
    t.textContent = msg;
    t.style.cssText = [
      'position:fixed',
      'bottom:80px',
      'left:50%',
      'transform:translateX(-50%)',
      'background:' + (isError ? '#7a1a1a' : '#1a3a1a'),
      'color:#fff',
      'padding:10px 20px',
      'border-radius:8px',
      'font-size:14px',
      'font-weight:600',
      'z-index:10001',
      'pointer-events:none',
      'box-shadow:0 4px 16px rgba(0,0,0,0.2)',
      'white-space:nowrap',
    ].join(';');
    document.body.appendChild(t);
    setTimeout(function () { t.remove(); }, 3000);
  }

  var TYPES = [
    { value: 'run',      label: 'Run' },
    { value: 'strength', label: 'Strength' },
  ];

  function buildTypeSelector(selected) {
    return TYPES.map(function (t) {
      return '<button type="button" class="wf-type-btn' + (t.value === selected ? ' active' : '') + '" data-type="' + t.value + '">' + t.label + '</button>';
    }).join('');
  }

  function buildRunFields() {
    return [
      '<div class="wf-field">',
        '<label class="wf-label">Date</label>',
        '<input type="date" id="wf-date" class="wf-input" value="' + getBangkokDate() + '">',
      '</div>',
      '<div class="wf-field">',
        '<label class="wf-label">Name <span class="wf-optional">(optional)</span></label>',
        '<input type="text" id="wf-name" class="wf-input" placeholder="Run">',
      '</div>',
      '<div class="wf-field">',
        '<label class="wf-label">Distance (km) <span class="wf-required">*</span></label>',
        '<input type="number" id="wf-distance-km" class="wf-input" min="0.1" max="100" step="0.1" placeholder="e.g. 5">',
        '<div class="wf-error" id="wf-distance-km-err"></div>',
      '</div>',
      '<div class="wf-field">',
        '<label class="wf-label">Duration (minutes) <span class="wf-required">*</span></label>',
        '<input type="number" id="wf-duration-minutes" class="wf-input" min="1" max="480" step="1" placeholder="e.g. 30">',
        '<div class="wf-error" id="wf-duration-minutes-err"></div>',
      '</div>',
      '<div class="wf-field">',
        '<label class="wf-label">Avg HR <span class="wf-optional">(optional)</span></label>',
        '<input type="number" id="wf-avg-hr" class="wf-input" min="80" max="220" step="1" placeholder="e.g. 145">',
        '<div class="wf-error" id="wf-avg-hr-err"></div>',
      '</div>',
      '<div class="wf-field">',
        '<label class="wf-label">Zone 2 minutes <span class="wf-optional">(optional)</span></label>',
        '<input type="number" id="wf-zone2-minutes" class="wf-input" min="0" step="1" placeholder="e.g. 20">',
        '<div class="wf-error" id="wf-zone2-minutes-err"></div>',
      '</div>',
      '<div class="wf-field">',
        '<label class="wf-label">Notes <span class="wf-optional">(optional)</span></label>',
        '<textarea id="wf-notes" class="wf-input wf-textarea" maxlength="500" rows="3" placeholder="How did it feel?"></textarea>',
        '<div class="wf-char-count" id="wf-notes-count">500 remaining</div>',
      '</div>',
    ].join('');
  }

  function buildStrengthFields() {
    return [
      '<div class="wf-field">',
        '<label class="wf-label">Date</label>',
        '<input type="date" id="wf-date" class="wf-input" value="' + getBangkokDate() + '">',
      '</div>',
      '<div class="wf-field">',
        '<label class="wf-label">Name <span class="wf-optional">(optional)</span></label>',
        '<input type="text" id="wf-name" class="wf-input" placeholder="Strength training">',
      '</div>',
      '<div class="wf-field">',
        '<label class="wf-label">Duration (minutes) <span class="wf-required">*</span></label>',
        '<input type="number" id="wf-duration-minutes" class="wf-input" min="1" max="480" step="1" placeholder="e.g. 45">',
        '<div class="wf-error" id="wf-duration-minutes-err"></div>',
      '</div>',
      '<div class="wf-field">',
        '<label class="wf-label">Exercises <span class="wf-optional">(optional)</span></label>',
        '<textarea id="wf-exercises" class="wf-input wf-textarea" maxlength="2000" rows="5" placeholder="e.g. Squat 3×5, Bench 3×8…"></textarea>',
        '<div class="wf-char-count" id="wf-exercises-count">2000 remaining</div>',
      '</div>',
      '<div class="wf-field">',
        '<label class="wf-label">Avg HR <span class="wf-optional">(optional)</span></label>',
        '<input type="number" id="wf-avg-hr" class="wf-input" min="80" max="220" step="1" placeholder="e.g. 130">',
        '<div class="wf-error" id="wf-avg-hr-err"></div>',
      '</div>',
      '<div class="wf-field">',
        '<label class="wf-label">Notes <span class="wf-optional">(optional)</span></label>',
        '<textarea id="wf-notes" class="wf-input wf-textarea" maxlength="500" rows="2" placeholder="How did it feel?"></textarea>',
        '<div class="wf-char-count" id="wf-notes-count">500 remaining</div>',
      '</div>',
    ].join('');
  }

  function buildFormHTML(type) {
    var fields = type === 'strength' ? buildStrengthFields() : buildRunFields();
    return [
      '<div class="wf-modal-inner" role="dialog" aria-modal="true" aria-label="Log workout">',
        '<div class="wf-header">',
          '<h2 class="wf-title">Log workout</h2>',
          '<button type="button" class="wf-close" aria-label="Close">&#x2715;</button>',
        '</div>',
        '<div class="wf-type-selector">',
          buildTypeSelector(type),
        '</div>',
        '<form id="wf-form" class="wf-body" novalidate>',
          '<div id="wf-fields">' + fields + '</div>',
          '<div class="wf-error wf-submit-error" id="wf-submit-err" style="display:none"></div>',
          '<div class="wf-footer">',
            '<button type="submit" class="wf-submit-btn" id="wf-submit">Log workout</button>',
            '<a class="wf-full-editor-link" href="/training">Need intervals or templates? Open the full editor</a>',
          '</div>',
        '</form>',
      '</div>',
    ].join('');
  }

  function setError(id, msg) {
    var el = document.getElementById(id);
    if (el) { el.textContent = msg; el.style.display = msg ? '' : 'none'; }
  }

  function clearErrors() {
    ['wf-distance-km-err', 'wf-duration-minutes-err', 'wf-avg-hr-err',
     'wf-zone2-minutes-err', 'wf-submit-err'].forEach(function (id) {
      setError(id, '');
    });
  }

  function getDurationMinutes() {
    var el = document.getElementById('wf-duration-minutes');
    return el ? el.value : '';
  }

  function validateRun() {
    var ok = true;
    var dist = parseFloat(document.getElementById('wf-distance-km').value);
    if (!document.getElementById('wf-distance-km').value) {
      setError('wf-distance-km-err', 'Distance is required'); ok = false;
    } else if (isNaN(dist) || dist < 0.1 || dist > 100) {
      setError('wf-distance-km-err', 'Distance must be 0.1–100 km'); ok = false;
    }

    var duration_minutes = parseInt(getDurationMinutes(), 10);
    if (!getDurationMinutes()) {
      setError('wf-duration-minutes-err', 'Duration is required'); ok = false;
    } else if (isNaN(duration_minutes) || duration_minutes < 1 || duration_minutes > 480) {
      setError('wf-duration-minutes-err', 'Duration must be 1–480 minutes'); ok = false;
    }

    var hrEl = document.getElementById('wf-avg-hr');
    if (hrEl && hrEl.value) {
      var hr = parseInt(hrEl.value, 10);
      if (isNaN(hr) || hr < 80 || hr > 220) {
        setError('wf-avg-hr-err', 'Avg HR must be 80–220'); ok = false;
      }
    }

    var z2El = document.getElementById('wf-zone2-minutes');
    if (z2El && z2El.value !== '') {
      var z2 = parseInt(z2El.value, 10);
      var durVal = parseInt(getDurationMinutes(), 10);
      if (isNaN(z2) || z2 < 0) {
        setError('wf-zone2-minutes-err', 'Zone 2 minutes must be ≥ 0'); ok = false;
      } else if (!isNaN(durVal) && z2 > durVal) {
        setError('wf-zone2-minutes-err', 'Zone 2 minutes cannot exceed duration'); ok = false;
      }
    }
    return ok;
  }

  function validateStrength() {
    var ok = true;
    var duration_minutes = parseInt(getDurationMinutes(), 10);
    if (!getDurationMinutes()) {
      setError('wf-duration-minutes-err', 'Duration is required'); ok = false;
    } else if (isNaN(duration_minutes) || duration_minutes < 1 || duration_minutes > 480) {
      setError('wf-duration-minutes-err', 'Duration must be 1–480 minutes'); ok = false;
    }

    var hrEl = document.getElementById('wf-avg-hr');
    if (hrEl && hrEl.value) {
      var hr = parseInt(hrEl.value, 10);
      if (isNaN(hr) || hr < 80 || hr > 220) {
        setError('wf-avg-hr-err', 'Avg HR must be 80–220'); ok = false;
      }
    }
    return ok;
  }

  function collectRun() {
    var nameEl = document.getElementById('wf-name');
    var name = (nameEl && nameEl.value.trim()) || 'Run';
    var dateEl = document.getElementById('wf-date');
    var duration_minutes = parseInt(getDurationMinutes(), 10);
    var dist = parseFloat(document.getElementById('wf-distance-km').value);
    var hrEl = document.getElementById('wf-avg-hr');
    var z2El = document.getElementById('wf-zone2-minutes');
    var notesEl = document.getElementById('wf-notes');

    var payload = {
      name: name,
      workout_date: dateEl ? dateEl.value : getBangkokDate(),
      workout_type: 'run',
      duration_seconds: duration_minutes * 60,
      distance_km: dist,
      exercises: [],
    };
    if (hrEl && hrEl.value) payload.avg_hr = parseInt(hrEl.value, 10);
    if (z2El && z2El.value !== '') payload.zone2_minutes = parseInt(z2El.value, 10);
    if (notesEl && notesEl.value.trim()) payload.remarks = notesEl.value.trim();
    return payload;
  }

  function collectStrength() {
    var nameEl = document.getElementById('wf-name');
    var name = (nameEl && nameEl.value.trim()) || 'Strength training';
    var dateEl = document.getElementById('wf-date');
    var duration_minutes = parseInt(getDurationMinutes(), 10);
    var exEl = document.getElementById('wf-exercises');
    var hrEl = document.getElementById('wf-avg-hr');
    var notesEl = document.getElementById('wf-notes');

    var payload = {
      name: name,
      workout_date: dateEl ? dateEl.value : getBangkokDate(),
      workout_type: 'strength',
      duration_seconds: duration_minutes * 60,
      exercises: [],
    };
    if (hrEl && hrEl.value) payload.avg_hr = parseInt(hrEl.value, 10);

    var parts = [];
    if (exEl && exEl.value.trim()) parts.push(exEl.value.trim());
    if (notesEl && notesEl.value.trim()) parts.push(notesEl.value.trim());
    if (parts.length) payload.remarks = parts.join('\n\n');
    return payload;
  }

  function wireCharCounts() {
    [
      { inputId: 'wf-notes',     countId: 'wf-notes-count',     max: 500 },
      { inputId: 'wf-exercises', countId: 'wf-exercises-count', max: 2000 },
    ].forEach(function (cfg) {
      var el = document.getElementById(cfg.inputId);
      var cnt = document.getElementById(cfg.countId);
      if (!el || !cnt) return;
      el.addEventListener('input', function () {
        var remaining = cfg.max - el.value.length;
        cnt.textContent = remaining + ' remaining';
        cnt.style.color = remaining < 0 ? '#dc2626' : '';
      });
    });
  }

  function openWorkoutForm() {
    var existing = document.getElementById('wf-overlay');
    if (existing) existing.remove();

    var currentType = 'run';

    var overlay = document.createElement('div');
    overlay.id = 'wf-overlay';
    overlay.className = 'wf-overlay';
    overlay.innerHTML = buildFormHTML(currentType);

    var style = document.getElementById('wf-style');
    if (!style) {
      style = document.createElement('style');
      style.id = 'wf-style';
      style.textContent = [
        '.wf-overlay{position:fixed;inset:0;background:rgba(0,0,0,0.5);z-index:9999;display:flex;align-items:flex-end;justify-content:center;}',
        '@media (min-width:501px){.wf-overlay{align-items:center;}}',
        '.wf-modal-inner{background:#fff;width:100%;max-width:480px;border-radius:16px 16px 0 0;padding:20px 16px 32px;max-height:90vh;overflow-y:auto;display:flex;flex-direction:column;gap:0;}',
        '@media (min-width:501px){.wf-modal-inner{border-radius:16px;}}',
        '.wf-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px;}',
        '.wf-title{font-size:18px;font-weight:700;margin:0;color:#0b1530;}',
        '.wf-close{background:none;border:none;font-size:20px;cursor:pointer;color:#5c6886;padding:4px 8px;border-radius:6px;line-height:1;}',
        '.wf-type-selector{display:flex;gap:8px;margin-bottom:20px;}',
        '.wf-type-btn{flex:1;padding:10px;border:2px solid #d8e3f5;border-radius:10px;background:#f5f8ff;font-size:14px;font-weight:600;cursor:pointer;color:#5c6886;transition:all 0.15s;}',
        '.wf-type-btn.active{border-color:#5a8dee;background:#5a8dee;color:#fff;}',
        '.wf-body{display:flex;flex-direction:column;gap:0;}',
        '.wf-field{display:flex;flex-direction:column;gap:4px;margin-bottom:14px;}',
        '.wf-label{font-size:13px;font-weight:600;color:#0b1530;}',
        '.wf-optional{font-weight:400;color:#8b95ad;}',
        '.wf-required{color:#dc2626;}',
        '.wf-input{width:100%;padding:10px 12px;border:1.5px solid #d8e3f5;border-radius:8px;font-size:15px;font-family:inherit;color:#0b1530;background:#fff;box-sizing:border-box;min-height:44px;}',
        '.wf-input:focus{outline:none;border-color:#5a8dee;}',
        '.wf-textarea{min-height:80px;resize:vertical;}',
        '.wf-char-count{font-size:11px;color:#8b95ad;text-align:right;}',
        '.wf-error{font-size:12px;color:#dc2626;min-height:16px;}',
        '.wf-footer{margin-top:8px;}',
        '.wf-full-editor-link{display:block;text-align:center;margin-top:10px;font-size:13px;color:#5c6886;text-decoration:underline;}',
        '.wf-submit-btn{width:100%;padding:14px;background:#5a8dee;color:#fff;border:none;border-radius:10px;font-size:16px;font-weight:700;cursor:pointer;min-height:48px;}',
        '.wf-submit-btn:disabled{opacity:0.6;cursor:not-allowed;}',
        '.wf-submit-error{margin-bottom:8px;}',
      ].join('');
      document.head.appendChild(style);
    }

    document.body.appendChild(overlay);
    wireCharCounts();

    overlay.addEventListener('click', function (e) {
      if (e.target === overlay) closeForm();
    });

    overlay.querySelector('.wf-close').addEventListener('click', closeForm);

    overlay.querySelectorAll('.wf-type-btn').forEach(function (btn) {
      btn.addEventListener('click', function () {
        currentType = btn.dataset.type;
        var fieldsEl = document.getElementById('wf-fields');
        fieldsEl.innerHTML = currentType === 'strength' ? buildStrengthFields() : buildRunFields();
        overlay.querySelectorAll('.wf-type-btn').forEach(function (b) {
          b.classList.toggle('active', b.dataset.type === currentType);
        });
        wireCharCounts();
      });
    });

    var form = document.getElementById('wf-form');
    form.addEventListener('submit', async function (e) {
      e.preventDefault();
      clearErrors();

      var valid = currentType === 'strength' ? validateStrength() : validateRun();
      if (!valid) return;

      var payload = currentType === 'strength' ? collectStrength() : collectRun();
      var submitBtn = document.getElementById('wf-submit');
      submitBtn.disabled = true;

      try {
        var response = await fetch('/api/workouts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        if (response.ok) {
          closeForm();
          showToast('Workout logged');
          setTimeout(function () { location.reload(); }, 400);
        } else {
          var data = await response.json().catch(function () { return {}; });
          var msg = (data && data.detail) ? data.detail : 'Failed to save workout. Please try again.';
          var errEl = document.getElementById('wf-submit-err');
          if (errEl) { errEl.textContent = msg; errEl.style.display = ''; }
          showToast(msg, true);
          submitBtn.disabled = false;
        }
      } catch (err) {
        var errEl = document.getElementById('wf-submit-err');
        if (errEl) { errEl.textContent = 'Network error. Please try again.'; errEl.style.display = ''; }
        showToast('Network error. Please try again.', true);
        submitBtn.disabled = false;
      }
    });
  }

  function closeForm() {
    var overlay = document.getElementById('wf-overlay');
    if (overlay) overlay.remove();
  }

  global.WorkoutForm = { open: openWorkoutForm, close: closeForm };

})(window);
