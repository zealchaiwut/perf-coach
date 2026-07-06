(function () {
  var VALID_SECTIONS = ['profile', 'thresholds', 'personal-records', 'integrations', 'about'];
  var DEFAULT_SECTION = 'profile';

  function activateSection(sectionId) {
    if (VALID_SECTIONS.indexOf(sectionId) === -1) {
      sectionId = DEFAULT_SECTION;
    }

    document.querySelectorAll('.settings-section').forEach(function (el) {
      el.classList.remove('active');
      el.style.display = 'none';
    });

    document.querySelectorAll('.settings-nav-item').forEach(function (el) {
      el.classList.remove('active');
      el.setAttribute('aria-selected', 'false');
      el.setAttribute('tabindex', '-1');
    });

    var target = document.getElementById('section-' + sectionId);
    if (target) {
      target.style.display = 'block';
      target.classList.add('active');
    }

    var navItem = document.querySelector('[data-section="' + sectionId + '"]');
    if (navItem) {
      navItem.classList.add('active');
      navItem.setAttribute('aria-selected', 'true');
      navItem.setAttribute('tabindex', '0');
    }
  }

  function getSectionFromHash() {
    var hash = window.location.hash.replace('#', '').trim();
    return hash || DEFAULT_SECTION;
  }

  var navItems = Array.prototype.slice.call(document.querySelectorAll('.settings-nav-item'));
  var visibleNavItems = navItems.filter(function (el) { return !el.hasAttribute('hidden'); });

  navItems.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var section = btn.getAttribute('data-section');
      if (window.location.hash !== '#' + section) {
        window.location.hash = section;
      } else {
        activateSection(section);
      }
    });

    // Roving-tabindex arrow-key navigation between tabs (WAI-ARIA tabs pattern)
    btn.addEventListener('keydown', function (e) {
      var key = e.key;
      if (key !== 'ArrowRight' && key !== 'ArrowLeft' && key !== 'Home' && key !== 'End') return;
      e.preventDefault();
      var idx = visibleNavItems.indexOf(btn);
      if (idx === -1) return;
      var nextIdx = idx;
      if (key === 'ArrowRight') nextIdx = (idx + 1) % visibleNavItems.length;
      else if (key === 'ArrowLeft') nextIdx = (idx - 1 + visibleNavItems.length) % visibleNavItems.length;
      else if (key === 'Home') nextIdx = 0;
      else if (key === 'End') nextIdx = visibleNavItems.length - 1;
      var nextBtn = visibleNavItems[nextIdx];
      if (nextBtn) {
        nextBtn.focus();
        var section = nextBtn.getAttribute('data-section');
        if (window.location.hash !== '#' + section) {
          window.location.hash = section;
        } else {
          activateSection(section);
        }
      }
    });
  });

  window.addEventListener('hashchange', function () {
    activateSection(getSectionFromHash());
  });

  activateSection(getSectionFromHash());
}());
