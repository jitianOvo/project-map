import test from "node:test";
import assert from "node:assert/strict";
import { Api, initializeNative } from "../web/api.js";
import { RememberedApi } from "../web/auth.js";

const endpoint = "http://127.0.0.1:18770/";
const original = Api.prototype.request;
async function reset() {
  const values = new Map();
  globalThis.window = {};
  globalThis.localStorage = {
    getItem: key => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: key => values.delete(key),
  };
  await initializeNative();
  Api.prototype.request = async function(path) {
    if (path === "api/login") return { token: "access-test", refresh_token: "remember-test" };
    return { ok: true };
  };
  return values;
}
test.after(() => { Api.prototype.request = original; });

test("remembered login restores without keeping a password", async () => {
  const values = await reset(), prefs = {};
  const api = new RememberedApi(endpoint, prefs, "测试");
  await api.login("owner", "password-not-to-store", true);
  const restored = new RememberedApi(endpoint, prefs, "测试");
  await restored.restore();
  assert.equal(restored.token, "access-test");
  assert.equal(restored.account.refresh_token, "remember-test");
  assert.ok(![...values.values()].join("").includes("password-not-to-store"));
});

test("unchecked login works now but does not restore next time", async () => {
  await reset();
  const prefs = {}, api = new RememberedApi(endpoint, prefs, "测试");
  await api.login("owner", "test-only", false);
  assert.equal(api.token, "access-test");
  const restored = new RememberedApi(endpoint, prefs, "测试");
  await restored.restore();
  assert.equal(restored.token, "");
});

test("parallel expired requests use one renewal", async () => {
  await reset();
  const api = new RememberedApi(endpoint, {}, "测试");
  await api.login("owner", "test-only", true);
  let renewals = 0;
  Api.prototype.request = async function(path) {
    if (path === "api/session/refresh") {
      renewals++;
      await new Promise(resolve => setTimeout(resolve, 15));
      return { token: "renewed-test" };
    }
    if (this.token === "access-test") throw Object.assign(new Error("expired"), { status: 401 });
    return { ok: true };
  };
  const result = await Promise.all([api.request("api/changes"), api.request("api/media/123")]);
  assert.equal(renewals, 1);
  assert.ok(result.every(value => value.ok));
  assert.equal(api.token, "renewed-test");
  const restored = new RememberedApi(endpoint, api.prefs, "测试");
  await restored.restore();
  assert.equal(restored.token, "renewed-test");
});

test("revoked remembered login is cleared instead of looping", async () => {
  await reset();
  const api = new RememberedApi(endpoint, {}, "测试");
  await api.login("owner", "test-only", true);
  Api.prototype.request = async () => { throw Object.assign(new Error("revoked"), { status: 401 }); };
  await assert.rejects(api.request("api/changes"));
  assert.equal(api.token, "");
  assert.equal(localStorage.getItem(api.storageKey), null);
});

test("offline renewal retains the remembered session for retry", async () => {
  await reset();
  const api = new RememberedApi(endpoint, {}, "测试");
  await api.login("owner", "test-only", true);
  Api.prototype.request = async function(path) {
    throw Object.assign(new Error("temporary"), { status: path === "api/session/refresh" ? 503 : 401 });
  };
  await assert.rejects(api.request("api/changes"));
  assert.equal(api.account.refresh_token, "remember-test");
  assert.ok(localStorage.getItem(api.storageKey));
});

test("logout cannot be undone by an in-flight renewal", async () => {
  await reset();
  const api = new RememberedApi(endpoint, {}, "测试");
  await api.login("owner", "test-only", true);
  let finish;
  Api.prototype.request = async function(path) {
    if (path === "api/session/refresh") return new Promise(resolve => { finish = resolve; });
    if (path === "api/session/logout") return { ok: true };
    throw Object.assign(new Error("expired"), { status: 401 });
  };
  const pending = api.request("api/changes");
  await new Promise(resolve => setTimeout(resolve, 0));
  await api.logout();
  finish({ token: "must-not-restore" });
  await assert.rejects(pending);
  assert.equal(api.token, "");
  assert.equal(localStorage.getItem(api.storageKey), null);
});

test("Android vault is used and old plaintext token is removed", async () => {
  const values = await reset();
  const vault = new Map();
  window.AndroidBridge = {
    readLogin: endpoint => vault.get(endpoint) || "{}",
    saveLogin: (endpoint, data) => { vault.set(endpoint, data); return true; },
    clearLogin: endpoint => { vault.delete(endpoint); return true; },
  };
  await initializeNative();
  localStorage.setItem("project-map-token:" + endpoint, "legacy-test");
  const api = new RememberedApi(endpoint, {}, "测试");
  await api.restore();
  assert.equal(api.token, "legacy-test");
  assert.equal(localStorage.getItem("project-map-token:" + endpoint), null);
  assert.ok(vault.has(endpoint));
  await api.login("owner", "password-not-to-store", true);
  assert.ok(![...values.values()].join("").includes("access-test"));
  assert.ok(![...vault.values()].join("").includes("password-not-to-store"));
  await api.setRemember(false);
  assert.equal(vault.size, 0);
});
