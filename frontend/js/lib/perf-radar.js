// Performance radar component (revamp P4-6). One component for Home (small) and
// Performance (large): both mount into [data-perf-radar] and read the SAME
// endpoint, so they cannot disagree. The SVG is rendered server-side from that
// payload (backend/services/radar_svg.py); nothing is recomputed here.
(function (global) {
  "use strict";

  var ENDPOINT = "/api/performance/radar";

  function paint(host, payload, opts) {
    if (!host || !payload || !payload.svg) return null;
    host.innerHTML = payload.svg;
    var legend = document.createElement("div");
    legend.className = "perf-radar-legend";
    legend.setAttribute("aria-hidden", "true");
    var compact = opts && opts.compactLegend;
    var flags = payload.legend || {};
    var hasPast = flags.past;
    if (hasPast == null) hasPast = !!host.querySelector(".perf-radar-past");
    var hasStale = flags.stale;
    if (hasStale == null) hasStale = !!host.querySelector(".perf-radar-point--stale");
    var hasFocus = flags.focus;
    if (hasFocus == null) hasFocus = !!host.querySelector(".perf-radar-point--focus");
    var hasMissing = flags.not_measured;
    if (hasMissing == null) hasMissing = !!host.querySelector(".perf-radar-point--missing");
    var html = '<span class="perf-radar-legend-item"><span class="perf-radar-swatch perf-radar-swatch--now"></span>Now</span>';
    if (hasPast) {
      html += '<span class="perf-radar-legend-item"><span class="perf-radar-swatch perf-radar-swatch--past"></span>' +
        (compact ? "4 wk ago" : "4 weeks ago") + "</span>";
    }
    if (hasStale) {
      html += '<span class="perf-radar-legend-item"><span class="perf-radar-swatch perf-radar-swatch--stale"></span>Stale</span>';
    }
    if (hasFocus) {
      html += '<span class="perf-radar-legend-item"><span class="perf-radar-swatch perf-radar-swatch--focus"></span>Focus</span>';
    }
    if (hasMissing) {
      html += '<span class="perf-radar-legend-item"><span class="perf-radar-swatch perf-radar-swatch--missing"></span>Not measured</span>';
    }
    legend.innerHTML = html;
    host.appendChild(legend);
    host.removeAttribute("aria-busy");
    host.dispatchEvent(new CustomEvent("perf-radar:loaded", { detail: payload, bubbles: true }));
    return payload;
  }

  function mount(host, opts) {
    var size = (opts && opts.size) || host.getAttribute("data-size") || "large";
    host.setAttribute("aria-busy", "true");
    return fetch(ENDPOINT + "?size=" + encodeURIComponent(size), { credentials: "same-origin" })
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (payload) { return paint(host, payload, opts); })
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

  global.PerfRadar = { mount: mount, mountAll: mountAll, paint: paint, ENDPOINT: ENDPOINT };
  document.addEventListener("DOMContentLoaded", function () {
    if (document.body && document.body.getAttribute("data-perf-radar-boot") === "page") return;
    mountAll();
  });
})(window);
