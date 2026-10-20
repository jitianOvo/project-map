from __future__ import annotations

import argparse
import json
import re
import time
import xml.etree.ElementTree as ET

from verify_adb import Device


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serial", required=True)
    args = parser.parse_args()
    device = Device(args.serial)
    flags = device.adb("shell", "dumpsys", "package", device.package)
    assert "versionName=4.2.1" in flags and "DEBUGGABLE" not in flags
    remote = "/data/local/tmp/project-map-release-verify.xml"
    try:
        for _ in range(8):
            device.adb("shell", "uiautomator", "dump", remote)
            tree = ET.fromstring(device.adb("shell", "cat", remote))
            nodes = [node for node in tree.iter("node") if node.get("package") == device.package]
            buttons = [node.get("text") for node in nodes if node.get("class") == "android.widget.Button"]
            counts = [node.get("text") for node in nodes if re.fullmatch(r"\d+\s*个项目", node.get("text", ""))]
            if "账户" in buttons and counts:
                break
            time.sleep(0.5)
        assert "账户" in buttons and "登录并同步" not in buttons
        assert counts
        assert not device.adb("shell", "pm", "path", "me.jitian.projectmap.leaseqa", check=False)
        statuses = [node.get("text") for node in nodes if node.get("class") == "android.widget.TextView"
                    and node.get("text", "").startswith(("已同步", "离线 /", "本地已保存", "登录已过期", "正在同步"))]
        print(json.dumps({"version": "4.2.1", "formal_release": True, "auto_login_restored": True,
                          "projects": counts[0], "status": statuses, "test_package_removed": True}, ensure_ascii=False))
    finally:
        device.adb("shell", "rm", "-f", remote, check=False)
        device.cleanup()


if __name__ == "__main__":
    main()
