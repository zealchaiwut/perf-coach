/* Timestamp-based timer engine for EMOM, 40/20, and holds. */
(function (global) {
  "use strict";

  function now() { return Date.now(); }

  function Engine(steps, saved) {
    this.steps = steps || [];
    this.i = (saved && saved.i) || 0;
    this.startedAt = saved && saved.startedAt;
    this.pausedAt = saved && saved.pausedAt;
    this.pauseAccum = (saved && saved.pauseAccum) || 0;
    this.muted = !!(saved && saved.muted);
    this._tick = null;
    this.onStep = null;
    this.onTick = null;
  }

  Engine.prototype.toJSON = function () {
    return {
      i: this.i,
      startedAt: this.startedAt,
      pausedAt: this.pausedAt,
      pauseAccum: this.pauseAccum,
      muted: this.muted
    };
  };

  Engine.prototype.elapsed = function () {
    if (!this.startedAt) return 0;
    var end = this.pausedAt || now();
    return Math.max(0, end - this.startedAt - this.pauseAccum);
  };

  Engine.prototype.stepRemaining = function () {
    var acc = 0;
    for (var i = 0; i < this.steps.length; i++) {
      var dur = this.steps[i].seconds * 1000;
      if (i === this.i) return Math.max(0, dur - (this.elapsed() - acc));
      acc += dur;
    }
    return 0;
  };

  Engine.prototype.start = function () {
    if (!this.startedAt) this.startedAt = now();
    if (this.pausedAt) {
      this.pauseAccum += now() - this.pausedAt;
      this.pausedAt = null;
    }
    this._loop();
    this._wake();
  };

  Engine.prototype.pause = function () {
    if (!this.pausedAt) this.pausedAt = now();
    if (this._tick) cancelAnimationFrame(this._tick);
  };

  Engine.prototype.resume = function () { this.start(); };
  Engine.prototype.reset = function () {
    this.i = 0;
    this.startedAt = null;
    this.pausedAt = null;
    this.pauseAccum = 0;
  };
  Engine.prototype.skip = function () {
    this.i = Math.min(this.i + 1, this.steps.length);
    if (this.onStep) this.onStep(this.steps[this.i], this.i);
  };
  Engine.prototype.previous = function () {
    this.i = Math.max(this.i - 1, 0);
    if (this.onStep) this.onStep(this.steps[this.i], this.i);
  };

  Engine.prototype._loop = function () {
    var self = this;
    function frame() {
      if (self.pausedAt) return;
      var rem = self.stepRemaining();
      if (self.onTick) self.onTick(rem, self.steps[self.i], self.i);
      if (rem <= 3000 && rem > 2900) self._cue();
      if (rem <= 0 && self.i < self.steps.length - 1) {
        self.i += 1;
        if (self.onStep) self.onStep(self.steps[self.i], self.i);
      }
      self._tick = requestAnimationFrame(frame);
    }
    this._tick = requestAnimationFrame(frame);
  };

  Engine.prototype._cue = function () {
    if (this.muted) return;
    try {
      if (navigator.vibrate) navigator.vibrate(40);
      var ctx = new (window.AudioContext || window.webkitAudioContext)();
      var o = ctx.createOscillator();
      var g = ctx.createGain();
      o.frequency.value = 880;
      o.connect(g);
      g.connect(ctx.destination);
      o.start();
      o.stop(ctx.currentTime + 0.08);
    } catch (e) { /* ignore */ }
  };

  Engine.prototype._wake = function () {
    if (navigator.wakeLock && navigator.wakeLock.request) {
      navigator.wakeLock.request("screen").catch(function () {});
    }
  };

  function playEmom(root, session, state, persist) {
    var exercises = session.exercises || [];
    var minutes = 8;
    var steps = [];
    for (var m = 1; m <= minutes; m++) {
      var owner = exercises.filter(function (ex) {
        var rule = (ex.emom && ex.emom.minute_rule) || "every";
        if (rule === "every") return true;
        if (rule === "odd") return m % 2 === 1;
        return m % 2 === 0;
      })[0] || exercises[0];
      steps.push({ label: "Minute " + m, kind: "work", seconds: 60, payload: owner });
    }
    var eng = new Engine(steps, state.timer);
    function paint() {
      var step = steps[eng.i] || steps[0];
      var rem = Math.ceil(eng.stepRemaining() / 1000);
      root.innerHTML = '<div class="m-timer"><div class="m-kicker">MINUTE ' + (eng.i + 1) + " OF " + steps.length +
        '</div><div class="m-ring m-mono">' + rem + "</div><div>" + ((step.payload && step.payload.name) || "") +
        '</div><button type="button" class="m-primary" id="m-pause">Pause</button></div>';
      var p = document.getElementById("m-pause");
      if (p) p.addEventListener("click", function () {
        if (eng.pausedAt) eng.resume();
        else eng.pause();
        state.timer = eng.toJSON();
        persist(state);
      });
    }
    eng.onTick = function () { paint(); };
    eng.start();
    paint();
  }

  function playInterval(root, session, state, persist) {
    var items = (session.exercises || []).filter(function (e) { return e.section_format === "interval"; });
    var a = items[0] || session.exercises[0];
    var b = items[1] || items[0];
    var n = (a && a.interval && a.interval.intervals) || 6;
    var work = (a && a.interval && a.interval.work_seconds) || 40;
    var rest = (a && a.interval && a.interval.rest_seconds) || 20;
    var steps = [];
    for (var i = 0; i < n; i++) {
      steps.push({ label: "WORK", kind: "work", seconds: work, payload: i % 2 === 0 ? a : b, n: i + 1 });
      steps.push({ label: "REST", kind: "rest", seconds: rest, payload: null, n: i + 1 });
    }
    var eng = new Engine(steps, state.timer);
    function paint() {
      var step = steps[eng.i] || steps[0];
      var rem = Math.ceil(eng.stepRemaining() / 1000);
      root.innerHTML = '<div class="m-timer m-timer--' + step.kind + '"><div class="m-kicker">' + step.label +
        " · INTERVAL " + step.n + " OF " + n + '</div><div class="m-ring m-mono">' + rem + "</div><div>" +
        ((step.payload && step.payload.name) || "") + '</div><button type="button" class="m-primary" id="m-pause">Pause</button></div>';
      var p = document.getElementById("m-pause");
      if (p) p.addEventListener("click", function () { eng.pausedAt ? eng.resume() : eng.pause(); persist(state); });
    }
    eng.onTick = paint;
    eng.start();
    paint();
  }

  function playHold(root, session, state, persist) {
    var ex = (session.exercises || []).filter(function (e) { return e.section_format === "hold"; })[0] || session.exercises[0];
    var target = (ex.hold && ex.hold.target_seconds) || 45;
    var started = now();
    function paint() {
      var held = Math.round((now() - started) / 1000);
      root.innerHTML = '<div class="m-timer"><div class="m-kicker">HOLD</div><div class="m-ring m-mono">' + held +
        's</div><div>target ' + target + 's</div><button type="button" class="m-danger" id="m-stop">Stop · save</button></div>';
      document.getElementById("m-stop").addEventListener("click", function () {
        state.results[ex.name] = { held: held, target: target };
        persist(state);
        location.href = "/m/today";
      });
    }
    setInterval(paint, 200);
    paint();
  }

  global.MTimer = { Engine: Engine, playEmom: playEmom, playInterval: playInterval, playHold: playHold };
})(window);
