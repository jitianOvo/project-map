from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QFileSystemWatcher, QSettings, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow

from .config import BACKUP_DIR, DATA_DIR, ICON_PATH, MARKDOWN_DIR, MEDIA_DIR
from .mixins.actions import ActionsMixin
from .mixins.formatting import FormattingMixin
from .mixins.panels import PanelsMixin
from .mixins.preview import PreviewMixin
from .mixins.projects import ProjectsMixin
from .mixins.ui import UiMixin


class MainWindow(UiMixin, ProjectsMixin, PreviewMixin, FormattingMixin, PanelsMixin, ActionsMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        for directory in (MARKDOWN_DIR, DATA_DIR, BACKUP_DIR, MEDIA_DIR):
            directory.mkdir(exist_ok=True)
        self.settings = QSettings(str(DATA_DIR / "settings.ini"), QSettings.IniFormat)
        self.metadata = self.load_metadata()
        self.current_path: Path | None = None
        self.loading = False
        self.dirty = False
        self.save_guard = False
        self.find_dialog = None
        self.layout_timer = QTimer(self)
        self.layout_timer.setSingleShot(True)
        self.layout_timer.timeout.connect(self.save_layout)
        self.setWindowTitle("项目航图")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1480, 900)
        self.build_ui()
        if geometry := self.settings.value("geometry"):
            self.restoreGeometry(geometry)
        self.restore_layout()
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _: self.refresh_files())
        self.watcher.fileChanged.connect(self.external_file_changed)
        self.refresh_files()

