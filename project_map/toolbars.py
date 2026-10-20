from __future__ import annotations

import json

from PySide6.QtCore import QEasingCurve, QEvent, Property, QPropertyAnimation, QSize, QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QPushButton, QSizePolicy, QTabWidget, QToolButton,
    QVBoxLayout, QWidget,
)

from .appearance import apply_window_icon
from .menus import RoundedMenu
from .project_list import NoFocusFrameDelegate


TOOL_LABEL_ALIASES = {
    "最紧急（红色）": "紧急",
    "优先（蓝色）": "优先",
    "普通（绿色）": "普通",
}


def toolbar_order(settings, key, defaults):
    try:
        stored = json.loads(str(settings.value(f"toolbar/{key}/order", "[]")))
    except (ValueError, TypeError):
        stored = []
    order = [TOOL_LABEL_ALIASES.get(item, item) for item in stored]
    order = [item for item in order if item in defaults]
    return list(dict.fromkeys([*order, *defaults]))


def toolbar_enabled(settings, key, defaults):
    try:
        hidden = json.loads(str(settings.value(f"toolbar/{key}/hidden", "[]")))
    except (ValueError, TypeError):
        hidden = []
    hidden = [TOOL_LABEL_ALIASES.get(item, item) for item in hidden]
    return [item for item in toolbar_order(settings, key, defaults) if item not in hidden]


class AdaptiveToolBar(QWidget):
    settings_requested = Signal()
    collapsed_changed = Signal(bool)
    reveal_changed = Signal(float)

    def __init__(self, title, icons_only=False, parent=None, show_settings=True):
        super().__init__(parent)
        self.title = title
        self.icons_only = icons_only
        self.collapsed = False
        self.entries = []
        self.buttons = []
        self.observed_actions = set()
        self.fade_effect = None
        self.transitioning = False
        self._reveal_progress = 1.0
        self.transition_animation = QPropertyAnimation(self, b"revealProgress", self)
        self.transition_animation.setEasingCurve(QEasingCurve.InOutCubic)
        self.transition_animation.finished.connect(self.finish_transition)
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
        self.tool_slot = QWidget(self)
        self.tool_slot.setObjectName("toolbarSlot")
        self.tool_slot.setStyleSheet("QWidget#toolbarSlot, QWidget#toolbarViewport { background:transparent; border:0; }")
        self.tool_slot.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.tool_slot.setMinimumWidth(0)
        self.tool_slot.installEventFilter(self)
        self.tool_viewport = QWidget(self.tool_slot)
        self.tool_viewport.setObjectName("toolbarViewport")
        self.tools = QWidget(self.tool_viewport)
        self.tools.setObjectName("toolbarContent")
        self.tools.setStyleSheet("QWidget#toolbarContent { background:transparent; border:0; }")
        self.tools.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.tools.setMinimumWidth(0)
        self.tools.installEventFilter(self)
        self.tools_row = QHBoxLayout(self.tools)
        self.tools_row.setContentsMargins(0, 0, 0, 0)
        self.tools_row.setSpacing(3)
        self.tools_row.addStretch(1)
        self.row.addWidget(self.tool_slot, 1)
        self.overflow = QToolButton(self.tools)
        self.overflow.setObjectName("modeButton")
        self.overflow.setText("»")
        self.overflow.setToolTip("显示放不下的工具")
        self.overflow.setPopupMode(QToolButton.InstantPopup)
        self.overflow_menu = RoundedMenu(self)
        self.overflow.setMenu(self.overflow_menu)
        self.tools_row.addWidget(self.overflow)
        self.configure = None
        if show_settings:
            self.configure = QToolButton(self)
            self.configure.setObjectName("modeButton")
            self.configure.setText("设置")
            self.configure.setToolTip("统一设置快速工具和格式工具")
            self.configure.clicked.connect(self.settings_requested)
            self.row.addWidget(self.configure)
        self.set_collapsed(False, notify=False)

    def set_entries(self, entries):
        self.finish_transition()
        for button in self.buttons:
            self.tools_row.removeWidget(button)
            button.hide()
            button.deleteLater()
        self.entries = list(entries)
        self.buttons = []
        for index, action in enumerate(self.entries):
            button = QToolButton(self.tools)
            button.setDefaultAction(action)
            button.setObjectName("formatButton" if self.icons_only else "modeButton")
            button.setToolButtonStyle(Qt.ToolButtonIconOnly if self.icons_only else Qt.ToolButtonTextOnly)
            button.setIconSize(QSize(22, 22))
            self.tools_row.insertWidget(index, button)
            self.buttons.append(button)
            if action not in self.observed_actions:
                action.changed.connect(self.schedule_reflow)
                self.observed_actions.add(action)
        self.reflow()
        self.schedule_reflow()

    def schedule_reflow(self):
        self.reflow_timer.start(0)

    def set_collapsed(self, collapsed, notify=True, animate=None):
        previous = self.collapsed
        self.collapsed = bool(collapsed)
        self.toggle.setText(f"{self.title} {'▸' if self.collapsed else '▾'}")
        self.toggle.setToolTip(f"{'展开' if self.collapsed else '收起'}{self.title}")
        if animate is None:
            animate = notify and self.icons_only and self.isVisible()
        if previous != self.collapsed and animate:
            self.start_transition()
        elif not animate:
            self.finish_transition()
            self.set_reveal_progress(0.0 if self.collapsed else 1.0)
            self.tools.setEnabled(not self.collapsed)
            self.reflow()
        if notify and previous != self.collapsed:
            self.collapsed_changed.emit(self.collapsed)

    def start_transition(self):
        self.transition_animation.stop()
        if self.fade_effect is None:
            self.fade_effect = QGraphicsOpacityEffect(self.tools)
            self.tools.setGraphicsEffect(self.fade_effect)
        start = self._reveal_progress
        end = 0.0 if self.collapsed else 1.0
        self.transitioning = True
        self.tools.setEnabled(not self.collapsed)
        self.reflow()
        self.set_reveal_progress(start)
        self.transition_animation.setDuration(max(45, round(150 * abs(end - start))))
        self.transition_animation.setStartValue(start)
        self.transition_animation.setEndValue(end)
        self.transition_animation.start()

    def get_reveal_progress(self):
        return self._reveal_progress

    def set_reveal_progress(self, progress):
        progress = max(0.0, min(1.0, float(progress)))
        changed = progress != self._reveal_progress
        self._reveal_progress = progress
        self.update_reveal_geometry()
        if self.fade_effect is not None:
            self.fade_effect.setOpacity(0.35 + 0.65 * progress if progress else 0.0)
        if changed:
            self.reveal_changed.emit(progress)

    revealProgress = Property(float, get_reveal_progress, set_reveal_progress, notify=reveal_changed)

    def update_reveal_geometry(self):
        width, height = self.tool_slot.width(), self.tool_slot.height()
        visible_width = round(width * self._reveal_progress)
        self.tool_viewport.setGeometry(0, 0, visible_width, height)
        offset = -round(12 * (1.0 - self._reveal_progress))
        # 仅改变裁切范围和位置，按钮维持完整布局，避免每帧重排文字。
        self.tools.setGeometry(offset, 0, width, height)

    def finish_transition(self):
        if not self.transitioning:
            return
        self.transition_animation.stop()
        self.tools.setGraphicsEffect(None)
        self.fade_effect = None
        self.transitioning = False
        self.set_reveal_progress(0.0 if self.collapsed else 1.0)
        self.tools.setEnabled(not self.collapsed)
        self.reflow()

    def reflow(self):
        height = max([self.toggle.sizeHint().height(), self.overflow.sizeHint().height(), *(button.sizeHint().height() for button in self.buttons)])
        self.tool_slot.setFixedHeight(height)
        self.update_reveal_geometry()
        self.overflow_menu.clear()
        if self.collapsed and not self.transitioning:
            for button in self.buttons:
                button.hide()
            self.overflow.hide()
            return
        active = [(button, action) for button, action in zip(self.buttons, self.entries) if action.isVisible()]
        sizes = [button.sizeHint().width() for button, _action in active]
        for button, action in zip(self.buttons, self.entries):
            if not action.isVisible():
                button.hide()
        available = max(0, self.tools.width() - 6)
        overflow_needed = sum(sizes) + len(sizes) * self.tools_row.spacing() > available
        if overflow_needed:
            available -= self.overflow.sizeHint().width() + self.tools_row.spacing()
        used = 0
        overflowing = False
        for (button, action), width in zip(active, sizes):
            used += width + self.tools_row.spacing()
            overflowing = overflowing or used > available
            button.setVisible(not overflowing)
            if overflowing:
                self.overflow_menu.addAction(action)
        self.overflow.setVisible(bool(self.overflow_menu.actions()))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Resize:
            if watched is self.tool_slot:
                self.update_reveal_geometry()
            elif watched is self.tools:
                self.schedule_reflow()
        return super().eventFilter(watched, event)

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
        self.setWindowTitle("项目航图设置")
        apply_window_icon(self)
        self.resize(530, 560)
        layout = QVBoxLayout(self)
        note = QLabel("勾选需要的工具，拖动条目调整顺序。隐藏工具后，原快捷键仍可使用。")
        note.setWordWrap(True)
        layout.addWidget(note)
        self.tabs = QTabWidget()
        for key, (title, actions) in catalogs.items():
            view = QListWidget()
            view.setIconSize(QSize(22, 22))
            view.setItemDelegate(NoFocusFrameDelegate(view))
            view.setDragDropMode(QAbstractItemView.InternalMove)
            self.lists[key] = view
            enabled = toolbar_enabled(settings, key, actions)
            self.populate(view, toolbar_order(settings, key, actions), actions, enabled)
            self.tabs.addTab(view, title)
        self.data_panel = self.cloud_panel = None
        if parent is not None and hasattr(parent, "paths") and hasattr(parent, "cloud"):
            from .integration_settings import CloudSettingsPanel, DataSourcesPanel
            self.data_panel = DataSourcesPanel(parent, self)
            self.cloud_panel = CloudSettingsPanel(parent, self)
            self.cloud_panel.password.installEventFilter(self)
            self.tabs.addTab(self.data_panel, "数据目录")
            self.tabs.addTab(self.cloud_panel, "云同步")
            self.resize(710, 610)
        from .help_panel import HelpPanel
        self.help_panel = HelpPanel(catalogs, parent.actions() if parent is not None else (), self)
        self.tabs.addTab(self.help_panel, "使用说明")
        self.resize(860, 660)
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
        controls_widget = QWidget(self)
        controls_widget.setLayout(controls)
        layout.addWidget(controls_widget)
        def update_controls(_index):
            toolbar_tab = self.tabs.currentWidget() in self.lists.values()
            controls_widget.setVisible(toolbar_tab)
            note.setVisible(toolbar_tab)
        self.tabs.currentChanged.connect(update_controls)
        self.tabs.currentChanged.connect(lambda _index: self.help_panel.focus_search() if self.tabs.currentWidget() is self.help_panel else None)
        update_controls(self.tabs.currentIndex())
        footer = QHBoxLayout()
        footer.addStretch()
        cancel = QPushButton("取消")
        save = QPushButton("保存设置")
        save.setObjectName("primaryButton")
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept_settings)
        footer.addWidget(cancel)
        footer.addWidget(save)
        layout.addLayout(footer)

    def accept_settings(self):
        try:
            if self.data_panel:
                self.data_panel.validate()
                self.cloud_panel.validate()
        except (OSError, ValueError) as error:
            self.parent().show_notice("设置暂未保存", str(error))
            return
        self.accept()

    def eventFilter(self, watched, event):
        if self.cloud_panel and watched is self.cloud_panel.password and event.type() == QEvent.KeyPress and event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.cloud_panel.login()
            event.accept()
            return True
        return super().eventFilter(watched, event)

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
        if view not in self.lists.values():
            return
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
