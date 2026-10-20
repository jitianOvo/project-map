"""仅在获得 HTTPS 路由和专属启动服务授权后执行。"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
UNIT = Path("/etc/systemd/system/project-map-cloud.service")


def command(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--authorized-proxy-and-service",action="store_true",required=True)
    parser.parse_args()
    if ROOT != Path("/root/项目航图") or os.geteuid()!=0:
        raise SystemExit("部署范围或身份不符")
    config=Path("/etc/nginx/sites-enabled/default").resolve(strict=True)
    content=config.read_text()
    marker="    server_name jitian666.me www.jitian666.me; # managed by Certbot"
    include='    include "/root/项目航图/deploy/nginx-location.conf";'
    if content.count(marker)!=1:
        raise SystemExit("HTTPS 配置不符合已检查结构，未修改")
    if UNIT.exists() and UNIT.read_bytes()!=(ROOT/"deploy/project-map-cloud.service").read_bytes():
        raise SystemExit("服务名称已被其他内容占用，未覆盖")
    backup=ROOT/".deploy"/time.strftime("%Y%m%d-%H%M%S")
    backup.mkdir(parents=True,mode=0o700)
    shutil.copy2(config,backup/"nginx-default.before")
    existed=UNIT.exists()
    if existed:shutil.copy2(UNIT,backup/"service.before")
    updated=content if include in content else content.replace(marker,marker+"\n"+include,1)
    try:
        config.write_text(updated)
        command("nginx","-t")
        shutil.copy2(ROOT/"deploy/project-map-cloud.service",UNIT)
        os.chmod(UNIT,0o644)
        command("systemctl","daemon-reload")
        command("systemctl","enable","--now","project-map-cloud.service")
        command("systemctl","reload","nginx")
        command("systemctl","is-active","project-map-cloud.service")
    except Exception:
        shutil.copy2(backup/"nginx-default.before",config)
        if existed:shutil.copy2(backup/"service.before",UNIT)
        else:
            subprocess.run(["systemctl","disable","--now","project-map-cloud.service"],capture_output=True)
            UNIT.unlink(missing_ok=True)
        subprocess.run(["systemctl","daemon-reload"],capture_output=True)
        raise
    result={"nginx_config":str(config),"backup":str(backup),"unit":str(UNIT),"original_sha256":hashlib.sha256(content.encode()).hexdigest(),"updated_sha256":hashlib.sha256(updated.encode()).hexdigest(),"url":"https://jitian666.me/project-map/"}
    (ROOT/".deploy/deployment.json").write_text(json.dumps(result,ensure_ascii=False,indent=2))
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":main()
