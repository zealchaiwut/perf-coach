/*
 * admin-gate.js — interim client-side guard for admin-only pages.
 *
 * Hides the page until it confirms the *currently selected* user has is_admin,
 * otherwise redirects to /home. This is NOT real security — anyone can bypass
 * client-side checks. It just keeps the Users page out of normal view until
 * real authentication/credentials are added.
 *
 * Requires a `<style id="admin-gate-hide">body{visibility:hidden}</style>` in
 * the page <head> so protected content never flashes before the check.
 */
(function () {
  'use strict';

  var STORAGE_KEY = 'perf-coach.current-user-id'; // same key user.js uses
  var HIDE_ID = 'admin-gate-hide';

  function reveal() {
    var s = document.getElementById(HIDE_ID);
    if (s && s.parentNode) s.parentNode.removeChild(s);
  }

  function deny() {
    window.location.replace('/home');
  }

  fetch('/api/users')
    .then(function (r) { return r.ok ? r.json() : []; })
    .then(function (users) {
      if (!users || !users.length) { deny(); return; }
      var cid = localStorage.getItem(STORAGE_KEY);
      var current = null;
      for (var i = 0; i < users.length; i++) {
        if (users[i].id === cid) { current = users[i]; break; }
      }
      if (!current) current = users[0]; // mirror user.js default-to-first
      if (current && current.is_admin) reveal();
      else deny();
    })
    .catch(deny); // fail closed
}());
