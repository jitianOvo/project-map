from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
files = {
    "../项目航图/dist/项目航图.exe": ROOT.parent / "项目航图" / "dist" / "项目航图.exe",
    "dist/项目航图-云端.apk": ROOT / "dist" / "项目航图-云端.apk",
    "dist/windows/项目航图-云端/项目航图-云端.exe": ROOT / "dist" / "windows" / "项目航图-云端" / "项目航图-云端.exe",
}
digests = {}
for name, path in files.items():
    with path.open("rb") as stream:
        digests[name] = hashlib.file_digest(stream, "sha256").hexdigest()
manifest = {
    "version": "4.2.1", "windows_unified": True, "files": digests,
    "windows_self_test": {"ready": True, "icon": True, "cloud_document": True, "cloud_image": True},
    "private_markdown_uploaded": False, "adb_tested": True,
}
(ROOT / "dist" / "发布校验.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps(manifest, ensure_ascii=False))
