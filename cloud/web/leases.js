import { payload, uuid } from "./core.js";

export class EditingAccess {
  constructor(api, store, sync, onAccess, retryOpen = null) {
    Object.assign(this, { api, store, sync, onAccess });
    const key = "project-map-editor-client";
    this.client = globalThis.AndroidBridge
      ? localStorage.getItem(key) || uuid() : uuid();
    if (globalThis.AndroidBridge) localStorage.setItem(key, this.client);
    this.active = null;
    this.wanted = null;
    this.paused = false;
    this.foreground = true;
    this.switching = false;
    this.lastRenew = 0;
    this.retryAt = 0;
    this.renewing = false;
    this.retryOpen = retryOpen || ((id) => this.open(id));
    this.timer = setInterval(() => this.tick(), 1000);
  }
  proof(lease = this.active) {
    return { id: lease.id, client_id: lease.client_id, lease_token: lease.lease_token };
  }
  remember(reply, client = this.client, started = performance.now()) {
    return { ...reply, client_id: client, deadline: started + (reply.expires_in - 5) * 1000 };
  }
  open(id) {
    if (this.switching || this.ending || !this.foreground) return Promise.resolve(false);
    this.paused = false;
    this.wanted = id;
    this.switching = true;
    this.opening = this.acquire(id).finally(() => { this.switching = false; });
    return this.opening;
  }
  async acquire(id) {
    if (!this.api.token) {
      this.onAccess(true, "");
      return true;
    }
    this.onAccess(false, "正在保存同步并确认编辑占用…");
    let acquired = null;
    try {
      await this.sync.run();
      if (this.paused || !this.foreground) return false;
      if (this.active && (await this.store.read("docs", this.active.id))?.dirty)
        throw new Error("当前大纲尚未同步，暂时不能切换；内容保存在本机，将自动重试。");
      if (id) {
        const started = performance.now();
        acquired = this.remember(await this.api.request("api/editor/open", {
          id, client_id: this.client, recover: this.active?.id !== id,
        }), this.client, started);
        const local = await this.store.read("docs", id);
        if (local?.dirty) throw new Error("这份大纲还有本地待同步修改，正在自动重试。");
        if (acquired.document) {
          const latest = acquired.document;
          await this.store.put("docs", { ...latest, base: payload(latest), dirty: false, pending: null, generation: local?.generation || 0 });
        }
      }
      if (this.active && this.active.id !== id)
        await this.api.request("api/editor/release", this.proof());
      if (acquired && acquired.deadline <= performance.now()) throw new Error("加载期间占用已到期，正在自动恢复");
      this.active = acquired;
      this.lastRenew = performance.now();
      this.retryAt = 0;
      if (this.paused || !this.foreground) return false;
      this.onAccess(true, acquired ? "正在本端编辑 · 另一端暂不能打开此大纲" : "");
      return true;
    } catch (error) {
      if (acquired && acquired.id !== this.active?.id) {
        try { await this.api.request("api/editor/release", this.proof(acquired)); } catch {}
      }
      const keepEditing = !!this.active && this.active.id !== id && this.active.deadline > performance.now();
      if (!keepEditing && this.active) this.active.deadline = 0;
      if (keepEditing) this.wanted = this.active.id;
      this.retryAt = performance.now() + 2000;
      this.onAccess(keepEditing, error.message + (keepEditing ? "" : " · 正在自动重试"));
      throw error;
    }
  }
  async write(body) {
    const retained = this.active?.id === body.id;
    const client = retained ? this.client : uuid();
    const started = performance.now();
    const lease = this.remember(await this.api.request("api/editor/open", { id: body.id, client_id: client }), client, started);
    if (retained) this.active = lease;
    try {
      return await this.api.request("api/sync", { ...body, ...this.proof(lease) });
    } finally {
      if (!retained) {
        try { await this.api.request("api/editor/release", this.proof(lease)); } catch {}
      }
    }
  }
  end() {
    this.paused = true;
    this.wanted = null;
    this.retryAt = 0;
    if (!this.ending) this.ending = this.release().finally(() => { this.ending = null; });
    return this.ending;
  }
  async release() {
    try {
      if (this.switching) await this.opening.catch(() => {});
      await this.sync.run();
    } finally {
      const lease = this.active;
      this.active = null;
      try {
        if (lease) await this.api.request("api/editor/release", this.proof(lease));
      } finally {
        if (this.api.token) this.onAccess(false, "本端已结束编辑；点击继续编辑可重新取得占用。未同步内容仍保存在本机。");
      }
    }
  }
  suspend() {
    if (this.active) this.active.deadline = 0;
    this.retryAt = performance.now() + 2000;
    if (this.api.token) this.onAccess(false, "连接中断 · 草稿保存在本机，联网后会自动恢复");
  }
  leave() {
    this.foreground = false;
    this.paused = true;
    this.wanted = null;
    const lease = this.active;
    this.active = null;
    if (!lease || !this.api.token) return;
    if (globalThis.AndroidBridge) {
      this.api.request("api/editor/release", this.proof(lease)).catch(() => {});
    } else {
      fetch(this.api.endpoint + "api/editor/release", {
        method: "POST", keepalive: true, credentials: "omit",
        headers: { "Content-Type": "application/json", Authorization: "Bearer " + this.api.token },
        body: JSON.stringify(this.proof(lease)),
      }).catch(() => {});
    }
  }
  async tick() {
    if (!this.foreground || this.paused || this.switching || !this.api.token) return;
    const lease = this.active;
    if (!lease || lease.deadline <= performance.now()) {
      if (lease && !this.retryAt) this.suspend();
      if (this.wanted && performance.now() >= this.retryAt) {
        this.retryAt = performance.now() + 2000;
        try { await this.retryOpen(this.wanted); } catch {}
      }
      return;
    }
    if (this.renewing || performance.now() - this.lastRenew < (lease.heartbeat_in || 5) * 1000) return;
    this.renewing = true;
    this.lastRenew = performance.now();
    const started = performance.now();
    try {
      const reply = await this.api.request("api/editor/renew", this.proof(lease));
      if (this.active === lease) lease.deadline = started + (reply.expires_in - 5) * 1000;
    } catch { if (this.active === lease) this.suspend(); }
    finally { this.renewing = false; }
  }
  stop() { clearInterval(this.timer); }
}
