/* Body screen: weigh-in, trend, Zone 2. */
(function (global) {
  "use strict";

  function render(root, bundle) {
    var body = (bundle && bundle.body) || {};
    var last = (body.last_weigh_in && body.last_weigh_in.kg) || body.trend_kg || 70;
    var kg = last;
    var z = body.zone2_week;
    var ch = body.change_28d_kg;
    root.innerHTML = '<header class="m-page-head"><a href="/m/today" class="m-back">‹</a><h1>Body</h1></header>' +
      '<div class="m-card" id="m-weigh-card"><span class="m-kicker m-kicker--grey">WEIGH-IN</span>' +
      '<p class="m-muted">Morning, after the toilet.</p>' +
      '<div class="m-stepper m-stepper--lg"><button type="button" id="m-kg-down">−</button>' +
      '<button type="button" class="m-kg-num" id="m-kg-num">' + Number(kg).toFixed(1) +
      '</button><button type="button" id="m-kg-up">+</button></div>' +
      '<button type="button" class="m-primary" id="m-save-w">Save weigh-in</button></div>' +
      '<div class="m-card"><span class="m-kicker m-kicker--grey">TREND</span>' +
      '<div class="m-mono m-lg">' + (body.trend_kg != null ? Number(body.trend_kg).toFixed(1) : "—") +
      " kg " + (ch != null ? (ch < 0 ? '<span class="m-down">↓' + Math.abs(ch).toFixed(1) : "↑" + Math.abs(ch).toFixed(1)) + "</span>" : "") +
      '</div><div id="m-trend-chart" class="m-chart"></div></div>' +
      (z ? '<div class="m-card"><span class="m-kicker m-kicker--grey">ZONE 2</span><div class="m-mono m-lg">' +
        (z.total || 0) + " / " + (z.target || 150) + " min</div></div>" : "");

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
        return MStore.getBundle().then(function (row) {
          var payload = (row && row.payload) || bundle;
          payload.body = payload.body || {};
          payload.body.last_weigh_in = { date: today, kg: kg };
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

  global.MBody = { mount: mount, render: render };
})(window);
