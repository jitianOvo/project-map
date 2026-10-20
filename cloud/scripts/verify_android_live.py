from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

from verify_adb import Device, PACKAGE, ROOT, wait, restart

sys.path.insert(0, str(ROOT.parent / "项目航图"))
from project_map.cloud.api import Api
from project_map.file_io import write_json

ENDPOINT = "https://jitian666.me/project-map/"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    parser.add_argument("--clear-owned-test-cache", action="store_true", required=True)
    args = parser.parse_args()
    device = Device(args.serial)
    qa = ROOT / ".cache/adb-qa"
    test_result = json.loads((qa / "result.json").read_text(encoding="utf-8"))
    if test_result["device"] != args.serial or test_result["private_documents_used"]:
        raise RuntimeError("没有该设备本轮公开测试的证据，不清除应用资料")
    browser = None
    phase = "检查测试安装"
    try:
        device.start()
        with sync_playwright() as playwright:
            browser, page = device.connect(playwright)
            current = page.evaluate("JSON.parse(localStorage.getItem('project-map-preferences') || '{}').endpoint")
            if not current or not current.startswith("http://127.0.0.1:"):
                raise RuntimeError("应用已切换到非测试资料，不清除缓存")
            browser.close()
            browser = None
            phase = "清理本轮公开测试缓存"
            device.stop()
            try:
                cleared = device.adb("shell", "pm", "clear", PACKAGE) == "Success"
            except RuntimeError:
                cleared = False
            if not cleared:
                directory = device.adb("shell", "run-as", PACKAGE, "pwd")
                if directory != "/data/user/0/" + PACKAGE:
                    raise RuntimeError("应用自己的缓存目录核验失败，未移动数据")
                backup = directory + "/app_webview-public-test-before-4.1.0"
                exists = device.adb("shell", "run-as", PACKAGE, "ls", "-d", backup, check=False)
                if exists:
                    raise RuntimeError("已有公开测试缓存备份，未覆盖")
                device.adb("shell", "run-as", PACKAGE, "mv", directory + "/app_webview", backup)
                device.adb("shell", "run-as", PACKAGE, "mv", directory + "/shared_prefs/project-map-login.xml", directory + "/shared_prefs/project-map-login-public-test.xml")
            device.start()
            phase = "正式服务器首次登录"
            browser, page = device.connect(playwright)
            page.locator("#accountButton").click()
            login = (ROOT / ".secrets/云端首次登录.txt").read_text(encoding="utf-8")
            username = re.search(r"账户：(.*)", login).group(1).strip()
            password = re.search(r"密码：(.*)", login).group(1).strip()
            page.locator("#dialogContent input[type=text]").fill(username)
            page.locator("#dialogContent input[type=password]").fill(password)
            page.locator("#dialogConfirm").click()
            password = login = None
            wait(page, "document.querySelector('#accountButton').textContent === '账户'", 20000)
            wait(page, "document.querySelector('#syncStatus').textContent.startsWith('已同步')", 45000)
            account = json.loads(page.evaluate("endpoint => AndroidBridge.readLogin(endpoint)", ENDPOINT))
            documents = Api(ENDPOINT, account["token"]).request("api/changes?since=0")["documents"]
            count = len([document for document in documents if not document["deleted"]])
            browser, page = restart(device, playwright, browser)
            phase = "正式账号重启恢复"
            wait(page, "document.querySelector('#syncStatus').textContent.startsWith('已同步')", 45000)
            assert page.locator("#accountButton").inner_text() == "账户"
            count_text = page.locator("#projectCount").inner_text()
            assert str(count) in count_text
            browser.close()
            browser = None
        device.stop()
        phase = "正式 APK 覆盖安装"
        device.adb("install", "-r", (ROOT / "dist/project-map.apk").resolve())
        device.start()
        flags = device.adb("shell", "dumpsys", "package", PACKAGE)
        assert "DEBUGGABLE" not in flags
        pid = device.adb("shell", "pidof", PACKAGE)
        sockets = device.adb("shell", "cat", "/proc/net/unix")
        assert "webview_devtools_remote_" + pid.split()[0] not in sockets
        result = {
            "version": "4.1.0", "actual_server_https_login": True,
            "remembered_after_restart": True, "cloud_projects_received": count,
            "existing_cloud_documents_modified": False, "test_cache_cleared": True,
            "test_cache_recoverably_isolated": not cleared,
            "release_installed": True, "release_debugging_disabled": True,
            "credentials_printed": False,
        }
        write_json(qa / "live-result.json", result)
        print(json.dumps(result, ensure_ascii=False))
    except Exception as error:
        raise RuntimeError("正式客户端验证未完成：" + phase + " / " + type(error).__name__ + "；不输出账号密码，请检查应用提示") from None
    finally:
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        device.cleanup()


if __name__ == "__main__":
    main()
