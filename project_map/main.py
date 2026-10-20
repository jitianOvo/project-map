from __future__ import annotations

import sys
import hashlib

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from .appearance import configure_windows_app_id, load_app_icon
from .config import APP_DIR, APP_VERSION
from .single_instance import INSTANCE_NAME, SingleInstance
from .window import MainWindow


def main():
    configure_windows_app_id()
    app = QApplication(sys.argv)
    app.setApplicationName("项目航图")
    app.setApplicationDisplayName("项目航图")
    app.setApplicationVersion(APP_VERSION)
    app.setStyle("Fusion")
    icon = load_app_icon()
    if not icon.isNull():
        app.setWindowIcon(icon)
    name = INSTANCE_NAME
    testing = any(value in sys.argv for value in ("--self-test", "--self-test-cloud", "--self-test-auto-login"))
    if testing:
        name += ".Test." + hashlib.sha256(str(APP_DIR).encode()).hexdigest()[:16]
    instance = SingleInstance(name=name, parent=app)
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
    if testing:
        from .diagnostics import run_self_test
        run_self_test(window, cloud="--self-test-cloud" in sys.argv, auto_login="--self-test-auto-login" in sys.argv)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
