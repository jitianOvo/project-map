from __future__ import annotations

import hashlib
import json
import re
import sys
import time
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from project_map.cloud.api import Api, CloudError, DEFAULT_ENDPOINT


def digest(api):
    documents, cursor = [], 0
    while True:
        page = api.request("api/changes?since=" + str(cursor))
        documents.extend(page["documents"])
        cursor = page["cursor"]
        if not page["has_more"]:
            return len(documents), hashlib.sha256(json.dumps(documents, sort_keys=True).encode()).hexdigest()


def main():
    secret = (ROOT.parent / "项目航图-云端/.secrets/云端首次登录.txt").read_text(encoding="utf-8")
    password = re.search(r"密码[:：]\s*(.+)", secret).group(1).strip()
    clients, refreshes = [], []
    claims = []
    try:
        for device in ("Windows-占用修复验收", "手机-占用修复验收"):
            account = Api(DEFAULT_ENDPOINT).request("api/login", {"username": "owner", "password": password, "device_id": device, "auto_login": True})
            clients.append(Api(DEFAULT_ENDPOINT, account["token"]))
            refreshes.append(account["refresh_token"])
        password = secret = None
        pc, phone = clients
        before = digest(pc)
        identifier = str(uuid.uuid4())
        request = {"id": identifier, "client_id": str(uuid.uuid4())}
        old = pc.request("api/editor/open", request)
        assert old["expires_in"] == 20 and old["heartbeat_in"] == 5
        current = pc.request("api/editor/open", {**request, "recover": True})
        proof = {**request, "lease_token": current["lease_token"]}
        claims.append((pc, proof))
        assert current["lease_token"] != old["lease_token"]
        pc.request("api/editor/release", {**request, "lease_token": old["lease_token"]})
        pc.request("api/editor/renew", proof)
        other = {"id": identifier, "client_id": str(uuid.uuid4())}
        try:
            phone.request("api/editor/open", other)
            raise AssertionError("另一端不应同时取得占用")
        except CloudError as error:
            assert error.status == 423 and error.details["owner"] == "电脑端"
        started = time.monotonic()
        pc.request("api/editor/release", proof)
        received = phone.request("api/editor/open", other)
        claims.append((phone, {**other, "lease_token": received["lease_token"]}))
        elapsed = time.monotonic() - started
        assert before == digest(pc)
        print(json.dumps({"version": pc.request("api/health")["version"], "same_installation_recovered": True,
                          "late_release_fenced": True, "other_device_blocked_until_release": True,
                          "release_to_handoff_seconds": round(elapsed, 3), "cloud_documents": before[0],
                          "cloud_documents_unchanged": True, "private_document_claimed_or_edited": False}, ensure_ascii=False))
    finally:
        for api, claim in claims:
            try: api.request("api/editor/release", claim)
            except CloudError: pass
        for refresh in refreshes:
            try: Api(DEFAULT_ENDPOINT).request("api/session/logout", {"refresh_token": refresh})
            except CloudError: pass


if __name__ == "__main__":
    main()
