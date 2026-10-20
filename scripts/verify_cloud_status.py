from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

import test_workflow as workflow
from PySide6.QtCore import QRect
from PySide6.QtTest import QTest
from project_map.toolbars import ToolbarSettingsDialog


def main():
    fixture = workflow.WindowTests()
    qa = ROOT / ".cache" / "cloud-status-qa"
    qa.mkdir(parents=True, exist_ok=True)
    fixture.setUp()
    try:
        window = fixture.window
        issues = [{"path": str(fixture.path), "kind": "missing_image",
                   "message": "图片未找到：C:/旧的图片目录/演示图.png；请恢复原图，或将图片所在文件夹加入“图片缓存设置”后重试"}]
        with patch.object(window.cloud, "apply_result"):
            window.cloud.finish_job({"kind": "sync", "error": None, "value": {"issues": issues}})
        for theme in ("light", "dark"):
            window.apply_theme(theme)
            window.resize(1180, 760)
            QTest.qWait(80)
            button = window.cloud_label
            assert button.fontMetrics().horizontalAdvance(button.text()) + 16 <= button.width()
            assert window.grab(QRect(0, window.height() - 90, window.width(), 90)).save(str(qa / f"status-{theme}.png"))
            dialog = ToolbarSettingsDialog(window.settings, window.toolbar_catalogs, window)
            try:
                dialog.tabs.setCurrentWidget(dialog.cloud_panel)
                dialog.show()
                QTest.qWait(80)
                assert dialog.cloud_panel.details.isVisible()
                assert "演示图.png" in dialog.cloud_panel.details.toPlainText()
                assert dialog.grab().save(str(qa / f"details-{theme}.png"))
            finally:
                workflow.dispose(dialog)
        print(json.dumps({"status_fits": True, "themes": ["light", "dark"], "full_details": True,
                          "private_files_used": False, "screenshots": str(qa)}, ensure_ascii=False))
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    main()
