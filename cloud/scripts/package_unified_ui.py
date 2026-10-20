from __future__ import annotations

import hashlib
import json
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
output = ROOT / ".state" / "unified-ui.tar.gz"
output.parent.mkdir(exist_ok=True)
with tarfile.open(output, "w:gz") as archive:
    public = ROOT / "server" / "public"
    for path in sorted(public.rglob("*")):
        if path.is_file() and path != public / "downloads" / "project-map.apk":
            archive.add(path, arcname=path.relative_to(ROOT), recursive=False)
    archive.add(ROOT / "dist" / "project-map.apk", arcname="server/public/downloads/project-map.apk", recursive=False)
print(json.dumps({"archive": str(output), "bytes": output.stat().st_size, "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}, ensure_ascii=False))
