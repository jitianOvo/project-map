from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .appearance import configure_windows_app_id, load_app_icon
from .single_instance import SingleInstance
from .window import MainWindow


def main():
    configure_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("项目航图")
    app.setApplicationDisplayName("项目航图")
    app.setStyle("Fusion")
    icon = load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    instance = SingleInstance(parent=app)
    if not instance.is_primary:
        return 0
    window = MainWindow()

    def activate_window():
        if window.windowState() & Qt.WindowMinimized:
            window.setWindowState(window.windowState() & ~Qt.WindowMinimized)
        window.show()
        window.raise_()
        window.activateWindow()
        QApplication.alert(window, 0)

    instance.activation_requested.connect(activate_window)
    theme = window.settings.value("theme", "dark")
    window.apply_theme(theme)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
