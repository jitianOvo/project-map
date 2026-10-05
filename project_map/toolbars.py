from __future__ import annotations

import json

from PySide6.QtCore import QEvent, QSize, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QSizePolicy, QTabWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from .appearance import apply_window_icon
from .menus import RoundedMenu


def toolbar_order(settings, key, defaults):
    try:
        stored = json.loads(str(settings.value(f"toolbar/{key}/order", "[]")))
    except (ValueError, TypeError):
        stored = []
    order = [item for item in stored if item in defaults]
    return list(dict.fromkeys([*order, *defaults]))


def toolbar_enabled(settings, key, defaults):
    try:
        hidden = json.loads(str(settings.value(f"toolbar/{key}/hidden", "[]")))
    except (ValueError, TypeError):
        hidden = []
    return [item for item in toolbar_order(settings, key, defaults) if item not in hidden]


class AdaptiveToolBar(QWidget):
    settings_requested = Signal()
    collapsed_changed = Signal(bool)

    def __init__(self, title, icons_only=False, parent=None):
        super().__init__(parent)
        self.title = title
        self.icons_only = icons_only
        self.collapsed = False
        self.entries = []
        self.buttons = []
        self.observed_actions = set()
        self.reflow_timer = QTimer(self)
        self.reflow_timer.setSingleShot(True)
        self.reflow_timer.timeout.connect(self.reflow)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.setMinimumWidth(0)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(3, 3, 3, 3)
        self.row.setSpacing(3)
        self.toggle = QToolButton(self)
        self.toggle.setObjectName("modeButton")
        self.toggle.clicked.connect(lambda: self.set_collapsed(not self.collapsed))
        self.row.addWidget(self.toggle)
        self.row.addStretch(1)
        self.overflow = QToolButton(self)
        self.overflow.setObjectName("modeButton")
        self.overflow.setText("»")
        self.overflow.setToolTip("显示放不下的工具")
        self.overflow.setPopupMode(QToolButton.InstantPopup)
        self.overflow_menu = RoundedMenu(self)
        self.overflow.setMenu(self.overflow_menu)
        self.row.addWidget(self.overflow)
        self.configure = QToolButton(self)
        self.configure.setObjectName("modeButton")
        self.configure.setText("设置")
        self.configure.setToolTip("工具栏排序、显示与隐藏")
        self.configure.clicked.connect(self.settings_requested)
        self.row.addWidget(self.configure)
        self.set_collapsed(False, notify=False)

    def set_entries(self, entries):
        for button in self.buttons:
            self.row.removeWidget(button)
            button.deleteLater()
        self.entries = list(entries)
        self.buttons = []
        for index, action in enumerate(self.entries):
            button = QToolButton(self)
            button.setDefaultAction(action)
            button.setObjectName("formatButton" if self.icons_only else "modeButton")
            button.setToolButtonStyle(Qt.ToolButtonIconOnly if self.icons_only else Qt.ToolButtonTextOnly)
            button.setIconSize(QSize(22, 22))
            self.row.insertWidget(index + 1, button)
            self.buttons.append(button)
            if action not in self.observed_actions:
                action.changed.connect(self.schedule_reflow)
                self.observed_actions.add(action)
        self.reflow()
        self.schedule_reflow()

    def schedule_reflow(self):
        self.reflow_timer.start(0)

    def set_collapsed(self, collapsed, notify=True):
        self.collapsed = bool(collapsed)
        self.toggle.setText(f"{self.title} {'▸' if self.collapsed else '▾'}")
        self.toggle.setToolTip(f"{'展开' if self.collapsed else '收起'}{self.title}")
        self.reflow()
        if notify:
            self.collapsed_changed.emit(self.collapsed)

    def reflow(self):
        self.overflow_menu.clear()
        if self.collapsed:
            for button in self.buttons:
                button.hide()
            self.overflow.hide()
            return
        margins = self.row.contentsMargins()
        reserved = margins.left() + margins.right() + self.toggle.sizeHint().width() + self.configure.sizeHint().width()
        active = [(button, action) for button, action in zip(self.buttons, self.entries) if action.isVisible()]
        sizes = [button.sizeHint().width() for button, _action in active]
        for button, action in zip(self.buttons, self.entries):
            if not action.isVisible():
                button.hide()
        available = max(0, self.width() - reserved - 12)
        overflow_needed = sum(sizes) + len(sizes) * self.row.spacing() > available
        if overflow_needed:
            available -= self.overflow.sizeHint().width() + self.row.spacing()
        used = 0
        overflowing = False
        for (button, action), width in zip(active, sizes):
            used += width + self.row.spacing()
            overflowing = overflowing or used > available
            button.setVisible(not overflowing)
            if overflowing:
                self.overflow_menu.addAction(action)
        self.overflow.setVisible(bool(self.overflow_menu.actions()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "row") and event.type() in (QEvent.StyleChange, QEvent.FontChange):
            self.schedule_reflow()


class ToolbarSettingsDialog(QDialog):
    def __init__(self, settings, catalogs, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.catalogs = catalogs
        self.lists = {}
        self.setWindowTitle("工具栏设置")
        apply_window_icon(self)
        self.resize(530, 560)
        layout = QVBoxLayout(self)
        note = QLabel("勾选需要的工具，拖动条目调整顺序。隐藏工具后，原快捷键仍可使用。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs = QTabWidget()
        for key, (title, actions) in catalogs.items():
            view = QListWidget()
            view.setDragDropMode(QAbstractItemView.InternalMove)
            self.lists[key] = view
            enabled = toolbar_enabled(settings, key, actions)
            self.populate(view, toolbar_order(settings, key, actions), actions, enabled)
            self.tabs.addTab(view, title)
        layout.addWidget(self.tabs, 1)
        controls = QHBoxLayout()
        for label, delta in (("上移", -1), ("下移", 1)):
            button = QPushButton(label)
            button.clicked.connect(lambda _checked=False, value=delta: self.move_selected(value))
            controls.addWidget(button)
        defaults = QPushButton("恢复默认")
        defaults.clicked.connect(self.restore_defaults)
        controls.addWidget(defaults)
        controls.addStretch()
        layout.addLayout(controls)
        footer = QHBoxLayout()
        footer.addStretch()
        cancel = QPushButton("取消")
        save = QPushButton("保存设置")
        save.setObjectName("primaryButton")
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        footer.addWidget(cancel)
        footer.addWidget(save)
        layout.addLayout(footer)

    @staticmethod
    def populate(view, order, actions, enabled):
        view.clear()
        for key in order:
            action = actions[key]
            item = QListWidgetItem(action.icon(), action.text())
            item.setData(Qt.UserRole, key)
            item.setToolTip(action.toolTip())
            item.setCheckState(Qt.Checked if key in enabled else Qt.Unchecked)
            view.addItem(item)

    def move_selected(self, delta):
        view = self.tabs.currentWidget()
        index = view.currentRow()
        target = index + delta
        if index >= 0 and 0 <= target < view.count():
            item = view.takeItem(index)
            view.insertItem(target, item)
            view.setCurrentItem(item)

    def restore_defaults(self):
        for key, (_title, actions) in self.catalogs.items():
            self.populate(self.lists[key], list(actions), actions, list(actions))

    def save_configuration(self):
        for key, view in self.lists.items():
            order = [view.item(index).data(Qt.UserRole) for index in range(view.count())]
            hidden = [view.item(index).data(Qt.UserRole) for index in range(view.count()) if view.item(index).checkState() != Qt.Checked]
            self.settings.setValue(f"toolbar/{key}/order", json.dumps(order))
            self.settings.setValue(f"toolbar/{key}/hidden", json.dumps(hidden))
        self.settings.sync()
