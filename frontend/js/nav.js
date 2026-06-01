/*
 * nav.js — global top navigation bar.
 *
 * Single source of truth for the app's primary nav. Each page just loads this
 * script; it injects its own scoped styles, the Tabler icon font (if missing),
 * and the nav markup, then highlights the active page from the URL.
 *
 * Do NOT hand-write <nav> markup in pages — add or change links here only.
 */
(function () {
  'use strict';

  // Every primary destination, shown inline in the bar (left → right).
  var LINKS = [
    { href: '/home.html',     label: 'Home',         icon: 'ti-home',         match: ['/', '/home.html', '/index.html'] },
    { href: '/log',           label: 'Training Log', icon: 'ti-list-details', match: ['/log', '/log.html', '/training', '/training.html'] },
    { href: '/trends',        label: 'Trends',       icon: 'ti-chart-line',   match: ['/trends', '/trends.html'] },
    { href: '/calendar.html', label: 'Calendar',     icon: 'ti-calendar',     match: ['/calendar.html'] },
    { href: '/weight.html',   label: 'Weight',       icon: 'ti-scale',        match: ['/weight.html'] },
    { href: '/habits.html',   label: 'Habits',       icon: 'ti-checklist',    match: ['/habits.html'] },
    { href: '/users.html',    label: 'Users',        icon: 'ti-users',        match: ['/users.html'] }
  ];

  // Scoped under .global-nav so it cannot leak into page styles. Colours are the
  // literal values from the original home.html topnav (no CSS-var dependency).
  var CSS = [
    '.global-nav{background:linear-gradient(180deg,#eaf0fb 0%,#d8e3f5 100%);',
      'border-bottom:1px solid rgba(13,30,67,0.06);padding:0 24px;height:60px;',
      'display:flex;align-items:center;gap:20px;position:sticky;top:0;z-index:100;',
      "font-family:'Inter Tight',-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;}",
    '.global-nav .gn-brand{display:flex;align-items:center;gap:10px;font-weight:700;',
      'font-size:16px;letter-spacing:-0.02em;color:#0b1530;text-decoration:none;flex-shrink:0;}',
    '.global-nav .gn-mark{width:30px;height:30px;border-radius:9px;',
      'background:linear-gradient(135deg,#6e90f0,#2b4ca8);color:#fff;display:flex;',
      'align-items:center;justify-content:center;font-size:16px;flex-shrink:0;}',
    '.global-nav .gn-links{display:flex;gap:4px;flex:1;overflow-x:auto;scrollbar-width:none;}',
    '.global-nav .gn-links::-webkit-scrollbar{display:none;}',
    '.global-nav .gn-link{padding:8px 14px;border-radius:999px;font-size:13.5px;font-weight:500;',
      'color:#5c6886;text-decoration:none;display:inline-flex;align-items:center;gap:7px;white-space:nowrap;}',
    '.global-nav .gn-link i{font-size:15px;}',
    '.global-nav .gn-link:hover{background:rgba(13,30,67,0.05);color:#0b1530;}',
    '.global-nav .gn-link.active{background:#0b1530;color:#fff;}',
    '.global-nav .gn-right{display:flex;align-items:center;gap:10px;flex-shrink:0;}',
    '.global-nav .gn-avatar{width:34px;height:34px;border-radius:50%;',
      'background:linear-gradient(135deg,#ffb88a,#d97a3a);color:#fff;display:flex;',
      'align-items:center;justify-content:center;font-weight:600;font-size:13px;flex-shrink:0;}',
    '@media (max-width:880px){.global-nav{padding:0 14px;height:56px;gap:12px;}',
      '.global-nav .gn-brand-text{display:none;}}'
  ].join('');

  function ensureIconFont() {
    if (document.querySelector('link[href*="tabler-icons"]')) return;
    var link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = 'https://cdn.jsdelivr.net/npm/@tabler/icons-webfont@3/tabler-icons.min.css';
    document.head.appendChild(link);
  }

  function injectStyles() {
    if (document.getElementById('global-nav-styles')) return;
    var style = document.createElement('style');
    style.id = 'global-nav-styles';
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  function escAttr(s) {
    return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');
  }

  function buildNav() {
    if (document.querySelector('.global-nav')) return;
    var path = window.location.pathname;

    var linksHtml = LINKS.map(function (l) {
      var active = l.match.indexOf(path) !== -1;
      return '<a class="gn-link' + (active ? ' active' : '') + '" href="' + escAttr(l.href) + '"' +
             (active ? ' aria-current="page"' : '') + '>' +
             '<i class="ti ' + l.icon + '" aria-hidden="true"></i>' +
             '<span>' + l.label + '</span></a>';
    }).join('');

    var nav = document.createElement('nav');
    nav.className = 'global-nav';
    nav.setAttribute('aria-label', 'Primary navigation');
    nav.innerHTML =
      '<a class="gn-brand" href="/home.html">' +
        '<span class="gn-mark"><i class="ti ti-activity-heartbeat" aria-hidden="true"></i></span>' +
        '<span class="gn-brand-text">perf-coach</span>' +
      '</a>' +
      '<div class="gn-links">' + linksHtml + '</div>' +
      '<div class="gn-right">' +
        '<div class="gn-avatar" id="nav-avatar" aria-label="User avatar">U</div>' +
      '</div>';

    document.body.insertBefore(nav, document.body.firstChild);
  }

  // Mirror the selected user's initial into the avatar. Works with user.js's
  // selector + userReady/userChanged events; no-ops on pages without it.
  function updateAvatar() {
    var el = document.getElementById('nav-avatar');
    if (!el) return;
    var sel = document.getElementById('user-selector-select');
    if (!sel || sel.selectedIndex < 0) return;
    var opt = sel.options[sel.selectedIndex];
    if (!opt || opt.value === '__add__') return;
    el.textContent = (opt.textContent.trim().charAt(0) || 'U').toUpperCase();
  }

  function init() {
    ensureIconFont();
    injectStyles();
    buildNav();
    updateAvatar();
    window.addEventListener('userReady', updateAvatar);
    // user.js repopulates its <select> after a change; defer a tick to read it.
    window.addEventListener('userChanged', function () { setTimeout(updateAvatar, 0); });
  }

  if (document.body) init();
  else document.addEventListener('DOMContentLoaded', init);
}());
