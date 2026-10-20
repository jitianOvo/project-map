from __future__ import annotations

from difflib import SequenceMatcher


def merge_text(base: str, local: str, remote: str) -> str | None:
    if local == remote or remote == base:
        return local
    if local == base:
        return remote
    original = base.splitlines(keepends=True)
    changes = []
    for text in (local, remote):
        lines = text.splitlines(keepends=True)
        if len(original) * len(lines) > 4_000_000:
            return None
        edits = [(start, end, lines[new_start:new_end]) for tag, start, end, new_start, new_end in SequenceMatcher(None, original, lines, autojunk=False).get_opcodes() if tag != "equal"]
        for edit in edits:
            if edit in changes:
                continue
            start, end, _replacement = edit
            for other_start, other_end, _other in changes:
                overlap = max(start, other_start) < min(end, other_end)
                inserted = start == end and other_start <= start < other_end
                other_inserted = other_start == other_end and start <= other_start < end
                same_insert = start == end == other_start == other_end
                if overlap or inserted or other_inserted or same_insert:
                    return None
            changes.append(edit)
    for start, end, replacement in sorted(changes, key=lambda item: (item[0], item[1]), reverse=True):
        original[start:end] = replacement
    return "".join(original)


def merge_document(base: dict, local: dict, remote: dict) -> dict | None:
    if (local.get("deleted") != base.get("deleted") and remote != base) or (remote.get("deleted") != base.get("deleted") and local != base):
        if local != remote:
            return None
    content = merge_text(base["content"], local["content"], remote["content"])
    if content is None:
        return None
    merged = {"content": content}
    for key in ("title", "group", "description", "priority", "pinned", "order", "deleted", "project_path"):
        before, first, second = base.get(key), local.get(key), remote.get(key)
        if first != before and second != before and first != second:
            return None
        merged[key] = second if first == before else first
    return merged
