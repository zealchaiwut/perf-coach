    // Shared field-error helper: sets/clears the message text next to a form
    // control AND toggles aria-invalid on the control itself (id convention:
    // control id + "-error" = message element id). Used by Profile, Thresholds
    // and Personal Records forms below.
    window._settingsSetFieldError = function (errorElId, msg) {
      var errEl = document.getElementById(errorElId);
      if (errEl) errEl.textContent = msg || '';
      var inputId = errorElId.replace(/-error$/, '');
      var inputEl = document.getElementById(inputId);
      if (inputEl) {
        if (msg) inputEl.setAttribute('aria-invalid', 'true');
        else inputEl.removeAttribute('aria-invalid');
      }
    };
    window._settingsClearFieldError = function (errorElId) {
      window._settingsSetFieldError(errorElId, '');
    };