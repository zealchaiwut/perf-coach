/**
 * Shared CTL / ATL / TSB / ACWR readiness tiles (Training Log + Home).
 * One design: number + label + band + status. ACWR fills async via daily-load.
 */
(function (win) {
  "use strict";

  var ACWR_LOWER = 0.8;
  var ACWR_HIGH = 1.5;
  var ACWR_MIN_DAYS = 28;

  var BAND = {
    ctl: "linear-gradient(90deg,#fbbf24,#60a5fa,#22c55e)",
    atl: "linear-gradient(90deg,#22c55e,#eab308,#ef4444)",
    tsb: "linear-gradient(90deg,#f59e0b,#22c55e,#60a5fa)",
  };

  // Plain-language definitions, grounded in docs/calculations/training-load.md
  // and docs/calculations/acwr-guardrail.md — do not drift from the formulas
  // documented there without updating both.
  var METRIC_TIPS = {
    ctl:
      "Chronic Training Load (fitness): a slow, 42-day rolling average of " +
      "your daily training stress (TSS). It moves gradually, reflecting " +
      "fitness you've built up over weeks — not any single workout.",
    atl:
      "Acute Training Load (fatigue): a fast, 7-day rolling average of " +
      "your daily training stress (TSS). It reacts quickly to what you've " +
      "trained in just the last week.",
    tsb:
      "Training Stress Balance (freshness/form): today's CTL minus ATL. " +
      "Positive means you're fresher than your recent training would " +
      "suggest; very negative means fatigue has outpaced fitness " +
      "(overreached).",
    acwr:
      "Acute:Chronic Workload Ratio: the last 7 days' training load " +
      "divided by your average load over the 4 weeks before that. Flags " +
      "when load is ramping up faster than your body has adapted to — " +
      "a load-management signal, not a medical diagnosis. Below 0.8 = " +
      "detraining, above 1.5 = high risk.",
  };

  var _tipSeq = 0;

  // Builds a self-contained "i" affordance: a focusable/hoverable button
  // holding its own tooltip bubble (see .info-tip in styles.css). alignRight
  // nudges the bubble so it doesn't clip off the right edge of a 2-col grid.
  function infoTip(metric, alignRight) {
    var text = METRIC_TIPS[metric];
    if (!text) return "";
    var id = "info-tip-" + metric + "-" + _tipSeq++;
    return (
      '<button type="button" class="info-tip' +
      (alignRight ? " info-tip--right" : "") +
      '" aria-label="' +
      esc("What is " + metric.toUpperCase() + "?") +
      '" aria-describedby="' +
      id +
      '">i<span class="info-tip-bubble" role="tooltip" id="' +
      id +
      '">' +
      esc(text) +
      "</span></button>"
    );
  }

  var ACWR_STATUS_META = {
    detraining: { word: "DETRAINING", color: "var(--lrx-amber)" },
    productive: { word: "PRODUCTIVE", color: "var(--lrx-green)" },
    high_risk: { word: "HIGH RISK", color: "var(--lrx-red)" },
    baseline_forming: { word: "BUILDING", color: "var(--lrx-muted)" },
  };

  // Delegates to the shared escaper (issue #1603). The local copies
  // disagreed about the apostrophe, so identical content was safe on
  // some pages and attribute-injectable on others.
  function esc(s) {
    return window.AppCommon.escapeHtml(s);
  }

  function fmtLoadNum(v) {
    if (v === null || v === undefined || isNaN(v)) return "—";
    return String(Math.round(v * 10) / 10);
  }

  function readStatus(metric, v) {
    if (metric === "ctl") {
      if (v < 20) return { word: "DETRAINING", color: "var(--lrx-amber)" };
      if (v < 40) return { word: "STEADY", color: "var(--lrx-lavHi)" };
      return { word: "STRONG", color: "var(--lrx-green)" };
    }
    if (metric === "atl") {
      if (v < 25) return { word: "LOW", color: "var(--lrx-green)" };
      if (v < 45) return { word: "MODERATE", color: "var(--lrx-lavHi)" };
      return { word: "HIGH", color: "var(--lrx-amber)" };
    }
    if (v < -10) return { word: "OVERREACHED", color: "var(--lrx-amber)" };
    if (v <= 5) return { word: "OPTIMAL", color: "var(--lrx-green)" };
    return { word: "FRESH", color: "var(--lrx-run, #4f6ef7)" };
  }

  function markerPct(metric, v) {
    var min = metric === "tsb" ? -25 : 0;
    var max = metric === "tsb" ? 15 : 60;
    var pct = ((v - min) / (max - min)) * 100;
    return Math.max(2, Math.min(98, pct));
  }

  function rcard(metric, val, abbr, label) {
    var st = readStatus(metric, val);
    var pct = markerPct(metric, val);
    // Right column of the 2×2 grid (ATL) would clip the bubble off-screen
    // if centered — see buildGridHtml's fixed CTL/ATL/TSB/ACWR order.
    var alignRight = metric === "atl";
    return (
      '<div class="lrx-rcard">' +
      '<div class="rv">' +
      esc(fmtLoadNum(val)) +
      "</div>" +
      '<div class="rl">' +
      abbr +
      " · " +
      label +
      infoTip(metric, alignRight) +
      "</div>" +
      '<div class="lrx-rband" style="background:' +
      BAND[metric] +
      '">' +
      '<div class="mk" style="left:' +
      pct.toFixed(0) +
      '%"></div></div>' +
      '<div class="lrx-rstatus" style="color:' +
      st.color +
      '">' +
      st.word +
      "</div>" +
      "</div>"
    );
  }

  function acwrTileHtml() {
    return (
      '<div class="lrx-rcard" id="acwr-tile">' +
      '<div class="rv" id="acwr-ratio">–</div>' +
      '<div class="rl">ACWR · Load ratio' +
      infoTip("acwr", true) +
      "</div>" +
      '<div class="lrx-rband perf-acwr-rband" id="acwr-band">' +
      '<div class="mk" id="acwr-marker" style="left:50%"></div>' +
      "</div>" +
      '<div class="lrx-rstatus" id="acwr-status">–</div>' +
      "</div>"
    );
  }

  /**
   * Inner 2×2 grid only (CTL/ATL/TSB/ACWR). Caller wraps with page chrome.
   * data: /api/readiness payload (ctl, atl, tsb, building_baseline).
   */
  function buildGridHtml(data) {
    if (!data) return "";
    if (data.building_baseline) {
      return (
        '<p class="lrx-load-baseline">Building baseline — log more workouts to unlock Fitness, Fatigue, Freshness, and ACWR.</p>'
      );
    }
    return (
      '<div class="lrx-readfull">' +
      rcard("ctl", data.ctl, "CTL", "Fitness") +
      rcard("atl", data.atl, "ATL", "Fatigue") +
      rcard("tsb", data.tsb, "TSB", "Freshness") +
      acwrTileHtml() +
      "</div>"
    );
  }

  function acwrRatioAt(series, idx) {
    if (idx < ACWR_MIN_DAYS - 1) return null;
    var acute = 0;
    for (var i = idx - 6; i <= idx; i++) acute += series[i] || 0;
    var priorTotals = [];
    [
      [idx - 34, idx - 28],
      [idx - 27, idx - 21],
      [idx - 20, idx - 14],
      [idx - 13, idx - 7],
    ].forEach(function (w) {
      var lo = Math.max(0, w[0]),
        hi = w[1];
      if (hi < lo) return;
      var tot = 0;
      for (var j = lo; j <= hi; j++) tot += series[j] || 0;
      priorTotals.push(tot);
    });
    var chronic = priorTotals.length
      ? priorTotals.reduce(function (a, b) {
          return a + b;
        }, 0) / priorTotals.length
      : 0;
    return chronic ? acute / chronic : null;
  }

  function acwrBandFor(ratio) {
    return ratio < ACWR_LOWER
      ? "detraining"
      : ratio > ACWR_HIGH
        ? "high_risk"
        : "productive";
  }

  function computeAcwr(series) {
    if (series.length < ACWR_MIN_DAYS)
      return { ratio: null, band: "baseline_forming" };
    var ratio = acwrRatioAt(series, series.length - 1);
    if (ratio === null) return { ratio: null, band: null };
    return { ratio: ratio, band: acwrBandFor(ratio) };
  }

  function fillAcwrTile(acwr, root) {
    root = root || document;
    var ratioEl = root.querySelector
      ? root.querySelector("#acwr-ratio")
      : document.getElementById("acwr-ratio");
    var statusEl = root.querySelector
      ? root.querySelector("#acwr-status")
      : document.getElementById("acwr-status");
    var markerEl = root.querySelector
      ? root.querySelector("#acwr-marker")
      : document.getElementById("acwr-marker");
    if (!ratioEl) return;

    if (acwr.band === "baseline_forming" || acwr.ratio === null) {
      ratioEl.textContent = "–";
      var bf = ACWR_STATUS_META.baseline_forming;
      if (statusEl) {
        statusEl.textContent = bf.word;
        statusEl.style.color = bf.color;
      }
      if (markerEl) markerEl.style.visibility = "hidden";
      return;
    }
    ratioEl.textContent = acwr.ratio.toFixed(2);
    var meta = ACWR_STATUS_META[acwr.band] || {
      word: "—",
      color: "var(--lrx-muted)",
    };
    if (statusEl) {
      statusEl.textContent = meta.word;
      statusEl.style.color = meta.color;
    }
    if (markerEl) {
      markerEl.style.visibility = "";
      var pct = Math.max(2, Math.min(98, (acwr.ratio / 2.0) * 100));
      markerEl.style.left = pct.toFixed(1) + "%";
    }
  }

  function resolveAthleteId(cb) {
    var uid = win.getCurrentUserId ? win.getCurrentUserId() : null;
    if (uid) {
      cb(uid);
      return;
    }
    win.addEventListener(
      "userReady",
      function (e) {
        cb(e.detail.userId);
      },
      { once: true },
    );
  }

  function loadAcwrTile(root) {
    root = root || document;
    var ratioEl = root.querySelector
      ? root.querySelector("#acwr-ratio")
      : document.getElementById("acwr-ratio");
    if (!ratioEl) return;
    resolveAthleteId(function (athleteId) {
      var today = new Date().toLocaleDateString("en-CA");
      var start = window.AppCommon.nowBangkok();
      start.setDate(start.getDate() - 35);
      var startDate = start.toLocaleDateString("en-CA");
      fetch(
        "/api/athletes/" +
          athleteId +
          "/daily-load?start_date=" +
          startDate +
          "&end_date=" +
          today,
      )
        .then(function (r) {
          return r.ok ? r.json() : Promise.reject(r.status);
        })
        .then(function (data) {
          var series = Array.isArray(data)
            ? data.map(function (d) {
                return d.daily_load || 0;
              })
            : [];
          fillAcwrTile(computeAcwr(series), root);
        })
        .catch(function () {
          fillAcwrTile({ ratio: null, band: null }, root);
        });
    });
  }

  win.LoadReadinessTiles = {
    ACWR_LOWER: ACWR_LOWER,
    ACWR_HIGH: ACWR_HIGH,
    ACWR_MIN_DAYS: ACWR_MIN_DAYS,
    ACWR_STATUS_META: ACWR_STATUS_META,
    BAND: BAND,
    METRIC_TIPS: METRIC_TIPS,
    infoTip: infoTip,
    esc: esc,
    fmtLoadNum: fmtLoadNum,
    readStatus: readStatus,
    markerPct: markerPct,
    rcard: rcard,
    acwrTileHtml: acwrTileHtml,
    buildGridHtml: buildGridHtml,
    acwrRatioAt: acwrRatioAt,
    acwrBandFor: acwrBandFor,
    computeAcwr: computeAcwr,
    fillAcwrTile: fillAcwrTile,
    loadAcwrTile: loadAcwrTile,
  };
})(window);
