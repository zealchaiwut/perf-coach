/* Gym mode overview + loggers (PWA phase 3). */
(function (global) {
  "use strict";

  function sessionIdFromPath() {
    var m = location.pathname.match(/\/m\/gym\/([^/]+)/);
    return m ? decodeURIComponent(m[1]) : null;
  }

  function findSession(bundle, id) {
    var list = (bundle && bundle.sessions) || [];
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }

  function emptyState(state, session) {
    return state || {
      session_id: session && session.id,
      started_at: Date.now(),
      position: { section: 0, exercise: 0, set: 0, round: 0 },
      results: {},
      edit_log: [],
      session_rpe: null,
      notes: "",
      active: true
    };
  }

  function persist(state) {
    state.active = true;
    return MStore.setSession(state).then(function () {
      return MStore.setMeta("session-active", true);
    });
  }

  function renderOverview(root, session, bundle, state) {
    var exercises = (session && session.exercises) || [];
    var sections = [];
    exercises.forEach(function (ex) {
      var sid = ex.section_id || sections.length || 1;
      var cur = sections.filter(function (s) { return s.id === sid; })[0];
      if (!cur) {
        cur = { id: sid, title: ex.section_title || ex.block || "Section", format: ex.section_format || "straight", items: [] };
        sections.push(cur);
      }
      cur.items.push(ex);
    });
    var last = bundle.last_numbers || {};
    var html = '<header class="m-gym-head"><a href="/m/today" class="m-back">‹</a><div>' +
      '<div class="m-kicker">GYM MODE · OFFLINE READY</div><h1>' + (session.name || "Strength") +
      '</h1></div><button type="button" id="m-gym-edit" class="m-text-btn">Edit</button></header>' +
      '<p class="m-mono m-muted">' + sections.length + " sections · " + exercises.length + " exercises · ≈" +
      (session.estimated_tss || "—") + " TSS</p><div id=\"m-gym-sections\">";
    sections.forEach(function (sec, i) {
      html += '<section class="m-sec"><div class="m-sec-h"><span>' + (i + 1) + " · " + String(sec.title).toUpperCase() +
        '</span><span class="m-muted">' + sec.format + "</span></div>";
      sec.items.forEach(function (ex, ei) {
        var ln = last[ex.name];
        html += '<button type="button" class="m-ex-row" data-sec="' + i + '" data-ex="' + ei + '"><strong>' +
          (ex.pair_label ? ex.pair_label + " " : "") + (ex.name || "") + "</strong>" +
          (ln ? '<div class="m-muted">Last: ' + (ln.kg != null ? ln.kg + " kg × " : "") + (ln.reps || "") + "</div>" : "") +
          "</button>";
      });
      html += "</section>";
    });
    html += '</div><button type="button" class="m-primary" id="m-gym-start">Start · ' +
      ((sections[0] && sections[0].title) || "session") + "</button>";
    root.innerHTML = html;
    function startAt(s, e) {
      state.position = { section: s || 0, exercise: e || 0, set: 0, round: 0 };
      persist(state).then(function () { paintLogger(root, session, bundle, state); });
    }
    var start = document.getElementById("m-gym-start");
    if (start) start.addEventListener("click", function () { startAt(0, 0); });
    root.querySelectorAll("[data-ex]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        startAt(Number(btn.getAttribute("data-sec")), Number(btn.getAttribute("data-ex")));
      });
    });
    var edit = document.getElementById("m-gym-edit");
    if (edit) edit.addEventListener("click", function () { if (global.MGymSwap) MGymSwap.open(session, state, bundle); });
  }

  function currentExercise(session, state) {
    var exercises = (session.exercises || []);
    return exercises[state.position.exercise] || exercises[0];
  }

  function paintLogger(root, session, bundle, state) {
    var ex = currentExercise(session, state) || { name: "Exercise", sets: [] };
    var fmt = ex.section_format || "straight";
    if (fmt === "emom" && global.MTimer) return MTimer.playEmom(root, session, state, persist);
    if (fmt === "interval" && global.MTimer) return MTimer.playInterval(root, session, state, persist);
    if (fmt === "hold" && global.MTimer) return MTimer.playHold(root, session, state, persist);
    var sets = Array.isArray(ex.sets) ? ex.sets : [];
    var idx = state.position.set || 0;
    var html = '<header class="m-gym-head"><button type="button" class="m-back" id="m-log-back">‹</button><div class="m-progress">';
    (session.exercises || []).forEach(function (_, i) {
      html += '<span class="m-pseg' + (i < state.position.exercise ? " done" : i === state.position.exercise ? " on" : "") + '"></span>';
    });
    html += '</div></header><h1>' + (ex.name || "") + "</h1>";
    var st = sets[idx] || { kg: 0, reps: 0 };
    html += '<div class="m-set-card"><div class="m-stepper"><button type="button" data-kg="-2">−</button><span id="m-kg">' +
      (st.kg || 0) + '</span><button type="button" data-kg="2">+</button></div>' +
      '<div class="m-stepper"><button type="button" data-reps="-1">−</button><span id="m-reps">' +
      (st.reps || 0) + '</span><button type="button" data-reps="1">+</button></div>' +
      '<button type="button" class="m-primary" id="m-done-set">Done set ' + (idx + 1) + "</button></div>" +
      '<div class="m-rpe">' + [6, 7, 8, 9, 10].map(function (n) {
        return '<button type="button" data-rpe="' + n + '">' + n + "</button>";
      }).join("") + "</div>" +
      '<div class="m-actions"><button type="button" id="m-swap">Swap</button><button type="button" id="m-add-set">+ Set</button>' +
      '<button type="button" id="m-skip">Skip</button></div>' +
      '<button type="button" class="m-primary" id="m-finish">Finish session</button>';
    root.innerHTML = html;
    document.getElementById("m-log-back").addEventListener("click", function () {
      renderOverview(root, session, bundle, state);
    });
    root.querySelectorAll("[data-kg]").forEach(function (b) {
      b.addEventListener("click", function () {
        st.kg = Number(st.kg || 0) + Number(b.getAttribute("data-kg"));
        document.getElementById("m-kg").textContent = st.kg;
        persist(state);
      });
    });
    root.querySelectorAll("[data-reps]").forEach(function (b) {
      b.addEventListener("click", function () {
        var n = parseInt(st.reps, 10) || 0;
        st.reps = n + Number(b.getAttribute("data-reps"));
        document.getElementById("m-reps").textContent = st.reps;
        persist(state);
      });
    });
    document.getElementById("m-done-set").addEventListener("click", function () {
      state.results[ex.name + ":" + idx] = { kg: st.kg, reps: st.reps };
      state.position.set = idx + 1;
      persist(state).then(function () {
        if (state.position.set >= sets.length) {
          state.position.exercise += 1;
          state.position.set = 0;
        }
        if (state.position.exercise >= (session.exercises || []).length) finish(session, state);
        else paintLogger(root, session, bundle, state);
      });
    });
    document.getElementById("m-finish").addEventListener("click", function () { finish(session, state); });
    document.getElementById("m-swap").addEventListener("click", function () {
      if (global.MGymSwap) MGymSwap.open(session, state, bundle);
    });
  }

  function finish(session, state) {
    var op = MStore.newOp("session_log", {
      session_id: session.id,
      name: session.name,
      date: session.date,
      exercises: session.exercises,
      results: state.results,
      session_rpe: state.session_rpe,
      notes: state.notes,
      duration_seconds: Math.round((Date.now() - state.started_at) / 1000),
      apply_to_future: true,
      edit_log: state.edit_log
    }, session.version_id);
    MSync.enqueue(op).then(function () {
      state.active = false;
      return Promise.all([MStore.setSession(state), MStore.setMeta("session-active", false)]);
    }).then(function () {
      location.href = "/m/today";
    });
  }

  function mount() {
    var root = document.getElementById("m-main");
    var id = sessionIdFromPath();
    MStore.getBundle().then(function (row) {
      var bundle = (row && row.payload) || { sessions: [] };
      var session = findSession(bundle, id);
      if (!session) {
        root.innerHTML = '<p class="m-card">Session is not on this phone. Pull to refresh when you are online.</p>';
        return;
      }
      MStore.getSession().then(function (saved) {
        var state = saved && saved.session_id === session.id ? saved : emptyState(null, session);
        if (state.active && saved && saved.position) paintLogger(root, session, bundle, state);
        else renderOverview(root, session, bundle, state);
      });
    });
  }

  global.MGym = { mount: mount, persist: persist, emptyState: emptyState, findSession: findSession };
})(window);
