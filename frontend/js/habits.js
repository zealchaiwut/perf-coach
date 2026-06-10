// ── Constants ─────────────────────────────────────────────────────────────────

const ICONS = [
  'ti-run', 'ti-barbell', 'ti-droplet', 'ti-book',
  'ti-bed', 'ti-flame', 'ti-walk', 'ti-bike',
  'ti-meditation', 'ti-shoe', 'ti-clipboard',
];

const COLORS = [
  '#3b82f6', // blue
  '#8b5cf6', // purple
  '#10b981', // green
  '#f59e0b', // amber
  '#ef4444', // red
  '#ec4899', // pink
  '#06b6d4', // cyan
  '#f97316', // orange
];

const TRACKING_TYPE_LABELS = {
  daily_checkmark: 'Daily checkmark',
  weekly_count: 'Weekly count',
  weekly_minutes: 'Weekly minutes',
  weekly_quantity: 'Weekly quantity',
};

const STARTER_HABITS = [
  {
    name: 'Zone 2 cardio',
    tracking_type: 'weekly_minutes',
    weekly_target: 210,
    unit: 'min',
    auto_fill_source: 'workout.zone2_minutes',
    icon: 'ti-run',
    color: '#3b82f6',
    description: 'Low-intensity aerobic training in Zone 2 heart rate',
  },
  {
    name: 'Running sessions',
    tracking_type: 'weekly_count',
    weekly_target: 3,
    unit: 'sessions',
    auto_fill_source: 'workout.run_count',
    icon: 'ti-shoe',
    color: '#3b82f6',
    description: 'Weekly run sessions',
  },
  {
    name: 'Strength sessions',
    tracking_type: 'weekly_count',
    weekly_target: 2,
    unit: 'sessions',
    auto_fill_source: 'workout.lift_count',
    icon: 'ti-barbell',
    color: '#8b5cf6',
    description: 'Weekly strength/lifting sessions',
  },
  {
    name: 'Daily metrics logged',
    tracking_type: 'daily_checkmark',
    weekly_target: 7,
    unit: 'days',
    auto_fill_source: null,
    icon: 'ti-clipboard',
    color: '#10b981',
    description: 'Log HRV, RHR, sleep, mood, and energy daily',
  },
];

// ── State ─────────────────────────────────────────────────────────────────────

let currentUserId = null;
let activeHabits = [];
let archivedHabits = [];
let editingHabitId = null;
let selectedIcon = ICONS[0];
let selectedColor = COLORS[0];
let dragSrcIndex = null;

// ── Helpers ───────────────────────────────────────────────────────────────────

function showError(msg) {
  const el = document.getElementById('api-error');
  if (el) el.textContent = msg;
}

function clearError() { showError(''); }

function iconLabel(code) {
  return code ? code.replace('ti-', '').replace(/-/g, ' ') : '?';
}

function habitIconEl(icon, color) {
  const el = document.createElement('div');
  el.className = 'habit-icon';
  el.style.background = color || '#999';
  el.textContent = iconLabel(icon).slice(0, 2).toUpperCase();
  el.title = icon || '';
  return el;
}

function goalText(habit) {
  if (!habit.weekly_target) return '';
  const unit = habit.unit || '';
  return `Goal: ${habit.weekly_target} ${unit}/week`.trim();
}

function autofillPill(source) {
  const span = document.createElement('span');
  if (source) {
    span.className = 'habit-autofill-pill';
    span.textContent = 'auto from workouts';
    span.title = source;
  } else {
    span.className = 'habit-autofill-pill manual';
    span.textContent = 'manual';
  }
  return span;
}

// ── Load ──────────────────────────────────────────────────────────────────────

async function loadAndRender() {
  clearError();
  const list = document.getElementById('habit-list');
  if (list && typeof UIStates !== 'undefined') UIStates.setLoading(list);

  try {
    const [activeRes, archivedRes] = await Promise.all([
      fetch('/api/habits'),
      fetch('/api/habits?include_archived=true'),
    ]);
    if (!activeRes.ok) throw new Error(`Server error ${activeRes.status}`);
    if (!archivedRes.ok) throw new Error(`Server error ${archivedRes.status}`);

    const allWithArchived = await archivedRes.json();
    activeHabits = (await activeRes.json());
    archivedHabits = allWithArchived.filter(h => h.is_archived);

    renderActiveList();
    renderArchivedList();
    renderStarterOrList();
  } catch (e) {
    showError('Unable to load habits: ' + e.message);
    if (list && typeof UIStates !== 'undefined') UIStates.setError(list, 'Something went wrong. Please try again.');
  }
}

// ── Render active list ────────────────────────────────────────────────────────

function renderStarterOrList() {
  const starterSection = document.getElementById('starter-section');
  const habitList = document.getElementById('habit-list');

  if (activeHabits.length === 0 && archivedHabits.length === 0) {
    starterSection.style.display = '';
    renderStarterGrid();
  } else {
    starterSection.style.display = 'none';
  }
}

function renderStarterGrid() {
  const grid = document.getElementById('starter-grid');
  grid.innerHTML = '';
  STARTER_HABITS.forEach(s => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'starter-btn';

    const iconEl = document.createElement('div');
    iconEl.className = 'starter-icon';
    iconEl.style.background = s.color;
    iconEl.textContent = iconLabel(s.icon).slice(0, 2).toUpperCase();

    const labelEl = document.createElement('span');
    labelEl.textContent = s.name;

    btn.appendChild(iconEl);
    btn.appendChild(labelEl);
    btn.addEventListener('click', () => createStarterHabit(s));
    grid.appendChild(btn);
  });
}

async function createStarterHabit(starter) {
  try {
    const res = await fetch('/api/habits', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(starter),
    });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    if (typeof UIStates !== 'undefined') UIStates.showToast('Habit added');
    await loadAndRender();
  } catch (e) {
    showError('Failed to add habit: ' + e.message);
  }
}

function renderActiveList() {
  const list = document.getElementById('habit-list');
  list.innerHTML = '';

  if (activeHabits.length === 0) return;

  activeHabits.forEach((habit, index) => {
    list.appendChild(buildHabitRow(habit, index, false));
  });
}

function buildHabitRow(habit, index, isArchived) {
  const li = document.createElement('li');
  li.className = 'habit-row';
  li.dataset.id = habit.id;
  li.dataset.index = index;

  // Drag handle (active only)
  if (!isArchived) {
    const handle = document.createElement('span');
    handle.className = 'drag-handle';
    handle.textContent = '⠿';
    handle.draggable = true;
    handle.setAttribute('aria-label', 'Drag to reorder');
    li.appendChild(handle);

    li.setAttribute('draggable', 'true');
    li.addEventListener('dragstart', onDragStart);
    li.addEventListener('dragover', onDragOver);
    li.addEventListener('dragleave', onDragLeave);
    li.addEventListener('drop', onDrop);
    li.addEventListener('dragend', onDragEnd);
  }

  // Icon
  li.appendChild(habitIconEl(habit.icon, habit.color));

  // Info block
  const info = document.createElement('div');
  info.className = 'habit-info';

  const nameEl = document.createElement('div');
  nameEl.className = 'habit-name';
  nameEl.textContent = habit.name;
  info.appendChild(nameEl);

  const meta = document.createElement('div');
  meta.className = 'habit-meta';

  const typeLabel = document.createElement('span');
  typeLabel.className = 'habit-tracking-type';
  typeLabel.textContent = TRACKING_TYPE_LABELS[habit.tracking_type] || habit.tracking_type;
  meta.appendChild(typeLabel);

  const goal = goalText(habit);
  if (goal) {
    const goalEl = document.createElement('span');
    goalEl.className = 'habit-goal';
    goalEl.textContent = goal;
    meta.appendChild(goalEl);
  }

  meta.appendChild(autofillPill(habit.auto_fill_source));
  info.appendChild(meta);
  li.appendChild(info);

  // Actions menu
  const actionsDiv = document.createElement('div');
  actionsDiv.className = 'habit-actions';

  const toggle = document.createElement('button');
  toggle.type = 'button';
  toggle.className = 'actions-toggle';
  toggle.textContent = '⋯';
  toggle.setAttribute('aria-label', 'Habit actions');
  toggle.addEventListener('click', e => {
    e.stopPropagation();
    closeAllMenus();
    menu.classList.toggle('open');
  });

  const menu = document.createElement('div');
  menu.className = 'actions-menu';

  if (!isArchived) {
    const editBtn = document.createElement('button');
    editBtn.type = 'button';
    editBtn.textContent = 'Edit';
    editBtn.addEventListener('click', () => { closeAllMenus(); openEditModal(habit); });
    menu.appendChild(editBtn);

    const archiveBtn = document.createElement('button');
    archiveBtn.type = 'button';
    archiveBtn.textContent = 'Archive';
    archiveBtn.addEventListener('click', () => { closeAllMenus(); archiveHabit(habit.id); });
    menu.appendChild(archiveBtn);
  } else {
    const unarchiveBtn = document.createElement('button');
    unarchiveBtn.type = 'button';
    unarchiveBtn.textContent = 'Unarchive';
    unarchiveBtn.addEventListener('click', () => { closeAllMenus(); unarchiveHabit(habit.id); });
    menu.appendChild(unarchiveBtn);
  }

  const deleteBtn = document.createElement('button');
  deleteBtn.type = 'button';
  deleteBtn.className = 'danger';
  deleteBtn.textContent = 'Delete';
  deleteBtn.addEventListener('click', () => {
    closeAllMenus();
    if (confirm(`Delete "${habit.name}"? This cannot be undone.`)) {
      deleteHabit(habit.id);
    }
  });
  menu.appendChild(deleteBtn);

  actionsDiv.appendChild(toggle);
  actionsDiv.appendChild(menu);
  li.appendChild(actionsDiv);

  return li;
}

function closeAllMenus() {
  document.querySelectorAll('.actions-menu.open').forEach(m => m.classList.remove('open'));
}

document.addEventListener('click', closeAllMenus);

// ── Render archived list ──────────────────────────────────────────────────────

function renderArchivedList() {
  const section = document.getElementById('archived-section');
  const list = document.getElementById('archived-list');
  const countEl = document.getElementById('archived-count');

  if (archivedHabits.length === 0) {
    section.style.display = 'none';
    return;
  }

  section.style.display = '';
  countEl.textContent = ` (${archivedHabits.length})`;
  list.innerHTML = '';
  archivedHabits.forEach((habit, index) => {
    list.appendChild(buildHabitRow(habit, index, true));
  });
}

// ── Archive / Unarchive / Delete ──────────────────────────────────────────────

async function archiveHabit(habitId) {
  try {
    const res = await fetch(`/api/habits/${encodeURIComponent(habitId)}`, { method: 'DELETE' });
    if (!res.ok && res.status !== 404) throw new Error(`Server error ${res.status}`);
    if (typeof UIStates !== 'undefined') UIStates.showToast('Habit archived');
    await loadAndRender();
  } catch (e) {
    showError('Failed to archive habit: ' + e.message);
  }
}

async function unarchiveHabit(habitId) {
  try {
    const res = await fetch(`/api/habits/${encodeURIComponent(habitId)}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ is_archived: false }),
    });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
    if (typeof UIStates !== 'undefined') UIStates.showToast('Habit restored');
    await loadAndRender();
  } catch (e) {
    showError('Failed to unarchive habit: ' + e.message);
  }
}

async function deleteHabit(habitId) {
  try {
    const res = await fetch(`/api/habits/${encodeURIComponent(habitId)}?hard=true`, { method: 'DELETE' });
    if (!res.ok && res.status !== 404) throw new Error(`Server error ${res.status}`);
    if (typeof UIStates !== 'undefined') UIStates.showToast('Habit deleted');
    await loadAndRender();
  } catch (e) {
    showError('Failed to delete habit: ' + e.message);
  }
}

// ── Drag & drop reorder ───────────────────────────────────────────────────────

function onDragStart(e) {
  dragSrcIndex = parseInt(this.dataset.index, 10);
  this.classList.add('dragging');
  e.dataTransfer.effectAllowed = 'move';
}

function onDragOver(e) {
  e.preventDefault();
  e.dataTransfer.dropEffect = 'move';
  this.classList.add('drag-over');
}

function onDragLeave() {
  this.classList.remove('drag-over');
}

async function onDrop(e) {
  e.preventDefault();
  this.classList.remove('drag-over');
  const destIndex = parseInt(this.dataset.index, 10);
  if (dragSrcIndex === null || dragSrcIndex === destIndex) return;

  const reordered = [...activeHabits];
  const [moved] = reordered.splice(dragSrcIndex, 1);
  reordered.splice(destIndex, 0, moved);

  activeHabits = reordered;
  renderActiveList();

  // Persist new sort_order for the moved habit
  try {
    const res = await fetch(`/api/habits/${encodeURIComponent(moved.id)}/reorder`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sort_order: destIndex }),
    });
    if (!res.ok) throw new Error(`Server error ${res.status}`);
  } catch (e) {
    showError('Failed to save order: ' + e.message);
    await loadAndRender();
  }
}

function onDragEnd() {
  document.querySelectorAll('.habit-row').forEach(r => {
    r.classList.remove('dragging', 'drag-over');
  });
  dragSrcIndex = null;
}

// ── Modal ─────────────────────────────────────────────────────────────────────

function buildIconPicker() {
  const container = document.getElementById('icon-picker');
  container.innerHTML = '';
  ICONS.forEach(icon => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'icon-option' + (icon === selectedIcon ? ' selected' : '');
    btn.textContent = iconLabel(icon).slice(0, 2).toUpperCase();
    btn.title = icon;
    btn.dataset.icon = icon;
    btn.addEventListener('click', () => {
      selectedIcon = icon;
      container.querySelectorAll('.icon-option').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
    });
    container.appendChild(btn);
  });
}

function buildColorPicker() {
  const container = document.getElementById('color-picker');
  container.innerHTML = '';
  COLORS.forEach(color => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'color-swatch' + (color === selectedColor ? ' selected' : '');
    btn.style.background = color;
    btn.title = color;
    btn.dataset.color = color;
    btn.addEventListener('click', () => {
      selectedColor = color;
      container.querySelectorAll('.color-swatch').forEach(b => b.classList.remove('selected'));
      btn.classList.add('selected');
    });
    container.appendChild(btn);
  });
}

function openNewModal() {
  editingHabitId = null;
  selectedIcon = ICONS[0];
  selectedColor = COLORS[0];

  document.getElementById('modal-title').textContent = 'New habit';
  document.getElementById('modal-submit').textContent = 'Add habit';
  document.getElementById('modal-name').value = '';
  document.getElementById('modal-description').value = '';
  document.getElementById('modal-tracking-type').value = 'daily_checkmark';
  document.getElementById('modal-weekly-target').value = '';
  document.getElementById('modal-unit').value = '';
  document.getElementById('modal-auto-fill').value = '';
  document.getElementById('modal-error').textContent = '';

  buildIconPicker();
  buildColorPicker();

  document.getElementById('habit-modal').classList.add('open');
  document.getElementById('modal-name').focus();
}

function openEditModal(habit) {
  editingHabitId = habit.id;
  selectedIcon = habit.icon || ICONS[0];
  selectedColor = habit.color || COLORS[0];

  document.getElementById('modal-title').textContent = 'Edit habit';
  document.getElementById('modal-submit').textContent = 'Save changes';
  document.getElementById('modal-name').value = habit.name || '';
  document.getElementById('modal-description').value = habit.description || '';
  document.getElementById('modal-tracking-type').value = habit.tracking_type || 'daily_checkmark';
  document.getElementById('modal-weekly-target').value = habit.weekly_target != null ? habit.weekly_target : '';
  document.getElementById('modal-unit').value = habit.unit || '';
  document.getElementById('modal-auto-fill').value = habit.auto_fill_source || '';
  document.getElementById('modal-error').textContent = '';

  buildIconPicker();
  buildColorPicker();

  document.getElementById('habit-modal').classList.add('open');
  document.getElementById('modal-name').focus();
}

function closeModal() {
  document.getElementById('habit-modal').classList.remove('open');
  editingHabitId = null;
}

// ── Form submit ───────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  document.getElementById('add-habit-btn').addEventListener('click', openNewModal);
  document.getElementById('modal-cancel').addEventListener('click', closeModal);

  document.getElementById('habit-modal').addEventListener('click', e => {
    if (e.target === document.getElementById('habit-modal')) closeModal();
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeModal();
  });

  document.getElementById('archived-toggle').addEventListener('click', () => {
    const toggle = document.getElementById('archived-toggle');
    const list = document.getElementById('archived-list');
    const isOpen = toggle.classList.contains('open');
    toggle.classList.toggle('open', !isOpen);
    list.style.display = isOpen ? 'none' : '';
  });

  document.getElementById('modal-form').addEventListener('submit', async e => {
    e.preventDefault();
    const errorEl = document.getElementById('modal-error');
    errorEl.textContent = '';

    const name = document.getElementById('modal-name').value.trim();
    if (!name) {
      errorEl.textContent = 'Name is required.';
      document.getElementById('modal-name').focus();
      return;
    }

    const payload = {
      name,
      description: document.getElementById('modal-description').value.trim() || null,
      tracking_type: document.getElementById('modal-tracking-type').value,
      weekly_target: document.getElementById('modal-weekly-target').value
        ? parseFloat(document.getElementById('modal-weekly-target').value)
        : null,
      unit: document.getElementById('modal-unit').value.trim() || null,
      auto_fill_source: document.getElementById('modal-auto-fill').value || null,
      icon: selectedIcon || null,
      color: selectedColor || null,
    };

    try {
      let res;
      if (editingHabitId) {
        res = await fetch(`/api/habits/${encodeURIComponent(editingHabitId)}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        res = await fetch('/api/habits', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        errorEl.textContent = body.detail || `Server error ${res.status}`;
        return;
      }
      closeModal();
      if (typeof UIStates !== 'undefined') UIStates.showToast(editingHabitId ? 'Habit updated' : 'Habit added');
      await loadAndRender();
    } catch (err) {
      errorEl.textContent = 'Failed to save: ' + err.message;
    }
  });
});

// ── Boot ──────────────────────────────────────────────────────────────────────

window.addEventListener('userReady', e => {
  currentUserId = e.detail.userId;
  loadAndRender();
});

window.addEventListener('userChanged', e => {
  currentUserId = e.detail.userId;
  loadAndRender();
});
