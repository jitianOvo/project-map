import {
  Api,
  DEFAULT_ENDPOINT,
  clipboardContent,
  copyText,
  initializeNative,
  native,
} from "./api.js";
import { Store } from "./store.js";
import { RememberedApi } from "./auth.js";
import { Sync } from "./sync.js";
import { EditingAccess } from "./leases.js";
import { uuid } from "./core.js";
import { Editor, TOOLS } from "./editor.js";
import { Preview } from "./preview.js";
import { Library } from "./library.js";
import { Find } from "./find.js";
import { decode, download, Media } from "./media.js";
import {
  login,
  readPrefs,
  settings,
  toolList,
  writePrefs,
} from "./settings.js";
import { $, contextMenu, dialog, el, field, toast } from "./ui.js";

let active = null,
  lifecycle = 0,
  saveTimer,
  renderTimer,
  assistantTab = "outline",
  restorePosition = false;
const pending = new Map();
const prefs = readPrefs(),
  mobile = innerWidth <= 760;
if (prefs.libraryHidden === undefined) prefs.libraryHidden = mobile;
if (prefs.assistantHidden === undefined) prefs.assistantHidden = true;
if (prefs.mode === undefined) prefs.mode = mobile ? "edit" : "split";
await initializeNative();
const endpoint =
  prefs.endpoint ||
  (native() ? DEFAULT_ENDPOINT : new URL("./", location.href).href);
const device =
  localStorage.getItem("project-map-device") ||
  (mobile ? "手机" : "电脑") + "-" + uuid().slice(0, 8);
localStorage.setItem("project-map-device", device);
const api = new RememberedApi(endpoint, prefs, device);
await api.restore();
const store = await Store.open(api.endpoint);
const editor = new Editor(
  $("#editor"),
  changed,
  (files) => images(files).catch((error) => toast(error.message)),
  () => insertLink(),
);
const preview = new Preview(
  $("#preview"),
  (url) => media.open(url),
  (line) => toggleTask(line),
);
const media = new Media(store, api, preview),
  finder = new Find(editor);
const library = new Library(store, select, (id) => libraryChanged(id), () => {
  prefs.libraryHidden = true;
  writePrefs(prefs);
  applyPrefs();
});
const sync = new Sync(
  store,
  api,
  device,
  (change) => remoteChanged(change),
  (text) => { $("#syncStatus").textContent = text; $("#accountButton").textContent = api.token ? "账户" : "登录"; },
  save,
);
const access = new EditingAccess(api, store, sync, (allowed, message) => {
  $("#editor").readOnly = !allowed;
  $("#editingBanner").hidden = !message;
  $("#editingMessage").textContent = message;
  $("#resumeEditing").hidden = allowed;
  $("#endEditing").hidden = !allowed;
  for (const button of $("#formatTools").querySelectorAll("button")) button.disabled = !allowed;
}, (id) => select(id, true));
sync.write = (body) => access.write(body);
$("#resumeEditing").onclick = () => select(active).catch(error => toast(error.message));
$("#endEditing").onclick = () => access.end().catch(error => toast(error.message));

async function save() {
  clearTimeout(saveTimer);
  for (const [id, content] of [...pending]) {
    pending.delete(id);
    try {
      await store.edit(id, { content });
    } catch (error) {
      pending.set(id, content);
      toast("本地保存失败，请立即导出备份：" + error.message);
      throw error;
    }
  }
  if (active) await rememberPosition();
}
function changed() {
  if (!active) return;
  pending.set(active, $("#editor").value);
  clearTimeout(saveTimer);
  saveTimer = setTimeout(
    () =>
      save()
        .then(() => sync.schedule())
        .catch(() => {}),
    90,
  );
  clearTimeout(renderTimer);
  renderTimer = setTimeout(render, 100);
  position();
  $("#syncStatus").textContent = api.token
    ? "本地已保存 · 等待同步"
    : "本地已保存 · 未登录";
}
async function rememberPosition() {
  if (!active) return;
  const b = $("#editor"),
    p = $("#preview");
  await store.meta("position:" + active, {
    start: b.selectionStart,
    end: b.selectionEnd,
    top: b.scrollTop,
    left: b.scrollLeft,
    previewTop: p.scrollTop,
    previewLeft: p.scrollLeft,
  });
}
async function select(id, automatic = false) {
  await save();
  try {
    if (await access.open(id) === false) return false;
  } catch (error) {
    if (!automatic) toast(error.message);
    return false;
  }
  active = id;
  library.selected = id;
  await store.meta("active", id);
  const doc = id ? await store.read("docs", id) : null;
  $("#editor").disabled = !doc;
  $("#emptyState").hidden = !!doc;
  $("#documentTitle").textContent = doc?.title || "选择或新建一个项目";
  $("#editor").value = doc?.content || "";
  render();
  if (doc) {
    const pos = await store.meta("position:" + id);
    if (pos) {
      restorePosition = true;
      $("#editor").setSelectionRange(pos.start, pos.end);
      $("#editor").scrollTop = pos.top;
      $("#editor").scrollLeft = pos.left;
      $("#preview").scrollTop = pos.previewTop;
      $("#preview").scrollLeft = pos.previewLeft;
      requestAnimationFrame(() => {
        $("#preview").scrollTop = pos.previewTop;
        restorePosition = false;
      });
    }
  }
  library.render();
  position();
}
function render() {
  clearTimeout(renderTimer);
  preview.render($("#editor").value);
  media.hydrate($("#editor").value);
  renderAssistant();
}
async function libraryChanged(id) {
  sync.schedule();
  if (id === active) {
    const doc = await store.read("docs", id);
    $("#documentTitle").textContent = doc.title;
    renderAssistant();
  }
}
async function remoteChanged(change) {
  await library.refresh();
  if (change.switchTo && active === change.id) {
    await save();
    const latest = pending.get(active);
    await select(change.switchTo);
    toast("同时修改已保留为冲突副本，请检查两份内容");
    return;
  }
  if (change.id === active && !pending.has(active)) {
    const doc = await store.read("docs", active);
    if (doc && !doc.deleted && $("#editor").value !== doc.content) {
      const b = $("#editor"),
        start = b.selectionStart,
        end = b.selectionEnd,
        top = b.scrollTop,
        left = b.scrollLeft;
      b.value = doc.content;
      b.setSelectionRange(
        Math.min(start, b.value.length),
        Math.min(end, b.value.length),
      );
      b.scrollTop = top;
      b.scrollLeft = left;
      render();
    }
    if (doc) $("#documentTitle").textContent = doc.title;
    if (doc?.deleted) await select(null);
  }
  if (change.remote && active) media.hydrate($("#editor").value);
}
function position() {
  const b = $("#editor"),
    before = b.value.slice(0, b.selectionStart),
    line = before.split("\n").length,
    column = b.selectionStart - before.lastIndexOf("\n");
  $("#positionStatus").textContent =
    `行 ${line} · 列 ${column} · ${b.value.length} 字`;
}
function renderAssistant() {
  const pane = $("#assistantContent"),
    lines = $("#editor").value.split("\n");
  pane.replaceChildren();
  if (assistantTab === "outline")
    for (const [line, text] of lines.entries()) {
      const match = text.match(/^(#{1,6})\s+(.+)$/);
      if (match) {
        const b = el("button", match[2], "outline-item");
        b.style.paddingLeft = +match[1].length * 9 + "px";
        b.onclick = () => goLine(line);
        pane.append(b);
      }
    }
  if (assistantTab === "tasks")
    for (const [line, text] of lines.entries()) {
      const match = text.match(/^\s*- \[([ xX])\] (.*)$/);
      if (match) {
        const b = el(
          "button",
          (match[1] === " " ? "□ " : "✓ ") + match[2],
          "task-item" + (match[1] === " " ? "" : " done"),
        );
        b.onclick = () => toggleTask(line);
        pane.append(b);
      }
    }
  if (assistantTab === "info") {
    const doc = library.current();
    if (doc)
      for (const [label, value] of [
        ["分组", doc.group],
        ["说明", doc.description || "暂无说明"],
        ["项目位置", doc.project_path || "未填写"],
        ["云端版本", String(doc.revision)],
        ["同步状态", doc.dirty ? "有本地修改" : "已同步"],
        ["项目 ID", doc.id],
        ["设备", device],
      ])
        pane.append(
          el("div", label, "info-label"),
          el("div", value, "info-value"),
        );
  }
}
function goLine(line) {
  const b = $("#editor"),
    offset =
      b.value.split("\n").slice(0, line).join("\n").length + (line ? 1 : 0);
  b.focus();
  b.setSelectionRange(offset, offset);
  b.scrollTop = line * parseFloat(getComputedStyle(b).lineHeight);
  position();
}
function toggleTask(line) {
  if (!active || $("#editor").readOnly) return;
  const b = $("#editor"),
    lines = b.value.split("\n"),
    match = lines[line]?.match(/^(\s*- )\[([ xX])\](.*)$/);
  if (!match) return;
  lines[line] =
    match[1] + "[" + (match[2] === " " ? "x" : " ") + "]" + match[3];
  const start = b.selectionStart,
    end = b.selectionEnd;
  editor.apply({
    start: 0,
    end: b.value.length,
    replacement: lines.join("\n"),
    selection: [start, end],
  });
}
async function images(files) {
  if ($("#editor").readOnly) throw new Error("请先取得本端编辑占用再插入图片");
  if (!active) {
    toast("请先选择或新建项目");
    return;
  }
  const id = active,
    markdown = [];
  for (const file of files) markdown.push((await media.cache(file)).markdown);
  const content = "\n" + markdown.join("\n\n") + "\n";
  if (id === active) editor.insert(content);
  else {
    const doc = await store.read("docs", id);
    await store.edit(id, { content: doc.content + content });
  }
  sync.schedule();
}
async function paste() {
  if ($("#editor").readOnly) throw new Error("请先点击继续编辑，再粘贴内容");
  const content = await clipboardContent();
  if (content.error) throw new Error(content.error);
  const files = (content.images || []).map((image) =>
    image instanceof Blob
      ? new File([image], "粘贴图片", { type: image.type })
      : new File([decode(image.data)], image.name || "粘贴图片", {
          type: image.mime,
        }),
  );
  if (files.length) await images(files);
  else if (content.text) editor.insert(content.text);
}
async function insertLink() {
  const title = field(
      "链接文字",
      "text",
      $("#editor").value.slice(
        $("#editor").selectionStart,
        $("#editor").selectionEnd,
      ) || "链接",
    ),
    url = field("链接地址", "url", "https://");
  await dialog(
    "插入链接",
    [title.wrapper, url.wrapper],
    async () => {
      if (!/^https?:\/\//.test(url.input.value))
        throw new Error("请输入 http 或 https 地址");
      editor.insert(
        "[" +
          title.input.value.replace(/[\[\]]/g, "") +
          "](" +
          url.input.value.replace(/[\s()]/g, encodeURIComponent) +
          ")",
      );
    },
    "插入",
  );
}
async function importFiles(files) {
  for (const file of files) {
    if (file.size > 50 * 1024 * 1024) throw new Error("导入文件最多 50 MB");
    const text = await file.text();
    if (file.name.endsWith(".json")) await media.importBackup(text);
    else {
      if (new TextEncoder().encode(text).length > 2 * 1024 * 1024)
        throw new Error("单个 Markdown 最多 2 MB");
      const doc = await store.create({
        title: file.name.replace(/\.(md|markdown)$/i, ""),
        content: text,
        order: Date.now(),
      });
      await library.refresh();
      await select(doc.id);
    }
  }
  await library.refresh();
  sync.schedule();
}
async function exportCurrent() {
  await save();
  const doc = active ? await store.read("docs", active) : null;
  if (!doc) {
    toast("请先选择项目");
    return;
  }
  download(
    doc.title.replace(/[\\/:*?"<>|]/g, "_") + ".md",
    "text/markdown",
    doc.content,
  );
  toast("Markdown 已导出；跨设备完整迁移请使用「导出备份」");
}
async function history() {
  if (!active || !api.token) {
    toast("请先选择已同步项目并登录");
    return;
  }
  await save();
  const id = active,
    result = await api.request("api/history/" + id),
    container = el("div");
  for (const version of result.revisions) {
    const row = el("div", "", "group-setting"),
      restore = el("button", "恢复");
    restore.type = "button";
    row.append(
      el(
        "span",
        "版本 " +
          version.revision +
          " · " +
          new Date(version.created * 1000).toLocaleString("zh-CN"),
      ),
      restore,
    );
    restore.onclick = async () => {
      await store.edit(id, { content: version.content });
      $("#dialog").close();
      if (active === id) {
        $("#editor").value = version.content;
        render();
      }
      sync.schedule();
      toast("已恢复为本地修改，将生成新的云端版本");
    };
    container.append(row);
  }
  await dialog(
    "版本历史（最近 50 次同步）",
    [container],
    async () => {},
    "关闭",
  );
}
const quick = [
  ["new", "新建", "新建", "Ctrl+N", () => library.create()],
  [
    "save",
    "保存",
    "保存",
    "Ctrl+S",
    async () => {
      await save();
      await sync.run();
    },
  ],
  ["find", "查找替换", "查找替换", "Ctrl+F", () => finder.show()],
  ["import", "导入", "导入", "Ctrl+G", () => $("#importInput").click()],
  ["properties", "项目属性", "项目属性", "Ctrl+L", () => library.properties()],
  ["refresh", "刷新", "刷新", "Ctrl+E", () => sync.run()],
  [
    "theme",
    "切换主题",
    "切换主题",
    "Ctrl+T",
    () => {
      prefs.theme = prefs.theme === "dark" ? "light" : "dark";
      writePrefs(prefs);
      applyPrefs();
    },
  ],
  [
    "assistant",
    "辅助面板",
    "辅助面板",
    "Ctrl+R",
    () => togglePanel("assistant"),
  ],
  ["export", "导出 MD", "导出 Markdown", "", exportCurrent],
  ["backup", "导出备份", "导出完整备份", "", () => media.exportBackup()],
  ["history", "历史版本", "历史版本", "", history],
];
function toolbars() {
  $("#formatTools").replaceChildren();
  for (const item of toolList(TOOLS, prefs, "format").filter(
    (t) => t.enabled,
  )) {
    const tool = TOOLS.find((t) => t[0] === item.id),
      b = el(
        "button",
        tool[1],
        ["urgent", "high", "normal"].includes(item.id) ? item.id : "",
      );
    b.dataset.tool = item.id;
    b.title = tool[2] + (tool[3] ? " · " + tool[3] : "");
    b.setAttribute("aria-label", tool[2]);
    b.onpointerdown = (event) => event.preventDefault();
    b.onclick = () => {
      if (active) editor.command(item.id);
    };
    $("#formatTools").append(b);
  }
  $("#quickTools").replaceChildren();
  for (const item of toolList(quick, prefs, "quick").filter((t) => t.enabled)) {
    const tool = quick.find((t) => t[0] === item.id),
      b = el("button", tool[1]);
    b.title = tool[2] + (tool[3] ? " · " + tool[3] : "");
    b.onclick = () =>
      Promise.resolve(tool[4]()).catch((error) => toast(error.message));
    $("#quickTools").append(b);
  }
}
function applyPrefs() {
  document.body.classList.toggle("dark", prefs.theme === "dark");
  $("#workspace").classList.toggle("no-library", prefs.libraryHidden);
  $("#workspace").classList.toggle("no-assistant", prefs.assistantHidden);
  $("#panes").dataset.mode = prefs.mode;
  document.querySelectorAll("[data-mode]").forEach((b) => {
    if (b.tagName === "BUTTON")
      b.classList.toggle("active", b.dataset.mode === prefs.mode);
  });
  $("#editor").style.whiteSpace = prefs.editorWrap ? "pre-wrap" : "pre";
  $("#editor").wrap = prefs.editorWrap ? "soft" : "off";
  $("#preview article").style.whiteSpace =
    prefs.previewWrap === false ? "nowrap" : "normal";
  $("#editor").style.fontSize = (15 * (prefs.editorZoom || 100)) / 100 + "px";
  preview.setZoom(prefs.previewZoom || 100);
  $("#zoomButton").textContent =
    `编辑 ${prefs.editorZoom || 100}% · 预览 ${prefs.previewZoom || 100}%`;
  $(".format-shell").classList.toggle("collapsed", !!prefs.formatCollapsed);
  $("#formatToggle").textContent =
    "格式工具 " + (prefs.formatCollapsed ? "▸" : "▾");
  $(".quick-shell").classList.toggle("collapsed", !!prefs.quickCollapsed);
  $("#quickToggle").textContent =
    "快速工具 " + (prefs.quickCollapsed ? "▸" : "▾");
  $("#accountButton").textContent = api.token ? "账户" : "登录";
  toolbars();
}
function togglePanel(name) {
  prefs[name + "Hidden"] = !prefs[name + "Hidden"];
  writePrefs(prefs);
  applyPrefs();
}
$("#toggleLibrary").onclick = () => togglePanel("library");
$("#toggleAssistant").onclick = () => togglePanel("assistant");
$("#closeAssistant").onclick = () => togglePanel("assistant");
$("#formatToggle").onclick = () => {
  prefs.formatCollapsed = !prefs.formatCollapsed;
  writePrefs(prefs);
  applyPrefs();
};
$("#quickToggle").onclick = () => {
  prefs.quickCollapsed = !prefs.quickCollapsed;
  writePrefs(prefs);
  applyPrefs();
};
$("#settingsButton").onclick = () => settings(prefs, TOOLS, quick, applyPrefs);
$("#accountButton").onclick = async () => {
  if (!api.token)
    return login(api, prefs, device, () => {
      applyPrefs();
      sync.start();
      if (active) select(active).catch(error => toast(error.message));
    });
  const remember = field("记住登录，下次自动登录", "checkbox", prefs.autoLogin !== false);
  remember.input.onchange = () => api.setRemember(remember.input.checked).catch(error => toast(error.message));
  await dialog(
    "云端账户",
    [
      el("p", "服务器：" + api.endpoint, "form-hint"),
      el("p", "设备：" + device, "form-hint"),
      el("p", "账户：" + (api.account.username || prefs.username || "owner"), "form-hint"),
      remember.wrapper,
      el(
        "p",
        "退出登录后，本机大纲仍会保留；共享设备请勿留下私人内容。",
        "form-hint",
      ),
    ],
    async () => {
      await access.end();
      await api.logout();
      applyPrefs();
      $("#editor").readOnly = false;
      $("#editingBanner").hidden = true;
      sync.schedule();
    },
    "退出登录",
  );
};
$("#syncButton").onclick = async () => {
  await save();
  if (!api.token) $("#accountButton").click();
  else await sync.run();
};
$("#wrapButton").onclick = async () => {
  const a = field("编辑区启用自动换行", "checkbox", !!prefs.editorWrap),
    b = field("预览区启用自动换行", "checkbox", prefs.previewWrap !== false);
  await dialog(
    "自动换行",
    [a.wrapper, b.wrapper],
    async () => {
      prefs.editorWrap = a.input.checked;
      prefs.previewWrap = b.input.checked;
      writePrefs(prefs);
      applyPrefs();
    },
    "应用",
  );
};
$("#zoomButton").onclick = () => {
  prefs.editorZoom = prefs.previewZoom = 100;
  writePrefs(prefs);
  applyPrefs();
};
for (const [selector, key] of [
  ["#editor", "editorZoom"],
  ["#preview", "previewZoom"],
])
  $(selector).addEventListener(
    "wheel",
    (event) => {
      if (event.ctrlKey) {
        event.preventDefault();
        prefs[key] = Math.max(
          50,
          Math.min(250, (prefs[key] || 100) + (event.deltaY < 0 ? 10 : -10)),
        );
        writePrefs(prefs);
        applyPrefs();
        toast(
          (key === "editorZoom" ? "编辑" : "预览") + " " + prefs[key] + "%",
        );
      }
    },
    { passive: false },
  );
document.querySelectorAll(".mode-buttons button").forEach(
  (b) =>
    (b.onclick = () => {
      prefs.mode = b.dataset.mode;
      writePrefs(prefs);
      applyPrefs();
    }),
);
document.querySelectorAll("[data-tab]").forEach(
  (b) =>
    (b.onclick = () => {
      assistantTab = b.dataset.tab;
      document
        .querySelectorAll("[data-tab]")
        .forEach((item) => item.classList.toggle("active", item === b));
      renderAssistant();
    }),
);
$("#importInput").onchange = (event) =>
  importFiles([...event.target.files])
    .catch((error) => toast(error.message))
    .finally(() => (event.target.value = ""));
$("#imageInput").onchange = (event) =>
  images([...event.target.files])
    .catch((error) => toast(error.message))
    .finally(() => (event.target.value = ""));
$("#editor").addEventListener("contextmenu", (event) =>
  contextMenu(event, [
    ["撤销", () => editor.command("undo")],
    ["重做", () => editor.command("redo")],
    [
      "复制",
      () =>
        copyText(
          $("#editor").value.slice(
            $("#editor").selectionStart,
            $("#editor").selectionEnd,
          ),
        ),
    ],
    ["粘贴", paste],
    ["增加 Vn", () => editor.command("version")],
    ["增加子版本", () => editor.command("subversion")],
    ["减少 Vn", () => editor.command("removeversion")],
    ["紧急", () => editor.command("urgent")],
    ["优先", () => editor.command("high")],
    ["普通", () => editor.command("normal")],
    ["清除优先级", () => editor.command("clearpriority")],
  ]),
);
$("#preview").addEventListener("contextmenu", (event) =>
  contextMenu(event, [
    ["复制选中文本", () => copyText(window.getSelection().toString())],
    [
      "恢复预览大小",
      () => {
        prefs.previewZoom = 100;
        writePrefs(prefs);
        applyPrefs();
      },
    ],
  ]),
);
$("#editor").addEventListener("keyup", position);
$("#editor").addEventListener("click", position);
let positionTimer;
for (const idof of ["#editor", "#preview"])
  $(idof).addEventListener(
    "scroll",
    () => {
      if (restorePosition) return;
      clearTimeout(positionTimer);
      positionTimer = setTimeout(rememberPosition, 200);
    },
    { passive: true },
  );
$("#editor").addEventListener("blur", () => save().catch(() => {}));
document.addEventListener("keydown", (event) => {
  if (!(event.ctrlKey || event.metaKey) || $("#dialog").open) return;
  const key = event.key.toLowerCase(),
    tool = quick.find((t) => t[3] === "Ctrl+" + key.toUpperCase());
  if (tool) {
    event.preventDefault();
    Promise.resolve(tool[4]()).catch((error) => toast(error.message));
  }
});
$("#editor").addEventListener("keydown", (event) => {
  if (
    (event.ctrlKey || event.metaKey) &&
    event.key.toLowerCase() === "v" &&
    native()?.readClipboardContent
  ) {
    event.preventDefault();
    paste().catch((error) => toast(error.message));
  }
});
document.addEventListener("visibilitychange", () => {
  access.foreground = !document.hidden;
  if (document.hidden) {
    window.pauseProjectMap();
  }
  else window.resumeProjectMap();
});
window.addEventListener("offline", () => { save().catch(() => {}); access.suspend(); });
window.addEventListener("online", () => sync.schedule(100));
window.flushProjectMap = () => save();
window.pauseProjectMap = async () => {
  const generation = ++lifecycle;
  access.foreground = false;
  try {
    await save();
    if (generation === lifecycle && !access.foreground) await access.end();
  } catch { if (generation === lifecycle) access.suspend(); }
};
window.resumeProjectMap = () => {
  lifecycle++;
  access.foreground = true;
  const id = active || access.wanted;
  if (id && api.token) {
    access.wanted = id;
    access.paused = false;
    select(id, true).catch(() => {});
  }
  else sync.schedule(100);
};
window.addEventListener("pagehide", () => access.leave());
let resizing = false;
$("#splitter").onpointerdown = (event) => {
  resizing = true;
  event.target.setPointerCapture(event.pointerId);
};
$("#splitter").onpointermove = (event) => {
  if (!resizing) return;
  const rect = $("#panes").getBoundingClientRect(),
    ratio =
      innerWidth <= 760
        ? (event.clientY - rect.top) / rect.height
        : (event.clientX - rect.left) / rect.width;
  prefs.splitRatio = Math.max(0.2, Math.min(0.8, ratio));
  $("#editPane").style.flex = "0 0 " + prefs.splitRatio * 100 + "%";
};
$("#splitter").onpointerup = () => {
  resizing = false;
  writePrefs(prefs);
};
if (prefs.splitRatio)
  $("#editPane").style.flex = "0 0 " + prefs.splitRatio * 100 + "%";
window.addEventListener("unhandledrejection", (event) => {
  toast(event.reason?.message || "操作未完成，本地内容仍保留");
  console.error(event.reason);
});
applyPrefs();
api.onChange = () => applyPrefs();
await library.refresh();
const saved = await store.meta("active");
if (saved && library.docs.some((d) => d.id === saved && !d.deleted))
  await select(saved, true);
else await select(null);
sync.start();
