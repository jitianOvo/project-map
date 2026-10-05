from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout,
)

from .appearance import apply_window_icon

class ProjectDialog(QDialog):
    def __init__(self, name, meta, groups=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("项目属性")
        apply_window_icon(self)
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.name = QLineEdit(name)
        self.group = QComboBox()
        self.group.setEditable(True)
        self.group.addItems(groups or ["默认项目"])
        current_group = meta.get("group", "默认项目")
        if self.group.findText(current_group) < 0:
            self.group.addItem(current_group)
        self.group.setCurrentText(current_group)
        self.description = QLineEdit(meta.get("description", ""))
        form.addRow("显示名称", self.name)
        form.addRow("项目分组", self.group)
        form.addRow("项目描述", self.description)
        self.project_path = add_project_path_field(form, meta.get("project_path", ""), self)
        buttons = QHBoxLayout()
        cancel = QPushButton("取消")
        save = QPushButton("保存")
        save.setObjectName("primaryButton")
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        self.name.returnPressed.connect(self.accept)
        self.group.lineEdit().returnPressed.connect(self.accept)
        self.description.returnPressed.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        form.addRow(buttons)


class NameDialog(QDialog):
    def __init__(self, title, label, value="", parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        apply_window_icon(self)
        self.setMinimumWidth(420)
        form = QFormLayout(self)
        self.value = QLineEdit(value)
        self.value.selectAll()
        form.addRow(label, self.value)
        buttons = QHBoxLayout()
        cancel = QPushButton("取消")
        confirm = QPushButton("确定")
        confirm.setObjectName("primaryButton")
        confirm.setDefault(True)
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self.accept)
        self.value.returnPressed.connect(self.accept)
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(confirm)
        form.addRow(buttons)


def add_project_path_field(form, value, parent):
    row = QHBoxLayout()
    edit = QLineEdit(value)
    edit.setPlaceholderText("选填：项目的文件夹或文件路径")
    row.addWidget(edit, 1)
    for label, folder in (("文件夹", True), ("文件", False)):
        button = QPushButton(label)
        button.setAutoDefault(False)

        def browse(_checked=False, choose_folder=folder):
            if choose_folder:
                path = QFileDialog.getExistingDirectory(parent, "选择项目文件夹", edit.text())
            else:
                path, _filter = QFileDialog.getOpenFileName(parent, "选择项目文件", edit.text())
            if path:
                edit.setText(path)

        button.clicked.connect(browse)
        row.addWidget(button)
    form.addRow("项目位置（选填）", row)
    return edit


class NewProjectDialog(NameDialog):
    def __init__(self, parent=None):
        super().__init__("新建项目大纲", "文件名", "新项目大纲", parent)
        form = self.layout()
        self.project_path = add_project_path_field(form, "", self)
        # 保持确定按钮在全部输入项下方。
        field = form.takeRow(form.rowCount() - 1)
        form.insertRow(1, field.labelItem.widget(), field.fieldItem.layout())


class FindReplaceDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("查找和替换")
        apply_window_icon(self)
        self.setMinimumWidth(500)
        self.setModal(False)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText("输入要查找的内容")
        self.replace_edit = QLineEdit()
        self.replace_edit.setPlaceholderText("输入替换后的内容")
        form.addRow("查找内容", self.find_edit)
        form.addRow("替换为", self.replace_edit)
        layout.addLayout(form)
        options = QHBoxLayout()
        self.case_sensitive = QCheckBox("区分大小写")
        self.whole_word = QCheckBox("全字匹配")
        options.addWidget(self.case_sensitive)
        options.addWidget(self.whole_word)
        options.addStretch()
        layout.addLayout(options)
        buttons = QHBoxLayout()
        self.find_button = QPushButton("查找下一个")
        self.replace_button = QPushButton("替换")
        self.replace_all_button = QPushButton("全部替换")
        close_button = QPushButton("关闭")
        close_button.clicked.connect(self.close)
        buttons.addWidget(self.find_button)
        buttons.addWidget(self.replace_button)
        buttons.addWidget(self.replace_all_button)
        buttons.addStretch()
        buttons.addWidget(close_button)
        layout.addLayout(buttons)
        self.find_edit.returnPressed.connect(self.find_button.click)


class MediaFoldersDialog(QDialog):
    def __init__(self, default_directory, extra_directories=None, parent=None):
        super().__init__(parent)
        self.default_directory = Path(default_directory).resolve(strict=False)
        self.setWindowTitle("图片缓存目录")
        apply_window_icon(self)
        self.setMinimumSize(620, 390)
        layout = QVBoxLayout(self)

        title = QLabel("默认图片缓存目录")
        title.setObjectName("dialogSectionTitle")
        layout.addWidget(title)
        default_path = QLabel(str(self.default_directory))
        default_path.setObjectName("pathLabel")
        default_path.setTextInteractionFlags(Qt.TextSelectableByMouse)
        default_path.setWordWrap(True)
        layout.addWidget(default_path)

        extra_title = QLabel("附加查找目录（可加入源码版或编译版使用的其他 Media 文件夹）")
        extra_title.setObjectName("dialogSectionTitle")
        layout.addWidget(extra_title)
        self.folder_list = QListWidget()
        for directory in extra_directories or []:
            self.add_directory_item(directory)
        layout.addWidget(self.folder_list, 1)

        manage_row = QHBoxLayout()
        add_button = QPushButton("＋ 添加文件夹")
        remove_button = QPushButton("移除选中")
        open_button = QPushButton("打开选中目录")
        add_button.clicked.connect(self.choose_directory)
        remove_button.clicked.connect(self.remove_selected)
        open_button.clicked.connect(self.open_selected)
        manage_row.addWidget(add_button)
        manage_row.addWidget(remove_button)
        manage_row.addWidget(open_button)
        manage_row.addStretch()
        layout.addLayout(manage_row)

        note = QLabel("粘贴的新图片仍写入默认目录；预览会按项目目录、默认目录和以上附加目录依次查找。")
        note.setObjectName("muted")
        note.setWordWrap(True)
        layout.addWidget(note)

        button_row = QHBoxLayout()
        cancel = QPushButton("暂不保存")
        save = QPushButton("保存配置")
        save.setObjectName("primaryButton")
        save.setDefault(True)
        cancel.clicked.connect(self.reject)
        save.clicked.connect(self.accept)
        button_row.addStretch()
        button_row.addWidget(cancel)
        button_row.addWidget(save)
        layout.addLayout(button_row)

    @staticmethod
    def normalized(path):
        return str(Path(path).resolve(strict=False)).casefold()

    def add_directory_item(self, directory):
        path = Path(directory).resolve(strict=False)
        existing = {self.normalized(self.folder_list.item(index).data(Qt.UserRole)) for index in range(self.folder_list.count())}
        if self.normalized(path) == self.normalized(self.default_directory) or self.normalized(path) in existing:
            return
        item = QListWidgetItem(str(path))
        item.setData(Qt.UserRole, str(path))
        item.setToolTip(str(path))
        self.folder_list.addItem(item)

    def choose_directory(self):
        selected = QFileDialog.getExistingDirectory(self, "选择附加图片缓存目录", str(self.default_directory.parent))
        if selected:
            self.add_directory_item(selected)

    def remove_selected(self):
        for item in self.folder_list.selectedItems():
            self.folder_list.takeItem(self.folder_list.row(item))

    def open_selected(self):
        item = self.folder_list.currentItem()
        if item:
            QDesktopServices.openUrl(QUrl.fromLocalFile(item.data(Qt.UserRole)))

    def directories(self):
        return [Path(self.folder_list.item(index).data(Qt.UserRole)) for index in range(self.folder_list.count())]
