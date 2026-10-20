from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKUP = ROOT / "Backups" / "云占用修复-4.2.1-20261020"


def fingerprints():
    return {
        str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
        for folder in (ROOT / "Markdown", ROOT / "Media")
        for path in folder.rglob("*") if path.is_file()
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", action="store_true")
    args = parser.parse_args()
    if args.snapshot:
        BACKUP.mkdir(exist_ok=False)
        for name in ("Markdown", "Media", "Data"):
            shutil.copytree(ROOT / name, BACKUP / name)
        shutil.copy2(ROOT / "dist/项目航图.exe", BACKUP / "项目航图-4.2.0.exe")
        (BACKUP / "fingerprints.json").write_text(json.dumps(fingerprints()), encoding="utf-8")
        print(json.dumps({"backup_created": True, "private_files": len(fingerprints())}))
    else:
        before = json.loads((BACKUP / "fingerprints.json").read_text(encoding="utf-8"))
        after = fingerprints()
        result = {"private_files_checked": len(before), "private_files_unchanged": before == after}
        print(json.dumps(result))
        if before != after:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
