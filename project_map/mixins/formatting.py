from __future__ import annotations

import html
import re

from PySide6.QtCore import QByteArray, QSize, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence, QPainter, QPixmap, QTextCursor
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QTextEdit

from ..editor_workflow import PRIORITIES, priority_icon
from ..toolbars import AdaptiveToolBar

class FormattingMixin:

    def add_markdown_toolbar(self, parent_layout):
        bar = AdaptiveToolBar("格式工具", icons_only=True)
        bar.setObjectName("markdownBar")
        groups = [
            [("↶", "撤销", "Ctrl+Z", self.editor_undo), ("↷", "重做", "Ctrl+Y", self.editor_redo)],
            [("B", "加粗", "Ctrl+B", lambda: self.wrap_selection("**", "**")),
             ("I", "斜体", "Ctrl+I", lambda: self.wrap_selection("*", "*")),
             ("S", "删除线", "Ctrl+Shift+X", lambda: self.wrap_selection("~~", "~~")),
             ("U", "下划线（HTML）", "Ctrl+U", lambda: self.wrap_selection("<u>", "</u>"))],
            [("H1", "一级标题", "Ctrl+1", lambda: self.set_heading_level(1)),
             ("H2", "二级标题", "Ctrl+2", lambda: self.set_heading_level(2)),
             ("H3", "三级标题", "Ctrl+3", lambda: self.set_heading_level(3)),
             ("H4", "四级标题", "Ctrl+4", lambda: self.set_heading_level(4)),
             ("H5", "五级标题", "Ctrl+5", lambda: self.set_heading_level(5)),
             ("H6", "六级标题", "Ctrl+6", lambda: self.set_heading_level(6))],
            [("☷", "项目列表", "Ctrl+Shift+8", lambda: self.prefix_lines("- ")), ("☑", "任务清单", "Ctrl+Shift+9", lambda: self.prefix_lines("- [ ] ")), (">", "引用", "Ctrl+Shift+.", lambda: self.prefix_lines("> "))],
            [("</>", "代码块", "Ctrl+Shift+C", self.insert_code_block), ("↗", "插入链接", "Ctrl+K", self.insert_link), ("—", "分隔线", "Ctrl+H", lambda: self.insert_text("\n\n---\n\n"))],
        ]
        groups.append([
            ("V+", "增加 Vn", "", self.editor.add_version),
            ("v.x", "增加子版本", "", lambda: self.editor.add_version(True)),
            ("V−", "减少 Vn", "", self.editor.remove_version),
        ])
        for key, (name, _color) in PRIORITIES.items():
            groups.append([(name[0], name, "", lambda _checked=False, value=key: self.editor.set_priority(value))])
        groups.append([("○", "清除优先级", "", lambda: self.editor.set_priority(None))])
        actions = {}
        for group in groups:
            for symbol, name, shortcut, handler in group:
                action = QAction(self.vector_icon(symbol), name, self)
                action.setToolTip(f"{name}{'  ·  ' + shortcut if shortcut else ''}")
                if shortcut:
                    action.setShortcut(QKeySequence(shortcut))
                    action.setShortcutVisibleInContextMenu(True)
                action.triggered.connect(handler)
                self.addAction(action)
                actions[name] = action
        for key, (name, _color) in PRIORITIES.items():
            actions[name].setIcon(priority_icon(key))
        self.markdown_toolbar = bar
        self.configure_toolbar(bar, "format", actions)
        parent_layout.addWidget(bar)

    def editor_undo(self):
        self.editor.undo()

    def editor_redo(self):
        self.editor.redo()

    def vector_icon(self, symbol):
        safe_symbol = html.escape(symbol)
        svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24">
        <rect x="1" y="1" width="22" height="22" rx="6" fill="none" stroke="#64748b" stroke-width="1.2"/>
        <text x="12" y="16.5" text-anchor="middle" font-family="Segoe UI, Microsoft YaHei UI" font-size="12" font-weight="700" fill="#64748b">{safe_symbol}</text>
        </svg>'''
        renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
        pixmap = QPixmap(48, 48)
        pixmap.setDevicePixelRatio(2)
        pixmap.fill(Qt.transparent)
        painter = QPainter(pixmap)
        renderer.render(painter)
        painter.end()
        return QIcon(pixmap)

    def selected_cursor(self):
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            cursor.select(QTextCursor.WordUnderCursor)
        return cursor

    def wrap_selection(self, prefix, suffix):
        cursor = self.editor.textCursor()
        if not cursor.hasSelection():
            block = cursor.block()
            start, end = block.position(), block.position() + len(block.text())
            line = block.text()
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.KeepAnchor)
            if line.startswith(prefix) and line.endswith(suffix) and len(line) >= len(prefix) + len(suffix):
                cursor.insertText(line[len(prefix):-len(suffix)])
                cursor.setPosition(start)
                cursor.setPosition(start + len(line) - len(prefix) - len(suffix), QTextCursor.KeepAnchor)
                self.editor.setTextCursor(cursor)
                self.editor.setFocus()
                return
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        selected = cursor.selectedText() or "文本"
        text = self.editor.toPlainText()
        if selected.startswith(prefix) and selected.endswith(suffix) and len(selected) >= len(prefix) + len(suffix):
            inner = selected[len(prefix):-len(suffix)]
            cursor.insertText(inner)
            cursor.setPosition(start)
            cursor.setPosition(start + len(inner), QTextCursor.KeepAnchor)
        elif text[:start].endswith(prefix) and text[end:].startswith(suffix):
            cursor.setPosition(start - len(prefix))
            cursor.setPosition(end + len(suffix), QTextCursor.KeepAnchor)
            cursor.insertText(selected)
            cursor.setPosition(start - len(prefix))
            cursor.setPosition(start - len(prefix) + len(selected), QTextCursor.KeepAnchor)
        else:
            cursor.insertText(prefix + selected + suffix)
            cursor.setPosition(start + len(prefix))
            cursor.setPosition(start + len(prefix) + len(selected), QTextCursor.KeepAnchor)
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def set_heading_level(self, level):
        cursor = self.editor.textCursor()
        start, end = cursor.selectionStart(), cursor.selectionEnd()
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.StartOfLine)
        first = cursor.position()
        cursor.setPosition(end)
        cursor.movePosition(QTextCursor.EndOfLine)
        last = cursor.position()
        cursor.setPosition(first)
        cursor.setPosition(last, QTextCursor.KeepAnchor)
        lines = cursor.selectedText().replace("\u2029", "\n").split("\n")
        heading = re.compile(r"^([ \t]*)(#{1,6})(?:[ \t]+|$)(.*)$")
        converted = []
        for line in lines:
            match = heading.match(line)
            if match and len(match.group(2)) == level:
                converted.append(match.group(1) + match.group(3))
            elif match:
                converted.append(match.group(1) + ("#" * level) + " " + match.group(3))
            else:
                converted.append("#" * level + " " + line)
        cursor.insertText("\n".join(converted))
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def prefix_lines(self, prefix):
        cursor = self.editor.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.StartOfLine)
        first = cursor.position()
        cursor.setPosition(end)
        cursor.movePosition(QTextCursor.EndOfLine)
        last = cursor.position()
        cursor.setPosition(first)
        cursor.setPosition(last, QTextCursor.KeepAnchor)
        lines = cursor.selectedText().replace("\u2029", "\n")
        cursor.insertText("\n".join(prefix + line for line in lines.split("\n")))
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def insert_text(self, text):
        self.editor.textCursor().insertText(text)
        self.editor.setFocus()

    def insert_code_block(self):
        cursor = self.editor.textCursor()
        selected = cursor.selectedText() or "代码"
        cursor.insertText("```python\n" + selected + "\n```")
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def insert_link(self):
        cursor = self.selected_cursor()
        label = cursor.selectedText() or "链接文字"
        cursor.insertText(f"[{label}](URL)")
        self.editor.setTextCursor(cursor)
        self.editor.setFocus()

    def update_status(self):
        cursor = self.editor.textCursor()
        self.statusBar().showMessage(f"行 {cursor.blockNumber()+1}，列 {cursor.columnNumber()+1}    字数 {len(self.editor.toPlainText())}    {'未保存' if self.dirty else '已保存'}")

    def apply_zoom(self, target, value, update=True):
        value = max(50, min(200, int(value)))
        if target == "editor":
            self.editor_zoom = value
            self.settings.setValue("editor_zoom", value)
            font = self.editor.font()
            font.setPointSizeF(self.editor_base_font_size * value / 100)
            self.editor.setFont(font)
            self.editor.update_line_number_width(0)
        else:
            self.preview_zoom = value
            self.settings.setValue("preview_zoom", value)
            font = self.preview.font()
            font.setPointSizeF(self.preview_base_font_size * value / 100)
            self.preview.setFont(font)
            if update:
                self.update_preview()
        self.update_zoom_label()

    def change_zoom(self, target, delta):
        current = self.editor_zoom if target == "editor" else self.preview_zoom
        self.apply_zoom(target, current + delta)
        self.statusBar().showMessage(f"{'编辑栏' if target == 'editor' else '预览栏'}缩放：{current + delta}%")

    def update_zoom_label(self):
        if hasattr(self, "zoom_label"):
            self.zoom_label.setText(f"编辑 {self.editor_zoom}%  ·  预览 {self.preview_zoom}%")
