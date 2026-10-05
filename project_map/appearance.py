from __future__ import annotations

import ctypes
import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QWidget

from .config import ICON_PATH


WINDOWS_APP_ID = "ProjectMap.Desktop"


def configure_windows_app_id():
    """让 Windows 将源码版和编译版窗口归入项目航图应用。"""
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(WINDOWS_APP_ID)
    except (AttributeError, OSError):
        pass


def load_app_icon():
    return QIcon(str(ICON_PATH)) if ICON_PATH.exists() else QIcon()


def apply_window_icon(window: QWidget):
    app = QApplication.instance()
    icon = app.windowIcon() if app is not None else QIcon()
    if icon.isNull():
        icon = load_app_icon()
    if not icon.isNull():
        window.setWindowIcon(icon)
