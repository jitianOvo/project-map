from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .config import ICON_PATH
from .window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("项目航图")
    app.setStyle("Fusion")
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    window = MainWindow()
    theme = window.settings.value("theme", "dark")
    window.apply_theme(theme)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

