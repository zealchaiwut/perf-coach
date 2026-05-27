(function () {
  var STORAGE_KEY = 'perf-coach.current-user-id';

  function getCurrentUserId() {
    return localStorage.getItem(STORAGE_KEY) || null;
  }

  function buildAddUserModal(onSuccess) {
    var overlay = document.createElement('div');
    overlay.className = 'modal-overlay';
    overlay.innerHTML =
      '<div class="modal-box">' +
        '<p style="margin:0 0 0.75rem;font-weight:600">Add user</p>' +
        '<input type="text" id="_modal-name-input" maxlength="100" autocomplete="off" placeholder="Name"' +
          ' style="width:100%;padding:0.45rem 0.75rem;border:1px solid #ccc;border-radius:4px;font-size:1rem;box-sizing:border-box">' +
        '<p id="_modal-name-error" style="color:#c0392b;font-size:0.8125rem;min-height:1.2em;margin:0.4rem 0 0.75rem"></p>' +
        '<div class="modal-actions">' +
          '<button id="_modal-save" type="button" class="btn-primary">Save</button>' +
          '<button id="_modal-cancel" type="button" class="btn-secondary" style="margin-left:0.5rem">Cancel</button>' +
        '</div>' +
      '</div>';

    overlay.classList.add('is-open');
    document.body.appendChild(overlay);

    var inp = overlay.querySelector('#_modal-name-input');
    var errEl = overlay.querySelector('#_modal-name-error');
    inp.focus();

    function close() { document.body.removeChild(overlay); }

    overlay.querySelector('#_modal-cancel').addEventListener('click', close);

    async function attemptSave() {
      var name = inp.value.trim();
      errEl.textContent = '';
      if (!name) { errEl.textContent = 'Name cannot be empty.'; return; }
      if (name.length > 100) { errEl.textContent = 'Name must be 100 characters or fewer.'; return; }
      try {
        var res = await fetch('/api/users', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: name }),
        });
        if (res.status === 409) { errEl.textContent = 'Name already exists.'; return; }
        if (!res.ok) throw new Error('Server error ' + res.status);
        var newUser = await res.json();
        close();
        onSuccess(newUser);
      } catch (e) {
        errEl.textContent = 'Save failed: ' + e.message;
      }
    }

    overlay.querySelector('#_modal-save').addEventListener('click', attemptSave);
    inp.addEventListener('keydown', function (e) {
      if (e.key === 'Enter') attemptSave();
      if (e.key === 'Escape') close();
    });
  }

  function renderSelector(users) {
    var header = document.querySelector('header');
    if (!header || !users.length) return;

    var wrapper = document.createElement('div');
    wrapper.className = 'user-selector';

    var label = document.createElement('span');
    label.className = 'user-selector-label';
    label.textContent = 'Logged in as:';

    var select = document.createElement('select');
    select.id = 'user-selector-select';

    var saved = localStorage.getItem(STORAGE_KEY);
    var validSaved = users.some(function (u) { return u.id === saved; });
    var current = validSaved ? saved : users[0].id;

    if (!validSaved) {
      localStorage.setItem(STORAGE_KEY, current);
    }

    users.forEach(function (u) {
      var opt = document.createElement('option');
      opt.value = u.id;
      opt.textContent = u.name;
      if (u.id === current) opt.selected = true;
      select.appendChild(opt);
    });

    var addOpt = document.createElement('option');
    addOpt.value = '__add__';
    addOpt.textContent = '+ Add user...';
    select.appendChild(addOpt);

    var prevValue = current;

    select.addEventListener('change', function () {
      if (select.value === '__add__') {
        select.value = prevValue;
        buildAddUserModal(function (newUser) {
          localStorage.setItem(STORAGE_KEY, newUser.id);
          window.dispatchEvent(new CustomEvent('userChanged', { detail: { userId: newUser.id } }));
          fetch('/api/users')
            .then(function (r) { return r.json(); })
            .then(function (freshUsers) {
              while (select.options.length > 0) select.remove(0);
              freshUsers.forEach(function (u) {
                var opt = document.createElement('option');
                opt.value = u.id;
                opt.textContent = u.name;
                if (u.id === newUser.id) opt.selected = true;
                select.appendChild(opt);
              });
              var ao = document.createElement('option');
              ao.value = '__add__';
              ao.textContent = '+ Add user...';
              select.appendChild(ao);
              prevValue = newUser.id;
            })
            .catch(function () {});
        });
        return;
      }
      prevValue = select.value;
      localStorage.setItem(STORAGE_KEY, select.value);
      window.dispatchEvent(new CustomEvent('userChanged', { detail: { userId: select.value } }));
    });

    wrapper.appendChild(label);
    wrapper.appendChild(select);

    var envLabel = header.querySelector('#env-label');
    if (envLabel) {
      header.insertBefore(wrapper, envLabel);
    } else {
      header.appendChild(wrapper);
    }

    window.dispatchEvent(new CustomEvent('userReady', { detail: { userId: current } }));
  }

  fetch('/api/users')
    .then(function (res) { return res.json(); })
    .then(function (users) { renderSelector(users); })
    .catch(function () {});

  window.getCurrentUserId = getCurrentUserId;
  window.buildAddUserModal = buildAddUserModal;
}());
