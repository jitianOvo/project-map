from pathlib import Path
import tarfile

root=Path(__file__).resolve().parents[1]
archive=root/".state/server-source.tar.gz"
archive.parent.mkdir(exist_ok=True)
with tarfile.open(archive,"w:gz") as package:
    for folder in ("server","deploy","web","android","windows","docs","tests","scripts"):
        for source in (root/folder).rglob("*"):
            if source.is_file() and "__pycache__" not in source.parts and source != root/"server/public/downloads/project-map.apk":
                package.add(source,arcname=source.relative_to(root).as_posix(),recursive=False)
    for name in ("README.md","package.json","package-lock.json",".gitignore","启动Windows云端版.bat"):
        package.add(root/name,arcname=name)
    package.add(root/"dist/project-map.apk",arcname="server/public/downloads/project-map.apk",recursive=False)
print("服务端发布包已生成。")
