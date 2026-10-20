from __future__ import annotations

import base64
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from PySide6.QtCore import QByteArray, QBuffer, QIODevice, QObject, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


class Bridge(QObject):
    finished = Signal(str, str)
    ready_to_close = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="cloud-network")

    @Slot(str, str, str, str, str, str)
    def request(self, identifier, endpoint, method, path, body, token):
        self.pool.submit(self.fetch, identifier, endpoint, method, path, body, token)

    def fetch(self, identifier, endpoint, method, path, body, token):
        try:
            parsed = urlsplit(endpoint)
            local = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")
            if not (parsed.scheme == "https" or local) or parsed.username or parsed.password or parsed.query or parsed.fragment or not endpoint.endswith("/"):
                raise ValueError("服务器地址无效")
            if not re.fullmatch(r"api/[a-zA-Z0-9/?=&_-]+", path) or method not in ("GET", "POST"):
                raise ValueError("接口无效")
            data = body.encode() if method == "POST" else None
            if data and len(data) > 18 * 1024 * 1024:
                raise ValueError("请求过大")
            headers = {"Content-Type": "application/json"}
            if token:
                headers["Authorization"] = "Bearer " + token
            try:
                response = build_opener(ProxyHandler({}), NoRedirect()).open(Request(endpoint + path, data=data, headers=headers, method=method), timeout=30)
            except HTTPError as error:
                response = error
            with response:
                content = response.read(20 * 1024 * 1024 + 1)
                if len(content) > 20 * 1024 * 1024:
                    raise ValueError("响应过大")
                result = {"status": response.status, "body": json.loads(content)}
        except Exception as error:
            result = {"status": 503, "body": {"error": "连接失败，本地内容已保留：" + str(error)[:200]}}
        try:
            self.finished.emit(identifier, json.dumps(result, ensure_ascii=False))
        except RuntimeError:
            pass

    @Slot(str, str, str)
    def exportFile(self, name, mime, data):
        try:
            content = base64.b64decode(data, validate=True)
            if len(content) > 100 * 1024 * 1024:
                raise ValueError("导出文件过大")
            target, _ = QFileDialog.getSaveFileName(self.parent(), "保存导出文件", name, "所有文件 (*)")
            if target:
                Path(target).write_bytes(content)
        except Exception as error:
            QMessageBox.warning(self.parent(), "导出失败", str(error))

    @Slot(str)
    def openPath(self, value):
        path = Path(value)
        if path.exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
        else:
            QMessageBox.information(self.parent(), "位置不存在", "当前电脑没有这个位置：\n" + value)

    @Slot(result=str)
    def readClipboard(self):
        return QApplication.clipboard().text()

    @Slot(result=str)
    def readClipboardContent(self):
        clipboard=QApplication.clipboard()
        image=clipboard.image()
        result={"text":clipboard.text(),"images":[]}
        if not image.isNull():
            data=QByteArray()
            buffer=QBuffer(data)
            buffer.open(QIODevice.WriteOnly)
            image.save(buffer,"PNG")
            buffer.close()
            if data.size()>12*1024*1024:
                return json.dumps({"error":"剪贴板图片超过 12 MB"})
            result["images"].append({"name":"粘贴图片.png","mime":"image/png","data":base64.b64encode(bytes(data)).decode()})
        return json.dumps(result,ensure_ascii=False)

    @Slot(str)
    def writeClipboard(self, text):
        QApplication.clipboard().setText(text)

    @Slot()
    def readyToClose(self):
        self.ready_to_close.emit()
