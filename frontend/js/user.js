(function () {
  // CSRF fetch patching lives in nav.js (loaded before this script on every page).

  var _currentUser = null;

  function getCurrentUserId() {
    return _currentUser ? _currentUser.id : null;
  }

  var authReady = window.ensureCsrfReady
    ? window.ensureCsrfReady()
    : Promise.resolve();

  authReady
    .then(function () {
      return fetch("/api/auth/me");
    })
    .then(function (res) {
      if (res.status === 401 || res.status === 403) {
        window.location.href = "/login";
        return null;
      }
      if (!res.ok) throw new Error("auth/me error " + res.status);
      return res.json();
    })
    .then(function (user) {
      if (!user) return;
      _currentUser = user;
      window.dispatchEvent(
        new CustomEvent("userReady", {
          detail: { userId: user.id, userName: user.name },
        }),
      );
    })
    .catch(function () {
      window.location.href = "/login";
    });

  window.getCurrentUserId = getCurrentUserId;
})();
