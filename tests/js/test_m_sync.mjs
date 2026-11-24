import { readFileSync } from "node:fs";
import { createContext, runInContext } from "node:vm";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import assert from "node:assert/strict";

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "..", "..");

class FakeReq {
  constructor(result) {
    this.result = result;
    this.error = null;
    queueMicrotask(() => {
      if (this.onsuccess) this.onsuccess({ target: this });
    });
  }
}

class FakeStore {
  constructor(map) {
    this.map = map;
  }
  get(key) {
    return new FakeReq(this.map.get(key));
  }
  put(value, key) {
    const k = key !== undefined ? key : value.client_mutation_id;
    this.map.set(k, value);
    return new FakeReq(value);
  }
  delete(key) {
    this.map.delete(key);
    return new FakeReq(undefined);
  }
  getAll() {
    return new FakeReq([...this.map.values()]);
  }
}

function makeIdb() {
  const stores = {
    bundle: new Map(),
    outbox: new Map(),
    session_state: new Map(),
    meta: new Map(),
  };
  const db = {
    objectStoreNames: { contains: (n) => n in stores },
    transaction(name) {
      const store = new FakeStore(stores[name]);
      return { objectStore: () => store };
    },
  };
  return {
    stores,
    indexedDB: {
      open() {
        const req = { result: db };
        queueMicrotask(() => {
          if (req.onupgradeneeded) req.onupgradeneeded({ target: req });
          if (req.onsuccess) req.onsuccess({ target: req });
        });
        return req;
      },
    },
  };
}

function load(fetchImpl) {
  const { stores, indexedDB } = makeIdb();
  const sandbox = {
    window: null,
    indexedDB,
    crypto: { randomUUID: () => "op-" + Math.random().toString(16).slice(2) },
    document: { cookie: "csrf-token=test", addEventListener() {}, hidden: false },
    fetch: fetchImpl,
    AbortController,
    setTimeout() { return 0; },
    clearTimeout() {},
    dispatchEvent() {},
    addEventListener() {},
    Date,
    JSON,
    Promise,
    Map,
    CustomEvent: class CustomEvent {
      constructor(type, init) {
        this.type = type;
        this.detail = init && init.detail;
      }
    },
    console,
  };
  sandbox.window = sandbox;
  sandbox.global = sandbox;
  const ctx = createContext(sandbox);
  for (const file of ["frontend/js/m/store.js", "frontend/js/m/sync.js"]) {
    runInContext(readFileSync(join(ROOT, file), "utf8"), ctx, { filename: file });
  }
  return { ctx, stores };
}

test("enqueue writes the op immediately", async () => {
  const { ctx, stores } = load(async () => ({ ok: true, json: async () => ({ ops: [] }) }));
  const op = ctx.MStore.newOp("weigh_in", { kg: 67.8 });
  await ctx.MSync.enqueue(op);
  assert.equal(stores.outbox.size, 1);
  assert.equal([...stores.outbox.values()][0].op_type, "weigh_in");
});

test("duplicate response clears the op", async () => {
  const { ctx, stores } = load(async () => ({
    ok: true,
    json: async () => ({ ops: [{ status: "duplicate" }] }),
  }));
  const op = ctx.MStore.newOp("weigh_in", { kg: 68 });
  stores.outbox.set(op.client_mutation_id, op);
  await ctx.MSync.flush();
  assert.equal(stores.outbox.size, 0);
});

test("conflict keeps the op and marks it", async () => {
  const { ctx, stores } = load(async () => ({
    ok: true,
    json: async () => ({ ops: [{ status: "conflict", server_version: { version_id: "9" } }] }),
  }));
  const op = ctx.MStore.newOp("session_log", { name: "Strength A" });
  stores.outbox.set(op.client_mutation_id, op);
  await ctx.MSync.flush();
  const left = [...stores.outbox.values()][0];
  assert.equal(left.conflict, true);
  assert.equal(left.server_version.version_id, "9");
});

test("backoff steps 2s then 4s up to 60s", () => {
  const { ctx } = load(async () => ({ ok: true, json: async () => ({ ops: [] }) }));
  assert.equal(ctx.MSync.nextDelay(0), 2000);
  assert.equal(ctx.MSync.nextDelay(1), 4000);
  assert.equal(ctx.MSync.nextDelay(5), 60000);
  assert.equal(ctx.MSync.nextDelay(99), 60000);
});
