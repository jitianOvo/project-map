from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path


def password_hash(password: str, salt: str) -> str:
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()


def initialize(root: Path):
    directory = root / ".secrets"
    directory.mkdir(mode=0o700, exist_ok=True)
    account = directory / "account.json"
    if account.exists():
        return
    password = secrets.token_urlsafe(24)
    salt = secrets.token_hex(16)
    account.write_text(json.dumps({"username": "owner", "salt": salt, "hash": password_hash(password, salt)}), encoding="utf-8")
    login = directory / "首次登录.txt"
    login.write_text(f"项目航图云端首次登录\n账户：owner\n密码：{password}\n\n这是独立的应用账户，不是服务器 SSH 密码。请妥善保存，不要提交到仓库。\n", encoding="utf-8")
    for path in (account, login):
        os.chmod(path, 0o600)


class Authentication:
    def __init__(self, root, storage):
        initialize(root)
        self.account_path = root / ".secrets" / "account.json"
        self.storage = storage
        self.lock = threading.Lock()
        self.attempts = {}

    def login(self, request, address):
        username, password = request.get("username", ""), request.get("password", "")
        if not isinstance(username, str) or not isinstance(password, str) or len(password) > 1000:
            raise ValueError("账户或密码格式不正确")
        now = time.monotonic()
        with self.lock:
            self.attempts = {ip: values for ip, values in self.attempts.items() if values and values[-1] > now - 900}
            values = [stamp for stamp in self.attempts.get(address, []) if stamp > now - 900]
            if len(values) >= 10:
                raise PermissionError("尝试次数过多，请 15 分钟后再试")
            values.append(now)
            self.attempts[address] = values
        account = json.loads(self.account_path.read_text(encoding="utf-8"))
        valid = hmac.compare_digest(password_hash(password, account["salt"]), account["hash"])
        if not valid or not hmac.compare_digest(username, account["username"]):
            raise PermissionError("账户或密码不正确")
        token = secrets.token_urlsafe(32)
        remember = request.get("auto_login", False)
        if type(remember) is not bool:
            raise ValueError("自动登录选项格式不正确")
        refresh = secrets.token_urlsafe(48) if remember else ""
        self.storage.add_session(self.digest(token), str(request.get("device_id", "未知设备")), self.digest(refresh) if refresh else "")
        with self.lock:
            self.attempts.pop(address, None)
        return {"token": token, "expires_in": 30 * 86400, "refresh_token": refresh}

    def refresh(self, request):
        refresh = self.refresh_token(request)
        token = secrets.token_urlsafe(32)
        self.storage.refresh_session(self.digest(refresh), self.digest(token))
        return {"token": token, "expires_in": 30 * 86400}

    @staticmethod
    def refresh_token(request):
        value = request.get("refresh_token", "")
        if not isinstance(value, str) or not 32 <= len(value) <= 128:
            raise PermissionError("自动登录已失效，请重新输入账号和密码")
        return value

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def authorized(self, header):
        if not header.startswith("Bearer ") or len(header) > 200:
            return False
        return self.storage.session_valid(self.digest(header[7:]))
