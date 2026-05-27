(function () {
  var pendingDeleteId = null;
  var usersCache = [];

  function fmtDate(iso) {
    return iso ? iso.slice(0, 10) : '—';
  }

  function esc(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  function showPageError(msg) {
    document.getElementById('page-error').textContent = msg;
  }

  function clearPageError() {
    document.getElementById('page-error').textContent = '';
  }

  async function loadUsers() {
    try {
      var res = await fetch('/api/users');
      if (!res.ok) throw new Error('Server error ' + res.status);
      usersCache = await res.json();
      renderTable();
    } catch (e) {
      showPageError('Failed to load users: ' + e.message);
    }
  }

  function rowHtml(u) {
    return '<td class="user-name-cell">' + esc(u.name) + '</td>' +
      '<td>' + fmtDate(u.created_at) + '</td>' +
      '<td>' + u.weight_count + '</td>' +
      '<td>' + u.habits_count + '</td>' +
      '<td class="actions-cell">' +
        '<button type="button" class="btn-sm btn-rename" data-id="' + esc(u.id) + '">Rename</button>' +
        '<button type="button" class="btn-sm btn-delete" data-id="' + esc(u.id) + '">Delete</button>' +
      '</td>';
  }

  function renderTable() {
    var tbody = document.getElementById('users-tbody');
    tbody.innerHTML = '';
    usersCache.forEach(function (u) {
      var tr = document.createElement('tr');
      tr.dataset.id = u.id;
      tr.innerHTML = rowHtml(u);
      tbody.appendChild(tr);
    });
    rebindActions();
  }

  function rebindActions() {
    document.querySelectorAll('#users-tbody .btn-rename').forEach(function (btn) {
      btn.addEventListener('click', function () { startRename(btn.dataset.id); });
    });
    document.querySelectorAll('#users-tbody .btn-delete').forEach(function (btn) {
      btn.addEventListener('click', function () { startDelete(btn.dataset.id); });
    });
  }

  // ── Add user ──────────────────────────────────────────────────────────────

  function openAddForm() {
    clearPageError();
    document.getElementById('add-form-bar').hidden = true;
    document.getElementById('add-form-inline').hidden = false;
    var inp = document.getElementById('add-name-input');
    inp.value = '';
    document.getElementById('add-name-error').textContent = '';
    inp.focus();
  }

  function closeAddForm() {
    document.getElementById('add-form-inline').hidden = true;
    document.getElementById('add-form-bar').hidden = false;
  }

  async function submitAddUser() {
    var name = document.getElementById('add-name-input').value.trim();
    var errEl = document.getElementById('add-name-error');
    errEl.textContent = '';

    if (!name) { errEl.textContent = 'Name cannot be empty.'; return; }
    if (name.length > 100) { errEl.textContent = 'Name must be 100 characters or fewer.'; return; }
    if (usersCache.some(function (u) { return u.name.toLowerCase() === name.toLowerCase(); })) {
      errEl.textContent = 'Name already exists.';
      return;
    }

    try {
      var res = await fetch('/api/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name }),
      });
      if (res.status === 409) { errEl.textContent = 'Name already exists.'; return; }
      if (!res.ok) throw new Error('Server error ' + res.status);
      closeAddForm();
      await loadUsers();
    } catch (e) {
      errEl.textContent = 'Save failed: ' + e.message;
    }
  }

  // ── Rename ────────────────────────────────────────────────────────────────

  function startRename(userId) {
    var user = usersCache.find(function (u) { return u.id === userId; });
    if (!user) return;
    var tr = document.querySelector('#users-tbody tr[data-id="' + userId + '"]');
    if (!tr) return;

    tr.querySelector('.user-name-cell').innerHTML =
      '<input type="text" class="rename-input" value="' + esc(user.name) + '" maxlength="100" autocomplete="off"' +
      ' style="padding:0.35rem 0.6rem;border:1px solid #ccc;border-radius:4px;font-size:0.9375rem">' +
      '<span class="field-error rename-error" role="alert" style="margin-left:0.5rem"></span>';

    tr.querySelector('.actions-cell').innerHTML =
      '<button type="button" class="btn-sm btn-rename-save" data-id="' + esc(userId) + '">Save</button>' +
      '<button type="button" class="btn-sm btn-rename-cancel" data-id="' + esc(userId) + '">Cancel</button>';

    var inp = tr.querySelector('.rename-input');
    inp.focus();
    inp.select();

    inp.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') saveRename(userId);
      if (e.key === 'Escape') cancelRename(userId);
    });
    tr.querySelector('.btn-rename-save').addEventListener('click', function () { saveRename(userId); });
    tr.querySelector('.btn-rename-cancel').addEventListener('click', function () { cancelRename(userId); });
  }

  function cancelRename(userId) {
    var user = usersCache.find(function (u) { return u.id === userId; });
    if (!user) return;
    var tr = document.querySelector('#users-tbody tr[data-id="' + userId + '"]');
    if (!tr) return;
    tr.innerHTML = rowHtml(user);
    rebindActions();
  }

  async function saveRename(userId) {
    var tr = document.querySelector('#users-tbody tr[data-id="' + userId + '"]');
    if (!tr) return;
    var inp = tr.querySelector('.rename-input');
    var errEl = tr.querySelector('.rename-error');
    var name = inp.value.trim();

    if (!name) { errEl.textContent = 'Name cannot be empty.'; return; }
    if (name.length > 100) { errEl.textContent = 'Name must be 100 characters or fewer.'; return; }
    if (usersCache.some(function (u) { return u.id !== userId && u.name.toLowerCase() === name.toLowerCase(); })) {
      errEl.textContent = 'Name already exists.';
      return;
    }

    try {
      var res = await fetch('/api/users/' + userId, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name: name }),
      });
      if (res.status === 409) { errEl.textContent = 'Name already exists.'; return; }
      if (!res.ok) throw new Error('Server error ' + res.status);
      await loadUsers();
    } catch (e) {
      var errEl2 = tr.querySelector('.rename-error');
      if (errEl2) errEl2.textContent = 'Save failed: ' + e.message;
    }
  }

  // ── Delete ────────────────────────────────────────────────────────────────

  function startDelete(userId) {
    var user = usersCache.find(function (u) { return u.id === userId; });
    if (!user) return;
    clearPageError();

    var currentId = typeof window.getCurrentUserId === 'function'
      ? window.getCurrentUserId()
      : localStorage.getItem('perf-coach.current-user-id');

    if (userId === currentId) {
      showPageError('Switch to another user first');
      return;
    }

    pendingDeleteId = userId;
    document.getElementById('delete-modal-text').textContent =
      'Delete ' + user.name + '? This will permanently delete all their weight entries and habit logs.';
    document.getElementById('delete-modal').classList.add('is-open');
  }

  async function confirmDelete() {
    if (!pendingDeleteId) return;
    var userId = pendingDeleteId;
    pendingDeleteId = null;
    document.getElementById('delete-modal').classList.remove('is-open');

    try {
      var res = await fetch('/api/users/' + userId, { method: 'DELETE' });
      if (res.status === 409) {
        var body = await res.json();
        showPageError(body.error || 'Cannot delete user');
        return;
      }
      if (res.status !== 204) throw new Error('Server error ' + res.status);
      await loadUsers();
    } catch (e) {
      showPageError('Delete failed: ' + e.message);
    }
  }

  // ── Init ──────────────────────────────────────────────────────────────────

  document.addEventListener('DOMContentLoaded', function () {
    document.getElementById('add-user-btn').addEventListener('click', openAddForm);
    document.getElementById('add-cancel-btn').addEventListener('click', closeAddForm);
    document.getElementById('add-save-btn').addEventListener('click', submitAddUser);
    document.getElementById('add-name-input').addEventListener('keydown', function (e) {
      if (e.key === 'Enter') submitAddUser();
      if (e.key === 'Escape') closeAddForm();
    });
    document.getElementById('delete-confirm-btn').addEventListener('click', confirmDelete);
    document.getElementById('delete-cancel-btn').addEventListener('click', function () {
      pendingDeleteId = null;
      document.getElementById('delete-modal').classList.remove('is-open');
    });

    loadUsers();
  });
}());
