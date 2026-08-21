from __future__ import annotations

import html
import re
from pathlib import Path

import markdown as markdown_lib

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QImage, QTextCursor
from PySide6.QtWidgets import QTreeWidgetItem

from ..config import APP_DIR
from ..preview import ImageViewer

class PreviewMixin:

    def preview_base_dir(self):
        if self.current_path and not self.is_local_project(self.current_path):
            return self.current_path.parent
        return APP_DIR

    def content_changed(self):
        if self.loading:
            return
        self.dirty = True
        if hasattr(self, "auto_save_timer"):
            self.auto_save_timer.start()
        self.file_title.setText(self.display_name(self.current_path) + " *") if self.current_path else None
        self.update_preview()
        self.update_sidebar()

    def update_preview(self):
        if not hasattr(self, "preview"):
            return
        vertical_value = self.preview.verticalScrollBar().value()
        horizontal_value = self.preview.horizontalScrollBar().value()
        old_vertical_max = self.preview.verticalScrollBar().maximum()
        old_horizontal_max = self.preview.horizontalScrollBar().maximum()
        self.preview_update_serial = getattr(self, "preview_update_serial", 0) + 1
        update_serial = self.preview_update_serial
        dark = getattr(self.editor, "theme_name", "dark") == "dark"
        foreground = "#e5e7eb" if dark else "#1f2937"
        muted = "#8ea1bb" if dark else "#8b98aa"
        code_background = "#0b1220" if dark else "#f1f5f9"
        preview_size = self.preview_base_font_size * self.preview_zoom / 100
        divider = f"<table class='md-divider' width='100%' cellspacing='0' cellpadding='0' style='border-collapse:collapse; margin:14px 0 16px 0;'><tr><td style='border-bottom:2px dashed {muted}; height:1px; padding:0;'></td></tr></table>"
        source = re.sub(r"(?m)^\s*---\s*$", divider, self.preview_markdown())
        html = markdown_lib.markdown(source, extensions=["extra", "tables", "fenced_code", "sane_lists", "nl2br"])
        html = self.scale_preview_images(html)
        self.preview.document().setBaseUrl(QUrl.fromLocalFile(str(self.preview_base_dir()) + "/"))
        self.preview.document().setHtml(f"""
        <style>
            body {{ color:{foreground}; font-family:'Microsoft YaHei UI'; font-size:{preview_size:.1f}pt; line-height:1.55; }}
            h1,h2,h3,h4 {{ margin-top:18px; margin-bottom:8px; }}
            code, pre {{ background:{code_background}; border-radius:6px; }}
            code {{ padding:2px 5px; }}
            pre {{ padding:10px; white-space:pre-wrap; }}
            blockquote {{ color:{muted}; border-left:3px solid #60a5fa; margin-left:0; padding-left:12px; }}
            table {{ border-collapse:collapse; }}
            th,td {{ border:1px solid {muted}; padding:5px 8px; }}
        </style>
        {html}
        """)
        vertical_ratio = vertical_value / old_vertical_max if old_vertical_max else 0.0
        horizontal_ratio = horizontal_value / old_horizontal_max if old_horizontal_max else 0.0
        QTimer.singleShot(0, lambda: self.restore_preview_scroll(vertical_value, horizontal_value, vertical_ratio, horizontal_ratio, update_serial, 0))
        self.update_toc_and_tasks()

    def scale_preview_images(self, rendered_html):
        image_pattern = re.compile(r"<img\b([^>]*?)\bsrc=[\"']([^\"']+)[\"']([^>]*)>", re.IGNORECASE)

        def replace_image(match):
            before, source, after = match.groups()
            if source.startswith("file:"):
                candidates = [Path(QUrl(source).toLocalFile())]
            else:
                source_path = Path(source.replace("/", "\\"))
                candidates = [source_path] if source_path.is_absolute() else [
                    self.preview_base_dir() / source_path,
                    APP_DIR / source_path,
                ]
            local_path = next((candidate for candidate in candidates if candidate.is_file()), candidates[0])
            image = QImage(str(local_path))
            if image.isNull():
                return match.group(0)
            viewport_width = self.preview.viewport().width()
            if viewport_width <= 0:
                viewport_width = 760
            fit_width = max(320, min(860, viewport_width - 48))
            width = max(1, round(image.width() * self.preview_zoom / 100))
            max_width = max(1, round(fit_width * self.preview_zoom / 100))
            if width > max_width:
                width = max_width
            height = max(1, round(image.height() * width / image.width()))
            cleaned = re.sub(r"\sstyle=[\"'][^\"']*[\"']", "", before + after, flags=re.IGNORECASE)
            cleaned = re.sub(r"/\s*$", "", cleaned).strip()
            return f'<img {cleaned} src="{html.escape(source, quote=True)}" width="{width}" height="{height}">'

        return image_pattern.sub(replace_image, rendered_html)

    def open_preview_image(self, path):
        image_path = Path(path)
        if image_path.is_file():
            ImageViewer(image_path, self).exec()

    def restore_preview_scroll(self, vertical_value, horizontal_value, vertical_ratio=0.0, horizontal_ratio=0.0, update_serial=None, attempt=0):
        if update_serial is not None and update_serial != getattr(self, "preview_update_serial", update_serial):
            return
        vertical = self.preview.verticalScrollBar()
        horizontal = self.preview.horizontalScrollBar()
        if attempt < 8 and vertical.maximum() == 0 and (vertical_value or vertical_ratio):
            QTimer.singleShot(25, lambda: self.restore_preview_scroll(vertical_value, horizontal_value, vertical_ratio, horizontal_ratio, update_serial, attempt + 1))
            return
        vertical.setValue(min(vertical.maximum(), max(0, round(vertical_value if vertical_value else vertical.maximum() * vertical_ratio))))
        horizontal.setValue(min(horizontal.maximum(), max(0, round(horizontal_value if horizontal_value else horizontal.maximum() * horizontal_ratio))))

    def preview_markdown(self):
        lines = self.editor.toPlainText().splitlines()
        for start, end in self.editor.pasted_number_blocks:
            for index in range(max(0, start), min(len(lines), end + 1)):
                if re.match(r"^\d+\.\s+", lines[index]) and not lines[index].startswith(("\t", "    ")):
                    lines[index] = "\t" + lines[index]
        return "\n".join(lines)

    def update_toc_and_tasks(self):
        self.toc.clear()
        stack = [(0, self.toc.invisibleRootItem())]
        for line_no, line in enumerate(self.editor.toPlainText().splitlines()):
            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                title = line[level:].strip() or "未命名标题"
                while stack and stack[-1][0] >= level:
                    stack.pop()
                parent = stack[-1][1] if stack else self.toc.invisibleRootItem()
                item = QTreeWidgetItem(parent, [title])
                item.setData(0, Qt.UserRole, line_no)
                stack.append((level, item))
        self.tasks.clear()
        for line_no, line in enumerate(self.editor.toPlainText().splitlines()):
            stripped = line.strip()
            if stripped.startswith("- [") and len(stripped) > 5:
                checked = stripped[3].lower() == "x"
                task = QTreeWidgetItem(self.tasks, [stripped[5:], "完成" if checked else "待办"])
                task.setData(0, Qt.UserRole, line_no)
                task.setForeground(1, QColor("#34d399" if checked else "#fbbf24"))
        self.tasks.resizeColumnToContents(1)

    def update_sidebar(self):
        if not self.current_path:
            return
        lines = self.editor.toPlainText().splitlines()
        total = sum(line.strip().startswith("- [") for line in lines)
        done = sum(line.strip().lower().startswith("- [x]") for line in lines)
        meta = self.project_meta(self.current_path)
        self.info.setText(f"项目：{self.display_name(self.current_path)}\n\n分组：{meta.get('group', '默认项目')}\n描述：{meta.get('description', '暂无描述')}\n\n完成度：{done}/{total} 个任务")

    def jump_to_heading(self, item, _column):
        self.jump_to_line(item.data(0, Qt.UserRole))

    def jump_to_task(self, item, _column):
        self.jump_to_line(item.data(0, Qt.UserRole))

    def jump_to_line(self, line):
        cursor = self.editor.textCursor()
        cursor.movePosition(QTextCursor.Start)
        cursor.movePosition(QTextCursor.Down, QTextCursor.MoveAnchor, int(line))
        self.editor.setTextCursor(cursor)
        self.editor.ensureCursorVisible()
