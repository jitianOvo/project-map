from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import tarfile
import time
from pathlib import Path, PurePosixPath
from urllib.request import urlopen


def run(*arguments):
    return subprocess.run(arguments, check=True, capture_output=True, text=True)


def document_digest(database):
    with sqlite3.connect(database) as connection:
        rows = connection.execute("SELECT id,revision,payload FROM documents ORDER BY id").fetchall()
    return len(rows), hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", required=True)
    parser.add_argument("--version", default="4.2.1", choices=("4.2.0", "4.2.1"))
    args = parser.parse_args()
    root = Path("/root/项目航图").resolve(strict=True)
    archive = Path(args.archive).resolve(strict=True)
    if not archive.is_relative_to(root / ".deploy"):
        raise RuntimeError("发布包不在项目自己的部署目录内")
    stage = root / ".deploy" / ("editing-" + args.version + "-stage")
    stage.mkdir(exist_ok=True)
    allowed = {"server", "deploy", "web", "android", "windows", "docs", "tests", "scripts", "README.md", "package.json", "package-lock.json", ".gitignore", "启动Windows云端版.bat"}
    files = []
    with tarfile.open(archive, "r:gz") as package:
        for member in package.getmembers():
            name = PurePosixPath(member.name)
            if name.is_absolute() or ".." in name.parts or not name.parts or name.parts[0] not in allowed or not member.isfile():
                raise RuntimeError("发布包成员越界或不是常规文件")
            target = stage.joinpath(*name.parts).resolve()
            if not target.is_relative_to(stage.resolve()):
                raise RuntimeError("发布目标越界")
            target.parent.mkdir(parents=True, exist_ok=True)
            with package.extractfile(member) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            files.append(Path(*name.parts))
    backup = root / ".deploy" / ("editing-" + args.version + "-" + time.strftime("%Y%m%d-%H%M%S"))
    backup.mkdir(mode=0o700)
    previous = []
    for relative in files:
        current = (root / relative).resolve()
        if not current.is_relative_to(root):
            raise RuntimeError("现有目标越界")
        if current.is_file():
            target = backup / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(current, target)
            previous.append(relative)
    database = root / "runtime/projects.sqlite3"
    run("systemctl", "stop", "project-map-cloud.service")
    before = document_digest(database)
    with sqlite3.connect(database) as source, sqlite3.connect(backup / "projects.sqlite3.before") as target:
        source.backup(target)
    try:
        for relative in files:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(stage / relative, target)
        run("systemctl", "start", "project-map-cloud.service")
        health = None
        for _ in range(30):
            try:
                with urlopen("http://127.0.0.1:18770/api/health", timeout=2) as response:
                    health = json.load(response)
                break
            except OSError:
                time.sleep(0.1)
        if not health or health.get("version") != args.version or not health.get("document_leases"):
            raise RuntimeError("新版服务健康检查未通过")
        after = document_digest(database)
        result = {"version": args.version, "backup": str(backup), "documents": after[0], "documents_unchanged": before == after,
                  "document_leases": True, "nginx_modified": False, "other_projects_modified": False}
        (backup / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False))
    except Exception:
        run("systemctl", "stop", "project-map-cloud.service")
        for relative in files:
            if relative in previous:
                shutil.copy2(backup / relative, root / relative)
            else:
                (root / relative).unlink(missing_ok=True)
        run("systemctl", "start", "project-map-cloud.service")
        raise


if __name__ == "__main__":
    main()
