from __future__ import annotations

import copy
import unittest
import uuid
from pathlib import Path

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QImage, QTextCursor
from PySide6.QtTest import QTest

from project_map.cloud.merge import payload
from project_map.file_io import read_json
from project_map.toolbars import ToolbarSettingsDialog
from project_map.cloud.assets import Assets
import test_workflow as workflow
from test_cloud import PNG
from unittest.mock import patch


class IntegratedUiTests(unittest.TestCase):
    setUp = workflow.WindowTests.setUp
    tearDown = workflow.WindowTests.tearDown

    def test_sync_snapshots_follow_loaded_document_not_pending_selection(self):
        new = self.path.parent / "新建空项目.md"
        new.write_text("", encoding="utf-8")
        original = self.window.editor.toPlainText()
        self.window.current_path = new
        snapshots = {Path(item["path"]): item for item in self.window.cloud.snapshots()}
        self.assertEqual(snapshots[new]["document"]["content"], "")
        self.assertFalse(snapshots[new]["active"])
        self.assertEqual(snapshots[self.path]["document"]["content"], original)
        self.assertTrue(snapshots[self.path]["active"])

    def test_save_never_writes_loaded_text_into_pending_project(self):
        new = self.path.parent / "另一个空项目.md"
        new.write_text("", encoding="utf-8")
        self.window.editor.insertPlainText("当前项目的未保存文字")
        expected = self.window.editor.toPlainText()
        self.window.current_path = new
        self.assertTrue(self.window.flush_auto_save())
        self.assertEqual(new.read_text(encoding="utf-8"), "")
        self.assertEqual(self.path.read_text(encoding="utf-8"), expected)

    def test_new_project_during_pending_open_keeps_an_empty_own_snapshot(self):
        from project_map.dialogs import NewProjectDialog
        from PySide6.QtWidgets import QDialog

        access = self.window.cloud.editing
        access.pending = True
        access.active = {"id": "test-pending", "deadline": 0}
        dialog = NewProjectDialog(self.window)
        dialog.value.setText("Solar-Kernel")
        with patch("project_map.mixins.actions.NewProjectDialog", return_value=dialog), patch.object(dialog, "exec", return_value=QDialog.Accepted):
            self.window.new_file()
        new = self.path.parent / "Solar-Kernel.md"
        snapshots = {Path(item["path"]): item for item in self.window.cloud.snapshots()}
        self.assertEqual(new.read_text(encoding="utf-8"), "")
        self.assertEqual(snapshots[new]["document"]["content"], "")
        self.assertEqual(self.window.current_path, self.window.editor.current_document_path)
        access.pending, access.active = False, None

    def test_delayed_external_reload_cannot_switch_back_to_previous_project(self):
        other = self.path.parent / "另一个项目.md"
        other.write_text("另一个项目的正文", encoding="utf-8")
        self.window.external_file_changed(str(self.path))
        self.window.load_file(other)
        QTest.qWait(220)
        self.assertEqual(self.window.current_path, other)
        self.assertEqual(self.window.editor.current_document_path, other)
        self.assertEqual(self.window.editor.toPlainText(), "另一个项目的正文")

    def test_settings_add_sources_and_cloud_without_another_settings_button(self):
        dialog = ToolbarSettingsDialog(self.window.settings, self.window.toolbar_catalogs, self.window)
        self.assertEqual([dialog.tabs.tabText(i) for i in range(dialog.tabs.count())], ["快速工具", "格式工具", "数据目录", "云同步", "使用说明"])
        self.assertEqual(dialog.data_panel.markdown.text(), str(self.window.paths.markdown))
        self.assertFalse(self.window.cloud.config["enabled"])
        self.assertEqual(dialog.cloud_panel.endpoint.text(), "https://jitian666.me/project-map/")
        self.assertEqual(set(dialog.lists), {"quick", "format"})
        workflow.dispose(dialog)

    def test_cloud_warning_is_short_clickable_and_shows_all_details(self):
        cloud = self.window.cloud
        issues = [{"path": str(self.path), "message": "图片未找到：C:/旧目录/丢失.png", "kind": "missing_image"},
                  {"path": str(self.path.parent / "另一个.md"), "message": "图片超过 12 MB"}]
        with patch.object(cloud, "apply_result"):
            cloud.finish_job({"kind": "sync", "error": None, "value": {"issues": issues, "errors": []}})
        self.assertEqual(self.window.cloud_label.text(), "云：2 个项目待处理 · 查看详情")
        self.assertNotIn("C:/", self.window.cloud_label.text())
        self.assertIn("丢失.png", self.window.cloud_label.toolTip())
        with patch.object(self.window, "show_toolbar_settings") as show:
            QTest.mouseClick(self.window.cloud_label, Qt.LeftButton)
            show.assert_called_once_with("云同步")
        dialog = ToolbarSettingsDialog(self.window.settings, self.window.toolbar_catalogs, self.window)
        try:
            dialog.tabs.setCurrentWidget(dialog.cloud_panel)
            dialog.show()
            workflow.APP.processEvents()
            details = dialog.cloud_panel.details.toPlainText()
            self.assertIn(str(self.path), details)
            self.assertIn("丢失.png", details)
            self.assertIn("另一个.md", details)
            self.assertTrue(dialog.cloud_panel.issue_box.isVisible())
            self.assertTrue(dialog.cloud_panel.details.isReadOnly())
            with patch.object(cloud, "apply_result"):
                cloud.finish_job({"kind": "sync", "error": None, "value": {"issues": [], "errors": []}})
            self.assertEqual(dialog.cloud_panel.details.toPlainText(), "")
            self.assertFalse(dialog.cloud_panel.issue_box.isVisible())
            self.assertIn("已同步", self.window.cloud_label.text())
        finally:
            workflow.dispose(dialog)

    def test_cloud_long_errors_are_not_cut_off_and_tooltip_escapes_html(self):
        message = "读取项目失败：<test> & " + "非常长的文件路径/" * 20
        self.window.cloud.set_status(message)
        self.assertEqual(self.window.cloud_label.text(), "云：同步异常 · 查看详情")
        self.assertIn("&lt;test&gt; &amp;", self.window.cloud_label.toolTip())
        dialog = ToolbarSettingsDialog(self.window.settings, self.window.toolbar_catalogs, self.window)
        self.assertEqual(dialog.cloud_panel.status.text(), message)
        workflow.dispose(dialog)

    def test_preview_and_cloud_resolve_relocated_absolute_image_consistently(self):
        image = self.window.paths.media / "原图.png"
        image.write_bytes(PNG)
        old = self.window.paths.root / "旧的Typora目录" / image.name
        preview = self.window.resolve_media_source(str(old), self.path.parent)
        cloud = Assets(self.window.paths.media).resolve(str(old), self.path)
        self.assertEqual(preview, cloud)
        self.assertEqual(preview, image.resolve())

    def test_saved_warning_survives_controller_restart(self):
        from project_map.cloud.controller import CloudController
        from project_map.file_io import write_json

        cloud = self.window.cloud
        state = cloud.engine.load()
        state["issues"] = [{"path": str(self.path), "message": "缺失图片，等待恢复"}]
        write_json(cloud.engine.state_path, state)
        cloud.shutdown()
        replacement = CloudController(self.window)
        try:
            self.assertEqual(replacement.issues, state["issues"])
        finally:
            replacement.shutdown()
            replacement.deleteLater()

    def test_cloud_password_enter_logs_in_without_accepting_settings(self):
        dialog = ToolbarSettingsDialog(self.window.settings, self.window.toolbar_catalogs, self.window)
        dialog.tabs.setCurrentWidget(dialog.cloud_panel)
        dialog.show()
        dialog.cloud_panel.password.setFocus()
        dialog.cloud_panel.password.setText("测试，不是真实密码")
        with patch.object(self.window.cloud, "login") as login:
            QTest.keyClick(dialog.cloud_panel.password, Qt.Key_Return)
        self.assertEqual(login.call_count, 1)
        self.assertTrue(dialog.isVisible())
        workflow.dispose(dialog)

    def test_source_switch_new_file_image_and_return_restore_original_library(self):
        original = self.window.paths
        self.window.project_meta(self.path, create=True)["group"] = "原有分组"
        self.window.save_metadata()
        markdown = original.root / "其他大纲"
        media = original.root / "其他图片"
        markdown.mkdir()
        path = markdown / "另一篇.MD"
        path.write_text("# 另一篇", encoding="utf-8")
        self.window.change_data_sources(markdown, media)
        self.assertEqual(self.window.current_path, path)
        self.assertEqual(self.window.editor.toPlainText(), "# 另一篇")
        image = QImage(20, 30, QImage.Format_ARGB32)
        image.fill(QColor("#123456"))
        self.window.editor.insert_pasted_image(image)
        self.assertEqual(len(list(media.glob("*.png"))), 1)
        self.assertTrue(self.window.flush_auto_save())
        rendered = self.window.preview.toHtml()
        self.assertIn("其他图片", rendered)
        self.assertEqual(read_json(original.sources_file)["markdown"], str(markdown.relative_to(original.root)))
        self.window.change_data_sources(original.markdown, original.media)
        self.assertEqual(self.window.project_meta(self.path)["group"], "原有分组")
        self.assertIn(self.path, self.window.all_project_paths())
        self.assertNotIn(path, self.window.all_project_paths())

    def test_source_switch_resets_filter_so_new_library_is_not_hidden(self):
        group = self.window.register_project_group("旧库的空分组")
        self.window.activate_project_filter(group)
        self.assertEqual(self.window.file_list.count(), 0)
        markdown = self.window.paths.root / "新库"
        markdown.mkdir()
        (markdown / "可见项目.md").write_text("# 新资料", encoding="utf-8")
        self.window.change_data_sources(markdown, self.window.paths.media)
        self.assertEqual(self.window.settings.value("project_filter"), "全部项目")
        self.assertEqual(self.window.file_list.count(), 1)
        self.assertIn("新资料", self.window.editor.toPlainText())

    def test_cloud_apply_keeps_edits_made_while_request_in_flight(self):
        window = self.window
        window.editor.setPlainText("第一行\n第二行\n第三行\n")
        window.flush_auto_save()
        expected = window.cloud.snapshots()[0]["document"]
        remote = {**expected, "content": "手机第一行\n第二行\n第三行\n"}
        window.editor.setPlainText("第一行\n第二行\n电脑第三行\n")
        identifier = str(uuid.uuid4())
        result = {"applications": {identifier: {"path": str(self.path), "expected": expected, "remote": remote}}, "bindings": {identifier: str(self.path)}}
        window.cloud.apply_result(result)
        QTest.qWait(40)
        self.assertEqual(window.editor.toPlainText(), "手机第一行\n第二行\n电脑第三行\n")
        self.assertEqual(self.path.read_text(encoding="utf-8"), window.editor.toPlainText())
        self.assertTrue(list((window.paths.backups / "Cloud").glob("*.md.bak")))

    def test_cloud_overlap_keeps_local_and_remote_contents_in_separate_files(self):
        window = self.window
        window.editor.setPlainText("原文\n")
        window.flush_auto_save()
        expected = window.cloud.snapshots()[0]["document"]
        remote = {**expected, "content": "手机编辑\n"}
        window.editor.setPlainText("刚刚在电脑编辑\n")
        identifier = str(uuid.uuid4())
        window.cloud.apply_result({"applications": {identifier: {"path": str(self.path), "expected": expected, "remote": remote}}, "bindings": {identifier: str(self.path)}})
        QTest.qWait(40)
        contents = [path.read_text(encoding="utf-8") for path in window.paths.markdown.glob("*.md")]
        self.assertIn("手机编辑\n", contents)
        self.assertIn("刚刚在电脑编辑\n", contents)
        self.assertNotEqual(window.current_path, self.path)

    def test_cloud_remote_delete_is_backed_up_locally(self):
        window = self.window
        expected = window.cloud.snapshots()[0]["document"]
        identifier = str(uuid.uuid4())
        window.cloud.apply_result({"applications": {identifier: {"path": str(self.path), "expected": expected, "remote": {**expected, "deleted": True}}}, "bindings": {}})
        self.assertFalse(self.path.exists())
        self.assertTrue(list((window.paths.backups / "Cloud").glob("*.md.bak")))
        self.assertIsNone(window.current_path)

    def test_incoming_refresh_does_not_reset_current_scroll_or_cursor(self):
        window = self.window
        text = "\n\n".join(f"段落 {i} 普通文字" for i in range(150))
        window.editor.setPlainText(text)
        window.flush_auto_save()
        QTest.qWait(40)
        cursor = QTextCursor(window.editor.document().findBlockByNumber(130))
        window.editor.setTextCursor(cursor)
        window.editor.verticalScrollBar().setValue(200)
        window.preview.verticalScrollBar().setValue(400)
        position = window.editor.textCursor().position()
        expected = window.cloud.snapshots()[0]["document"]
        remote = {**expected, "content": text.replace("段落 140", "段落 140 手机补充")}
        identifier = str(uuid.uuid4())
        window.cloud.apply_result({"applications": {identifier: {"path": str(self.path), "expected": expected, "remote": remote}}, "bindings": {identifier: str(self.path)}})
        QTest.qWait(80)
        self.assertEqual(window.editor.textCursor().position(), position)
        self.assertEqual(window.editor.verticalScrollBar().value(), 200)
        self.assertEqual(window.preview.verticalScrollBar().value(), 400)

    def test_refresh_and_unchanged_cloud_ack_preserve_undo(self):
        window = self.window
        cursor = window.editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        cursor.insertText("新增文字")
        window.editor.setTextCursor(cursor)
        window.flush_auto_save()
        self.assertTrue(window.editor.document().isUndoAvailable())
        expected = window.cloud.snapshots()[0]["document"]
        identifier = str(uuid.uuid4())
        window.cloud.apply_result({"applications": {identifier: {"path": str(self.path), "expected": expected, "remote": copy.deepcopy(expected)}}, "bindings": {identifier: str(self.path)}})
        QTest.qWait(30)
        self.assertTrue(window.editor.document().isUndoAvailable())
        window.editor.undo()
        self.assertNotIn("新增文字", window.editor.toPlainText())

    def test_identical_documents_still_switch_editor_identity_and_last_file(self):
        another = self.path.parent / "正文相同的另一个项目.md"
        another.write_bytes(self.path.read_bytes())
        self.window.current_path = another
        self.window.refresh_files()
        self.assertEqual(self.window.editor.current_document_path, another)
        self.assertEqual(self.window.settings.value("last_file"), str(another))
        self.assertEqual(self.window.file_title.toolTip(), str(another.resolve()))

    def test_import_flushes_current_document_before_switch(self):
        external = self.window.paths.root / "待导入.md"
        external.write_text("外部资料", encoding="utf-8")
        self.window.editor.insertPlainText("还没等到自动保存")
        with patch("project_map.mixins.actions.QFileDialog.getOpenFileName", return_value=(str(external), "Markdown (*.md)")):
            self.window.import_file()
        self.assertIn("还没等到自动保存", self.path.read_text(encoding="utf-8"))
        self.assertEqual(self.window.current_path, external)
