from __future__ import annotations

import datetime as dt
import re
import shutil
from pathlib import Path

from PySide6.QtCore import QRegularExpression, Qt, Signal
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QTextCharFormat, QTextCursor, QSyntaxHighlighter
from PySide6.QtWidgets import QPlainTextEdit, QTextEdit, QWidget

from .config import MEDIA_DIR

class LineNumberArea(QWidget):
    def __init__(self, editor):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return self.editor.line_number_width(), 0

    def paintEvent(self, event):
        self.editor.paint_line_numbers(event)


class MarkdownHighlighter(QSyntaxHighlighter):
    def __init__(self, document):
        super().__init__(document)
        self.rules = []
        for pattern, color, bold in [
            (r"^#{1,6}\s.*$", "#60a5fa", True),
            (r"`[^`]+`", "#fbbf24", False),
            (r"^\s*[-*+]\s", "#a7f3d0", False),
            (r"^\s*>.*$", "#c4b5fd", False),
        ]:
            fmt = QTextCharFormat()
            fmt.setForeground(QColor(color))
            fmt.setFontWeight(QFont.Bold if bold else QFont.Normal)
            self.rules.append((QRegularExpression(pattern), fmt))

    def highlightBlock(self, text):
        for expression, fmt in self.rules:
            match = expression.match(text)
            if match.hasMatch():
                self.setFormat(match.capturedStart(), match.capturedLength(), fmt)


class MarkdownEditor(QPlainTextEdit):
    changed_cursor = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.theme_name = "dark"
        self.pasted_number_blocks = []
        self.line_numbers = LineNumberArea(self)
        self.blockCountChanged.connect(self.update_line_number_width)
        self.updateRequest.connect(self.update_line_number_area)
        self.cursorPositionChanged.connect(self.highlight_current_line)
        self.cursorPositionChanged.connect(self.changed_cursor)
        self.setTabStopDistance(28)
        self.setPlaceholderText("在这里编辑 Markdown 大纲……")
        self.highlighter = MarkdownHighlighter(self.document())
        self.update_line_number_width(0)

    def line_number_width(self):
        digits = len(str(max(1, self.blockCount())))
        return 18 + self.fontMetrics().horizontalAdvance("9") * digits

    def update_line_number_width(self, _):
        self.setViewportMargins(self.line_number_width(), 0, 0, 0)

    def update_line_number_area(self, rect, dy):
        if dy:
            self.line_numbers.scroll(0, dy)
        else:
            self.line_numbers.update(0, rect.y(), self.line_numbers.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self.update_line_number_width(0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rect = self.contentsRect()
        self.line_numbers.setGeometry(rect.left(), rect.top(), self.line_number_width(), rect.height())

    def mousePressEvent(self, event):
        horizontal = self.horizontalScrollBar().value()
        super().mousePressEvent(event)
        QTimer.singleShot(0, lambda: self.horizontalScrollBar().setValue(horizontal))

    def highlight_current_line(self):
        extra = []
        if not self.isReadOnly():
            selection = QTextEdit.ExtraSelection() if False else None
            from PySide6.QtWidgets import QTextEdit
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(QColor("#eef3fb" if self.theme_name == "light" else "#17243a"))
            selection.format.setProperty(QTextCharFormat.FullWidthSelection, True)
            selection.cursor = self.textCursor()
            selection.cursor.clearSelection()
            extra.append(selection)
        self.setExtraSelections(extra)

    def set_theme(self, theme):
        self.theme_name = theme
        self.highlight_current_line()
        self.line_numbers.update()

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        undo = menu.addAction("撤销")
        undo.setShortcut(QKeySequence.Undo)
        undo.setEnabled(self.document().isUndoAvailable())
        undo.triggered.connect(self.undo)
        redo = menu.addAction("重做")
        redo.setShortcut(QKeySequence.Redo)
        redo.setEnabled(self.document().isRedoAvailable())
        redo.triggered.connect(self.redo)
        menu.addSeparator()
        cut = menu.addAction("剪切")
        cut.setShortcut(QKeySequence.Cut)
        cut.setEnabled(self.textCursor().hasSelection())
        cut.triggered.connect(self.cut)
        copy = menu.addAction("复制")
        copy.setShortcut(QKeySequence.Copy)
        copy.setEnabled(self.textCursor().hasSelection())
        copy.triggered.connect(self.copy)
        paste = menu.addAction("粘贴")
        paste.setShortcut(QKeySequence.Paste)
        paste.setEnabled(bool(self.canPaste()))
        paste.triggered.connect(self.paste)
        delete = menu.addAction("删除选中内容")
        delete.setEnabled(self.textCursor().hasSelection())
        delete.triggered.connect(self.delete_selection)
        menu.addSeparator()
        select_all = menu.addAction("全选")
        select_all.setShortcut(QKeySequence.SelectAll)
        select_all.triggered.connect(self.selectAll)
        menu.exec(event.globalPos())

    def delete_selection(self):
        cursor = self.textCursor()
        cursor.removeSelectedText()
        self.setTextCursor(cursor)

    def paint_line_numbers(self, event):
        painter = QPainter(self.line_numbers)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor("#eef1f6" if self.theme_name == "light" else "#111c2e"))
        painter.drawRoundedRect(0, 0, self.line_numbers.width(), self.line_numbers.height(), 8, 8)
        block = self.firstVisibleBlock()
        block_number = block.blockNumber()
        top = int(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + int(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                painter.setPen(QColor("#7b8799" if self.theme_name == "light" else "#64748b"))
                painter.drawText(0, top, self.line_numbers.width() - 6, self.fontMetrics().height(), Qt.AlignRight, str(block_number + 1))
            block = block.next()
            top = bottom
            bottom = top + int(self.blockBoundingRect(block).height())
            block_number += 1

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Tab, Qt.Key_Backtab):
            if self.textCursor().hasSelection():
                self.indent_selection(event.key() == Qt.Key_Backtab or bool(event.modifiers() & Qt.ShiftModifier))
            else:
                if event.key() == Qt.Key_Backtab or event.modifiers() & Qt.ShiftModifier:
                    super().keyPressEvent(event)
                else:
                    self.insertPlainText("\t")
            return
        if event.key() in (Qt.Key_Return, Qt.Key_Enter) and not event.modifiers() and not self.textCursor().hasSelection():
            if self.try_continue_numbered_list():
                return
        super().keyPressEvent(event)

    def indent_selection(self, outdent=False):
        cursor = self.textCursor()
        start = cursor.selectionStart()
        end = cursor.selectionEnd()
        cursor.setPosition(start)
        cursor.movePosition(QTextCursor.StartOfLine)
        first = cursor.position()
        cursor.setPosition(end)
        if cursor.positionInBlock() == 0 and end > start:
            cursor.movePosition(QTextCursor.PreviousBlock)
        cursor.movePosition(QTextCursor.EndOfLine)
        last = cursor.position()
        cursor.setPosition(first)
        cursor.setPosition(last, QTextCursor.KeepAnchor)
        lines = cursor.selectedText().replace("\u2029", "\n").split("\n")
        if outdent:
            lines = [line[1:] if line.startswith("\t") else (line[4:] if line.startswith("    ") else line) for line in lines]
        else:
            normalized = []
            for line in lines:
                match = re.match(r"^([ \t]*)(\d+)\.(.*)$", line)
                if match and (not match.group(3) or not match.group(3)[0].isspace()):
                    normalized.append(f"{match.group(1)}{match.group(2)}. {match.group(3)}")
                else:
                    normalized.append(line)
            if normalized != lines:
                lines = normalized
            else:
                lines = ["\t" + line for line in lines]
        replacement = "\n".join(lines)
        cursor.insertText(replacement)
        cursor.setPosition(first)
        cursor.setPosition(first + len(replacement), QTextCursor.KeepAnchor)
        self.setTextCursor(cursor)
        self.setFocus()

    def insertFromMimeData(self, source):
        if source.hasImage():
            image = source.imageData()
            if hasattr(image, "isNull") and not image.isNull():
                self.insert_pasted_image(image)
                return
        if source.hasUrls():
            for url in source.urls():
                source_path = Path(url.toLocalFile())
                if source_path.is_file() and source_path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
                    self.insert_pasted_image_file(source_path)
                    return
        text = source.text()
        paste_cursor = self.textCursor()
        start_line = paste_cursor.block().blockNumber()
        line_prefix = paste_cursor.block().text()[:paste_cursor.positionInBlock()]
        before_lines = self.toPlainText().splitlines()
        super().insertFromMimeData(source)
        lines = text.splitlines()
        if not line_prefix.strip() and self.has_number_pair(before_lines) and self.has_number_pair(lines, require_start=True):
            caret = self.textCursor().position()
            added = self.indent_line_range(start_line, start_line + len(lines) - 1)
            restored = self.textCursor()
            restored.setPosition(caret + added)
            self.setTextCursor(restored)
            self.pasted_number_blocks.append((start_line, start_line + len(lines) - 1))

    def image_name(self):
        return f"image-{dt.datetime.now().strftime('%Y%m%d%H%M%S%f')[:-3]}.png"

    def insert_pasted_image(self, image):
        filename = self.image_name()
        target = MEDIA_DIR / filename
        if image.save(str(target), "PNG"):
            self.insertPlainText(f"![{filename.rsplit('.', 1)[0]}](Media/{filename})")

    def insert_pasted_image_file(self, source_path):
        filename = self.image_name()
        target = MEDIA_DIR / filename
        shutil.copy2(source_path, target)
        self.insertPlainText(f"![{filename.rsplit('.', 1)[0]}](Media/{filename})")

    @staticmethod
    def has_number_pair(lines, require_start=False):
        for index in range(len(lines) - 1):
            first = re.match(r"^([ \t]*)(\d+)\.(?:[ \t]+|$)", lines[index])
            second = re.match(r"^([ \t]*)(\d+)\.(?:[ \t]+|$)", lines[index + 1])
            if first and second and first.group(1) == second.group(1):
                if require_start and (first.group(2), second.group(2)) != ("1", "2"):
                    continue
                if not require_start or int(second.group(2)) == int(first.group(2)) + 1:
                    return True
        return False

    def indent_line_range(self, start_line, end_line):
        document = self.document()
        first_block = document.findBlockByNumber(max(0, start_line))
        last_block = document.findBlockByNumber(max(0, end_line))
        if not first_block.isValid() or not last_block.isValid():
            return 0
        cursor = QTextCursor(document)
        cursor.setPosition(first_block.position())
        end = last_block.position() + len(last_block.text())
        cursor.setPosition(end, QTextCursor.KeepAnchor)
        lines = cursor.selectedText().replace("\u2029", "\n").split("\n")
        replacement = "\n".join("\t" + line for line in lines)
        cursor.insertText(replacement)
        return len(lines)

    def try_continue_numbered_list(self):
        cursor = self.textCursor()
        current_line = cursor.block().text()
        if cursor.positionInBlock() != len(current_line):
            return False
        match = re.match(r"^([ \t]*)(\d+)\.(?:[ \t]+|$)(.*)$", current_line)
        if not match:
            return False
        indent = match.group(1)
        current_number = int(match.group(2))
        lines = self.toPlainText().splitlines()
        index = cursor.block().blockNumber()
        chain = [current_number]
        expected = current_number - 1
        scan = index - 1
        while scan >= 0:
            previous = re.match(r"^([ \t]*)(\d+)\.(?:[ \t]+|$).*$", lines[scan])
            if not previous or previous.group(1) != indent or int(previous.group(2)) != expected:
                break
            chain.insert(0, expected)
            expected -= 1
            scan -= 1
        if len(chain) < 1:
            return False
        cursor.insertText(f"\n{indent}{current_number + 1}. ")
        self.setTextCursor(cursor)
        return True
