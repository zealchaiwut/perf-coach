/* Offline swap / reorder sheet. */
(function (global) {
  "use strict";

  var state = { session: null, gymState: null, bundle: null, keep: true, pick: null, query: "", onDone: null };

  function library(bundle) {
    var lib = (bundle && bundle.library) || [];
    if (Array.isArray(lib)) return lib;
    return lib.items || [];
  }

  function usualFor(name, bundle) {
    var hist = (bundle && bundle.swap_history) || {};
    var row = hist[name] || hist[String(name).toLowerCase()];
    if (!row) return null;
    return row.usual || row.replacement || row.name || null;
  }

  function matches(item, q) {
    if (!q) return true;
    q = q.toLowerCase();
    var blob = [item.name].concat(item.aliases || []).concat(item.muscles || []).join(" ").toLowerCase();
    return blob.indexOf(q) !== -1;
  }

  function render() {
    var el = document.getElementById("m-swap-sheet");
    if (!el) return;
    var bundle = state.bundle || {};
    var lib = library(bundle).filter(function (it) { return matches(it, state.query); });
    var fromName = state.fromName || "exercise";
    var usual = usualFor(fromName, bundle);
    if (usual) {
      lib.sort(function (a, b) {
        var au = (a.name || "").toLowerCase() === String(usual).toLowerCase() ? 0 : 1;
        var bu = (b.name || "").toLowerCase() === String(usual).toLowerCase() ? 0 : 1;
        return au - bu;
      });
    }
    var rows = lib.slice(0, 12).map(function (it) {
      var isUsual = usual && (it.name || "").toLowerCase() === String(usual).toLowerCase();
      var on = state.pick && state.pick.name === it.name;
      return '<button type="button" class="m-swap-row' + (on ? " on" : "") + '" data-name="' + (it.name || "") + '">' +
        "<span><strong>" + (it.name || "") + "</strong>" +
        (isUsual ? '<div class="m-muted">You picked this recently</div>' : "") +
        "</span>" + (isUsual ? '<span class="m-usual">USUAL</span>' : "") + "</button>";
    }).join("");
    el.innerHTML = '<span class="m-sheet-handle"></span>' +
      '<div class="m-row"><div><div class="m-kicker m-kicker--grey">SWAP</div><h2>Swap ' + fromName +
      '</h2></div><button type="button" class="m-text-btn" id="m-swap-close">✕</button></div>' +
      '<input id="m-swap-q" placeholder="Search the library (works offline)" value="' + (state.query || "") + '">' +
      '<div id="m-swap-list">' + (rows || '<div class="m-muted">No matches.</div>') + "</div>" +
      '<div class="m-keep-row"><span>Keep planned scheme</span>' +
      '<button type="button" id="m-keep-scheme" aria-pressed="' + state.keep + '">' + (state.keep ? "On" : "Off") + "</button></div>" +
      orderHtml() +
      '<button type="button" class="m-keep" id="m-swap-go">Swap to ' + ((state.pick && state.pick.name) || "…") + "</button>";
    el.hidden = false;
    var backdrop = document.getElementById("m-sheet-backdrop");
    if (backdrop) backdrop.hidden = false;
    bind();
  }

  function orderHtml() {
    var exercises = (state.session && state.session.exercises) || [];
    if (exercises.length < 2) return "";
    return '<div class="m-kicker m-kicker--grey">ORDER</div>' + exercises.map(function (ex, i) {
      return '<div class="m-swap-row" data-ord="' + i + '"><span>' + (ex.name || "ex") +
        '</span><span><button type="button" data-move="-1" data-ord="' + i + '">↑</button>' +
        '<button type="button" data-move="1" data-ord="' + i + '">↓</button></span></div>';
    }).join("");
  }

  function bind() {
    var q = document.getElementById("m-swap-q");
    if (q) q.addEventListener("input", function () {
      state.query = q.value;
      render();
      var again = document.getElementById("m-swap-q");
      if (again) { again.focus(); again.value = state.query; again.setSelectionRange(state.query.length, state.query.length); }
    });
    document.getElementById("m-swap-close").addEventListener("click", close);
    document.getElementById("m-keep-scheme").addEventListener("click", function () {
      state.keep = !state.keep;
      render();
    });
    document.querySelectorAll("[data-name]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var name = btn.getAttribute("data-name");
        state.pick = library(state.bundle).filter(function (it) { return it.name === name; })[0] || { name: name };
        render();
      });
    });
    document.querySelectorAll("[data-move]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var i = Number(btn.getAttribute("data-ord"));
        var dir = Number(btn.getAttribute("data-move"));
        var list = state.session.exercises;
        var j = i + dir;
        if (j < 0 || j >= list.length) return;
        var tmp = list[i];
        list[i] = list[j];
        list[j] = tmp;
        if (state.gymState && state.gymState.edit_log) {
          state.gymState.edit_log.push({ type: "reorder", from: i, to: j });
        }
        if (global.MGym && MGym.persist) MGym.persist();
        render();
      });
    });
    document.getElementById("m-swap-go").addEventListener("click", function () {
      if (!state.pick || !state.onDone) return close();
      state.onDone({
        from: state.fromName,
        to: state.pick.name,
        keep: state.keep,
        last_numbers: (state.bundle.last_numbers || {})[state.pick.name]
      });
      close();
    });
  }

  function close() {
    var el = document.getElementById("m-swap-sheet");
    if (el) el.hidden = true;
    var backdrop = document.getElementById("m-sheet-backdrop");
    if (backdrop) backdrop.hidden = true;
  }

  function open(session, gymState, bundle, fromName, onDone) {
    state = { session: session, gymState: gymState, bundle: bundle, keep: true, pick: null, query: "", fromName: fromName, onDone: onDone };
    var host = document.getElementById("m-swap-sheet");
    if (!host) {
      host = document.createElement("div");
      host.id = "m-swap-sheet";
      host.className = "m-sheet";
      host.setAttribute("role", "dialog");
      document.body.appendChild(host);
    }
    render();
  }

  global.MGymSwap = { open: open, close: close, usualFor: usualFor, matches: matches };
})(window);
