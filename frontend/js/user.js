(function () {
  // CSRF fetch patching + the shared /api/auth/me fetch both live in nav.js
  // (loaded before this script on every page).

  var _currentUser = null;

  function getCurrentUserId() {
    return _currentUser ? _currentUser.id : null;
  }

  // perf/hot-paths Task 7 fix: the shared fetchCurrentUser() promise now
  // starts resolving earlier (nav.js kicks it off before this script even
  // runs), which can race ahead of a still-loading blocking <script src>
  // further down the page (e.g. the Chart.js CDN tag on /trends) — the
  // fetch can resolve, and this dispatch fire, before trends.js/calendar.js/
  // habits.js/training*.js have executed and registered their 'userReady'
  // listener. document.readyState !== "loading" is only true once the
  // parser has finished running every synchronous script in the document,
  // so gating the dispatch on DOMContentLoaded when parsing isn't done yet
  // guarantees every same-document listener is registered first — no
  // arbitrary delay, a spec-guaranteed ordering.
  function _dispatchUserReady(detail) {
    var fire = function () {
      window.dispatchEvent(new CustomEvent("userReady", { detail: detail }));
    };
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", fire, { once: true });
    } else {
      fire();
    }
  }

  window
    .fetchCurrentUser()
    .then(function (user) {
      if (!user) {
        window.location.href = "/login";
        return;
      }
      _currentUser = user;
      _dispatchUserReady({ userId: user.id, userName: user.name });
    })
    .catch(function () {
      window.location.href = "/login";
    });

  window.getCurrentUserId = getCurrentUserId;
})();
