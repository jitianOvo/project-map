from __future__ import annotations

import json
import shutil
import sys
import threading
import time
import unittest
from pathlib import Path

from PySide6.QtGui import QColor, QImage, QTextCursor
from PySide6.QtTest import QTest

from project_map.cloud.api import Api
from project_map.file_io import write_json
from project_map.locations import cloud_dir
from qt_test_support import APP
import test_workflow as workflow

SERVICE_SOURCE = cloud_dir(Path(__file__).resolve().parents[1])


@unittest.skipUnless((SERVICE_SOURCE / "server" / "http.py").is_file(), "跨端验证需要同级云服务源码")
class SyncContractTests(unittest.TestCase):
    def setUp(self):
        workflow.WindowTests.setUp(self)
        sys.path.insert(0, str(SERVICE_SOURCE))
        from server.auth import initialize, password_hash
        from server.http import CloudServer

        root = self.window.paths.root / "临时云服务"
        shutil.copytree(SERVICE_SOURCE / "server" / "public", root / "server" / "public")
        initialize(root)
        salt = "00" * 16
        write_json(root / ".secrets" / "account.json", {"username": "owner", "salt": salt, "hash": password_hash("contract-test-only", salt)})
        self.service = CloudServer(("127.0.0.1", 0), root)
        self.thread = threading.Thread(target=self.service.serve_forever, daemon=True)
        self.thread.start()
        self.endpoint = f"http://127.0.0.1:{self.service.server_port}/"
        self.window.cloud.poll.stop()

    def tearDown(self):
        self.service.shutdown()
        self.thread.join(timeout=5)
        self.service.server_close()
        sys.path.remove(str(SERVICE_SOURCE))
        workflow.WindowTests.tearDown(self)

    def wait_desktop(self):
        deadline = time.monotonic() + 15
        while self.window.cloud.busy and time.monotonic() < deadline:
            QTest.qWait(20)
            time.sleep(0.005)
        self.assertFalse(self.window.cloud.busy, self.window.cloud.status)
        self.assertTrue(self.window.cloud.status.startswith(("已同步", "登录成功")), self.window.cloud.status)
        self.window.cloud.timer.stop()

    def test_native_desktop_and_mobile_share_markdown_images_and_offline_edits(self):
        from playwright.sync_api import sync_playwright

        window = self.window
        window.editor.setPlainText("# 共享测试\n\n第一段：电脑原文\n\n第二段：手机原文\n\n")
        cursor = window.editor.textCursor()
        cursor.movePosition(QTextCursor.End)
        window.editor.setTextCursor(cursor)
        image = QImage(120, 80, QImage.Format_ARGB32)
        image.fill(QColor("#2563eb"))
        window.editor.insert_pasted_image(image)
        window.flush_auto_save()
        window.cloud.login(self.endpoint, "owner", "contract-test-only")
        self.wait_desktop()
        window.cloud.synchronize(force=True)
        self.wait_desktop()
        self.assertEqual(len(self.service.storage.changes(0)["documents"]), 1)
        window.cloud.editing.end_editing()
        self.wait_desktop()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(executable_path=r"C:\Program Files\Google\Chrome\Application\chrome.exe", headless=True)
            context = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True, has_touch=True)
            try:
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.add_init_script("localStorage.setItem('project-map-preferences',JSON.stringify({endpoint:" + json.dumps(self.endpoint) + "}));")
                page.goto(self.endpoint, wait_until="networkidle")
                page.wait_for_function("()=>document.querySelector('#projectCount').textContent.includes('项目')")
                page.locator("#accountButton").click()
                page.locator("#dialogContent input[type=password]").fill("contract-test-only")
                page.locator("#dialogConfirm").click()
                try:
                    page.wait_for_function("()=>document.querySelector('#accountButton').textContent==='账户'", timeout=10000)
                except Exception:
                    print("测试登录提示：", page.locator("#toast").inner_text(), flush=True)
                    raise
                page.locator("#syncButton").click()
                page.wait_for_function("()=>document.querySelectorAll('.project').length===1")
                project_rect = page.locator(".project").first.bounding_box()
                if project_rect is None or project_rect["x"] < 0:
                    page.locator("#toggleLibrary").click()
                page.locator(".project").first.click()
                page.wait_for_function("()=>document.querySelector('#editor').value.includes('第一段：电脑原文')")
                if not page.locator("#workspace").evaluate("element=>element.classList.contains('no-library')"):
                    page.locator("#toggleLibrary").click()
                page.wait_for_timeout(250)
                page.locator(".mode-buttons [data-mode=preview]").click()
                page.wait_for_function("()=>{const i=document.querySelector('#preview img');return i&&i.complete&&i.naturalWidth===120;}")
                self.assertEqual(page.locator("#preview img").count(), 1)
                self.assertTrue(page.locator("#workspace").evaluate("element=>element.classList.contains('no-library')"))
                page.locator(".mode-buttons [data-mode=edit]").click()
                phone_text = page.locator("#editor").input_value().replace("第二段：手机原文", "第二段：手机已修改")
                page.locator("#editor").fill(phone_text)
                page.wait_for_timeout(180)
                page.locator("#syncButton").click()
                deadline = time.monotonic() + 10
                while "手机已修改" not in self.service.storage.changes(0)["documents"][0]["content"] and time.monotonic() < deadline:
                    page.wait_for_timeout(100)
                window.cloud.synchronize(force=True)
                self.wait_desktop()
                self.assertIn("手机已修改", window.editor.toPlainText())
                self.assertIn("手机已修改", self.path.read_text(encoding="utf-8"))
                self.assertIn("file:///", window.preview.toHtml())

                window.cloud.save_config(enabled=False)
                window.editor.setPlainText(window.editor.toPlainText().replace("第一段：电脑原文", "第一段：电脑离线修改"))
                window.flush_auto_save()
                self.assertIn("电脑离线修改", self.path.read_text(encoding="utf-8"))
                phone_text = page.locator("#editor").input_value().replace("第二段：手机已修改", "第二段：手机同时修改")
                page.locator("#editor").fill(phone_text)
                page.wait_for_timeout(180)
                page.locator("#syncButton").click()
                deadline = time.monotonic() + 10
                while "手机同时修改" not in self.service.storage.changes(0)["documents"][0]["content"] and time.monotonic() < deadline:
                    page.wait_for_timeout(100)
                page.locator("#endEditing").click()
                page.wait_for_function("()=>document.querySelector('#editingMessage').textContent.includes('本端已结束')")
                window.cloud.synchronize(force=True)
                self.wait_desktop()
                merged = self.path.read_text(encoding="utf-8")
                self.assertIn("电脑离线修改", merged)
                self.assertIn("手机同时修改", merged)
                self.assertEqual(len(self.service.storage.changes(0)["documents"]), 1)
                page.locator("#syncButton").click()
                page.wait_for_function("()=>document.querySelector('#editor').value.includes('电脑离线修改')")
                self.assertFalse(errors)
                page.locator(".mode-buttons [data-mode=preview]").click()
                page.wait_for_function("()=>{const i=document.querySelector('#preview img');return i&&i.complete&&i.naturalWidth>0;}")
                qa = Path(__file__).resolve().parents[1] / ".cache" / "integration-qa"
                qa.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(qa / "mobile-shared-library.png"))
                window.grab().save(str(qa / "native-shared-library.png"))
            finally:
                context.close()
                browser.close()
