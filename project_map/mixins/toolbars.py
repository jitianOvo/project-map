from __future__ import annotations

from PySide6.QtWidgets import QDialog

from ..toolbars import ToolbarSettingsDialog, toolbar_enabled


class ToolbarsMixin:
    def configure_toolbar(self, bar, key, actions):
        self.toolbar_catalogs[key] = (bar.title, actions)
        self.toolbar_widgets[key] = bar
        bar.settings_requested.connect(self.show_toolbar_settings)
        bar.collapsed_changed.connect(lambda value: self.settings.setValue(f"toolbar/{key}/collapsed", value))
        collapsed = str(self.settings.value(f"toolbar/{key}/collapsed", "false")).lower() == "true"
        bar.set_collapsed(collapsed, notify=False)
        bar.set_entries([actions[item] for item in toolbar_enabled(self.settings, key, actions)])

    def show_toolbar_settings(self):
        dialog = ToolbarSettingsDialog(self.settings, self.toolbar_catalogs, self)
        if dialog.exec() == QDialog.Accepted:
            dialog.save_configuration()
            for key, (_title, actions) in self.toolbar_catalogs.items():
                self.toolbar_widgets[key].set_entries([actions[item] for item in toolbar_enabled(self.settings, key, actions)])
            self.statusBar().showMessage("工具栏设置已保存")
