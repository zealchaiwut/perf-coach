(function () {
  // Patch window.fetch once to auto-attach X-CSRF-Token on mutating requests.
  if (!window._csrfFetchPatched) {
    window._csrfFetchPatched = true;
    var _origFetch = window.fetch.bind(window);
    window.fetch = function (url, opts) {
      opts = opts || {};
      var method = (opts.method || 'GET').toUpperCase();
      if (method === 'POST' || method === 'PATCH' || method === 'DELETE' || method === 'PUT') {
        var match = document.cookie.match(/(?:^|;\s*)csrf-token=([^;]*)/);
        if (match) {
          var headers = opts.headers || {};
          if (headers instanceof Headers) {
            headers = new Headers(headers);
            headers.set('X-CSRF-Token', decodeURIComponent(match[1]));
          } else {
            headers = Object.assign({}, headers, { 'X-CSRF-Token': decodeURIComponent(match[1]) });
          }
          opts = Object.assign({}, opts, { headers: headers });
        }
      }
      return _origFetch(url, opts);
    };
  }

  var _currentUser = null;

  function getCurrentUserId() {
    return _currentUser ? _currentUser.id : null;
  }

  fetch('/api/auth/me')
    .then(function (res) {
      if (res.status === 401 || res.status === 403) {
        window.location.href = '/login';
        return null;
      }
      if (!res.ok) throw new Error('auth/me error ' + res.status);
      return res.json();
    })
    .then(function (user) {
      if (!user) return;
      _currentUser = user;
      window.dispatchEvent(new CustomEvent('userReady', {
        detail: { userId: user.id, userName: user.name }
      }));
    })
    .catch(function () {
      window.location.href = '/login';
    });

  window.getCurrentUserId = getCurrentUserId;
}());
