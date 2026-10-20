import time

import pytest
from urllib.error import HTTPError

from test_server import service, request


def login(url, remember=True):
    return request(url, "/api/login", {"username": "owner", "password": "测试密码", "auto_login": remember})


def test_remembered_session_refresh_and_logout(service):
    server, url = service
    account = login(url)
    assert account["refresh_token"]
    assert request(url, "/api/session", token=account["token"])["ok"]
    with server.storage.lock, server.storage.db:
        server.storage.db.execute("UPDATE sessions SET expires=?", (time.time() - 1,))
    with pytest.raises(HTTPError):
        request(url, "/api/session", token=account["token"])
    refreshed = request(url, "/api/session/refresh", {"refresh_token": account["refresh_token"]})
    assert request(url, "/api/session", token=refreshed["token"])["ok"]
    request(url, "/api/logout", {}, refreshed["token"])
    with pytest.raises(HTTPError):
        request(url, "/api/session/refresh", {"refresh_token": account["refresh_token"]})


def test_unchecked_does_not_issue_long_lived_login(service):
    server, url = service
    assert not login(url, False)["refresh_token"]
    assert server.storage.db.execute("SELECT COUNT(*) FROM remembered_sessions").fetchone()[0] == 0


def test_refresh_response_loss_can_retry_without_password(service):
    server, url = service
    account = login(url)
    first = request(url, "/api/session/refresh", {"refresh_token": account["refresh_token"]})
    second = request(url, "/api/session/refresh", {"refresh_token": account["refresh_token"]})
    assert first["token"] != second["token"]
    assert request(url, "/api/session", token=second["token"])["ok"]
    assert server.storage.db.execute("SELECT COUNT(*) FROM remembered_sessions").fetchone()[0] == 1


def test_logout_with_expired_access_revokes_remembered_login(service):
    server, url = service
    account = login(url)
    with server.storage.lock, server.storage.db:
        server.storage.db.execute("UPDATE sessions SET expires=0")
    request(url, "/api/session/logout", {"refresh_token": account["refresh_token"]})
    with pytest.raises(HTTPError):
        request(url, "/api/session/refresh", {"refresh_token": account["refresh_token"]})


def test_invalid_or_expired_refresh_does_not_grant_access(service):
    server, url = service
    account = login(url)
    with server.storage.lock, server.storage.db:
        server.storage.db.execute("UPDATE remembered_sessions SET expires=0")
    for value in (account["refresh_token"], "x" * 64, "", 123):
        with pytest.raises(HTTPError) as error:
            request(url, "/api/session/refresh", {"refresh_token": value})
        assert error.value.code == 401
