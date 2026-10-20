from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from project_map.cloud.api import Api, DEFAULT_ENDPOINT


def main():
    source = ROOT.parent / "项目航图-云端" / ".secrets" / "云端首次登录.txt"
    info = source.read_text(encoding="utf-8")
    password = re.search(r"密码[:：]\s*(.+)", info).group(1).strip()
    api = Api(DEFAULT_ENDPOINT)
    health = api.request("api/health")
    session = api.request("api/login", {"username": "owner", "password": password, "device_id": "Windows-连接验证"})
    api.token = session["token"]
    try:
        projects = api.request("api/changes?since=0")
        value = {"health": health, "authenticated": True, "project_count_first_page": len(projects["documents"]), "private_markdown_uploaded": False}
        print(json.dumps(value, ensure_ascii=False))
    finally:
        api.request("api/logout", {})


if __name__ == "__main__":
    main()
