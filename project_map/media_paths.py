from __future__ import annotations

import hashlib
import html
from pathlib import Path
from urllib.parse import unquote, urlparse


def resolve_image(source, document_path, search_dirs=()):
    source = html.unescape(str(source).strip().strip("<>"))
    if source.casefold().startswith("file:"):
        parsed = urlparse(source)
        source = unquote(parsed.path)
        if parsed.netloc and parsed.netloc.casefold() != "localhost":
            source = "//" + parsed.netloc + source
        elif source.startswith("/") and len(source) > 2 and source[2] == ":":
            source = source[1:]
    else:
        source = unquote(source)
    path = Path(source.replace("\\", "/"))
    parent = Path(document_path).parent
    folders = [parent / "Media", parent.parent / "Media", *(Path(folder) for folder in search_dirs)]
    if path.is_absolute():
        if path.is_file():
            return path
        # A relocated absolute reference must not pick an arbitrary same-name image.
        matches = {candidate.resolve() for folder in folders if (candidate := folder / path.name).is_file()}
        if len(matches) == 1:
            return next(iter(matches))
        if len(matches) > 1:
            try:
                digests = {hashlib.sha256(candidate.read_bytes()).digest() for candidate in matches}
            except OSError:
                return None
            if len(digests) == 1:
                return sorted(matches, key=str)[0]
        return None
    candidates = [parent / path, parent.parent / path]
    parts = list(path.parts)
    while parts and parts[0] == "..":
        parts.pop(0)
    if parts and parts[0].casefold() == "media":
        parts.pop(0)
    candidates.extend(folder.joinpath(*parts) for folder in folders)
    return next((candidate for candidate in candidates if candidate.is_file()), None)
