from __future__ import annotations

from PySide6.QtCore import QEasingCurve, QElapsedTimer, QPropertyAnimation, QTimer, Qt, Signal
from PySide6.QtWidgets import QAbstractItemView, QGraphicsOpacityEffect, QListWidget


class ProjectListWidget(QListWidget):
    """支持长按拖拽排序和项目级快捷键的列表。"""

    order_changed = Signal()
    delete_requested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._press_timer = QElapsedTimer()
        self._drop_animation: QPropertyAnimation | None = None
        self.setFocusPolicy(Qt.StrongFocus)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDragDropOverwriteMode(False)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setAutoScroll(True)
        self.setAutoScrollMargin(36)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press_timer.start()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and self._press_timer.isValid() and self._press_timer.elapsed() < 160:
            return
        super().mouseMoveEvent(event)

    def dropEvent(self, event):
        before = [self.item(index).data(Qt.UserRole) for index in range(self.count())]
        super().dropEvent(event)
        after = [self.item(index).data(Qt.UserRole) for index in range(self.count())]
        if before != after:
            self._animate_drop_settle()
            QTimer.singleShot(0, self.order_changed.emit)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Delete and event.modifiers() == Qt.NoModifier and self.currentItem():
            self.delete_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _animate_drop_settle(self):
        effect = QGraphicsOpacityEffect(self.viewport())
        self.viewport().setGraphicsEffect(effect)
        animation = QPropertyAnimation(effect, b"opacity", self)
        animation.setDuration(170)
        animation.setStartValue(0.78)
        animation.setEndValue(1.0)
        animation.setEasingCurve(QEasingCurve.OutCubic)
        animation.finished.connect(lambda: self.viewport().setGraphicsEffect(None))
        self._drop_animation = animation
        animation.start()
