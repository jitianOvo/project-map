from __future__ import annotations

import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import test_workflow as workflow
from PySide6.QtTest import QTest
from project_map.cloud.api import Api, CloudError
from project_map.cloud.editing import LeaseApi
from project_map.locations import cloud_dir

sys.path.insert(0, str(cloud_dir(Path(__file__).resolve().parents[1])))
from server.http import CloudServer
from server.auth import initialize, password_hash
from project_map.file_io import write_json


class EditingAccessTests(unittest.TestCase):
    def setUp(self):
        workflow.WindowTests.setUp(self)
        root = self.window.paths.root / "服务"
        root.mkdir()
        initialize(root)
        salt = "00" * 16
        write_json(root / ".secrets/account.json", {"username": "owner", "salt": salt, "hash": password_hash("lease-test-only", salt)})
        self.service = CloudServer(("127.0.0.1", 0), root)
        self.worker = threading.Thread(target=self.service.serve_forever, daemon=True)
        self.worker.start()
        self.endpoint = f"http://127.0.0.1:{self.service.server_port}/"
        self.notices = self.patches.enter_context(patch.object(self.window, "show_notice"))
        self.window.cloud.login(self.endpoint, "owner", "lease-test-only")
        self.jobs = []
        self.window.cloud.job_finished.connect(lambda result: self.jobs.append((result["kind"], str(result["error"]))))
        self.addCleanup(self.cleanup_service)
        self.wait(lambda: self.window.cloud.editing.active and not self.window.cloud.editing.pending
                  and not self.window.cloud.busy and not self.window.editor.isReadOnly()
                  and self.window.project_meta(self.window.current_path).get("cloud_id") == self.window.cloud.editing.active["id"])
        token = Api(self.endpoint).request("api/login", {"username": "owner", "password": "lease-test-only", "device_id": "手机-test"})["token"]
        self.phone = Api(self.endpoint, token)

    def wait(self, predicate):
        deadline = time.monotonic() + 10
        while not predicate() and time.monotonic() < deadline:
            QTest.qWait(25)
            time.sleep(0.005)
        self.assertTrue(predicate(), self.window.cloud.status + " / " + self.window.editing_label.text() + " / " + str(self.jobs))

    def tearDown(self):
        self.cleanup_service()
        workflow.WindowTests.tearDown(self)

    def cleanup_service(self):
        if getattr(self, "service_closed", False):
            return
        self.service_closed = True
        self.window.cloud.editing.closing_ready = True
        self.window.cloud.shutdown()
        self.service.shutdown()
        self.worker.join(timeout=3)
        self.service.server_close()

    def test_other_client_blocked_and_handoff_loads_latest(self):
        import uuid
        identifier = self.window.cloud.editing.active["id"]
        request = {"id": identifier, "client_id": str(uuid.uuid4())}
        with self.assertRaises(CloudError) as error:
            self.phone.request("api/editor/open", request)
        self.assertEqual(error.exception.status, 423)
        self.window.editor.insertPlainText("交接前的新内容")
        self.window.cloud.editing.end_editing()
        self.wait(lambda: not self.window.cloud.editing.pending and not self.window.cloud.editing.active)
        reply = self.phone.request("api/editor/open", request)
        self.assertIn("交接前的新内容", reply["document"]["content"])
        self.assertTrue(self.window.editor.isReadOnly())

    def test_blocked_open_keeps_previous_project_and_other_project_editable(self):
        import uuid
        old = self.window.current_path
        new = old.parent / "另一大纲.md"
        new.write_text("另一份正文", encoding="utf-8")
        self.window.refresh_files()
        self.window.cloud.synchronize(force=True)
        self.wait(lambda: self.window.project_meta(new).get("cloud_id") and not self.window.cloud.busy)
        identifier = self.window.project_meta(new)["cloud_id"]
        phone = self.phone.request("api/editor/open", {"id": identifier, "client_id": str(uuid.uuid4())})
        self.window.load_file(new)
        self.wait(lambda: not self.window.cloud.editing.pending)
        self.assertEqual(self.window.current_path, old)
        self.assertFalse(self.window.editor.isReadOnly())
        self.assertTrue(self.notices.called)
        self.assertIn("手机端", self.notices.call_args.args[1])

    def test_expired_lease_freezes_format_tools_and_keeps_local_draft(self):
        self.window.editor.insertPlainText("草稿不能丢")
        access = self.window.cloud.editing
        access.active["deadline"] = 0
        access.last_renew = time.monotonic()
        access.tick()
        self.assertTrue(self.window.editor.isReadOnly())
        before = self.window.editor.toPlainText()
        self.window.wrap_selection("**", "**")
        self.window.editor.add_version()
        self.window.editor.set_priority("urgent")
        self.assertEqual(self.window.editor.toPlainText(), before)
        self.assertIn("草稿不能丢", self.path.read_text(encoding="utf-8"))

    def test_stale_renew_response_does_not_extend_another_project(self):
        access = self.window.cloud.editing
        proof = {"id": "old", "lease_token": "old"}
        deadline = access.active["deadline"]
        access.renew_finished(proof, {"expires_in": 60}, None)
        self.assertEqual(access.active["deadline"], deadline)

    def test_expired_lease_recovers_automatically_without_clicking_continue(self):
        access = self.window.cloud.editing
        with self.service.storage.lock, self.service.storage.db:
            self.service.storage.db.execute("DELETE FROM editor_leases")
        access.renew_finished(dict(access.active), None, "占用已过期")
        self.assertTrue(self.window.editor.isReadOnly())
        access.retry_at = 0
        access.tick()
        self.wait(lambda: not access.pending and access.writable() and not self.window.editor.isReadOnly())

    def test_waiting_editor_resumes_when_other_device_releases(self):
        import uuid
        access = self.window.cloud.editing
        identifier = access.active["id"]
        self.window.cloud.session_api().request("api/editor/release", dict(access.active))
        claim = {"id": identifier, "client_id": str(uuid.uuid4())}
        phone = self.phone.request("api/editor/open", claim)
        access.renew_finished(dict(access.active), None, "手机端正在编辑")
        access.retry_at = 0
        access.tick()
        self.wait(lambda: not access.pending)
        self.assertTrue(self.window.editor.isReadOnly())
        self.phone.request("api/editor/release", {**claim, "lease_token": phone["lease_token"]})
        access.retry_at = 0
        access.tick()
        self.wait(lambda: access.writable() and not access.pending and not self.window.editor.isReadOnly())

    def test_close_during_open_releases_newly_acquired_lease(self):
        import uuid
        self.wait(lambda: not self.window.cloud.busy)
        access = self.window.cloud.editing
        identifier = access.active["id"]
        lease = self.window.cloud.session_api().request("api/editor/open", {"id": identifier, "client_id": access.client})
        lease["deadline"] = time.monotonic() + 15
        access.target, access.previous = self.path, self.path
        access.pending, access.close_after = True, True
        access.opened({"error": None, "value": lease})
        self.wait(lambda: access.closing_ready)
        self.assertEqual(self.phone.request("api/editor/open", {"id": identifier, "client_id": str(uuid.uuid4())})["id"], identifier)

    def test_failed_sync_on_end_releases_lease_without_losing_draft(self):
        import uuid
        access = self.window.cloud.editing
        identifier = access.active["id"]
        self.window.editor.insertPlainText("未联网的草稿")
        with patch.object(self.window.cloud.engine, "cycle", side_effect=CloudError("网络失败")):
            access.end_editing()
            self.wait(lambda: not access.pending and not access.active)
        self.assertIn("未联网的草稿", self.path.read_text(encoding="utf-8"))
        self.assertTrue(access.paused)
        access.tick()
        self.assertIsNone(access.active)
        self.assertEqual(self.phone.request("api/editor/open", {"id": identifier, "client_id": str(uuid.uuid4())})["id"], identifier)

    def test_waiting_local_draft_is_not_replaced_by_latest_cloud_content(self):
        import uuid
        access = self.window.cloud.editing
        identifier = access.active["id"]
        self.window.cloud.session_api().request("api/editor/release", dict(access.active))
        request = {"id": identifier, "client_id": str(uuid.uuid4())}
        phone = self.phone.request("api/editor/open", request)
        self.window.editor.insertPlainText("电脑未同步草稿")
        self.window.flush_auto_save()
        access.active = None
        access.request_open(self.path, force=True, quiet=True)
        self.wait(lambda: not access.pending)
        self.assertIn("电脑未同步草稿", self.path.read_text(encoding="utf-8"))
        self.assertTrue(self.window.editor.isReadOnly(), self.window.editing_label.text() + " / " + str(self.jobs))
        self.phone.request("api/editor/release", {**request, "lease_token": phone["lease_token"]})
        access.retry_at = 0
        access.tick()
        self.wait(lambda: access.writable() and not access.pending and not self.window.editor.isReadOnly())
        self.assertIn("电脑未同步草稿", self.window.editor.toPlainText())

    def test_end_during_open_releases_instead_of_retaining_a_background_lock(self):
        import uuid
        self.wait(lambda: not self.window.cloud.busy)
        access = self.window.cloud.editing
        identifier = access.active["id"]
        lease = self.window.cloud.session_api().request("api/editor/open", {"id": identifier, "client_id": access.client})
        lease["deadline"] = time.monotonic() + 15
        access.target, access.previous = self.path, self.path
        access.pending = True
        access.end_editing()
        access.opened({"error": None, "value": lease})
        self.wait(lambda: not access.pending and access.active is None)
        self.assertTrue(self.window.editor.isReadOnly())
        self.assertEqual(self.phone.request("api/editor/open", {"id": identifier, "client_id": str(uuid.uuid4())})["id"], identifier)


class InitialPublicationTests(unittest.TestCase):
    def test_first_publication_retains_active_ownership_without_unlock_gap(self):
        from types import SimpleNamespace
        import uuid
        calls = []
        class Transport:
            def request(self, route, body):
                calls.append((route, body))
                return {"lease_token": "test-proof", "expires_in": 60} if route == "api/editor/open" else {"ok": True}
        editing = SimpleNamespace(lock=threading.RLock(), active=None, client=str(uuid.uuid4()), paused=False)
        identifier = str(uuid.uuid4())
        LeaseApi(Transport(), editing).request("api/sync", {"id": identifier, "_active_editor": True})
        self.assertEqual(editing.active["id"], identifier)
        self.assertTrue(editing.active["initial"])
        self.assertEqual([route for route, _ in calls], ["api/editor/open", "api/sync"])
        self.assertNotIn("_active_editor", calls[-1][1])
