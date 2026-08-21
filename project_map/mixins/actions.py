from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

from PySide6.QtCore import QRegularExpression, QTimer, QUrl, Qt
from PySide6.QtGui import QAction, QColor, QCloseEvent, QDesktopServices, QIcon, QKeySequence, QTextCursor, QTextDocument
from PySide6.QtWidgets import QApplication, QCheckBox, QFileDialog, QDialog, QLineEdit, QMessageBox

from ..config import APP_DIR, BACKUP_DIR, DATA_DIR, ICON_PATH, MARKDOWN_DIR
from ..dialogs import FindReplaceDialog, NameDialog, ProjectDialog

class ActionsMixin:

    def maybe_save(self):
        if not self.dirty:
            return True
        if hasattr(self, "auto_save_timer") and self.auto_save_timer.isActive() and self.flush_auto_save():
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

    def save_file(self, _checked=False, *, create_backup=True, quiet=False):
        if not self.current_path:
            return False
        cursor = self.editor.textCursor()
        cursor_position = cursor.position()
        cursor_anchor = cursor.anchor()
        horizontal = self.editor.horizontalScrollBar().value()
        vertical = self.editor.verticalScrollBar().value()
        self.save_guard = True
        try:
            if create_backup and self.current_path.exists():
                stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
                shutil.copy2(self.current_path, BACKUP_DIR / f"{self.current_path.stem}_{stamp}.md.bak")
            self.current_path.write_text(self.editor.toPlainText(), encoding="utf-8")
        except OSError as error:
            self.save_guard = False
            self.statusBar().showMessage(f"保存失败：{error}")
            return False
        restored = self.editor.textCursor()
        restored.setPosition(cursor_position)
        restored.setPosition(cursor_anchor, QTextCursor.KeepAnchor)
        self.editor.setTextCursor(restored)
        self.editor.horizontalScrollBar().setValue(horizontal)
        self.editor.verticalScrollBar().setValue(vertical)
        self.save_guard_timer.start()
        self.dirty = False
        self.save_project_view_state(self.current_path)
        self.save_metadata()
        self.file_title.setText(self.display_name(self.current_path))
        self.statusBar().showMessage(f"{'已自动保存' if quiet else '已保存'}：{self.current_path.name}")
        return True

    def auto_save_file(self):
        if self.loading or not self.dirty or not self.current_path:
            return True
        return self.save_file(create_backup=False, quiet=True)

    def flush_auto_save(self):
        if hasattr(self, "auto_save_timer"):
            self.auto_save_timer.stop()
        return self.auto_save_file()

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
        self.metadata[self.project_key(path)] = {
            "display_name": path.stem,
            "group": "默认项目",
            "description": "",
            "pinned": False,
            "order": self.next_project_order(False),
        }
        self.save_metadata()
        self.current_path = path
        self.refresh_files()

    def edit_project(self):
        if not self.current_path:
            return
        meta = self.project_meta(self.current_path, create=True)
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
        path = Path(source).resolve()
        for existing in self.all_project_paths():
            if self.same_path(existing, path):
                self.current_path = existing
                self.refresh_files()
                self.statusBar().showMessage(f"项目已经在项目库中：{path.name}")
                return
        key = self.external_project_key(path)
        self.metadata[key] = {
            "source_path": str(path),
            "display_name": path.stem,
            "group": "默认项目",
            "description": "",
            "pinned": False,
            "order": self.next_project_order(False),
        }
        self.save_metadata()
        self.current_path = path
        self.refresh_files()
        self.statusBar().showMessage(f"已链接外部项目：{path}")

    def delete_file(self):
        path = self.selected_project_path()
        if not path or not self.maybe_save():
            return
        external = not self.is_local_project(path)
        box = QMessageBox(self)
        box.setWindowTitle("删除项目大纲")
        box.setText(f"要删除“{self.display_name(path)}”吗？")
        box.setInformativeText(
            "默认只从项目库移除链接，不改动外部原文件；勾选后将删除外部原文件。"
            if external else
            "默认会移入备份目录；勾选永久删除后将直接删除原文件。"
        )
        permanent = QCheckBox("同时永久删除外部原文件" if external else "永久删除，不保留备份")
        box.setCheckBox(permanent)
        delete_button = box.addButton("移出项目库" if external else "移入备份", QMessageBox.DestructiveRole)
        box.addButton("暂不删除", QMessageBox.RejectRole)
        permanent.toggled.connect(
            lambda checked: delete_button.setText(
                "永久删除原文件" if checked and external
                else "永久删除" if checked
                else "移出项目库" if external
                else "移入备份"
            )
        )
        box.exec()
        if box.clickedButton() is not delete_button:
            return
        self.remove_project_file(path, permanent.isChecked())

    def remove_project_file(self, path, permanent=False):
        path = Path(path)
        key = self.project_key(path)
        external = not self.is_local_project(path)
        display_name = self.display_name(path)
        if str(path) in self.watcher.files():
            self.watcher.removePath(str(path))
        stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        if permanent:
            path.unlink()
            result = f"已永久删除：{display_name}"
        elif external:
            result = f"已移出项目库，外部原文件保持不变：{display_name}"
        else:
            shutil.move(str(path), str(BACKUP_DIR / f"{path.stem}_{stamp}.md.deleted"))
            result = f"已移入备份：{display_name}"
        self.metadata.pop(key, None)
        self.save_metadata()
        self.current_path = None
        self.refresh_files()
        self.statusBar().showMessage(result)

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
            QListWidget::item { padding:9px; border-radius:8px; margin:2px 0; outline:0; }
            QListWidget::item:selected { background:#dbeafe; color:#1d4ed8; border-radius:8px; }
            QListWidget::drop-indicator { background:#3b82f6; height:2px; }
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
        QListWidget::item { padding:9px; border-radius:8px; margin:2px 0; outline:0; }
        QListWidget::item:selected { background:#274d83; color:#ffffff; border-radius:8px; }
        QListWidget::drop-indicator { background:#60a5fa; height:2px; }
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

    def external_file_changed(self, filename):
        path = Path(filename)
        if self.same_path(path, self.current_path) and self.save_guard:
            if path.exists() and str(path) not in self.watcher.files():
                self.watcher.addPath(str(path))
            return
        if self.same_path(path, self.current_path) and not self.dirty and path.exists():
            QTimer.singleShot(150, lambda: self.load_file(path))
        else:
            self.refresh_files()

    def closeEvent(self, event: QCloseEvent):
        self.save_project_view_state()
        self.flush_auto_save()
        if not self.maybe_save():
            event.ignore()
            return
        self.save_metadata()
        self.save_layout()
        event.accept()
