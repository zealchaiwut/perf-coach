(function () {
  // CSRF fetch patching + the shared /api/auth/me fetch both live in nav.js
  // (loaded before this script on every page).

  var _currentUser = null;

  function getCurrentUserId() {
    return _currentUser ? _currentUser.id : null;
  }

  window
    .fetchCurrentUser()
    .then(function (user) {
      if (!user) {
        window.location.href = "/login";
        return;
      }
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
