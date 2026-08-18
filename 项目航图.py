from __future__ import annotations

import datetime as dt
import html
import json
import re
import shutil
import sys
from pathlib import Path

import markdown as markdown_lib

from PySide6.QtCore import QByteArray, QEasingCurve, QEvent, QFileSystemWatcher, QPropertyAnimation, QRegularExpression, QSettings, QTimer, QUrl, QSize, Qt, Signal
from PySide6.QtGui import QAction, QColor, QCloseEvent, QDesktopServices, QFont, QIcon, QImage, QKeySequence, QPainter, QPixmap, QTextCharFormat, QTextCursor, QTextDocument, QSyntaxHighlighter
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QDialog, QFileDialog, QFormLayout,
    QGraphicsOpacityEffect, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMainWindow,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSplitter, QStatusBar, QTabWidget,
    QTextBrowser, QTextEdit, QToolBar, QToolButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget, QMenu, QScrollBar,
)
from PySide6.QtSvg import QSvgRenderer

if getattr(sys, "frozen", False):
    _exe_dir = Path(sys.executable).resolve().parent
    APP_DIR = _exe_dir.parent if _exe_dir.name.casefold() == "dist" else _exe_dir
else:
    APP_DIR = Path(__file__).resolve().parent
MARKDOWN_DIR = APP_DIR / "Markdown"
DATA_DIR = APP_DIR / "Data"
BACKUP_DIR = APP_DIR / "Backups"
MEDIA_DIR = APP_DIR / "Media"
PROJECTS_FILE = DATA_DIR / "projects.json"
ICON_PATH = APP_DIR / "assets" / "app_icon.svg"


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


class ProjectDialog(QDialog):
    def __init__(self, name, meta, parent=None):
        super().__init__(parent)
        self.setWindowTitle("项目属性")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.name = QLineEdit(name)
        self.group = QLineEdit(meta.get("group", "默认项目"))
        self.description = QLineEdit(meta.get("description", ""))
        form.addRow("显示名称", self.name)
        form.addRow("项目分组", self.group)
        form.addRow("项目描述", self.description)
        buttons = QHBoxLayout()
        cancel = QPushButton("取消")
        save = QPushButton("保存")
        save.setObjectName("primaryButton")
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        self.name.returnPressed.connect(self.accept)
        self.group.returnPressed.connect(self.accept)
        self.description.returnPressed.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        form.addRow(buttons)


class NameDialog(QDialog):
    def __init__(self, title, label, value="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.value = QLineEdit(value)
        self.value.selectAll()
        form.addRow(label, self.value)
        buttons = QHBoxLayout()
        cancel = QPushButton("取消")
        confirm = QPushButton("继续")
        confirm.setObjectName("primaryButton")
        confirm.setDefault(True)
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self.accept)
        self.value.returnPressed.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        form.addRow(buttons)


class FindReplaceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("查找和替换")
        self.setMinimumWidth(500)
        self.setModal(False)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("输入要查找的内容")
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("输入替换后的内容")
        form.addRow("查找内容", self.find_edit)
        form.addRow("替换为", self.replace_edit)
        layout.addLayout(form)
        options = QHBoxLayout()
        self.case_sensitive = QCheckBox("区分大小写")
        self.whole_word = QCheckBox("全字匹配")
        options.addWidget(self.case_sensitive)
        options.addWidget(self.whole_word)
        options.addStretch()
        layout.addLayout(options)
        buttons = QHBoxLayout()
        self.find_button = QPushButton("查找下一个")
        self.replace_button = QPushButton("替换")
        self.replace_all_button = QPushButton("全部替换")
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        buttons.addWidget(self.find_button)
        buttons.addWidget(self.replace_button)
        buttons.addWidget(self.replace_all_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self.find_edit.returnPressed.connect(self.find_button.click)
        self.setWindowIcon(QIcon(str(ICON_PATH)) if ICON_PATH.exists() else QIcon())


class PreviewBrowser(QTextBrowser):
    """预览区使用中文右键菜单，避免 Qt 原生英文菜单混入界面。"""

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        cursor = self.textCursor()
        copy_action = menu.addAction("复制")
        copy_action.setEnabled(cursor.hasSelection())
        copy_action.triggered.connect(self.copy)
        select_action = menu.addAction("全选")
        select_action.triggered.connect(self.selectAll)
        anchor = self.anchorAt(event.pos())
        if anchor:
            menu.addSeparator()
            open_action = menu.addAction("打开链接")
            open_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl(anchor)))
        menu.exec(event.globalPos())

    image_double_clicked = Signal(str)

    def mouseDoubleClickEvent(self, event):
        cursor = self.cursorForPosition(event.pos())
        char_format = cursor.charFormat()
        if char_format.isImageFormat():
            name = char_format.toImageFormat().name()
            url = QUrl(name)
            if url.isRelative():
                url = self.document().baseUrl().resolved(url)
            path = url.toLocalFile()
            if path:
                self.image_double_clicked.emit(path)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)


class ImageViewer(QDialog):
    def __init__(self, path, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"图片预览 · {Path(path).name}")
        self.resize(900, 700)
        self.source_pixmap = QPixmap(path)
        self.scale = min(1.0, 820 / max(1, self.source_pixmap.width()), 560 / max(1, self.source_pixmap.height()))
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(False)
        self.image_label = QLabel()
        self.image_label.setAlignment(Qt.AlignCenter)
        self.scroll_area.setWidget(self.image_label)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addWidget(self.scroll_area)
        self.update_image()

    def update_image(self):
        if self.source_pixmap.isNull():
            self.image_label.setText("图片无法打开")
            return
        size = QSize(max(1, round(self.source_pixmap.width() * self.scale)), max(1, round(self.source_pixmap.height() * self.scale)))
        scaled = self.source_pixmap.scaled(size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(scaled)
        self.image_label.resize(scaled.size())

    def wheelEvent(self, event):
        if event.angleDelta().y() > 0:
            self.scale = min(8.0, self.scale * 1.15)
        else:
            self.scale = max(0.1, self.scale / 1.15)
        self.update_image()
        event.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        for directory in (MARKDOWN_DIR, DATA_DIR, BACKUP_DIR, MEDIA_DIR):
            directory.mkdir(exist_ok=True)
        self.settings = QSettings(str(DATA_DIR / "settings.ini"), QSettings.IniFormat)
        self.metadata = self.load_metadata()
        self.current_path: Path | None = None
        self.loading = False
        self.dirty = False
        self.save_guard = False
        self.find_dialog = None
        self.layout_timer = QTimer(self)
        self.layout_timer.setSingleShot(True)
        self.layout_timer.timeout.connect(self.save_layout)
        self.setWindowTitle("项目航图")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1480, 900)
        self.build_ui()
        if geometry := self.settings.value("geometry"):
            self.restoreGeometry(geometry)
        self.restore_layout()
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _: self.refresh_files())
        self.watcher.fileChanged.connect(self.external_file_changed)
        self.refresh_files()

    def load_metadata(self):
        try:
            return json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def save_metadata(self):
        PROJECTS_FILE.write_text(json.dumps(self.metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    def build_ui(self):
        toolbar = QToolBar("工具栏")
        toolbar.setMovable(False)
        self.addToolBar(toolbar)
        actions = [
            ("新建", self.new_file, "Ctrl+N"),
            ("保存", self.save_file, "Ctrl+S"),
            ("查找替换", self.show_find_replace, "Ctrl+F"),
            ("导入", self.import_file, "Ctrl+G"),
            ("项目属性", self.edit_project, "Ctrl+L"),
            ("刷新", self.refresh_files, "Ctrl+E"),
        ]
        for label, handler, shortcut in actions:
            action = QAction(label, self)
            action.setShortcut(QKeySequence(shortcut))
            action.setToolTip(f"{label}  ·  {shortcut}")
            action.setStatusTip(f"{label}（{shortcut}）")
            action.triggered.connect(handler)
            toolbar.addAction(action)
        toolbar.addSeparator()
        theme_action = QAction("切换主题", self)
        theme_action.setShortcut(QKeySequence("Ctrl+T"))
        theme_action.setToolTip("切换主题  ·  Ctrl+T")
        theme_action.triggered.connect(self.toggle_theme)
        toolbar.addAction(theme_action)
        self.right_toggle_action = QAction("收起右栏", self)
        self.right_toggle_action.setShortcut(QKeySequence("Ctrl+R"))
        self.right_toggle_action.setToolTip("收起右栏 / 展开右栏  ·  Ctrl+R")
        self.right_toggle_action.triggered.connect(self.toggle_right_panel)
        toolbar.addAction(self.right_toggle_action)
        open_action = QAction("打开数据目录", self)
        open_action.setShortcut(QKeySequence("Ctrl+O"))
        open_action.setToolTip("打开数据目录  ·  Ctrl+O")
        open_action.triggered.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(MARKDOWN_DIR))))
        toolbar.addAction(open_action)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        left = QWidget()
        self.left_panel = left
        left.setObjectName("panel")
        left_layout = QVBoxLayout(left)
        heading = QHBoxLayout()
        heading.setContentsMargins(6, 4, 6, 4)
        title = QLabel("项目库")
        title.setObjectName("title")
        heading.addWidget(title)
        left_collapse = QToolButton()
        left_collapse.setObjectName("panelCollapseButton")
        left_collapse.setText("‹")
        left_collapse.setToolTip("收起左侧项目库")
        left_collapse.clicked.connect(self.toggle_left_panel)
        heading.addWidget(left_collapse)
        self.count_label = QLabel()
        self.count_label.setObjectName("countBadge")
        heading.addWidget(self.count_label, 0, Qt.AlignRight)
        left_layout.addLayout(heading)
        self.search = QLineEdit()
        self.search.setPlaceholderText("搜索项目名称或内容……")
        self.search.textChanged.connect(self.filter_files)
        left_layout.addWidget(self.search)
        self.filter_button = QToolButton()
        self.filter_button.setObjectName("filterButton")
        self.filter_button.setPopupMode(QToolButton.InstantPopup)
        self.filter_menu = QMenu(self)
        self.filter_menu.triggered.connect(self.set_project_filter)
        self.filter_button.setMenu(self.filter_menu)
        left_layout.addWidget(self.filter_button)
        self.file_list = QListWidget()
        self.file_list.setFocusPolicy(Qt.NoFocus)
        self.file_list.currentItemChanged.connect(self.select_file)
        left_layout.addWidget(self.file_list, 1)
        buttons = QHBoxLayout()
        for label, handler in (("＋ 新建", self.new_file), ("项目属性", self.edit_project), ("删除", self.delete_file)):
            button = QPushButton(label)
            button.clicked.connect(handler)
            buttons.addWidget(button)
        left_layout.addLayout(buttons)

        center = QWidget()
        center_layout = QVBoxLayout(center)
        center_layout.setContentsMargins(0, 0, 0, 0)
        self.file_title = QLabel("请选择左侧项目")
        self.file_title.setObjectName("fileTitle")
        file_header = QHBoxLayout()
        self.file_header = file_header
        file_header.addWidget(self.file_title)
        file_header.addStretch()
        self.expand_left_button = QToolButton(root)
        self.expand_left_button.setObjectName("panelExpandButton")
        self.expand_left_button.setText("›")
        self.expand_left_button.setToolTip("展开左侧项目库")
        self.expand_left_button.clicked.connect(self.toggle_left_panel)
        self.expand_left_button.setVisible(False)
        self.expand_right_button = QToolButton()
        self.expand_right_button.setObjectName("panelExpandButton")
        self.expand_right_button.setText("›")
        self.expand_right_button.setToolTip("展开右侧辅助面板")
        self.expand_right_button.clicked.connect(self.toggle_right_panel)
        self.expand_right_button.setVisible(False)
        file_header.addWidget(self.expand_right_button)
        center_layout.addLayout(file_header)
        self.editor = MarkdownEditor()
        self.editor.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.editor_base_font_size = self.editor.font().pointSizeF() if self.editor.font().pointSizeF() > 0 else 10.0
        self.editor_zoom = int(self.settings.value("editor_zoom", 100))
        self.add_markdown_toolbar(center_layout)
        self.editor.textChanged.connect(self.content_changed)
        self.editor.cursorPositionChanged.connect(self.update_status)
        self.preview = PreviewBrowser()
        self.preview.setLineWrapMode(QTextEdit.NoWrap)
        self.preview_base_font_size = 10.0
        self.preview_zoom = int(self.settings.value("preview_zoom", 100))
        self.preview.anchorClicked.connect(lambda url: QDesktopServices.openUrl(url))
        self.preview.image_double_clicked.connect(self.open_preview_image)
        for widget in (self.editor, self.editor.viewport(), self.preview, self.preview.viewport(), self.editor.verticalScrollBar(), self.editor.horizontalScrollBar(), self.preview.verticalScrollBar(), self.preview.horizontalScrollBar()):
            widget.installEventFilter(self)
        self.apply_zoom("editor", self.editor_zoom, update=False)
        self.apply_zoom("preview", self.preview_zoom, update=False)
        self.center_splitter = QSplitter(Qt.Horizontal)
        self.center_splitter.addWidget(self.editor)
        self.center_splitter.addWidget(self.preview)
        self.center_splitter.setChildrenCollapsible(False)
        self.center_splitter.setSizes([500, 500])
        self.last_split_sizes = [500, 500]
        self.current_view_mode = "split"
        center_layout.addWidget(self.center_splitter, 1)
        mode_row = QHBoxLayout()
        for label, mode in (("编辑", "edit"), ("分栏", "split"), ("预览", "preview")):
            button = QToolButton()
            button.setText(label)
            button.setObjectName("modeButton")
            button.clicked.connect(lambda _=False, value=mode: self.set_view_mode(value))
            mode_row.addWidget(button)
        mode_row.addSpacing(8)
        self.wrap_button = QToolButton()
        self.wrap_button.setObjectName("modeButton")
        self.wrap_button.setText("↔  自动换行")
        self.wrap_button.setPopupMode(QToolButton.InstantPopup)
        self.wrap_button.setToolTip("选择编辑栏或预览栏的自动换行设置")
        self.wrap_menu = QMenu(self)
        self.editor_wrap_action = self.wrap_menu.addAction("编辑栏启用")
        self.editor_wrap_action.setCheckable(True)
        self.preview_wrap_action = self.wrap_menu.addAction("预览栏启用")
        self.preview_wrap_action.setCheckable(True)
        self.editor_wrap_action.toggled.connect(lambda checked: self.toggle_word_wrap("editor", checked))
        self.preview_wrap_action.toggled.connect(lambda checked: self.toggle_word_wrap("preview", checked))
        self.wrap_button.setMenu(self.wrap_menu)
        editor_wrap = str(self.settings.value("editor_wrap", "false")).lower() == "true"
        preview_wrap = str(self.settings.value("preview_wrap", "false")).lower() == "true"
        self.editor_wrap_action.setChecked(editor_wrap)
        self.preview_wrap_action.setChecked(preview_wrap)
        mode_row.addWidget(self.wrap_button)
        wrap_shortcut = QAction("切换自动换行", self)
        wrap_shortcut.setShortcut(QKeySequence("Alt+Z"))
        wrap_shortcut.triggered.connect(self.toggle_word_wrap_shortcut)
        self.addAction(wrap_shortcut)
        mode_row.addStretch()
        center_layout.addLayout(mode_row)

        right = QWidget()
        self.right_panel = right
        right.setObjectName("panel")
        right_layout = QVBoxLayout(right)
        right_header = QHBoxLayout()
        right_title = QLabel("辅助面板")
        right_title.setObjectName("panelTitle")
        right_header.addWidget(right_title)
        right_header.addStretch()
        right_collapse = QToolButton()
        right_collapse.setObjectName("panelCollapseButton")
        right_collapse.setText("‹")
        right_collapse.setToolTip("收起右侧辅助面板")
        right_collapse.clicked.connect(self.toggle_right_panel)
        right_header.addWidget(right_collapse)
        right_layout.addLayout(right_header)
        self.right_tabs = QTabWidget()
        self.toc = QTreeWidget()
        self.toc.setHeaderHidden(True)
        self.toc.itemClicked.connect(self.jump_to_heading)
        self.tasks = QTreeWidget()
        self.tasks.setHeaderLabels(["任务", "状态"])
        self.tasks.itemClicked.connect(self.jump_to_task)
        self.info = QLabel("暂无项目")
        self.info.setWordWrap(True)
        self.info.setObjectName("info")
        self.right_tabs.addTab(self.toc, "文档目录")
        self.right_tabs.addTab(self.tasks, "任务面板")
        self.right_tabs.addTab(self.info, "项目信息")
        self.right_tabs.setDocumentMode(True)
        self.right_tabs.tabBar().setUsesScrollButtons(False)
        self.right_tabs.tabBar().setExpanding(True)
        self.right_tabs.currentChanged.connect(lambda *_: self.schedule_layout_save())
        right_layout.addWidget(self.right_tabs)

        self.main_splitter = QSplitter(Qt.Horizontal)
        self.main_splitter.addWidget(left)
        self.main_splitter.addWidget(center)
        self.main_splitter.addWidget(right)
        self.main_splitter.setChildrenCollapsible(False)
        self.main_splitter.setSizes([280, 860, 300])
        self.main_splitter.setStretchFactor(1, 1)
        self.main_splitter.setStretchFactor(2, 0)
        self.main_splitter.splitterMoved.connect(lambda *_: self.schedule_layout_save())
        self.center_splitter.splitterMoved.connect(lambda *_: self.schedule_layout_save())
        layout.addWidget(self.main_splitter)
        self.setStatusBar(QStatusBar())
        self.zoom_label = QLabel()
        self.zoom_label.setObjectName("zoomBadge")
        self.statusBar().addPermanentWidget(self.zoom_label)
        self.update_zoom_label()
        self.set_view_mode("split")

    def files(self):
        files = list(MARKDOWN_DIR.glob("*.md"))
        group = str(self.settings.value("project_filter", "全部项目"))
        if group and group != "全部项目":
            files = [p for p in files if self.metadata.get(p.name, {}).get("group", "默认项目") == group]
        return sorted(files, key=lambda p: (not self.metadata.get(p.name, {}).get("pinned", False), p.name.casefold()))

    def refresh_groups(self):
        groups = sorted({self.metadata.get(p.name, {}).get("group", "默认项目") for p in MARKDOWN_DIR.glob("*.md")})
        selected = str(self.settings.value("project_filter", "全部项目"))
        self.filter_menu.clear()
        all_action = self.filter_menu.addAction("全部项目")
        all_action.setData("全部项目")
        all_action.setCheckable(True)
        self.filter_menu.addSeparator()
        for group in groups:
            action = self.filter_menu.addAction(group)
            action.setData(group)
            action.setCheckable(True)
        self.set_project_filter_by_name(selected)

    def set_project_filter(self, action):
        self.set_project_filter_by_name(str(action.data()))
        self.refresh_files()

    def set_project_filter_by_name(self, name):
        name = name if name else "全部项目"
        self.settings.setValue("project_filter", name)
        self.filter_button.setText(f"{name}  ▾")
        for action in self.filter_menu.actions():
            action.setChecked(action.data() == name)
        self.filter_menu.setSeparatorsCollapsible(False)

    def refresh_files(self):
        selected = self.current_path.name if self.current_path else str(self.settings.value("last_file", ""))
        self.refresh_groups()
        files = self.files()
        self.file_list.blockSignals(True)
        self.file_list.clear()
        for path in files:
            meta = self.metadata.get(path.name, {})
            prefix = "★ " if meta.get("favorite") else ""
            item = QListWidgetItem(prefix + meta.get("display_name", path.stem))
            item.setData(Qt.UserRole, str(path))
            stamp = dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%m-%d %H:%M")
            text = path.read_text(encoding="utf-8", errors="ignore")
            done, total = text.count("- [x]") + text.count("- [X]"), text.count("- [")
            item.setToolTip(f"{path.name}\n{meta.get('description', '')}\n任务：{done}/{total}\n修改：{stamp}")
            self.file_list.addItem(item)
        self.file_list.blockSignals(False)
        self.count_label.setText(f"{len(files)} 个项目")
        self.filter_files(self.search.text())
        for i in range(self.file_list.count()):
            if Path(self.file_list.item(i).data(Qt.UserRole)).name == Path(selected).name:
                self.file_list.setCurrentRow(i)
                self.load_file(Path(self.file_list.item(i).data(Qt.UserRole)))
                break
        else:
            if files:
                self.file_list.setCurrentRow(0)
                self.load_file(files[0])

    def filter_files(self, query):
        query = query.casefold().strip()
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            path = Path(item.data(Qt.UserRole))
            content = path.read_text(encoding="utf-8", errors="ignore").casefold()
            item.setHidden(bool(query and query not in item.text().casefold() and query not in content))

    def select_file(self, current, _previous):
        if not current:
            return
        if self.maybe_save():
            self.load_file(Path(current.data(Qt.UserRole)))

    def load_file(self, path):
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8-sig")
        self.loading = True
        self.current_path = path
        self.settings.setValue("last_file", str(path))
        self.editor.pasted_number_blocks = []
        self.editor.setPlainText(content)
        self.loading = False
        self.dirty = False
        self.file_title.setText(self.display_name(path))
        self.update_preview()
        self.update_sidebar()
        self.statusBar().showMessage(f"已打开：{path.name}")
        if str(path) not in self.watcher.files():
            self.watcher.addPath(str(path))

    def display_name(self, path):
        return self.metadata.get(path.name, {}).get("display_name", path.stem)

    def content_changed(self):
        if self.loading:
            return
        self.dirty = True
        self.file_title.setText(self.display_name(self.current_path) + " *") if self.current_path else None
        self.update_preview()
        self.update_sidebar()

    def update_preview(self):
        if not hasattr(self, "preview"):
            return
        vertical_value = self.preview.verticalScrollBar().value()
        horizontal_value = self.preview.horizontalScrollBar().value()
        old_vertical_max = self.preview.verticalScrollBar().maximum()
        old_horizontal_max = self.preview.horizontalScrollBar().maximum()
        self.preview_update_serial = getattr(self, "preview_update_serial", 0) + 1
        update_serial = self.preview_update_serial
        dark = getattr(self.editor, "theme_name", "dark") == "dark"
        foreground = "#e5e7eb" if dark else "#1f2937"
        muted = "#8ea1bb" if dark else "#8b98aa"
        code_background = "#0b1220" if dark else "#f1f5f9"
        preview_size = self.preview_base_font_size * self.preview_zoom / 100
        divider = f"<table class='md-divider' width='100%' cellspacing='0' cellpadding='0' style='border-collapse:collapse; margin:14px 0 16px 0;'><tr><td style='border-bottom:2px dashed {muted}; height:1px; padding:0;'></td></tr></table>"
        source = re.sub(r"(?m)^\s*---\s*$", divider, self.preview_markdown())
        html = markdown_lib.markdown(source, extensions=["extra", "tables", "fenced_code", "sane_lists", "nl2br"])
        html = self.scale_preview_images(html)
        self.preview.document().setBaseUrl(QUrl.fromLocalFile(str(APP_DIR) + "/"))
        self.preview.document().setHtml(f"""
        <style>
            body {{ color:{foreground}; font-family:'Microsoft YaHei UI'; font-size:{preview_size:.1f}pt; line-height:1.55; }}
            h1,h2,h3,h4 {{ margin-top:18px; margin-bottom:8px; }}
            code, pre {{ background:{code_background}; border-radius:6px; }}
            code {{ padding:2px 5px; }}
            pre {{ padding:10px; white-space:pre-wrap; }}
            blockquote {{ color:{muted}; border-left:3px solid #60a5fa; margin-left:0; padding-left:12px; }}
            table {{ border-collapse:collapse; }}
            th,td {{ border:1px solid {muted}; padding:5px 8px; }}
        </style>
        {html}
        """)
        vertical_ratio = vertical_value / old_vertical_max if old_vertical_max else 0.0
        horizontal_ratio = horizontal_value / old_horizontal_max if old_horizontal_max else 0.0
        QTimer.singleShot(0, lambda: self.restore_preview_scroll(vertical_value, horizontal_value, vertical_ratio, horizontal_ratio, update_serial, 0))
        self.update_toc_and_tasks()

    def scale_preview_images(self, rendered_html):
        image_pattern = re.compile(r"<img\b([^>]*?)\bsrc=[\"']([^\"']+)[\"']([^>]*)>", re.IGNORECASE)

        def replace_image(match):
            before, source, after = match.groups()
            local_path = QUrl(source).toLocalFile() if source.startswith("file:") else str(APP_DIR / source.replace("/", "\\"))
            image = QImage(local_path)
            if image.isNull():
                return match.group(0)
            viewport_width = self.preview.viewport().width()
            if viewport_width <= 0:
                viewport_width = 760
            fit_width = max(320, min(860, viewport_width - 48))
            width = max(1, round(image.width() * self.preview_zoom / 100))
            max_width = max(1, round(fit_width * self.preview_zoom / 100))
            if width > max_width:
                width = max_width
            height = max(1, round(image.height() * width / image.width()))
            cleaned = re.sub(r"\sstyle=[\"'][^\"']*[\"']", "", before + after, flags=re.IGNORECASE)
            cleaned = re.sub(r"/\s*$", "", cleaned).strip()
            return f'<img {cleaned} src="{html.escape(source, quote=True)}" width="{width}" height="{height}">'

        return image_pattern.sub(replace_image, rendered_html)

    def open_preview_image(self, path):
        image_path = Path(path)
        if image_path.is_file():
            ImageViewer(image_path, self).exec()

    def restore_preview_scroll(self, vertical_value, horizontal_value, vertical_ratio=0.0, horizontal_ratio=0.0, update_serial=None, attempt=0):
        if update_serial is not None and update_serial != getattr(self, "preview_update_serial", update_serial):
            return
        vertical = self.preview.verticalScrollBar()
        horizontal = self.preview.horizontalScrollBar()
        if attempt < 8 and vertical.maximum() == 0 and (vertical_value or vertical_ratio):
            QTimer.singleShot(25, lambda: self.restore_preview_scroll(vertical_value, horizontal_value, vertical_ratio, horizontal_ratio, update_serial, attempt + 1))
            return
        vertical.setValue(min(vertical.maximum(), max(0, round(vertical_value if vertical_value else vertical.maximum() * vertical_ratio))))
        horizontal.setValue(min(horizontal.maximum(), max(0, round(horizontal_value if horizontal_value else horizontal.maximum() * horizontal_ratio))))

    def preview_markdown(self):
        lines = self.editor.toPlainText().splitlines()
        for start, end in self.editor.pasted_number_blocks:
            for index in range(max(0, start), min(len(lines), end + 1)):
                if re.match(r"^\d+\.\s+", lines[index]) and not lines[index].startswith(("\t", "    ")):
                    lines[index] = "\t" + lines[index]
        return "\n".join(lines)

    def add_markdown_toolbar(self, parent_layout):
        bar = QToolBar("Markdown 格式工具栏")
        bar.setObjectName("markdownBar")
        bar.setIconSize(QSize(18, 18))
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
        for group_index, group in enumerate(groups):
            if group_index:
                bar.addSeparator()
            for symbol, name, shortcut, handler in group:
                action = QAction(self.vector_icon(symbol), symbol, self)
                action.setToolTip(f"{name}{'  ·  ' + shortcut if shortcut else ''}")
                if shortcut:
                    action.setShortcut(QKeySequence(shortcut))
                    action.setShortcutVisibleInContextMenu(True)
                action.triggered.connect(handler)
                self.addAction(action)
                button = QToolButton()
                button.setDefaultAction(action)
                button.setObjectName("formatButton")
                button.setToolButtonStyle(Qt.ToolButtonIconOnly)
                button.setIconSize(QSize(20, 20))
                button.setToolTip(action.toolTip())
                bar.addWidget(button)
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
        pixmap = QPixmap(24, 24)
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

    def update_toc_and_tasks(self):
        self.toc.clear()
        stack = [(0, self.toc.invisibleRootItem())]
        for line_no, line in enumerate(self.editor.toPlainText().splitlines()):
            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                title = line[level:].strip() or "未命名标题"
                while stack and stack[-1][0] >= level:
                    stack.pop()
                parent = stack[-1][1] if stack else self.toc.invisibleRootItem()
                item = QTreeWidgetItem(parent, [title])
                item.setData(0, Qt.UserRole, line_no)
                stack.append((level, item))
        self.tasks.clear()
        for line_no, line in enumerate(self.editor.toPlainText().splitlines()):
            stripped = line.strip()
            if stripped.startswith("- [") and len(stripped) > 5:
                checked = stripped[3].lower() == "x"
                task = QTreeWidgetItem(self.tasks, [stripped[5:], "完成" if checked else "待办"])
                task.setData(0, Qt.UserRole, line_no)
                task.setForeground(1, QColor("#34d399" if checked else "#fbbf24"))
        self.tasks.resizeColumnToContents(1)

    def update_sidebar(self):
        if not self.current_path:
            return
        lines = self.editor.toPlainText().splitlines()
        total = sum(line.strip().startswith("- [") for line in lines)
        done = sum(line.strip().lower().startswith("- [x]") for line in lines)
        meta = self.metadata.get(self.current_path.name, {})
        self.info.setText(f"项目：{self.display_name(self.current_path)}\n\n分组：{meta.get('group', '默认项目')}\n描述：{meta.get('description', '暂无描述')}\n\n完成度：{done}/{total} 个任务")

    def jump_to_heading(self, item, _column):
        self.jump_to_line(item.data(0, Qt.UserRole))

    def jump_to_task(self, item, _column):
        self.jump_to_line(item.data(0, Qt.UserRole))

    def jump_to_line(self, line):
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.Start)
        cursor.movePosition(QTextCursor.Down, QTextCursor.MoveAnchor, int(line))
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()

    def set_view_mode(self, mode):
        if self.current_view_mode == "split" and mode != "split":
            sizes = self.center_splitter.sizes()
            if all(size > 30 for size in sizes):
                self.last_split_sizes = sizes
        if mode == "split":
            sizes = self.last_split_sizes if all(size > 30 for size in self.last_split_sizes) else [500, 500]
            self.editor.setVisible(True)
            self.preview.setVisible(True)
            self.center_splitter.setSizes(sizes)
        elif mode == "edit":
            self.editor.setVisible(True)
            self.preview.setVisible(False)
            self.center_splitter.setSizes([max(700, sum(self.center_splitter.sizes())), 0])
        elif mode == "preview":
            self.editor.setVisible(False)
            self.preview.setVisible(True)
            self.center_splitter.setSizes([0, max(700, sum(self.center_splitter.sizes()))])
        self.current_view_mode = mode
        self.schedule_layout_save()

    def toggle_right_panel(self):
        visible = not self.right_panel.isVisible()
        sizes = self.main_splitter.sizes()
        if not visible and len(sizes) == 3 and sizes[2] > 30:
            self.last_right_width = sizes[2]
        self.animate_panel(self.right_panel, 2, visible, getattr(self, "last_right_width", 300), self.expand_right_button)
        self.right_toggle_action.setText("收起右栏" if visible else "展开右栏")
        self.schedule_layout_save()

    def toggle_left_panel(self):
        visible = not self.left_panel.isVisible()
        sizes = self.main_splitter.sizes()
        if not visible and len(sizes) == 3 and sizes[0] > 30:
            self.last_left_width = sizes[0]
        self.animate_panel(self.left_panel, 0, visible, getattr(self, "last_left_width", 280), self.expand_left_button)
        self.schedule_layout_save()

    def animate_panel(self, panel, index, visible, target_width, expand_button):
        old_animation = getattr(panel, "panel_animation", None)
        if old_animation:
            old_animation.stop()
        old_effect = getattr(panel, "panel_opacity_effect", None)
        if old_effect:
            panel.setGraphicsEffect(None)
            panel.panel_opacity_effect = None
        sizes = self.main_splitter.sizes()
        total_width = max(1, sum(sizes))
        current_width = max(0, sizes[index]) if len(sizes) == 3 else max(0, panel.width())
        end_width = max(220 if index == 0 else 260, int(target_width))

        def sizes_for(width):
            result = list(sizes)
            if len(result) != 3:
                return result
            if index == 0:
                result[0] = width
                result[1] = max(1, total_width - width - result[2])
            else:
                result[2] = width
                result[1] = max(1, total_width - result[0] - width)
            return result

        if visible:
            panel.setVisible(True)
            self.main_splitter.setSizes(sizes_for(end_width))
            expand_button.setVisible(False)
            if index == 0:
                self.file_header.setContentsMargins(0, 0, 0, 0)
            start_opacity, end_opacity = 0.0, 1.0
        else:
            if index == 0:
                self.file_header.setContentsMargins(34, 0, 0, 0)
            start_opacity, end_opacity = 1.0, 0.0

        effect = QGraphicsOpacityEffect(panel)
        effect.setOpacity(start_opacity)
        panel.setGraphicsEffect(effect)
        panel.panel_opacity_effect = effect
        animation = QPropertyAnimation(effect, b"opacity", panel)
        animation.setDuration(220)
        animation.setStartValue(start_opacity)
        animation.setEndValue(end_opacity)
        animation.setEasingCurve(QEasingCurve.InOutCubic)
        panel.panel_animation = animation

        def finished():
            panel.panel_animation = None
            panel.setGraphicsEffect(None)
            panel.panel_opacity_effect = None
            if not visible:
                self.main_splitter.setSizes(sizes_for(0))
                panel.setVisible(False)
                expand_button.setVisible(True)
                expand_button.raise_()
            self.schedule_layout_save()

        animation.finished.connect(finished)
        animation.start()

    def schedule_layout_save(self):
        self.layout_timer.start(250)

    def save_layout(self):
        if not hasattr(self, "main_splitter"):
            return
        self.settings.setValue("geometry", self.saveGeometry())
        self.settings.setValue("main_splitter", self.main_splitter.sizes())
        self.settings.setValue("center_splitter", self.center_splitter.sizes())
        self.settings.setValue("left_visible", self.left_panel.isVisible())
        self.settings.setValue("right_visible", self.right_panel.isVisible())
        self.settings.setValue("right_tab", self.right_tabs.currentIndex())
        self.settings.setValue("view_mode", self.current_view_mode)
        self.settings.sync()

    def restore_layout(self):
        main_sizes = self.settings.value("main_splitter")
        if main_sizes:
            self.main_splitter.setSizes([int(value) for value in main_sizes])
        center_sizes = self.settings.value("center_splitter")
        if center_sizes and all(int(value) > 30 for value in center_sizes):
            self.last_split_sizes = [int(value) for value in center_sizes]
        tab_index = self.settings.value("right_tab")
        if tab_index is not None:
            self.right_tabs.setCurrentIndex(int(tab_index))
        left_visible = str(self.settings.value("left_visible", "true")).lower() != "false"
        self.left_panel.setVisible(left_visible)
        self.expand_left_button.setVisible(not left_visible)
        self.file_header.setContentsMargins(0 if left_visible else 34, 0, 0, 0)
        visible = str(self.settings.value("right_visible", "true")).lower() != "false"
        self.right_panel.setVisible(visible)
        self.expand_right_button.setVisible(not visible)
        self.right_toggle_action.setText("收起右栏" if visible else "展开右栏")
        mode = str(self.settings.value("view_mode", "split"))
        self.set_view_mode(mode if mode in ("edit", "split", "preview") else "split")

    def toggle_word_wrap(self, target, enabled):
        if target == "editor":
            self.settings.setValue("editor_wrap", enabled)
            self.editor.setLineWrapMode(QPlainTextEdit.WidgetWidth if enabled else QPlainTextEdit.NoWrap)
        else:
            self.settings.setValue("preview_wrap", enabled)
            self.preview.setLineWrapMode(QTextEdit.WidgetWidth if enabled else QTextEdit.NoWrap)
        states = f"编辑栏{'开' if self.editor_wrap_action.isChecked() else '关'} / 预览栏{'开' if self.preview_wrap_action.isChecked() else '关'}"
        self.wrap_button.setToolTip(f"自动换行：{states}  ·  Alt+Z 切换编辑栏")

    def toggle_word_wrap_shortcut(self):
        self.editor_wrap_action.setChecked(not self.editor_wrap_action.isChecked())

    def maybe_save(self):
        if not self.dirty:
            return True
        box = QMessageBox(self)
        box.setWindowTitle("未保存修改")
        box.setText("当前大纲还有修改没有保存。\n要保存这些修改吗？")
        save = box.addButton("保存修改", QMessageBox.AcceptRole)
        discard = box.addButton("放弃修改", QMessageBox.DestructiveRole)
        box.addButton("返回编辑", QMessageBox.RejectRole)
        box.exec()
        return self.save_file() if box.clickedButton() is save else box.clickedButton() is discard

    def show_notice(self, title, text):
        box = QMessageBox(self)
        box.setWindowTitle(title)
        box.setText(text)
        box.addButton("知道了", QMessageBox.AcceptRole)
        box.exec()

    def save_file(self):
        if not self.current_path:
            return False
        cursor = self.editor.textCursor()
        cursor_position = cursor.position()
        cursor_anchor = cursor.anchor()
        horizontal = self.editor.horizontalScrollBar().value()
        vertical = self.editor.verticalScrollBar().value()
        self.save_guard = True
        if self.current_path.exists():
            stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
            shutil.copy2(self.current_path, BACKUP_DIR / f"{self.current_path.stem}_{stamp}.md.bak")
        self.current_path.write_text(self.editor.toPlainText(), encoding="utf-8")
        restored = self.editor.textCursor()
        restored.setPosition(cursor_position)
        restored.setPosition(cursor_anchor, QTextCursor.KeepAnchor)
        self.editor.setTextCursor(restored)
        self.editor.horizontalScrollBar().setValue(horizontal)
        self.editor.verticalScrollBar().setValue(vertical)
        QTimer.singleShot(1000, self.clear_save_guard)
        self.dirty = False
        self.file_title.setText(self.display_name(self.current_path))
        self.statusBar().showMessage(f"已保存：{self.current_path.name}")
        return True

    def clear_save_guard(self):
        self.save_guard = False

    def new_file(self):
        if not self.maybe_save():
            return
        dialog = NameDialog("新建项目大纲", "文件名", "新项目大纲", self)
        if dialog.exec() != QDialog.Accepted or not dialog.value.text().strip():
            return
        name = dialog.value.text()
        filename = name.strip() + ("" if name.lower().endswith(".md") else ".md")
        path = MARKDOWN_DIR / filename
        if path.exists():
            self.show_notice("文件已存在", "这个名称已经被使用，请换一个名称。")
            return
        path.write_text("# 新项目大纲\n\n## 待办事项\n\n- [ ] ", encoding="utf-8")
        self.metadata[path.name] = {"display_name": path.stem, "group": "默认项目", "description": ""}
        self.save_metadata()
        self.refresh_files()

    def edit_project(self):
        if not self.current_path:
            return
        meta = self.metadata.setdefault(self.current_path.name, {})
        dialog = ProjectDialog(self.display_name(self.current_path), meta, self)
        if dialog.exec() != QDialog.Accepted:
            return
        meta.update({"display_name": dialog.name.text().strip() or self.current_path.stem, "group": dialog.group.text().strip() or "默认项目", "description": dialog.description.text().strip()})
        self.save_metadata()
        self.refresh_files()

    def import_file(self):
        source, _ = QFileDialog.getOpenFileName(self, "导入 Markdown", str(APP_DIR), "Markdown (*.md)")
        if not source:
            return
        target = MARKDOWN_DIR / Path(source).name
        if target.exists():
            self.show_notice("文件已存在", "Markdown 文件夹中已有同名文件。")
            return
        shutil.copy2(source, target)
        self.refresh_files()

    def delete_file(self):
        if not self.current_path or not self.maybe_save():
            return
        box = QMessageBox(self)
        box.setWindowTitle("归档大纲")
        box.setText(f"要将“{self.display_name(self.current_path)}”移动到备份目录吗？")
        move_button = box.addButton("移入备份", QMessageBox.DestructiveRole)
        box.addButton("暂不处理", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not move_button:
            return
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.move(str(self.current_path), str(BACKUP_DIR / f"{self.current_path.stem}_{stamp}.md.deleted"))
        self.metadata.pop(self.current_path.name, None)
        self.save_metadata()
        self.current_path = None
        self.refresh_files()

    def show_find_replace(self):
        if self.find_dialog is None:
            self.find_dialog = FindReplaceDialog(self)
            self.find_dialog.find_button.clicked.connect(self.find_next)
            self.find_dialog.replace_button.clicked.connect(self.replace_current)
            self.find_dialog.replace_all_button.clicked.connect(self.replace_all)
        selected = self.editor.textCursor().selectedText()
        if selected and not self.find_dialog.find_edit.text():
            self.find_dialog.find_edit.setText(selected)
        self.find_dialog.show()
        self.find_dialog.raise_()
        self.find_dialog.activateWindow()
        self.find_dialog.find_edit.setFocus()
        self.find_dialog.find_edit.selectAll()

    def find_flags(self):
        flags = QTextDocument.FindFlags()
        if self.find_dialog.case_sensitive.isChecked():
            flags |= QTextDocument.FindCaseSensitively
        if self.find_dialog.whole_word.isChecked():
            flags |= QTextDocument.FindWholeWords
        return flags

    def find_next(self):
        query = self.find_dialog.find_edit.text()
        if not query:
            return
        cursor = self.editor.textCursor()
        start = cursor.selectionEnd() if cursor.hasSelection() else cursor.position()
        found = self.editor.document().find(query, start, self.find_flags())
        if found.isNull():
            found = self.editor.document().find(query, 0, self.find_flags())
        if found.isNull():
            self.statusBar().showMessage("没有找到匹配内容")
            return
        self.editor.setTextCursor(found)
        self.editor.ensureCursorVisible()
        self.statusBar().showMessage("已找到匹配内容")

    def replace_current(self):
        query = self.find_dialog.find_edit.text()
        replacement = self.find_dialog.replace_edit.text()
        if not query:
            return
        cursor = self.editor.textCursor()
        selected = cursor.selectedText()
        matches = selected == query if self.find_dialog.case_sensitive.isChecked() else selected.casefold() == query.casefold()
        if matches:
            cursor.insertText(replacement)
            self.editor.setTextCursor(cursor)
        self.find_next()

    def replace_all(self):
        query = self.find_dialog.find_edit.text()
        replacement = self.find_dialog.replace_edit.text()
        if not query:
            return
        document = self.editor.document()
        cursor = QTextCursor(document)
        cursor.beginEditBlock()
        start = 0
        count = 0
        flags = self.find_flags()
        while True:
            found = document.find(query, start, flags)
            if found.isNull():
                break
            position = found.position()
            found.insertText(replacement)
            start = position + len(replacement)
            count += 1
        cursor.endEditBlock()
        self.statusBar().showMessage(f"已替换 {count} 处")

    def toggle_theme(self):
        dark = self.settings.value("theme", "dark") == "dark"
        self.apply_theme("light" if dark else "dark")

    def apply_theme(self, theme):
        self.settings.setValue("theme", theme)
        QApplication.instance().setStyleSheet(self.stylesheet(theme))
        self.editor.set_theme(theme)
        self.update_preview()

    def stylesheet(self, theme):
        if theme == "light":
            return """
            QWidget { background:#f7f8fb; color:#1f2937; font-family:'Microsoft YaHei UI'; font-size:14px; }
            QMainWindow, QToolBar { background:#f7f8fb; }
            QToolBar { border:0; padding:7px 10px; spacing:4px; }
            QToolBar::separator { background:#d9dee8; width:1px; margin:5px 7px; }
            QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser, QTreeWidget, QListWidget { background:#ffffff; color:#1f2937; border:1px solid #e1e5ec; border-radius:9px; padding:7px; selection-background-color:#dbeafe; selection-color:#1e3a8a; }
            QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTreeWidget:focus, QListWidget:focus { border:1px solid #93b4f4; }
            QListWidget::item { padding:9px; border-radius:8px; margin:2px 0; }
            QListWidget::item:selected { background:#dbeafe; color:#1d4ed8; border-radius:8px; }
            QPushButton, QToolButton#modeButton { background:#ffffff; color:#475569; border:1px solid #e1e5ec; border-radius:7px; padding:7px 11px; }
            QPushButton:hover, QToolButton#modeButton:hover { background:#eef4ff; color:#2563eb; border-color:#b7cdf8; }
            QToolButton#modeButton:checked { background:#dbeafe; color:#1d4ed8; border-color:#93b4f4; }
            QToolButton#filterButton { background:#ffffff; color:#475569; border:1px solid #e1e5ec; border-radius:10px; padding:8px 11px; text-align:left; }
            QToolButton#filterButton:hover { background:#eef4ff; color:#2563eb; border-color:#b7cdf8; }
            QMenu { background:#ffffff; color:#1f2937; border:1px solid #e1e5ec; border-radius:9px; padding:6px; }
            QMenu::item { padding:8px 28px 8px 12px; border-radius:6px; }
            QMenu::item:selected { background:#e8eefb; color:#1d4ed8; }
            QToolButton#formatButton { background:transparent; color:#475569; border:0; border-radius:7px; min-width:30px; min-height:28px; padding:3px 6px; font-weight:600; }
            QToolButton#formatButton:hover { background:#e8eefb; color:#1d4ed8; }
            QToolButton#formatButton:pressed { background:#dbeafe; }
            QToolBar#markdownBar { background:#ffffff; border:1px solid #e1e5ec; border-radius:9px; padding:3px 6px; margin:4px 0 8px; }
            QToolBar#markdownBar::separator { background:#e5e7eb; width:1px; margin:4px 6px; }
            QTabWidget::pane { border:0; }
            QTabBar::tab { color:#64748b; padding:8px 12px; border:0; }
            QTabBar::tab:selected { color:#2563eb; border-bottom:2px solid #3b82f6; }
            QScrollBar:vertical { background:transparent; width:14px; margin:3px 1px; }
            QScrollBar::handle:vertical { background:transparent; min-height:34px; border-radius:7px; }
            QScrollBar[hovered="true"]::handle:vertical { background:#c5ccd8; }
            QScrollBar[hovered="true"]::handle:vertical:hover { background:#94a3b8; }
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { height:0; background:transparent; }
            QScrollBar:horizontal { background:transparent; height:14px; margin:1px 3px; }
            QScrollBar::handle:horizontal { background:transparent; min-width:34px; border-radius:7px; }
            QScrollBar[hovered="true"]::handle:horizontal { background:#c5ccd8; }
            QScrollBar[hovered="true"]::handle:horizontal:hover { background:#94a3b8; }
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal, QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { width:0; background:transparent; }
            QSplitter::handle:horizontal { background:transparent; width:6px; }
            QSplitter::handle:horizontal:hover { background:#c6d5ed; border-radius:3px; }
            #panel { background:#eef1f6; border-radius:12px; }
            #title { font-size:19px; font-weight:700; background:#e8eefb; color:#315a9b; padding:5px 8px 5px 10px; border-radius:9px; }
            #panelTitle { font-size:15px; font-weight:700; background:#ffffff; color:#526174; padding:5px 14px; border-radius:9px; }
            #fileTitle { font-size:20px; font-weight:700; padding:2px 0; }
            #muted { color:#7b8799; font-size:12px; }
            #countBadge { background:#e8eefb; color:#2563eb; border-radius:10px; padding:4px 9px; font-size:12px; }
            QToolButton#panelCollapseButton, QToolButton#panelExpandButton { background:#ffffff; color:#64748b; border:1px solid #e1e5ec; border-radius:8px; min-width:28px; min-height:28px; font-size:20px; padding:0; }
            QToolButton#panelCollapseButton:hover, QToolButton#panelExpandButton:hover { background:#eef4ff; color:#2563eb; }
            QPushButton#primaryButton { background:#2563eb; color:#ffffff; border:0; }
            #info { padding:10px; color:#526174; }
            #zoomBadge { background:#e8eefb; color:#526fa5; border-radius:8px; padding:3px 8px; }
            """
        return """
        QWidget { background:#0f172a; color:#e5e7eb; font-family:'Microsoft YaHei UI'; font-size:14px; }
        QMainWindow, QToolBar { background:#0f172a; }
        QToolBar { border:0; padding:7px 10px; spacing:4px; }
        QToolBar::separator { background:#2b3950; width:1px; margin:5px 7px; }
        QLineEdit, QComboBox, QPlainTextEdit, QTextBrowser, QTreeWidget, QListWidget { background:#111c2e; color:#e5e7eb; border:1px solid #263650; border-radius:9px; padding:7px; selection-background-color:#254b85; selection-color:#ffffff; }
        QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus, QTreeWidget:focus, QListWidget:focus { border:1px solid #4777bd; }
        QListWidget::item { padding:9px; border-radius:8px; margin:2px 0; }
        QListWidget::item:selected { background:#274d83; color:#ffffff; border-radius:8px; }
        QPushButton, QToolButton#modeButton { background:#18263c; color:#cbd5e1; border:1px solid #2b3c59; border-radius:7px; padding:7px 11px; }
        QPushButton:hover, QToolButton#modeButton:hover { background:#213655; color:#93c5fd; border-color:#4777bd; }
        QToolButton#modeButton:checked { background:#27466f; color:#bfdbfe; border-color:#5b8acb; }
        QToolButton#filterButton { background:#18263c; color:#cbd5e1; border:1px solid #2b3c59; border-radius:10px; padding:8px 11px; text-align:left; }
        QToolButton#filterButton:hover { background:#213655; color:#93c5fd; border-color:#4777bd; }
        QMenu { background:#162238; color:#e5e7eb; border:1px solid #2b3c59; border-radius:9px; padding:6px; }
        QMenu::item { padding:8px 28px 8px 12px; border-radius:6px; }
        QMenu::item:selected { background:#243b60; color:#bfdbfe; }
        QToolButton#formatButton { background:transparent; color:#cbd5e1; border:0; border-radius:7px; min-width:30px; min-height:28px; padding:3px 6px; font-weight:600; }
        QToolButton#formatButton:hover { background:#243653; color:#93c5fd; }
        QToolButton#formatButton:pressed { background:#2d4d7b; }
        QToolBar#markdownBar { background:#162238; border:1px solid #293b59; border-radius:9px; padding:3px 6px; margin:4px 0 8px; }
        QToolBar#markdownBar::separator { background:#2f405d; width:1px; margin:4px 6px; }
        QTabWidget::pane { border:0; }
        QTabBar::tab { color:#8293aa; padding:8px 12px; border:0; }
        QTabBar::tab:selected { color:#93c5fd; border-bottom:2px solid #60a5fa; }
        QScrollBar:vertical { background:transparent; width:14px; margin:3px 1px; }
        QScrollBar::handle:vertical { background:transparent; min-height:34px; border-radius:7px; }
        QScrollBar[hovered="true"]::handle:vertical { background:#344866; }
        QScrollBar[hovered="true"]::handle:vertical:hover { background:#5273a3; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { height:0; background:transparent; }
        QScrollBar:horizontal { background:transparent; height:14px; margin:1px 3px; }
        QScrollBar::handle:horizontal { background:transparent; min-width:34px; border-radius:7px; }
        QScrollBar[hovered="true"]::handle:horizontal { background:#344866; }
        QScrollBar[hovered="true"]::handle:horizontal:hover { background:#5273a3; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal, QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { width:0; background:transparent; }
        QSplitter::handle:horizontal { background:transparent; width:6px; }
        QSplitter::handle:horizontal:hover { background:#36557d; border-radius:3px; }
        #panel { background:#162238; border-radius:12px; }
        #title { font-size:19px; font-weight:700; background:#243653; color:#bfdbfe; padding:5px 8px 5px 10px; border-radius:9px; }
        #panelTitle { font-size:15px; font-weight:700; background:#1d2c43; color:#b6c3d6; padding:5px 14px; border-radius:9px; }
        #fileTitle { font-size:20px; font-weight:700; padding:2px 0; }
        #muted { color:#8293aa; font-size:12px; }
        #countBadge { background:#243653; color:#93c5fd; border-radius:10px; padding:4px 9px; font-size:12px; }
        QToolButton#panelCollapseButton, QToolButton#panelExpandButton { background:#1d2c43; color:#94a3b8; border:1px solid #2b3c59; border-radius:8px; min-width:28px; min-height:28px; font-size:20px; padding:0; }
        QToolButton#panelCollapseButton:hover, QToolButton#panelExpandButton:hover { background:#243b60; color:#bfdbfe; }
        QPushButton#primaryButton { background:#2563eb; color:#ffffff; border:0; }
        #info { padding:10px; color:#b6c3d6; }
        #zoomBadge { background:#243653; color:#9bb9e8; border-radius:8px; padding:3px 8px; }
        """

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

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel and event.modifiers() & Qt.ControlModifier:
            editor_targets = (self.editor, self.editor.viewport())
            preview_targets = (self.preview, self.preview.viewport())
            if watched in editor_targets or watched in preview_targets:
                target = "editor" if watched in editor_targets else "preview"
                delta = 10 if event.angleDelta().y() > 0 else -10
                self.change_zoom(target, delta)
                event.accept()
                return True
        if isinstance(watched, QScrollBar) and event.type() in (QEvent.Enter, QEvent.Leave):
            watched.setProperty("hovered", event.type() == QEvent.Enter)
            watched.style().unpolish(watched)
            watched.style().polish(watched)
            watched.update()
        return super().eventFilter(watched, event)

    def external_file_changed(self, filename):
        path = Path(filename)
        if path == self.current_path and self.save_guard:
            if path.exists() and str(path) not in self.watcher.files():
                self.watcher.addPath(str(path))
            return
        if path == self.current_path and not self.dirty and path.exists():
            QTimer.singleShot(150, lambda: self.load_file(path))
        else:
            self.refresh_files()

    def closeEvent(self, event: QCloseEvent):
        if not self.maybe_save():
            event.ignore()
            return
        self.save_layout()
        event.accept()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "expand_left_button") and self.centralWidget():
            self.expand_left_button.setGeometry(4, 16, 30, 30)
            self.expand_left_button.raise_()
        if hasattr(self, "preview") and self.preview.isVisible():
            QTimer.singleShot(120, self.update_preview)
        self.schedule_layout_save()

    def moveEvent(self, event):
        super().moveEvent(event)
        self.schedule_layout_save()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("项目航图")
    app.setStyle("Fusion")
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    window = MainWindow()
    theme = window.settings.value("theme", "dark")
    window.apply_theme(theme)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
