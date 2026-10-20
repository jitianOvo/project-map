import { Api, native } from "./api.js";

async function bridgeCall(method, ...args) {
  const bridge = native();
  if (!bridge?.[method]) return undefined;
  if (window.AndroidBridge) return bridge[method](...args);
  return new Promise((resolve) => bridge[method](...args, resolve));
}

export class RememberedApi extends Api {
  constructor(endpoint, prefs, device, onChange = () => {}) {
    super(endpoint);
    Object.assign(this, { prefs, device, onChange });
    this.account = {};
    this.generation = 0;
    this.renewing = null;
  }
  get storageKey() {
    return "project-map-login:" + this.endpoint;
  }
  savePreferences() {
    localStorage.setItem("project-map-preferences", JSON.stringify(this.prefs));
  }
  async persist() {
    const remember = this.prefs.autoLogin !== false && !!this.token;
    if (native()?.saveLogin) {
      const ok = remember
        ? await bridgeCall("saveLogin", this.endpoint, JSON.stringify(this.account))
        : await bridgeCall("clearLogin", this.endpoint);
      if (!ok) throw new Error("无法保存自动登录状态，请重新登录或取消记住登录");
      localStorage.removeItem(this.storageKey);
    } else if (remember) {
      localStorage.setItem(this.storageKey, JSON.stringify(this.account));
    } else localStorage.removeItem(this.storageKey);
    localStorage.removeItem("project-map-token:" + this.endpoint);
  }
  async restore() {
    if (this.prefs.autoLogin === false) {
      await this.persist();
      return;
    }
    let account = {};
    try {
      const stored = await bridgeCall("readLogin", this.endpoint);
      account = JSON.parse(stored === undefined ? localStorage.getItem(this.storageKey) || "{}" : stored);
      const legacy = localStorage.getItem("project-map-token:" + this.endpoint);
      if (!account.token && legacy) account = { token: legacy, refresh_token: "", username: this.prefs.username || "owner" };
      if (account.error) throw new Error(account.error);
      if (typeof account.token !== "string" || typeof (account.refresh_token || "") !== "string") account = {};
      this.account = account;
      this.token = account.token || "";
      if (legacy) await this.persist();
    } catch {
      this.account = {};
      this.token = "";
      await this.persist();
    }
  }
  async login(username, password, remember) {
    const generation = ++this.generation;
    const result = await new Api(this.endpoint).request("api/login", {
      username: username.trim(), password, device_id: this.device, auto_login: !!remember,
    });
    if (generation !== this.generation) throw new Error("登录状态已改变，请重试");
    this.account = { token: result.token, refresh_token: result.refresh_token || "", username: username.trim() };
    this.token = result.token;
    Object.assign(this.prefs, { username: username.trim(), autoLogin: !!remember });
    this.savePreferences();
    await this.persist();
    this.onChange();
  }
  async forget() {
    ++this.generation;
    this.account = {};
    this.token = "";
    await this.persist();
    this.onChange();
  }
  async logout() {
    const account = { ...this.account };
    await this.forget();
    try {
      if (account.refresh_token)
        await new Api(this.endpoint).request("api/session/logout", { refresh_token: account.refresh_token });
      else if (account.token)
        await new Api(this.endpoint, account.token).request("api/logout", {});
    } catch {}
  }
  async setRemember(value) {
    this.prefs.autoLogin = !!value;
    this.savePreferences();
    await this.persist();
  }
  async renew() {
    const generation = this.generation;
    const result = await new Api(this.endpoint).request("api/session/refresh", { refresh_token: this.account.refresh_token });
    if (generation !== this.generation) throw new Error("登录状态已改变，请重试");
    this.account.token = this.token = result.token;
    await this.persist();
    this.onChange();
  }
  async request(path, body) {
    const token = this.token;
    try {
      return await super.request(path, body);
    } catch (error) {
      if (error.status !== 401) throw error;
      if (!this.account.refresh_token) {
        await this.forget();
        throw error;
      }
    }
    try {
      if (this.token === token) {
        if (!this.renewing) this.renewing = this.renew().finally(() => { this.renewing = null; });
        await this.renewing;
      }
      return await super.request(path, body);
    } catch (error) {
      if (error.status === 401) await this.forget();
      throw error;
    }
  }
}
