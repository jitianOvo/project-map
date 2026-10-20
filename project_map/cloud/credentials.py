from __future__ import annotations

import base64
import ctypes
import json
import os
from pathlib import Path

from ..file_io import read_json, write_json


class DataBlob(ctypes.Structure):
    _fields_ = [("size", ctypes.c_uint32), ("data", ctypes.POINTER(ctypes.c_ubyte))]


def windows_protect(value: bytes, decrypt=False):
    buffer = ctypes.create_string_buffer(value)
    source = DataBlob(len(value), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    destination = DataBlob()
    api = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not api(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(destination)):
        raise OSError("Windows 登录凭据保护失败")
    try:
        return ctypes.string_at(destination.data, destination.size)
    finally:
        ctypes.windll.kernel32.LocalFree(destination.data)


def save_token(path: Path, endpoint: str, token: str, username: str):
    save_account(path, endpoint, {"token": token, "username": username, "refresh_token": ""})


def save_account(path: Path, endpoint: str, account: dict):
    secret = json.dumps({"token": account.get("token", ""), "refresh_token": account.get("refresh_token", "")}).encode()
    protected = windows_protect(secret) if os.name == "nt" else secret
    write_json(path, {"endpoint": endpoint, "username": account.get("username", ""), "protected": os.name == "nt", "credentials": base64.b64encode(protected).decode()})
    if os.name != "nt":
        path.chmod(0o600)


def load_token(path: Path, endpoint: str):
    return load_account(path, endpoint).get("token", "")


def load_account(path: Path, endpoint: str):
    value = read_json(path)
    if value.get("endpoint") != endpoint:
        return {}
    try:
        raw = base64.b64decode(value.get("credentials", value.get("token", "")), validate=True)
        if value.get("protected"):
            raw = windows_protect(raw, decrypt=True)
        account = json.loads(raw) if "credentials" in value else {"token": raw.decode(), "refresh_token": ""}
        if not isinstance(account, dict) or any(not isinstance(account.get(key, ""), str) for key in ("token", "refresh_token")):
            return {}
        return {"token": account.get("token", ""), "refresh_token": account.get("refresh_token", ""), "username": value.get("username", "")}
    except (ValueError, OSError, UnicodeError):
        return {}
