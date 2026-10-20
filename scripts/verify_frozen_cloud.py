from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from project_map.locations import cloud_dir

sys.path.insert(0, str(cloud_dir(ROOT)))
from server.auth import initialize, password_hash
from server.http import CloudServer
from project_map.file_io import write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--executable", type=Path, default=ROOT / "dist" / "项目航图.exe")
    options = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="project-map-cloud-contract-") as temporary:
        directory = Path(temporary)
        service_root = directory / "service"
        service_root.mkdir()
        initialize(service_root)
        salt = "00" * 16
        write_json(service_root / ".secrets" / "account.json", {"username": "owner", "salt": salt, "hash": password_hash("frozen-test-only", salt)})
        service = CloudServer(("127.0.0.1", 0), service_root)
        thread = threading.Thread(target=service.serve_forever, daemon=True)
        thread.start()
        try:
            workspace = directory / "workspace"
            (workspace / "Markdown").mkdir(parents=True)
            (workspace / "Media").mkdir()
            from PySide6.QtGui import QColor, QImage
            image = QImage(160, 90, QImage.Format_ARGB32)
            image.fill(QColor("#2563eb"))
            image_path = workspace / "Media" / "demo.png"
            assert image.save(str(image_path), "PNG")
            markdown = workspace / "Markdown" / "公开编译验证.md"
            markdown.write_text("# 公开验证\n\n单文件版与云同步共用大纲。\n\n![演示](Media/demo.png)", encoding="utf-8")
            login_file = directory / "test-account.json"
            write_json(login_file, {"endpoint": f"http://127.0.0.1:{service.server_port}/", "username": "owner", "password": "frozen-test-only"})
            environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", PYTHONUTF8="1", PROJECT_MAP_DATA_ROOT=str(workspace), PROJECT_MAP_TEST_LOGIN=str(login_file))
            startup = subprocess.STARTUPINFO()
            startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startup.wShowWindow = 0
            process = subprocess.run([str(options.executable.resolve()), "--self-test-cloud"], env=environment, cwd=ROOT, capture_output=True, timeout=35, startupinfo=startup)
            if process.returncode:
                raise RuntimeError("编译版退出异常：" + process.stderr.decode("utf-8", errors="replace"))
            result = json.loads((workspace / "Data" / "self-test.json").read_text(encoding="utf-8"))
            assert result["ready"] and result["icon"] and result["cloud_enabled"], result
            documents = service.storage.changes(0)["documents"]
            assert len(documents) == 1
            digest = hashlib.sha256(image_path.read_bytes()).hexdigest()
            assert "Media/" + digest + ".png" in documents[0]["content"]
            assert (service.media / digest).read_bytes() == image_path.read_bytes()
            result.update(cloud_document=True, cloud_image=True, single_file=True, private_files_used=False)
            qa = ROOT / ".cache" / "integration-qa"
            qa.mkdir(parents=True, exist_ok=True)
            write_json(qa / "frozen-cloud.json", result)
            print(json.dumps(result, ensure_ascii=False))
        finally:
            service.shutdown()
            thread.join(timeout=5)
            service.server_close()


if __name__ == "__main__":
    main()
