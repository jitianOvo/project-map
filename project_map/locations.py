from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .file_io import read_json, write_json


def path_identity(path):
    return str(Path(path).resolve(strict=False)).casefold()


@dataclass(frozen=True)
class AppPaths:
    root: Path
    markdown: Path
    media: Path
    data: Path
    backups: Path

    @property
    def library_id(self):
        reference = "relative:" + str(self.markdown.relative_to(self.root)).casefold() if self.markdown.is_relative_to(self.root) else "absolute:" + path_identity(self.markdown)
        return hashlib.sha256(reference.encode("utf-8")).hexdigest()[:20]

    @property
    def projects(self):
        if path_identity(self.markdown) == path_identity(self.root / "Markdown"):
            return self.data / "projects.json"
        return self.data / "libraries" / (self.library_id + ".json")

    @property
    def sources_file(self):
        return self.data / "data-sources.json"

    @classmethod
    def load(cls, root, markdown, media, data, backups):
        value = read_json(Path(data) / "data-sources.json")
        def resolve_source(key, fallback):
            selected = Path(value.get(key, fallback))
            return selected if selected.is_absolute() else Path(root) / selected
        return cls(Path(root), resolve_source("markdown", markdown), resolve_source("media", media), Path(data), Path(backups))

    def ensure(self):
        for path in (self.markdown, self.media, self.data, self.backups):
            path.mkdir(parents=True, exist_ok=True)

    def with_sources(self, markdown, media):
        selected = AppPaths(self.root, Path(markdown).expanduser().resolve(), Path(media).expanduser().resolve(), self.data, self.backups)
        if path_identity(selected.markdown) == path_identity(selected.media):
            raise ValueError("Markdown 与图片缓存请选择两个不同的文件夹")
        selected.ensure()
        return selected

    def save(self):
        def portable(path):
            return str(path.relative_to(self.root)) if path.is_relative_to(self.root) else str(path)
        write_json(self.sources_file, {"markdown": portable(self.markdown), "media": portable(self.media)})
