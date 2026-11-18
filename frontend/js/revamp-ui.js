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

  window.RevampUI = { openDrawer: openDrawer, closeDrawer: closeDrawer, showToast: showToast };
})();