from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import sys
from pathlib import Path

import paramiko


ROOT = Path(__file__).resolve().parents[1]


class ProjectHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    def missing_host_key(self, client, hostname, key):
        fingerprint = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
        print(f"服务器主机指纹 SHA256:{fingerprint}", flush=True)
        client.get_host_keys().add(hostname, key.get_name(), key)
        path = ROOT / ".state" / "ssh_known_hosts"
        path.parent.mkdir(exist_ok=True)
        client.save_host_keys(str(path))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", required=True)
    parser.add_argument("--user", default="root")
    args = parser.parse_args()
    client = paramiko.SSHClient()
    known = ROOT / ".state" / "ssh_known_hosts"
    if known.exists():
        client.load_host_keys(str(known))
    client.set_missing_host_key_policy(ProjectHostKeyPolicy())
    password = getpass.getpass("SSH 密码（不会保存）：")
    client.connect(args.host, username=args.user, password=password, look_for_keys=False, allow_agent=False, timeout=15)
    client.get_transport().set_keepalive(15)
    password = None
    print("SSH 已连接；等待 JSON 指令。", flush=True)
    scope = None
    for raw in sys.stdin:
        try:
            request = json.loads(raw)
            if "scope" in request:
                target = str(request["scope"])
                if not target.startswith("/") or target.rstrip("/").rsplit("/", 1)[-1] != "项目航图":
                    raise ValueError("服务端范围必须是绝对路径下新建的项目航图目录")
                scope = target.rstrip("/")
                print(json.dumps({"scope": scope}, ensure_ascii=False), flush=True)
                continue
            if "upload" in request:
                if scope is None:
                    raise ValueError("请先确认服务端目录范围")
                relative = request["upload"]
                path = (ROOT / relative).resolve()
                if not path.is_relative_to(ROOT):
                    raise ValueError("上传源必须位于本云项目中")
                remote_relative = request.get("to", relative).replace("\\", "/")
                if remote_relative.startswith("/") or ".." in remote_relative.split("/"):
                    raise ValueError("上传目的路径越界")
                with client.open_sftp() as sftp:
                    remote = scope + "/" + remote_relative
                    parent = remote.rsplit("/", 1)[0]
                    cursor = ""
                    for part in parent.split("/")[1:]:
                        cursor += "/" + part
                        try:
                            sftp.stat(cursor)
                        except FileNotFoundError:
                            sftp.mkdir(cursor)
                    sftp.put(str(path), remote)
                print(json.dumps({"uploaded": remote}, ensure_ascii=False), flush=True)
                continue
            if "download" in request:
                if scope is None:
                    raise ValueError("请先确认服务端目录范围")
                relative = request["download"].replace("\\", "/")
                local = (ROOT / request.get("to", relative)).resolve()
                if relative.startswith("/") or ".." in relative.split("/") or not local.is_relative_to(ROOT):
                    raise ValueError("下载路径越界")
                local.parent.mkdir(parents=True, exist_ok=True)
                with client.open_sftp() as sftp:
                    sftp.get(scope + "/" + relative, str(local))
                print(json.dumps({"downloaded": str(local)}, ensure_ascii=False), flush=True)
                continue
            if request.get("exit"):
                break
            _stdin, stdout, stderr = client.exec_command(request["cmd"], timeout=request.get("timeout", 30))
            output = stdout.read().decode("utf-8", errors="replace")
            error = stderr.read().decode("utf-8", errors="replace")
            print(json.dumps({"exit": stdout.channel.recv_exit_status(), "stdout": output, "stderr": error}, ensure_ascii=False), flush=True)
        except Exception as error:
            print(json.dumps({"error": str(error)}, ensure_ascii=False), flush=True)
    client.close()


if __name__ == "__main__":
    main()
