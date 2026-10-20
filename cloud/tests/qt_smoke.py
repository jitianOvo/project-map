from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT.parent / "项目航图"

with tempfile.TemporaryDirectory(prefix="unified-qt-") as directory:
    environment = dict(os.environ, QT_QPA_PLATFORM="offscreen", PROJECT_MAP_DATA_ROOT=directory, PYTHONUTF8="1")
    result = subprocess.run([sys.executable, str(LOCAL / "项目航图.py"), "--self-test"], cwd=LOCAL, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=30)
    if result.returncode:
        raise RuntimeError(result.stderr)
    value = json.loads((Path(directory) / "Data" / "self-test.json").read_text(encoding="utf-8"))
    print(json.dumps(value, ensure_ascii=False))
    assert value["ready"] and value["icon"] and not value["cloud_enabled"]
