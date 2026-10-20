import { $, toast } from "./ui.js";

export class Find {
  constructor(editor) {
    this.editor = editor;
    $("#findClose").onclick = () => ($("#findBar").hidden = true);
    $("#findNext").onclick = () => this.find();
    $("#findPrev").onclick = () => this.find(true);
    $("#replaceOne").onclick = () => this.replace();
    $("#replaceAll").onclick = () => this.replace(true);
    $("#findText").onkeydown = (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        this.find(event.shiftKey);
      }
      if (event.key === "Escape") $("#findBar").hidden = true;
    };
  }
  show() {
    $("#findBar").hidden = false;
    const b = this.editor.element;
    if (b.selectionStart !== b.selectionEnd)
      $("#findText").value = b.value.slice(b.selectionStart, b.selectionEnd);
    $("#findText").focus();
    $("#findText").select();
  }
  matches() {
    const value = $("#findText").value;
    if (!value) return [];
    const escaped = value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"),
      word = $("#wholeWord").checked;
    const regex = new RegExp(
      (word ? "(?<![\\p{L}\\p{N}_])" : "") +
        escaped +
        (word ? "(?![\\p{L}\\p{N}_])" : ""),
      "gu" + ($("#matchCase").checked ? "" : "i"),
    );
    return [...this.editor.element.value.matchAll(regex)].map((match) => [
      match.index,
      match.index + match[0].length,
    ]);
  }
  find(previous = false) {
    const matches = this.matches(),
      box = this.editor.element;
    if (!matches.length) {
      $("#findStatus").textContent = "未找到";
      return;
    }
    const match = previous
      ? [...matches].reverse().find((m) => m[0] < box.selectionStart) ||
        matches.at(-1)
      : matches.find((m) => m[0] >= box.selectionEnd) || matches[0];
    box.focus();
    box.setSelectionRange(...match);
    const line = box.value.slice(0, match[0]).split("\n").length - 1;
    box.scrollTop =
      line * parseFloat(getComputedStyle(box).lineHeight) -
      box.clientHeight / 3;
    $("#findStatus").textContent =
      matches.findIndex((m) => m[0] === match[0]) + 1 + " / " + matches.length;
  }
  replace(all = false) {
    const b = this.editor.element,
      matches = this.matches(),
      value = $("#replaceText").value;
    if (!matches.length) {
      $("#findStatus").textContent = "未找到";
      return;
    }
    if (all) {
      let text = b.value;
      for (const [start, end] of matches.reverse())
        text = text.slice(0, start) + value + text.slice(end);
      this.editor.apply({
        start: 0,
        end: b.value.length,
        replacement: text,
        selection: [0, 0],
      });
      toast("已替换 " + matches.length + " 处");
    } else {
      const match = matches.find(
        (m) => m[0] === b.selectionStart && m[1] === b.selectionEnd,
      );
      if (!match) {
        this.find();
        return;
      }
      this.editor.apply({
        start: match[0],
        end: match[1],
        replacement: value,
        selection: [match[0] + value.length, match[0] + value.length],
      });
      this.find();
    }
  }
}
