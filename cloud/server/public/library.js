import { $, contextMenu, dialog, el, field, toast } from "./ui.js";
import { native } from "./api.js";

export class Library {
  constructor(store, onSelect, onEdit, onMobileSelect) {
    Object.assign(this, { store, onSelect, onEdit, onMobileSelect });
    this.selected = null;
    this.docs = [];
    this.trash = false;
    $("#projectSearch").oninput = () => this.render();
    $("#groupFilter").onchange = () => this.render();
    $("#newButton").onclick = () => this.create();
    $("#emptyNew").onclick = () => this.create();
    $("#propertiesButton").onclick = () => this.properties();
    $("#pinButton").onclick = () => this.pin();
    $("#deleteButton").onclick = () => this.remove();
    $("#groupsButton").onclick = () => this.groups();
    $("#trashButton").onclick = () => {
      this.trash = !this.trash;
      $("#trashButton").textContent = this.trash ? "返回项目库" : "回收站";
      this.render();
    };
    $("#projectList").onkeydown = (event) => {
      if (event.key === "Delete") {
        event.preventDefault();
        this.remove();
      }
    };
  }
  async refresh() {
    this.docs = await this.store.read("docs");
    this.render();
  }
  current() {
    return this.docs.find((doc) => doc.id === this.selected);
  }
  render() {
    const group = $("#groupFilter").value,
      search = $("#projectSearch").value.toLowerCase();
    const groups = [
      ...new Set([
        "默认项目",
        ...this.docs.filter((doc) => !doc.deleted).map((doc) => doc.group),
      ]),
    ];
    $("#groupFilter").replaceChildren(
      ...[["", "全部项目"], ...groups.map((g) => [g, g])].map(([id, label]) => {
        const o = el("option", label);
        o.value = id;
        return o;
      }),
    );
    $("#groupFilter").value = groups.includes(group) ? group : "";
    this.visible = this.docs
      .filter(
        (doc) =>
          doc.deleted === this.trash &&
          (!group || doc.group === group) &&
          (!search ||
            (doc.title + "\n" + doc.content).toLowerCase().includes(search)),
      )
      .sort(
        (a, b) =>
          Number(b.pinned) - Number(a.pinned) ||
          a.order - b.order ||
          a.title.localeCompare(b.title, "zh-CN"),
      );
    const titles = new Map();
    for (const doc of this.visible)
      titles.set(doc.title, (titles.get(doc.title) || 0) + 1);
    const list = $("#projectList");
    list.replaceChildren();
    for (const doc of this.visible) {
      const item = el(
        "div",
        "",
        "project" + (doc.id === this.selected ? " selected" : ""),
      );
      item.setAttribute("role", "option");
      item.setAttribute("aria-selected", doc.id === this.selected);
      item.dataset.id = doc.id;
      item.draggable = true;
      item.tabIndex = -1;
      if (doc.priority) item.append(el("span", "", "dot " + doc.priority));
      if (doc.pinned) item.append(el("span", "↑"));
      const name = el("div", "", "name");
      name.append(el("span", doc.title));
      if (titles.get(doc.title) > 1)
        name.append(
          el("small", doc.group + " · " + doc.id.slice(0, 6), "path"),
        );
      item.append(name);
      if (doc.dirty) item.append(el("small", "·"));
      item.title = doc.title + "\n" + doc.group;
      item.onclick = () => this.select(doc.id);
      item.oncontextmenu = (event) =>
        contextMenu(event, [
          ["项目属性", () => this.properties(doc.id)],
          [doc.pinned ? "取消置顶" : "置顶", () => this.pin(doc.id)],
          ...(doc.project_path
            ? [["打开项目位置", () => this.openPath(doc)]]
            : []),
          [doc.deleted ? "恢复项目" : "移到回收站", () => this.remove(doc.id)],
        ]);
      item.ondragstart = (event) => {
        this.dragId = doc.id;
        event.dataTransfer.setData("text/plain", doc.id);
        item.classList.add("dragging");
      };
      item.ondragend = () => {
        this.dragId = null;
        item.classList.remove("dragging");
        list
          .querySelectorAll(".drop-target")
          .forEach((i) => i.classList.remove("drop-target"));
      };
      item.ondragover = (event) => {
        event.preventDefault();
        item.classList.add("drop-target");
      };
      item.ondragleave = () => item.classList.remove("drop-target");
      item.ondrop = (event) => {
        event.preventDefault();
        this.reorder(event.dataTransfer.getData("text/plain"), doc.id);
      };
      this.touchDrag(item, doc.id);
      list.append(item);
    }
    $("#projectCount").textContent = this.visible.length + " 个项目";
    const selected = this.current();
    $("#pinButton").textContent = selected?.pinned ? "取消置顶" : "置顶";
    $("#deleteButton").textContent = selected?.deleted ? "恢复" : "删除";
    for (const id of ["propertiesButton", "pinButton", "deleteButton"])
      $("#" + id).disabled = !selected;
  }
  touchDrag(item, id) {
    let timer,
      origin,
      holding = false,
      target;
    item.addEventListener("pointerdown", (event) => {
      if (event.pointerType === "mouse") return;
      origin = [event.clientX, event.clientY];
      timer = setTimeout(() => {
        holding = true;
        item.classList.add("dragging");
        toast("拖动到目标项目后松手");
      }, 450);
    });
    item.addEventListener(
      "pointermove",
      (event) => {
        if (!origin) return;
        if (
          !holding &&
          Math.hypot(event.clientX - origin[0], event.clientY - origin[1]) > 8
        )
          clearTimeout(timer);
        if (holding) {
          event.preventDefault();
          const row = document
            .elementFromPoint(event.clientX, event.clientY)
            ?.closest(".project");
          if (row) {
            target = row.dataset.id;
            $("#projectList")
              .querySelectorAll(".drop-target")
              .forEach((i) => i.classList.remove("drop-target"));
            row.classList.add("drop-target");
          }
        }
      },
      { passive: false },
    );
    const end = () => {
      clearTimeout(timer);
      origin = null;
      if (holding && target && target !== id) this.reorder(id, target);
      holding = false;
      item.classList.remove("dragging");
      $("#projectList")
        .querySelectorAll(".drop-target")
        .forEach((i) => i.classList.remove("drop-target"));
    };
    item.addEventListener("pointerup", end);
    item.addEventListener("pointercancel", end);
  }
  async select(id) {
    if (await this.onSelect(id) === false) return;
    this.selected = id;
    this.render();
    if (innerWidth <= 760) {
      if (this.onMobileSelect) this.onMobileSelect();
      else $("#workspace").classList.add("no-library");
    }
  }
  async create() {
    const title = field("项目名称", "text", ""),
      group = field("分组", "text", $("#groupFilter").value || "默认项目"),
      path = field("项目位置（选填，电脑路径或网页地址）");
    await dialog(
      "新建项目大纲",
      [title.wrapper, group.wrapper, path.wrapper],
      async () => {
        if (!title.input.value.trim()) throw new Error("请输入项目名称");
        const doc = await this.store.create({
          title: title.input.value.trim(),
          group: group.input.value.trim() || "默认项目",
          project_path: path.input.value.trim(),
          content:
            "# " + title.input.value.trim() + "\n\n## 待办事项\n\n- [ ] \n",
          order: Date.now(),
        });
        await this.refresh();
        await this.select(doc.id);
        this.onEdit();
      },
      "新建",
    );
  }
  async properties(id = this.selected) {
    const doc = this.docs.find((d) => d.id === id);
    if (!doc) return;
    const title = field("项目名称", "text", doc.title),
      group = field("分组", "text", doc.group),
      path = field("项目位置（电脑路径 / 网页地址）", "text", doc.project_path),
      description = field("项目说明", "textarea", doc.description),
      priority = field("项目优先级", "select", doc.priority, [
        ["", "不标记"],
        ["urgent", "紧急"],
        ["high", "优先"],
        ["normal", "普通"],
      ]);
    await dialog(
      "项目属性",
      [
        title.wrapper,
        group.wrapper,
        priority.wrapper,
        path.wrapper,
        description.wrapper,
        el("p", "云端项目 ID：" + doc.id, "form-hint"),
      ],
      async () => {
        if (!title.input.value.trim()) throw new Error("项目名称不能为空");
        await this.store.edit(id, {
          title: title.input.value.trim(),
          group: group.input.value.trim() || "默认项目",
          priority: priority.input.value,
          description: description.input.value,
          project_path: path.input.value.trim(),
        });
        await this.refresh();
        this.onEdit(id);
      },
      "保存",
    );
  }
  async pin(id = this.selected) {
    const doc = this.docs.find((d) => d.id === id);
    if (doc) {
      await this.store.edit(id, { pinned: !doc.pinned });
      await this.refresh();
      this.onEdit();
    }
  }
  async remove(id = this.selected) {
    const doc = this.docs.find((d) => d.id === id);
    if (!doc) return;
    await dialog(
      doc.deleted ? "恢复项目" : "删除项目",
      [
        el("p", (doc.deleted ? "恢复" : "移到回收站") + "：" + doc.title),
        el("p", "项目 ID：" + doc.id, "form-hint"),
        el(
          "p",
          doc.project_path
            ? "关联项目位置：" + doc.project_path
            : "来源：云端工作区；本操作不删除电脑上的原始 Markdown 文件。",
          "form-hint",
        ),
      ],
      async () => {
        await this.store.edit(id, { deleted: !doc.deleted });
        await this.refresh();
        this.onEdit(id);
        if (id === this.selected && !doc.deleted) await this.onSelect(null);
      },
      doc.deleted ? "恢复" : "移到回收站",
    );
  }
  async reorder(id, target) {
    const rows = [...this.docs].sort((a, b) => a.order - b.order),
      first = rows.findIndex((d) => d.id === id),
      last = rows.findIndex((d) => d.id === target);
    if (first < 0 || last < 0 || first === last) return;
    const [moved] = rows.splice(first, 1);
    rows.splice(last, 0, moved);
    for (let index = 0; index < rows.length; index++)
      if (rows[index].order !== index)
        await this.store.edit(rows[index].id, { order: index });
    await this.refresh();
    this.onEdit();
  }
  async openPath(doc) {
    if (/^https:\/\//i.test(doc.project_path))
      window.open(doc.project_path, "_blank", "noopener");
    else if (native()?.openPath) native().openPath(doc.project_path);
    else toast("这是电脑上的路径，请在 Windows 云端版打开");
  }
  async groups() {
    const content = el("div");
    const names = [
      ...new Set([
        "默认项目",
        ...this.docs.filter((d) => !d.deleted).map((d) => d.group),
      ]),
    ];
    for (const name of names) {
      const row = el("div", "", "group-setting");
      row.append(el("span", name));
      if (name !== "默认项目") {
        const remove = el("button", "删除分组");
        remove.type = "button";
        remove.onclick = async () => {
          await this.confirmGroup(name);
          $("#dialog").close();
        };
        row.append(remove);
      }
      content.append(row);
    }
    content.append(
      el(
        "p",
        "在项目属性中填写新的分组名即可创建；分组删除后，项目归入默认项目。",
        "form-hint",
      ),
    );
    await dialog("项目分组", [content], async () => {}, "完成");
  }
  async confirmGroup(name) {
    for (const doc of this.docs.filter((d) => d.group === name))
      await this.store.edit(doc.id, { group: "默认项目" });
    await this.refresh();
    this.onEdit();
    toast("分组已删除，项目已归入默认项目");
  }
}
