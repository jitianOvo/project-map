from __future__ import annotations

from ..locations import path_identity


class IntegrationMixin:
    def change_data_sources(self, markdown, media):
        selected = self.paths.with_sources(markdown, media)
        if selected == self.paths:
            return
        if hasattr(self, "cloud") and self.cloud.editing.defer_until_released(lambda: self.change_data_sources(markdown, media)):
            return
        if hasattr(self, "cloud") and self.cloud.busy:
            raise ValueError("正在同步，请稍后再切换数据目录")
        if not self.flush_auto_save():
            raise OSError("当前项目未保存，数据目录没有切换")
        self.save_project_view_state()
        self.save_metadata()
        self.settings.sync()
        old_paths = self.paths
        selected.save()
        self.paths = selected
        if path_identity(old_paths.markdown) != path_identity(selected.markdown):
            self.metadata = self.load_metadata()
            self.current_path = None
            self.editor.current_document_path = None
            self.dirty = False
            self.set_project_filter_by_name(self.ALL_GROUPS)
            watched = self.watcher.files() + self.watcher.directories()
            if watched:
                self.watcher.removePaths(watched)
            self.watcher.addPath(str(selected.markdown))
        self.editor.media_dir = selected.media
        self.cloud.rebind()
        self.refresh_files()
        self.update_preview()
        self.statusBar().showMessage("数据目录已切换，原文件保持不变")
