import base64
import hashlib
import json
import threading
import uuid
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

from server.auth import initialize, password_hash
from server.http import CloudServer
from server.merge import merge_text
from server.storage import Storage


@pytest.fixture
def store(tmp_path):
    storage = Storage(tmp_path / "database.sqlite3")
    yield storage
    storage.db.close()


def save(store, doc_id, content, revision=0, **fields):
    return store.sync({"id": doc_id, "op_id": str(uuid.uuid4()), "base_revision": revision, "device_id": "测试设备", "document": {"content": content, **fields}})


def test_disjoint_merge(store):
    doc_id = str(uuid.uuid4())
    save(store, doc_id, "第一行\n第二行\n第三行\n")
    save(store, doc_id, "电脑修改\n第二行\n第三行\n", 1)
    result = save(store, doc_id, "第一行\n第二行\n手机修改\n", 1)
    assert result["status"] == "merged"
    assert result["document"]["content"] == "电脑修改\n第二行\n手机修改\n"


def test_conflict_preserves_both(store):
    doc_id = str(uuid.uuid4())
    save(store, doc_id, "原内容")
    save(store, doc_id, "电脑", 1)
    result = save(store, doc_id, "手机", 1)
    assert result["status"] == "conflict"
    assert result["document"]["content"] == "电脑"
    assert result["conflict"]["content"] == "手机"
    assert len(store.changes(0)["documents"]) == 2


def test_retry_idempotent(store):
    request = {"id": str(uuid.uuid4()), "op_id": str(uuid.uuid4()), "base_revision": 0, "document": {"content": "重试内容"}}
    assert store.sync(request) == store.sync(request)
    assert len(store.history(request["id"])) == 1


def test_metadata_merge_and_conflict(store):
    doc_id = str(uuid.uuid4())
    save(store, doc_id, "内容", title="初始")
    save(store, doc_id, "内容", 1, title="电脑改名")
    result = save(store, doc_id, "手机内容", 1, title="初始")
    assert result["document"]["title"] == "电脑改名"
    assert result["document"]["content"] == "手机内容"
    assert save(store, doc_id, "内容", 1, title="手机改名")["status"] == "conflict"


def test_delete_vs_edit_preserved(store):
    doc_id = str(uuid.uuid4())
    save(store, doc_id, "内容")
    save(store, doc_id, "内容", 1, deleted=True)
    result = save(store, doc_id, "编辑后的内容", 1)
    assert result["status"] == "conflict"
    assert result["document"]["deleted"]
    assert not result["conflict"]["deleted"]


def test_merge_boundaries():
    assert merge_text("a\nb\n", "x\na\nb\n", "a\nb\ny\n") == "x\na\nb\ny\n"
    assert merge_text("a\n", "x\na\n", "y\na\n") is None
    assert merge_text("", "x", "y") is None


def test_large_merge_falls_back_without_expensive_diff():
    base="重复行\n"*3000
    assert merge_text(base,"电脑\n"+base,base+"手机\n") is None


def test_invalid_fields_do_not_write(store):
    with pytest.raises(ValueError):
        save(store,str(uuid.uuid4()),"文字",pinned="yes")
    assert store.changes(0)["documents"]==[]


def test_same_names_remain_separate(store):
    first=save(store,str(uuid.uuid4()),"文件一",title="同名")
    second=save(store,str(uuid.uuid4()),"文件二",title="同名")
    assert first["document"]["id"]!=second["document"]["id"]
    assert len(store.changes(0)["documents"])==2


@pytest.fixture
def service(tmp_path):
    initialize(tmp_path)
    account = tmp_path / ".secrets" / "account.json"
    salt = "00" * 16
    account.write_text(json.dumps({"username": "owner", "salt": salt, "hash": password_hash("测试密码", salt)}))
    server = CloudServer(("127.0.0.1", 0), tmp_path)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    yield server, f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    worker.join()
    server.server_close()


def request(url, path, body=None, token=""):
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = "Bearer " + token
    call = Request(url + path, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with urlopen(call, timeout=10) as response:
        return json.loads(response.read())


def test_auth_and_media(service):
    server, url = service
    assert request(url, "/api/health")["ok"]
    with pytest.raises(HTTPError) as error:
        request(url, "/api/changes")
    assert error.value.code == 401
    token = request(url, "/api/login", {"username": "owner", "password": "测试密码"})["token"]
    data = b"\x89PNG\r\n\x1a\n" + b"test"
    identifier = hashlib.sha256(data).hexdigest()
    result = request(url, "/api/media", {"id": identifier, "data": base64.b64encode(data).decode()}, token)
    assert result["id"] == identifier
    assert request(url, "/api/media/" + identifier, token=token)["data"] == base64.b64encode(data).decode()
    request(url, "/api/logout", {}, token)
    with pytest.raises(HTTPError):
        request(url, "/api/changes", token=token)


def test_invalid_path_and_hash(service):
    _server, url = service
    token = request(url, "/api/login", {"username": "owner", "password": "测试密码"})["token"]
    for path in ("/../.secrets/account.json", "/%2e%2e/.secrets/account.json", "/api/media/../../account.json"):
        with pytest.raises(HTTPError):
            request(url, path, token=token)
    with pytest.raises(HTTPError):
        request(url, "/api/media", {"id": "0" * 64, "data": "aGVsbG8="}, token)
