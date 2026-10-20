from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from .auth import initialize
from .http import CloudServer


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description="项目航图独立云服务")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18770)
    parser.add_argument("--init", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    initialize(ROOT)
    if args.init:
        print("应用账户已初始化；首次登录信息位于本项目 .secrets/首次登录.txt")
        return
    runtime = ROOT / "runtime"
    runtime.mkdir(mode=0o700, exist_ok=True)
    logging.basicConfig(filename=runtime / "server.log", level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    server = CloudServer((args.host, args.port), ROOT)
    print(f"项目航图云端已启动：{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
