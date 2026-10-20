from __future__ import annotations

import unittest
from unittest.mock import patch

from PySide6.QtTest import QTest

import test_workflow as workflow
from project_map.cloud.api import Api, CloudError
from project_map.cloud.controller import CloudController
from project_map.cloud.credentials import load_account, load_token, save_account
from project_map.cloud.session import SessionApi
from project_map.file_io import read_json


class AutoLoginTests(unittest.TestCase):
    setUp = workflow.WindowTests.setUp
    tearDown = workflow.WindowTests.tearDown

    def wait(self, predicate):
        for _ in range(400):
            if predicate():
                return
            QTest.qWait(10)
        self.fail("登录任务没有及时完成")

    def test_login_remembers_protected_tokens_but_never_password(self):
        cloud = self.window.cloud
        reply = {"token": "desktop-access-fixture", "refresh_token": "desktop-refresh-fixture"}
        with patch("project_map.cloud.controller.Api") as api:
            api.return_value.request.return_value = reply
            cloud.login(cloud.config["endpoint"], "owner", "password-only-for-test", True)
            self.wait(lambda: not cloud.busy)
        cloud.timer.stop()
        self.assertEqual(load_account(cloud.auth_path, cloud.config["endpoint"])["refresh_token"], reply["refresh_token"])
        disk = cloud.auth_path.read_text(encoding="utf-8")
        self.assertNotIn("desktop-access-fixture", disk)
        self.assertNotIn("desktop-refresh-fixture", disk)
        self.assertNotIn("password-only-for-test", disk)
        self.assertNotIn("token", cloud.config)
        self.assertTrue(api.return_value.request.call_args.args[1]["auto_login"])

    def test_unchecked_works_in_memory_and_leaves_nothing_to_restore(self):
        cloud = self.window.cloud
        with patch("project_map.cloud.controller.Api") as api:
            api.return_value.request.return_value = {"token": "this-session-only", "refresh_token": ""}
            cloud.login(cloud.config["endpoint"], "owner", "test-only", False)
            self.wait(lambda: not cloud.busy)
        cloud.timer.stop()
        self.assertEqual(cloud.session["token"], "this-session-only")
        self.assertEqual(load_token(cloud.auth_path, cloud.config["endpoint"]), "")
        self.assertFalse(cloud.config["auto_login"])

    def test_reopening_renews_expired_session_without_password(self):
        old = self.window.cloud
        old.save_config(auto_login=True, enabled=False)
        save_account(old.auth_path, old.config["endpoint"], {"token": "expired-test", "refresh_token": "valid-remember-test", "username": "owner"})
        old.shutdown()
        def reply(client, route, body=None):
            if route == "api/session/refresh":
                self.assertEqual(body, {"refresh_token": "valid-remember-test"})
                return {"token": "renewed-test"}
            if client.token == "expired-test":
                raise CloudError("过期", 401)
            return {"ok": True}
        with patch.object(Api, "request", reply):
            self.window.cloud = CloudController(self.window)
            self.wait(lambda: "已自动登录" in self.window.cloud.status)
        self.assertEqual(self.window.cloud.session["token"], "renewed-test")
        self.assertEqual(load_token(old.auth_path, old.config["endpoint"]), "renewed-test")
        self.assertFalse(self.window.cloud.config["enabled"])

    def test_refresh_failure_keeps_credentials_for_offline_retry(self):
        cloud = self.window.cloud
        cloud.set_session({"token": "expired-test", "refresh_token": "remember-test"})
        def reply(client, route, body=None):
            raise CloudError("临时断网", 0 if route == "api/session/refresh" else 401)
        with patch.object(Api, "request", reply):
            with self.assertRaises(CloudError):
                cloud.session_api().request("api/session")
        self.assertEqual(load_account(cloud.auth_path, cloud.config["endpoint"])["refresh_token"], "remember-test")

    def test_logout_forgets_credentials_and_uses_refresh_revocation(self):
        cloud = self.window.cloud
        cloud.set_session({"token": "expired-test", "refresh_token": "remember-test"})
        with patch("project_map.cloud.controller.Api") as api:
            api.return_value.request.return_value = {"ok": True}
            cloud.logout()
            self.wait(lambda: not cloud.busy)
        self.assertEqual(read_json(cloud.auth_path), {})
        self.assertFalse(cloud.session)
        self.assertEqual(api.return_value.request.call_args.args[0], "api/session/logout")

    def test_cancel_remember_and_endpoint_switch_cannot_reuse_saved_account(self):
        cloud = self.window.cloud
        cloud.set_session({"token": "fixture-access", "refresh_token": "fixture-refresh"})
        cloud.save_config(auto_login=False)
        self.assertEqual(read_json(cloud.auth_path), {})
        self.assertEqual(cloud.session["token"], "fixture-access")
        cloud.save_config(endpoint="https://example.test/", enabled=False)
        self.assertFalse(cloud.session)
