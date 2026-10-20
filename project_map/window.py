from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QEvent, QFileSystemWatcher, QSettings, QTimer
from PySide6.QtWidgets import QMainWindow

from .appearance import apply_window_icon
from .config import APP_DIR, BACKUP_DIR, DATA_DIR, MARKDOWN_DIR, MEDIA_DIR
from .locations import AppPaths
from .cloud.controller import CloudController
from .mixins.integration import IntegrationMixin
from .mixins.actions import ActionsMixin
from .mixins.formatting import FormattingMixin
from .mixins.media import MediaMixin
from .mixins.panels import PanelsMixin
from .mixins.preview import PreviewMixin
from .mixins.projects import ProjectsMixin
from .mixins.ui import UiMixin
from .mixins.toolbars import ToolbarsMixin


class MainWindow(UiMixin, ProjectsMixin, PreviewMixin, FormattingMixin, ToolbarsMixin, MediaMixin, PanelsMixin, ActionsMixin, IntegrationMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.paths = AppPaths.load(APP_DIR, MARKDOWN_DIR, MEDIA_DIR, DATA_DIR, BACKUP_DIR)
        self.paths.ensure()
        self.paths.save()
        self.settings = QSettings(str(self.paths.data / "settings.ini"), QSettings.IniFormat)
        self.metadata = self.load_metadata()
        self.current_path: Path | None = None
        self.loading = False
        self.dirty = False
        self.save_guard = False
        self.find_dialog = None
        self.layout_timer = QTimer(self)
        self.layout_timer.setSingleShot(True)
        self.layout_timer.timeout.connect(self.save_layout)
        self.auto_save_timer = QTimer(self)
        self.auto_save_timer.setSingleShot(True)
        self.auto_save_timer.setInterval(750)
        self.auto_save_timer.timeout.connect(self.auto_save_file)
        self.save_guard_timer = QTimer(self)
        self.save_guard_timer.setSingleShot(True)
        self.save_guard_timer.setInterval(1200)
        self.save_guard_timer.timeout.connect(self.clear_save_guard)
        self.setWindowTitle("项目航图")
        apply_window_icon(self)
        self.resize(1480, 900)
        self.build_ui()
        if geometry := self.settings.value("geometry"):
            self.restoreGeometry(geometry)
        self.restore_layout()
        self.watcher = QFileSystemWatcher(self)
        self.watcher.directoryChanged.connect(lambda _: self.refresh_files())
        self.watcher.fileChanged.connect(self.external_file_changed)
        self.watcher.addPath(str(self.paths.markdown))
        self.refresh_files()
        self.editor.media_dir = self.paths.media
        self.cloud = CloudController(self)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and hasattr(self, "cloud"):
            if self.isMinimized():
                self.cloud.editing.end_editing()
            elif self.cloud.editing.managed_id(self.current_path) and self.editor.isReadOnly():
                if self.cloud.editing.pending:
                    self.cloud.editing.resume_after = True
                else:
                    self.cloud.editing.request_open(self.current_path, force=True, quiet=True)
