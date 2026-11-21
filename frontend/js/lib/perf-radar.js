// Performance radar component (revamp P4-6). One component for Home (small) and
// Performance (large): both mount into [data-perf-radar] and read the SAME
// endpoint, so they cannot disagree. The SVG is rendered server-side from that
// payload (backend/services/radar_svg.py); nothing is recomputed here.
(function (global) {
  "use strict";

  var ENDPOINT = "/api/performance/radar";

  function mount(host, opts) {
    var size = (opts && opts.size) || host.getAttribute("data-size") || "large";
    host.setAttribute("aria-busy", "true");
    return fetch(ENDPOINT + "?size=" + encodeURIComponent(size), { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (payload) {
        host.innerHTML = payload.svg;
        host.removeAttribute("aria-busy");
        host.dispatchEvent(new CustomEvent("perf-radar:loaded", { detail: payload, bubbles: true }));
        return payload;
      })
      .catch(function () {
        host.removeAttribute("aria-busy");
        host.innerHTML = '<p class="rv-subtitle">Radar not available.</p>';
        return null;
      });
  }

  function mountAll(root) {
    var nodes = (root || document).querySelectorAll("[data-perf-radar]");
    return Promise.all(Array.prototype.map.call(nodes, function (n) { return mount(n); }));
  }

  global.PerfRadar = { mount: mount, mountAll: mountAll, ENDPOINT: ENDPOINT };
  document.addEventListener("DOMContentLoaded", function () { mountAll(); });
})(window);
