/* Phone Today screen. Renders only from the stored bundle. */
(function (global) {
  "use strict";

  function esc(s) {
    if (global.AppCommon && AppCommon.escapeHtml) return AppCommon.escapeHtml(String(s == null ? "" : s));
    return String(s == null ? "" : s);
  }
  function pad(n) { return n < 10 ? "0" + n : String(n); }
  function fmtDate(iso) {
    if (!iso) return "";
    var d = new Date(iso + "T00:00:00");
    var days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return days[d.getDay()] + " " + d.getDate() + " " + months[d.getMonth()];
  }
  function fmtDay(iso) {
    if (!iso) return "";
    var d = new Date(iso + "T00:00:00");
    var days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    return days[d.getDay()] + " " + d.getDate();
  }
  function addDays(iso, n) {
    var d = new Date(iso + "T00:00:00");
    d.setDate(d.getDate() + n);
    return d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate());
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

  function sessionKind(session) {
    if (!session) return "empty";
    var t = (session.session_type || "").toLowerCase();
    if (t === "rest" || t.indexOf("rest") === 0) return "rest";
    if (t.indexOf("run") !== -1 || t === "easy" || t === "quality" || t === "long") return "run";
    if (t === "mobility" || t === "stretch") return "rest";
    return "strength";
  }

  function kindLabel(kind) {
    if (kind === "rest") return "TODAY · REST";
    if (kind === "run") return "TODAY · RUN";
    if (kind === "empty") return "TODAY";
    return "TODAY · STRENGTH";
  }

  function setCount(exercises) {
    return (exercises || []).reduce(function (a, e) {
      if (Array.isArray(e.sets)) return a + e.sets.length;
      var n = Number(e.sets);
      return a + (n || 0);
    }, 0);
  }

  function render(root, bundle) {
    if (!root || !bundle) return;
    var today = bundle.today || {};
    var session = todaySession(bundle);
    var kind = sessionKind(session);
    var subtitle = fmtDate(today.date);
    var bits = [today.block_name, today.plan_phase].filter(Boolean);
    if (bits.length) subtitle += " · " + bits.join(", ");
    var subEl = document.getElementById("m-sub");
    if (subEl) subEl.textContent = subtitle;

    var exercises = (session && session.exercises) || [];
    var chips = exercises.slice(0, 3).map(function (e) {
      return '<span class="m-chip">' + esc(e.name) + "</span>";
    }).join("");
    if (exercises.length > 3) chips += '<span class="m-chip">+' + (exercises.length - 3) + "</span>";
    var sets = setCount(exercises);
    var mins = session && session.duration_minutes;
    var summaryParts = [];
    if (kind === "strength") {
      summaryParts.push(exercises.length + " exercises");
      summaryParts.push(sets + " sets");
      if (mins) summaryParts.push("~" + mins + " min");
      summaryParts.push("≈" + (session.estimated_tss != null ? session.estimated_tss : "—") + " TSS");
    } else if (kind === "run" && session) {
      if (mins) summaryParts.push("~" + mins + " min");
      if (session.estimated_tss != null) summaryParts.push("≈" + session.estimated_tss + " TSS");
    }

    var action = "";
    if (kind === "strength" && session) {
      action = '<a class="m-primary" href="/m/gym/' + encodeURIComponent(session.id) + '">Start session ›</a>';
    } else if (kind === "run" && session) {
      action = '<a class="m-primary m-primary--ghost" href="/v2/training/log">Details</a>';
    }

    var title = (session && session.name) || (kind === "rest" ? "Rest day" : "Nothing planned");
    var ready = kind === "strength"
      ? '<span class="m-ready"><svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M5 12l5 5 9-10"/></svg>Ready offline</span>'
      : "";

    var hero = '<div class="m-card m-card--ink" data-today-kind="' + kind + '">' +
      '<div class="m-row"><span class="m-kicker">' + kindLabel(kind) + "</span>" + ready + "</div>" +
      "<h2>" + esc(title) + "</h2>" +
      (summaryParts.length ? '<p class="m-mono m-muted">' + summaryParts.join(" · ") + "</p>" : "") +
      (chips ? '<div class="m-chips">' + chips + "</div>" : "") +
      action + "</div>";

    var run = (bundle.recent_runs || [])[0];
    var runHtml = "";
    if (run) {
      runHtml = '<div class="m-card"><span class="m-kicker m-kicker--grey">LAST RUN</span>' +
        '<div class="m-row"><div><strong>' + esc(run.name || "Run") + " · " + fmtDate(run.date) + "</strong>" +
        '<div class="m-mono"><b>' + dur(run.duration_seconds) + "</b> · <b>" +
        (run.distance_km != null ? Number(run.distance_km).toFixed(1) + " km" : "") +
        "</b> · " + pace(run.pace_sec_per_km) +
        '</div></div><div class="m-tss"><span>' + (run.tss != null ? Math.round(run.tss) : "—") +
        '</span><small>TSS</small></div></div></div>';
    }

    var body = bundle.body;
    var bodyHtml = "";
    if (body) {
      var z = body.zone2_week;
      var ch = body.change_28d_kg;
      var chHtml = ch == null ? "" : '<span class="' + (ch < 0 ? "m-down" : "") + '">' +
        (ch < 0 ? "↓" : "↑") + Math.abs(ch).toFixed(1) + "</span>";
      bodyHtml = '<div class="m-card" id="m-body-card"><div class="m-row"><span class="m-kicker m-kicker--grey">BODY</span>' +
        '<a href="/m/body/weigh-in">Weigh in ›</a></div>' +
        '<div class="m-body-grid"><div><span class="m-muted">Trend weight</span><div class="m-mono m-lg">' +
        (body.trend_kg != null ? Number(body.trend_kg).toFixed(1) : "—") + " " + chHtml + "</div></div>" +
        (z ? '<div><span class="m-muted">Zone 2 this week</span><div class="m-mono m-lg">' + (z.total || 0) +
          ' <span class="m-muted">/ ' + (z.target || 150) + " min</span></div></div>" : "") +
        "</div></div>";
    }

    var byDate = {};
    (bundle.sessions || []).forEach(function (s) { byDate[s.date] = s; });
    var nextHtml = '<div class="m-card m-card--glass"><span class="m-kicker m-kicker--on-ink">NEXT DAYS</span>';
    if (today.date) {
      for (var i = 1; i <= 6; i++) {
        var d = addDays(today.date, i);
        var s = byDate[d];
        var sk = sessionKind(s);
        var mark = s && sk === "strength"
          ? '<span class="m-offline-mark">✓ offline</span>'
          : '<span class="m-mono m-muted">' + (s && s.estimated_tss != null ? s.estimated_tss : "") + "</span>";
        nextHtml += '<div class="m-next"><span class="m-mono">' + fmtDay(d) + "</span><span>" +
          esc(s ? (s.name || s.session_type) : "Rest") + "</span>" + mark + "</div>";
      }
    }
    nextHtml += "</div>";

    root.innerHTML = hero + runHtml + bodyHtml + nextHtml;
  }

  function mount() {
    var root = document.getElementById("m-main");
    function go(payload) {
      if (payload) render(root, payload);
    }
    MStore.getBundle().then(function (row) {
      go(row && row.payload);
      fetch("/api/mobile/today-link", { credentials: "same-origin" }).catch(function () {});
    });
    global.addEventListener("pc:bundle", function (e) { go(e.detail); });
    var startY = 0;
    document.addEventListener("touchstart", function (e) { startY = e.touches[0].clientY; }, { passive: true });
    document.addEventListener("touchend", function (e) {
      if (window.scrollY === 0 && startY && e.changedTouches[0].clientY - startY > 60) {
        MSync.refreshBundle();
      }
    });
  }

  global.MToday = {
    mount: mount,
    render: render,
    todaySession: todaySession,
    sessionKind: sessionKind,
    kindLabel: kindLabel
  };
})(window);
