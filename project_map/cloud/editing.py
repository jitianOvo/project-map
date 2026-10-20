from __future__ import annotations

import threading
import time
import uuid
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, Signal

from .api import CloudError


class LeaseApi:
    def __init__(self, api, editing):
        self.api, self.editing = api, editing

    def request(self, route, body=None):
        if route != "api/sync":
            return self.api.request(route, body)
        editing = self.editing
        with editing.lock:
            active = editing.active
            initial = not active and body.get("_active_editor") and not editing.paused
            retained = bool(initial or (active and active["id"] == body["id"]))
            client = editing.client if retained else str(uuid.uuid4())
        started = time.monotonic()
        lease = self.api.request("api/editor/open", {"id": body["id"], "client_id": client, "recover": bool(initial)})
        proof = {"id": body["id"], "client_id": client, "lease_token": lease["lease_token"]}
        if retained:
            with editing.lock:
                if initial and editing.active is None:
                    editing.active = {**proof, "deadline": started + lease["expires_in"] - 5, "initial": True}
                elif editing.active is active:
                    active.update(proof, deadline=started + lease["expires_in"] - 5)
        try:
            request = {key: value for key, value in body.items() if key != "_active_editor"}
            return self.api.request(route, {**request, **proof})
        finally:
            if not retained:
                try:
                    self.api.request("api/editor/release", proof)
                except CloudError:
                    pass


class EditorAccess(QObject):
    renewed = Signal(object, object, object)

    def __init__(self, cloud):
        super().__init__(cloud)
        self.cloud, self.window = cloud, cloud.window
        self.client = str(uuid.uuid5(uuid.NAMESPACE_URL, f"project-map:{cloud.config['device_id']}:{self.window.paths.library_id}"))
        self.lock = threading.RLock()
        self.active = None
        self.pending = False
        self.target = None
        self.queued_path = None
        self.after_release = []
        self.previous = None
        self.bypass = False
        self.closing_ready = False
        self.close_after = False
        self.release_only = False
        self.deactivate_after = False
        self.resume_after = False
        self.renew_busy = False
        self.enabled = True
        self.blocked_path = None
        self.paused = False
        self.sync_attempts = 0
        self.retry_path = None
        self.retry_at = 0
        self.quiet = False
        self.heartbeat = 5
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.timer.start()
        self.renewed.connect(self.renew_finished)
        self.last_renew = 0
        self.window.editing_resume.clicked.connect(lambda: self.request_open(self.window.current_path, force=True))
        self.window.editing_release.clicked.connect(self.end_editing)

    def managed_id(self, path):
        if not path or not self.enabled or not self.cloud.config.get("enabled"):
            return None
        if not self.window.is_local_project(path) and not self.cloud.config.get("include_external"):
            return None
        meta = self.window.project_meta(path)
        return meta.get("cloud_id") if meta.get("cloud_endpoint") == self.cloud.config["endpoint"] else None

    def writable(self):
        return bool(self.active and self.active["deadline"] > time.monotonic())

    def set_access(self, allowed, message=""):
        self.window.editor.setReadOnly(not allowed)
        for action in self.window.toolbar_catalogs["format"][1].values():
            action.setEnabled(allowed)
        self.window.editing_label.setText(message if not allowed else "")
        self.window.editing_banner.setVisible(bool(message) and not allowed)
        self.window.editing_resume.hide()
        self.window.editing_release.hide()

    def request_open(self, path, force=False, quiet=False):
        if self.bypass or self.closing_ready:
            return False
        loaded = self.window.loaded_project_path()
        if loaded:
            self.window.current_path = loaded
        if self.pending:
            if path and (force or not self.window.same_path(path, loaded)):
                self.queued_path = None if self.window.same_path(path, self.target) else Path(path)
            return True
        if self.paused and not force and self.window.same_path(path, self.window.current_path):
            return False
        identifier = self.managed_id(path)
        if path and self.blocked_path and self.window.same_path(path, self.blocked_path) and not force:
            return True
        if not identifier and not self.active:
            self.set_access(True)
            return False
        if not force and self.active and self.active["id"] == identifier and self.writable() and not self.pending:
            return False
        self.previous = getattr(self.window.editor, "current_document_path", None)
        if self.previous:
            self.window.current_path = self.previous
        if not self.window.flush_auto_save():
            self.window.show_notice("暂时不能切换", "当前内容还没有保存成功，请先处理保存问题。")
            return True
        self.target = Path(path) if path else None
        self.retry_path = None
        self.quiet = quiet
        self.blocked_path = None
        self.paused = self.release_only
        self.pending = True
        self.sync_attempts = 0
        self.set_access(False, "正在保存同步并确认编辑占用…")
        self.start_sync()
        return True

    def start_sync(self):
        if self.cloud.closing or not self.pending:
            return
        if self.cloud.busy:
            QTimer.singleShot(100, self, self.start_sync)
        else:
            self.cloud.synchronize(force=True)
            if not self.cloud.busy:
                self.fail("无法确认云端状态，请联网并登录后重试。")

    def synced(self, result):
        if not self.pending:
            return
        if result["error"]:
            self.fail(str(result["error"]))
            return
        if self.active and self.previous:
            try:
                state = self.cloud.engine.load()
                entry = state["documents"].get(self.active["id"])
                if not entry or entry.get("pending") or self.cloud.current_document(self.previous, entry["base"]) != entry["base"]:
                    blocked = any(self.window.same_path(issue["path"], self.previous) for issue in result["value"].get("issues", []))
                    self.sync_attempts += 1
                    if not blocked and self.sync_attempts <= 3:
                        QTimer.singleShot(0, self, self.start_sync)
                        return
                    raise ValueError("当前大纲尚未同步完成，暂时不能交给另一端；请查看云同步详情后重试。")
            except (OSError, ValueError) as error:
                self.fail(str(error), keep_current=True)
                return
        target_id = self.managed_id(self.target)
        if target_id:
            try:
                entry = self.cloud.engine.load()["documents"].get(target_id)
                if entry and (entry.get("pending") or self.cloud.current_document(self.target, entry["base"]) != entry["base"]):
                    self.sync_attempts += 1
                    if self.sync_attempts <= 3:
                        QTimer.singleShot(0, self, self.start_sync)
                    else:
                        self.fail("这份大纲还有本地待同步草稿，已保留原稿，正在等待云端可用后同步。", keep_current=True)
                    return
            except (OSError, ValueError) as error:
                self.fail(str(error), keep_current=True)
                return
        previous = dict(self.active) if self.active else None

        def open_target():
            api = self.cloud.session_api()
            started = time.monotonic()
            lease = api.request("api/editor/open", {"id": target_id, "client_id": self.client,
                                "recover": not previous or previous["id"] != target_id}) if target_id else None
            if lease:
                lease["deadline"] = started + lease["expires_in"] - 5
            if previous and (not lease or lease["id"] != previous["id"]):
                api.request("api/editor/release", {key: previous[key] for key in ("id", "client_id", "lease_token")})
            return lease

        self.cloud.run_job("editor_open", open_target)

    def opened(self, result):
        if result["error"]:
            self.fail(str(result["error"]), keep_current=getattr(result["error"], "status", 0) == 423)
            return
        lease = result["value"]
        if lease and lease["id"] != self.managed_id(self.target):
            self.fail("收到的云端大纲与待打开项目不一致，已停止载入并保留本机内容。")
            return
        self.heartbeat = lease.get("heartbeat_in", 5) if lease else 5
        with self.lock:
            self.active = ({"id": lease["id"], "client_id": self.client, "lease_token": lease["lease_token"],
                            "deadline": lease["deadline"]} if lease else None)
        self.last_renew = time.monotonic()
        target = self.target
        try:
            if lease and lease.get("document"):
                state = self.cloud.engine.load()
                expected = self.cloud.current_document(target, lease["document"])
                self.cloud.engine.queue_remote(state, self.cloud.session_api(), lease["document"], expected, target)
                self.bypass = True
                self.cloud.apply_result(self.cloud.engine.result(state))
            self.bypass = True
            if target and target.exists():
                self.window.load_file(target)
                self.window.current_path = target
                self.window.refresh_files()
            self.pending = False
            if self.active and not self.writable():
                raise CloudError("加载期间编辑占用已到期，请联网后重新打开。")
            if self.release_only:
                self.paused = True
                if not self.close_after and not self.deactivate_after:
                    self.released()
            else:
                self.set_access(True, "正在本端编辑 · 另一端暂不能打开此大纲" if self.active else "")
            if self.close_after:
                self.finish_close()
            elif self.deactivate_after:
                self.deactivate_after = False
                self.finish_close(close=False)
        except (OSError, ValueError, CloudError) as error:
            self.active = None
            self.fail("最新版尚未加载，编辑已暂停：" + str(error))
        finally:
            self.bypass = False
            self.release_only = False
            self.close_after = False
            self.open_queued()

    def open_queued(self):
        path, self.queued_path = self.queued_path, None
        if path and path.exists() and not self.closing_ready and not self.cloud.closing:
            QTimer.singleShot(0, self, lambda: self.request_open(path, force=True, quiet=True))

    def fail(self, message, keep_current=False):
        self.blocked_path = self.target
        self.pending = False
        releasing = self.release_only
        self.release_only = False
        close_after, self.close_after = self.close_after, False
        allowed = bool(keep_current and self.writable() and self.active["id"] != self.managed_id(self.target))
        if not allowed and self.active:
            self.active["deadline"] = 0
        if not allowed and not self.paused and self.target and self.managed_id(self.target):
            self.retry_path = self.target
            self.retry_at = time.monotonic() + 2
            message += "\n正在自动重试，释放后会接续编辑。"
        self.set_access(allowed, message)
        if self.previous:
            self.window.current_path = self.previous
            self.bypass = True
            try:
                self.window.refresh_files()
            finally:
                self.bypass = False
        if close_after:
            self.finish_close()
        elif releasing or self.deactivate_after:
            self.deactivate_after = False
            self.finish_close(close=False)
        elif not self.quiet:
            self.window.show_notice("这份大纲暂时不能打开", message)
        self.open_queued()

    def finish_close(self, close=True):
        self.paused = True
        self.retry_path = None
        self.pending = True
        self.window.flush_auto_save()
        with self.lock:
            active, self.active = self.active, None

        def release():
            if active:
                self.cloud.session_api().request("api/editor/release", {key: active[key] for key in ("id", "client_id", "lease_token")})

        self.cloud.run_job("editor_close" if close else "editor_release", release)

    def closed(self):
        self.pending = False
        self.closing_ready = True
        self.window.close()

    def released(self):
        self.pending = False
        self.set_access(False, "编辑已自动交接 · 点击项目或编辑区即可继续")
        callbacks, self.after_release = self.after_release, []
        if callbacks:
            self.resume_after = False
            QTimer.singleShot(0, self, lambda: self.apply_after_release(callbacks))
        elif self.resume_after and not self.window.isMinimized():
            self.resume_after = False
            self.request_open(self.window.current_path, force=True, quiet=True)

    def defer_until_released(self, callback):
        if not self.active and not self.pending:
            return False
        self.after_release.append(callback)
        self.end_editing()
        return True

    def apply_after_release(self, callbacks):
        for callback in callbacks:
            try:
                callback()
            except (OSError, ValueError) as error:
                self.window.show_notice("设置暂未应用", str(error))

    def end_editing(self, close=False):
        self.retry_path = None
        self.queued_path = None
        if not close:
            self.paused = True
            if self.pending:
                self.deactivate_after = True
                return True
        if not self.active or self.pending:
            return False
        self.close_after = close
        self.release_only = True
        self.request_open(None, force=True)
        return True

    def tick(self):
        if self.cloud.closing:
            return
        now = time.monotonic()
        if self.retry_path and not self.pending and not self.paused and now >= self.retry_at and not self.window.isMinimized():
            self.request_open(self.retry_path, force=True, quiet=True)
            return
        if not self.active:
            return
        if not self.writable() and not self.window.editor.isReadOnly():
            self.window.flush_auto_save()
            self.set_access(False, "连接中断或占用已失效 · 内容已保存在本机，恢复后自动继续")
        if not self.writable() and not self.pending and not self.paused:
            self.retry_path = self.window.current_path
            self.retry_at = now + 2
            return
        if self.pending or self.paused or self.renew_busy or now - self.last_renew < self.heartbeat:
            return
        self.renew_busy = True
        self.last_renew = time.monotonic()
        proof = {key: self.active[key] for key in ("id", "client_id", "lease_token")}

        def renew():
            started = time.monotonic()
            try:
                reply, error = self.cloud.session_api().request("api/editor/renew", proof), None
                reply["deadline"] = started + reply["expires_in"] - 5
            except Exception as failure:
                reply, error = None, str(failure)
            if not self.cloud.closing:
                self.renewed.emit(proof, reply, error)

        threading.Thread(target=renew, name="ProjectMap.EditLease", daemon=True).start()

    def renew_finished(self, proof, reply, error):
        self.renew_busy = False
        if not self.active or any(self.active[key] != proof[key] for key in ("id", "lease_token")):
            return
        if error:
            self.active["deadline"] = 0
            self.window.flush_auto_save()
            self.set_access(False, "编辑占用续期失败 · 内容保留在本机，正在自动恢复")
            if not self.paused:
                self.retry_path = self.window.current_path
                self.retry_at = time.monotonic() + 2
        else:
            self.active["deadline"] = reply["deadline"]
            if not self.pending and not self.paused:
                self.retry_path = None
                self.set_access(True, "正在本端编辑 · 另一端暂不能打开此大纲")

    def activate(self):
        path = self.window.loaded_project_path()
        if self.managed_id(path) and not self.pending and not self.window.isMinimized():
            if not self.paused and self.writable():
                return
            self.request_open(path, force=True, quiet=True)

    def shutdown(self):
        self.timer.stop()
