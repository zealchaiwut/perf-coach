(function () {
  "use strict";

  var lastFocus = null;

  function openDrawer(trigger) {
    var backdrop = document.getElementById("rv-drawer-backdrop");
    var drawer = document.getElementById("rv-drawer");
    if (!backdrop || !drawer) return;
    lastFocus = trigger || document.activeElement;
    backdrop.classList.add("is-open");
    drawer.classList.add("is-open");
    drawer.setAttribute("aria-hidden", "false");
    var closeBtn = drawer.querySelector("[data-rv-drawer-close]");
    if (closeBtn) closeBtn.focus();
  }

  function closeDrawer() {
    var backdrop = document.getElementById("rv-drawer-backdrop");
    var drawer = document.getElementById("rv-drawer");
    if (!backdrop || !drawer) return;
    backdrop.classList.remove("is-open");
    drawer.classList.remove("is-open");
    drawer.setAttribute("aria-hidden", "true");
    if (lastFocus && typeof lastFocus.focus === "function") {
      lastFocus.focus();
    }
  }

  function showToast(message) {
    var el = document.getElementById("rv-toast");
    if (!el) return;
    el.textContent = message;
    el.classList.add("is-visible");
    window.setTimeout(function () {
      el.classList.remove("is-visible");
    }, 2800);
  }

  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape") {
      closeDrawer();
    }
  });

  document.addEventListener("click", function (ev) {
    var openBtn = ev.target.closest("[data-rv-drawer-open]");
    if (openBtn) {
      ev.preventDefault();
      openDrawer(openBtn);
      return;
    }
    if (ev.target.closest("[data-rv-drawer-close]") || ev.target.id === "rv-drawer-backdrop") {
      closeDrawer();
    }
    var toastBtn = ev.target.closest("[data-rv-toast]");
    if (toastBtn) {
      showToast(toastBtn.getAttribute("data-rv-toast") || "Saved");
    }
  });

  function initAdminTab() {
    var tab = document.getElementById("rv-admin-tab");
    if (!tab) return;
    if (tab.querySelector('[aria-current="page"]')) {
      tab.hidden = false;
      return;
    }
    var me = window.fetchCurrentUser
      ? window.fetchCurrentUser()
      : fetch("/api/auth/me", { credentials: "same-origin" }).then(function (r) {
          return r.ok ? r.json() : null;
        });
    me.then(function (u) {
      if (u && u.is_admin) tab.hidden = false;
    }).catch(function () {});
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initAdminTab);
  } else {
    initAdminTab();
  }

  window.RevampUI = { openDrawer: openDrawer, closeDrawer: closeDrawer, showToast: showToast, initAdminTab: initAdminTab };
})();