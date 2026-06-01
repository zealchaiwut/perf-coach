(function () {
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
