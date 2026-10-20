from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import QDialog

from ..config import APP_DIR, MEDIA_DIR
from ..dialogs import MediaFoldersDialog
from ..media_paths import resolve_image


class MediaMixin:
    def extra_media_dirs(self):
        raw = self.settings.value("extra_media_dirs", "")
        try:
            values = json.loads(raw) if isinstance(raw, str) and raw else list(raw or [])
        except (TypeError, json.JSONDecodeError):
            values = []
        directories = []
        known = {self.normalized_path(self.paths.media)}
        for value in values:
            path = Path(value).expanduser().resolve(strict=False)
            normalized = self.normalized_path(path)
            if normalized not in known:
                directories.append(path)
                known.add(normalized)
        return directories

    def save_extra_media_dirs(self, directories):
        cleaned = []
        known = {self.normalized_path(self.paths.media)}
        for directory in directories:
            path = Path(directory).expanduser().resolve(strict=False)
            normalized = self.normalized_path(path)
            if normalized not in known:
                cleaned.append(str(path))
                known.add(normalized)
        self.settings.setValue("extra_media_dirs", json.dumps(cleaned, ensure_ascii=False))

    def show_media_folders(self):
        dialog = MediaFoldersDialog(self.paths.media, self.extra_media_dirs(), self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.save_extra_media_dirs(dialog.directories())
        self.update_preview()
        if hasattr(self, "cloud"):
            self.cloud.schedule()
        self.statusBar().showMessage(f"图片缓存配置已保存：{len(dialog.directories())} 个附加目录")

    def media_search_dirs(self, project_path=None):
        project_path = Path(project_path or self.current_path) if project_path or self.current_path else None
        candidates = []
        if project_path:
            candidates.append(project_path.parent / "Media")
            if project_path.parent.name.casefold() == "markdown":
                candidates.append(project_path.parent.parent / "Media")
        candidates.extend([self.paths.media, self.paths.root / "Media", *self.extra_media_dirs()])
        directories = []
        known = set()
        for candidate in candidates:
            path = Path(candidate).resolve(strict=False)
            normalized = self.normalized_path(path)
            if normalized not in known:
                directories.append(path)
                known.add(normalized)
        return directories

    def resolve_media_source(self, source, base_dir=None):
        document = self.current_path or Path(base_dir or self.paths.root) / "__preview__.md"
        return resolve_image(source, document, self.media_search_dirs())
