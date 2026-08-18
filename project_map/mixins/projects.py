from __future__ import annotations

import json
import datetime as dt
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QListWidgetItem

from ..config import MARKDOWN_DIR, PROJECTS_FILE

class ProjectsMixin:

    def load_metadata(self):
        try:
            return json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def save_metadata(self):
        PROJECTS_FILE.write_text(json.dumps(self.metadata, ensure_ascii=False, indent=2), encoding="utf-8")

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
