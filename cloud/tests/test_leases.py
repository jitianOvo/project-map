from concurrent.futures import ThreadPoolExecutor
import json
import time
import uuid
from unittest.mock import patch
from urllib.error import HTTPError

import pytest

from server.leases import LeaseConflict, LEASE_SECONDS
from test_server import service, request, store


def claim(identifier=None):
    return {"id": identifier or str(uuid.uuid4()), "client_id": str(uuid.uuid4())}


def proof(storage, owner, item):
    return {**item, "lease_token": storage.leases.open(item, owner)["lease_token"]}


def test_same_document_exclusive_different_documents_allowed(store):
    first = claim()
    pc = proof(store, "Windows-test", first)
    with pytest.raises(LeaseConflict, match="电脑端"):
        store.leases.open(claim(first["id"]), "手机-test")
    phone = proof(store, "手机-test", claim())
    assert phone["id"] != pc["id"]
    store.leases.release(pc, "Windows-test")
    assert store.leases.open(claim(pc["id"]), "手机-test")["id"] == pc["id"]


def test_concurrent_claim_has_exactly_one_winner(store):
    identifier = str(uuid.uuid4())
    def compete(index):
        try:
            store.leases.open(claim(identifier), "设备-" + str(index))
            return True
        except LeaseConflict:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(compete, range(8))) == 1


def test_old_token_cannot_write_after_expiry_or_release_new_owner(store):
    old = proof(store, "Windows-test", claim())
    with patch("server.leases.time.time", return_value=time.time() + 70):
        new = proof(store, "手机-test", claim(old["id"]))
        store.leases.release(old, "Windows-test")
        with pytest.raises(LeaseConflict):
            store.sync({**old, "op_id": str(uuid.uuid4()), "base_revision": 0, "document": {"content": "过期写入"}}, "Windows-test")
        saved = store.sync({**new, "op_id": str(uuid.uuid4()), "base_revision": 0, "document": {"content": "新端写入"}}, "手机-test")
        assert saved["document"]["content"] == "新端写入"


def test_renew_extends_lease_and_retry_keeps_idempotency(store):
    item = proof(store, "电脑-test", claim())
    assert store.leases.renew(item, "电脑-test")["expires_in"] == LEASE_SECONDS
    operation = {**item, "op_id": str(uuid.uuid4()), "base_revision": 0, "document": {"content": "已确认"}}
    response = store.sync(operation, "电脑-test")
    store.leases.release(item, "电脑-test")
    assert store.sync(operation, "电脑-test") == response
    assert len(store.history(item["id"])) == 1


def test_open_returns_latest_after_handoff(store):
    pc = proof(store, "电脑-test", claim())
    store.sync({**pc, "op_id": str(uuid.uuid4()), "base_revision": 0, "document": {"content": "最新正文"}}, "电脑-test")
    store.leases.release(pc, "电脑-test")
    reply = store.leases.open(claim(pc["id"]), "手机-test")
    assert reply["document"]["content"] == "最新正文"
    assert reply["document"]["revision"] == 1


def test_same_device_other_window_does_not_share_ownership(store):
    pc = proof(store, "Windows-test", claim())
    with pytest.raises(LeaseConflict):
        store.leases.open(claim(pc["id"]), "Windows-test")


def test_http_uses_authenticated_device_not_supplied_name(service):
    server, url = service
    tokens = [request(url, "/api/login", {"username": "owner", "password": "测试密码", "device_id": device})["token"]
              for device in ("Windows-test", "手机-test")]
    pc = claim()
    opened = request(url, "/api/editor/open", pc, tokens[0])
    with pytest.raises(HTTPError) as error:
        request(url, "/api/sync", {**pc, "lease_token": opened["lease_token"], "device_id": "Windows-test",
                                   "op_id": str(uuid.uuid4()), "base_revision": 0, "document": {"content": "冒用名称"}}, tokens[1])
    assert error.value.code == 423
    assert json.loads(error.value.read())["owner"] == "电脑端"
    assert server.storage.changes(0)["documents"] == []


def test_unauthenticated_lock_request_rejected(service):
    _, url = service
    with pytest.raises(HTTPError) as error:
        request(url, "/api/editor/open", claim())
    assert error.value.code == 401


def test_same_installation_recovers_and_fences_delayed_old_release(store):
    request = claim()
    old = proof(store, "Windows-test", request)
    recovered = store.leases.open({**request, "recover": True}, "Windows-test")
    assert recovered["lease_token"] != old["lease_token"]
    store.leases.release(old, "Windows-test")
    with pytest.raises(LeaseConflict):
        store.leases.renew(old, "Windows-test")
    current = {**request, "lease_token": recovered["lease_token"]}
    assert store.leases.renew(current, "Windows-test")["expires_in"] == LEASE_SECONDS
    with pytest.raises(LeaseConflict):
        store.leases.open(claim(request["id"]), "手机-test")


def test_crashed_owner_expires_in_twenty_seconds_without_clearing_data(store):
    first = proof(store, "Windows-test", claim())
    store.sync({**first, "op_id": str(uuid.uuid4()), "base_revision": 0, "document": {"content": "必须保留的正文"}}, "Windows-test")
    with patch("server.leases.time.time", return_value=time.time() + LEASE_SECONDS + 1):
        reply = store.leases.open(claim(first["id"]), "手机-test")
        assert reply["document"]["content"] == "必须保留的正文"
