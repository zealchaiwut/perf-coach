const STORAGE_KEY = 'perf-coach.habits';

function load() {
  try {
    return JSON.parse(localStorage.getItem(STORAGE_KEY)) || [];
  } catch {
    return [];
  }
}

function save(habits) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(habits));
}

function uid() {
  return Date.now().toString(36) + Math.random().toString(36).slice(2);
}

let habits = load();

function render() {
  const list = document.getElementById('habit-list');
  list.innerHTML = '';

  if (habits.length === 0) {
    const empty = document.createElement('li');
    empty.className = 'habit-empty';
    empty.textContent = 'No habits yet. Add one above.';
    list.appendChild(empty);
    return;
  }

  habits.forEach(habit => {
    const li = document.createElement('li');
    li.className = 'habit-row' + (habit.done ? ' habit-done' : '');

    const checkbox = document.createElement('input');
    checkbox.type = 'checkbox';
    checkbox.checked = habit.done;
    checkbox.setAttribute('aria-label', 'Mark ' + habit.name + ' as done');
    checkbox.addEventListener('change', () => toggle(habit.id));

    const name = document.createElement('span');
    name.className = 'habit-name';
    name.textContent = habit.name;

    const del = document.createElement('button');
    del.className = 'habit-delete';
    del.textContent = 'Delete';
    del.setAttribute('aria-label', 'Delete ' + habit.name);
    del.addEventListener('click', () => remove(habit.id));

    li.appendChild(checkbox);
    li.appendChild(name);
    li.appendChild(del);
    list.appendChild(li);
  });
}

function toggle(id) {
  habits = habits.map(h => h.id === id ? { ...h, done: !h.done } : h);
  save(habits);
  render();
}

function remove(id) {
  habits = habits.filter(h => h.id !== id);
  save(habits);
  render();
}

document.getElementById('habit-form').addEventListener('submit', e => {
  e.preventDefault();
  const input = document.getElementById('habit-input');
  const error = document.getElementById('habit-error');
  const name = input.value.trim();

  if (!name) {
    error.textContent = 'Habit name cannot be empty.';
    input.focus();
    return;
  }

  error.textContent = '';
  habits.push({ id: uid(), name, done: false });
  save(habits);
  input.value = '';
  render();
});

render();
