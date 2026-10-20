import { $, dialog, el, field, toast } from "./ui.js";
import { normalizeEndpoint } from "./api.js";
import { RememberedApi } from "./auth.js";

export function readPrefs() {
  try {
    return JSON.parse(localStorage.getItem("project-map-preferences") || "{}");
  } catch {
    return {};
  }
}
export function writePrefs(prefs) {
  localStorage.setItem("project-map-preferences", JSON.stringify(prefs));
}
export function toolList(choices, prefs, key) {
  const stored = prefs[key] || [],
    known = new Set(choices.map((c) => c[0]));
  const values = stored.filter((t) => known.has(t.id)),
    present = new Set(values.map((t) => t.id));
  return [
    ...values,
    ...choices
      .filter((t) => !present.has(t[0]))
      .map((t) => ({ id: t[0], enabled: true })),
  ];
}
export async function settings(prefs, format, quick, onApply) {
  const theme = field("主题", "select", prefs.theme || "light", [
      ["light", "浅色"],
      ["dark", "深色"],
    ]),
    editorWrap = field("编辑区自动换行", "checkbox", prefs.editorWrap || false),
    previewWrap = field(
      "预览区自动换行",
      "checkbox",
      prefs.previewWrap !== false,
    );
  const formats = toolList(format, prefs, "format"),
    quicks = toolList(quick, prefs, "quick");
  const makeTools = (title, items, choices) => {
    const box = el("div");
    box.append(el("h3", title));
    const rows = el("div");
    box.append(rows);
    const render = () => {
      rows.replaceChildren();
      for (const [index, item] of items.entries()) {
        const row = el("div", "", "tool-setting"),
          check = document.createElement("input");
        check.type = "checkbox";
        check.checked = item.enabled;
        check.onchange = () => (item.enabled = check.checked);
        row.append(check, el("span", choices.find((c) => c[0] === item.id)[2]));
        for (const [offset, label] of [
          [-1, "↑"],
          [1, "↓"],
        ]) {
          const b = el("button", label);
          b.type = "button";
          b.disabled = index + offset < 0 || index + offset >= items.length;
          b.onclick = () => {
            [items[index], items[index + offset]] = [
              items[index + offset],
              items[index],
            ];
            render();
          };
          row.append(b);
        }
        rows.append(row);
      }
    };
    render();
    return box;
  };
  await dialog(
    "设置",
    [
      theme.wrapper,
      editorWrap.wrapper,
      previewWrap.wrapper,
      makeTools("快速工具", quicks, quick),
      makeTools("格式工具", formats, format),
      el("p", "隐藏工具不影响快捷键。窄屏工具栏可横向滑动。", "form-hint"),
    ],
    async () => {
      Object.assign(prefs, {
        theme: theme.input.value,
        editorWrap: editorWrap.input.checked,
        previewWrap: previewWrap.input.checked,
        format: formats,
        quick: quicks,
      });
      writePrefs(prefs);
      onApply();
    },
    "保存设置",
  );
}
export async function login(api, prefs, device, onLogin) {
  const endpoint = field("服务器地址", "url", api.endpoint),
    username = field("账户", "text", prefs.username || "owner"),
    password = field("密码", "password", ""),
    remember = field("记住登录，下次自动登录", "checkbox", prefs.autoLogin !== false);
  username.input.autocomplete = "username";
  password.input.autocomplete = "current-password";
  const info = el(
    "p",
    "自动登录记住的是登录令牌，不保存密码。取消勾选只登录本次；退出账号会清除本机自动登录。登录后同步当前服务器工作区，应用账户与 SSH 账户独立。",
    "form-hint",
  );
  await dialog(
    "连接你的云端",
    [endpoint.wrapper, username.wrapper, password.wrapper, remember.wrapper, info],
    async () => {
      const next = normalizeEndpoint(endpoint.input.value);
      if (next !== api.endpoint) {
        await new RememberedApi(next, prefs, device).login(username.input.value, password.input.value, remember.input.checked);
        prefs.endpoint = next;
        writePrefs(prefs);
        location.reload();
        return;
      }
      await api.login(username.input.value, password.input.value, remember.input.checked);
      password.input.value = "";
      onLogin();
    },
    "登录并同步",
  );
}
