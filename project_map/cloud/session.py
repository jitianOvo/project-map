from __future__ import annotations

from .api import Api, CloudError


class SessionApi(Api):
    def __init__(self, endpoint, account, on_refresh=None):
        super().__init__(endpoint, account.get("token", ""))
        self.account = dict(account)
        self.on_refresh = on_refresh

    def request(self, route, body=None):
        try:
            return super().request(route, body)
        except CloudError as error:
            refresh = self.account.get("refresh_token", "")
            if error.status != 401 or not refresh:
                raise
        result = Api(self.endpoint).request("api/session/refresh", {"refresh_token": refresh})
        self.token = result["token"]
        self.account["token"] = self.token
        if self.on_refresh:
            self.on_refresh(self.account)
        return super().request(route, body)
