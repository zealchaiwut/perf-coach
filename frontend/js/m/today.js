/* Phone Today screen. Renders only from the stored bundle. */
(function (global) {
  "use strict";

  function pad(n) { return n < 10 ? "0" + n : String(n); }
  function fmtDate(iso) {
    if (!iso) return "";
    var d = new Date(iso + "T00:00:00");
    var days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return days[d.getDay()] + " " + d.getDate() + " " + months[d.getMonth()];
  }
  function dur(sec) {
    if (!sec) return "";
    var m = Math.floor(sec / 60);
    var s = sec % 60;
    return Math.floor(m / 60) ? Math.floor(m / 60) + ":" + pad(m % 60) + ":" + pad(s) : m + ":" + pad(s);
  }
  function pace(sec) {
    if (!sec) return "";
    return Math.floor(sec / 60) + ":" + pad(sec % 60) + " /km";
  }

  function todaySession(bundle) {
    var today = bundle.today && bundle.today.date;
    var sessions = bundle.sessions || [];
    return sessions.filter(function (s) { return s.date === today; })[0] || null;
  }

  function kindLabel(session, rest) {
    if (rest) return "TODAY · REST";
    if (!session) return "TODAY";
    var t = (session.session_type || "").toLowerCase();
    if (t.indexOf("run") === 0) return "TODAY · RUN";
    if (t.indexOf("rest") === 0) return "TODAY · REST";
    return "TODAY · STRENGTH";
  }

  function render(root, bundle) {
    if (!root || !bundle) return;
    var today = bundle.today || {};
    var session = todaySession(bundle);
    var isRest = !session || (session.session_type || "").toLowerCase() === "rest";
    var subtitle = fmtDate(today.date);
    if (today.block_name || today.plan_phase) {
      subtitle += " · " + [today.block_name, today.plan_phase].filter(Boolean).join(", ");
    }
    var subEl = document.getElementById("m-sub");
    if (subEl) subEl.textContent = subtitle;

    var exercises = (session && session.exercises) || [];
    var chips = exercises.slice(0, 3).map(function (e) {
      return '<span class="m-chip">' + (e.name || "") + "</span>";
    }).join("");
    if (exercises.length > 3) chips += '<span class="m-chip">+' + (exercises.length - 3) + "</span>";
    var sets = exercises.reduce(function (a, e) { return a + ((e.sets && e.sets.length) || Number(e.sets) || 0); }, 0);
    var action = "";
    var t = session && (session.session_type || "").toLowerCase();
    if (session && t.indexOf("run") !== 0 && t !== "rest") {
      action = '<a class="m-primary" href="/m/gym/' + session.id + '">Start session ›</a>';
    } else if (session && t.indexOf("run") === 0) {
      action = '<a class="m-primary m-primary--ghost" href="/v2/training/log">Details</a>';
    }

    var hero = '<div class="m-card m-card--ink">' +
      '<div class="m-row"><span class="m-kicker">' + kindLabel(session, isRest && !session) + "</span>" +
      (session ? '<span class="m-ready">Ready offline</span>' : "") + "</div>" +
      "<h2>" + ((session && session.name) || (isRest ? "Rest day" : "Nothing planned")) + "</h2>" +
      (session ? '<p class="m-mono m-muted">' + exercises.length + " exercises · " + sets + " sets · ≈" + (session.estimated_tss || "—") + " TSS</p>" : "") +
      '<div class="m-chips">' + chips + "</div>" + action + "</div>";

    var run = (bundle.recent_runs || [])[0];
    var runHtml = run ? '<div class="m-card"><span class="m-kicker m-kicker--grey">LAST RUN</span>' +
      '<div class="m-row"><div><strong>' + (run.name || "Run") + " · " + fmtDate(run.date) + "</strong>" +
      '<div class="m-mono"><b>' + dur(run.duration_seconds) + "</b> · <b>" + (run.distance_km != null ? run.distance_km.toFixed(1) + " km" : "") + "</b> · " + pace(run.pace_sec_per_km) +
      "</div></div><div class="m-tss"><span>" + (run.tss != null ? Math.round(run.tss) : "—") + '</span><small>TSS</small></div></div></div>' : "";

    var body = bundle.body;
    var bodyHtml = "";
    if (body && (body.trend_kg != null || body.zone2_week)) {
      var z = body.zone2_week;
      var ch = body.change_28d_kg;
      var chHtml = ch == null ? "" : '<span class="' + (ch < 0 ? "m-down" : "") + '">' + (ch < 0 ? "↓" : "↑") + Math.abs(ch).toFixed(1) + "</span>";
      bodyHtml = '<div class="m-card"><div class="m-row"><span class="m-kicker m-kicker--grey">BODY</span><a href="/m/body/weigh-in">Weigh in ›</a></div>' +
        '<div class="m-body-grid"><div><span class="m-muted">Trend weight</span><div class="m-mono m-lg">' +
        (body.trend_kg != null ? body.trend_kg.toFixed(1) : "—") + " " + chHtml + "</div></div>" +
        (z ? '<div><span class="m-muted">Zone 2 this week</span><div class="m-mono m-lg">' + (z.total || 0) +
          ' <span class="m-muted">/ ' + (z.target || 150) + " min</span></div></div>" : "") +
        "</div></div>";
    }

    var next = (bundle.sessions || []).filter(function (s) { return s.date !== today.date; }).slice(0, 6);
    var nextHtml = '<div class="m-card m-card--glass"><span class="m-kicker m-kicker--on-ink">NEXT DAYS</span>' +
      next.map(function (s) {
        var mark = (s.session_type || "").toLowerCase().indexOf("run") !== 0 && s.session_type !== "rest"
          ? '<span class="m-offline-mark">✓ offline</span>' : '<span class="m-mono m-muted">' + (s.estimated_tss || "") + "</span>";
        return '<div class="m-next"><span class="m-mono">' + fmtDate(s.date).slice(0, 6) + "</span><span>" +
          (s.name || s.session_type) + "</span>" + mark + "</div>";
      }).join("") + "</div>";

    root.innerHTML = hero + runHtml + bodyHtml + nextHtml;
  }

  function mount() {
    var root = document.getElementById("m-main");
    function go(payload) {
      if (payload) render(root, payload);
    }
    fetch("/api/mobile/today-link", { credentials: "same-origin" }).catch(function () {});
    MStore.getBundle().then(function (row) { go(row && row.payload); });
    global.addEventListener("pc:bundle", function (e) { go(e.detail); });
    var startY = 0;
    document.addEventListener("touchstart", function (e) { startY = e.touches[0].clientY; }, { passive: true });
    document.addEventListener("touchend", function (e) {
      if (window.scrollY === 0 && startY && e.changedTouches[0].clientY - startY > 60) {
        MSync.refreshBundle();
      }
    });
  }

  global.MToday = { mount: mount, render: render, todaySession: todaySession };
})(window);
