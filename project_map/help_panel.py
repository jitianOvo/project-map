from __future__ import annotations

import markdown
from PySide6.QtCore import QEvent, QTimer, Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QSplitter, QToolButton, QVBoxLayout, QWidget,
)

from .help_content import build_help_articles, search_articles
from .menus import RoundedMenu
from .preview import PreviewBrowser
from .project_list import NoFocusFrameDelegate


class HelpPanel(QWidget):
    def __init__(self, catalogs, actions=(), parent=None):
        super().__init__(parent)
        self.articles = build_help_articles(catalogs, actions)
        self.category = None
        self.article_id = None
        self.category_actions = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 6, 0, 0)
        row = QHBoxLayout()
        self.search = QLineEdit(self)
        self.search.setPlaceholderText("搜索功能、用法或快捷键，例如：Tab、图片、Ctrl+B")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("搜索使用说明")
        self.search.installEventFilter(self)
        row.addWidget(self.search, 1)
        self.category_button = QToolButton(self)
        self.category_button.setObjectName("filterButton")
        self.category_button.setPopupMode(QToolButton.InstantPopup)
        menu = RoundedMenu(self.category_button)
        for name in (None, *dict.fromkeys(article.category for article in self.articles)):
            action = menu.addAction(name or "全部主题")
            action.setCheckable(True)
            action.triggered.connect(lambda _checked=False, value=name: self.set_category(value))
            self.category_actions[name] = action
        self.category_button.setMenu(menu)
        row.addWidget(self.category_button)
        layout.addLayout(row)
        self.result_label = QLabel(self)
        self.result_label.setObjectName("muted")
        layout.addWidget(self.result_label)
        self.topics = QListWidget(self)
        self.topics.setAccessibleName("说明主题")
        self.topics.setItemDelegate(NoFocusFrameDelegate(self.topics))
        self.topics.setMinimumWidth(155)
        self.topics.setWordWrap(True)
        self.topics.installEventFilter(self)
        self.topics.currentItemChanged.connect(self.show_article)
        self.reader = PreviewBrowser(self)
        self.reader.setAccessibleName("说明正文")
        self.reader.setOpenLinks(False)
        self.reader.setOpenExternalLinks(False)
        for bar in (self.topics.verticalScrollBar(), self.reader.verticalScrollBar(), self.reader.horizontalScrollBar()):
            bar.installEventFilter(self)
        splitter = QSplitter(Qt.Horizontal, self)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self.topics)
        splitter.addWidget(self.reader)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([205, 570])
        layout.addWidget(splitter, 1)
        hint = QLabel("离线可用 · 说明只读，不改动大纲 · F1 直达说明 · Ctrl+F 搜索说明", self)
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(90)
        self.filter_timer.timeout.connect(self.filter_topics)
        self.search.textChanged.connect(lambda _text: self.filter_timer.start())
        self.find_shortcut = QShortcut(QKeySequence.Find, self)
        self.find_shortcut.setContext(Qt.WidgetWithChildrenShortcut)
        self.find_shortcut.activated.connect(self.focus_search)
        self.set_category(None)

    def focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def set_category(self, category):
        self.category = category
        self.category_button.setText(category or "全部主题")
        for name, action in self.category_actions.items():
            action.setChecked(name == category)
        self.filter_topics()

    def filter_topics(self):
        self.filter_timer.stop()
        selected = self.article_id
        matches = search_articles(self.articles, self.search.text(), self.category)
        self.topics.blockSignals(True)
        self.topics.clear()
        target = 0
        for index, article in enumerate(matches):
            item = QListWidgetItem(article.title)
            item.setData(Qt.UserRole, article.identifier)
            item.setToolTip(f"{article.category} · {article.title}")
            self.topics.addItem(item)
            if article.identifier == selected:
                target = index
        self.topics.blockSignals(False)
        self.result_label.setText(f"{len(matches)} 个主题 · {self.category or '全部分类'}")
        if matches:
            self.topics.setCurrentRow(target)
        else:
            self.article_id = None
            self.render("# 没有找到对应说明\n\n试试更短的关键词，或切回“全部主题”。\n\n例如：编号、Vn、图片、云同步、Ctrl+B。")

    def show_article(self, item, _previous=None):
        if item is None:
            return
        identifier = item.data(Qt.UserRole)
        article = next(article for article in self.articles if article.identifier == identifier)
        self.article_id = identifier
        self.render(article.markdown)
        self.reader.verticalScrollBar().setValue(0)

    def render(self, source):
        dark = QApplication.instance().property("theme") != "light"
        text, muted, accent, code = ("#e5e7eb", "#a6b5cb", "#93c5fd", "#18263c") if dark else ("#1f2937", "#64748b", "#2563eb", "#f1f5f9")
        rendered = markdown.markdown(source, extensions=["tables", "fenced_code", "sane_lists"])
        self.reader.setHtml(f"""<html><head><style>
            body {{ color:{text}; font-family:'Microsoft YaHei UI'; font-size:10.5pt; }}
            h1 {{ color:{accent}; font-size:17pt; margin-bottom:14px; }}
            h2 {{ font-size:12.5pt; margin-top:20px; margin-bottom:8px; }}
            p, li {{ margin-top:6px; margin-bottom:8px; }}
            code, pre {{ background:{code}; font-family:Consolas,'Microsoft YaHei UI'; }}
            pre {{ padding:10px; white-space:pre-wrap; }}
            th {{ background:{code}; }}
            th, td {{ border:1px solid {muted}; padding:6px; }}
        </style></head><body>{rendered}</body></html>""")

    def eventFilter(self, watched, event):
        if watched is self.search and event.type() == QEvent.ContextMenu:
            menu = RoundedMenu(self.search)
            clipboard = QApplication.clipboard()
            for label, handler, enabled, shortcut in (
                ("撤销", self.search.undo, self.search.isUndoAvailable(), "Ctrl+Z"),
                ("重做", self.search.redo, self.search.isRedoAvailable(), "Ctrl+Y"),
                ("剪切", self.search.cut, self.search.hasSelectedText(), "Ctrl+X"),
                ("复制", self.search.copy, self.search.hasSelectedText(), "Ctrl+C"),
                ("粘贴", self.search.paste, bool(clipboard.text()), "Ctrl+V"),
                ("删除选中内容", lambda: self.search.insert(""), self.search.hasSelectedText(), ""),
                ("全选", self.search.selectAll, bool(self.search.text()), "Ctrl+A"),
            ):
                action = menu.addAction(label, handler)
                action.setEnabled(enabled)
                if shortcut:
                    action.setShortcut(QKeySequence(shortcut))
                    action.setShortcutVisibleInContextMenu(True)
            menu.exec(event.globalPos())
            return True
        if event.type() == QEvent.KeyPress and watched in (self.search, self.topics):
            if event.key() in (Qt.Key_Return, Qt.Key_Enter):
                self.filter_topics()
                self.topics.setFocus()
                return True
            if watched is self.search and event.key() == Qt.Key_Down:
                self.filter_topics()
                self.topics.setFocus()
                return True
        if event.type() in (QEvent.Enter, QEvent.Leave) and watched not in (self.search, self.topics):
            watched.setProperty("hovered", event.type() == QEvent.Enter)
            watched.style().unpolish(watched)
            watched.style().polish(watched)
            watched.update()
        return super().eventFilter(watched, event)
