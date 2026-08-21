from __future__ import annotations

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    _exe_dir = Path(sys.executable).resolve().parent
    _adjacent_markdown = _exe_dir / "Markdown"
    _repository_markdown = _exe_dir.parent / "Markdown"
    if _adjacent_markdown.exists():
        APP_DIR = _exe_dir
    elif _exe_dir.name.casefold() == "dist" and _repository_markdown.exists():
        APP_DIR = _exe_dir.parent
    else:
        APP_DIR = _exe_dir
else:
    APP_DIR = Path(__file__).resolve().parent.parent

RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))

MARKDOWN_DIR = APP_DIR / "Markdown"
DATA_DIR = APP_DIR / "Data"
BACKUP_DIR = APP_DIR / "Backups"
MEDIA_DIR = APP_DIR / "Media"
PROJECTS_FILE = DATA_DIR / "projects.json"
_icon_candidates = (
    RESOURCE_DIR / "assets" / "app_icon.ico",
    RESOURCE_DIR / "assets" / "app_icon.svg",
    APP_DIR / "assets" / "app_icon.ico",
    APP_DIR / "assets" / "app_icon.svg",
)
ICON_PATH = next((path for path in _icon_candidates if path.exists()), _icon_candidates[0])
