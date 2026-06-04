/* Shared UI state helpers — loading, empty, error, toast */
(function (global) {
  function _injectStyles() {
    if (document.getElementById('ui-states-css')) return;
    var s = document.createElement('style');
    s.id = 'ui-states-css';
    s.textContent =
      '#ui-toast{position:fixed;bottom:1.25rem;right:1.25rem;z-index:9999;' +
      'padding:.625rem 1rem;border-radius:6px;font-size:.875rem;font-family:inherit;' +
      'font-weight:500;max-width:320px;box-shadow:0 2px 12px rgba(0,0,0,.18);' +
      'display:none;pointer-events:none;}' +
      '#ui-toast.ui-toast--ok{background:#16a34a;color:#fff;}' +
      '#ui-toast.ui-toast--error{background:#dc2626;color:#fff;}' +
      '@keyframes ui-spin{to{transform:rotate(360deg)}}' +
      '.ui-loading{display:flex;align-items:center;gap:.5rem;padding:.75rem 0;' +
      'font-size:.8125rem;color:#9ca3af;}' +
      '.ui-spinner{display:inline-block;width:14px;height:14px;' +
      'border:2px solid currentColor;border-top-color:transparent;border-radius:50%;' +
      'animation:ui-spin .7s linear infinite;flex-shrink:0;}' +
      '.ui-empty{padding:.75rem 0;font-size:.875rem;color:#888;}' +
      '.ui-empty p{margin:0 0 .4rem;}' +
      '.ui-empty-cta{margin-top:.4rem;}' +
      '.ui-error{padding:.75rem 0;font-size:.875rem;color:#dc2626;}';
    document.head.appendChild(s);
  }

  var _toastEl = null;
  var _toastTimer = null;

  function _ensureToast() {
    if (!_toastEl) {
      _toastEl = document.createElement('div');
      _toastEl.id = 'ui-toast';
      _toastEl.setAttribute('role', 'status');
      _toastEl.setAttribute('aria-live', 'polite');
      document.body.appendChild(_toastEl);
    }
    return _toastEl;
  }

  function showToast(msg, isError) {
    var el = _ensureToast();
    if (_toastTimer) clearTimeout(_toastTimer);
    el.textContent = msg;
    el.className = isError ? 'ui-toast--error' : 'ui-toast--ok';
    el.style.display = 'block';
    _toastTimer = setTimeout(function () { el.style.display = 'none'; }, 3000);
  }

  function loadingHTML(label) {
    return '<div class="ui-loading" role="status" aria-live="polite">' +
      '<span class="ui-spinner"></span>' +
      '<span>' + (label || 'Loading…') + '</span></div>';
  }

  function emptyHTML(msg, ctaHTML) {
    return '<div class="ui-empty"><p>' + msg + '</p>' +
      (ctaHTML ? '<div class="ui-empty-cta">' + ctaHTML + '</div>' : '') + '</div>';
  }

  function errorHTML(msg) {
    return '<div class="ui-error">' +
      (msg || 'Something went wrong. Please try again.') + '</div>';
  }

  function setLoading(el, label) { el.innerHTML = loadingHTML(label); }
  function setEmpty(el, msg, ctaHTML) { el.innerHTML = emptyHTML(msg, ctaHTML); }
  function setError(el, msg) { el.innerHTML = errorHTML(msg); }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', _injectStyles);
  } else {
    _injectStyles();
  }

  global.UIStates = {
    showToast: showToast,
    loadingHTML: loadingHTML,
    emptyHTML: emptyHTML,
    errorHTML: errorHTML,
    setLoading: setLoading,
    setEmpty: setEmpty,
    setError: setError
  };
})(window);
