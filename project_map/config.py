from __future__ import annotations

import sys
import os
from pathlib import Path

APP_VERSION = "4.2.2"

if getattr(sys, "frozen", False):
    _exe_dir = Path(sys.executable).resolve().parent
    if _exe_dir.name.casefold() == "dist":
        APP_DIR = _exe_dir.parent
    else:
        APP_DIR = _exe_dir
else:
    APP_DIR = Path(__file__).resolve().parent.parent

if _data_root := os.environ.get("PROJECT_MAP_DATA_ROOT"):
    APP_DIR = Path(_data_root).expanduser().resolve()

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
