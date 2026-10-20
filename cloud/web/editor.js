import {
  heading,
  indent,
  insertVersion,
  lineRange,
  numberedEnter,
  removeVersion,
  wrap,
} from "./editing.js";

export const TOOLS = [
  ["undo", "↶", "撤销", "Ctrl+Z"],
  ["redo", "↷", "重做", "Ctrl+Y"],
  ["bold", "B", "加粗", "Ctrl+B"],
  ["italic", "I", "斜体", "Ctrl+I"],
  ["strike", "S", "删除线", "Ctrl+Shift+X"],
  ["underline", "U", "下划线", "Ctrl+U"],
  ...[1, 2, 3, 4, 5, 6].map((n) => [
    "h" + n,
    "H" + n,
    n + "级标题",
    "Ctrl+" + n,
  ]),
  ["list", "≡", "项目列表", "Ctrl+Shift+8"],
  ["task", "☑", "任务清单", "Ctrl+Shift+9"],
  ["quote", "❯", "引用", ""],
  ["code", "</>", "代码块", "Ctrl+Shift+C"],
  ["link", "↗", "链接", "Ctrl+K"],
  ["hr", "—", "分隔线", "Ctrl+H"],
  ["image", "▧", "插入图片", ""],
  ["version", "V+", "增加 Vn", ""],
  ["subversion", "v.x", "增加子版本", ""],
  ["removeversion", "V−", "减少 Vn", ""],
  ["urgent", "●", "紧急", ""],
  ["high", "●", "优先", ""],
  ["normal", "●", "普通", ""],
  ["clearpriority", "○", "清除优先级", ""],
];

export class Editor {
  constructor(element, onChange, onImage, onFind) {
    Object.assign(this, { element, onChange, onImage, onFind });
    this.composing = false;
    element.addEventListener("compositionstart", () => (this.composing = true));
    element.addEventListener("compositionend", () => {
      this.composing = false;
      onChange();
    });
    element.addEventListener("input", onChange);
    element.addEventListener("keydown", (event) => this.key(event));
    element.addEventListener("paste", (event) => {
      const images = [...event.clipboardData.items]
        .filter((item) => item.type.startsWith("image/"))
        .map((item) => item.getAsFile());
      if (images.length) {
        event.preventDefault();
        onImage(images);
      }
    });
  }
  apply(edit) {
    if (!edit || this.element.readOnly || this.element.disabled) return;
    const box = this.element,
      top = box.scrollTop,
      left = box.scrollLeft;
    box.focus();
    box.setSelectionRange(edit.start, edit.end);
    if (!document.execCommand("insertText", false, edit.replacement))
      box.setRangeText(edit.replacement, edit.start, edit.end, "end");
    box.setSelectionRange(...edit.selection);
    box.scrollTop = top;
    box.scrollLeft = left;
    this.onChange();
  }
  insert(text) {
    const b = this.element;
    this.apply({
      start: b.selectionStart,
      end: b.selectionEnd,
      replacement: text,
      selection: [
        b.selectionStart + text.length,
        b.selectionStart + text.length,
      ],
    });
  }
  command(name) {
    if (this.element.readOnly || this.element.disabled) return;
    const box = this.element,
      text = box.value,
      start = box.selectionStart,
      end = box.selectionEnd;
    if (name === "undo" || name === "redo") {
      box.focus();
      document.execCommand(name);
      this.onChange();
      return;
    }
    if (/^h[1-6]$/.test(name))
      return this.apply(heading(text, start, end, +name[1]));
    const pairs = {
      bold: ["**", "**"],
      italic: ["*", "*"],
      strike: ["~~", "~~"],
      underline: ["<u>", "</u>"],
      code: ["\n```\n", "\n```\n"],
    };
    if (pairs[name]) return this.apply(wrap(text, start, end, ...pairs[name]));
    if (name === "version" || name === "subversion")
      return this.apply(insertVersion(text, start, end, name === "subversion"));
    if (name === "removeversion")
      return this.apply(removeVersion(text, start, end));
    if (name === "hr") return this.insert("\n\n---\n\n");
    if (name === "image") return document.querySelector("#imageInput").click();
    if (name === "link") {
      this.onFind("link");
      return;
    }
    if (["urgent", "high", "normal"].includes(name))
      return this.apply(
        wrap(text, start, end, `<span data-priority="${name}">`, "</span>"),
      );
    if (name === "clearpriority") {
      const [a, b] = start === end ? lineRange(text, start) : [start, end],
        replacement = text
          .slice(a, b)
          .replace(
            /<span data-priority="(?:urgent|high|normal)">([\s\S]*?)<\/span>/g,
            "$1",
          );
      return this.apply({
        start: a,
        end: b,
        replacement,
        selection: [a, a + replacement.length],
      });
    }
    const prefix = { list: "- ", task: "- [ ] ", quote: "> " }[name];
    if (prefix) {
      const [a, b] = lineRange(text, start, end),
        lines = text.slice(a, b).split("\n"),
        remove = lines.every((line) => line.startsWith(prefix));
      const replacement = lines
        .map((line) => (remove ? line.slice(prefix.length) : prefix + line))
        .join("\n");
      this.apply({
        start: a,
        end: b,
        replacement,
        selection: [a, a + replacement.length],
      });
    }
  }
  key(event) {
    if (this.composing || event.isComposing || event.keyCode === 229) return;
    const b = this.element;
    if (event.key === "Tab") {
      event.preventDefault();
      this.apply(
        indent(b.value, b.selectionStart, b.selectionEnd, event.shiftKey),
      );
      return;
    }
    if (event.key === "Enter" && !event.ctrlKey && !event.altKey) {
      const edit = numberedEnter(
        b.value,
        b.selectionStart,
        b.selectionEnd,
        event.shiftKey,
      );
      if (edit) {
        event.preventDefault();
        this.apply(edit);
      }
      return;
    }
    if (!(event.ctrlKey || event.metaKey)) return;
    const key = event.key.toLowerCase();
    let command;
    if (event.shiftKey)
      command = { x: "strike", 8: "list", 9: "task", c: "code" }[key];
    else
      command = {
        b: "bold",
        i: "italic",
        u: "underline",
        h: "hr",
        k: "link",
        1: "h1",
        2: "h2",
        3: "h3",
        4: "h4",
        5: "h5",
        6: "h6",
      }[key];
    if (command) {
      event.preventDefault();
      this.command(command);
    }
  }
}
