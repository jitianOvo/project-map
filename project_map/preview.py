from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt, Signal, QSize
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QMenu, QScrollArea, QTextBrowser, QVBoxLayout

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
