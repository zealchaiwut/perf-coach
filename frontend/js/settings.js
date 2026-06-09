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
    });

    var target = document.getElementById('section-' + sectionId);
    if (target) {
      target.style.display = 'block';
      target.classList.add('active');
    }

    var navItem = document.querySelector('[data-section="' + sectionId + '"]');
    if (navItem) {
      navItem.classList.add('active');
    }
  }

  function getSectionFromHash() {
    var hash = window.location.hash.replace('#', '').trim();
    return hash || DEFAULT_SECTION;
  }

  document.querySelectorAll('.settings-nav-item').forEach(function (btn) {
    btn.addEventListener('click', function () {
      var section = btn.getAttribute('data-section');
      if (window.location.hash !== '#' + section) {
        window.location.hash = section;
      } else {
        activateSection(section);
      }
    });
  });

  window.addEventListener('hashchange', function () {
    activateSection(getSectionFromHash());
  });

  activateSection(getSectionFromHash());
}());
