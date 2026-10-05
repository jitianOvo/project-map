from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap, QTextCursor

from .menus import RoundedMenu
from .versioning import insert_version, markdown_content_lines, remove_versions


PRIORITIES = {
    "urgent": ("最紧急（红色）", "#dc2626"),
    "high": ("优先（蓝色）", "#2563eb"),
    "normal": ("普通（绿色）", "#16a34a"),
}
PRIORITY_SPAN = re.compile(r'<span data-priority="(?:urgent|high|normal)" style="color:#[0-9a-fA-F]{6}">(.*?)</span>')
NUMBERED = re.compile(r"^([ \t]*)(\d+)\.([ \t]+)(.*)$")
MARKDOWN_PREFIX = re.compile(r"^(?:[ \t]*#{1,6}[ \t]+(?:[Vv]\d+(?:\.\d+)*[ \t]*)?|[ \t]*(?:\d+\.|[-*+])[ \t]+(?:\[[ xX]\][ \t]+)?|[ \t]*>[ \t]*)")


def utf16_length(text):
    return len(text.encode("utf-16-le")) // 2


def priority_icon(priority):
    pixmap = QPixmap(40, 40)
    pixmap.setDevicePixelRatio(2)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(PRIORITIES[priority][1]))
    painter.drawEllipse(4, 4, 12, 12)
    painter.end()
    return QIcon(pixmap)


class EditorWorkflow:
    def __init__(self, editor):
        self.editor = editor

    def replace_document(self, text, line=None):
        editor = self.editor
        original = editor.toPlainText()
        if text == original:
            return
        horizontal = editor.horizontalScrollBar().value()
        cursor = editor.textCursor()
        position = cursor.position()
        # 只替换变动区间，保留滚动锚点以及正文的撤销历史。
        start = 0
        limit = min(len(original), len(text))
        while start < limit and original[start] == text[start]:
            start += 1
        end = 0
        while end < limit - start and original[-end - 1] == text[-end - 1]:
            end += 1
        cursor.beginEditBlock()
        cursor.setPosition(utf16_length(original[:start]))
        cursor.setPosition(utf16_length(original[:len(original) - end]), QTextCursor.KeepAnchor)
        cursor.insertText(text[start:len(text) - end])
        cursor.endEditBlock()
        if line is not None:
            cursor.setPosition(editor.document().findBlockByNumber(line).position())
        else:
            cursor.setPosition(min(position, editor.document().characterCount() - 1))
        editor.setTextCursor(cursor)
        editor.horizontalScrollBar().setValue(horizontal)
        editor.setFocus()

    def add_version(self, child=False):
        text, line = insert_version(self.editor.toPlainText(), self.editor.textCursor().blockNumber(), child)
        self.replace_document(text, line)

    def remove_version(self):
        cursor = self.editor.textCursor()
        first = self.editor.document().findBlock(cursor.selectionStart()).blockNumber()
        last = self.editor.document().findBlock(max(cursor.selectionStart(), cursor.selectionEnd() - 1)).blockNumber()
        text, changed = remove_versions(self.editor.toPlainText(), first, last)
        if changed:
            self.replace_document(text)

    def set_priority(self, priority):
        editor = self.editor
        cursor = editor.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.BlockUnderCursor)
            # 保留标题和列表前缀，使 Markdown 继续按原结构渲染。
            block = cursor.block()
            content = block.text()
            prefix = MARKDOWN_PREFIX.match(content)
            cursor.setPosition(block.position() + utf16_length(prefix[0] if prefix else ""))
            cursor.setPosition(block.position() + utf16_length(content), QTextCursor.KeepAnchor)
        selected = cursor.selectedText()
        if not selected:
            return
        start = cursor.selectionStart()
        inner = PRIORITY_SPAN.sub(r"\1", selected)
        if priority in PRIORITIES:
            color = PRIORITIES[priority][1]
            parts = []
            starts_at_block = start == editor.document().findBlock(start).position()
            for index, part in enumerate(inner.split("\u2029")):
                prefix = MARKDOWN_PREFIX.match(part) if index or starts_at_block else None
                leading = prefix[0] if prefix else ""
                body = part[len(leading):]
                parts.append(leading + (f'<span data-priority="{priority}" style="color:{color}">{body}</span>' if body else ""))
            replacement = "\u2029".join(parts)
        else:
            replacement = inner
        cursor.beginEditBlock()
        cursor.insertText(replacement.replace("\u2029", "\n"))
        cursor.endEditBlock()
        cursor.setPosition(start)
        cursor.setPosition(start + utf16_length(replacement), QTextCursor.KeepAnchor)
        editor.setTextCursor(cursor)
        editor.setFocus()

    def add_context_actions(self, menu):
        menu.addAction("增加 Vn（跟随附近版本）", lambda: self.add_version())
        menu.addAction("增加子版本（小数）", lambda: self.add_version(True))
        menu.addAction("减少 Vn（保留正文）", self.remove_version)
        priorities = RoundedMenu(menu)
        priorities.setTitle("优先级")
        menu.addMenu(priorities)
        for key, (label, _color) in PRIORITIES.items():
            action = priorities.addAction(priority_icon(key), label)
            action.triggered.connect(lambda _checked=False, value=key: self.set_priority(value))
        priorities.addSeparator()
        priorities.addAction("清除优先级", lambda: self.set_priority(None))

    def insert_numbered_item(self):
        editor = self.editor
        cursor = editor.textCursor()
        if cursor.hasSelection():
            return False
        line = cursor.block().text()
        match = NUMBERED.match(line)
        if not match or cursor.positionInBlock() < utf16_length(line[:match.start(4)]):
            return False
        start = cursor.block().blockNumber()
        lines = editor.toPlainText().split("\n")
        if start not in {index for index, _line in markdown_content_lines(lines)}:
            return False
        expected = int(match[2]) + 1
        for index in range(start + 1, len(lines)):
            following = NUMBERED.match(lines[index])
            if not following or following[1] != match[1] or int(following[2]) != expected:
                break
            lines[index] = f"{following[1]}{expected + 1}.{following[3]}{following[4]}"
            expected += 1
        # Qt 光标位置使用 UTF-16，分割交给 QTextCursor 后再统一修正编号。
        prefix_cursor = QTextCursor(cursor)
        prefix_cursor.setPosition(cursor.block().position())
        prefix_cursor.setPosition(cursor.position(), QTextCursor.KeepAnchor)
        before = prefix_cursor.selectedText()
        tail = line[len(before):]
        lines[start:start + 1] = [before, f"{match[1]}{int(match[2]) + 1}. {tail}"]
        self.replace_document("\n".join(lines), start + 1)
        restored = editor.textCursor()
        restored.setPosition(restored.block().position() + utf16_length(f"{match[1]}{int(match[2]) + 1}. "))
        editor.setTextCursor(restored)
        return True
