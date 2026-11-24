/* Gym mode: overview, loggers, timers, finish. */
(function (global) {
  "use strict";

  var ctx = { session: null, bundle: null, state: null, root: null };

  function sessionIdFromPath() {
    var m = location.pathname.match(/\/m\/gym\/([^/]+)/);
    return m ? decodeURIComponent(m[1]) : null;
  }

  function findSession(bundle, id) {
    var list = (bundle && bundle.sessions) || [];
    for (var i = 0; i < list.length; i++) if (String(list[i].id) === String(id)) return list[i];
    return null;
  }

  function sectionsOf(session) {
    var exercises = (session && session.exercises) || [];
    var sections = [];
    var map = {};
    exercises.forEach(function (ex, idx) {
      var sid = ex.section_id != null ? String(ex.section_id) : String(sections.length || 1);
      if (ex.section_title) sid = String(ex.section_id != null ? ex.section_id : ex.section_title);
      var cur = map[sid];
      if (!cur) {
        cur = {
          id: sid,
          title: ex.section_title || ex.block || ("Section " + (sections.length + 1)),
          format: ex.section_format || "straight",
          items: [],
          startIndex: idx
        };
        map[sid] = cur;
        sections.push(cur);
      }
      cur.items.push(ex);
    });
    if (!sections.length && exercises.length) {
      sections.push({ id: "1", title: "Main", format: "straight", items: exercises, startIndex: 0 });
    }
    return sections;
  }

  function emptyState(session) {
    return {
      session_id: session && session.id,
      started_at: Date.now(),
      position: { section: 0, exercise: 0, set: 0, round: 0 },
      results: {},
      rpe: {},
      notes: "",
      session_rpe: null,
      edit_log: [],
      rest_until: null,
      apply_to_future: true,
      screen: "overview",
      timer: null,
      active: true
    };
  }

  function persist() {
    ctx.state.active = true;
    return Promise.all([
      MStore.setSession(ctx.state),
      MStore.setMeta("session-active", true)
    ]);
  }

  function plannedSets(ex) {
    if (Array.isArray(ex.sets) && ex.sets.length) return ex.sets.map(function (s) { return { kg: s.kg || 0, reps: s.reps || 0, hold: s.hold }; });
    var n = Number(ex.sets) || 3;
    var kg = ex.load || ex.kg || 0;
    var reps = ex.reps || 8;
    var out = [];
    for (var i = 0; i < n; i++) out.push({ kg: kg, reps: reps });
    return out;
  }

  function resultKey(ex, setIdx) {
    return (ex.name || "ex") + ":" + setIdx;
  }

  function renderOverview() {
    var session = ctx.session;
    var bundle = ctx.bundle;
    var sections = sectionsOf(session);
    var last = bundle.last_numbers || {};
    var html = '<header class="m-gym-head"><a href="/m/today" class="m-back">‹</a><div>' +
      '<div class="m-kicker">GYM MODE · OFFLINE READY</div><h1>' + (session.name || "Strength") +
      '</h1></div><button type="button" id="m-gym-edit" class="m-text-btn">Edit</button></header>' +
      '<p class="m-mono m-muted">' + sections.length + " sections · " + (session.exercises || []).length +
      " exercises · ≈" + (session.estimated_tss != null ? session.estimated_tss : "—") + " TSS</p><div id=\"m-gym-sections\">";
    sections.forEach(function (sec, i) {
      var timed = sec.format === "emom" || sec.format === "interval" || sec.format === "hold";
      html += '<section class="m-sec" data-format="' + sec.format + '"><div class="m-sec-h"><span>' +
        (i + 1) + " · " + String(sec.title).toUpperCase() + '</span><span class="m-muted">' +
        (timed ? "timer · " : "") + sec.format + "</span></div>";
      if (sec.format === "superset") {
        html += '<div class="m-super">';
        sec.items.forEach(function (ex, ei) {
          html += '<button type="button" class="m-ex-row" data-sec="' + i + '" data-ex="' + (sec.startIndex + ei) + '"><strong>' +
            (ex.pair_label || "") + " " + (ex.name || "") + "</strong></button>";
        });
        html += "</div>";
      } else {
        sec.items.forEach(function (ex, ei) {
          var ln = last[ex.name];
          html += '<button type="button" class="m-ex-row" data-sec="' + i + '" data-ex="' + (sec.startIndex + ei) + '"><strong>' +
            (ex.name || "") + "</strong>" +
            (ln ? '<div class="m-muted">Last: ' + (ln.kg != null ? ln.kg + " kg × " : "") + (ln.reps || "") + "</div>" : "") +
            "</button>";
        });
      }
      html += "</section>";
    });
    html += '</div><button type="button" class="m-primary" id="m-gym-start">Start · ' +
      ((sections[0] && sections[0].title) || "session") + "</button>";
    ctx.root.innerHTML = html;
    function startAt(s, e) {
      ctx.state.position = { section: s || 0, exercise: e || 0, set: 0, round: 0 };
      ctx.state.screen = "play";
      persist().then(paintPlay);
    }
    document.getElementById("m-gym-start").addEventListener("click", function () { startAt(0, 0); });
    ctx.root.querySelectorAll("[data-ex]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        startAt(Number(btn.getAttribute("data-sec")), Number(btn.getAttribute("data-ex")));
      });
    });
    document.getElementById("m-gym-edit").addEventListener("click", function () { openSwap(null); });
  }

  function currentExercise() {
    return ((ctx.session.exercises || [])[ctx.state.position.exercise]) || (ctx.session.exercises || [])[0];
  }

  function paintPlay() {
    var ex = currentExercise();
    if (!ex) return renderFinish();
    var fmt = ex.section_format || "straight";
    if (fmt === "superset") return paintSuperset();
    if (fmt === "emom") return paintEmom();
    if (fmt === "interval") return paintInterval();
    if (fmt === "hold") return paintHold();
    return paintStraight();
  }

  function paintStraight() {
    var session = ctx.session;
    var ex = currentExercise();
    var sets = plannedSets(ex);
    var idx = ctx.state.position.set || 0;
    var html = '<header class="m-gym-head"><button type="button" class="m-back" id="m-log-back">‹</button><div class="m-progress">';
    (session.exercises || []).forEach(function (_, i) {
      html += '<span class="m-pseg' + (i < ctx.state.position.exercise ? " done" : i === ctx.state.position.exercise ? " on" : "") + '"></span>';
    });
    html += '</div><span class="m-mono" id="m-elapsed"></span></header><h1>' + (ex.name || "") + "</h1>";
    if (ctx.state.rest_until && Date.now() < ctx.state.rest_until) {
      var left = Math.ceil((ctx.state.rest_until - Date.now()) / 1000);
      html += '<div class="m-rest"><span class="m-mono m-lg">' + left + 's</span> Rest<button type="button" id="m-skip-rest">Skip</button></div>';
    }
    sets.forEach(function (st, i) {
      var done = ctx.state.results[resultKey(ex, i)];
      if (done) {
        html += '<div class="m-set-done"><span class="m-mono">Set ' + (i + 1) + '</span><span class="m-mono">' +
          (done.kg || 0) + " kg × " + (done.reps || 0) + "</span></div>";
      } else if (i === idx) {
        html += '<div class="m-set-card"><div class="m-mono">Set ' + (i + 1) + ' · now</div>' +
          '<div class="m-stepper"><button type="button" data-kg="-2">−</button><span id="m-kg">' +
          (st.kg || 0) + '</span><button type="button" data-kg="2">+</button></div>' +
          '<div class="m-stepper"><button type="button" data-reps="-1">−</button><span id="m-reps">' +
          (st.reps || 0) + '</span><button type="button" data-reps="1">+</button></div>' +
          '<button type="button" class="m-primary" id="m-done-set">Done set ' + (i + 1) + "</button></div>";
      } else {
        html += '<div class="m-set-todo"><span class="m-mono">Set ' + (i + 1) + "</span><span>" +
          (st.kg || 0) + " kg × " + (st.reps || 0) + "</span></div>";
      }
    });
    html += '<div class="m-rpe">' + [6, 7, 8, 9, 10].map(function (n) {
      var on = ctx.state.rpe[ex.name] === n ? " on" : "";
      return '<button type="button" class="' + on + '" data-rpe="' + n + '">' + n + "</button>";
    }).join("") + "</div>" +
      '<div class="m-actions"><button type="button" id="m-swap">Swap</button><button type="button" id="m-add-set">+ Set</button>' +
      '<button type="button" id="m-skip">Skip</button><button type="button" id="m-note">Note</button></div>' +
      '<button type="button" class="m-primary" id="m-next-ex">Next</button>';
    ctx.root.innerHTML = html;
    tickElapsed();
    document.getElementById("m-log-back").addEventListener("click", function () {
      ctx.state.screen = "overview";
      persist().then(renderOverview);
    });
    var skipRest = document.getElementById("m-skip-rest");
    if (skipRest) skipRest.addEventListener("click", function () { ctx.state.rest_until = null; persist().then(paintStraight); });
    ctx.root.querySelectorAll("[data-kg]").forEach(function (b) {
      b.addEventListener("click", function () {
        var st = sets[idx];
        var delta = Number(b.getAttribute("data-kg"));
        st.kg = Number(st.kg || 0) + delta;
        for (var j = idx; j < sets.length; j++) sets[j].kg = st.kg;
        document.getElementById("m-kg").textContent = st.kg;
        var key = (ex.name || "").toLowerCase();
        var last = ctx.state.edit_log.filter(function (e) { return e.type === "kg" && e.exercise_key === key; }).pop();
        if (last) last.kg = st.kg;
        else ctx.state.edit_log.push({ type: "kg", exercise: ex.name, exercise_key: key, kg: st.kg, kg_delta: delta });
        persist();
      });
    });
    ctx.root.querySelectorAll("[data-reps]").forEach(function (b) {
      b.addEventListener("click", function () {
        var st = sets[idx];
        st.reps = (parseInt(st.reps, 10) || 0) + Number(b.getAttribute("data-reps"));
        document.getElementById("m-reps").textContent = st.reps;
        persist();
      });
    });
    var done = document.getElementById("m-done-set");
    if (done) done.addEventListener("click", function () {
      var st = sets[idx];
      ctx.state.results[resultKey(ex, idx)] = { kg: st.kg, reps: st.reps };
      ctx.state.position.set = idx + 1;
      ctx.state.rest_until = Date.now() + ((ex.rest_after_seconds || 90) * 1000);
      persist().then(paintPlay);
    });
    ctx.root.querySelectorAll("[data-rpe]").forEach(function (b) {
      b.addEventListener("click", function () {
        ctx.state.rpe[ex.name] = Number(b.getAttribute("data-rpe"));
        persist().then(paintStraight);
      });
    });
    document.getElementById("m-add-set").addEventListener("click", function () {
      sets.push(Object.assign({}, sets[sets.length - 1] || { kg: 0, reps: 8 }));
      ex.sets = sets;
      ctx.state.edit_log.push({ type: "add_set", exercise: ex.name, exercise_key: (ex.name || "").toLowerCase() });
      persist().then(paintStraight);
    });
    document.getElementById("m-skip").addEventListener("click", nextExercise);
    document.getElementById("m-next-ex").addEventListener("click", nextExercise);
    document.getElementById("m-swap").addEventListener("click", function () { openSwap(ex); });
    document.getElementById("m-note").addEventListener("click", function () {
      var n = prompt("Note", ctx.state.notes || "");
      if (n != null) { ctx.state.notes = n; persist(); }
    });
  }

  function nextExercise() {
    ctx.state.position.exercise += 1;
    ctx.state.position.set = 0;
    ctx.state.rest_until = null;
    if (ctx.state.position.exercise >= (ctx.session.exercises || []).length) {
      ctx.state.screen = "finish";
      persist().then(renderFinish);
    } else persist().then(paintPlay);
  }

  function paintSuperset() {
    var ex = currentExercise();
    var sections = sectionsOf(ctx.session);
    var sec = sections[ctx.state.position.section] || sections.filter(function (s) { return s.format === "superset"; })[0];
    var items = (sec && sec.items) || [ex];
    var round = ctx.state.position.round || 0;
    var rounds = ctx.state.position.rounds || 3;
    var which = ctx.state.position.set % items.length;
    var html = '<header class="m-gym-head"><button type="button" class="m-back" id="m-log-back">‹</button>' +
      '<div class="m-kicker">SUPERSET · ROUND ' + (round + 1) + " OF " + rounds + "</div></header>";
    items.forEach(function (it, i) {
      var on = i === which;
      html += '<div class="m-ex-row' + (on ? " on" : "") + '"><strong>' + (it.pair_label || "") + " " + (it.name || "") +
        "</strong></div>";
    });
    html += '<button type="button" class="m-primary" id="m-done-a">Done ' + (items[which] && items[which].pair_label || "A") + "</button>" +
      '<button type="button" id="m-add-round">+ Round</button>';
    ctx.root.innerHTML = html;
    document.getElementById("m-log-back").addEventListener("click", function () {
      ctx.state.screen = "overview"; persist().then(renderOverview);
    });
    document.getElementById("m-done-a").addEventListener("click", function () {
      var it = items[which];
      var sets = plannedSets(it);
      var st = sets[round] || sets[0] || { kg: 0, reps: 0 };
      ctx.state.results[resultKey(it, round)] = st;
      ctx.state.position.set += 1;
      if (ctx.state.position.set % items.length === 0) {
        ctx.state.position.round += 1;
        ctx.state.rest_until = Date.now() + 90000;
      }
      if (ctx.state.position.round >= rounds) nextExercise();
      else persist().then(paintSuperset);
    });
    document.getElementById("m-add-round").addEventListener("click", function () {
      ctx.state.position.rounds = rounds + 1;
      ctx.state.edit_log.push({ type: "add_round", exercise: (sec && sec.title) || "superset" });
      persist().then(paintSuperset);
    });
  }

  function paintEmom() {
    var items = (ctx.session.exercises || []).filter(function (e) { return e.section_format === "emom"; });
    if (!items.length) items = [currentExercise()];
    var minutes = (items[0].emom && items[0].emom.minutes) || 8;
    var steps = MTimer.emomSteps(items, minutes);
    var eng = new MTimer.Engine(steps, ctx.state.timer);
    function paint() {
      var step = steps[eng.i] || steps[0];
      var rem = Math.ceil(eng.stepRemaining() / 1000);
      ctx.root.innerHTML = '<div class="m-timer" data-kind="emom"><div class="m-kicker">MINUTE ' +
        (eng.i + 1) + " OF " + steps.length + '</div><div class="m-ring m-mono">' + rem +
        "</div><div>" + ((step.payload && step.payload.name) || "") +
        '</div><button type="button" class="m-primary" id="m-pause">Pause</button>' +
        '<button type="button" id="m-end-timer">End</button></div>';
      document.getElementById("m-pause").addEventListener("click", function () {
        if (eng.pausedAt) eng.resume(); else eng.pause();
        ctx.state.timer = eng.toJSON();
        persist();
      });
      document.getElementById("m-end-timer").addEventListener("click", nextExercise);
    }
    eng.onTick = function () { ctx.state.timer = eng.toJSON(); paint(); };
    eng.onStep = function (step, i) {
      ctx.state.results["emom:" + i] = { minute: i + 1, name: step.payload && step.payload.name };
      persist();
    };
    eng.start();
    paint();
  }

  function paintInterval() {
    var items = (ctx.session.exercises || []).filter(function (e) { return e.section_format === "interval"; });
    if (!items.length) items = [currentExercise()];
    var a = items[0];
    var n = (a.interval && a.interval.intervals) || 6;
    var work = (a.interval && a.interval.work_seconds) || 40;
    var rest = (a.interval && a.interval.rest_seconds) || 20;
    var steps = MTimer.intervalSteps(items, n, work, rest);
    var eng = new MTimer.Engine(steps, ctx.state.timer);
    function paint() {
      var step = steps[eng.i] || steps[0];
      var rem = Math.ceil(eng.stepRemaining() / 1000);
      ctx.root.innerHTML = '<div class="m-timer m-timer--' + step.kind + '" data-kind="interval"><div class="m-kicker">' +
        step.label + " · INTERVAL " + step.n + " OF " + n + '</div><div class="m-ring m-mono">' + rem +
        "</div><div>" + ((step.payload && step.payload.name) || "") +
        '</div><button type="button" class="m-primary" id="m-pause">Pause</button></div>';
      document.getElementById("m-pause").addEventListener("click", function () {
        eng.pausedAt ? eng.resume() : eng.pause();
        ctx.state.timer = eng.toJSON();
        persist();
      });
    }
    eng.onTick = function (rem, step, i) {
      paint();
      if (i === steps.length - 1 && rem <= 0) nextExercise();
    };
    eng.start();
    paint();
  }

  function paintHold() {
    var ex = currentExercise();
    var target = (ex.hold && ex.hold.target_seconds) || 45;
    var started = ctx.state.hold_started || Date.now();
    ctx.state.hold_started = started;
    persist();
    function paint() {
      var held = Math.round((Date.now() - started) / 1000);
      ctx.root.innerHTML = '<div class="m-timer" data-kind="hold"><div class="m-kicker">HOLD</div><div class="m-ring m-mono">' +
        held + 's</div><div>target ' + target + 's</div>' +
        '<button type="button" class="m-danger" id="m-stop">Stop · save</button></div>';
      document.getElementById("m-stop").addEventListener("click", function () {
        ctx.state.results[ex.name] = { held: held, target: target };
        ctx.state.hold_started = null;
        persist().then(nextExercise);
      });
    }
    paint();
    var t = setInterval(paint, 200);
    ctx._holdTick = t;
  }

  function loggedExercises() {
    var exercises = JSON.parse(JSON.stringify(ctx.session.exercises || []));
    exercises.forEach(function (ex) {
      var sets = plannedSets(ex);
      var out = [];
      sets.forEach(function (st, i) {
        var r = ctx.state.results[resultKey(ex, i)];
        out.push(r || st);
      });
      if (ctx.state.results[ex.name] && ctx.state.results[ex.name].held) {
        ex.hold_result = ctx.state.results[ex.name];
      }
      ex.sets = out;
      ex.rpe = ctx.state.rpe[ex.name];
    });
    return exercises;
  }

  function renderFinish() {
    ctx.state.screen = "finish";
    var exercises = loggedExercises();
    var est = (global.MTss && MTss.fromExercises(exercises)) || { tss: ctx.session.estimated_tss };
    var doneSets = Object.keys(ctx.state.results).length;
    var planned = (ctx.session.exercises || []).reduce(function (a, e) { return a + plannedSets(e).length; }, 0);
    var mins = Math.round((Date.now() - ctx.state.started_at) / 60000);
    var html = '<div class="m-kicker">SESSION DONE</div><h1>' + (ctx.session.name || "Strength") + "</h1>" +
      '<div class="m-finish-tiles"><div><span>Time</span><b class="m-mono">' + mins +
      ' min</b></div><div><span>Sets</span><b class="m-mono">' + doneSets + "/" + planned +
      '</b></div><div><span>TSS est.</span><b class="m-mono">' + (est.tss != null ? est.tss : "—") + "</b></div></div>" +
      '<div class="m-rpe">' + [6, 7, 8, 9, 10].map(function (n) {
        return '<button type="button" data-srpe="' + n + '"' + (ctx.state.session_rpe === n ? ' class="on"' : "") + ">" + n + "</button>";
      }).join("") + "</div>" +
      '<div class="m-card"><span class="m-kicker m-kicker--grey">CHANGED FROM THE PLAN</span>' +
      (ctx.state.edit_log.length ? ctx.state.edit_log.map(function (e) {
        return "<div>" + (e.type === "swap" ? (e.from + " → <b>" + e.to + "</b>") : e.type + " " + (e.exercise || "")) + "</div>";
      }).join("") : "<div class=\"m-muted\">No changes.</div>") +
      '<label class="m-check"><input type="checkbox" id="m-future" ' + (ctx.state.apply_to_future ? "checked" : "") +
      "> Use these in future sessions</label></div>" +
      '<div class="m-sync-bar">Saved on this phone · syncs when the server is up <button type="button" id="m-sync-now">Sync now</button></div>' +
      '<button type="button" class="m-primary" id="m-done">Done</button>';
    ctx.root.innerHTML = html;
    ctx.root.querySelectorAll("[data-srpe]").forEach(function (b) {
      b.addEventListener("click", function () {
        ctx.state.session_rpe = Number(b.getAttribute("data-srpe"));
        persist().then(renderFinish);
      });
    });
    document.getElementById("m-future").addEventListener("change", function (e) {
      ctx.state.apply_to_future = e.target.checked;
      persist();
    });
    function queue() {
      var op = MStore.newOp("session_log", {
        session_id: ctx.session.id,
        name: ctx.session.name,
        date: ctx.session.date,
        template_key: ctx.session.template_key || ctx.session.pattern_name || ctx.session.name,
        exercises: exercises,
        results: ctx.state.results,
        session_rpe: ctx.state.session_rpe,
        notes: ctx.state.notes,
        duration_seconds: Math.round((Date.now() - ctx.state.started_at) / 1000),
        apply_to_future: ctx.state.apply_to_future,
        edit_log: ctx.state.edit_log,
        tss_est: est.tss
      }, ctx.session.version_id);
      ctx.state.active = false;
      return Promise.all([
        MSync.enqueue(op),
        MStore.setSession(ctx.state),
        MStore.setMeta("session-active", false)
      ]);
    }
    document.getElementById("m-sync-now").addEventListener("click", function () {
      queue().then(function () { return MSync.flush(); });
    });
    document.getElementById("m-done").addEventListener("click", function () {
      queue().then(function () { location.href = "/m/today"; });
    });
  }

  function openSwap(ex) {
    if (!global.MGymSwap) return;
    MGymSwap.open(ctx.session, ctx.state, ctx.bundle, ex && ex.name, function (choice) {
      if (!choice || !choice.to) return;
      if (ex) {
        ctx.state.edit_log.push({
          type: "swap",
          from: ex.name,
          to: choice.to,
          exercise_key: (ex.name || "").toLowerCase(),
          exercise: ex.name
        });
        if (!choice.keep && choice.last_numbers) {
          ex.sets = plannedSets(ex).map(function (st) {
            return { kg: choice.last_numbers.kg != null ? choice.last_numbers.kg : st.kg, reps: choice.last_numbers.reps || st.reps };
          });
        }
        ex.name = choice.to;
      }
      persist().then(function () {
        if (ctx.state.screen === "overview") renderOverview();
        else paintPlay();
      });
    });
  }

  function tickElapsed() {
    var el = document.getElementById("m-elapsed");
    if (!el || !ctx.state.started_at) return;
    var s = Math.floor((Date.now() - ctx.state.started_at) / 1000);
    var m = Math.floor(s / 60);
    el.textContent = m + ":" + (s % 60 < 10 ? "0" : "") + (s % 60);
  }

  function mount() {
    ctx.root = document.getElementById("m-main");
    var id = sessionIdFromPath();
    MStore.getBundle().then(function (row) {
      ctx.bundle = (row && row.payload) || { sessions: [] };
      ctx.session = findSession(ctx.bundle, id);
      if (!ctx.session) {
        ctx.root.innerHTML = '<p class="m-card">Session is not on this phone. Pull to refresh when you are online.</p>';
        return;
      }
      return MStore.getSession().then(function (saved) {
        ctx.state = saved && saved.session_id === ctx.session.id ? saved : emptyState(ctx.session);
        ctx.state.active = true;
        persist().then(function () {
          if (ctx.state.screen === "finish") renderFinish();
          else if (ctx.state.screen === "play" || (saved && saved.position && saved.active)) paintPlay();
          else renderOverview();
        });
      });
    });
  }

  global.MGym = {
    mount: mount,
    persist: persist,
    emptyState: emptyState,
    findSession: findSession,
    sectionsOf: sectionsOf,
    plannedSets: plannedSets,
    sessionIdFromPath: sessionIdFromPath
  };
})(window);
