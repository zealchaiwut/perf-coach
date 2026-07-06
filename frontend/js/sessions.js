(function () {
  "use strict";

  // -- Constants ---------------------------------------------------------------

  var PLYO_PHASES = [
    { value: "intro", label: "Intro" },
    { value: "build", label: "Build" },
    { value: "maintain", label: "Maintain" },
  ];

  var LOAD_UNITS = ["kg", "lbs"];

  // -- State -------------------------------------------------------------------

  var state = {
    sessionType: "strength", // "strength" | "plyo"
    exercises: [], // array of {_id, exercise_name, sets, reps, load, load_unit, foot_contacts, plyo_phase}
    editingEntryId: null, // DB id of an existing exercise entry being edited (null for new)
    sessionDate: "",
    strengthEntries: [], // persisted entries from GET /api/strength-sessions
    plyoEntries: [], // persisted entries from GET /api/plyo-sessions
  };

  // -- Helpers -----------------------------------------------------------------

  function esc(s) {
    if (s == null) return "";
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function today() {
    var d = new Date();
    var mm = String(d.getMonth() + 1).padStart(2, "0");
    var dd = String(d.getDate()).padStart(2, "0");
    return d.getFullYear() + "-" + mm + "-" + dd;
  }

  function fmtDate(str) {
    if (!str) return "—";
    try {
      var d = new Date(str + "T00:00:00");
      return d.toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      });
    } catch (e) {
      return str;
    }
  }

  function getCsrf() {
    var m = document.cookie.match(/(?:^|; )csrf_token=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  function apiFetch(url, opts) {
    opts = opts || {};
    opts.credentials = "include";
    opts.headers = Object.assign(
      { "Content-Type": "application/json", "X-CSRF-Token": getCsrf() },
      opts.headers || {},
    );
    return fetch(url, opts).then(function (r) {
      if (r.status === 204) return null;
      return r.json().then(function (data) {
        if (!r.ok) {
          var msg =
            data && data.detail
              ? JSON.stringify(data.detail)
              : "Request failed (" + r.status + ")";
          var err = new Error(msg);
          err.status = r.status;
          err.data = data;
          throw err;
        }
        return data;
      });
    });
  }

  // -- Toast -------------------------------------------------------------------

  var _toastTimer = null;
  function showToast(msg, type) {
    var t = document.getElementById("se-toast");
    t.textContent = msg;
    t.className = "se-toast " + (type || "success") + " is-visible";
    clearTimeout(_toastTimer);
    _toastTimer = setTimeout(function () {
      t.className = "se-toast";
    }, 2600);
  }

  // -- Exercise row builder (form) ----------------------------------------------

  var _exSeq = 0;
  function newExerciseRow() {
    return {
      _id: ++_exSeq,
      exercise_name: "",
      sets: "",
      reps: "",
      load: "",
      load_unit: "kg",
      foot_contacts: "",
      plyo_phase: "intro",
    };
  }

  function renderExerciseRow(ex, idx) {
    var type = state.sessionType;
    var gridCls = type === "strength" ? "strength-grid" : "plyo-grid";

    var deleteBtn =
      state.exercises.length > 1
        ? '<button type="button" class="se-ex-delete" data-seq="' +
          ex._id +
          '" title="Remove exercise" aria-label="Remove exercise">×</button>'
        : "";

    if (type === "strength") {
      return (
        '<div class="se-ex-row ' +
        gridCls +
        '" data-seq="' +
        ex._id +
        '">' +
        deleteBtn +
        '<div class="se-ex-field" data-area="name"><label for="ex-name-' +
        ex._id +
        '">Exercise *</label>' +
        '<input class="se-ex-input" type="text" id="ex-name-' +
        ex._id +
        '" data-field="exercise_name" data-seq="' +
        ex._id +
        '" value="' +
        esc(ex.exercise_name) +
        '" placeholder="e.g. Squat" maxlength="200"></div>' +
        '<div class="se-ex-field" data-area="sets"><label for="ex-sets-' +
        ex._id +
        '">Sets</label>' +
        '<input class="se-ex-input" type="number" id="ex-sets-' +
        ex._id +
        '" data-field="sets" data-seq="' +
        ex._id +
        '" value="' +
        esc(ex.sets) +
        '" min="1" placeholder="—"></div>' +
        '<div class="se-ex-field" data-area="reps"><label for="ex-reps-' +
        ex._id +
        '">Reps</label>' +
        '<input class="se-ex-input" type="number" id="ex-reps-' +
        ex._id +
        '" data-field="reps" data-seq="' +
        ex._id +
        '" value="' +
        esc(ex.reps) +
        '" min="1" placeholder="—"></div>' +
        '<div class="se-ex-field" data-area="load"><label for="ex-load-' +
        ex._id +
        '">Load</label>' +
        '<input class="se-ex-input" type="number" id="ex-load-' +
        ex._id +
        '" data-field="load" data-seq="' +
        ex._id +
        '" value="' +
        esc(ex.load) +
        '" min="0" step="0.5" placeholder="—"></div>' +
        '<div class="se-ex-field" data-area="unit"><label for="ex-unit-' +
        ex._id +
        '">Unit</label>' +
        '<select class="se-ex-select" id="ex-unit-' +
        ex._id +
        '" data-field="load_unit" data-seq="' +
        ex._id +
        '">' +
        LOAD_UNITS.map(function (u) {
          return (
            '<option value="' +
            u +
            '"' +
            (ex.load_unit === u ? " selected" : "") +
            ">" +
            u +
            "</option>"
          );
        }).join("") +
        "</select></div>" +
        '<div class="se-ex-errors" data-seq-err="' +
        ex._id +
        '" role="alert"></div>' +
        "</div>"
      );
    } else {
      return (
        '<div class="se-ex-row ' +
        gridCls +
        '" data-seq="' +
        ex._id +
        '">' +
        deleteBtn +
        '<div class="se-ex-field" data-area="name"><label for="ex-name-' +
        ex._id +
        '">Exercise *</label>' +
        '<input class="se-ex-input" type="text" id="ex-name-' +
        ex._id +
        '" data-field="exercise_name" data-seq="' +
        ex._id +
        '" value="' +
        esc(ex.exercise_name) +
        '" placeholder="e.g. Box Jump" maxlength="200"></div>' +
        '<div class="se-ex-field" data-area="contacts"><label for="ex-contacts-' +
        ex._id +
        '">Foot Contacts *</label>' +
        '<input class="se-ex-input" type="number" id="ex-contacts-' +
        ex._id +
        '" data-field="foot_contacts" data-seq="' +
        ex._id +
        '" value="' +
        esc(ex.foot_contacts) +
        '" min="0" placeholder="e.g. 80"></div>' +
        '<div class="se-ex-field" data-area="phase"><label for="ex-phase-' +
        ex._id +
        '">Phase *</label>' +
        '<select class="se-ex-select" id="ex-phase-' +
        ex._id +
        '" data-field="plyo_phase" data-seq="' +
        ex._id +
        '">' +
        PLYO_PHASES.map(function (p) {
          return (
            '<option value="' +
            p.value +
            '"' +
            (ex.plyo_phase === p.value ? " selected" : "") +
            ">" +
            p.label +
            "</option>"
          );
        }).join("") +
        "</select></div>" +
        '<div class="se-ex-errors" data-seq-err="' +
        ex._id +
        '" role="alert"></div>' +
        "</div>"
      );
    }
  }

  function renderForm() {
    var container = document.getElementById("se-exercises");
    container.innerHTML = state.exercises
      .map(function (ex, i) {
        return renderExerciseRow(ex, i);
      })
      .join("");
    wireFormInputs();
  }

  function wireFormInputs() {
    // Sync all inputs back to state on change
    document.querySelectorAll("[data-field][data-seq]").forEach(function (el) {
      el.addEventListener("input", function () {
        var seq = parseInt(el.dataset.seq, 10);
        var field = el.dataset.field;
        var ex = state.exercises.find(function (e) {
          return e._id === seq;
        });
        if (ex) ex[field] = el.value;
      });
      el.addEventListener("change", function () {
        var seq = parseInt(el.dataset.seq, 10);
        var field = el.dataset.field;
        var ex = state.exercises.find(function (e) {
          return e._id === seq;
        });
        if (ex) ex[field] = el.value;
      });
    });

    // Delete exercise row buttons
    document.querySelectorAll(".se-ex-delete").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var seq = parseInt(btn.dataset.seq, 10);
        if (state.exercises.length <= 1) return;
        var idx = state.exercises.findIndex(function (e) {
          return e._id === seq;
        });
        if (idx !== -1) state.exercises.splice(idx, 1);
        renderForm();
      });
    });
  }

  // -- Validation ---------------------------------------------------------------

  function clearErrors() {
    document.querySelectorAll(".se-ex-errors").forEach(function (el) {
      el.innerHTML = "";
    });
    document.querySelectorAll(".has-error").forEach(function (el) {
      el.classList.remove("has-error");
    });
    var dateErr = document.getElementById("se-date-err");
    if (dateErr) {
      dateErr.style.display = "none";
      dateErr.textContent = "";
    }
  }

  function fieldError(seq, field, msg) {
    var input = document.querySelector(
      '[data-field="' + field + '"][data-seq="' + seq + '"]',
    );
    if (input) input.classList.add("has-error");
    var errContainer = document.querySelector('[data-seq-err="' + seq + '"]');
    if (errContainer) {
      errContainer.innerHTML +=
        '<span class="se-ex-error-msg">' +
        esc(field) +
        ": " +
        esc(msg) +
        "</span>";
    }
  }

  function validateForm() {
    clearErrors();
    var ok = true;

    var dateVal = document.getElementById("se-date").value;
    if (!dateVal) {
      var de = document.getElementById("se-date-err");
      de.textContent = "Session date is required.";
      de.style.display = "inline";
      ok = false;
    }

    state.exercises.forEach(function (ex) {
      if (!ex.exercise_name || !ex.exercise_name.trim()) {
        fieldError(ex._id, "exercise_name", "required");
        ok = false;
      }
      if (state.sessionType === "plyo") {
        var fc = ex.foot_contacts;
        if (fc === "" || fc === null || fc === undefined) {
          fieldError(ex._id, "foot_contacts", "required");
          ok = false;
        } else if (parseInt(fc, 10) < 0) {
          fieldError(ex._id, "foot_contacts", "must be ≥ 0");
          ok = false;
        }
      }
    });

    return ok;
  }

  // -- Form show/hide -----------------------------------------------------------

  function showForm() {
    var card = document.getElementById("se-form-card");
    card.style.display = "block";
    document.getElementById("se-add-btn").style.display = "none";
    document.getElementById("se-date").value = today();
    state.sessionDate = today();
    state.exercises = [newExerciseRow()];
    state.editingEntryId = null;
    renderForm();
    updateTypeButtons();
  }

  function hideForm() {
    document.getElementById("se-form-card").style.display = "none";
    document.getElementById("se-add-btn").style.display = "inline-flex";
    clearErrors();
  }

  // -- Type switching -----------------------------------------------------------

  function updateTypeButtons() {
    var strengthBtn = document.getElementById("se-type-strength");
    var plyoBtn = document.getElementById("se-type-plyo");
    if (state.sessionType === "strength") {
      strengthBtn.classList.add("is-active");
      plyoBtn.classList.remove("is-active");
      strengthBtn.setAttribute("aria-pressed", "true");
      plyoBtn.setAttribute("aria-pressed", "false");
    } else {
      plyoBtn.classList.add("is-active");
      strengthBtn.classList.remove("is-active");
      plyoBtn.setAttribute("aria-pressed", "true");
      strengthBtn.setAttribute("aria-pressed", "false");
    }
  }

  // -- Submit -------------------------------------------------------------------

  function submitForm() {
    if (!validateForm()) return;

    var dateVal = document.getElementById("se-date").value;
    var btn = document.getElementById("se-submit-btn");
    btn.disabled = true;
    btn.textContent = "Saving…";

    var endpoint =
      state.sessionType === "strength"
        ? "/api/strength-sessions"
        : "/api/plyo-sessions";

    var promises = state.exercises.map(function (ex) {
      var payload;
      if (state.sessionType === "strength") {
        payload = {
          session_date: dateVal,
          exercise_name: ex.exercise_name.trim(),
          sets: ex.sets !== "" ? parseInt(ex.sets, 10) : null,
          reps: ex.reps !== "" ? parseInt(ex.reps, 10) : null,
          load: ex.load !== "" ? parseFloat(ex.load) : null,
          load_unit: ex.load_unit || "kg",
        };
      } else {
        payload = {
          session_date: dateVal,
          exercise_name: ex.exercise_name.trim(),
          foot_contacts: parseInt(ex.foot_contacts, 10),
          plyo_phase: ex.plyo_phase || "intro",
        };
      }
      return apiFetch(endpoint, {
        method: "POST",
        body: JSON.stringify(payload),
      });
    });

    Promise.all(promises)
      .then(function () {
        showToast("Session saved!", "success");
        hideForm();
        loadAll();
      })
      .catch(function (err) {
        showToast("Save failed: " + err.message, "error");
      })
      .finally(function () {
        btn.disabled = false;
        btn.textContent = "Save Session";
      });
  }

  // -- Inline edit (single exercise entry) --------------------------------------

  function openEditEntry(id, type) {
    var entry =
      type === "strength"
        ? state.strengthEntries.find(function (e) {
            return e.id === id;
          })
        : state.plyoEntries.find(function (e) {
            return e.id === id;
          });
    if (!entry) return;

    state.sessionType = type;
    state.editingEntryId = id;
    var ex = {
      _id: ++_exSeq,
      exercise_name: entry.exercise_name || "",
      sets: entry.sets || "",
      reps: entry.reps || "",
      load: entry.load != null ? entry.load : "",
      load_unit: entry.load_unit || "kg",
      foot_contacts: entry.foot_contacts != null ? entry.foot_contacts : "",
      plyo_phase: entry.plyo_phase || "intro",
    };
    state.exercises = [ex];

    var card = document.getElementById("se-form-card");
    card.style.display = "block";
    document.getElementById("se-add-btn").style.display = "none";
    document.getElementById("se-date").value = entry.session_date || today();
    document.getElementById("se-submit-btn").textContent = "Update Entry";
    // Hide "add another exercise" for single-entry edits
    document.getElementById("se-add-ex-btn").style.display = "none";
    updateTypeButtons();
    // Disable type switching during edit
    document.getElementById("se-type-strength").disabled = true;
    document.getElementById("se-type-plyo").disabled = true;
    renderForm();
  }

  function submitEdit() {
    if (!validateForm()) return;

    var dateVal = document.getElementById("se-date").value;
    var btn = document.getElementById("se-submit-btn");
    btn.disabled = true;
    btn.textContent = "Saving…";

    var ex = state.exercises[0];
    var endpoint =
      (state.sessionType === "strength"
        ? "/api/strength-sessions/"
        : "/api/plyo-sessions/") + state.editingEntryId;
    var payload;
    if (state.sessionType === "strength") {
      payload = {
        session_date: dateVal,
        exercise_name: ex.exercise_name.trim(),
        sets: ex.sets !== "" && ex.sets !== null ? parseInt(ex.sets, 10) : null,
        reps: ex.reps !== "" && ex.reps !== null ? parseInt(ex.reps, 10) : null,
        load: ex.load !== "" && ex.load !== null ? parseFloat(ex.load) : null,
        load_unit: ex.load_unit || "kg",
      };
    } else {
      payload = {
        session_date: dateVal,
        exercise_name: ex.exercise_name.trim(),
        foot_contacts: parseInt(ex.foot_contacts, 10),
        plyo_phase: ex.plyo_phase || "intro",
      };
    }

    apiFetch(endpoint, { method: "PUT", body: JSON.stringify(payload) })
      .then(function () {
        showToast("Entry updated!", "success");
        cancelEdit();
        loadAll();
      })
      .catch(function (err) {
        showToast("Update failed: " + err.message, "error");
        btn.disabled = false;
        btn.textContent = "Update Entry";
      });
  }

  function cancelEdit() {
    document.getElementById("se-add-ex-btn").style.display = "inline-flex";
    document.getElementById("se-type-strength").disabled = false;
    document.getElementById("se-type-plyo").disabled = false;
    document.getElementById("se-submit-btn").textContent = "Save Session";
    hideForm();
  }

  // -- Delete --------------------------------------------------------------------

  function confirmDeleteEntry(id, type, name) {
    if (
      !confirm(
        'Delete "' + (name || "this exercise") + '"? This cannot be undone.',
      )
    )
      return;
    var endpoint =
      (type === "strength"
        ? "/api/strength-sessions/"
        : "/api/plyo-sessions/") + id;
    apiFetch(endpoint, { method: "DELETE" })
      .then(function () {
        showToast("Entry deleted.", "success");
        loadAll();
      })
      .catch(function (err) {
        showToast("Delete failed: " + err.message, "error");
      });
  }

  // -- List rendering ------------------------------------------------------------

  function groupByDate(entries, type) {
    var groups = {};
    entries.forEach(function (e) {
      var d = e.session_date;
      if (!groups[d]) groups[d] = { date: d, type: type, exercises: [] };
      groups[d].exercises.push(e);
    });
    return Object.values(groups).sort(function (a, b) {
      return b.date.localeCompare(a.date);
    });
  }

  function strengthDetail(e) {
    var parts = [];
    if (e.sets) parts.push(e.sets + " sets");
    if (e.reps) parts.push(e.reps + " reps");
    if (e.load != null) parts.push(e.load + " " + (e.load_unit || "kg"));
    return parts.join(" × ") || "—";
  }

  function plyoDetail(e) {
    var phase = PLYO_PHASES.find(function (p) {
      return p.value === e.plyo_phase;
    });
    return (
      (e.foot_contacts != null ? e.foot_contacts + " contacts" : "—") +
      " · " +
      (phase ? phase.label : e.plyo_phase || "—")
    );
  }

  function renderSessionGroup(g) {
    var badgeCls = g.type;
    var label = g.type === "strength" ? "Strength" : "Plyo";
    var count = g.exercises.length;
    var countLabel = count + (count === 1 ? " exercise" : " exercises");

    var exHtml = g.exercises
      .map(function (e) {
        var detail = g.type === "strength" ? strengthDetail(e) : plyoDetail(e);
        return (
          '<div class="se-ex-item">' +
          '<span class="se-ex-dot ' +
          badgeCls +
          '"></span>' +
          '<span class="se-ex-item-name">' +
          esc(e.exercise_name || "Exercise") +
          "</span>" +
          '<span class="se-ex-item-detail">' +
          esc(detail) +
          "</span>" +
          '<div class="se-ex-item-actions">' +
          '<button class="se-ex-item-btn edit" data-id="' +
          e.id +
          '" data-type="' +
          g.type +
          '">Edit</button>' +
          '<button class="se-ex-item-btn del" data-id="' +
          e.id +
          '" data-type="' +
          g.type +
          '" data-name="' +
          esc(e.exercise_name) +
          '">Delete</button>' +
          "</div>" +
          "</div>"
        );
      })
      .join("");

    return (
      '<div class="se-session-card">' +
      '<div class="se-session-header">' +
      '<div class="se-session-meta">' +
      '<span class="se-session-badge ' +
      badgeCls +
      '">' +
      label +
      "</span>" +
      '<span class="se-session-date">' +
      fmtDate(g.date) +
      "</span>" +
      '<span class="se-session-count">' +
      countLabel +
      "</span>" +
      "</div>" +
      "</div>" +
      '<div class="se-ex-list">' +
      exHtml +
      "</div>" +
      "</div>"
    );
  }

  var EMPTY_ICON =
    '<svg class="se-empty-icon" width="32" height="32" viewBox="0 0 24 24" ' +
    'fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" ' +
    'stroke-linejoin="round" aria-hidden="true">' +
    '<path d="M4 9v6M2 10v4M20 9v6M22 10v4M7 12h10"/>' +
    '<rect x="5.5" y="7" width="3" height="10" rx="1"/>' +
    '<rect x="15.5" y="7" width="3" height="10" rx="1"/>' +
    "</svg>";

  function renderList() {
    var container = document.getElementById("se-list-container");
    container.setAttribute("aria-busy", "false");
    var strengthGroups = groupByDate(state.strengthEntries, "strength");
    var plyoGroups = groupByDate(state.plyoEntries, "plyo");
    var allGroups = strengthGroups.concat(plyoGroups).sort(function (a, b) {
      return b.date.localeCompare(a.date);
    });

    if (!allGroups.length) {
      container.innerHTML =
        '<div class="se-card se-empty">' +
        EMPTY_ICON +
        "<strong>No sessions yet</strong>" +
        "<p>Click “Add Session” above to log your first strength or plyo session.</p>" +
        "</div>";
      return;
    }

    container.innerHTML =
      '<div class="se-list">' +
      allGroups.map(renderSessionGroup).join("") +
      "</div>";

    // Wire edit / delete buttons
    container.querySelectorAll(".se-ex-item-btn.edit").forEach(function (btn) {
      btn.addEventListener("click", function () {
        openEditEntry(btn.dataset.id, btn.dataset.type);
      });
    });
    container.querySelectorAll(".se-ex-item-btn.del").forEach(function (btn) {
      btn.addEventListener("click", function () {
        confirmDeleteEntry(btn.dataset.id, btn.dataset.type, btn.dataset.name);
      });
    });
  }

  // -- Data loading --------------------------------------------------------------

  function loadAll() {
    Promise.all([
      apiFetch("/api/strength-sessions"),
      apiFetch("/api/plyo-sessions"),
    ])
      .then(function (results) {
        state.strengthEntries = results[0] || [];
        state.plyoEntries = results[1] || [];
        renderList();
      })
      .catch(function (err) {
        var container = document.getElementById("se-list-container");
        container.setAttribute("aria-busy", "false");
        container.innerHTML =
          '<div class="se-card se-error-banner" role="alert">Failed to load sessions: ' +
          esc(err.message) +
          "</div>";
      });
  }

  // -- Event wiring --------------------------------------------------------------

  function init() {
    // Add session button
    document.getElementById("se-add-btn").addEventListener("click", showForm);

    // Type picker
    document
      .getElementById("se-type-strength")
      .addEventListener("click", function () {
        state.sessionType = "strength";
        state.exercises = [newExerciseRow()];
        updateTypeButtons();
        renderForm();
      });
    document
      .getElementById("se-type-plyo")
      .addEventListener("click", function () {
        state.sessionType = "plyo";
        state.exercises = [newExerciseRow()];
        updateTypeButtons();
        renderForm();
      });

    // Add another exercise
    document
      .getElementById("se-add-ex-btn")
      .addEventListener("click", function () {
        state.exercises.push(newExerciseRow());
        renderForm();
      });

    // Cancel
    document
      .getElementById("se-cancel-btn")
      .addEventListener("click", function () {
        if (state.editingEntryId) {
          cancelEdit();
        } else {
          hideForm();
        }
      });

    // Submit
    document
      .getElementById("se-submit-btn")
      .addEventListener("click", function () {
        if (state.editingEntryId) {
          submitEdit();
        } else {
          submitForm();
        }
      });

    // Date input
    document.getElementById("se-date").addEventListener("change", function () {
      state.sessionDate = this.value;
    });

    loadAll();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
