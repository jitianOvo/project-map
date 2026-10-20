from __future__ import annotations

import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

from playwright.sync_api import sync_playwright
from websockets.sync.client import connect as websocket_connect
from websockets.sync.server import serve as websocket_serve

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent / "项目航图"))
from server.auth import initialize, password_hash
from server.http import CloudServer
from project_map.cloud.api import Api
from project_map.cloud.credentials import save_account
from project_map.file_io import write_json

ADB = Path(os.environ.get("PROJECT_MAP_ADB", r"D:\桌面\Work\AI-Agent-Pro\逆向分析\platform-tools\platform-tools\adb.exe"))
PACKAGE = "me.jitian.projectmap"
PASSWORD = "adb-public-fixture-only"
PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg==")


class WebViewProxy:
    def __init__(self, remote):
        def handle(client):
            with websocket_connect(remote, max_size=None) as upstream:
                def receive():
                    try:
                        for value in upstream:
                            client.send(value)
                    except Exception:
                        pass
                thread = threading.Thread(target=receive, daemon=True)
                thread.start()
                try:
                    for value in client:
                        message = json.loads(value)
                        # WebView 没有浏览器下载目录；这里只跳过测试框架的目录初始化。
                        if message.get("method") == "Browser.setDownloadBehavior":
                            client.send(json.dumps({"id": message["id"], "result": {}}))
                        else:
                            upstream.send(value)
                except Exception:
                    pass
        self.server = websocket_serve(handle, "127.0.0.1", 0, max_size=None)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = "ws://127.0.0.1:" + str(self.server.socket.getsockname()[1])

    def close(self):
        self.server.shutdown()
        self.thread.join(timeout=3)


class Device:
    def __init__(self, serial, package=PACKAGE, activity=".MainActivity"):
        self.serial = serial
        self.package, self.activity = package, activity
        self.forwards = []
        self.proxies = []

    def adb(self, *args, binary=False, check=True, timeout=40):
        result = subprocess.run([str(ADB), "-s", self.serial, *map(str, args)], capture_output=True, timeout=timeout)
        if check and result.returncode:
            raise RuntimeError("ADB 操作未完成：" + result.stderr.decode("utf-8", errors="replace")[:400])
        return result.stdout if binary else result.stdout.decode("utf-8", errors="replace").strip()

    def start(self):
        self.adb("shell", "am", "start", "-n", self.package + "/" + self.activity)

    def stop(self):
        self.adb("shell", "am", "force-stop", self.package)

    def connect(self, playwright):
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            pid = self.adb("shell", "pidof", self.package, check=False)
            sockets = self.adb("shell", "cat", "/proc/net/unix")
            name = "webview_devtools_remote_" + pid.split()[0] if pid else ""
            if name and name in sockets:
                port = self.adb("forward", "tcp:0", "localabstract:" + name)
                self.forwards.append(port)
                try:
                    with build_opener(ProxyHandler({})).open("http://127.0.0.1:" + port + "/json/version", timeout=5) as response:
                        remote = json.load(response)["webSocketDebuggerUrl"]
                    proxy = WebViewProxy(remote)
                    self.proxies.append(proxy)
                    browser = playwright.chromium.connect_over_cdp(proxy.url, timeout=10000)
                    page = next(page for context in browser.contexts for page in context.pages if "appassets.androidplatform.net" in page.url)
                    page.wait_for_load_state("load", timeout=20000)
                    wait(page, "document.querySelector('#projectCount').textContent.includes('项目')")
                    return browser, page
                except Exception as error:
                    self.adb("forward", "--remove", "tcp:" + port, check=False)
                    raise RuntimeError("连接本应用 WebView 失败：" + str(error)) from error
            time.sleep(0.15)
        raise RuntimeError("没有连接到本应用的调试 WebView")

    def screenshot(self, path):
        path.write_bytes(self.adb("exec-out", "screencap", "-p", binary=True))

    def bounds(self):
        remote = "/data/local/tmp/project-map-qa-" + uuid.uuid4().hex + ".xml"
        try:
            self.adb("shell", "uiautomator", "dump", remote)
            tree = ET.fromstring(self.adb("shell", "cat", remote))
            node = next(node for node in tree.iter("node") if node.get("class") == "android.webkit.WebView" and node.get("package") == self.package)
            return list(map(int, re.findall(r"\d+", node.attrib["bounds"])))
        finally:
            self.adb("shell", "rm", remote, check=False)

    def tap(self, page, selector):
        box = page.locator(selector).bounding_box()
        if box is None:
            raise RuntimeError("待测试控件不可见：" + selector)
        left, top, right, _bottom = self.bounds()
        scale = (right - left) / page.evaluate("innerWidth")
        self.adb("shell", "input", "tap", round(left + (box["x"] + box["width"] / 2) * scale), round(top + (box["y"] + box["height"] / 2) * scale))

    def cleanup(self):
        for proxy in self.proxies:
            proxy.close()
        for port in self.forwards:
            self.adb("forward", "--remove", "tcp:" + port, check=False)


def wait(page, expression, timeout=20000):
    session = page.context.new_cdp_session(page)
    expression = "(" + expression + ")()" if expression.startswith("()") else expression
    deadline = time.monotonic() + timeout / 1000
    while time.monotonic() < deadline:
        result = session.send("Runtime.evaluate", {"expression": expression, "returnByValue": True, "allowUnsafeEvalBlockedByCSP": True})
        if result.get("result", {}).get("value"):
            return
        page.wait_for_timeout(100)
    raise RuntimeError("真机界面等待超时：" + expression)


def wait_sync(page):
    wait(page, "document.querySelector('#syncStatus').textContent.startsWith('已同步')", timeout=40000)


def sign_in(page, remember=True):
    page.locator("#accountButton").click()
    page.locator("#dialogContent input[type=password]").fill(PASSWORD)
    page.locator("#dialogContent input[type=checkbox]").set_checked(remember)
    page.locator("#dialogConfirm").click()
    wait(page, "document.querySelector('#accountButton').textContent === '账户'", timeout=15000)
    wait_sync(page)


def restart(device, playwright, browser):
    browser.close()
    device.stop()
    device.start()
    return device.connect(playwright)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--apk", type=Path, default=ROOT / ".cache/android-debug/project-map-debug.apk")
    parser.add_argument("--desktop-executable", type=Path)
    parser.add_argument("--retry-own-install", action="store_true")
    options = parser.parse_args()
    device = Device(options.serial)
    qa = ROOT / ".cache/adb-qa"
    qa.mkdir(parents=True, exist_ok=True)
    result = {"device": options.serial, "android_sdk": device.adb("shell", "getprop", "ro.build.version.sdk"), "private_documents_used": False}
    result["previously_installed"] = bool(device.adb("shell", "pm", "path", PACKAGE, check=False))
    result["retry_of_own_test_install"] = options.retry_own_install
    if result["previously_installed"] and not options.retry_own_install:
        raise RuntimeError("设备已经安装了应用，请先核对已有数据；本脚本不清除或改用它的资料")
    with tempfile.TemporaryDirectory(prefix="project-map-adb-") as temporary:
        workspace = Path(temporary)
        shutil.copytree(ROOT / "server/public", workspace / "server/public")
        initialize(workspace)
        salt = "00" * 16
        write_json(workspace / ".secrets/account.json", {"username": "owner", "salt": salt, "hash": password_hash(PASSWORD, salt)})
        server = CloudServer(("127.0.0.1", 0), workspace)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        reverse = "tcp:" + str(server.server_port)
        endpoint = "http://127.0.0.1:" + str(server.server_port) + "/"
        browser = None
        try:
            device.adb("install", "-r", options.apk.resolve())
            device.adb("reverse", reverse, reverse)
            device.adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
            device.start()
            with sync_playwright() as playwright:
                browser, page = device.connect(playwright)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.evaluate("endpoint => localStorage.setItem('project-map-preferences', JSON.stringify({endpoint,mode:'edit',libraryHidden:true}))", endpoint)
                page.reload(wait_until="domcontentloaded")
                wait(page, "document.querySelector('#projectCount').textContent.includes('项目')")
                page.locator("#emptyNew").click()
                page.locator("#dialogContent input").first.fill("ADB 公开功能验证")
                page.locator("#dialogConfirm").click()
                wait(page, "!document.querySelector('#editor').disabled")
                original = "# 真机公开演示\n\n第一段\n第二段\n第三段\n\n1. 手机工作"
                page.locator("#editor").fill(original)
                page.locator("#editor").press("Control+End")
                device.adb("shell", "input", "keyevent", "66")
                wait(page, "document.querySelector('#editor').value.endsWith('2. ')")
                result["native_enter_numbered_list"] = True
                page.locator("#editor").fill(original)
                page.wait_for_timeout(200)
                page.locator("#accountButton").click()
                assert page.locator("#dialogContent input[type=checkbox]").is_checked()
                page.locator("#dialogContent input[type=password]").click()
                page.wait_for_timeout(100)
                page.locator("#dialogContent input[type=password]").focus()
                wait(page, "document.activeElement?.type === 'password'")
                device.adb("shell", "input", "text", PASSWORD)
                assert page.locator("#dialogContent input[type=password]").input_value() == PASSWORD
                device.adb("shell", "input", "keyevent", "111")
                device.tap(page, "#dialogConfirm")
                wait(page, "document.querySelector('#accountButton').textContent === '账户'", timeout=15000)
                wait_sync(page)
                result["adb_password_and_login_tap"] = True
                account = json.loads(page.evaluate("endpoint => AndroidBridge.readLogin(endpoint)", endpoint))
                encrypted = device.adb("shell", "run-as", PACKAGE, "cat", "shared_prefs/project-map-login.xml")
                assert account["token"] not in encrypted and account["refresh_token"] not in encrypted and PASSWORD not in encrypted
                assert page.evaluate("() => Object.keys(localStorage).every(key => !key.startsWith('project-map-token:') && !key.startsWith('project-map-login:'))")
                result["native_keystore_encrypted"] = True
                page.locator("#imageInput").set_input_files({"name": "公开测试.png", "mimeType": "image/png", "buffer": PNG})
                page.locator(".mode-buttons [data-mode=preview]").click()
                wait(page, "() => {const image=document.querySelector('#preview img');return image?.complete&&image.naturalWidth>0}")
                page.locator("#preview img").dblclick()
                wait(page, "document.querySelector('#lightbox').open")
                before = page.locator("#largeImage").bounding_box()["width"]
                page.locator("#imageZoomIn").click()
                assert page.locator("#largeImage").bounding_box()["width"] > before
                page.locator("#imageClose").click()
                result["image_preview_viewer_and_zoom"] = True
                page.locator(".mode-buttons [data-mode=edit]").click()
                wait_sync(page)
                browser, page = restart(device, playwright, browser)
                wait_sync(page)
                assert page.locator("#accountButton").inner_text() == "账户"
                assert "真机公开演示" in page.locator("#editor").input_value()
                result["force_stop_auto_login_and_document_restore"] = True
                with server.storage.lock, server.storage.db:
                    server.storage.db.execute("UPDATE sessions SET expires=0")
                browser, page = restart(device, playwright, browser)
                wait_sync(page)
                renewed = json.loads(page.evaluate("endpoint => AndroidBridge.readLogin(endpoint)", endpoint))
                assert renewed["token"] != account["token"]
                result["expired_session_renewed_without_password"] = True
                device.adb("reverse", "--remove", reverse)
                page.locator("#editor").fill(page.locator("#editor").input_value() + "\n断网中文与 Emoji 😀 修改")
                page.wait_for_timeout(300)
                device.adb("shell", "input", "keyevent", "3")
                device.start()
                browser, page = restart(device, playwright, browser)
                assert "断网中文" in page.locator("#editor").input_value()
                assert page.locator("#accountButton").inner_text() == "账户"
                device.adb("reverse", reverse, reverse)
                page.locator("#syncButton").click()
                wait_sync(page)
                assert "断网中文" in server.storage.changes(0)["documents"][0]["content"]
                result["background_offline_edit_restart_and_reconnect"] = True
                docs = server.storage.changes(0)["documents"]
                document = docs[0]
                pc_content = document["content"].replace("第一段", "电脑修改第一段")
                server.storage.sync({"id": document["id"], "op_id": str(uuid.uuid4()), "base_revision": document["revision"], "device_id": "电脑测试", "document": {**document, "content": pc_content}})
                page.locator("#syncButton").click()
                wait(page, "document.querySelector('#editor').value.includes('电脑修改第一段')")
                result["computer_to_real_phone_sync"] = True
                # 新统一 Windows 单文件程序使用独立目录读取真机刚同步的内容。
                desktop = workspace / "desktop"
                write_json(desktop / "Data/cloud/config.json", {"endpoint": endpoint, "username": "owner", "enabled": True, "auto_login": True})
                pc_account = Api(endpoint).request("api/login", {"username": "owner", "password": PASSWORD, "auto_login": True, "device_id": "电脑编译测试"})
                save_account(desktop / "Data/cloud/account.json", endpoint, {**pc_account, "username": "owner"})
                if options.desktop_executable:
                    environment = dict(os.environ, PROJECT_MAP_DATA_ROOT=str(desktop), QT_QPA_PLATFORM="offscreen", PYTHONUTF8="1")
                    startup = subprocess.STARTUPINFO()
                    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
                    startup.wShowWindow = 0
                    def desktop_cycle():
                        call = subprocess.run([str(options.desktop_executable.resolve()), "--self-test-auto-login"], env=environment, capture_output=True, startupinfo=startup, timeout=35)
                        assert call.returncode == 0, "电脑编译版测试没有正常退出"
                        report = json.loads((desktop / "Data/self-test.json").read_text(encoding="utf-8"))
                        assert report["ready"] and report["session_restored"] and report["auto_login"], report
                    desktop_cycle()
                    markdown = next((desktop / "Markdown").glob("*.md"))
                    assert "断网中文" in markdown.read_text(encoding="utf-8")
                    markdown.write_text(markdown.read_text(encoding="utf-8") + "\n电脑自动登录后编辑", encoding="utf-8")
                    with server.storage.lock, server.storage.db:
                        server.storage.db.execute("UPDATE sessions SET expires=0 WHERE hash=?", (server.auth.digest(pc_account["token"]),))
                    desktop_cycle()
                    page.locator("#syncButton").click()
                    wait(page, "document.querySelector('#editor').value.includes('电脑自动登录后编辑')")
                    result["compiled_desktop_auto_login_renewal_and_real_phone_sync"] = True
                device.screenshot(qa / "android-editor.png")
                page.locator(".mode-buttons [data-mode=preview]").click()
                device.screenshot(qa / "android-preview.png")
                page.locator("#accountButton").click()
                page.locator("#dialogConfirm").click()
                wait(page, "document.querySelector('#accountButton').textContent === '登录'")
                browser, page = restart(device, playwright, browser)
                assert page.locator("#accountButton").inner_text() == "登录"
                assert "断网中文" in page.locator("#editor").input_value()
                result["logout_survives_restart_without_deleting_docs"] = True
                sign_in(page, False)
                browser, page = restart(device, playwright, browser)
                assert page.locator("#accountButton").inner_text() == "登录"
                result["unchecked_login_does_not_restore"] = True
                assert not errors, errors
                result["page_errors"] = errors
                device.screenshot(qa / "android-logged-out.png")
                browser.close()
                browser = None
            write_json(qa / "result.json", {key: value for key, value in result.items() if key not in {"fixture_endpoint", "desktop_workspace"}})
            print(json.dumps({key: value for key, value in result.items() if key not in {"fixture_endpoint", "desktop_workspace"}}, ensure_ascii=False))
        finally:
            if browser:
                try:
                    browser.close()
                except Exception:
                    pass
            device.adb("reverse", "--remove", reverse, check=False)
            device.cleanup()
            server.shutdown()
            thread.join(timeout=5)
            server.server_close()


if __name__ == "__main__":
    main()
