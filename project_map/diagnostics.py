from __future__ import annotations

import os

from PySide6.QtCore import QTimer

from .config import APP_VERSION
from .file_io import read_json, write_json


def run_self_test(window, cloud=False, auto_login=False):
    finished = False

    def complete(success=True, error=""):
        nonlocal finished
        if finished:
            return
        finished = True
        from .toolbars import ToolbarSettingsDialog
        settings = ToolbarSettingsDialog(window.settings, window.toolbar_catalogs, window)
        settings_tabs = [settings.tabs.tabText(index) for index in range(settings.tabs.count())]
        help_topics = len(settings.help_panel.articles)
        settings.deleteLater()
        write_json(window.paths.data / "self-test.json", {
            "version": APP_VERSION, "ready": success, "icon": not window.windowIcon().isNull(),
            "root": str(window.paths.root), "markdown": str(window.paths.markdown), "media": str(window.paths.media),
            "projects": len(window.all_project_paths()), "settings_tabs": settings_tabs, "help_topics": help_topics,
            "cloud_enabled": window.cloud.config["enabled"], "cloud_status": window.cloud.status, "error": error,
            "auto_login": window.cloud.config["auto_login"], "session_restored": bool(window.cloud.session.get("token")),
        })
        window.close()

    if not cloud and not auto_login:
        QTimer.singleShot(350, window, complete)
        return
    login_file = os.environ.get("PROJECT_MAP_TEST_LOGIN")
    if not os.environ.get("PROJECT_MAP_DATA_ROOT") or (cloud and not login_file):
        complete(False, "云诊断必须指定隔离数据目录与测试账号文件")
        return
    account = read_json(login_file) if login_file else {}
    window.cloud.poll.stop()

    def logged_in(success, message):
        if not success:
            complete(False, message)
        else:
            window.cloud.synchronize(force=True)

    def received(result):
        if auto_login and result["kind"] == "resume" and result["error"]:
            complete(False, str(result["error"]))
            return
        if result["kind"] != "sync":
            return
        if result["error"]:
            complete(False, str(result["error"]))
        else:
            QTimer.singleShot(100, window, lambda: complete(window.cloud.status.startswith("已同步"), "" if window.cloud.status.startswith("已同步") else window.cloud.status))

    window.cloud.login_finished.connect(logged_in)
    window.cloud.job_finished.connect(received)
    QTimer.singleShot(25000, window, lambda: complete(False, "云诊断超时"))
    if cloud:
        window.cloud.login(account["endpoint"], account["username"], account["password"])
