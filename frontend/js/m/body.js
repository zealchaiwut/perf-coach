/* Body screen: weigh-in, trend, Zone 2. */
(function (global) {
  "use strict";

  function esc(s) {
    if (global.AppCommon && AppCommon.escapeHtml) return AppCommon.escapeHtml(String(s == null ? "" : s));
    return String(s == null ? "" : s);
  }

  function chartSvg(weighIns) {
    var pts = (weighIns || []).filter(function (w) { return w && w.kg != null; });
    if (pts.length < 2) return '<div class="m-muted">Not enough weigh-ins for a trend yet.</div>';
    var kgs = pts.map(function (p) { return Number(p.kg); });
    var trends = pts.map(function (p) { return p.trend_kg != null ? Number(p.trend_kg) : Number(p.kg); });
    var lo = Math.min.apply(null, kgs.concat(trends)) - 0.3;
    var hi = Math.max.apply(null, kgs.concat(trends)) + 0.3;
    var span = hi - lo || 1;
    var w = 340;
    var h = 110;
    function x(i) { return 10 + (i / (pts.length - 1)) * (w - 20); }
    function y(v) { return h - 10 - ((v - lo) / span) * (h - 20); }
    var dots = pts.map(function (p, i) {
      return '<circle cx="' + x(i).toFixed(1) + '" cy="' + y(Number(p.kg)).toFixed(1) + '" r="3" fill="#c7d7f5"></circle>';
    }).join("");
    var line = trends.map(function (v, i) { return x(i).toFixed(1) + "," + y(v).toFixed(1); }).join(" ");
    return '<svg viewBox="0 0 ' + w + " " + h + '" class="m-chart" role="img" aria-label="Weight trend">' +
      '<line x1="0" y1="100" x2="340" y2="100" stroke="#eef1f7"></line>' +
      dots +
      '<polyline points="' + line + '" fill="none" stroke="#1f3b8a" stroke-width="2.5" stroke-linejoin="round"></polyline>' +
      '<circle cx="' + x(pts.length - 1).toFixed(1) + '" cy="' + y(trends[trends.length - 1]).toFixed(1) +
      '" r="5" fill="#1f3b8a"></circle></svg>';
  }

  function zone2Card(z) {
    if (!z) return "";
    var days = z.days || [];
    var max = 1;
    days.forEach(function (d) {
      max = Math.max(max, d.logged_min || 0, d.planned_min || 0);
    });
    var bars = days.map(function (d) {
      var logged = d.logged_min || 0;
      var planned = d.planned_min || 0;
      if (logged) {
        var h = Math.max(8, Math.round((logged / max) * 60));
        return '<span class="m-z2-bar m-z2-bar--logged" style="height:' + h + 'px"></span>';
      }
      if (planned) {
        var hp = Math.max(8, Math.round((planned / max) * 60));
        return '<span class="m-z2-bar m-z2-bar--planned" style="height:' + hp + 'px"></span>';
      }
      return '<span class="m-z2-bar m-z2-bar--stub"></span>';
    }).join("");
    var labels = days.map(function (d) { return "<span>" + esc(d.label || "") + "</span>"; }).join("");
    var hr = z.hr_ceiling != null ? z.hr_ceiling : 155;
    return '<div class="m-card"><span class="m-kicker m-kicker--grey">ZONE 2 · THIS WEEK</span>' +
      '<div class="m-mono m-lg">' + (z.total || 0) + ' <span class="m-muted">/ ' + (z.target || 150) + " min</span></div>" +
      '<div class="m-z2-bars">' + bars + "</div>" +
      '<div class="m-z2-labels">' + labels + "</div>" +
      '<p class="m-muted">Minutes with heart rate at or below ' + hr +
      " bpm, from synced runs. Dashed = planned easy runs.</p></div>";
  }

  function render(root, bundle) {
    var body = (bundle && bundle.body) || {};
    var last = (body.last_weigh_in && body.last_weigh_in.kg) || body.trend_kg || 70;
    var kg = last;
    var z = body.zone2_week;
    var ch = body.change_28d_kg;
    var trendLabel = body.trend_est ? " est." : "";
    var chHtml = ch == null ? "" : (ch < 0
      ? '<span class="m-down">↓' + Math.abs(ch).toFixed(1) + " in 4 wk</span>"
      : "↑" + Math.abs(Number(ch)).toFixed(1) + " in 4 wk");
    root.innerHTML = '<header class="m-page-head"><a href="/m/today" class="m-back">‹</a><h1>Body</h1></header>' +
      '<div class="m-card" id="m-weigh-card"><span class="m-kicker m-kicker--grey">WEIGH-IN</span>' +
      '<p class="m-muted">Morning, after the toilet.</p>' +
      '<div class="m-stepper m-stepper--lg"><button type="button" id="m-kg-down" aria-label="Minus 0.1 kg">−</button>' +
      '<button type="button" class="m-kg-num" id="m-kg-num">' + Number(kg).toFixed(1) +
      '</button><button type="button" id="m-kg-up" aria-label="Plus 0.1 kg">+</button></div>' +
      '<button type="button" class="m-primary" id="m-save-w">Save weigh-in</button></div>' +
      '<div class="m-card"><span class="m-kicker m-kicker--grey">TREND WEIGHT · 8 WEEKS</span>' +
      '<div class="m-mono m-lg">' + (body.trend_kg != null ? Number(body.trend_kg).toFixed(1) : "—") +
      " kg" + trendLabel + " " + chHtml + "</div>" +
      chartSvg(body.weigh_ins) +
      '<p class="m-muted">Dots are weigh-ins; the line is the smoothed trend that power-to-weight also uses.</p></div>' +
      zone2Card(z);

    function setKg(v) {
      kg = Math.round(v * 10) / 10;
      document.getElementById("m-kg-num").textContent = kg.toFixed(1);
    }
    document.getElementById("m-kg-down").addEventListener("click", function () { setKg(kg - 0.1); });
    document.getElementById("m-kg-up").addEventListener("click", function () { setKg(kg + 0.1); });
    document.getElementById("m-kg-num").addEventListener("click", function () {
      var typed = prompt("Weight (kg)", kg.toFixed(1));
      if (typed) setKg(parseFloat(typed));
    });
    document.getElementById("m-save-w").addEventListener("click", function () {
      var today = (bundle.today && bundle.today.date) || new Date().toISOString().slice(0, 10);
      var op = MStore.newOp("weigh_in", { date: today, kg: kg });
      MSync.enqueue(op).then(function () {
        if (!bundle.body) bundle.body = {};
        bundle.body.last_weigh_in = { date: today, kg: kg };
        bundle.body.trend_est = true;
        var list = bundle.body.weigh_ins || [];
        var hit = list.filter(function (w) { return w.date === today; })[0];
        if (hit) hit.kg = kg;
        else list.push({ date: today, kg: kg });
        bundle.body.weigh_ins = list;
        return MStore.getBundle().then(function (row) {
          var payload = (row && row.payload) || bundle;
          payload.body = payload.body || {};
          payload.body.last_weigh_in = { date: today, kg: kg };
          payload.body.trend_est = true;
          payload.body.weigh_ins = list;
          return MStore.setBundle(payload, row && row.etag);
        });
      }).then(function () {
        render(root, bundle);
      });
    });
    if (location.pathname.indexOf("weigh-in") !== -1) {
      document.getElementById("m-kg-num").focus();
    }
  }

  function mount() {
    var root = document.getElementById("m-main");
    MStore.getBundle().then(function (row) { render(root, (row && row.payload) || {}); });
    global.addEventListener("pc:bundle", function (e) { render(root, e.detail); });
  }

  global.MBody = { mount: mount, render: render, chartSvg: chartSvg, zone2Card: zone2Card };
})(window);
