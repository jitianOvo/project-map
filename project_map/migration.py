from __future__ import annotations

import shutil
from pathlib import Path

from .file_io import read_json, write_json
from .locations import path_identity


def backup_data(root: Path, backup: Path):
    for label, base in (("外层原始", root), ("内层原始", root / "dist")):
        for name in ("Markdown", "Media", "Data"):
            source = base / name
            target = backup / label / name
            if source.is_dir() and not source.is_symlink() and not target.exists():
                shutil.copytree(source, target)


def merge_inner_data(root: Path, backup: Path):
    root, backup = root.resolve(), backup.resolve()
    if not backup.is_relative_to(root / "Backups"):
        raise ValueError("迁移备份必须位于本项目 Backups 内")
    if (backup / "migration.json").exists():
        raise ValueError("此迁移已执行，不重复覆盖资料")
    backup_data(root, backup)
    result = {"markdown_copied": 0, "media_copied": 0, "conflicts": [], "backup": str(backup)}
    for name in ("Markdown", "Media"):
        source, target = root / "dist" / name, root / name
        target.mkdir(parents=True, exist_ok=True)
        if not source.is_dir():
            continue
        for path in source.rglob("*"):
            if not path.is_file():
                continue
            destination = target / path.relative_to(source)
            if destination.exists() and destination.read_bytes() != path.read_bytes():
                result["conflicts"].append(str(path.relative_to(root)))
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
            result["markdown_copied" if name == "Markdown" else "media_copied"] += 1
    outer = read_json(root / "Data" / "projects.json")
    inner = read_json(root / "dist" / "Data" / "projects.json")
    metadata = dict(outer)
    for key, value in inner.items():
        value = dict(value)
        source = value.get("source_path")
        if source:
            source_path = Path(source).resolve(strict=False)
            if path_identity(source_path.parent) in {path_identity(root / "Markdown"), path_identity(root / "dist" / "Markdown")}:
                key = source_path.name
                value.pop("source_path", None)
        metadata[key] = value
    write_json(root / "Data" / "projects.json", metadata)
    settings = root / "dist" / "Data" / "settings.ini"
    if settings.exists():
        shutil.copy2(settings, root / "Data" / "settings.ini")
    write_json(root / "Data" / "data-sources.json", {"markdown": "Markdown", "media": "Media"})
    result["markdown_total"] = len(list((root / "Markdown").glob("*.md")))
    result["media_total"] = len([p for p in (root / "Media").rglob("*") if p.is_file()])
    write_json(backup / "migration.json", result)
    return result
