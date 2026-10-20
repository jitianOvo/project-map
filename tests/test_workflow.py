from __future__ import annotations

import os
import tempfile
import unittest
import sys
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QSettings, Qt
from PySide6.QtGui import QAction, QContextMenuEvent, QTextCursor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

from project_map.dialogs import NewProjectDialog
from project_map.editor import MarkdownEditor
from project_map.toolbars import AdaptiveToolBar, ToolbarSettingsDialog, toolbar_enabled
from project_map.versioning import insert_version, remove_versions
from project_map.window import MainWindow
from project_map.menus import RoundedMenu


from qt_test_support import APP


def dispose(widget):
    if hasattr(widget, "cloud"):
        widget.cloud.editing.closing_ready = True
        widget.cloud.shutdown()
    widget.close()
    widget.deleteLater()
    APP.sendPostedEvents(None, QEvent.DeferredDelete)
    APP.processEvents()


class VersionTests(unittest.TestCase):
    def test_insert_round_and_renumber(self):
        text, line = insert_version("# V1\n需求\n\n# V2\n后续\n# V3\n末尾", 2)
        self.assertEqual(text, "# V1\n需求\n# V2\n\n\n# V3\n后续\n# V4\n末尾")
        self.assertEqual(line, 3)

    def test_decimal_and_scope(self):
        text, _line = insert_version("# V3.5\n## v3.1\n一\n\n## v3.2\n二\n# V4.0\n## v3.2\n别组", 3)
        self.assertIn("## v3.3\n二", text)
        self.assertTrue(text.endswith("# V4.0\n## v3.2\n别组"))

    def test_child_start(self):
        text, _line = insert_version("# V3.5\n", 1, child=True)
        self.assertIn("## v3.1", text)

    def test_code_is_ignored(self):
        text, _line = insert_version("```md\n# V99\n```\n", 3)
        self.assertIn("# V1\n", text)
        self.assertIn("# V99", text)

    def test_remove_preserves_body(self):
        text, changed = remove_versions("# V1\n一\n# V2 第二轮\n保留\n# V3\n三", 2, 2)
        self.assertTrue(changed)
        self.assertEqual(text, "# V1\n一\n第二轮\n保留\n# V2\n三")

    def test_fenced_parent_heading_does_not_break_decimal_series(self):
        text, _line = insert_version("# V3\n## v3.1\n\n```md\n# 示例\n```\n## v3.2\n正文", 2)
        self.assertIn("## v3.3\n正文", text)
        self.assertIn("# 示例", text)

    def test_renumber_round_keeps_child_prefix(self):
        text, _line = insert_version("# V1\n\n# V2\n## v2.1\n内容\n# V3\n## v3.1", 1)
        self.assertIn("# V3\n## v3.1\n内容", text)
        self.assertTrue(text.endswith("# V4\n## v4.1"))


class EditorTests(unittest.TestCase):
    def setUp(self):
        self.editor = MarkdownEditor()
        self.editor.show()

    def tearDown(self):
        dispose(self.editor)

    def place(self, line, at_end=True):
        cursor = QTextCursor(self.editor.document().findBlockByNumber(line))
        if at_end:
            cursor.movePosition(QTextCursor.EndOfBlock)
        self.editor.setTextCursor(cursor)

    def test_shift_enter_renumbers_and_single_undo(self):
        original = "1. 第一项\n2. 第二😀\n3. 第三项\n4. 第四项\n\n9. 别组"
        self.editor.setPlainText(original)
        self.place(1)
        QTest.keyClick(self.editor, Qt.Key_Return, Qt.ShiftModifier)
        self.assertEqual(self.editor.toPlainText(), "1. 第一项\n2. 第二😀\n3. \n4. 第三项\n5. 第四项\n\n9. 别组")
        self.editor.undo()
        self.assertEqual(self.editor.toPlainText(), original)

    def test_nonstandard_number_not_rewritten(self):
        self.editor.setPlainText("1.甲\n2.乙\n3.丙")
        self.place(1)
        QTest.keyClick(self.editor, Qt.Key_Return, Qt.ShiftModifier)
        self.assertTrue(self.editor.toPlainText().endswith("3.丙"))
        self.assertNotIn("4.丙", self.editor.toPlainText())

    def test_priority_keeps_number_and_switches(self):
        self.editor.setPlainText("2. 需求😀")
        self.place(0)
        self.editor.set_priority("urgent")
        self.assertTrue(self.editor.toPlainText().startswith('2. <span data-priority="urgent"'))
        self.editor.set_priority("high")
        self.assertEqual(self.editor.toPlainText().count("<span"), 1)
        self.editor.set_priority(None)
        self.assertEqual(self.editor.toPlainText(), "2. 需求😀")

    def test_version_insert_undo(self):
        original = "# V1\n中文😀\n\n# V2\n后续"
        self.editor.setPlainText(original)
        self.place(2)
        self.editor.add_version()
        self.assertIn("# V3\n后续", self.editor.toPlainText())
        self.editor.undo()
        self.assertEqual(self.editor.toPlainText(), original)

    def test_priority_multiline_preserves_markdown_prefix(self):
        original = "1. 一😀\n2. 二\n- [ ] 三"
        self.editor.setPlainText(original)
        self.editor.selectAll()
        self.editor.set_priority("normal")
        text = self.editor.toPlainText()
        self.assertEqual(text.count('data-priority="normal"'), 3)
        self.assertIn("\n2. <span", text)
        self.assertIn("\n- [ ] <span", text)
        self.editor.set_priority(None)
        self.assertEqual(self.editor.toPlainText(), original)

    def test_tab_selection_retains_emoji(self):
        original = "一😀\n二😀"
        self.editor.setPlainText(original)
        self.editor.selectAll()
        QTest.keyClick(self.editor, Qt.Key_Tab)
        self.assertEqual(self.editor.textCursor().selectedText(), "\t一😀\u2029\t二😀")
        QTest.keyClick(self.editor, Qt.Key_Backtab)
        self.assertEqual(self.editor.toPlainText(), original)

    def test_normal_enter_after_emoji_continues(self):
        self.editor.setPlainText("2. 二😀")
        self.place(0)
        QTest.keyClick(self.editor, Qt.Key_Return)
        self.assertEqual(self.editor.toPlainText(), "2. 二😀\n3. ")

    def test_shift_enter_ignores_fenced_code(self):
        self.editor.setPlainText("```text\n1. 一\n2. 二\n```")
        self.place(1)
        self.assertFalse(self.editor.workflow.insert_numbered_item())

    def test_context_menu_contains_workflow_after_paste(self):
        captured = []
        with patch.object(RoundedMenu, "exec", lambda menu, *_: captured.extend(action.text() for action in menu.actions())):
            position = self.editor.cursorRect().center()
            event = QContextMenuEvent(QContextMenuEvent.Mouse, position, self.editor.mapToGlobal(position))
            self.editor.contextMenuEvent(event)
        paste = captured.index("粘贴")
        self.assertTrue(captured[paste + 1].startswith("增加 Vn"))
        self.assertIn("优先级", captured)


class ToolbarTests(unittest.TestCase):
    def test_overflow_executes_real_action(self):
        bar = AdaptiveToolBar("格式", icons_only=True)
        triggered = []
        actions = []
        for index in range(20):
            action = QAction(f"工具{index}", bar)
            action.triggered.connect(lambda _checked=False, value=index: triggered.append(value))
            actions.append(action)
        bar.resize(260, 40)
        bar.set_entries(actions)
        bar.show()
        APP.processEvents()
        self.assertTrue(bar.overflow.isVisible())
        self.assertTrue(bar.overflow_menu.actions())
        last = bar.overflow_menu.actions()[-1]
        self.assertIs(last, actions[-1])
        last.trigger()
        self.assertEqual(triggered, [19])
        bar.set_collapsed(True)
        QTest.qWait(230)
        self.assertTrue(all(button.isHidden() for button in bar.buttons))
        bar.set_collapsed(False)
        self.assertTrue(bar.overflow_menu.actions())
        dispose(bar)

    def test_sort_hide_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.IniFormat)
            actions = {name: QAction(name, APP) for name in ("A", "B", "C")}
            dialog = ToolbarSettingsDialog(settings, {"quick": ("快速工具", actions)})
            view = dialog.lists["quick"]
            view.setCurrentRow(2)
            dialog.move_selected(-1)
            view.item(0).setCheckState(Qt.Unchecked)
            dialog.save_configuration()
            restored = QSettings(str(Path(directory) / "settings.ini"), QSettings.IniFormat)
            self.assertEqual(toolbar_enabled(restored, "quick", actions), ["C", "B"])
            dispose(dialog)
            for action in actions.values():
                action.deleteLater()
            APP.sendPostedEvents(None, QEvent.DeferredDelete)

    def test_new_dialog_enter_accepts_optional_path(self):
        dialog = NewProjectDialog()
        dialog.show()
        dialog.value.setText("测试项目")
        QTest.keyClick(dialog.value, Qt.Key_Return)
        self.assertEqual(dialog.result(), QDialog.Accepted)
        self.assertEqual(dialog.project_path.text(), "")
        dispose(dialog)

    def test_settings_focus_frame_removed_without_losing_keyboard(self):
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QImage, QPainter
        from PySide6.QtWidgets import QStyle, QStyleOptionViewItem
        from project_map.project_list import NoFocusFrameDelegate

        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.IniFormat)
            dialog = ToolbarSettingsDialog(settings, {"format": ("格式工具", {name: QAction(name, APP) for name in ("撤销", "重做")})})
            view = dialog.lists["format"]
            self.assertIsInstance(view.itemDelegate(), NoFocusFrameDelegate)
            dialog.show()
            view.setCurrentRow(0)
            view.setFocus()
            APP.processEvents()
            QTest.keyClick(view, Qt.Key_Down)
            self.assertEqual(view.currentRow(), 1)
            QTest.keyClick(view, Qt.Key_Space)
            self.assertEqual(view.item(1).checkState(), Qt.Unchecked)

            def render(focused):
                image = QImage(260, 48, QImage.Format_ARGB32_Premultiplied)
                image.fill(Qt.transparent)
                option = QStyleOptionViewItem()
                option.initFrom(view)
                option.rect = QRect(0, 0, 260, 48)
                option.state |= QStyle.State_Selected | QStyle.State_Active
                option.state &= ~QStyle.State_HasFocus
                if focused:
                    option.state |= QStyle.State_HasFocus
                painter = QPainter(image)
                view.itemDelegate().paint(painter, option, view.model().index(1, 0))
                painter.end()
                return image

            self.assertEqual(render(True), render(False))
            dispose(dialog)

    def test_collapse_animation_has_intermediate_frames(self):
        from PySide6.QtTest import QSignalSpy

        bar = AdaptiveToolBar("格式工具", icons_only=True)
        bar.resize(600, 44)
        bar.set_entries([QAction(f"工具{index}", bar) for index in range(10)])
        bar.show()
        APP.processEvents()
        original_height = bar.height()
        original_content_width = bar.tools.width()
        self.assertGreater(bar.tools.height(), 0)
        bar.set_collapsed(True)
        self.assertTrue(bar.transitioning)
        self.assertTrue(any(button.isVisible() for button in bar.buttons))
        frames = QSignalSpy(bar.fade_effect.opacityChanged)
        QTest.qWait(65)
        self.assertGreater(bar.fade_effect.opacity(), 0)
        self.assertLess(bar.fade_effect.opacity(), 1)
        self.assertGreater(bar.tool_viewport.width(), 0)
        self.assertLess(bar.tool_viewport.width(), original_content_width)
        self.assertEqual(bar.tools.width(), original_content_width)
        self.assertLess(bar.tools.x(), 0)
        self.assertLessEqual(bar.transition_animation.duration(), 150)
        QTest.qWait(180)
        self.assertGreaterEqual(frames.count(), 5)
        self.assertFalse(bar.transitioning)
        self.assertIsNone(bar.tools.graphicsEffect())
        self.assertTrue(all(button.isHidden() for button in bar.buttons))
        self.assertEqual(bar.height(), original_height)
        bar.set_collapsed(False)
        self.assertTrue(bar.transitioning)
        QTest.qWait(230)
        self.assertTrue(any(button.isVisible() for button in bar.buttons))
        self.assertIsNone(bar.tools.graphicsEffect())
        self.assertEqual(bar.tool_viewport.width(), bar.tools.width())
        self.assertEqual(bar.tools.x(), 0)
        self.assertEqual(bar.height(), original_height)
        dispose(bar)

    def test_collapse_animation_reverses_and_survives_resize(self):
        bar = AdaptiveToolBar("格式工具", icons_only=True)
        bar.resize(650, 44)
        bar.set_entries([QAction(f"工具{index}", bar) for index in range(20)])
        bar.show()
        APP.processEvents()
        bar.set_collapsed(True)
        QTest.qWait(55)
        previous_opacity = bar.fade_effect.opacity()
        previous_reveal = bar.get_reveal_progress()
        bar.set_collapsed(False)
        self.assertAlmostEqual(bar.fade_effect.opacity(), previous_opacity)
        self.assertAlmostEqual(bar.get_reveal_progress(), previous_reveal)
        bar.resize(300, 44)
        QTest.qWait(230)
        self.assertFalse(bar.collapsed)
        self.assertFalse(bar.transitioning)
        self.assertTrue(bar.overflow_menu.actions())
        self.assertIsNone(bar.tools.graphicsEffect())
        bar.set_collapsed(True, notify=False)
        self.assertFalse(bar.transitioning)
        self.assertTrue(all(button.isHidden() for button in bar.buttons))
        dispose(bar)

    def test_priority_rename_preserves_saved_order_and_hidden_tools(self):
        import json

        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory) / "settings.ini"), QSettings.IniFormat)
            settings.setValue("toolbar/format/order", json.dumps(["普通（绿色）", "最紧急（红色）", "加粗", "优先（蓝色）"]))
            settings.setValue("toolbar/format/hidden", json.dumps(["最紧急（红色）"]))
            self.assertEqual(toolbar_enabled(settings, "format", {name: None for name in ("加粗", "紧急", "优先", "普通")}), ["普通", "加粗", "优先"])


class WindowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        directories = {"APP_DIR": root, "MARKDOWN_DIR": root / "Markdown", "DATA_DIR": root / "Data", "BACKUP_DIR": root / "Backups", "MEDIA_DIR": root / "Media"}
        directories["PROJECTS_FILE"] = directories["DATA_DIR"] / "projects.json"
        for name in ("MARKDOWN_DIR", "DATA_DIR", "BACKUP_DIR", "MEDIA_DIR"):
            directories[name].mkdir()
        self.path = directories["MARKDOWN_DIR"] / "测试.md"
        self.path.write_text("# V1\n测试😀\n\n# V2\n后续", encoding="utf-8")
        self.patches = ExitStack()
        for name, module in list(sys.modules.items()):
            if name.startswith("project_map") and module:
                for attr, value in directories.items():
                    if hasattr(module, attr):
                        self.patches.enter_context(patch.object(module, attr, value))
        self.window = MainWindow()
        self.window.apply_theme("light")
        self.window.show()
        APP.processEvents()
        QTest.qWait(30)

    def tearDown(self):
        dispose(self.window)
        self.patches.close()
        self.temporary.cleanup()

    def test_narrow_toolbar_and_version_action(self):
        self.window.markdown_toolbar.resize(270, 46)
        self.window.markdown_toolbar.reflow()
        actions = self.window.toolbar_catalogs["format"][1]
        self.assertIn(actions["增加 Vn"], self.window.markdown_toolbar.overflow_menu.actions())
        cursor = QTextCursor(self.window.editor.document().findBlockByNumber(2))
        self.window.editor.setTextCursor(cursor)
        actions["增加 Vn"].trigger()
        self.assertIn("# V3\n后续", self.window.editor.toPlainText())
        self.assertTrue(self.window.flush_auto_save())
        self.assertIn("# V3", self.path.read_text(encoding="utf-8"))

    def test_associated_path_conditional_and_open(self):
        self.assertFalse(self.window.open_project_action.isVisible())
        meta = self.window.project_meta(self.path, create=True)
        meta["project_path"] = str(self.path.parent)
        self.window.update_pin_button()
        self.assertTrue(self.window.open_project_action.isVisible())
        with patch("project_map.mixins.projects.QDesktopServices.openUrl", return_value=True) as opened:
            self.window.open_project_action.trigger()
            self.assertEqual(opened.call_args[0][0].toLocalFile(), str(self.path.parent).replace("\\", "/"))
        meta["project_path"] = ""
        self.window.update_pin_button()
        self.assertFalse(self.window.open_project_action.isVisible())

    def test_collapse_and_priority_are_persisted(self):
        self.window.quick_toolbar.set_collapsed(True)
        self.window.set_project_priority(self.path, "urgent")
        self.assertEqual(self.window.project_meta(self.path)["priority"], "urgent")
        self.assertFalse(self.window.file_list.currentItem().icon().isNull())
        settings = QSettings(self.window.settings.fileName(), QSettings.IniFormat)
        self.window.settings.sync()
        self.assertEqual(str(settings.value("toolbar/quick/collapsed")).lower(), "true")
        self.window.apply_theme("dark")
        self.window.quick_toolbar.set_collapsed(False)

    def test_project_context_conditional_open(self):
        captured = []
        self.window.project_meta(self.path, create=True)["project_path"] = str(self.path.parent)
        rect = self.window.file_list.visualItemRect(self.window.file_list.currentItem())
        with patch.object(RoundedMenu, "exec", lambda menu, *_: captured.extend(action.text() for action in menu.actions())):
            self.window.show_project_context_menu(rect.center())
        self.assertIn("打开项目位置", captured)
        self.assertIn("项目优先级", captured)

    def test_new_project_saves_optional_association(self):
        dialog = NewProjectDialog(self.window)
        dialog.value.setText("新测试项目")
        dialog.project_path.setText(str(self.path.parent))
        with patch("project_map.mixins.actions.NewProjectDialog", return_value=dialog), patch.object(dialog, "exec", return_value=QDialog.Accepted):
            self.window.new_file()
        new_path = self.path.parent / "新测试项目.md"
        self.assertTrue(new_path.is_file())
        self.assertEqual(self.window.project_meta(new_path)["project_path"], str(self.path.parent))
        self.assertTrue(self.window.open_project_action.isVisible())

    def test_text_priority_is_rendered_and_preview_scroll_stays(self):
        self.window.editor.setPlainText("\n\n".join(f"段落 {index} 示例文本" for index in range(120)))
        QTest.qWait(30)
        self.window.preview.verticalScrollBar().setValue(200)
        cursor = QTextCursor(self.window.editor.document().findBlockByNumber(80))
        self.window.editor.setTextCursor(cursor)
        self.window.editor.set_priority("urgent")
        QTest.qWait(30)
        self.assertEqual(self.window.preview.verticalScrollBar().value(), 200)
        self.assertIn("#dc2626", self.window.preview.toHtml())

    def test_toolbar_settings_share_complete_icons_and_labels(self):
        from test_icons import reference_icon
        from PySide6.QtCore import QSize

        actions = self.window.toolbar_catalogs["format"][1]
        symbols = {"撤销": "↶", "重做": "↷", "加粗": "B", "斜体": "I", "一级标题": "H1", "六级标题": "H6", "增加 Vn": "V+", "增加子版本": "v.x"}
        for theme in ("light", "dark"):
            self.window.apply_theme(theme)
            dialog = ToolbarSettingsDialog(self.window.settings, self.window.toolbar_catalogs, self.window)
            dialog.tabs.setCurrentWidget(dialog.lists["format"])
            dialog.show()
            dialog.lists["format"].setCurrentRow(1)
            dialog.lists["format"].setFocus()
            APP.processEvents()
            view = dialog.lists["format"]
            self.assertEqual(view.iconSize(), QSize(22, 22))
            for row in range(view.count()):
                item = view.item(row)
                name = item.data(Qt.UserRole)
                self.assertEqual(item.text(), actions[name].text())
                if name in symbols:
                    self.assertEqual(item.icon().pixmap(QSize(22, 22), 2).toImage(), reference_icon(symbols[name]).pixmap(QSize(22, 22), 2).toImage())
            if directory := os.environ.get("PROJECT_MAP_QA_DIR"):
                output = Path(directory)
                output.mkdir(parents=True, exist_ok=True)
                self.window.markdown_toolbar.grab().save(str(output / f"toolbar-{theme}.png"))
                dialog.grab().save(str(output / f"settings-{theme}.png"))
                view.scrollToItem(view.item(view.count() - 1))
                APP.processEvents()
                dialog.grab().save(str(output / f"settings-priorities-{theme}.png"))
            dispose(dialog)

    def test_single_settings_entry_and_two_character_priorities(self):
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QToolButton

        self.assertIsNotNone(self.window.quick_toolbar.configure)
        self.assertIsNone(self.window.markdown_toolbar.configure)
        buttons = [button for button in self.window.findChildren(QToolButton) if button.text() == "设置"]
        self.assertEqual(len(buttons), 1)
        labels = self.window.toolbar_catalogs["format"][1]
        self.assertTrue({"紧急", "优先", "普通"}.issubset(labels))
        self.assertFalse(any("（红色）" in name or "（蓝色）" in name or "（绿色）" in name for name in labels))
        opened = []

        def dismiss_settings():
            dialog = QApplication.activeModalWidget()
            if isinstance(dialog, ToolbarSettingsDialog):
                opened.append(dialog)
                dialog.reject()

        QTimer.singleShot(0, self.window, dismiss_settings)
        self.window.quick_toolbar.configure.click()
        self.assertEqual(len(opened), 1)
        self.assertEqual(set(opened[0].lists), {"quick", "format"})
        dispose(opened[0])

    def test_format_animation_keeps_editor_layout_fixed(self):
        bar = self.window.markdown_toolbar
        self.assertGreater(bar.tool_viewport.height(), 0)
        self.assertGreater(bar.tools.height(), 0)
        initial_editor_rect = self.window.editor.geometry()
        initial_bar_rect = bar.geometry()
        for theme in ("light", "dark"):
            self.window.apply_theme(theme)
            APP.processEvents()
            if directory := os.environ.get("PROJECT_MAP_QA_DIR"):
                output = Path(directory)
                output.mkdir(parents=True, exist_ok=True)
                bar.grab().save(str(output / f"animation-expanded-{theme}.png"))
            bar.set_collapsed(True)
            QTest.qWait(65)
            self.assertEqual(self.window.editor.geometry(), initial_editor_rect)
            self.assertEqual(bar.geometry(), initial_bar_rect)
            if directory:
                bar.grab().save(str(output / f"animation-closing-{theme}.png"))
            QTest.qWait(130)
            for _attempt in range(100):
                if not bar.transitioning:
                    break
                QTest.qWait(10)
            self.assertFalse(bar.transitioning)
            self.assertEqual(bar.tool_viewport.width(), 0)
            bar.set_collapsed(False)
            QTest.qWait(65)
            self.assertGreater(bar.tool_viewport.width(), 0)
            if directory:
                bar.grab().save(str(output / f"animation-opening-{theme}.png"))
            QTest.qWait(130)
            self.assertEqual(self.window.editor.geometry(), initial_editor_rect)
            self.assertEqual(bar.geometry(), initial_bar_rect)


if __name__ == "__main__":
    unittest.main()
