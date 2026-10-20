from pathlib import Path
import secrets
import sys

root = Path(__file__).resolve().parents[1]
directory = root / ".secrets"
directory.mkdir(exist_ok=True)
target = directory / "android-signing-password.txt"
if not target.exists():
    target.write_text(secrets.token_urlsafe(32), encoding="utf-8")
if "--read" in sys.argv:
    print(target.read_text(encoding="utf-8"))
