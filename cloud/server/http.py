from __future__ import annotations

import base64
import hashlib
import json
import logging
import mimetypes
import os
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .auth import Authentication
from .storage import Storage
from .leases import LeaseConflict, LEASE_SECONDS, HEARTBEAT_SECONDS


MEDIA_ID = re.compile(r"^[a-f0-9]{64}$")
MAX_BODY = 18 * 1024 * 1024
VERSION = "4.2.1"


def image_type(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    raise ValueError("只支持 PNG、JPEG、GIF、WebP 图片")


class CloudServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, address, root):
        self.root = Path(root).resolve()
        self.runtime = self.root / "runtime"
        self.runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.media = self.runtime / "media"
        self.media.mkdir(mode=0o700, exist_ok=True)
        self.storage = Storage(self.runtime / "projects.sqlite3")
        self.auth = Authentication(self.root, self.storage)
        self.last_backup = 0
        self.slots = threading.BoundedSemaphore(8)
        super().__init__(address, Handler)

    def process_request(self, request, address):
        self.slots.acquire()
        try:
            super().process_request(request, address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            self.slots.release()

    def daily_backup(self):
        with self.storage.lock:
            if time.time() - self.last_backup < 86400:
                return
            backups = self.runtime / "backups"
            backups.mkdir(mode=0o700, exist_ok=True)
            self.storage.backup(backups / (time.strftime("%Y-%m-%d") + ".sqlite3"))
            self.last_backup = time.time()

    def server_close(self):
        super().server_close()
        self.storage.db.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "ProjectMap"

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def log_message(self, format, *args):
        logging.info("%s %s", self.client_address[0], format % args)

    def reply(self, status, payload, mime="application/json; charset=utf-8"):
        data = json.dumps(payload, ensure_ascii=False).encode() if not isinstance(payload, bytes) else payload
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store" if mime.startswith("application/json") else "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        if mime.startswith("text/html"):
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' qrc:; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data: https:; connect-src 'self' https: http://127.0.0.1:*; object-src 'none'; frame-src 'none'; base-uri 'none'")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def body(self, limit=MAX_BODY):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= limit:
            raise ValueError("请求为空或超过大小限制")
        value = json.loads(self.rfile.read(length))
        if not isinstance(value, dict):
            raise ValueError("请求格式不正确")
        return value

    def do_GET(self):
        self.handle_request()

    def do_HEAD(self):
        self.handle_request()

    def do_POST(self):
        self.handle_request()

    def handle_request(self):
        try:
            self.route()
        except LeaseConflict as error:
            self.reply(423, error.details)
        except (ValueError, KeyError, TypeError, UnicodeError) as error:
            self.reply(400, {"error": str(error)[:300]})
        except PermissionError as error:
            self.reply(401, {"error": str(error)})
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            pass
        except Exception:
            logging.exception("请求处理失败")
            self.reply(500, {"error": "服务器处理失败；你的本地内容仍保留，请稍后重试"})

    def route(self):
        parsed = urlsplit(self.path)
        path = unquote(parsed.path)
        read = self.command in ("GET", "HEAD")
        if path == "/api/health" and read:
            return self.reply(200, {"ok": True, "version": VERSION, "document_leases": True})
        if path == "/api/login" and self.command == "POST":
            # Only a local reverse proxy may supply the original address.
            address = self.client_address[0]
            if address == "127.0.0.1":
                address = self.headers.get("X-Real-IP", address)[:100]
            return self.reply(200, self.server.auth.login(self.body(4096), address))
        if path == "/api/session/refresh" and self.command == "POST":
            return self.reply(200, self.server.auth.refresh(self.body(2048)))
        if path == "/api/session/logout" and self.command == "POST":
            token = self.server.auth.refresh_token(self.body(2048))
            self.server.storage.revoke_remembered_session(self.server.auth.digest(token))
            return self.reply(200, {"ok": True})
        if path.startswith("/api/"):
            header = self.headers.get("Authorization", "")
            if not self.server.auth.authorized(header):
                raise PermissionError("请先登录，或登录已过期")
            device = self.server.storage.session_device(self.server.auth.digest(header[7:]))
            if device is None:
                raise PermissionError("请先登录，或登录已过期")
            if path == "/api/session" and read:
                return self.reply(200, {"ok": True, "document_leases": True, "lease_seconds": LEASE_SECONDS, "heartbeat_seconds": HEARTBEAT_SECONDS})
            if path in ("/api/editor/open", "/api/editor/renew", "/api/editor/release") and self.command == "POST":
                operation = getattr(self.server.storage.leases, path.rsplit("/", 1)[-1])
                return self.reply(200, operation(self.body(4096), device))
            if path == "/api/logout" and self.command == "POST":
                self.server.storage.revoke_session(self.server.auth.digest(header[7:]))
                return self.reply(200, {"ok": True})
            if path == "/api/changes" and read:
                since = int(parse_qs(parsed.query).get("since", ["0"])[0])
                if since < 0:
                    raise ValueError("同步位置无效")
                return self.reply(200, self.server.storage.changes(since))
            if path == "/api/sync" and self.command == "POST":
                result = self.server.storage.sync(self.body(), device)
                self.server.daily_backup()
                return self.reply(200, result)
            if path.startswith("/api/history/") and read:
                return self.reply(200, {"revisions": self.server.storage.history(str(uuid.UUID(path.rsplit("/", 1)[-1])))})
            if path == "/api/media" and self.command == "POST":
                request = self.body()
                identifier = str(request.get("id", ""))
                if not MEDIA_ID.fullmatch(identifier):
                    raise ValueError("图片标识无效")
                data = base64.b64decode(request["data"], validate=True)
                if not 0 < len(data) <= 12 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != identifier:
                    raise ValueError("图片超过 12 MB 或校验失败")
                mime = image_type(data)
                target = self.server.media / identifier
                if not target.exists():
                    temporary = self.server.media / (identifier + "." + uuid.uuid4().hex + ".tmp")
                    try:
                        with temporary.open("xb") as stream:
                            stream.write(data)
                            stream.flush()
                            os.fsync(stream.fileno())
                        os.replace(temporary, target)
                    finally:
                        temporary.unlink(missing_ok=True)
                return self.reply(200, {"id": identifier, "mime": mime})
            if path.startswith("/api/media/") and read:
                identifier = path.rsplit("/", 1)[-1]
                if not MEDIA_ID.fullmatch(identifier):
                    raise ValueError("图片标识无效")
                target = self.server.media / identifier
                if not target.exists():
                    return self.reply(404, {"error": "图片暂未同步到云端"})
                data = target.read_bytes()
                return self.reply(200, {"mime": image_type(data), "data": base64.b64encode(data).decode()})
            return self.reply(404, {"error": "接口不存在"})
        if not read:
            return self.reply(405, {"error": "请求方式不支持"})
        public = (self.server.root / "server" / "public").resolve()
        target = (public / (path.lstrip("/") or "index.html")).resolve()
        if not target.is_relative_to(public) or not target.is_file():
            return self.reply(404, {"error": "页面不存在"})
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        if target.suffix in (".js", ".mjs"):
            mime = "text/javascript"
        self.reply(200, target.read_bytes(), mime)
