from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

ROOT=Path(__file__).resolve().parents[1]
BASE="https://jitian666.me/project-map/"
client=build_opener(ProxyHandler({}))


def request(path,body=None,token=""):
    headers={"Content-Type":"application/json"}
    if token:headers["Authorization"]="Bearer "+token
    with client.open(Request(BASE+path,data=json.dumps(body).encode() if body is not None else None,headers=headers),timeout=30) as response:
        return json.loads(response.read())


health=request("api/health")
try:request("api/changes")
except HTTPError as error:assert error.code==401
else:raise RuntimeError("未登录请求不应访问私人内容")
login=(ROOT/".secrets/云端首次登录.txt").read_text(encoding="utf-8")
username=re.search(r"账户：(.*)",login).group(1).strip()
password=re.search(r"密码：(.*)",login).group(1).strip()
token=request("api/login",{"username":username,"password":password,"device_id":"上线验证"})["token"]
try:
    documents=request("api/changes",token=token)
    result={"https":True,"authentication":True,"version":health["version"],"project_count":len(documents["documents"])}
finally:request("api/logout",{},token)
with client.open(BASE+"downloads/project-map.apk",timeout=30) as response:
    data=response.read()
    result["apk_sha256"]=hashlib.sha256(data).hexdigest()
    assert result["apk_sha256"]==hashlib.sha256((ROOT/"dist/project-map.apk").read_bytes()).hexdigest()
(ROOT/".state/live-verification.json").write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(result,ensure_ascii=False))
