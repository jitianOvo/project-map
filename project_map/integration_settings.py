from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QCheckBox, QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from .cloud.api import normalize_endpoint
from .locations import cloud_dir
from .menus import RoundedMenu


class CloudIssueDetails(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMinimumHeight(90)
        self.setMaximumHeight(160)
        self.setAccessibleName("云同步待处理详情")

    def contextMenuEvent(self, event):
        menu = RoundedMenu(self)
        copy = menu.addAction("复制", self.copy)
        copy.setEnabled(self.textCursor().hasSelection())
        menu.addAction("全选", self.selectAll)
        menu.exec(event.globalPos())


class DataSourcesPanel(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window = window
        layout = QVBoxLayout(self)
        note = QLabel("源码版与单文件版共用这两个目录。已有资料直接读取，新建大纲和粘贴图片也写入这里。")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.markdown = self.directory_field(form, "Markdown 文件夹", window.paths.markdown)
        self.media = self.directory_field(form, "图片缓存文件夹", window.paths.media)
        layout.addLayout(form)
        reset = QPushButton("恢复项目外层目录")
        reset.clicked.connect(self.restore_defaults)
        layout.addWidget(reset)
        help_text = QLabel("切换文件夹不会移动、覆盖或删除原文件。可随时切回；每个项目的分组、排序、阅读进度分别保留。切换大纲目录后显示全部项目，避免旧分组把新资料隐藏。\n\n单个外部 Markdown 仍可用顶部“导入”链接。其他旧图片目录可在“图片缓存”中作为附加查找目录。")
        help_text.setWordWrap(True)
        help_text.setObjectName("muted")
        layout.addWidget(help_text)
        layout.addStretch()

    def directory_field(self, form, label, value):
        row = QHBoxLayout()
        edit = QLineEdit(str(value))
        edit.setMinimumWidth(220)
        row.addWidget(edit, 1)
        choose = QPushButton("选择…")
        choose.setAutoDefault(False)
        choose.clicked.connect(lambda: self.choose_directory(edit, label))
        row.addWidget(choose)
        open_button = QPushButton("打开")
        open_button.setAutoDefault(False)
        open_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(edit.text())))
        row.addWidget(open_button)
        form.addRow(label, row)
        return edit

    def choose_directory(self, edit, label):
        directory = QFileDialog.getExistingDirectory(self, "选择" + label, edit.text())
        if directory:
            edit.setText(directory)

    def restore_defaults(self):
        self.markdown.setText(str(self.window.paths.root / "Markdown"))
        self.media.setText(str(self.window.paths.root / "Media"))

    def validate(self):
        if not self.markdown.text().strip() or not self.media.text().strip():
            raise ValueError("请为 Markdown 和图片缓存各选一个文件夹")
        changed = (Path(self.markdown.text()).resolve() != self.window.paths.markdown.resolve()
                   or Path(self.media.text()).resolve() != self.window.paths.media.resolve())
        if changed and self.window.cloud.busy:
            raise ValueError("正在同步，请稍后再切换目录")


class CloudSettingsPanel(QWidget):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.cloud = window.cloud
        layout = QVBoxLayout(self)
        note = QLabel("云同步是本地软件的附加功能，不再使用另一套 Windows 编辑器。手机使用相同服务器和账号；本地文件与图片仍在你选定的文件夹里。")
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.endpoint = QLineEdit(self.cloud.config["endpoint"])
        self.username = QLineEdit(self.cloud.config.get("username", "owner"))
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.Password)
        self.password.setPlaceholderText("只用于登录，不保存密码")
        form.addRow("服务器", self.endpoint)
        form.addRow("云账号", self.username)
        form.addRow("密码", self.password)
        layout.addLayout(form)
        self.auto_login = QCheckBox("记住登录，下次自动登录")
        self.auto_login.setChecked(bool(self.cloud.config.get("auto_login", True)))
        layout.addWidget(self.auto_login)
        self.enabled = QCheckBox("启用自动云同步")
        self.enabled.setChecked(bool(self.cloud.config.get("enabled")))
        self.external = QCheckBox("也同步通过“导入”链接的外部项目")
        self.external.setChecked(bool(self.cloud.config.get("include_external")))
        layout.addWidget(self.enabled)
        layout.addWidget(self.external)
        row = QHBoxLayout()
        self.login_button = QPushButton("登录并启用")
        self.login_button.setAutoDefault(False)
        self.login_button.setObjectName("primaryButton")
        self.login_button.clicked.connect(self.login)
        row.addWidget(self.login_button)
        sync = QPushButton("立即同步")
        sync.setAutoDefault(False)
        sync.clicked.connect(self.sync_now)
        row.addWidget(sync)
        logout = QPushButton("退出云账号")
        logout.setAutoDefault(False)
        logout.clicked.connect(self.cloud.logout)
        row.addWidget(logout)
        layout.addLayout(row)
        self.status = QLabel(self.cloud.status)
        self.status.setTextFormat(Qt.PlainText)
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.issue_box = QWidget(self)
        issue_layout = QVBoxLayout(self.issue_box)
        issue_layout.setContentsMargins(0, 0, 0, 0)
        issue_layout.addWidget(QLabel("待处理详情（其他项目仍会正常同步）"))
        self.details = CloudIssueDetails(self)
        issue_layout.addWidget(self.details)
        issue_buttons = QHBoxLayout()
        media = QPushButton("图片缓存设置")
        media.setAutoDefault(False)
        media.clicked.connect(window.show_media_folders)
        issue_buttons.addWidget(media)
        copy = QPushButton("复制完整详情")
        copy.setAutoDefault(False)
        copy.clicked.connect(lambda: QApplication.clipboard().setText(self.details.toPlainText()))
        issue_buttons.addWidget(copy)
        issue_buttons.addStretch()
        issue_layout.addLayout(issue_buttons)
        layout.addWidget(self.issue_box)
        self.cloud.status_changed.connect(self.update_status)
        self.update_status(self.cloud.status)
        self.cloud.login_finished.connect(self.login_result)
        hint = QLabel("自动登录只保存受 Windows 保护的登录令牌，不保存密码；登录过期可自动续期。取消记住或退出账号后，下次需手动登录。\n\n本地自动保存与云同步分开运行。断网修改会留在本机，恢复联网后重试；两端同时修改可合并的内容自动合并，冲突保留副本。云端删除在本机先备份，不直接永久删除。")
        hint.setWordWrap(True)
        hint.setObjectName("muted")
        layout.addWidget(hint)
        login_info = cloud_dir(window.paths.root) / ".secrets" / "云端首次登录.txt"
        if login_info.is_file():
            view = QPushButton("打开首次登录信息")
            view.setAutoDefault(False)
            view.clicked.connect(lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(str(login_info))))
            layout.addWidget(view)
        layout.addStretch()

    def update_status(self, status):
        self.status.setText(status)
        text = "\n\n".join(self.cloud.issue_text(issue) for issue in self.cloud.issues)
        if text != self.details.toPlainText():
            self.details.setPlainText(text)
        self.issue_box.setVisible(bool(text))

    def login(self):
        self.login_button.setEnabled(False)
        self.cloud.login(self.endpoint.text(), self.username.text(), self.password.text(), self.auto_login.isChecked())

    def login_result(self, success, message):
        self.login_button.setEnabled(True)
        self.status.setText(message)
        if success:
            self.password.clear()
            self.enabled.setChecked(True)

    def validate(self):
        endpoint = normalize_endpoint(self.endpoint.text())
        if endpoint != self.cloud.config["endpoint"] and self.cloud.busy:
            raise ValueError("正在同步，请稍后切换服务器")

    def save(self):
        self.cloud.save_config(endpoint=self.endpoint.text(), enabled=self.enabled.isChecked(), include_external=self.external.isChecked(), auto_login=self.auto_login.isChecked())

    def sync_now(self):
        try:
            self.validate()
            self.save()
            self.cloud.synchronize(force=True)
        except (ValueError, OSError) as error:
            self.status.setText(str(error))
