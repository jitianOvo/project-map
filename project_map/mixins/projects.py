from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtGui import QTextCursor
from PySide6.QtWidgets import QDialog, QListWidgetItem, QMenu, QMessageBox

from ..appearance import apply_window_icon
from ..config import MARKDOWN_DIR, PROJECTS_FILE
from ..dialogs import NameDialog


class ProjectsMixin:

    DEFAULT_GROUP = "默认项目"
    ALL_GROUPS = "全部项目"

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

    def project_groups(self):
        raw = self.settings.value("project_groups", "")
        try:
            saved = json.loads(raw) if isinstance(raw, str) and raw else list(raw or [])
        except (TypeError, json.JSONDecodeError):
            saved = []
        discovered = [
            str(self.project_meta(path).get("group", self.DEFAULT_GROUP)).strip() or self.DEFAULT_GROUP
            for path in self.all_project_paths()
        ]
        groups = []
        for name in [self.DEFAULT_GROUP, *saved, *discovered]:
            if name != self.ALL_GROUPS and name.casefold() not in {item.casefold() for item in groups}:
                groups.append(name)
        return groups

    def save_project_groups(self, groups):
        cleaned = []
        for name in [self.DEFAULT_GROUP, *groups]:
            name = str(name).strip()
            if name and name != self.ALL_GROUPS and name.casefold() not in {item.casefold() for item in cleaned}:
                cleaned.append(name)
        self.settings.setValue("project_groups", json.dumps(cleaned, ensure_ascii=False))

    def register_project_group(self, name):
        name = str(name).strip() or self.DEFAULT_GROUP
        groups = self.project_groups()
        for group in groups:
            if group.casefold() == name.casefold():
                return group
        groups.append(name)
        self.save_project_groups(groups)
        return name

    def active_project_group(self):
        selected = str(self.settings.value("project_filter", self.ALL_GROUPS))
        return selected if selected in self.project_groups() else self.DEFAULT_GROUP

    def refresh_groups(self):
        groups = self.project_groups()
        selected = str(self.settings.value("project_filter", self.ALL_GROUPS))
        if selected != self.ALL_GROUPS and selected not in groups:
            selected = self.ALL_GROUPS
        self.filter_menu.clear()
        all_action = self.filter_menu.addAction(self.ALL_GROUPS)
        all_action.setData(self.ALL_GROUPS)
        all_action.setCheckable(True)
        all_action.triggered.connect(lambda: self.activate_project_filter(self.ALL_GROUPS))
        self.filter_menu.addSeparator()
        for group in groups:
            action = self.filter_menu.addAction(group)
            action.setData(group)
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, value=group: self.activate_project_filter(value))
        self.filter_menu.addSeparator()
        create_action = self.filter_menu.addAction("＋ 新建分组…")
        create_action.triggered.connect(lambda: self.create_project_group())
        delete_action = self.filter_menu.addAction("删除当前分组…")
        delete_action.setEnabled(selected not in {self.ALL_GROUPS, self.DEFAULT_GROUP})
        delete_action.triggered.connect(self.delete_current_group)
        self.set_project_filter_by_name(selected)

    def set_project_filter(self, action):
        name = action.data()
        if not name:
            return
        self.set_project_filter_by_name(str(name))
        self.refresh_files()

    def activate_project_filter(self, name):
        self.set_project_filter_by_name(name)
        self.refresh_files()

    def set_project_filter_by_name(self, name):
        name = name if name else self.ALL_GROUPS
        self.settings.setValue("project_filter", name)
        self.filter_button.setText(f"{name}  ▾")
        for action in self.filter_menu.actions():
            action.setChecked(action.data() == name)
        self.filter_menu.setSeparatorsCollapsible(False)

    def create_project_group(self, assign_path=None):
        assign_path = None if isinstance(assign_path, bool) else assign_path
        previous_filter = str(self.settings.value("project_filter", self.ALL_GROUPS))
        dialog = NameDialog("新建项目分组", "分组名称", "新分组", self)
        if dialog.exec() != QDialog.Accepted:
            return
        name = dialog.value.text().strip()
        if not name:
            return
        if name == self.ALL_GROUPS:
            self.show_notice("名称不可使用", f'“{self.ALL_GROUPS}”是系统筛选项，请换一个名称。')
            return
        groups = self.project_groups()
        if name.casefold() in {group.casefold() for group in groups}:
            self.show_notice("分组已存在", f'项目分组“{name}”已经存在。')
            return
        groups.append(name)
        self.save_project_groups(groups)
        if assign_path:
            path = Path(assign_path)
            self.project_meta(path, create=True)["group"] = name
            self.save_metadata()
            self.current_path = path
            self.set_project_filter_by_name(previous_filter)
        else:
            self.set_project_filter_by_name(name)
        self.refresh_files()
        self.statusBar().showMessage(
            f"已新建分组并归入项目：{name}" if assign_path else f"已新建项目分组：{name}"
        )

    def delete_current_group(self):
        group = str(self.settings.value("project_filter", self.ALL_GROUPS))
        if group in {self.ALL_GROUPS, self.DEFAULT_GROUP}:
            return
        affected = [path for path in self.all_project_paths() if self.project_meta(path).get("group", self.DEFAULT_GROUP) == group]
        box = QMessageBox(self)
        apply_window_icon(box)
        box.setWindowTitle("删除项目分组")
        box.setText(f'要删除分组“{group}”吗？')
        box.setInformativeText(f"其中的 {len(affected)} 个项目会转入“{self.DEFAULT_GROUP}”，项目文件本身不会被删除。")
        delete_button = box.addButton("删除分组", QMessageBox.DestructiveRole)
        box.addButton("暂不删除", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not delete_button:
            return
        for path in affected:
            self.project_meta(path, create=True)["group"] = self.DEFAULT_GROUP
        self.save_project_groups([name for name in self.project_groups() if name != group])
        self.settings.setValue("project_filter", self.DEFAULT_GROUP)
        self.save_metadata()
        self.refresh_files()
        self.statusBar().showMessage(f"已删除分组“{group}”，原有项目已转入默认项目")

    def assign_project_to_group(self, path, group):
        path = Path(path)
        group = self.register_project_group(group)
        self.project_meta(path, create=True)["group"] = group
        self.save_metadata()
        self.current_path = path
        self.refresh_files()
        self.statusBar().showMessage(f"已将“{self.display_name(path)}”归入“{group}”")

    def refresh_files(self):
        if self.current_path:
            self.save_project_view_state(self.current_path)
        selected = str(self.current_path or self.settings.value("last_file", ""))
        self.refresh_groups()
        files = self.files()
        self.file_list.blockSignals(True)
        self.file_list.clear()
        display_counts = {}
        for path in files:
            name = self.display_name(path).casefold()
            display_counts[name] = display_counts.get(name, 0) + 1
        for path in files:
            meta = self.project_meta(path)
            prefix = "↑ " if meta.get("pinned") else ""
            prefix += "★ " if meta.get("favorite") else ""
            display_name = meta.get("display_name", path.stem)
            disambiguation = f"  ·  {path.resolve(strict=False).parent}" if display_counts[display_name.casefold()] > 1 else ""
            item = QListWidgetItem(prefix + display_name + disambiguation)
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
        group_menu = menu.addMenu("归入分组")
        current_group = self.project_meta(path).get("group", self.DEFAULT_GROUP)
        for group in self.project_groups():
            action = group_menu.addAction(group)
            action.setCheckable(True)
            action.setChecked(group == current_group)
            action.triggered.connect(lambda _checked=False, value=group: self.assign_project_to_group(path, value))
        group_menu.addSeparator()
        create_group_action = group_menu.addAction("＋ 新建分组…")
        create_group_action.triggered.connect(lambda: self.create_project_group(path))
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
        display_name = self.display_name(path)
        duplicates = [item for item in self.all_project_paths() if self.display_name(item).casefold() == display_name.casefold()]
        self.file_title.setText(
            f"{display_name}  ·  {path.resolve(strict=False).parent}" if len(duplicates) > 1 else display_name
        )
        self.file_title.setToolTip(str(path.resolve(strict=False)))
        self.update_preview()
        self.update_sidebar()
        self.statusBar().showMessage(f"已打开：{path.name}")
        if str(path) not in self.watcher.files():
            self.watcher.addPath(str(path))
        QTimer.singleShot(0, lambda: self.restore_project_view_state(path))

    def display_name(self, path):
        return str(self.project_meta(path).get("display_name") or Path(path).stem)
