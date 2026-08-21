from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QListWidgetItem, QMenu

from ..config import MARKDOWN_DIR, PROJECTS_FILE


class ProjectsMixin:

    def load_metadata(self):
        try:
            data = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def save_metadata(self):
        PROJECTS_FILE.write_text(json.dumps(self.metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    @staticmethod
    def normalized_path(path):
        return str(Path(path).resolve(strict=False)).casefold()

    def same_path(self, first, second):
        return bool(first and second and self.normalized_path(first) == self.normalized_path(second))

    def is_local_project(self, path):
        return self.normalized_path(Path(path).parent) == self.normalized_path(MARKDOWN_DIR)

    def external_project_key(self, path):
        digest = hashlib.sha1(self.normalized_path(path).encode("utf-8")).hexdigest()[:16]
        return f"external:{digest}"

    def project_key(self, path):
        path = Path(path)
        if self.is_local_project(path):
            return path.name
        normalized = self.normalized_path(path)
        for key, meta in self.metadata.items():
            source = meta.get("source_path") if isinstance(meta, dict) else None
            if source and self.normalized_path(source) == normalized:
                return key
        return self.external_project_key(path)

    def project_meta(self, path, create=False):
        key = self.project_key(path)
        return self.metadata.setdefault(key, {}) if create else self.metadata.get(key, {})

    def all_project_paths(self):
        paths = list(MARKDOWN_DIR.glob("*.md"))
        known = {self.normalized_path(path) for path in paths}
        for meta in self.metadata.values():
            if not isinstance(meta, dict) or not meta.get("source_path"):
                continue
            path = Path(meta["source_path"]).expanduser()
            normalized = self.normalized_path(path)
            if path.is_file() and path.suffix.casefold() == ".md" and normalized not in known:
                paths.append(path)
                known.add(normalized)
        return paths

    def files(self):
        files = self.all_project_paths()
        group = str(self.settings.value("project_filter", "全部项目"))
        if group and group != "全部项目":
            files = [path for path in files if self.project_meta(path).get("group", "默认项目") == group]
        return sorted(files, key=self.project_sort_key)

    def project_sort_key(self, path):
        meta = self.project_meta(path)
        order = meta.get("order")
        order = order if isinstance(order, int) else 1_000_000_000
        return (not meta.get("pinned", False), order, path.name.casefold(), self.normalized_path(path))

    def ordered_bucket(self, pinned, exclude=None):
        paths = [
            path for path in self.all_project_paths()
            if bool(self.project_meta(path).get("pinned", False)) == pinned and not self.same_path(path, exclude)
        ]
        return sorted(paths, key=lambda path: (
            self.project_meta(path).get("order")
            if isinstance(self.project_meta(path).get("order"), int)
            else 1_000_000_000,
            path.name.casefold(),
            self.normalized_path(path),
        ))

    def next_project_order(self, pinned=False):
        orders = [
            self.project_meta(path).get("order")
            for path in self.all_project_paths()
            if bool(self.project_meta(path).get("pinned", False)) == pinned
            and isinstance(self.project_meta(path).get("order"), int)
        ]
        return max(orders, default=-1) + 1

    def refresh_groups(self):
        groups = sorted({self.project_meta(path).get("group", "默认项目") for path in self.all_project_paths()})
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
        if self.current_path:
            self.save_project_view_state(self.current_path)
        selected = str(self.current_path or self.settings.value("last_file", ""))
        self.refresh_groups()
        files = self.files()
        self.file_list.blockSignals(True)
        self.file_list.clear()
        for path in files:
            meta = self.project_meta(path)
            prefix = "↑ " if meta.get("pinned") else ""
            prefix += "★ " if meta.get("favorite") else ""
            item = QListWidgetItem(prefix + meta.get("display_name", path.stem))
            item.setData(Qt.UserRole, str(path))
            item.setData(Qt.UserRole + 1, self.project_key(path))
            stamp = dt.datetime.fromtimestamp(path.stat().st_mtime).strftime("%m-%d %H:%M")
            text = path.read_text(encoding="utf-8", errors="ignore")
            done, total = text.count("- [x]") + text.count("- [X]"), text.count("- [")
            states = []
            if meta.get("pinned"):
                states.append("已置顶")
            if not self.is_local_project(path):
                states.append("外部导入")
            state_text = f"\n状态：{' / '.join(states)}" if states else ""
            item.setToolTip(f"{path}\n{meta.get('description', '')}\n任务：{done}/{total}\n修改：{stamp}{state_text}")
            self.file_list.addItem(item)
        self.count_label.setText(f"{len(files)} 个项目")
        self.filter_files(self.search.text())
        target_index = -1
        for index in range(self.file_list.count()):
            if self.same_path(self.file_list.item(index).data(Qt.UserRole), selected):
                target_index = index
                break
        if target_index < 0 and files:
            target_index = 0
        if target_index >= 0:
            self.file_list.setCurrentRow(target_index)
            target_path = Path(self.file_list.item(target_index).data(Qt.UserRole))
        else:
            target_path = None
        self.file_list.blockSignals(False)
        if target_path:
            self.load_file(target_path)
        elif not files:
            self.current_path = None
            self.file_title.setText("请选择左侧项目")
            self.loading = True
            self.editor.clear()
            self.preview.clear()
            self.loading = False
            self.dirty = False
        self.update_pin_button()

    def filter_files(self, query):
        query = query.casefold().strip()
        for index in range(self.file_list.count()):
            item = self.file_list.item(index)
            path = Path(item.data(Qt.UserRole))
            content = path.read_text(encoding="utf-8", errors="ignore").casefold()
            item.setHidden(bool(query and query not in item.text().casefold() and query not in content))

    def select_file(self, current, _previous):
        if not current:
            self.update_pin_button()
            return
        target = Path(current.data(Qt.UserRole))
        if self.same_path(target, self.current_path):
            self.update_pin_button()
            return
        if self.current_path:
            self.save_project_view_state(self.current_path)
        if hasattr(self, "flush_auto_save"):
            self.flush_auto_save()
        if self.maybe_save():
            self.save_metadata()
            self.load_file(target)
        elif self.current_path:
            self.file_list.blockSignals(True)
            for index in range(self.file_list.count()):
                item = self.file_list.item(index)
                if self.same_path(item.data(Qt.UserRole), self.current_path):
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
        pinned = bool(path and self.project_meta(path).get("pinned", False))
        self.pin_button.setText("取消置顶" if pinned else "置顶")
        self.pin_button.setEnabled(path is not None)

    def toggle_project_pin(self, path=None):
        path = Path(path) if path else self.selected_project_path()
        if not path:
            return
        meta = self.project_meta(path, create=True)
        pinned = bool(meta.get("pinned", False))
        if not pinned:
            normal_paths = self.ordered_bucket(False)
            meta["pre_pin_position"] = next(
                (index for index, item in enumerate(normal_paths) if self.same_path(item, path)),
                len(normal_paths),
            )
            meta["pinned"] = True
            meta["order"] = -1
            self.normalize_project_orders()
        else:
            position = meta.pop("pre_pin_position", len(self.ordered_bucket(False)))
            try:
                position = max(0, int(position))
            except (TypeError, ValueError):
                position = len(self.ordered_bucket(False))
            meta["pinned"] = False
            normal_paths = self.ordered_bucket(False, exclude=path)
            normal_paths.insert(min(position, len(normal_paths)), path)
            for order, item in enumerate(normal_paths):
                self.project_meta(item, create=True)["order"] = order
            self.normalize_project_orders()
        self.save_metadata()
        self.current_path = path
        self.refresh_files()
        state = "已置顶" if not pinned else "已取消置顶并恢复原位置"
        self.statusBar().showMessage(f"{state}：{self.display_name(path)}")

    def normalize_project_orders(self):
        for pinned in (True, False):
            for order, path in enumerate(self.ordered_bucket(pinned)):
                self.project_meta(path, create=True)["order"] = order

    def persist_project_order(self):
        visible_paths = [
            Path(self.file_list.item(index).data(Qt.UserRole))
            for index in range(self.file_list.count())
            if not self.file_list.item(index).isHidden()
        ]
        for pinned in (True, False):
            displayed = [path for path in visible_paths if bool(self.project_meta(path).get("pinned", False)) == pinned]
            if not displayed:
                continue
            bucket = self.ordered_bucket(pinned)
            displayed_ids = {self.normalized_path(path) for path in displayed}
            slots = [index for index, path in enumerate(bucket) if self.normalized_path(path) in displayed_ids]
            for slot, path in zip(slots, displayed):
                bucket[slot] = path
            for order, path in enumerate(bucket):
                self.project_meta(path, create=True)["order"] = order
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
        pinned = bool(self.project_meta(path).get("pinned", False))
        pin_action = menu.addAction("取消置顶" if pinned else "置顶")
        pin_action.triggered.connect(lambda: self.toggle_project_pin(path))
        menu.addSeparator()
        properties_action = menu.addAction("项目属性")
        properties_action.triggered.connect(self.edit_project)
        delete_action = menu.addAction("删除项目")
        delete_action.triggered.connect(self.delete_file)
        menu.exec(self.file_list.viewport().mapToGlobal(position))

    def save_project_view_state(self, path=None):
        path = Path(path or self.current_path) if path or self.current_path else None
        if not path or not hasattr(self, "editor"):
            return
        cursor = self.editor.textCursor()
        self.project_meta(path, create=True)["view_state"] = {
            "editor_vertical": self.editor.verticalScrollBar().value(),
            "editor_horizontal": self.editor.horizontalScrollBar().value(),
            "cursor": cursor.position(),
            "preview_vertical": self.preview.verticalScrollBar().value(),
            "preview_horizontal": self.preview.horizontalScrollBar().value(),
        }

    def restore_project_view_state(self, path, attempt=0):
        if not self.same_path(path, self.current_path):
            return
        state = self.project_meta(path).get("view_state", {})
        if not isinstance(state, dict):
            return
        cursor_position = min(max(0, int(state.get("cursor", 0))), max(0, self.editor.document().characterCount() - 1))
        cursor = self.editor.textCursor()
        cursor.setPosition(cursor_position)
        self.editor.setTextCursor(cursor)
        editor_vertical = int(state.get("editor_vertical", 0))
        editor_horizontal = int(state.get("editor_horizontal", 0))
        preview_vertical = int(state.get("preview_vertical", 0))
        preview_horizontal = int(state.get("preview_horizontal", 0))
        self.editor.verticalScrollBar().setValue(min(editor_vertical, self.editor.verticalScrollBar().maximum()))
        self.editor.horizontalScrollBar().setValue(min(editor_horizontal, self.editor.horizontalScrollBar().maximum()))
        self.preview.verticalScrollBar().setValue(min(preview_vertical, self.preview.verticalScrollBar().maximum()))
        self.preview.horizontalScrollBar().setValue(min(preview_horizontal, self.preview.horizontalScrollBar().maximum()))
        needs_retry = (
            (editor_vertical and self.editor.verticalScrollBar().maximum() == 0)
            or (preview_vertical and self.preview.verticalScrollBar().maximum() == 0)
        )
        if needs_retry and attempt < 6:
            QTimer.singleShot(35, lambda: self.restore_project_view_state(path, attempt + 1))

    def load_file(self, path):
        path = Path(path)
        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            content = path.read_text(encoding="utf-8-sig")
        except OSError as error:
            self.statusBar().showMessage(f"打开失败：{error}")
            return
        self.loading = True
        self.current_path = path
        self.settings.setValue("last_file", str(path))
        self.editor.pasted_number_blocks = []
        self.editor.current_document_path = path
        self.editor.setPlainText(content)
        self.loading = False
        self.dirty = False
        self.file_title.setText(self.display_name(path))
        self.update_preview()
        self.update_sidebar()
        self.statusBar().showMessage(f"已打开：{path.name}")
        if str(path) not in self.watcher.files():
            self.watcher.addPath(str(path))
        QTimer.singleShot(0, lambda: self.restore_project_view_state(path))

    def display_name(self, path):
        return self.project_meta(path).get("display_name", Path(path).stem)
