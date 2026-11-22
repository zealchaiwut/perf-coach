(function () {
  "use strict";

  var GROUPS = [
    "warmup", "heavy_compound", "superset", "standalone", "accessories",
    "cooldown", "bodyweight", "plyo", "isometric", "emom", "stretch",
  ];
  var FOCUS = ["lower", "upper", "full", "core"];

  var _all = [];
  var _selectedId = null;
  var _bodyPartKeys = [];
  var _importReady = null;

  function esc(s) {
    return window.AppCommon ? window.AppCommon.escapeHtml(s) : String(s);
  }

  function csrfToken() {
    var m = document.cookie.match(/(?:^|;\s*)csrf-token=([^;]*)/);
    if (m) return Promise.resolve(decodeURIComponent(m[1]));
    return fetch("/api/csrf-token", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : {}; })
      .then(function (b) { return (b && b.csrf_token) || ""; });
  }

  function api(path, opts) {
    opts = opts || {};
    var method = (opts.method || "GET").toUpperCase();
    var headers = Object.assign({ Accept: "application/json" }, opts.headers || {});
    var run = function (token) {
      if (token && method !== "GET" && method !== "HEAD") {
        headers["X-CSRF-Token"] = token;
      }
      return fetch(path, Object.assign({}, opts, { headers: headers, credentials: "same-origin" }))
        .then(function (r) {
          if (r.status === 204) return { ok: r.ok, status: r.status, data: null };
          return r.json().then(function (d) {
            return { ok: r.ok, status: r.status, data: d };
          }).catch(function () {
            return { ok: r.ok, status: r.status, data: null };
          });
        });
    };
    if (method === "GET" || method === "HEAD") return run("");
    return csrfToken().then(run);
  }

  function normalizeBodyPart(raw) {
    var key = String(raw || "").trim().toLowerCase().replace(/-/g, "_");
    if (!key) return null;
    var aliases = {
      quads: "quad", glutes: "glute", hamstrings: "hamstring", calves: "calf",
      hips: "hip", shoulders: "shoulder", obliques: "oblique", abs: "core",
    };
    return aliases[key] || key.replace(/ /g, "_");
  }

  function normalizeBodyPartsList(parts) {
    if (!Array.isArray(parts) || !parts.length) return null;
    var merged = {};
    for (var i = 0; i < parts.length; i++) {
      var p = parts[i];
      if (!p || typeof p !== "object") return null;
      var canon = normalizeBodyPart(p.part);
      var ratio = Number(p.ratio);
      if (!canon || !isFinite(ratio) || ratio <= 0) return null;
      merged[canon] = (merged[canon] || 0) + ratio;
    }
    return Object.keys(merged).map(function (k) {
      return { part: k, ratio: Math.round(merged[k] * 10000) / 10000 };
    });
  }

  function validateExerciseDraft(obj) {
    var checks = [];
    function add(ok, label) { checks.push({ ok: !!ok, label: label }); }

    if (!obj || typeof obj !== "object" || Array.isArray(obj)) {
      add(false, "Root must be one exercise object");
      return { ok: false, checks: checks, body: null };
    }

    var name = typeof obj.name === "string" ? obj.name.trim() : "";
    add(!!name, "name — non-empty string");

    var groups = Array.isArray(obj.groups) ? obj.groups : null;
    var groupsOk = !!groups && groups.length > 0 && groups.every(function (g) {
      return typeof g === "string" && GROUPS.indexOf(g) !== -1;
    });
    add(groupsOk, "groups — each in allowed enum");

    var focus = Array.isArray(obj.focus_tags) ? obj.focus_tags : null;
    var focusOk = !!focus && focus.length > 0 && focus.every(function (f) {
      return typeof f === "string" && FOCUS.indexOf(f) !== -1;
    });
    add(focusOk, "focus_tags — each in lower, upper, full, core");

    var parts = Array.isArray(obj.body_parts) ? normalizeBodyPartsList(obj.body_parts) : null;
    var partSum = 0;
    if (parts) parts.forEach(function (p) { partSum += Number(p.ratio); });
    add(!!parts && parts.length > 0, "body_parts — known parts, ratio > 0");
    add(!!parts && Math.abs(partSum - 1) <= 0.05, "body_parts ratios sum ≈ 1.0");

    var sets = Number(obj.default_sets);
    add(isFinite(sets) && sets >= 1 && sets <= 12, "default_sets — integer 1–12");

    var reps = typeof obj.default_reps === "string" ? obj.default_reps.trim() : "";
    add(!!reps, "default_reps — non-empty");

    var load = typeof obj.default_load === "string" ? obj.default_load.trim() : "";
    add(!!load, "default_load — non-empty");

    var tw = Number(obj.tss_weight);
    add(isFinite(tw) && tw > 0 && tw <= 3, "tss_weight — 0 < n ≤ 3");

    var active = obj.active === undefined ? true : obj.active;
    add(typeof active === "boolean", "active — boolean");

    var ok = checks.every(function (c) { return c.ok; });
    var body = ok ? {
      name: name,
      groups: groups.slice(),
      focus_tags: focus.slice(),
      body_parts: parts.map(function (p) {
        return { part: p.part, ratio: Math.round(Number(p.ratio) * 100) / 100 };
      }),
      tss_weight: tw,
      default_sets: sets,
      default_reps: reps,
      default_load: load,
      active: active,
    } : null;
    return { ok: ok, checks: checks, body: body };
  }

  function readEditorPayload() {
    var groups = [];
    document.querySelectorAll("#ed-groups .rv-chip.is-on").forEach(function (el) {
      groups.push(el.getAttribute("data-val"));
    });
    var focus = [];
    document.querySelectorAll("#ed-focus .rv-chip.is-on").forEach(function (el) {
      focus.push(el.getAttribute("data-val"));
    });
    var parts = [];
    document.querySelectorAll("#ed-parts .rv-part-row").forEach(function (row) {
      var part = row.querySelector(".rv-part-key");
      var pct = row.querySelector(".rv-part-pct");
      if (!part || !pct) return;
      var ratio = Number(pct.value) / 100;
      if (part.value && isFinite(ratio) && ratio > 0) {
        parts.push({ part: part.value, ratio: ratio });
      }
    });
    return validateExerciseDraft({
      name: document.getElementById("ed-name").value,
      groups: groups,
      focus_tags: focus,
      body_parts: parts,
      default_sets: document.getElementById("ed-sets").value,
      default_reps: document.getElementById("ed-reps").value,
      default_load: document.getElementById("ed-load").value,
      tss_weight: document.getElementById("ed-tss").value,
      active: true,
    });
  }

  function renderValidation(v) {
    var el = document.getElementById("ed-validation");
    var save = document.getElementById("btn-save");
    if (!v.ok) {
      var bad = (v.checks || []).filter(function (c) { return !c.ok; }).map(function (c) { return c.label; });
      el.textContent = bad.join(" · ");
      el.className = "rv-admin-validation rv-admin-validation--err";
      save.disabled = true;
      return;
    }
    el.textContent = "Ready to save";
    el.className = "rv-admin-validation rv-admin-validation--ok";
    save.disabled = false;
  }

  function renderPartSum() {
    var sum = 0;
    document.querySelectorAll("#ed-parts .rv-part-pct").forEach(function (inp) {
      sum += Number(inp.value) || 0;
    });
    var el = document.getElementById("ed-parts-sum");
    el.textContent = "Sum: " + sum.toFixed(0) + "%";
    el.classList.toggle("rv-admin-validation--err", Math.abs(sum - 100) > 5);
  }

  function formatBodyParts(parts) {
    if (!parts || !parts.length) return "—";
    return parts.map(function (p) {
      var pct = Math.round(Number(p.ratio) * 100);
      return esc(p.part) + " " + pct;
    }).join(" · ");
  }

  function formatDefault(e) {
    if (!e.default_sets && !e.default_reps) return "—";
    return esc(String(e.default_sets || "")) + " × " + esc(String(e.default_reps || ""));
  }

  function filteredExercises() {
    var q = (document.getElementById("filter-search").value || "").trim().toLowerCase();
    var g = document.getElementById("filter-group").value;
    var f = document.getElementById("filter-focus").value;
    return _all.filter(function (e) {
      if (g && (e.groups || []).indexOf(g) < 0) return false;
      if (f && (e.focus_tags || []).indexOf(f) < 0) return false;
      if (q && String(e.name || "").toLowerCase().indexOf(q) < 0) return false;
      return true;
    });
  }

  function renderTable() {
    var rows = filteredExercises();
    var tb = document.getElementById("exercise-tbody");
    tb.innerHTML = rows.map(function (e) {
      var sel = e.id === _selectedId ? " rv-admin-row--sel" : "";
      var groups = (e.groups || []).map(function (g) {
        return '<span class="rv-tag">' + esc(g) + "</span>";
      }).join("");
      return (
        "<tr class=\"rv-admin-row" + sel + "\" data-id=\"" + esc(e.id) + "\">" +
        "<td><button type=\"button\" class=\"rv-linkish\" data-pick=\"" + esc(e.id) + "\">" + esc(e.name) + "</button></td>" +
        "<td>" + groups + "</td>" +
        "<td>" + esc((e.focus_tags || []).join(", ")) + "</td>" +
        "<td>" + formatBodyParts(e.body_parts) + "</td>" +
        "<td class=\"rv-mono\">" + formatDefault(e) + "</td>" +
        "<td class=\"rv-mono\">" + esc(String(e.tss_weight != null ? e.tss_weight : "1")) + "</td>" +
        "<td><input type=\"checkbox\" class=\"rv-switch\" data-active=\"" + esc(e.id) + "\" " +
        (e.active !== false ? "checked" : "") + " aria-label=\"Active\"></td>" +
        "</tr>"
      );
    }).join("");
    document.getElementById("list-meta").textContent =
      rows.length + " shown · " + _all.length + " total";
    document.getElementById("nav-ex-count").textContent = String(_all.length);
  }

  function fillChipRow(containerId, options, selected, multi) {
    var el = document.getElementById(containerId);
    el.innerHTML = options.map(function (opt) {
      var on = (multi ? selected.indexOf(opt) >= 0 : selected === opt) ? " is-on" : "";
      return '<button type="button" class="rv-chip' + on + '" data-val="' + esc(opt) + '">' + esc(opt) + "</button>";
    }).join("");
  }

  function renderPartEditors(parts) {
    var host = document.getElementById("ed-parts");
    var list = parts && parts.length ? parts : [{ part: "core", ratio: 1 }];
    host.innerHTML = list.map(function (p, i) {
      var opts = _bodyPartKeys.map(function (k) {
        var sel = k === p.part ? " selected" : "";
        return '<option value="' + esc(k) + '"' + sel + ">" + esc(k) + "</option>";
      }).join("");
      return (
        '<div class="rv-part-row rv-row" style="gap:8px;margin-bottom:6px">' +
        '<select class="rv-input rv-part-key">' + opts + "</select>" +
        '<input class="rv-input rv-part-pct" type="number" min="1" max="100" value="' +
        Math.round(Number(p.ratio) * 100) + '">' +
        '<button type="button" class="rv-btn rv-btn--secondary rv-btn--sm" data-rm-part="' + i + '">×</button>' +
        "</div>"
      );
    }).join("");
    renderPartSum();
  }

  function fillEditor(ex) {
    _selectedId = ex && ex.id ? ex.id : null;
    document.getElementById("editor-title").textContent =
      _selectedId ? "Edit exercise" : "New exercise";
    document.getElementById("ed-name").value = ex ? ex.name || "" : "";
    fillChipRow("ed-groups", GROUPS, ex ? ex.groups || [] : ["standalone"], true);
    fillChipRow("ed-focus", FOCUS, ex ? ex.focus_tags || [] : ["full"], true);
    renderPartEditors(ex ? ex.body_parts : null);
    document.getElementById("ed-sets").value = ex && ex.default_sets != null ? ex.default_sets : 3;
    document.getElementById("ed-reps").value = ex && ex.default_reps ? ex.default_reps : "10";
    document.getElementById("ed-load").value = ex && ex.default_load ? ex.default_load : "moderate";
    document.getElementById("ed-tss").value = ex && ex.tss_weight != null ? ex.tss_weight : 1;
    renderValidation(readEditorPayload());
    renderTable();
  }

  function loadExercises() {
    return api("/api/admin/plan-exercises").then(function (res) {
      if (!res.ok) return;
      _all = (res.data && res.data.exercises) || [];
      renderTable();
    });
  }

  function loadBodyParts() {
    return api("/api/admin/plan-library/body-parts").then(function (res) {
      if (res.ok && res.data && res.data.parts) {
        _bodyPartKeys = res.data.parts;
      } else {
        _bodyPartKeys = ["core", "quad", "glute", "hamstring", "calf", "shoulder", "chest"];
      }
    });
  }

  function populateFilters() {
    var g = document.getElementById("filter-group");
    var f = document.getElementById("filter-focus");
    GROUPS.forEach(function (x) {
      var o = document.createElement("option");
      o.value = x;
      o.textContent = x;
      g.appendChild(o);
    });
    FOCUS.forEach(function (x) {
      var o = document.createElement("option");
      o.value = x;
      o.textContent = x;
      f.appendChild(o);
    });
  }

  function saveExercise() {
    var v = readEditorPayload();
    renderValidation(v);
    if (!v.ok || !v.body) return;
    var path = _selectedId
      ? "/api/admin/plan-exercises/" + encodeURIComponent(_selectedId)
      : "/api/admin/plan-exercises";
    var method = _selectedId ? "PATCH" : "POST";
    api(path, {
      method: method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(v.body),
    }).then(function (res) {
      if (!res.ok) {
        window.RevampUI && window.RevampUI.showToast((res.data && res.data.detail) || "Save failed");
        return;
      }
      window.RevampUI && window.RevampUI.showToast("Saved");
      loadExercises().then(function () {
        if (res.data && res.data.id) fillEditor(res.data);
      });
    });
  }

  function toggleActive(id, active) {
    var row = _all.filter(function (e) { return e.id === id; })[0];
    if (!row) return;
    var payload = {
      name: row.name,
      groups: row.groups || [],
      focus_tags: row.focus_tags || [],
      body_parts: row.body_parts || [],
      tss_weight: row.tss_weight != null ? row.tss_weight : 1,
      default_sets: row.default_sets,
      default_reps: row.default_reps,
      default_load: row.default_load,
      active: active,
    };
    api("/api/admin/plan-exercises/" + encodeURIComponent(id), {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (res) {
      if (!res.ok) {
        window.RevampUI && window.RevampUI.showToast("Could not update active flag");
        loadExercises();
        return;
      }
      row.active = active;
      renderTable();
    });
  }

  function exportJson() {
    api("/api/admin/plan-library/export").then(function (res) {
      if (!res.ok) return;
      var blob = new Blob([JSON.stringify(res.data, null, 2)], { type: "application/json" });
      var a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "plan-library-" + new Date().toISOString().slice(0, 10) + ".json";
      a.click();
    });
  }

  function fingerprintBody(body) {
    return JSON.stringify({
      groups: body.groups,
      focus_tags: body.focus_tags,
      body_parts: body.body_parts,
      tss_weight: body.tss_weight,
      default_sets: body.default_sets,
      default_reps: body.default_reps,
      default_load: body.default_load,
      active: body.active,
    });
  }

  function importDryRun(bundle) {
    var byName = {};
    _all.forEach(function (e) { byName[e.name] = e; });
    var out = { new: [], changed: [], unchanged: [], invalid: [] };
    bundle.forEach(function (row, i) {
      var v = validateExerciseDraft(row);
      if (!v.ok) {
        out.invalid.push({ index: i, name: row && row.name, detail: (v.checks || []).filter(function (c) { return !c.ok; })[0] });
        return;
      }
      var existing = byName[v.body.name];
      if (!existing) {
        out.new.push(v.body.name);
        return;
      }
      var cur = fingerprintBody({
        groups: existing.groups || [],
        focus_tags: existing.focus_tags || [],
        body_parts: existing.body_parts || [],
        tss_weight: existing.tss_weight,
        default_sets: existing.default_sets,
        default_reps: existing.default_reps,
        default_load: existing.default_load,
        active: existing.active !== false,
      });
      if (cur === fingerprintBody(v.body)) out.unchanged.push(v.body.name);
      else out.changed.push(v.body.name);
    });
    return out;
  }

  function normalizeImportBundle(parsed) {
    if (Array.isArray(parsed)) return { exercises: parsed, patterns: [] };
    if (parsed && Array.isArray(parsed.exercises)) {
      return { exercises: parsed.exercises, patterns: parsed.patterns || [] };
    }
    return { exercises: [], patterns: [] };
  }

  function showImportDiff(diff) {
    var lines = [];
    if (diff.new.length) lines.push("New (" + diff.new.length + "): " + diff.new.slice(0, 8).join(", "));
    if (diff.changed.length) lines.push("Changed (" + diff.changed.length + "): " + diff.changed.slice(0, 8).join(", "));
    if (diff.unchanged.length) lines.push("Unchanged (" + diff.unchanged.length + ")");
    if (diff.invalid.length) {
      lines.push("Invalid (" + diff.invalid.length + "):");
      diff.invalid.slice(0, 6).forEach(function (x) {
        lines.push("  · " + (x.name || "#" + x.index) + " — " + (x.detail && x.detail.label));
      });
    }
    document.getElementById("import-diff").textContent = lines.join("\n") || "Nothing to import.";
    document.getElementById("import-apply").disabled = diff.invalid.length > 0 ||
      (!diff.new.length && !diff.changed.length);
    _importReady = diff.invalid.length ? null : diff;
  }

  function runImportPreview() {
    var raw = (document.getElementById("import-json").value || "").trim();
    if (!raw) {
      document.getElementById("import-diff").textContent = "Paste JSON first.";
      return;
    }
    var parsed;
    try {
      parsed = JSON.parse(raw);
    } catch (e) {
      document.getElementById("import-diff").textContent = "Invalid JSON: " + e.message;
      return;
    }
    var bundle = normalizeImportBundle(parsed).exercises;
    _importClean = [];
    bundle.forEach(function (row) {
      var v = validateExerciseDraft(row);
      if (v.ok) _importClean.push(v.body);
    });
    showImportDiff(importDryRun(bundle));
  }

  var _importClean = [];

  function runImportApply() {
    if (!_importClean || !_importClean.length) return;
    var payload = {
      exercises: _importClean,
      patterns: [],
      mode: document.getElementById("import-upsert").checked ? "upsert" : "create",
    };
    api("/api/admin/plan-library/import", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).then(function (res) {
      if (!res.ok) {
        document.getElementById("import-diff").textContent =
          (res.data && res.data.detail) || "Import failed";
        return;
      }
      document.getElementById("import-modal").hidden = true;
      window.RevampUI && window.RevampUI.showToast("Import complete");
      loadExercises();
    });
  }

  function wireEvents() {
    document.getElementById("filter-search").addEventListener("input", renderTable);
    document.getElementById("filter-group").addEventListener("change", renderTable);
    document.getElementById("filter-focus").addEventListener("change", renderTable);

    document.getElementById("exercise-tbody").addEventListener("click", function (ev) {
      var pick = ev.target.closest("[data-pick]");
      if (pick) {
        var id = pick.getAttribute("data-pick");
        var ex = _all.filter(function (e) { return e.id === id; })[0];
        if (ex) fillEditor(ex);
        return;
      }
      var sw = ev.target.closest(".rv-switch");
      if (sw) {
        toggleActive(sw.getAttribute("data-active"), sw.checked);
      }
    });

    document.getElementById("ed-groups").addEventListener("click", function (ev) {
      var chip = ev.target.closest(".rv-chip");
      if (!chip) return;
      chip.classList.toggle("is-on");
      renderValidation(readEditorPayload());
    });
    document.getElementById("ed-focus").addEventListener("click", function (ev) {
      var chip = ev.target.closest(".rv-chip");
      if (!chip) return;
      if (chip.parentElement.id === "ed-focus") chip.classList.toggle("is-on");
      renderValidation(readEditorPayload());
    });

    ["ed-name", "ed-sets", "ed-reps", "ed-load", "ed-tss"].forEach(function (id) {
      document.getElementById(id).addEventListener("input", function () {
        renderValidation(readEditorPayload());
      });
    });
    document.getElementById("ed-parts").addEventListener("input", function () {
      renderPartSum();
      renderValidation(readEditorPayload());
    });
    document.getElementById("ed-parts").addEventListener("click", function (ev) {
      if (ev.target.closest("[data-rm-part]")) {
        ev.target.closest(".rv-part-row").remove();
        renderPartSum();
        renderValidation(readEditorPayload());
      }
    });
    document.getElementById("btn-add-part").onclick = function () {
      renderPartEditors([{ part: _bodyPartKeys[0] || "core", ratio: 0.2 }]);
      renderValidation(readEditorPayload());
    };

    document.getElementById("btn-save").onclick = saveExercise;
    document.getElementById("btn-discard").onclick = function () {
      if (_selectedId) {
        var ex = _all.filter(function (e) { return e.id === _selectedId; })[0];
        fillEditor(ex);
      } else fillEditor(null);
    };
    document.getElementById("btn-new").onclick = function () { fillEditor(null); };
    document.getElementById("btn-export").onclick = exportJson;

    document.getElementById("btn-import").onclick = function () {
      document.getElementById("import-modal").hidden = false;
      document.getElementById("import-json").value = "";
      document.getElementById("import-diff").textContent = "";
      document.getElementById("import-apply").disabled = true;
      _importClean = [];
    };
    document.getElementById("import-cancel").onclick = function () {
      document.getElementById("import-modal").hidden = true;
    };
    document.getElementById("import-preview").onclick = runImportPreview;
    document.getElementById("import-apply").onclick = runImportApply;
    document.getElementById("import-file").onchange = function (ev) {
      var file = ev.target.files && ev.target.files[0];
      if (!file) return;
      var reader = new FileReader();
      reader.onload = function () {
        document.getElementById("import-json").value = String(reader.result || "");
        runImportPreview();
      };
      reader.readAsText(file);
      ev.target.value = "";
    };
  }

  var exportApi = {
    validateExerciseDraft: validateExerciseDraft,
    normalizeBodyPartsList: normalizeBodyPartsList,
    GROUPS: GROUPS,
    FOCUS: FOCUS,
  };
  if (typeof globalThis !== "undefined") globalThis.__v2TrainingAdmin = exportApi;
  if (typeof window !== "undefined") window.__v2TrainingAdmin = exportApi;

  populateFilters();
  wireEvents();
  Promise.all([loadBodyParts(), loadExercises()]).then(function () {
    if (_all.length) fillEditor(_all[0]);
    else fillEditor(null);
  });
})();