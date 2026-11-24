/* IndexedDB wrapper for the phone PWA. */
(function (global) {
  "use strict";
  var DB_NAME = "perf-coach-m";
  var DB_VERSION = 1;
  var _db = null;

  function openDb() {
    if (_db) return Promise.resolve(_db);
    return new Promise(function (resolve, reject) {
      var req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = function (e) {
        var db = e.target.result;
        if (!db.objectStoreNames.contains("bundle")) db.createObjectStore("bundle");
        if (!db.objectStoreNames.contains("outbox")) db.createObjectStore("outbox", { keyPath: "client_mutation_id" });
        if (!db.objectStoreNames.contains("session_state")) db.createObjectStore("session_state");
        if (!db.objectStoreNames.contains("meta")) db.createObjectStore("meta");
      };
      req.onsuccess = function () {
        _db = req.result;
        resolve(_db);
      };
      req.onerror = function () { reject(req.error); };
    });
  }

  function tx(store, mode) {
    return openDb().then(function (db) {
      return db.transaction(store, mode || "readonly").objectStore(store);
    });
  }

  function reqToPromise(req) {
    return new Promise(function (resolve, reject) {
      req.onsuccess = function () { resolve(req.result); };
      req.onerror = function () { reject(req.error); };
    });
  }

  function get(store, key) {
    return tx(store).then(function (os) { return reqToPromise(os.get(key)); });
  }
  function put(store, value, key) {
    return tx(store, "readwrite").then(function (os) {
      return reqToPromise(key === undefined ? os.put(value) : os.put(value, key));
    });
  }
  function del(store, key) {
    return tx(store, "readwrite").then(function (os) { return reqToPromise(os.delete(key)); });
  }
  function getAll(store) {
    return tx(store).then(function (os) { return reqToPromise(os.getAll()); });
  }

  function uuid() {
    if (global.crypto && crypto.randomUUID) return crypto.randomUUID();
    return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, function (c) {
      var r = Math.random() * 16 | 0;
      return (c === "x" ? r : (r & 0x3 | 0x8)).toString(16);
    });
  }

  global.MStore = {
    open: openDb,
    getBundle: function () { return get("bundle", "current"); },
    setBundle: function (payload, etag) {
      return put("bundle", { payload: payload, etag: etag || null, fetched_at: Date.now() }, "current");
    },
    listOutbox: function () { return getAll("outbox"); },
    putOutbox: function (op) { return put("outbox", op); },
    deleteOutbox: function (id) { return del("outbox", id); },
    getSession: function (id) { return get("session_state", id || "active"); },
    setSession: function (state, id) { return put("session_state", state, id || "active"); },
    clearSession: function (id) { return del("session_state", id || "active"); },
    getMeta: function (key) { return get("meta", key); },
    setMeta: function (key, value) { return put("meta", value, key); },
    uuid: uuid,
    newOp: function (opType, payload, baseVersion) {
      return {
        client_mutation_id: uuid(),
        op_type: opType,
        created_at: new Date().toISOString(),
        base_version: baseVersion || null,
        payload: payload || {},
        attempts: 0,
        last_error: null,
        conflict: false
      };
    }
  };
})(window);
