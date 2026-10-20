from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

from ..file_io import atomic_write
from ..media_paths import resolve_image

IMAGE = re.compile(r"(!\[[^\]\n]*\]\()(<[^>\n]+>|[^)\n]+)(\))")
HTML_IMAGE = re.compile(r'(<img\b[^>]*\bsrc=["\'])([^"\']+)(["\'])', re.IGNORECASE)
CLOUD_IMAGE = re.compile(r"(?:cloud-media://|Media/)([a-f0-9]{64})(?:\.(?:png|jpg|jpeg|gif|webp))?", re.IGNORECASE)


class MissingImage(ValueError):
    def __init__(self, source):
        self.source = source
        super().__init__(f"图片未找到：{source}；请恢复原图，或将图片所在文件夹加入“图片缓存设置”后重试")


def image_extension(data):
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    raise ValueError("云同步图片支持 PNG、JPEG、GIF、WebP，请先转换这张图片")


class Assets:
    def __init__(self, media, search_dirs=()):
        self.media = Path(media)
        self.search_dirs = [self.media, *(Path(path) for path in search_dirs)]
        self.cache = {}

    def resolve(self, source, document_path):
        return resolve_image(source, document_path, self.search_dirs)

    def cloud_content(self, content, document_path):
        images = {}
        literal_ranges = []
        fence_start = None
        fence_marker = ""
        offset = 0
        for line in content.splitlines(keepends=True):
            fence = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
            if fence and fence_start is None:
                fence_start, fence_marker = offset, fence[1][0]
            elif fence and fence_start is not None and fence[1][0] == fence_marker:
                literal_ranges.append((fence_start, offset + len(line)))
                fence_start = None
            offset += len(line)
        if fence_start is not None:
            literal_ranges.append((fence_start, len(content)))
        literal_ranges.extend((match.start(), match.end()) for match in re.finditer(r"(`+)(?:(?!\1).)*?\1", content))

        def replace(match):
            if any(start <= match.start() < end for start, end in literal_ranges):
                return match[0]
            groups = match.groups()
            prefix, source, suffix = groups[:3] if groups[0] is not None else groups[3:]
            if source.startswith(("https://", "http://", "data:")):
                return match[0]
            bare = source
            title = ""
            if not source.startswith("<"):
                title_match = re.match(r'^(.*?)\s+("[^"\n]*"|\'[^\'\n]*\')$', source)
                if title_match:
                    bare, title = title_match.groups()
                    title = " " + title
            path = self.resolve(bare, document_path)
            if path is None:
                raise MissingImage(bare)
            stat = path.stat()
            key = (str(path.resolve()), stat.st_mtime_ns, stat.st_size)
            cached = self.cache.get(key)
            if cached is None:
                data = path.read_bytes()
                if len(data) > 12 * 1024 * 1024:
                    raise ValueError(f"图片超过 12 MB：{path.name}")
                cached = (hashlib.sha256(data).hexdigest(), image_extension(data))
                self.cache[key] = cached
            digest, extension = cached
            cached_path = self.media / (digest + extension)
            if not cached_path.exists():
                atomic_write(cached_path, path.read_bytes())
            images[digest] = cached_path
            return prefix + f"Media/{digest}{extension}" + title + suffix

        combined = re.compile(IMAGE.pattern + "|" + HTML_IMAGE.pattern, re.IGNORECASE)
        converted = combined.sub(replace, content)
        return converted, images

    def upload(self, api, images, uploaded):
        known = set(uploaded)
        for digest, path in images.items():
            if digest in known:
                continue
            api.request("api/media", {"id": digest, "data": base64.b64encode(path.read_bytes()).decode()})
            uploaded.append(digest)
            known.add(digest)

    def download(self, api, content):
        for digest in dict.fromkeys(match[1].lower() for match in CLOUD_IMAGE.finditer(content)):
            existing = [self.media / (digest + suffix) for suffix in (".png", ".jpg", ".jpeg", ".gif", ".webp")]
            if any(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest for path in existing):
                continue
            response = api.request("api/media/" + digest)
            data = base64.b64decode(response["data"], validate=True)
            if len(data) > 12 * 1024 * 1024 or hashlib.sha256(data).hexdigest() != digest:
                raise ValueError("云图片校验失败，本地资料未覆盖")
            atomic_write(self.media / (digest + image_extension(data)), data)
