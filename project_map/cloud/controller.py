from __future__ import annotations

import copy
import datetime as dt
import html
import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal
from shiboken6 import isValid

from ..file_io import atomic_write, read_json, write_json
from .api import Api, CloudError, DEFAULT_ENDPOINT, normalize_endpoint
from .credentials import load_account, save_account
from .session import SessionApi
from .engine import Engine
from .merge import merge_document, payload
from .editing import EditorAccess, LeaseApi


class CloudController(QObject):
    status_changed = Signal(str)
    job_finished = Signal(object)
    login_finished = Signal(bool, str)

    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.config_path = window.paths.data / "cloud" / "config.json"
        self.auth_path = window.paths.data / "cloud" / "account.json"
        self.config = {"endpoint": DEFAULT_ENDPOINT, "username": "owner", "enabled": False, "auto_login": True, "include_external": False, "device_id": "Windows-" + str(uuid.uuid4())[:12], **read_json(self.config_path)}
        self.auth_lock = threading.RLock()
        self.session = load_account(self.auth_path, self.config["endpoint"]) if self.config["auto_login"] else {}
        self.busy = False
        self.closing = False
        self.retry_at = 0.0
        self.file_cache = {}
        self.status = "云同步未启用"
        self.engine = self.new_engine()
        self.issues = self.engine.load().get("issues", [])
        self.editing = EditorAccess(self)
        self.job_finished.connect(self.finish_job)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.synchronize)
        self.poll = QTimer(self)
        self.poll.setInterval(5000)
        self.poll.timeout.connect(self.synchronize)
        self.poll.start()
        if self.session.get("token") or self.session.get("refresh_token"):
            self.set_status("正在自动登录")
            QTimer.singleShot(0, self, self.restore_session)
        else:
            self.schedule()
        if self.editing.managed_id(self.window.current_path):
            self.editing.set_access(False, "正在确认云端编辑占用…")

    def new_engine(self):
        return Engine(self.window.paths, self.config["endpoint"], self.window.extra_media_dirs())

    def set_status(self, value):
        self.status = value
        self.status_changed.emit(value)
        if hasattr(self.window, "cloud_label"):
            compact = value if len(value) <= 26 else "同步异常 · 查看详情"
            self.window.cloud_label.setText("云：" + compact)
            details = "\n\n".join(self.issue_text(issue) for issue in self.issues[:3])
            if len(self.issues) > 3:
                details += f"\n\n还有 {len(self.issues) - 3} 个项目，点击查看全部详情。"
            tooltip = value + ("\n\n" + details if details else "") + "\n\n点击查看云同步设置与完整详情"
            self.window.cloud_label.setToolTip("<qt>" + html.escape(tooltip).replace("\n", "<br>") + "</qt>")
            self.window.cloud_label.setAccessibleDescription(tooltip)

    @staticmethod
    def issue_text(issue):
        return f"项目：{Path(issue['path']).name}\n文件：{issue['path']}\n原因：{issue['message']}"

    def schedule(self):
        if self.config.get("enabled") and not self.closing:
            self.timer.start(1200)

    def set_session(self, account):
        with self.auth_lock:
            self.session = dict(account)
            if self.config.get("auto_login"):
                save_account(self.auth_path, self.config["endpoint"], self.session)

    def session_api(self):
        with self.auth_lock:
            account = dict(self.session)
        return SessionApi(self.config["endpoint"], account, self.set_session)

    def restore_session(self):
        if not self.busy and not self.closing:
            self.run_job("resume", lambda: self.session_api().request("api/session"))

    def forget_session(self):
        with self.auth_lock:
            self.session = {}
            write_json(self.auth_path, {})

    def save_config(self, *, endpoint=None, enabled=None, include_external=None, auto_login=None):
        if self.editing.active and (enabled is False or (endpoint is not None and normalize_endpoint(endpoint) != self.config["endpoint"])):
            raise ValueError("请先点击“结束本端编辑”，等保存同步完成后再暂停同步或切换服务器。")
        if endpoint is not None:
            endpoint = normalize_endpoint(endpoint)
            if endpoint != self.config["endpoint"]:
                if self.busy:
                    raise ValueError("正在同步，请稍后再切换服务器")
                self.config["endpoint"] = endpoint
                self.config["enabled"] = False
                self.forget_session()
                self.engine = self.new_engine()
                self.issues = self.engine.load().get("issues", [])
        if auto_login is not None:
            with self.auth_lock:
                self.config["auto_login"] = bool(auto_login)
                if not auto_login:
                    write_json(self.auth_path, {})
                elif self.session:
                    save_account(self.auth_path, self.config["endpoint"], self.session)
        if include_external is not None:
            self.config["include_external"] = bool(include_external)
        if enabled is not None:
            self.config["enabled"] = bool(enabled)
        write_json(self.config_path, self.config)
        if not self.config["enabled"]:
            self.timer.stop()
            self.set_status("云同步已暂停，本地照常保存")
            self.editing.paused = False
            self.editing.blocked_path = None
            self.editing.set_access(True)
        else:
            self.schedule()

    def run_job(self, kind, function):
        if self.busy or self.closing:
            return False
        self.busy = True

        def run():
            try:
                result = {"kind": kind, "value": function(), "error": None}
            except Exception as error:
                result = {"kind": kind, "value": None, "error": error}
            if not self.closing and isValid(self):
                self.job_finished.emit(result)

        threading.Thread(target=run, name="ProjectMap.Cloud", daemon=True).start()
        return True

    def login(self, endpoint, username, password, auto_login=None):
        if self.busy:
            self.login_finished.emit(False, "正在同步，请稍后再登录")
            return
        try:
            endpoint = normalize_endpoint(endpoint)
            if not username.strip() or not password:
                raise ValueError("请填写云账号和密码")
        except ValueError as error:
            self.login_finished.emit(False, str(error))
            return
        self.set_status("正在登录")
        remember = self.config["auto_login"] if auto_login is None else bool(auto_login)

        def connect():
            reply = Api(endpoint).request("api/login", {"username": username.strip(), "password": password, "device_id": self.config["device_id"], "auto_login": remember})
            return {"endpoint": endpoint, "username": username.strip(), "auto_login": remember, "account": {"token": reply["token"], "refresh_token": reply.get("refresh_token", ""), "username": username.strip()}}

        self.run_job("login", connect)

    def logout(self):
        if self.editing.active or self.editing.pending:
            self.window.show_notice("请先结束本端编辑", "先点击大纲上方的“结束本端编辑”，等保存同步完成后再退出云账号。")
            return
        if self.busy:
            self.set_status("正在同步，请稍后退出云账号")
            return
        account = dict(self.session)
        self.save_config(enabled=False)
        self.forget_session()
        self.set_status("已退出云账号，本地资料保留")
        if account.get("refresh_token"):
            self.run_job("logout", lambda: Api(self.config["endpoint"]).request("api/session/logout", {"refresh_token": account["refresh_token"]}))
        elif account.get("token"):
            self.run_job("logout", lambda: Api(self.config["endpoint"], account["token"]).request("api/logout", {}))

    def snapshots(self):
        result = []
        paths = sorted(self.window.all_project_paths(), key=self.window.project_sort_key)
        for index, path in enumerate(paths):
            meta = self.window.project_meta(path)
            if self.window.same_path(path, self.window.current_path):
                text = self.window.editor.toPlainText()
            else:
                stat = path.stat()
                key = self.window.normalized_path(path)
                stamp = (stat.st_mtime_ns, stat.st_size)
                cached = self.file_cache.get(key)
                if cached is None or cached[0] != stamp:
                    cached = (stamp, path.read_text(encoding="utf-8-sig"))
                    self.file_cache[key] = cached
                text = cached[1]
            result.append({
                "path": str(path), "external": not self.window.is_local_project(path),
                "active": self.window.same_path(path, self.window.current_path),
                "cloud_id": meta.get("cloud_id"), "cloud_endpoint": meta.get("cloud_endpoint"),
                "document": payload({
                    "content": text, "title": self.window.display_name(path), "group": meta.get("group", "默认项目"),
                    "description": meta.get("description", ""), "priority": meta.get("priority", ""),
                    "pinned": bool(meta.get("pinned", False)), "order": meta.get("order", index),
                    "project_path": meta.get("project_path", ""),
                }),
            })
        known = {self.window.normalized_path(item["path"]) for item in result}
        for meta in self.window.metadata.values():
            if isinstance(meta, dict) and meta.get("source_path") and self.window.normalized_path(meta["source_path"]) not in known:
                result.append({"path": meta["source_path"], "external": True, "document": None})
        return result

    def synchronize(self, force=False):
        if self.busy or self.closing or (not force and (not self.config.get("enabled") or time.monotonic() < self.retry_at)):
            return
        if not self.session.get("token") and not self.session.get("refresh_token"):
            self.set_status("尚未登录，资料仅保存在本机")
            return
        if not self.window.flush_auto_save():
            self.set_status("本地保存失败，未上传此修改")
            return
        try:
            snapshots = self.snapshots()
        except (OSError, UnicodeError) as error:
            self.set_status("读取项目失败：" + str(error))
            return
        self.set_status("同步中，本地可继续编辑")
        engine = self.engine
        engine.assets.search_dirs = [self.window.paths.media, self.window.paths.root / "Media", *self.window.extra_media_dirs()]
        config = copy.deepcopy(self.config)
        self.run_job("sync", lambda: engine.cycle(LeaseApi(self.session_api(), self.editing), snapshots, config["device_id"], config.get("include_external", False)))

    def current_document(self, path, fallback):
        if not path.exists():
            return {**fallback, "deleted": True}
        meta = self.window.project_meta(path)
        content = self.window.editor.toPlainText() if self.window.same_path(path, self.window.current_path) else path.read_text(encoding="utf-8-sig")
        content, _images = self.engine.assets.cloud_content(content, path)
        return payload({**fallback, "content": content, "title": self.window.display_name(path),
                        "group": meta.get("group", "默认项目"), "description": meta.get("description", ""),
                        "priority": meta.get("priority", ""), "pinned": bool(meta.get("pinned", False)),
                        "order": meta.get("order", fallback["order"]), "project_path": meta.get("project_path", "")})

    def write_document(self, path, document, identifier=None):
        window = self.window
        if document["deleted"]:
            if path.exists() and window.is_local_project(path):
                self.backup_file(path)
                path.unlink()
            window.metadata.pop(window.project_key(path), None)
            return
        content = document["content"]
        existing = path.read_text(encoding="utf-8-sig") if path.exists() else None
        if existing is not None:
            converted, _images = self.engine.assets.cloud_content(existing, path)
            if converted == content:
                content = existing
        if existing != content:
            if existing is not None:
                self.backup_file(path)
            atomic_write(path, content.encode("utf-8"))
        meta = window.project_meta(path, create=True)
        meta.update({"display_name": document["title"], **{key: document[key] for key in ("group", "description", "priority", "pinned", "order", "project_path")}})
        if identifier:
            meta.update(cloud_id=identifier, cloud_endpoint=self.config["endpoint"])

    def backup_file(self, path):
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        backup = self.window.paths.backups / "Cloud" / (path.stem + "-" + stamp + ".md.bak")
        atomic_write(backup, path.read_bytes())

    def apply_result(self, result):
        window = self.window
        if not window.flush_auto_save():
            raise OSError("本地保存失败，云变更暂未应用")
        done = []
        changed = False
        active = window.current_path
        window.save_project_view_state()
        try:
            for identifier, update in result["applications"].items():
                path = Path(update["path"])
                expected, remote = update["expected"], update["remote"]
                if path.exists():
                    latest = self.current_document(path, expected)
                    merged = merge_document(expected, latest, remote)
                    if merged is None:
                        if not latest["deleted"]:
                            copy_path = self.engine.unused_path(latest["title"] + " · 本地冲突副本", str(uuid.uuid4()), self.engine.load()["documents"])
                            self.write_document(copy_path, latest)
                            if window.same_path(path, active):
                                active = copy_path
                        merged = remote
                        self.set_status("存在同时修改，已保留冲突副本")
                else:
                    merged = remote
                self.write_document(path, merged, identifier)
                if update.get("related_path") and window.same_path(active, update["related_path"]):
                    active = path
                done.append(identifier)
                changed = True
            for identifier, path_text in result["bindings"].items():
                path = Path(path_text)
                if not path.exists():
                    continue
                meta = window.project_meta(path, create=True)
                if meta.get("cloud_id") != identifier or meta.get("cloud_endpoint") != self.config["endpoint"]:
                    meta.update(cloud_id=identifier, cloud_endpoint=self.config["endpoint"])
                    changed = True
            if changed:
                window.save_metadata()
                if active and active.exists():
                    window.current_path = active
                elif active and not active.exists():
                    window.current_path = None
                previous_bypass = self.editing.bypass
                self.editing.bypass = True
                try:
                    window.refresh_files()
                finally:
                    self.editing.bypass = previous_bypass
        finally:
            self.engine.acknowledge(done)

    def finish_job(self, result):
        self.busy = False
        if self.closing:
            return
        kind, error = result["kind"], result["error"]
        if kind == "editor_close":
            self.editing.closed()
            return
        if kind == "editor_release":
            self.editing.released()
            return
        if kind == "editor_open":
            self.editing.opened(result)
            return
        if error:
            if self.editing.close_after and not self.editing.pending:
                self.editing.finish_close()
                return
            self.set_status(str(error))
            if kind == "login":
                self.login_finished.emit(False, str(error))
            elif isinstance(error, CloudError) and error.status == 401:
                self.forget_session()
                self.editing.active = None
                self.editing.paused = True
                self.editing.set_access(False, "云登录已失效 · 内容保留在本机，请重新登录后继续编辑")
                self.set_status("登录已失效，请在云同步设置中重新登录")
            elif kind == "logout":
                self.set_status("已在本机退出，联网后可重新登录；本地资料保留")
            else:
                self.retry_at = time.monotonic() + 15
                self.timer.start(15000)
            if kind == "sync":
                self.editing.synced(result)
            return
        if kind == "login":
            account = result["value"]["account"]
            self.config.update({key: result["value"][key] for key in ("endpoint", "username", "auto_login")})
            self.forget_session()
            self.set_session(account)
            self.config["enabled"] = True
            self.engine = self.new_engine()
            self.issues = self.engine.load().get("issues", [])
            write_json(self.config_path, self.config)
            self.set_status("登录成功，即将同步")
            self.login_finished.emit(True, "已连接云端，手机使用同一账号即可同步")
            self.editing.paused = False
            self.schedule()
            self.editing.activate()
        elif kind == "resume":
            self.set_status("已自动登录，即将同步" if self.config["enabled"] else "已自动登录，云同步已暂停")
            self.schedule()
            self.editing.activate()
        elif kind == "sync":
            value = result["value"]
            self.issues = value.get("issues", [{"path": "待处理项目", "message": error}
                                             for error in value.get("errors", [])])
            try:
                self.apply_result(value)
            except (OSError, ValueError) as error:
                self.set_status("云变更未应用：" + str(error))
                self.timer.start(15000)
                self.editing.synced({**result, "error": error})
                return
            self.retry_at = 0.0
            self.set_status(f"{len(self.issues)} 个项目待处理 · 查看详情" if self.issues else "已同步 " + dt.datetime.now().strftime("%H:%M:%S"))
            if self.editing.close_after and not self.editing.pending:
                self.editing.finish_close()
            elif self.editing.pending:
                self.editing.synced(result)
            elif self.editing.active and self.editing.active.pop("initial", False):
                self.editing.set_access(self.editing.writable(), "正在本端编辑 · 另一端暂不能打开此大纲")
            elif self.editing.managed_id(self.window.current_path) and (not self.editing.active or self.editing.active["id"] != self.editing.managed_id(self.window.current_path)):
                self.editing.activate()
        elif kind == "logout":
            self.set_status("已退出云账号，本地资料保留")

        if self.editing.close_after and not self.editing.pending:
            self.editing.finish_close()

    def rebind(self):
        if self.busy:
            raise ValueError("正在同步，请稍后再切换数据目录")
        self.engine = self.new_engine()
        self.issues = self.engine.load().get("issues", [])
        self.schedule()

    def shutdown(self):
        self.closing = True
        self.timer.stop()
        self.poll.stop()
        self.engine.cancel.set()
        self.editing.shutdown()
