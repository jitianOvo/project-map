from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

DEFAULT_ENDPOINT = "https://jitian666.me/project-map/"


class CloudError(RuntimeError):
    def __init__(self, message, status=0, details=None):
        super().__init__(message)
        self.status = status
        self.details = details or {}


def normalize_endpoint(value):
    parsed = urlparse(value.strip())
    if parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.hostname:
        raise ValueError("服务器地址不能包含账号、密码、参数或锚点")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost"}):
        raise ValueError("服务器地址必须使用 HTTPS")
    return value.strip().rstrip("/") + "/"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


class Api:
    def __init__(self, endpoint, token="", timeout=8):
        self.endpoint = normalize_endpoint(endpoint)
        self.token = token
        self.timeout = timeout
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def request(self, route, body=None):
        if not re.fullmatch(r"api/[a-zA-Z0-9/?=&_-]+", route):
            raise ValueError("云接口地址无效")
        data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = Request(self.endpoint + route, data=data, headers=headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read(19 * 1024 * 1024 + 1)
                if len(raw) > 19 * 1024 * 1024:
                    raise CloudError("云响应过大，本地资料保持不变")
                return json.loads(raw)
        except HTTPError as error:
            details = {}
            message = "登录已失效，请重新登录" if error.code == 401 else "云请求失败，本地资料已保留"
            try:
                details = json.loads(error.read(4096))
                detail = details.get("error", "")
                if isinstance(detail, str) and detail:
                    message += "：" + detail[:200]
            except (ValueError, OSError):
                pass
            raise CloudError(message, error.code, details) from error
        except (URLError, TimeoutError, OSError) as error:
            raise CloudError("暂时连接不到云端，本地编辑和保存不受影响") from error
