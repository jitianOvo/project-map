export const DEFAULT_ENDPOINT = "https://jitian666.me/project-map/";
const requests = new Map();
let transport = null;
export function normalizeEndpoint(value) {
  const url = new URL(value);
  if (url.username || url.password || url.search || url.hash)
    throw new Error("服务器地址不能包含密码、参数或锚点");
  if (
    url.protocol !== "https:" &&
    !(
      url.protocol === "http:" &&
      ["127.0.0.1", "localhost"].includes(url.hostname)
    )
  )
    throw new Error("服务器地址必须使用 HTTPS");
  return url.href.replace(/\/?$/, "/");
}
export async function initializeNative() {
  transport = null;
  window.receiveNativeReply = (id, result) => {
    const call = requests.get(id);
    if (call) {
      requests.delete(id);
      clearTimeout(call.timer);
      call.resolve(result);
    }
  };
  if (window.AndroidBridge) transport = window.AndroidBridge;
  else if (window.qt?.webChannelTransport) {
    await new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "qrc:///qtwebchannel/qwebchannel.js";
      script.onload = () =>
        new QWebChannel(qt.webChannelTransport, (channel) => {
          transport = channel.objects.NativeBridge;
          resolve();
        });
      script.onerror = reject;
      document.head.append(script);
    });
  }
  window.NativeBridge = transport;
}
export function native() {
  return transport;
}
export async function clipboardContent() {
  if (transport?.readClipboardContent) {
    const value = window.AndroidBridge
      ? transport.readClipboardContent()
      : await new Promise((resolve) => transport.readClipboardContent(resolve));
    return JSON.parse(value);
  }
  if (navigator.clipboard.read) {
    const result = { text: "", images: [] };
    for (const item of await navigator.clipboard.read())
      for (const type of item.types) {
        if (type.startsWith("image/"))
          result.images.push(await item.getType(type));
        else if (type === "text/plain" && !result.text)
          result.text = await (await item.getType(type)).text();
      }
    return result;
  }
  return { text: await navigator.clipboard.readText(), images: [] };
}
export async function copyText(text) {
  if (transport?.writeClipboard) transport.writeClipboard(text);
  else await navigator.clipboard.writeText(text);
}
export class Api {
  constructor(endpoint, token = "") {
    this.endpoint = normalizeEndpoint(endpoint);
    this.token = token;
  }
  async request(path, body) {
    if (!/^api\/[a-z0-9/?=&_-]+$/i.test(path)) throw new Error("接口路径无效");
    let response;
    if (transport) {
      const id = crypto.getRandomValues(new Uint32Array(4)).join("-");
      response = await new Promise((resolve, reject) => {
        const timer = setTimeout(() => {
          requests.delete(id);
          reject(new Error("连接超时，本地内容已保留"));
        }, 40000);
        requests.set(id, { resolve, timer });
        transport.request(
          id,
          this.endpoint,
          body === undefined ? "GET" : "POST",
          path,
          body === undefined ? "" : JSON.stringify(body),
          this.token,
        );
      });
      if (typeof response === "string") response = JSON.parse(response);
    } else {
      const controller = new AbortController(),
        timer = setTimeout(() => controller.abort(), 35000);
      try {
        const call = await fetch(this.endpoint + path, {
          method: body === undefined ? "GET" : "POST",
          headers: {
            "Content-Type": "application/json",
            ...(this.token ? { Authorization: "Bearer " + this.token } : {}),
          },
          body: body === undefined ? undefined : JSON.stringify(body),
          signal: controller.signal,
          cache: "no-store",
          credentials: "omit",
        });
        response = { status: call.status, body: await call.json() };
      } finally {
        clearTimeout(timer);
      }
    }
    if (response.status < 200 || response.status >= 300) {
      const error = new Error(response.body?.error || "连接失败，请稍后再试");
      error.status = response.status;
      error.details = response.body;
      throw error;
    }
    return response.body;
  }
}
