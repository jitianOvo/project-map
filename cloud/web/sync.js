import { accepted, clone, payload, uuid } from "./core.js";

export class Sync {
  constructor(
    store,
    api,
    device,
    onChange,
    onStatus,
    beforeApply = async () => {},
  ) {
    Object.assign(this, {
      store,
      api,
      device,
      onChange,
      onStatus,
      beforeApply,
    });
    this.busy = false;
    this.delay = 5000;
    this.timer = null;
  }
  start() {
    this.schedule(200);
  }
  schedule(delay = 1500) {
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.run(), delay);
  }
  async pull() {
    let cursor = (await this.store.meta("cursor")) || 0,
      more = true;
    while (more) {
      const result = await this.api.request("api/changes?since=" + cursor);
      await this.beforeApply();
      for (const remote of result.documents) {
        let changed = false;
        await this.store.mutate("docs", remote.id, (entry) => {
          if (entry?.dirty || (entry && entry.revision >= remote.revision))
            return entry;
          changed = true;
          return {
            ...remote,
            base: payload(remote),
            dirty: false,
            generation: entry?.generation || 0,
            pending: null,
          };
        });
        if (changed) this.onChange({ id: remote.id, remote: true });
      }
      cursor = result.cursor;
      more = result.has_more;
      await this.store.meta("cursor", cursor);
    }
  }
  async push(entry) {
    const pending = await this.store.prepare(entry.id);
    if (!pending) return;
    const response = await (this.write || ((body) => this.api.request("api/sync", body)))({
      ...pending,
      device_id: this.device,
    });
    await this.beforeApply();
    let switchTo = null,
      localConflict = null;
    await this.store.mutate("docs", entry.id, (current) => {
      const result = accepted(current, pending, response);
      if (result.conflict) {
        localConflict = {
          ...result.local,
          title: result.local.title + " · 本地冲突副本",
          description: "同步期间继续编辑的内容；未覆盖云端版本。",
        };
        return {
          ...response.document,
          base: payload(response.document),
          dirty: false,
          generation: current.generation,
          pending: null,
        };
      }
      if (response.status === "conflict") {
        switchTo = result.entry;
        return {
          ...response.document,
          base: payload(response.document),
          dirty: false,
          generation: current.generation,
          pending: null,
        };
      }
      return result.entry;
    });
    if (switchTo) await this.store.put("docs", switchTo);
    if (localConflict) {
      switchTo = await this.store.create(localConflict);
    }
    this.onChange({
      id: entry.id,
      switchTo: switchTo?.id,
      conflict: !!switchTo,
      remote: true,
    });
  }
  run() {
    if (!this.running) this.running = this.cycle().finally(() => { this.running = null; });
    return this.running;
  }
  async cycle() {
    if (this.busy) return;
    clearTimeout(this.timer);
    if (!this.api.token) {
      this.onStatus("本地模式 · 登录后可同步");
      return;
    }
    this.busy = true;
    this.onStatus("正在同步…");
    try {
      await this.beforeApply();
      for (const image of await this.store.read("media"))
        if (!image.uploaded) {
          await this.api.request("api/media", {
            id: image.id,
            data: image.data,
          });
          await this.store.put("media", { ...image, uploaded: true });
        }
      await this.pull();
      let occupied = 0;
      for (const doc of await this.store.read("docs"))
        if (doc.dirty) {
          try { await this.push(doc); }
          catch (error) { if (error.status !== 423) throw error; occupied++; }
        }
      await this.pull();
      const pending = (await this.store.read("docs")).filter(
        (doc) => doc.dirty,
      ).length;
      this.onStatus(
        pending
          ? `本地已保存 · ${pending} 项待同步${occupied ? "（另一端正在编辑）" : ""}`
          : "已同步 · " +
              new Date().toLocaleTimeString("zh-CN", {
                hour: "2-digit",
                minute: "2-digit",
              }),
      );
      this.delay = pending ? 1500 : 5000;
    } catch (error) {
      this.delay = Math.min(this.delay * 2, 60000);
      this.onStatus(
        error.status === 401
          ? "登录已过期 · 本地内容已保留"
          : "离线 / 连接未就绪 · 本地内容已保留",
      );
      console.warn("同步暂缓", error.message);
    } finally {
      this.busy = false;
      this.schedule(this.delay);
    }
  }
}
