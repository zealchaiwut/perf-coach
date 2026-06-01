(function () {
  'use strict';

  var currentUserId = null;
  var currentView = 'new';
  var editingWorkoutId = null;
  var dragSrcIdx = null;
  var WORKOUT_TYPES = ['Strength', 'Running', 'Race', 'Yoga'];

  // ── Helpers ──────────────────────────────────────────────────────────────────

  function todayIso() {
    var d = new Date();
    var m = String(d.getMonth() + 1).padStart(2, '0');
    var day = String(d.getDate()).padStart(2, '0');
    return d.getFullYear() + '-' + m + '-' + day;
  }

  function relativeDate(iso) {
    var now = new Date();
    var then = new Date(iso + 'T00:00:00');
    var diffDays = Math.round((new Date(todayIso() + 'T00:00:00') - then) / 86400000);
    if (diffDays === 0) return 'Today';
    if (diffDays === 1) return 'Yesterday';
    if (diffDays < 7) return diffDays + ' days ago';
    return then.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  }

  function typeIcon(t) {
    var icons = { Strength: '🏋', Running: '🏃', Race: '🏁', Yoga: '🧘' };
    return icons[t] || '⚡';
  }

  function showToast(msg, isError) {
    var t = document.getElementById('toast');
    t.textContent = msg;
    t.className = 'toast' + (isError ? ' toast-error' : ' toast-ok');
    t.style.display = 'block';
    setTimeout(function () { t.style.display = 'none'; }, 3000);
  }

  // ── Tab switching ─────────────────────────────────────────────────────────────

  function switchTab(name) {
    currentView = name;
    document.querySelectorAll('.training-tab').forEach(function (btn) {
      btn.classList.toggle('active', btn.dataset.tab === name);
    });
    document.getElementById('view-new').style.display = name === 'new' ? '' : 'none';
    document.getElementById('view-history').style.display = name === 'history' ? '' : 'none';
    if (name === 'history' && currentUserId) loadHistory();
  }

  // ── Type chips ────────────────────────────────────────────────────────────────

  function initChips() {
    var container = document.getElementById('type-chips');
    var customInput = document.getElementById('custom-type-input');
    container.innerHTML = '';
    WORKOUT_TYPES.forEach(function (type) {
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'type-chip';
      btn.dataset.value = type;
      btn.textContent = type;
      btn.addEventListener('click', function () { selectChip(type); });
      container.appendChild(btn);
    });
    var customBtn = document.createElement('button');
    customBtn.type = 'button';
    customBtn.className = 'type-chip';
    customBtn.dataset.value = '__custom__';
    customBtn.textContent = '+ Custom';
    customBtn.addEventListener('click', function () { selectChip('__custom__'); });
    container.appendChild(customBtn);
    selectChip('Strength');
    customInput.addEventListener('input', function () {});
  }

  function selectChip(value) {
    var customInput = document.getElementById('custom-type-input');
    document.querySelectorAll('.type-chip').forEach(function (b) {
      b.classList.toggle('active', b.dataset.value === value);
    });
    customInput.style.display = value === '__custom__' ? 'block' : 'none';
    if (value !== '__custom__') customInput.value = '';
  }

  function getSelectedType() {
    var active = document.querySelector('.type-chip.active');
    if (!active) return 'Strength';
    if (active.dataset.value === '__custom__') {
      return document.getElementById('custom-type-input').value.trim() || 'Custom';
    }
    return active.dataset.value;
  }

  function setSelectedType(type) {
    var known = WORKOUT_TYPES.indexOf(type) !== -1;
    if (known) {
      selectChip(type);
    } else {
      selectChip('__custom__');
      document.getElementById('custom-type-input').value = type;
    }
  }

  // ── Exercise table ─────────────────────────────────────────────────────────────

  function getExerciseRows() {
    var rows = document.querySelectorAll('#exercises-tbody tr');
    var result = [];
    rows.forEach(function (row, i) {
      result.push({
        display_order: i,
        name: row.querySelector('.ex-name').value.trim(),
        sets: parseInt(row.querySelector('.ex-sets').value, 10) || null,
        reps: parseInt(row.querySelector('.ex-reps').value, 10) || null,
        weight_kg: parseFloat(row.querySelector('.ex-weight').value) || null,
        duration: row.querySelector('.ex-duration').value.trim() || null,
        rpe: parseInt(row.querySelector('.ex-rpe').value, 10) || null,
      });
    });
    return result;
  }

  function addExerciseRow(data) {
    var tbody = document.getElementById('exercises-tbody');
    var tr = document.createElement('tr');
    tr.draggable = true;
    tr.innerHTML =
      '<td class="drag-handle" title="Drag to reorder">⠿</td>' +
      '<td><input type="text" class="ex-input ex-name" placeholder="Exercise name" value="' + (data && data.name ? escapeAttr(data.name) : '') + '"></td>' +
      '<td><input type="number" class="ex-input ex-sets" placeholder="—" min="1" value="' + (data && data.sets != null ? data.sets : '') + '"></td>' +
      '<td><input type="number" class="ex-input ex-reps" placeholder="—" min="1" value="' + (data && data.reps != null ? data.reps : '') + '"></td>' +
      '<td><input type="number" class="ex-input ex-weight" placeholder="—" min="0" step="0.5" value="' + (data && data.weight_kg != null ? data.weight_kg : '') + '"></td>' +
      '<td><input type="text" class="ex-input ex-duration" placeholder="—" value="' + (data && data.duration ? escapeAttr(data.duration) : '') + '"></td>' +
      '<td><input type="number" class="ex-input ex-rpe" placeholder="—" min="1" max="10" value="' + (data && data.rpe != null ? data.rpe : '') + '"></td>' +
      '<td><button type="button" class="remove-row-btn" title="Remove exercise">✕</button></td>';

    tr.querySelector('.remove-row-btn').addEventListener('click', function () {
      tr.remove();
    });

    // Tab key advances cells within the row, then jumps to next row's first input
    tr.querySelectorAll('.ex-input').forEach(function (inp, idx, all) {
      inp.addEventListener('keydown', function (e) {
        if (e.key === 'Tab' && !e.shiftKey && idx === all.length - 1) {
          var next = tr.nextElementSibling;
          if (next) {
            e.preventDefault();
            var firstInput = next.querySelector('.ex-input');
            if (firstInput) firstInput.focus();
          }
        }
      });
    });

    // Drag-and-drop reordering
    tr.addEventListener('dragstart', function (e) {
      dragSrcIdx = rowIndex(tr);
      e.dataTransfer.effectAllowed = 'move';
      tr.classList.add('dragging');
    });
    tr.addEventListener('dragend', function () {
      tr.classList.remove('dragging');
      document.querySelectorAll('#exercises-tbody tr').forEach(function (r) {
        r.classList.remove('drag-over');
      });
    });
    tr.addEventListener('dragover', function (e) {
      e.preventDefault();
      e.dataTransfer.dropEffect = 'move';
      document.querySelectorAll('#exercises-tbody tr').forEach(function (r) { r.classList.remove('drag-over'); });
      tr.classList.add('drag-over');
    });
    tr.addEventListener('drop', function (e) {
      e.preventDefault();
      var destIdx = rowIndex(tr);
      if (dragSrcIdx === null || dragSrcIdx === destIdx) return;
      var tbody = document.getElementById('exercises-tbody');
      var rows = Array.from(tbody.querySelectorAll('tr'));
      var srcRow = rows[dragSrcIdx];
      tbody.removeChild(srcRow);
      var refRow = tbody.querySelectorAll('tr')[destIdx] || null;
      tbody.insertBefore(srcRow, refRow);
      dragSrcIdx = null;
    });

    tbody.appendChild(tr);
    tr.querySelector('.ex-name').focus();
  }

  function rowIndex(tr) {
    return Array.from(tr.parentElement.children).indexOf(tr);
  }

  function escapeAttr(s) {
    return String(s).replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ── Form reset / fill ─────────────────────────────────────────────────────────

  function resetForm() {
    editingWorkoutId = null;
    document.getElementById('workout-name').value = '';
    document.getElementById('workout-date').value = todayIso();
    document.getElementById('workout-remarks').value = '';
    document.getElementById('workout-tss').value = '';
    document.getElementById('exercises-tbody').innerHTML = '';
    document.getElementById('exercises-error').textContent = '';
    document.getElementById('name-error').textContent = '';
    document.getElementById('save-workout-btn').textContent = 'Save workout';
    setSelectedType('Strength');
    addExerciseRow(null);
  }

  function fillForm(workout) {
    editingWorkoutId = workout.id;
    document.getElementById('workout-name').value = workout.name;
    document.getElementById('workout-date').value = workout.workout_date;
    document.getElementById('workout-remarks').value = workout.remarks || '';
    document.getElementById('workout-tss').value = workout.tss != null ? workout.tss : '';
    document.getElementById('exercises-tbody').innerHTML = '';
    document.getElementById('exercises-error').textContent = '';
    document.getElementById('name-error').textContent = '';
    document.getElementById('save-workout-btn').textContent = 'Save changes';
    setSelectedType(workout.workout_type);
    (workout.exercises || []).forEach(function (ex) { addExerciseRow(ex); });
    if (!workout.exercises || !workout.exercises.length) addExerciseRow(null);
  }

  // ── Validation ────────────────────────────────────────────────────────────────

  function validateForm() {
    var valid = true;
    var nameEl = document.getElementById('workout-name');
    var nameErr = document.getElementById('name-error');
    var exErr = document.getElementById('exercises-error');

    nameErr.textContent = '';
    exErr.textContent = '';

    if (!nameEl.value.trim()) {
      nameErr.textContent = 'Workout name is required.';
      nameEl.focus();
      valid = false;
    }

    var rows = getExerciseRows();
    if (!rows.length || !rows.some(function (r) { return r.name; })) {
      exErr.textContent = 'Add at least one exercise.';
      valid = false;
    }

    rows.forEach(function (r) {
      if (r.rpe !== null && (r.rpe < 1 || r.rpe > 10)) {
        exErr.textContent = 'RPE must be between 1 and 10.';
        valid = false;
      }
    });

    var dateVal = document.getElementById('workout-date').value;
    if (!dateVal || !/^\d{4}-\d{2}-\d{2}$/.test(dateVal)) {
      document.getElementById('name-error').textContent = (document.getElementById('name-error').textContent ? document.getElementById('name-error').textContent + ' ' : '') + 'Invalid date.';
      valid = false;
    }

    return valid;
  }

  // ── Save workout ──────────────────────────────────────────────────────────────

  async function saveWorkout() {
    if (!validateForm()) return;

    var rows = getExerciseRows().filter(function (r) { return r.name; });
    var tssRaw = document.getElementById('workout-tss').value.trim();
    var tssVal = tssRaw !== '' ? parseFloat(tssRaw) : null;
    var payload = {
      user_id: currentUserId,
      name: document.getElementById('workout-name').value.trim(),
      workout_date: document.getElementById('workout-date').value,
      workout_type: getSelectedType(),
      remarks: document.getElementById('workout-remarks').value.trim() || null,
      tss: tssVal,
      exercises: rows,
    };

    var btn = document.getElementById('save-workout-btn');
    btn.disabled = true;

    try {
      var res;
      if (editingWorkoutId) {
        res = await fetch('/api/workouts/' + editingWorkoutId, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        res = await fetch('/api/workouts', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }

      if (!res.ok) {
        var err = await res.json().catch(function () { return {}; });
        showToast('Save failed: ' + (err.detail || res.status), true);
        return;
      }

      showToast(editingWorkoutId ? 'Workout updated!' : 'Workout saved!');
      resetForm();
      // Return to the Training Log (the canonical history view) — brief delay
      // so the success toast is visible before we navigate.
      setTimeout(function () { window.location.href = '/log'; }, 700);
    } catch (e) {
      showToast('Save failed: ' + e.message, true);
    } finally {
      btn.disabled = false;
    }
  }

  // ── History view ──────────────────────────────────────────────────────────────

  async function loadHistory() {
    if (!currentUserId) return;
    var list = document.getElementById('history-list');
    list.innerHTML = '<p class="loading-msg">Loading…</p>';
    try {
      // /api/workouts takes a from/to range (YYYY-MM-DD), not a day count.
      function ymd(d) {
        return d.getFullYear() + '-' +
          String(d.getMonth() + 1).padStart(2, '0') + '-' +
          String(d.getDate()).padStart(2, '0');
      }
      var to = new Date();
      var from = new Date();
      from.setDate(from.getDate() - 30);
      var res = await fetch('/api/workouts?user_id=' + encodeURIComponent(currentUserId) +
        '&from=' + ymd(from) + '&to=' + ymd(to));
      if (!res.ok) throw new Error('Server error ' + res.status);
      var workouts = await res.json();
      renderHistory(workouts);
    } catch (e) {
      list.innerHTML = '<p class="error-msg">Failed to load history: ' + e.message + '</p>';
    }
  }

  function renderHistory(workouts) {
    var list = document.getElementById('history-list');
    if (!workouts.length) {
      list.innerHTML = '<p class="empty-msg">No workouts yet.</p>';
      return;
    }
    list.innerHTML = '';
    workouts.forEach(function (w) {
      var row = document.createElement('div');
      row.className = 'history-row';
      var count = w.exercise_count || 0;
      row.innerHTML =
        '<div class="history-main">' +
          '<span class="history-name">' + escapeHtml(w.name) + '</span>' +
          '<span class="history-meta">' +
            '<span class="history-date">' + relativeDate(w.workout_date) + '</span>' +
            '<span class="history-type">' + typeIcon(w.workout_type) + ' ' + escapeHtml(w.workout_type) + '</span>' +
            '<span class="history-count">' + count + ' exercise' + (count !== 1 ? 's' : '') + '</span>' +
          '</span>' +
        '</div>' +
        '<span class="history-chevron">›</span>';
      row.addEventListener('click', function () { openDetail(w); });
      list.appendChild(row);
    });
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── Detail modal ──────────────────────────────────────────────────────────────

  async function openDetail(listItem) {
    // The history list omits exercises; fetch the full workout for the modal + edit.
    var workout = listItem;
    try {
      var full = await fetch('/api/workouts/' + listItem.id);
      if (full.ok) workout = await full.json();
    } catch (e) { /* fall back to the list item */ }

    var modal = document.getElementById('detail-modal');
    document.getElementById('detail-title').textContent = workout.name;
    document.getElementById('detail-meta').textContent =
      workout.workout_date + ' · ' + workout.workout_type +
      (workout.remarks ? ' · ' + workout.remarks : '');

    var tbody = document.getElementById('detail-exercises-tbody');
    tbody.innerHTML = '';
    (workout.exercises || []).forEach(function (ex) {
      var tr = document.createElement('tr');
      tr.innerHTML =
        '<td>' + escapeHtml(ex.name) + '</td>' +
        '<td>' + (ex.sets != null ? ex.sets : '—') + '</td>' +
        '<td>' + (ex.reps != null ? ex.reps : '—') + '</td>' +
        '<td>' + (ex.weight_kg != null ? ex.weight_kg + ' kg' : '—') + '</td>' +
        '<td>' + (ex.duration || '—') + '</td>' +
        '<td>' + (ex.rpe != null ? ex.rpe : '—') + '</td>';
      tbody.appendChild(tr);
    });

    modal.dataset.workoutId = workout.id;
    modal.style.display = 'flex';
    document.getElementById('detail-delete-btn').onclick = function () { deleteWorkout(workout.id); };
    document.getElementById('detail-edit-btn').onclick = function () {
      modal.style.display = 'none';
      fillForm(workout);
      switchTab('new');
    };
  }

  async function deleteWorkout(id) {
    if (!confirm('Delete this workout?')) return;
    try {
      var res = await fetch('/api/workouts/' + id, { method: 'DELETE' });
      if (!res.ok) throw new Error('Server error ' + res.status);
      document.getElementById('detail-modal').style.display = 'none';
      showToast('Workout deleted.');
      loadHistory();
    } catch (e) {
      showToast('Delete failed: ' + e.message, true);
    }
  }

  // ── Init ──────────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    initChips();
    document.getElementById('workout-date').value = todayIso();
    addExerciseRow(null);

    var editId = new URLSearchParams(location.search).get('edit');
    if (editId) {
      fetch('/api/workouts/' + encodeURIComponent(editId))
        .then(function (res) { if (!res.ok) throw new Error('not found'); return res.json(); })
        .then(function (workout) { fillForm(workout); })
        .catch(function () { /* leave default new-workout form */ });
    }

    document.querySelectorAll('.training-tab').forEach(function (btn) {
      btn.addEventListener('click', function () { switchTab(btn.dataset.tab); });
    });

    document.getElementById('add-exercise-btn').addEventListener('click', function () {
      addExerciseRow(null);
    });

    document.getElementById('save-workout-btn').addEventListener('click', saveWorkout);

    document.getElementById('cancel-btn').addEventListener('click', function () {
      resetForm();
    });

    document.getElementById('detail-close-btn').addEventListener('click', function () {
      document.getElementById('detail-modal').style.display = 'none';
    });

    document.getElementById('detail-modal').addEventListener('click', function (e) {
      if (e.target === this) this.style.display = 'none';
    });
  });

  window.addEventListener('userReady', function (e) {
    currentUserId = e.detail.userId;
  });

  window.addEventListener('userChanged', function (e) {
    currentUserId = e.detail.userId;
    if (currentView === 'history') {
      loadHistory();
    } else {
      resetForm();
    }
  });
}());
