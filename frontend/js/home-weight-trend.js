/**
 * Home "Weight trend" card (home revamp v2) — 30-day trend, rate ± CI,
 * coverage chip, sparkline. Reads the SAME /api/weight-chart endpoint the
 * Weight tab's chart uses (stats + ewma_series) — no new backend surface,
 * no invented numbers.
 */
(function () {
  'use strict';

  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  function _header() {
    return (
      '<div class="card-head">' +
        '<h2 class="ttl"><i class="ti ti-chart-line"></i>Weight trend</h2>' +
        '<a href="/weight">Open &#8594;</a>' +
      '</div>'
    );
  }

  function _fmtRate(rateKgWk, ciKgWk) {
    var sign = rateKgWk > 0 ? '+' : '';
    var txt = sign + rateKgWk.toFixed(2);
    if (ciKgWk != null) txt += ' <small>&plusmn; ' + Number(ciKgWk).toFixed(2) + ' kg/wk</small>';
    else txt += ' kg/wk';
    return txt;
  }

  function _sparklineSvg(series) {
    var pts = (series || []).map(function (p, i) { return { i: i, v: p.weight_kg }; })
      .filter(function (p) { return p.v != null; });
    if (pts.length < 2) return '';
    var vals = pts.map(function (p) { return p.v; });
    var min = Math.min.apply(null, vals), max = Math.max.apply(null, vals);
    var span = (max - min) || 1;
    var w = 320, h = 54, pad = 6;
    var n = series.length;
    function x(i) { return pad + i * ((w - pad * 2) / Math.max(1, n - 1)); }
    function y(v) { return pad + (1 - (v - min) / span) * (h - pad * 2); }

    var pathParts = [];
    var dots = '';
    series.forEach(function (p, i) {
      if (p.weight_kg == null) return;
      var px = x(i), py = y(p.weight_kg);
      pathParts.push((pathParts.length ? 'L' : 'M') + px.toFixed(1) + ',' + py.toFixed(1));
      dots += '<circle cx="' + px.toFixed(1) + '" cy="' + py.toFixed(1) + '" r="1.9" fill="#4f6ef7" opacity=".26"/>';
    });
    var lastIdx = pts[pts.length - 1].i;
    var lx = x(lastIdx).toFixed(1), ly = y(pts[pts.length - 1].v).toFixed(1);

    return (
      '<svg viewBox="0 0 ' + w + ' ' + h + '" width="100%" height="' + h + '" class="hwt-spark-svg" aria-hidden="true">' +
        dots +
        '<path d="' + pathParts.join(' ') + '" fill="none" stroke="#4f6ef7" stroke-width="2.2" stroke-linecap="round"/>' +
        '<circle cx="' + lx + '" cy="' + ly + '" r="3.6" fill="#4f6ef7"/>' +
      '</svg>'
    );
  }

  function render(host) {
    if (!host) return;
    host.innerHTML = _header() + '<div class="hwt-loading">Loading…</div>';

    var to = window.AppCommon.todayISO();
    var from = window.AppCommon.addDaysISO(to, -29);

    fetch('/api/weight-chart?from=' + from + '&to=' + to + '&include_target=true')
      .then(function (r) { return r.ok ? r.json() : Promise.reject(r.status); })
      .then(function (data) {
        var stats = data && data.stats;
        var series = (data && data.ewma_series) || [];
        var trendKg = stats && (stats.current_avg_kg != null ? stats.current_avg_kg : stats.current_weight_kg);

        if (!stats || trendKg == null) {
          host.innerHTML = _header() +
            '<div class="hwt-empty">No weight data yet. <a href="/weight">Log your first weigh-in</a>.</div>';
          return;
        }

        var rateHtml = stats.rate_kg_wk != null
          ? '<span class="hwt-rate">' + _fmtRate(stats.rate_kg_wk, stats.ci_kg_wk) + '</span>'
          : '<span class="hwt-rate hwt-rate--mute">rate not yet readable</span>';

        var covHtml = '';
        if (stats.coverage_pct != null) {
          covHtml = '<span class="hwt-cov' + (stats.gated ? ' hwt-cov--warn' : '') + '">' +
            Math.round(stats.coverage_pct) + '% logged' +
            (stats.gated ? ' &middot; need more data' : '') +
            '</span>';
        }

        host.innerHTML =
          _header() +
          '<div class="hwt-top">' +
            '<span><span class="hwt-big">' + esc(Number(trendKg).toFixed(1)) + '</span> <span class="hwt-unit">kg trend</span></span>' +
            rateHtml +
            covHtml +
          '</div>' +
          '<div class="hwt-spark">' + _sparklineSvg(series) + '</div>' +
          '<div class="hwt-foot"><span>' + series.length + ' days</span></div>';
      })
      .catch(function () {
        host.innerHTML = _header() + '<div class="hwt-empty">Could not load weight trend.</div>';
      });
  }

  window.HomeWeightTrend = { render: render };
})();
