from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path


def integrated_executable():
    location = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else Path(__file__).resolve()
    for parent in location.parents:
        executable = parent / "项目航图" / "dist" / "项目航图.exe"
        if executable.is_file() and executable.resolve() != location:
            return executable
    return None


def main():
    executable = integrated_executable()
    if executable is None:
        message = "没有找到项目航图主程序，请先在项目航图\\dist 中生成项目航图.exe。Windows 功能已整合到主程序。"
        if sys.platform == "win32":
            ctypes.windll.user32.MessageBoxW(None, message, "项目航图", 0x40)
        else:
            print(message)
        return 1
    process = subprocess.Popen([str(executable), *sys.argv[1:]], cwd=executable.parent.parent)
    if any(argument in sys.argv for argument in ("--self-test", "--self-test-cloud")):
        return process.wait(timeout=35)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
