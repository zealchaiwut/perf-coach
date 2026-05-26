(function () {
  var STORAGE_KEY = 'perf-coach.current-user-id';

  function getCurrentUserId() {
    return localStorage.getItem(STORAGE_KEY) || null;
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
    select.id = 'user-select';

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

    select.addEventListener('change', function () {
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
}());
