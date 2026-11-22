(function () {
      function _loadAbout() {
        fetch('/api/about')
          .then(function (r) {
            if (!r.ok) throw new Error('about endpoint unavailable');
            return r.json();
          })
          .then(function (data) {
            var vEl = document.getElementById('about-version');
            if (vEl) vEl.textContent = data.app_version || 'v0.0.1-dev';

            var shaEl = document.getElementById('about-sha');
            if (shaEl) shaEl.textContent = data.git_sha || 'local-dev';

            var envEl = document.getElementById('about-env');
            if (envEl) envEl.textContent = data.environment || 'local';

            if (data.changelog_available) {
              var cl = document.getElementById('about-changelog-link');
              if (cl) cl.style.display = '';
            }
          })
          .catch(function () {
            var vEl = document.getElementById('about-version');
            if (vEl) vEl.textContent = 'v0.0.1-dev';
            var shaEl = document.getElementById('about-sha');
            if (shaEl) shaEl.textContent = 'local-dev';
            var envEl = document.getElementById('about-env');
            if (envEl) envEl.textContent = 'local';
          });
      }

      _loadAbout();
}());
