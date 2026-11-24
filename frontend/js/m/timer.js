/* Timestamp-based timer engine for EMOM, 40/20, and holds. */
(function (global) {
  "use strict";

  function Engine(steps, saved, clock) {
    this.steps = steps || [];
    this.clock = clock || function () { return Date.now(); };
    this.i = (saved && saved.i) || 0;
    this.startedAt = saved && saved.startedAt;
    this.pausedAt = saved && saved.pausedAt;
    this.pauseAccum = (saved && saved.pauseAccum) || 0;
    this.muted = !!(saved && saved.muted);
    this._cued = {};
    this._tick = null;
    this.onStep = null;
    this.onTick = null;
    this.onCue = null;
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

  Engine.prototype.now = function () { return this.clock(); };

  Engine.prototype.elapsed = function () {
    if (this.startedAt == null) return 0;
    var end = this.pausedAt || this.now();
    return Math.max(0, end - this.startedAt - this.pauseAccum);
  };

  Engine.prototype.stepRemaining = function () {
    var acc = 0;
    var elapsed = this.elapsed();
    for (var i = 0; i < this.steps.length; i++) {
      var dur = this.steps[i].seconds * 1000;
      if (i === this.i) return Math.max(0, dur - (elapsed - acc));
      acc += dur;
    }
    return 0;
  };

  Engine.prototype.start = function () {
    if (this.startedAt == null) this.startedAt = this.now();
    if (this.pausedAt) {
      this.pauseAccum += this.now() - this.pausedAt;
      this.pausedAt = null;
    }
    this._loop();
    this._wake();
  };

  Engine.prototype.pause = function () {
    if (!this.pausedAt) this.pausedAt = this.now();
  };

  Engine.prototype.resume = function () { this.start(); };

  Engine.prototype.reset = function () {
    this.i = 0;
    this.startedAt = null;
    this.pausedAt = null;
    this.pauseAccum = 0;
    this._cued = {};
  };

  Engine.prototype.skip = function () {
    this.i = Math.min(this.i + 1, this.steps.length);
    if (this.onStep) this.onStep(this.steps[this.i], this.i);
  };

  Engine.prototype.previous = function () {
    this.i = Math.max(this.i - 1, 0);
    if (this.onStep) this.onStep(this.steps[this.i], this.i);
  };

  Engine.prototype.tick = function () {
    if (this.pausedAt) return;
    var rem = this.stepRemaining();
    if (this.onTick) this.onTick(rem, this.steps[this.i], this.i);
    var cueKey = this.i + ":3";
    if (rem <= 3000 && rem > 0 && !this._cued[cueKey]) {
      this._cued[cueKey] = true;
      this._cue();
      if (this.onCue) this.onCue(this.i);
    }
    if (rem <= 0 && this.i < this.steps.length - 1) {
      this.i += 1;
      if (this.onStep) this.onStep(this.steps[this.i], this.i);
    }
  };

  Engine.prototype._loop = function () {
    var self = this;
    function frame() {
      self.tick();
      if (typeof requestAnimationFrame === "function") {
        self._tick = requestAnimationFrame(frame);
      }
    }
    frame();
  };

  Engine.prototype._cue = function () {
    if (this.muted) return;
    try {
      if (typeof navigator !== "undefined" && navigator.vibrate) navigator.vibrate(40);
      if (typeof AudioContext === "undefined" && typeof webkitAudioContext === "undefined") return;
      var Ctx = AudioContext || webkitAudioContext;
      var ctx = new Ctx();
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
    if (typeof navigator !== "undefined" && navigator.wakeLock && navigator.wakeLock.request) {
      navigator.wakeLock.request("screen").catch(function () {});
    }
  };

  function emomSteps(exercises, minutes) {
    minutes = minutes || 8;
    var steps = [];
    for (var m = 1; m <= minutes; m++) {
      var owner = (exercises || []).filter(function (ex) {
        var rule = (ex.emom && ex.emom.minute_rule) || "every";
        if (rule === "every") return true;
        if (rule === "odd") return m % 2 === 1;
        return m % 2 === 0;
      })[0] || (exercises || [])[0];
      steps.push({ label: "Minute " + m, kind: "work", seconds: 60, payload: owner, minute: m });
    }
    return steps;
  }

  function intervalSteps(items, n, work, rest) {
    n = n || 6;
    work = work || 40;
    rest = rest || 20;
    var steps = [];
    for (var i = 0; i < n; i++) {
      var ex = items[i % items.length];
      steps.push({ label: "WORK", kind: "work", seconds: work, payload: ex, n: i + 1 });
      steps.push({ label: "REST", kind: "rest", seconds: rest, payload: items[(i + 1) % items.length], n: i + 1 });
    }
    return steps;
  }

  global.MTimer = {
    Engine: Engine,
    emomSteps: emomSteps,
    intervalSteps: intervalSteps
  };
})(typeof window !== "undefined" ? window : globalThis);
