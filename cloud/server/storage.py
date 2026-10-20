from __future__ import annotations

import json
from contextlib import closing
import sqlite3
import threading
import time
import uuid
from pathlib import Path

from .merge import merge_document
from .leases import DocumentLeases


FIELDS = {"content": "", "title": "新项目", "group": "默认项目", "description": "", "priority": "", "pinned": False, "order": 0, "deleted": False, "project_path": ""}


def normalize_document(document):
    if not isinstance(document, dict):
        raise ValueError("项目内容必须是对象")
    result = {key: document.get(key, default) for key, default in FIELDS.items()}
    for key in ("content", "title", "group", "description", "priority", "project_path"):
        if not isinstance(result[key], str):
            raise ValueError(f"{key} 必须是文字")
    if len(result["content"].encode("utf-8")) > 2 * 1024 * 1024:
        raise ValueError("单个大纲最多 2 MB")
    for key, limit in (("title", 200), ("group", 200), ("description", 4000), ("project_path", 2000)):
        if len(result[key]) > limit:
            raise ValueError(f"{key} 超出长度限制")
    result["title"] = result["title"].strip() or "未命名项目"
    result["group"] = result["group"].strip() or "默认项目"
    if result["priority"] not in ("", "urgent", "high", "normal"):
        raise ValueError("优先级无效")
    if type(result["pinned"]) is not bool or type(result["deleted"]) is not bool or type(result["order"]) is not int:
        raise ValueError("项目状态无效")
    return result


class Storage:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS counter (sequence INTEGER NOT NULL);
            INSERT INTO counter SELECT 0 WHERE NOT EXISTS (SELECT 1 FROM counter);
            CREATE TABLE IF NOT EXISTS documents (id TEXT PRIMARY KEY, revision INTEGER NOT NULL, sequence INTEGER NOT NULL, payload TEXT NOT NULL, updated REAL NOT NULL, device TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS revisions (id TEXT NOT NULL, revision INTEGER NOT NULL, payload TEXT NOT NULL, created REAL NOT NULL, PRIMARY KEY(id, revision));
            CREATE TABLE IF NOT EXISTS operations (id TEXT PRIMARY KEY, response TEXT NOT NULL, created REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (hash TEXT PRIMARY KEY, expires REAL NOT NULL, device TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS remembered_sessions (hash TEXT PRIMARY KEY, expires REAL NOT NULL, device TEXT NOT NULL, session_hash TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS editor_leases (id TEXT PRIMARY KEY, device TEXT NOT NULL, client TEXT NOT NULL, token TEXT NOT NULL, expires REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS documents_sequence ON documents(sequence);
        """)
        self.db.commit()
        self.leases = DocumentLeases(self)

    @staticmethod
    def unpack(row):
        return {"id": row["id"], "revision": row["revision"], "sequence": row["sequence"], "updated": row["updated"], "device": row["device"], **json.loads(row["payload"])}

    def write(self, document_id, payload, device):
        row = self.db.execute("SELECT revision FROM documents WHERE id=?", (document_id,)).fetchone()
        revision = row[0] + 1 if row else 1
        self.db.execute("UPDATE counter SET sequence=sequence+1")
        sequence = self.db.execute("SELECT sequence FROM counter").fetchone()[0]
        serialized = json.dumps(payload, ensure_ascii=False)
        now = time.time()
        self.db.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?)", (document_id, revision, sequence, serialized, now, device))
        self.db.execute("INSERT INTO revisions VALUES (?,?,?,?)", (document_id, revision, serialized, now))
        return self.unpack(self.db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone())

    def sync(self, request, authenticated_device=None):
        document_id = str(uuid.UUID(request["id"]))
        operation_id = str(uuid.UUID(request["op_id"]))
        device = str(request.get("device_id", "未知设备"))[:100]
        base_revision = request.get("base_revision", 0)
        if type(base_revision) is not int or base_revision < 0:
            raise ValueError("基础版本号无效")
        local = normalize_document(request["document"])
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                saved = self.db.execute("SELECT response FROM operations WHERE id=?", (operation_id,)).fetchone()
                if saved:
                    self.db.rollback()
                    return json.loads(saved[0])
                if authenticated_device is not None:
                    self.leases.check_write(request, authenticated_device)
                    device = authenticated_device
                row = self.db.execute("SELECT * FROM documents WHERE id=?", (document_id,)).fetchone()
                merged = local
                if row and row["revision"] != base_revision:
                    base = self.db.execute("SELECT payload FROM revisions WHERE id=? AND revision=?", (document_id, base_revision)).fetchone()
                    merged = merge_document(json.loads(base[0]), local, json.loads(row["payload"])) if base else None
                elif not row and base_revision:
                    raise ValueError("基础版本不存在")
                if merged is None:
                    copy_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "project-map-conflict:" + operation_id))
                    conflict = dict(local)
                    conflict["title"] = local["title"][:150] + " · 冲突副本"
                    conflict["deleted"] = False
                    conflict["description"] = f"来自 {device}，与项目 {document_id} 的同时修改未自动合并。"[:4000]
                    response = {"status": "conflict", "document": self.unpack(row), "conflict": self.write(copy_id, conflict, device)}
                else:
                    if row and merged == json.loads(row["payload"]):
                        result = self.unpack(row)
                    else:
                        result = self.write(document_id, merged, device)
                    response = {"status": "merged" if merged != local else "saved", "document": result}
                self.db.execute("INSERT INTO operations VALUES (?,?,?)", (operation_id, json.dumps(response, ensure_ascii=False), time.time()))
                self.db.commit()
                return response
            except Exception:
                self.db.rollback()
                raise

    def changes(self, since):
        with self.lock:
            rows = self.db.execute("SELECT * FROM documents WHERE sequence>? ORDER BY sequence LIMIT 201", (since,)).fetchall()
            selected = rows[:200]
            return {"documents": [self.unpack(row) for row in selected], "cursor": selected[-1]["sequence"] if selected else since, "has_more": len(rows) > 200}

    def history(self, document_id):
        with self.lock:
            return [{"revision": row["revision"], "created": row["created"], **json.loads(row["payload"])} for row in self.db.execute("SELECT * FROM revisions WHERE id=? ORDER BY revision DESC LIMIT 50", (document_id,))]

    def add_session(self, digest, device, refresh_digest=""):
        with self.lock:
            self.db.execute("DELETE FROM sessions WHERE expires<?", (time.time(),))
            self.db.execute("DELETE FROM remembered_sessions WHERE expires<?", (time.time(),))
            self.db.execute("INSERT INTO sessions VALUES (?,?,?)", (digest, time.time() + 30 * 86400, device[:100]))
            if refresh_digest:
                self.db.execute("INSERT INTO remembered_sessions VALUES (?,?,?,?)", (refresh_digest, time.time() + 180 * 86400, device[:100], digest))
            self.db.commit()

    def refresh_session(self, refresh_digest, digest):
        with self.lock, self.db:
            row = self.db.execute("SELECT * FROM remembered_sessions WHERE hash=? AND expires>?", (refresh_digest, time.time())).fetchone()
            if row is None:
                raise PermissionError("自动登录已失效，请重新输入账号和密码")
            self.db.execute("DELETE FROM sessions WHERE hash=?", (row["session_hash"],))
            self.db.execute("INSERT INTO sessions VALUES (?,?,?)", (digest, time.time() + 30 * 86400, row["device"]))
            self.db.execute("UPDATE remembered_sessions SET expires=?,session_hash=? WHERE hash=?", (time.time() + 180 * 86400, digest, refresh_digest))

    def session_valid(self, digest):
        with self.lock:
            return bool(self.db.execute("SELECT 1 FROM sessions WHERE hash=? AND expires>?", (digest, time.time())).fetchone())

    def session_device(self, digest):
        with self.lock:
            row = self.db.execute("SELECT device FROM sessions WHERE hash=? AND expires>?", (digest, time.time())).fetchone()
            return row["device"] if row else None

    def revoke_session(self, digest):
        with self.lock:
            self.db.execute("DELETE FROM remembered_sessions WHERE session_hash=?", (digest,))
            self.db.execute("DELETE FROM sessions WHERE hash=?", (digest,))
            self.db.commit()

    def revoke_remembered_session(self, digest):
        with self.lock, self.db:
            row = self.db.execute("SELECT session_hash FROM remembered_sessions WHERE hash=?", (digest,)).fetchone()
            if row:
                self.db.execute("DELETE FROM sessions WHERE hash=?", (row[0],))
            self.db.execute("DELETE FROM remembered_sessions WHERE hash=?", (digest,))

    def backup(self, target):
        with self.lock, closing(sqlite3.connect(target)) as backup:
            self.db.backup(backup)
