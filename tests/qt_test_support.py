from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication


APP = QApplication.instance() or QApplication([])

if os.name == "nt" and not QFontDatabase.families():
    # Windows 离屏平台不枚举系统字体，视觉回归需要显式加载实际使用的字体。
    fonts = Path(os.environ.get("SystemRoot", "C:/Windows")) / "Fonts"
    for name in ("segoeui.ttf", "segoeuib.ttf", "seguisym.ttf", "msyh.ttc", "msyhbd.ttc"):
        path = fonts / name
        if path.is_file():
            QFontDatabase.addApplicationFont(str(path))
    APP.setFont(QFont("Microsoft YaHei UI", 9))

APP.setStyle("Fusion")
