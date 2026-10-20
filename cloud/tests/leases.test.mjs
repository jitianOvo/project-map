import test from "node:test";
import assert from "node:assert/strict";
import { EditingAccess } from "../web/leases.js";

function fixture() {
  const docs = new Map([["one", { id: "one", dirty: false, content: "最新" }]]);
  const calls = [];
  const api = { token: "test", async request(route, body) {
    calls.push([route, body]);
    if (route === "api/editor/open") return { ...body, lease_token: "proof", expires_in: 60, document: docs.get(body.id) };
    if (route === "api/editor/renew") return { expires_in: 60 };
    if (route === "api/sync") return { ok: true };
    return { ok: true };
  }};
  const store = { async read(_, id) { return docs.get(id); }, async put(_, value) { docs.set(value.id, value); } };
  const states = [];
  const access = new EditingAccess(api, store, { async run() {} }, (...state) => states.push(state));
  return { api, access, calls, states, docs };
}

test("open latest and explicit handoff retains one active editing session", async () => {
  const f = fixture();
  try {
    assert.equal(await f.access.open("one"), true);
    assert.equal(f.access.active.id, "one");
    await f.access.end();
    assert.equal(f.access.active, null);
    assert.equal(f.states.at(-1)[0], false);
    assert.equal(f.calls.filter(([route]) => route === "api/editor/release").length, 1);
  } finally { f.access.stop(); }
});

test("unsynced old draft prevents releasing ownership", async () => {
  const f = fixture();
  try {
    await f.access.open("one");
    f.docs.get("one").dirty = true;
    await assert.rejects(f.access.open("two"), /尚未同步/);
    assert.equal(f.access.active.id, "one");
    assert.equal(f.calls.filter(([route]) => route === "api/editor/release").length, 0);
  } finally { f.access.stop(); }
});

test("background writes use temporary ownership but active writes retain it", async () => {
  const f = fixture();
  try {
    await f.access.open("one");
    await f.access.write({ id: "one" });
    assert.equal(f.calls.filter(([route]) => route === "api/editor/release").length, 0);
    await f.access.write({ id: "two" });
    assert.equal(f.calls.filter(([route]) => route === "api/editor/release").length, 1);
    assert.ok(f.calls.find(([route]) => route === "api/sync")[1].lease_token);
  } finally { f.access.stop(); }
});

test("expired ownership suspends editing without deleting document", async () => {
  const f = fixture();
  try {
    await f.access.open("one");
    f.access.active.deadline = 0;
    f.access.lastRenew = performance.now();
    await f.access.tick();
    assert.equal(f.states.at(-1)[0], false);
    assert.equal(f.docs.get("one").content, "最新");
  } finally { f.access.stop(); }
});

test("blocked document automatically opens after owner releases without a second click", async () => {
  const f = fixture();
  const request = f.api.request.bind(f.api);
  let blocked = true;
  f.api.request = async (route, body) => {
    if (route === "api/editor/open" && blocked) throw Object.assign(new Error("电脑端占用"), {status: 423});
    return request(route, body);
  };
  try {
    await assert.rejects(f.access.open("one"), /占用/);
    blocked = false;
    f.access.retryAt = -1;
    await f.access.tick();
    assert.equal(f.access.active.id, "one");
    assert.equal(f.states.at(-1)[0], true);
  } finally { f.access.stop(); }
});

test("background client does not keep renewing ownership", async () => {
  const f = fixture();
  try {
    await f.access.open("one");
    f.access.foreground = false;
    f.access.lastRenew = -10000;
    await f.access.tick();
    assert.equal(f.calls.filter(([route]) => route === "api/editor/renew").length, 0);
  } finally { f.access.stop(); }
});

test("end while opening never leaves a new lock behind", async () => {
  const f = fixture();
  let complete;
  f.access.sync.run = () => new Promise(resolve => { complete = resolve; });
  try {
    const opening = f.access.open("one");
    const ending = f.access.end();
    complete();
    await opening;
    f.access.sync.run = async () => {};
    await ending;
    assert.equal(f.access.active, null);
    assert.equal(f.access.paused, true);
    assert.equal(f.calls.filter(([route]) => route === "api/editor/open").length, 0);
  } finally { f.access.stop(); }
});

test("failed final sync still releases ownership and preserves local draft", async () => {
  const f = fixture();
  try {
    await f.access.open("one");
    f.docs.get("one").dirty = true;
    f.access.sync.run = async () => { throw new Error("断网"); };
    await assert.rejects(f.access.end(), /断网/);
    assert.equal(f.access.active, null);
    assert.equal(f.docs.get("one").content, "最新");
    assert.equal(f.calls.filter(([route]) => route === "api/editor/release").length, 1);
    await f.access.tick();
    assert.equal(f.calls.filter(([route]) => route === "api/editor/open").length, 1);
  } finally { f.access.stop(); }
});

test("failed renewal automatically reacquires instead of freezing forever", async () => {
  const f = fixture();
  const request = f.api.request.bind(f.api);
  try {
    await f.access.open("one");
    f.api.request = async (route, body) => {
      if (route === "api/editor/renew") throw new Error("过期");
      return request(route, body);
    };
    f.access.lastRenew = -10000;
    await f.access.tick();
    assert.equal(f.states.at(-1)[0], false);
    f.access.retryAt = -1;
    await f.access.tick();
    assert.equal(f.states.at(-1)[0], true);
  } finally { f.access.stop(); }
});
