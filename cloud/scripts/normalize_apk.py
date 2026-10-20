from __future__ import annotations

import copy
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def normalize(path):
    path = Path(path).resolve(strict=True)
    if not path.is_relative_to(ROOT / ".cache") or path.suffix != ".apk":
        raise ValueError("只能规范本项目构建缓存内的未签名 APK")
    temporary = path.with_suffix(".normalized.apk")
    with zipfile.ZipFile(path) as source, zipfile.ZipFile(temporary, "w") as target:
        names = set()
        for entry in source.infolist():
            name = entry.filename.replace("\\", "/")
            if name in names:
                raise ValueError("APK 资源路径重复：" + name)
            names.add(name)
            item = copy.copy(entry)
            item.filename = item.orig_filename = name
            target.writestr(item, source.read(entry))
        if "assets/web/index.html" not in names or "assets/web/auth.js" not in names:
            raise ValueError("APK 缺少规范路径的内置编辑与登录资源")
    with zipfile.ZipFile(temporary) as archive:
        if archive.testzip() is not None:
            raise ValueError("APK 资源校验失败")
    os.replace(temporary, path)
    print("APK 离线资源路径与 CRC 校验通过。")


if __name__ == "__main__":
    normalize(sys.argv[1])
