// CSRF-aware fetch + shared /api/auth/me (v2 pages; subset of nav.js).
(function () {
  "use strict";
  if (window._csrfFetchPatched) return;
  window._csrfFetchPatched = true;
  var _origFetch = window.fetch.bind(window);
  var _csrfBootstrap = null;

  function _readCsrfCookie() {
    var match = document.cookie.match(/(?:^|;\s*)csrf-token=([^;]*)/);
    return match ? decodeURIComponent(match[1]) : null;
  }

  function _writeCsrfCookie(token) {
    if (!token) return;
    var secure = window.location.protocol === "https:" ? "; Secure" : "";
    document.cookie =
      "csrf-token=" + encodeURIComponent(token) + "; Path=/; SameSite=Lax" + secure;
  }

  function _fetchCsrfToken() {
    return _origFetch("/api/csrf-token", { credentials: "same-origin" })
      .then(function (res) {
        if (!res.ok) return _readCsrfCookie();
        return res.json().then(function (body) {
          var token = (body && body.csrf_token) || _readCsrfCookie();
          if (token) _writeCsrfCookie(token);
          return _readCsrfCookie();
        });
      })
      .catch(function () {
        return _readCsrfCookie();
      });
  }

  function ensureCsrfReady() {
    var cookie = _readCsrfCookie();
    if (cookie) return Promise.resolve(cookie);
    if (!_csrfBootstrap) {
      _csrfBootstrap = _fetchCsrfToken().finally(function () {
        _csrfBootstrap = null;
      });
    }
    return _csrfBootstrap.then(function (token) {
      return token || _readCsrfCookie();
    });
  }

  function _attachCsrfHeader(opts, token) {
    if (!token) return opts;
    var headers = opts.headers || {};
    if (headers instanceof Headers) {
      headers = new Headers(headers);
      headers.set("X-CSRF-Token", token);
    } else {
      headers = Object.assign({}, headers, { "X-CSRF-Token": token });
    }
    return Object.assign({}, opts, { headers: headers, credentials: "same-origin" });
  }

  window.fetch = function (url, opts) {
    opts = opts || {};
    var method = (opts.method || "GET").toUpperCase();
    if (method === "POST" || method === "PATCH" || method === "DELETE" || method === "PUT") {
      return ensureCsrfReady().then(function (token) {
        return _origFetch(url, _attachCsrfHeader(opts, token || _readCsrfCookie()));
      });
    }
    return _origFetch(url, opts);
  };

  window.ensureCsrfReady = ensureCsrfReady;
  ensureCsrfReady().catch(function () {});

  var _currentUserPromise = null;
  window.fetchCurrentUser = function () {
    if (_currentUserPromise) return _currentUserPromise;
    _currentUserPromise = ensureCsrfReady()
      .then(function () {
        return fetch("/api/auth/me", { credentials: "same-origin" });
      })
      .then(function (res) {
        if (res.status === 401 || res.status === 403) return null;
        if (!res.ok) throw new Error("auth/me error " + res.status);
        return res.json();
      });
    return _currentUserPromise;
  };
})();