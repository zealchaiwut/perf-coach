/**
 * Run session screenshot picker — same modal as v1 training-log:
 * Theme (Dark | Light), Graph (With graph | No graph), Laps (Manual | 1 km).
 */
(function (global) {
  "use strict";

  var _busy = false;
  var _ctx = { workout: {}, full: null, toast: null };

  function notify(msg) {
    if (_ctx.toast) {
      _ctx.toast(msg);
      return;
    }
    if (global.RevampUI && global.RevampUI.showToast) {
      global.RevampUI.showToast(msg);
    }
  }

  function loadHtml2Canvas() {
    if (typeof global.html2canvas === "function") {
      return Promise.resolve(global.html2canvas);
    }
    if (global._html2canvasPromise) return global._html2canvasPromise;
    global._html2canvasPromise = new Promise(function (resolve, reject) {
      var s = document.createElement("script");
      s.src = "/js/lib/html2canvas.min.js";
      s.onload = function () {
        if (typeof global.html2canvas === "function") resolve(global.html2canvas);
        else reject(new Error("html2canvas missing"));
      };
      s.onerror = function () {
        reject(new Error("html2canvas failed"));
      };
      document.head.appendChild(s);
    });
    return global._html2canvasPromise;
  }

  function slugifyScreenshotName(name) {
    return (
      String(name || "workout")
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "")
        .slice(0, 60) || "workout"
    );
  }

  function screenshotFilename() {
    var w = _ctx.workout || {};
    var parts = [slugifyScreenshotName(w.name)];
    if (w.workout_date) parts.push(w.workout_date);
    return parts.join("-") + ".png";
  }

  function expandScreenshotOverflow(root) {
    var touched = [];
    if (!root) return touched;
    root.querySelectorAll("*").forEach(function (el) {
      var cs = window.getComputedStyle(el);
      var patch = {};
      if (
        cs.overflow === "auto" ||
        cs.overflow === "scroll" ||
        cs.overflow === "hidden"
      ) {
        patch.overflow = el.style.overflow;
        el.style.overflow = "visible";
      }
      if (cs.maxHeight && cs.maxHeight !== "none") {
        patch.maxHeight = el.style.maxHeight;
        el.style.maxHeight = "none";
      }
      if (Object.keys(patch).length) touched.push({ el: el, patch: patch });
    });
    return touched;
  }

  function restoreScreenshotOverflow(touched) {
    touched.forEach(function (item) {
      Object.keys(item.patch).forEach(function (key) {
        item.el.style[key] = item.patch[key];
      });
    });
  }

  function buildScreenshotClone(contentEl) {
    var stack = contentEl.querySelector(".rd4-stack");
    if (!stack) return contentEl.cloneNode(true);

    var out = document.createElement("div");
    out.className = "rd4-stack";

    var header = stack.querySelector(".rd4-header");
    if (header) out.appendChild(header.cloneNode(true));

    stack.querySelectorAll(".rd4-card").forEach(function (card) {
      if (
        card.classList.contains("rd4-header") ||
        card.classList.contains("rd4-laps-card")
      )
        return;
      var title = card.querySelector(".rd4-sec-title");
      if (!title) return;
      var label = title.textContent.replace(/\s+/g, " ").trim();
      if (/^load\s*&\s*intensity$/i.test(label)) {
        out.appendChild(card.cloneNode(true));
      }
    });

    var laps = stack.querySelector(".rd4-laps-card");
    if (laps) out.appendChild(laps.cloneNode(true));

    return out.childElementCount ? out : contentEl.cloneNode(true);
  }

  function applyScreenshotLapMode(contentEl, lapMode) {
    if (!contentEl || !lapMode) return;
    var toggle = contentEl.querySelector("#rd4-lapmode-toggle");
    if (!toggle) return;
    var target = toggle.querySelector(
      '.rd4-lm-btn[data-lap-mode="' + lapMode + '"]'
    );
    if (target && !target.classList.contains("rd4-lm-btn--on")) target.click();
  }

  function buildDetailCaptureRoot(contentEl, shotOpts) {
    shotOpts = shotOpts || {};
    applyScreenshotLapMode(contentEl, shotOpts.lapMode);
    var RD = global.RunDetailView;
    if (!RD) return buildScreenshotClone(contentEl);

    if (
      shotOpts.style === "simple" &&
      typeof RD.buildSimpleShareCard === "function"
    ) {
      var simple = RD.buildSimpleShareCard(contentEl, {
        workout: _ctx.workout || {},
        includeGraph: !!shotOpts.includeGraph,
      });
      if (simple) return simple;
    }

    if (typeof RD.buildShareCard === "function") {
      var share = RD.buildShareCard(contentEl, {
        workout: _ctx.workout || {},
        full: _ctx.full || null,
        lapSets: RD._lastLapSets || null,
        lapMode: shotOpts.lapMode || null,
        theme: shotOpts.theme === "light" ? "light" : "dark",
        includeGraph: !!shotOpts.includeGraph,
      });
      if (share) return share;
    }
    return buildScreenshotClone(contentEl);
  }

  /**
   * Single screenshot modal with live preview:
   *   Theme — Dark | Light
   *   Graph — With graph | No graph (pace/HR lap chart above the lap table)
   *   Laps  — Manual | 1 km (when both exist)
   * Resolves { style, theme, includeGraph, lapMode } or null if cancelled.
   */
  function promptScreenshotOptions(contentEl) {
    return new Promise(function (resolve) {
      var toggle = contentEl.querySelector("#rd4-lapmode-toggle");
      var hasLapChoice = !!(
        toggle && toggle.querySelectorAll(".rd4-lm-btn").length >= 2
      );

      var theme = "dark";
      var includeGraph = false;
      var lastLap = "manual";
      try {
        theme = localStorage.getItem("rd4_shot_theme") || "dark";
        if (theme !== "light") theme = "dark";
        if (localStorage.getItem("rd4_shot_graph") != null) {
          includeGraph = localStorage.getItem("rd4_shot_graph") !== "0";
        } else {
          var oldCard = localStorage.getItem("rd4_shot_card");
          includeGraph = oldCard === "simple_graph";
        }
        lastLap = localStorage.getItem("rd4_shot_lap") || "manual";
      } catch (e) {}

      var activeBtn =
        toggle &&
        (toggle.querySelector(".rd4-lm-btn--on") ||
          toggle.querySelector(".rd4-lm-btn"));
      var liveLap = activeBtn
        ? activeBtn.getAttribute("data-lap-mode")
        : "distance";
      if (lastLap !== "manual" && lastLap !== "distance")
        lastLap = liveLap || "manual";

      var lapMode = lastLap;

      var _shotModalReturnFocus = document.activeElement;
      function _restoreShotFocus() {
        var el = _shotModalReturnFocus;
        _shotModalReturnFocus = null;
        if (el && typeof el.focus === "function" && document.contains(el))
          el.focus();
      }

      var overlay = document.createElement("div");
      overlay.setAttribute("data-rd4-shot-modal", "1");
      overlay.style.cssText =
        "position:fixed;inset:0;background:rgba(0,0,0,0.4);z-index:9999;" +
        "display:flex;align-items:center;justify-content:center;padding:16px;" +
        "box-sizing:border-box;" +
        "--surface:#ffffff;--surface-2:#f9fafb;--text:#111827;--text-sub:#6b7280;" +
        "--border:#e5e7eb;--primary-dark:#2563eb;--ink:#0b1530;";

      var box = document.createElement("div");
      box.setAttribute("role", "dialog");
      box.setAttribute("aria-modal", "true");
      box.setAttribute("aria-label", "Screenshot options");
      box.style.cssText =
        "position:relative;background:var(--surface);border-radius:16px;padding:20px;max-width:760px;" +
        "width:100%;max-height:min(92vh,900px);overflow:auto;" +
        "box-shadow:0 12px 40px rgba(0,0,0,0.22);" +
        "display:grid;grid-template-columns:minmax(220px,260px) minmax(0,1fr);" +
        "gap:18px;align-items:start;font-family:'Inter Tight',system-ui,sans-serif;color:var(--text);";

      function closeModal() {
        if (!overlay.parentNode) return;
        document.body.removeChild(overlay);
        document.removeEventListener("keydown", onKey);
        _restoreShotFocus();
        resolve(null);
      }

      function onKey(e) {
        if (e.key === "Escape") {
          e.preventDefault();
          closeModal();
        }
      }

      var closeBtn = document.createElement("button");
      closeBtn.type = "button";
      closeBtn.setAttribute("aria-label", "Close");
      closeBtn.textContent = "✕";
      closeBtn.style.cssText =
        "position:absolute;top:10px;right:10px;z-index:2;" +
        "width:32px;height:32px;border:0;border-radius:8px;" +
        "background:transparent;color:var(--text-sub);cursor:pointer;" +
        "font-size:16px;line-height:1;display:flex;align-items:center;" +
        "justify-content:center;";
      closeBtn.addEventListener("mouseenter", function () {
        closeBtn.style.background = "var(--surface-2)";
        closeBtn.style.color = "var(--text)";
      });
      closeBtn.addEventListener("mouseleave", function () {
        closeBtn.style.background = "transparent";
        closeBtn.style.color = "var(--text-sub)";
      });
      closeBtn.addEventListener("click", function (e) {
        e.stopPropagation();
        closeModal();
      });
      box.appendChild(closeBtn);

      var controls = document.createElement("div");
      var previewCol = document.createElement("div");
      previewCol.style.cssText = "min-width:0;";

      function sectionTitle(text) {
        var p = document.createElement("p");
        p.textContent = text;
        p.style.cssText =
          "margin:0 0 10px;font-size:12px;font-weight:800;letter-spacing:.06em;" +
          "text-transform:uppercase;color:var(--text-sub);";
        return p;
      }

      function choiceBtn(group, label, value, getSel, setSel, onChange) {
        var b = document.createElement("button");
        b.type = "button";
        b.textContent = label;
        b.setAttribute("data-shot-group", group);
        b.setAttribute("data-shot-val", value);
        function paint() {
          var on = getSel() === value;
          var disabled = b.disabled;
          b.style.cssText =
            "display:block;width:100%;padding:11px;margin-bottom:8px;cursor:" +
            (disabled ? "default" : "pointer") +
            ";" +
            "border-radius:9px;font-size:14px;font-weight:600;" +
            "border:1.5px solid " +
            (on ? "var(--primary-dark)" : "var(--border)") +
            ";" +
            "background:" +
            (on ? "var(--primary-dark)" : "var(--surface)") +
            ";" +
            "color:" +
            (on ? "var(--surface)" : "var(--text)") +
            ";" +
            "opacity:" +
            (disabled ? "0.45" : "1") +
            ";";
        }
        paint();
        b._paint = paint;
        b.addEventListener("click", function () {
          if (b.disabled) return;
          setSel(value);
          Array.prototype.forEach.call(
            controls.querySelectorAll('[data-shot-group="' + group + '"]'),
            function (el) {
              el._paint && el._paint();
            }
          );
          if (onChange) onChange();
        });
        return b;
      }

      function cardNeedsLaps() {
        return true;
      }

      function applyLapModeIfNeeded() {
        if (!hasLapChoice || !cardNeedsLaps() || !toggle) return;
        var target = toggle.querySelector(
          '.rd4-lm-btn[data-lap-mode="' + lapMode + '"]'
        );
        if (target && !target.classList.contains("rd4-lm-btn--on"))
          target.click();
      }

      var previewLabel = sectionTitle("Preview");
      var previewStage = document.createElement("div");
      previewStage.className = "dp-shot-preview-stage";
      previewStage.style.cssText =
        "position:relative;border-radius:12px;overflow:hidden;" +
        "border:1px solid #e5e8ef;min-height:160px;" +
        "background-color:#f4f6fa;" +
        "background-image:linear-gradient(45deg,#e8ecf2 25%,transparent 25%)," +
        "linear-gradient(-45deg,#e8ecf2 25%,transparent 25%)," +
        "linear-gradient(45deg,transparent 75%,#e8ecf2 75%)," +
        "linear-gradient(-45deg,transparent 75%,#e8ecf2 75%);" +
        "background-size:16px 16px;" +
        "background-position:0 0,0 8px,8px -8px,-8px 0;";

      var previewHint = document.createElement("div");
      previewHint.style.cssText =
        "margin-top:8px;font-size:12px;color:var(--text-sub);font-weight:500;";
      previewHint.textContent = "Checkerboard shows transparency";

      function refreshPreview() {
        applyLapModeIfNeeded();
        previewStage.innerHTML =
          '<div style="padding:24px;text-align:center;color:var(--text-sub);font-size:13px;">Updating…</div>';
        requestAnimationFrame(function () {
          requestAnimationFrame(function () {
            var opts = {
              style: "full",
              theme: theme,
              includeGraph: includeGraph,
              lapMode: lapMode,
            };
            var node = buildDetailCaptureRoot(contentEl, opts);
            previewStage.innerHTML = "";
            if (!node) {
              previewStage.innerHTML =
                '<div style="padding:28px;text-align:center;color:var(--text-sub);font-size:13px;">Nothing to preview</div>';
              return;
            }

            var isSocial = node.classList.contains("rd4-social");
            var isSimple = node.classList.contains("rd4-simple");
            var naturalW = isSocial ? 1080 : isSimple ? 360 : 200;
            if (isSocial) node.style.width = "1080px";
            else node.style.width = "max-content";

            var scaleWrap = document.createElement("div");
            scaleWrap.style.cssText =
              "transform-origin:top left;will-change:transform;margin:8px;" +
              "display:inline-block;";
            scaleWrap.appendChild(node);
            previewStage.appendChild(scaleWrap);

            var measured =
              Math.ceil(node.offsetWidth) ||
              Math.ceil(node.getBoundingClientRect().width) ||
              naturalW;
            var measuredH =
              Math.ceil(node.offsetHeight) ||
              Math.ceil(node.getBoundingClientRect().height) ||
              200;

            if (isSimple) {
              previewStage.style.width = measured + 16 + "px";
              previewStage.style.maxWidth = "100%";
              previewStage.style.height = measuredH + 16 + "px";
              scaleWrap.style.transform = "none";
              scaleWrap.style.width = measured + "px";
            } else if (isSocial) {
              previewStage.style.width = "";
              previewStage.style.maxWidth = "100%";
              previewStage.style.backgroundColor =
                theme === "light" ? "#f4f6fa" : "#1a1a1a";
              var stageW = previewStage.clientWidth || 400;
              var scale = Math.min(1, (stageW - 16) / measured);
              scaleWrap.style.transform = "scale(" + scale + ")";
              scaleWrap.style.width = measured + "px";
              previewStage.style.height =
                Math.max(160, Math.ceil(measuredH * scale) + 16) + "px";
            } else {
              previewStage.style.width = "";
              previewStage.style.maxWidth = "";
              var stageW2 = previewStage.clientWidth || 400;
              var scale2 = Math.min(1, (stageW2 - 16) / measured);
              scaleWrap.style.transform = "scale(" + scale2 + ")";
              scaleWrap.style.width = measured + "px";
              previewStage.style.height =
                Math.max(120, Math.ceil(measuredH * scale2) + 16) + "px";
            }

            previewHint.style.display = "none";
          });
        });
      }

      function onOptionsChange() {
        syncLapSection();
        refreshPreview();
      }

      controls.appendChild(sectionTitle("Theme"));
      controls.appendChild(
        choiceBtn(
          "theme",
          "Dark",
          "dark",
          function () {
            return theme;
          },
          function (v) {
            theme = v;
          },
          onOptionsChange
        )
      );
      controls.appendChild(
        choiceBtn(
          "theme",
          "Light",
          "light",
          function () {
            return theme;
          },
          function (v) {
            theme = v;
          },
          onOptionsChange
        )
      );

      var graphWrap = document.createElement("div");
      graphWrap.style.cssText = "margin-top:8px;";
      graphWrap.appendChild(sectionTitle("Graph"));
      graphWrap.appendChild(
        choiceBtn(
          "graph",
          "With graph",
          "1",
          function () {
            return includeGraph ? "1" : "0";
          },
          function (v) {
            includeGraph = v === "1";
          },
          onOptionsChange
        )
      );
      graphWrap.appendChild(
        choiceBtn(
          "graph",
          "No graph",
          "0",
          function () {
            return includeGraph ? "1" : "0";
          },
          function (v) {
            includeGraph = v === "1";
          },
          onOptionsChange
        )
      );
      controls.appendChild(graphWrap);

      var lapsWrap = document.createElement("div");
      lapsWrap.style.cssText = "margin-top:8px;";
      lapsWrap.appendChild(sectionTitle("Laps"));
      var lapManual = choiceBtn(
        "lap",
        "Manual",
        "manual",
        function () {
          return lapMode;
        },
        function (v) {
          lapMode = v;
        },
        refreshPreview
      );
      var lapKm = choiceBtn(
        "lap",
        "1 km",
        "distance",
        function () {
          return lapMode;
        },
        function (v) {
          lapMode = v;
        },
        refreshPreview
      );
      lapsWrap.appendChild(lapManual);
      lapsWrap.appendChild(lapKm);
      controls.appendChild(lapsWrap);

      function syncLapSection() {
        var show = hasLapChoice;
        lapsWrap.style.display = show ? "" : "none";
        var need = cardNeedsLaps();
        [lapManual, lapKm].forEach(function (b) {
          b.disabled = !need;
          b._paint();
        });
        lapsWrap.style.opacity = need ? "1" : "0.55";
      }
      syncLapSection();

      var go = document.createElement("button");
      go.type = "button";
      go.textContent = "Save image";
      go.style.cssText =
        "display:block;width:100%;padding:12px;margin-top:14px;cursor:pointer;" +
        "border-radius:9px;font-size:14px;font-weight:700;border:0;" +
        "background:var(--ink);color:var(--surface);";
      go.addEventListener("click", function () {
        try {
          localStorage.setItem("rd4_shot_theme", theme);
          localStorage.setItem("rd4_shot_graph", includeGraph ? "1" : "0");
          localStorage.setItem("rd4_shot_lap", lapMode);
        } catch (e) {}
        applyLapModeIfNeeded();
        document.removeEventListener("keydown", onKey);
        document.body.removeChild(overlay);
        _restoreShotFocus();
        resolve({
          style: "full",
          theme: theme,
          includeGraph: includeGraph,
          lapMode: lapMode,
        });
      });
      controls.appendChild(go);

      previewCol.appendChild(previewLabel);
      previewCol.appendChild(previewStage);
      previewCol.appendChild(previewHint);

      box.appendChild(controls);
      box.appendChild(previewCol);

      var mq = window.matchMedia("(max-width: 640px)");
      function layoutModal() {
        if (mq.matches) {
          box.style.gridTemplateColumns = "1fr";
        } else {
          box.style.gridTemplateColumns = "minmax(220px,260px) minmax(0,1fr)";
        }
      }
      layoutModal();
      if (mq.addEventListener) mq.addEventListener("change", layoutModal);

      overlay.appendChild(box);
      overlay.addEventListener("click", function (e) {
        if (e.target === overlay) closeModal();
      });
      document.addEventListener("keydown", onKey);
      document.body.appendChild(overlay);
      closeBtn.focus();
      refreshPreview();
    });
  }

  function runCapture(contentEl, shotOpts) {
    return loadHtml2Canvas().then(function (h2c) {
      var clone = buildDetailCaptureRoot(contentEl, shotOpts);
      var isSocial = !!(
        clone &&
        clone.classList &&
        clone.classList.contains("rd4-social")
      );
      var isSimple = !!(
        clone &&
        clone.classList &&
        clone.classList.contains("rd4-simple")
      );
      var captureWidth = isSocial ? 1080 : isSimple ? 360 : 540;
      var bg = isSimple
        ? null
        : isSocial
          ? shotOpts.theme === "light"
            ? "#f8f6f1"
            : "#0a0a0a"
          : "#ffffff";

      var host = document.createElement("div");
      host.className =
        "dp-screenshot-capture" +
        (isSocial ? " dp-screenshot-capture--share" : "") +
        (isSimple ? " dp-screenshot-capture--simple" : "");
      host.setAttribute("aria-hidden", "true");
      host.style.cssText =
        "position:fixed;left:-10000px;top:0;width:" +
        (isSimple ? "max-content" : captureWidth + "px") +
        ";background:transparent;padding:0;box-sizing:border-box;pointer-events:none;";

      host.appendChild(clone);
      document.body.appendChild(host);

      if (isSimple) {
        var fitted = Math.ceil(clone.getBoundingClientRect().width);
        if (fitted > 40) {
          captureWidth = fitted + 4;
          host.style.width = captureWidth + "px";
        }
      }

      var overflowPatches = expandScreenshotOverflow(clone);

      return h2c(host, {
        backgroundColor: bg,
        scale: 2,
        logging: false,
        useCORS: true,
        width: captureWidth,
        windowWidth: captureWidth,
      })
        .then(function (canvas) {
          return new Promise(function (resolve, reject) {
            canvas.toBlob(function (blob) {
              if (!blob) {
                reject(new Error("empty blob"));
                return;
              }
              resolve(blob);
            }, "image/png");
          });
        })
        .then(function (blob) {
          var url = URL.createObjectURL(blob);
          var link = document.createElement("a");
          link.href = url;
          link.download = screenshotFilename();
          document.body.appendChild(link);
          link.click();
          link.remove();
          URL.revokeObjectURL(url);
          notify("Workout saved as image");
        })
        .finally(function () {
          restoreScreenshotOverflow(overflowPatches);
          if (host.parentNode) host.parentNode.removeChild(host);
        });
    });
  }

  function capture(contentEl, opts) {
    opts = opts || {};
    if (_busy) return;
    if (!contentEl || !contentEl.querySelector(".rd4-stack")) {
      notify("Nothing to capture yet.");
      return;
    }
    _busy = true;
    _ctx.workout = opts.workout || {};
    _ctx.full = opts.full || null;
    _ctx.toast = opts.toast || null;

    promptScreenshotOptions(contentEl)
      .then(function (shotOpts) {
        if (!shotOpts) {
          _busy = false;
          return;
        }
        requestAnimationFrame(function () {
          requestAnimationFrame(function () {
            runCapture(contentEl, shotOpts)
              .catch(function (err) {
                console.error("detail screenshot failed", err);
                notify("Could not save image. Try again.");
              })
              .finally(function () {
                _busy = false;
              });
          });
        });
      })
      .catch(function () {
        _busy = false;
      });
  }

  global.RunScreenshot = { capture: capture };
})(window);
