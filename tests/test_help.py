from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QContextMenuEvent, QKeySequence
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog
from shiboken6 import isValid

import test_workflow as workflow
from project_map.help_content import ARTICLES, action_shortcuts, build_help_articles, search_articles
from project_map.toolbars import ToolbarSettingsDialog
from project_map.menus import RoundedMenu


class HelpContentTests(unittest.TestCase):
    def test_public_topics_have_unique_ids_and_cover_hidden_rules(self):
        articles = build_help_articles()
        self.assertGreaterEqual(len(articles), 18)
        self.assertEqual(len(articles), len({article.identifier for article in articles}))
        self.assertEqual(articles[0].identifier, "start")
        for query in ("Tab", "Shift+Enter", "微信", "Vn", "冲突", "图片", "永久删除", "Ctrl + B"):
            self.assertTrue(search_articles(articles, query), query)
        paste = next(article for article in articles if article.identifier == "paste")
        self.assertIn("普通粘贴", paste.body)
        self.assertIn("不一定触发", paste.body)
        versions = next(article for article in articles if article.identifier == "versions")
        self.assertIn("字面量", versions.body)

    def test_search_is_case_insensitive_and_filters_category(self):
        self.assertTrue(search_articles(ARTICLES, "ctrl+b"))
        self.assertTrue(search_articles(ARTICLES, "图片 缓存", "数据与图片"))
        self.assertFalse(search_articles(ARTICLES, "绝不可能匹配的主题"))
        self.assertTrue(all(article.category == "云同步" for article in search_articles(ARTICLES, "", "云同步")))

    def test_shortcut_article_uses_live_action_not_a_hardcoded_table(self):
        action = QAction("临时工具")
        action.setShortcut(QKeySequence("Ctrl+Alt+9"))
        catalogs = {"quick": ("快速工具", {"临时工具": action})}
        article = next(article for article in build_help_articles(catalogs) if article.identifier == "shortcuts")
        self.assertIn("Ctrl+Alt+9", article.body)
        action.setShortcut(QKeySequence("Ctrl+Alt+8"))
        article = next(article for article in build_help_articles(catalogs) if article.identifier == "shortcuts")
        self.assertIn("Ctrl+Alt+8", article.body)
        self.assertNotIn("Ctrl+Alt+9", article.body)


class HelpUiTests(unittest.TestCase):
    setUp = workflow.WindowTests.setUp
    tearDown = workflow.WindowTests.tearDown

    def create_dialog(self):
        dialog = ToolbarSettingsDialog(self.window.settings, self.window.toolbar_catalogs, self.window)
        self.addCleanup(lambda: workflow.dispose(dialog) if isValid(dialog) else None)
        dialog.tabs.setCurrentWidget(dialog.help_panel)
        dialog.show()
        workflow.APP.processEvents()
        return dialog

    def test_help_has_live_shortcuts_and_chinese_read_only_reader(self):
        dialog = self.create_dialog()
        help_panel = dialog.help_panel
        self.assertTrue(help_panel.reader.isReadOnly())
        self.assertEqual(help_panel.article_id, "start")
        article = next(article for article in help_panel.articles if article.identifier == "shortcuts")
        for shortcut, label, _category in action_shortcuts(self.window.toolbar_catalogs, self.window.actions()):
            self.assertIn(shortcut, article.body)
            self.assertIn(label, article.body)
        self.assertIn("F1", article.body)
        self.assertIn("Alt+Z", article.body)
        self.assertEqual(set(dialog.lists), {"quick", "format"})

    def test_search_and_enter_do_not_accept_settings_or_modify_document(self):
        original_text = self.window.editor.toPlainText()
        original_bytes = self.path.read_bytes()
        original_config = dict(self.window.cloud.config)
        dialog = self.create_dialog()
        panel = dialog.help_panel
        panel.search.setText("Shift+Tab")
        QTest.keyClick(panel.search, Qt.Key_Return)
        workflow.APP.processEvents()
        self.assertTrue(dialog.isVisible())
        self.assertEqual(dialog.result(), QDialog.Rejected)
        self.assertGreater(panel.topics.count(), 0)
        self.assertIn("Shift+Tab", panel.reader.toPlainText())
        panel.search.setText("找不到这项测试说明")
        panel.filter_topics()
        self.assertEqual(panel.topics.count(), 0)
        self.assertIn("没有找到", panel.reader.toPlainText())
        panel.search.clear()
        panel.set_category("云同步")
        self.assertEqual(panel.topics.count(), 2)
        self.assertEqual(self.window.editor.toPlainText(), original_text)
        self.assertEqual(self.path.read_bytes(), original_bytes)
        self.assertEqual(self.window.cloud.config, original_config)

    def test_f1_opens_help_without_an_extra_settings_button(self):
        self.window.activateWindow()
        self.window.editor.setFocus()
        workflow.APP.processEvents()
        with patch.object(self.window, "show_toolbar_settings") as show:
            QTest.keyClick(self.window.editor, Qt.Key_F1)
            workflow.APP.processEvents()
        show.assert_called_once_with("使用说明")
        self.assertIsNone(self.window.markdown_toolbar.configure)

    def test_help_find_shortcut_and_search_focus(self):
        dialog = self.create_dialog()
        panel = dialog.help_panel
        self.assertTrue(panel.search.hasFocus())
        panel.reader.setFocus()
        QTest.keyClick(panel.reader, Qt.Key_F, Qt.ControlModifier)
        workflow.APP.processEvents()
        self.assertTrue(panel.search.hasFocus())
        self.assertEqual(panel.topics.itemDelegate().__class__.__name__, "NoFocusFrameDelegate")

    def test_help_renders_both_themes_and_long_markdown_examples(self):
        dialog = self.create_dialog()
        panel = dialog.help_panel
        for theme in ("light", "dark"):
            self.window.apply_theme(theme)
            for index in range(panel.topics.count()):
                panel.topics.setCurrentRow(index)
                workflow.APP.processEvents()
                self.assertGreater(len(panel.reader.toPlainText()), 80)
        panel.search.setText("增加子版本")
        panel.filter_topics()
        self.assertGreater(panel.topics.count(), 0)

    def test_help_search_context_menu_is_chinese(self):
        dialog = self.create_dialog()
        search = dialog.help_panel.search
        search.setText("测试搜索")
        search.selectAll()
        labels = []
        with patch.object(RoundedMenu, "exec", lambda menu, *_args: labels.extend(action.text() for action in menu.actions())):
            event = QContextMenuEvent(QContextMenuEvent.Mouse, search.rect().center(), search.mapToGlobal(search.rect().center()))
            workflow.APP.sendEvent(search, event)
        self.assertEqual(labels, ["撤销", "重做", "剪切", "复制", "粘贴", "删除选中内容", "全选"])


if __name__ == "__main__":
    unittest.main()
