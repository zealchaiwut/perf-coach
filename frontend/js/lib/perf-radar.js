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
        var legend = document.createElement("div");
        legend.className = "perf-radar-legend";
        legend.setAttribute("aria-hidden", "true");
        var compact = opts && opts.compactLegend;
        var pastLabel = compact ? "4 wk ago" : "4 weeks ago";
        var staleLabel = compact ? "Stale" : "Stale · needs a test effort";
        legend.innerHTML =
          '<span class="perf-radar-legend-item"><span class="perf-radar-swatch perf-radar-swatch--now"></span>Now</span>' +
          '<span class="perf-radar-legend-item"><span class="perf-radar-swatch perf-radar-swatch--past"></span>' + pastLabel + "</span>" +
          '<span class="perf-radar-legend-item"><span class="perf-radar-swatch perf-radar-swatch--stale"></span>' + staleLabel + "</span>" +
          '<span class="perf-radar-legend-item"><span class="perf-radar-swatch perf-radar-swatch--focus"></span>Focus</span>';
        host.appendChild(legend);
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
