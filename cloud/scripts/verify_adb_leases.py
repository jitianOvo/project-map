from __future__ import annotations

import argparse
import json
import tempfile
import threading
import time
import uuid
from pathlib import Path

from playwright.sync_api import sync_playwright
from verify_adb import Device, ROOT, wait
from server.auth import initialize, password_hash
from server.http import CloudServer
from project_map.cloud.api import Api, CloudError
from project_map.file_io import write_json

PACKAGE = "me.jitian.projectmap.leaseqa"
PASSWORD = "public-lease-test-only"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--retry-own-install", action="store_true")
    args = parser.parse_args()
    device = Device(args.serial, PACKAGE, "me.jitian.projectmap.MainActivity")
    existing = device.adb("shell", "pm", "path", PACKAGE, check=False)
    if existing and not args.retry_own_install:
        raise RuntimeError("测试包已存在，本脚本不接管或清空已有应用")
    if existing:
        details = device.adb("shell", "dumpsys", "package", PACKAGE)
        if "versionCode=40201" not in details or "DEBUGGABLE" not in details:
            raise RuntimeError("现有包不符合本轮公开测试安装，未使用或删除")
    qa = ROOT / ".cache" / "adb-lease-qa"
    qa.mkdir(parents=True, exist_ok=True)
    result = {"private_documents_used": False, "test_package": PACKAGE}
    installed = False
    browser = None
    with tempfile.TemporaryDirectory(prefix="project-map-lease-adb-") as folder:
        root = Path(folder)
        initialize(root)
        salt = "00" * 16
        write_json(root / ".secrets/account.json", {"username": "owner", "salt": salt, "hash": password_hash(PASSWORD, salt)})
        server = CloudServer(("127.0.0.1", 0), root)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        endpoint = f"http://127.0.0.1:{server.server_port}/"
        reverse = "tcp:" + str(server.server_port)
        api = Api(endpoint)
        print("正在准备隔离的公开服务", flush=True)
        api.token = api.request("api/login", {"username": "owner", "password": PASSWORD, "device_id": "Windows-public-test"})["token"]
        ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        for identifier, title in zip(ids, ("电脑正在编辑", "手机可单独编辑")):
            api.request("api/sync", {"id": identifier, "op_id": str(uuid.uuid4()), "base_revision": 0, "document": {"title": title, "content": "公开交接验证正文"}})
        pc = {"id": ids[0], "client_id": str(uuid.uuid4())}
        pc["lease_token"] = api.request("api/editor/open", pc)["lease_token"]
        try:
            print("正在安装独立测试包，不替换正式应用", flush=True)
            if not existing:
                device.adb("install", "-r", ROOT / ".cache/android-debug/project-map-debug.apk", timeout=120)
            installed = True
            device.adb("reverse", reverse, reverse)
            device.adb("shell", "input", "keyevent", "KEYCODE_WAKEUP")
            device.start()
            with sync_playwright() as playwright:
                browser, page = device.connect(playwright)
                print("已连接测试应用 WebView", flush=True)
                previous_endpoint = page.evaluate("JSON.parse(localStorage.getItem('project-map-preferences') || '{}').endpoint")
                if previous_endpoint and previous_endpoint.startswith("http://127.0.0.1:") and previous_endpoint != endpoint:
                    from urllib.parse import urlsplit
                    device.adb("reverse", "--remove", "tcp:" + str(urlsplit(previous_endpoint).port), check=False)
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.evaluate("endpoint=>localStorage.setItem('project-map-preferences',JSON.stringify({endpoint,mode:'edit',libraryHidden:true}))", endpoint)
                page.reload(wait_until="domcontentloaded")
                wait(page, "document.querySelector('#projectCount').textContent.includes('项目')")
                page.locator("#accountButton").click()
                page.locator("#dialogContent input[type=password]").fill(PASSWORD)
                page.locator("#dialogConfirm").click()
                wait(page, "document.querySelector('#accountButton').textContent==='账户'")
                page.locator("#syncButton").click()
                wait(page, "document.querySelectorAll('.project').length===2")
                page.locator("#toggleLibrary").click()
                page.locator(f".project[data-id='{ids[0]}']").click()
                wait(page, "document.querySelector('#editingMessage').textContent.includes('电脑端')")
                assert page.locator("#editor").is_disabled()
                device.screenshot(qa / "blocked.png")
                result["same_document_blocked"] = True
                print("同一大纲拦截已通过", flush=True)
                api.request("api/sync", {**pc, "op_id": str(uuid.uuid4()), "base_revision": 1,
                                        "document": {"title": "电脑正在编辑", "content": "电脑释放前的最新正文"}})
                api.request("api/editor/release", pc)
                wait(page, "!document.querySelector('#editor').readOnly && document.querySelector('#editor').value==='电脑释放前的最新正文'")
                result["waiting_phone_resumes_without_second_click"] = True
                page.locator(f".project[data-id='{ids[1]}']").click()
                wait(page, "!document.querySelector('#editor').readOnly && document.querySelector('#editor').value.includes('公开交接')")
                page.locator("#editor").fill("手机已更新的公开正文")
                page.locator("#endEditing").click()
                wait(page, "document.querySelector('#editingMessage').textContent.includes('本端已结束')")
                second = api.request("api/editor/open", {"id": ids[1], "client_id": str(uuid.uuid4())})
                assert second["document"]["content"] == "手机已更新的公开正文"
                result["different_documents_parallel"] = True
                result["latest_content_handoff"] = True
                print("不同大纲并行和正文交接已通过", flush=True)
                api.request("api/editor/release", pc)
                page.locator("#toggleLibrary").click()
                page.locator(f".project[data-id='{ids[0]}']").click()
                wait(page, "!document.querySelector('#editor').readOnly && document.querySelector('#editingMessage').textContent.includes('正在本端编辑')")
                page.locator("#editor").fill("进入后台前的公开草稿")
                device.adb("shell", "input", "keyevent", "KEYCODE_HOME")
                transferred = None
                deadline = time.monotonic() + 10
                while transferred is None and time.monotonic() < deadline:
                    try:
                        transferred = api.request("api/editor/open", pc)
                    except CloudError as error:
                        if error.status != 423: raise
                        time.sleep(0.15)
                assert transferred and transferred["document"]["content"] == "进入后台前的公开草稿"
                result["native_background_flush_and_release"] = True
                device.start()
                wait(page, "document.querySelector('#editingMessage').textContent.includes('电脑端')")
                api.request("api/editor/release", {**pc, "lease_token": transferred["lease_token"]})
                wait(page, "!document.querySelector('#editor').readOnly && document.querySelector('#editor').value==='进入后台前的公开草稿'")
                result["foreground_waiter_resumes_automatically"] = True
                assert errors == []
                result["page_errors"] = errors
                result["test_endpoint"] = endpoint
                write_json(qa / "result.json", result)
                print(json.dumps(result, ensure_ascii=False))
                browser.close()
                browser = None
        except Exception as error:
            print("公开真机测试未完成：" + str(error), flush=True)
            raise
        finally:
            if browser:
                try: browser.close()
                except Exception: pass
            device.cleanup()
            device.adb("reverse", "--remove", reverse, check=False)
            if installed:
                device.stop()
                device.adb("uninstall", PACKAGE)
            server.shutdown()
            thread.join(timeout=3)
            server.server_close()


if __name__ == "__main__":
    main()
