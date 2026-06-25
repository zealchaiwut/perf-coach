/* Habit-wheel theme-2 effects engine (issue: wheel re-theme + animation).
   Themed renderer (chunky rounded 7-segment stroke arcs), center countdown,
   check-in pop/burst/confetti, and the all-streak fire. Used by the Habits
   hero only — the shared wheel-helpers.js (home widget) is left untouched.
   Exposed as window.HabitWheelFx. All animation respects reduced-motion. */
(function (win) {
  'use strict';

  var SEGMENTS = 7;
  var R = 78, CX = 100, CY = 100;
  var GAP_DEG = 8;
  var SLOT = 360 / SEGMENTS;
  var SPAN = SLOT - GAP_DEG;
  var NS = 'http://www.w3.org/2000/svg';

  var STATE_CLASS = {
    full: 'hw2-seg-done',
    done: 'hw2-seg-done',
    partial: 'hw2-seg-partial',
    today: 'hw2-seg-today',
    today_pending: 'hw2-seg-today',
    zero: 'hw2-seg-upcoming',
    future: 'hw2-seg-upcoming',
  };

  function reduceMotion() {
    return win.matchMedia && win.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function polar(r, deg) {
    var rad = (deg - 90) * Math.PI / 180;
    return { x: CX + r * Math.cos(rad), y: CY + r * Math.sin(rad) };
  }
  function arc(deg0, deg1) {
    var s = polar(R, deg0), e = polar(R, deg1);
    var large = (deg1 - deg0) > 180 ? 1 : 0;
    return 'M ' + s.x.toFixed(2) + ' ' + s.y.toFixed(2) +
           ' A ' + R + ' ' + R + ' 0 ' + large + ' 1 ' + e.x.toFixed(2) + ' ' + e.y.toFixed(2);
  }
  function segStart(i) { return -90 + i * SLOT + GAP_DEG / 2; }

  /* Draw the themed wheel into an existing <svg> (viewBox 0 0 200 200). */
  function renderThemedWheel(svgEl, wheel) {
    if (!svgEl) return;
    while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);
    (wheel || []).forEach(function (seg, i) {
      var start = segStart(i);
      var p = document.createElementNS(NS, 'path');
      p.setAttribute('d', arc(start, start + SPAN));
      p.setAttribute('class', 'hw2-seg ' + (STATE_CLASS[seg.state] || 'hw2-seg-upcoming'));
      p.setAttribute('data-index', String(i));
      svgEl.appendChild(p);
    });
  }

  /* Center content. opts: { mode:'countdown'|'weekly', remaining, pct } */
  function renderCenter(centerEl, opts) {
    if (!centerEl) return;
    opts = opts || {};
    var isDone = opts.mode === 'countdown' && opts.remaining === 0;
    centerEl.classList.toggle('is-done', isDone);
    if (opts.mode === 'weekly') {
      centerEl.innerHTML =
        '<span class="hw2-center-num">' + (opts.pct != null ? Math.round(opts.pct) + '%' : '—') + '</span>' +
        '<span class="hw2-center-sub">this week</span>';
    } else if (isDone) {
      centerEl.innerHTML =
        '<svg class="hw2-center-check" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
        'stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
        '<path d="M5 13l4 4L19 7"/></svg>' +
        '<span class="hw2-center-sub">all done</span>';
    } else {
      centerEl.innerHTML =
        '<span class="hw2-center-num">' + Math.max(0, opts.remaining || 0) + '</span>' +
        '<span class="hw2-center-sub">more today</span>';
    }
  }

  /* Check-in celebration. opts: { wrap, svg, center, fx, segIndex } */
  function playCheckIn(opts) {
    opts = opts || {};
    var center = opts.center, svg = opts.svg, fx = opts.fx;
    if (center) {
      center.classList.remove('tick'); void center.offsetWidth; center.classList.add('tick');
      center.addEventListener('animationend', function () { center.classList.remove('tick'); }, { once: true });
    }
    if (reduceMotion()) return;

    if (svg && opts.segIndex != null) {
      var seg = svg.querySelector('[data-index="' + opts.segIndex + '"]');
      if (seg) {
        seg.classList.remove('pop'); void seg.getBBox(); seg.classList.add('pop');
        seg.addEventListener('animationend', function () { seg.classList.remove('pop'); }, { once: true });
      }
    }
    if (!fx) return;

    var idx = opts.segIndex != null ? opts.segIndex : 0;
    var mid = -90 + idx * SLOT + SLOT / 2;
    var pt = polar(R, mid);
    var leftPct = (pt.x / 200) * 100, topPct = (pt.y / 200) * 100;

    var burst = document.createElement('div');
    burst.className = 'hw2-burst go';
    burst.style.left = leftPct + '%'; burst.style.top = topPct + '%';
    fx.appendChild(burst);
    burst.addEventListener('animationend', function () { burst.remove(); }, { once: true });

    var COLORS = ['#16a34a', '#3563d4', '#d97706', '#fbbf24'];
    var N = 7;
    for (var i = 0; i < N; i++) {
      var f = document.createElement('div');
      f.className = 'hw2-confetti go';
      f.style.left = leftPct + '%'; f.style.top = topPct + '%';
      f.style.background = COLORS[i % COLORS.length];
      var ang = (i / N) * Math.PI * 2;
      f.style.setProperty('--cx', (Math.cos(ang) * (26 + Math.random() * 22)).toFixed(0) + 'px');
      f.style.setProperty('--cy', (Math.sin(ang) * (26 + Math.random() * 22) - 10).toFixed(0) + 'px');
      f.style.setProperty('--cr', (Math.random() * 360).toFixed(0) + 'deg');
      fx.appendChild(f);
      f.addEventListener('animationend', function () { this.remove(); }, { once: true });
    }
  }

  /* Build flame + capped embers inside the fire layer (once). */
  function buildFire(fireEl) {
    if (!fireEl || fireEl.dataset.built === '1') return;
    fireEl.dataset.built = '1';
    fireEl.innerHTML =
      '<div class="hw2-flame"></div><div class="hw2-flame f2"></div><div class="hw2-flame f3"></div>';
    if (reduceMotion()) return;          // calm fire: flames only, no embers
    var EMBERS = 7;
    for (var i = 0; i < EMBERS; i++) {
      var e = document.createElement('div');
      e.className = 'hw2-ember';
      e.style.left = (24 + Math.random() * 52) + '%';
      e.style.setProperty('--dx', (Math.random() * 40 - 20).toFixed(0) + 'px');
      e.style.setProperty('--dur', (2 + Math.random() * 1.6).toFixed(2) + 's');
      e.style.setProperty('--delay', (Math.random() * 2.2).toFixed(2) + 's');
      fireEl.appendChild(e);
    }
  }

  /* Toggle the all-streak fire. opts: { card, fire, badge, streakLen } */
  function setFire(on, opts) {
    opts = opts || {};
    if (on && opts.fire) buildFire(opts.fire);
    if (opts.card) opts.card.classList.toggle('is-lit', !!on);
    if (on && opts.badge && opts.streakLen != null) {
      var s = opts.badge.querySelector('[data-streak]');
      if (s) s.textContent = opts.streakLen;
    }
  }

  win.HabitWheelFx = {
    SEGMENTS: SEGMENTS,
    renderThemedWheel: renderThemedWheel,
    renderCenter: renderCenter,
    playCheckIn: playCheckIn,
    setFire: setFire,
    reduceMotion: reduceMotion,
  };
})(window);
