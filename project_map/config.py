from __future__ import annotations

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    _exe_dir = Path(sys.executable).resolve().parent
    APP_DIR = _exe_dir.parent if _exe_dir.name.casefold() == "dist" else _exe_dir
else:
    APP_DIR = Path(__file__).resolve().parent.parent

MARKDOWN_DIR = APP_DIR / "Markdown"
DATA_DIR = APP_DIR / "Data"
BACKUP_DIR = APP_DIR / "Backups"
MEDIA_DIR = APP_DIR / "Media"
PROJECTS_FILE = DATA_DIR / "projects.json"
ICON_PATH = APP_DIR / "assets" / "app_icon.svg"
