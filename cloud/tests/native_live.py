from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT.parent / "项目航图"
executable = ROOT / "dist/windows/项目航图-云端/项目航图-云端.exe"
subprocess.run([sys.executable, str(LOCAL / "scripts/verify_frozen_cloud.py"), "--executable", str(executable)], cwd=LOCAL, check=True)
