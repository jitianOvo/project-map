from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QEvent, QPropertyAnimation, QTimer, Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QGraphicsOpacityEffect, QPlainTextEdit, QScrollBar, QTextEdit

class PanelsMixin:

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
