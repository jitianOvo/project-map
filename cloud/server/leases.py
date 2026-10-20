from __future__ import annotations

import secrets
import time
import uuid


LEASE_SECONDS = 20
HEARTBEAT_SECONDS = 5


class LeaseConflict(Exception):
    def __init__(self, message, owner="", remaining=0):
        super().__init__(message)
        self.details = {"error": message, "owner": owner, "retry_after": max(1, int(remaining)), "code": "document_busy"}


class DocumentLeases:
    def __init__(self, storage):
        self.storage = storage

    @staticmethod
    def identity(request):
        document = str(uuid.UUID(request["id"]))
        client = str(uuid.UUID(request["client_id"]))
        return document, client

    @staticmethod
    def blocked(row, now):
        owner = row["device"]
        label = "电脑端" if owner.startswith(("Windows", "电脑")) else "手机端" if owner.startswith(("手机", "Android")) else "另一端"
        return LeaseConflict(f"这份大纲正在{label}编辑，释放后将自动接续。异常退出后最多等待 {LEASE_SECONDS} 秒。", label, row["expires"] - now)

    def open(self, request, device):
        document, client = self.identity(request)
        db = self.storage.db
        now = time.time()
        with self.storage.lock, db:
            db.execute("DELETE FROM editor_leases WHERE expires<=?", (now,))
            row = db.execute("SELECT * FROM editor_leases WHERE id=?", (document,)).fetchone()
            if row and (row["device"] != device or row["client"] != client):
                raise self.blocked(row, now)
            token = row["token"] if row and not request.get("recover") else secrets.token_urlsafe(32)
            db.execute("INSERT OR REPLACE INTO editor_leases VALUES (?,?,?,?,?)", (document, device, client, token, now + LEASE_SECONDS))
            latest = db.execute("SELECT * FROM documents WHERE id=?", (document,)).fetchone()
            return {"id": document, "lease_token": token, "expires_in": LEASE_SECONDS, "heartbeat_in": HEARTBEAT_SECONDS,
                    "document": self.storage.unpack(latest) if latest else None}

    def renew(self, request, device):
        document, client = self.identity(request)
        now = time.time()
        with self.storage.lock, self.storage.db:
            row = self.storage.db.execute("SELECT * FROM editor_leases WHERE id=?", (document,)).fetchone()
            self.check(row, request, device, now)
            self.storage.db.execute("UPDATE editor_leases SET expires=? WHERE id=?", (now + LEASE_SECONDS, document))
        return {"expires_in": LEASE_SECONDS}

    def release(self, request, device):
        document, client = self.identity(request)
        with self.storage.lock, self.storage.db:
            self.storage.db.execute("DELETE FROM editor_leases WHERE id=? AND device=? AND client=? AND token=?",
                                    (document, device, client, request.get("lease_token", "")))
        return {"ok": True}

    def check(self, row, request, device, now=None):
        now = time.time() if now is None else now
        if not row or row["expires"] <= now:
            raise LeaseConflict("编辑占用已失效，内容已保留在本机；请重新打开大纲后继续。")
        if row["device"] != device or row["client"] != request.get("client_id") or not secrets.compare_digest(row["token"], str(request.get("lease_token", ""))):
            raise self.blocked(row, now)

    def check_write(self, request, device):
        row = self.storage.db.execute("SELECT * FROM editor_leases WHERE id=?", (request["id"],)).fetchone()
        if request.get("client_id") or (row and row["expires"] > time.time()):
            self.check(row, request, device)
