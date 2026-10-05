from __future__ import annotations

import html
import json
from pathlib import Path
from urllib.parse import unquote

from PySide6.QtCore import QUrl
from PySide6.QtWidgets import QDialog

from ..config import APP_DIR, MEDIA_DIR
from ..dialogs import MediaFoldersDialog


class MediaMixin:
    def extra_media_dirs(self):
        raw = self.settings.value("extra_media_dirs", "")
        try:
            values = json.loads(raw) if isinstance(raw, str) and raw else list(raw or [])
        except (TypeError, json.JSONDecodeError):
            values = []
        directories = []
        known = {self.normalized_path(MEDIA_DIR)}
        for value in values:
            path = Path(value).expanduser().resolve(strict=False)
            normalized = self.normalized_path(path)
            if normalized not in known:
                directories.append(path)
                known.add(normalized)
        return directories

    def save_extra_media_dirs(self, directories):
        cleaned = []
        known = {self.normalized_path(MEDIA_DIR)}
        for directory in directories:
            path = Path(directory).expanduser().resolve(strict=False)
            normalized = self.normalized_path(path)
            if normalized not in known:
                cleaned.append(str(path))
                known.add(normalized)
        self.settings.setValue("extra_media_dirs", json.dumps(cleaned, ensure_ascii=False))

    def show_media_folders(self):
        dialog = MediaFoldersDialog(MEDIA_DIR, self.extra_media_dirs(), self)
        if dialog.exec() != QDialog.Accepted:
            return
        self.save_extra_media_dirs(dialog.directories())
        self.update_preview()
        self.statusBar().showMessage(f"图片缓存配置已保存：{len(dialog.directories())} 个附加目录")

    def media_search_dirs(self, project_path=None):
        project_path = Path(project_path or self.current_path) if project_path or self.current_path else None
        candidates = []
        if project_path:
            candidates.append(project_path.parent / "Media")
            if project_path.parent.name.casefold() == "markdown":
                candidates.append(project_path.parent.parent / "Media")
        candidates.extend([MEDIA_DIR, APP_DIR / "Media", *self.extra_media_dirs()])
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
        source = html.unescape(str(source)).strip()
        if source.startswith("file:"):
            file_path = Path(QUrl(source).toLocalFile())
            return file_path if file_path.is_file() else None
        source_path = Path(unquote(source).replace("/", "\\"))
        if source_path.is_absolute():
            return source_path if source_path.is_file() else None

        candidates = []
        if base_dir:
            candidates.append(Path(base_dir) / source_path)
        parts = source_path.parts
        if parts and parts[0].casefold() == "media":
            remainder = parts[1:]
            candidates.extend(directory.joinpath(*remainder) for directory in self.media_search_dirs())
        else:
            candidates.extend(directory / source_path for directory in self.media_search_dirs())
        known = set()
        for candidate in candidates:
            normalized = self.normalized_path(candidate)
            if normalized in known:
                continue
            known.add(normalized)
            if candidate.is_file():
                return candidate
        return None
