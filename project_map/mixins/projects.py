from __future__ import annotations

import json
import datetime as dt
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QListWidgetItem, QMenu

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
        return sorted(files, key=self.project_sort_key)

    def project_sort_key(self, path):
        meta = self.metadata.get(path.name, {})
        order = meta.get("order")
        order = order if isinstance(order, int) else 1_000_000_000
        return (not meta.get("pinned", False), order, path.name.casefold())

    def next_project_order(self, pinned=False):
        orders = [
            meta.get("order")
            for meta in self.metadata.values()
            if bool(meta.get("pinned", False)) == pinned and isinstance(meta.get("order"), int)
        ]
        return max(orders, default=-1) + 1

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
            prefix = "↑ " if meta.get("pinned") else ""
            prefix += "★ " if meta.get("favorite") else ""
            item = QListWidgetItem(prefix + meta.get("display_name", path.stem))
            item.setData(Qt.UserRole, str(path))
            stamp = dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%m-%d %H:%M")
            text = path.read_text(encoding="utf-8", errors="ignore")
            done, total = text.count("- [x]") + text.count("- [X]"), text.count("- [")
            pinned_text = "\n状态：已置顶" if meta.get("pinned") else ""
            item.setToolTip(f"{path.name}\n{meta.get('description', '')}\n任务：{done}/{total}\n修改：{stamp}{pinned_text}")
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
        self.update_pin_button()

    def filter_files(self, query):
        query = query.casefold().strip()
        for i in range(self.file_list.count()):
            item = self.file_list.item(i)
            path = Path(item.data(Qt.UserRole))
            content = path.read_text(encoding="utf-8", errors="ignore").casefold()
            item.setHidden(bool(query and query not in item.text().casefold() and query not in content))

    def select_file(self, current, _previous):
        if not current:
            self.update_pin_button()
            return
        if self.maybe_save():
            self.load_file(Path(current.data(Qt.UserRole)))
        elif self.current_path:
            self.file_list.blockSignals(True)
            for index in range(self.file_list.count()):
                item = self.file_list.item(index)
                if Path(item.data(Qt.UserRole)) == self.current_path:
                    self.file_list.setCurrentItem(item)
                    break
            self.file_list.blockSignals(False)
        self.update_pin_button()

    def selected_project_path(self):
        item = self.file_list.currentItem()
        return Path(item.data(Qt.UserRole)) if item else self.current_path

    def update_pin_button(self):
        if not hasattr(self, "pin_button"):
            return
        path = self.selected_project_path()
        pinned = bool(path and self.metadata.get(path.name, {}).get("pinned", False))
        self.pin_button.setText("取消置顶" if pinned else "置顶")
        self.pin_button.setEnabled(path is not None)

    def toggle_project_pin(self, path=None):
        path = Path(path) if path else self.selected_project_path()
        if not path:
            return
        meta = self.metadata.setdefault(path.name, {})
        pinned = not bool(meta.get("pinned", False))
        meta["pinned"] = pinned
        meta["order"] = -1
        self.normalize_project_orders()
        self.save_metadata()
        self.current_path = path
        self.refresh_files()
        state = "已置顶" if pinned else "已取消置顶"
        self.statusBar().showMessage(f"{state}：{self.display_name(path)}")

    def normalize_project_orders(self):
        paths = list(MARKDOWN_DIR.glob("*.md"))
        for pinned in (True, False):
            bucket = [path for path in paths if bool(self.metadata.get(path.name, {}).get("pinned", False)) == pinned]
            bucket.sort(key=lambda path: (
                self.metadata.get(path.name, {}).get("order")
                if isinstance(self.metadata.get(path.name, {}).get("order"), int)
                else 1_000_000_000,
                path.name.casefold(),
            ))
            for order, path in enumerate(bucket):
                self.metadata.setdefault(path.name, {})["order"] = order

    def persist_project_order(self):
        visible_order = [
            Path(self.file_list.item(index).data(Qt.UserRole)).name
            for index in range(self.file_list.count())
            if not self.file_list.item(index).isHidden()
        ]
        all_paths = list(MARKDOWN_DIR.glob("*.md"))
        for pinned in (True, False):
            displayed = [name for name in visible_order if bool(self.metadata.get(name, {}).get("pinned", False)) == pinned]
            if not displayed:
                continue
            bucket = [path.name for path in all_paths if bool(self.metadata.get(path.name, {}).get("pinned", False)) == pinned]
            bucket.sort(key=lambda name: (
                self.metadata.get(name, {}).get("order")
                if isinstance(self.metadata.get(name, {}).get("order"), int)
                else 1_000_000_000,
                name.casefold(),
            ))
            displayed_set = set(displayed)
            slots = [index for index, name in enumerate(bucket) if name in displayed_set]
            for slot, name in zip(slots, displayed):
                bucket[slot] = name
            for order, name in enumerate(bucket):
                self.metadata.setdefault(name, {})["order"] = order
        self.save_metadata()
        selected = self.selected_project_path()
        if selected:
            self.current_path = selected
        self.refresh_files()
        self.statusBar().showMessage("项目顺序已保存")

    def show_project_context_menu(self, position):
        item = self.file_list.itemAt(position)
        if not item:
            return
        self.file_list.setCurrentItem(item)
        path = Path(item.data(Qt.UserRole))
        menu = QMenu(self.file_list)
        pinned = bool(self.metadata.get(path.name, {}).get("pinned", False))
        pin_action = menu.addAction("取消置顶" if pinned else "置顶")
        pin_action.triggered.connect(lambda: self.toggle_project_pin(path))
        menu.addSeparator()
        properties_action = menu.addAction("项目属性")
        properties_action.triggered.connect(self.edit_project)
        delete_action = menu.addAction("删除项目")
        delete_action.triggered.connect(self.delete_file)
        menu.exec(self.file_list.viewport().mapToGlobal(position))

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
