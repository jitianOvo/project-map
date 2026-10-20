from __future__ import annotations

from difflib import SequenceMatcher

FIELDS = {
    "content": "", "title": "新项目", "group": "默认项目", "description": "",
    "priority": "", "pinned": False, "order": 0, "deleted": False, "project_path": "",
}


def payload(value):
    return {key: value.get(key, default) for key, default in FIELDS.items()}


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
                if (max(start, other_start) < min(end, other_end)
                    or start == end and other_start <= start < other_end
                    or other_start == other_end and start <= other_start < end
                    or start == end == other_start == other_end):
                    return None
            changes.append(edit)
    for start, end, replacement in sorted(changes, key=lambda item: (item[0], item[1]), reverse=True):
        original[start:end] = replacement
    return "".join(original)


def merge_document(base, local, remote):
    base, local, remote = payload(base), payload(local), payload(remote)
    if (local["deleted"] != base["deleted"] and remote != base) or (remote["deleted"] != base["deleted"] and local != base):
        if local != remote:
            return None
    content = merge_text(base["content"], local["content"], remote["content"])
    if content is None:
        return None
    merged = {"content": content}
    for key in FIELDS.keys() - {"content"}:
        before, first, second = base[key], local[key], remote[key]
        if first != before and second != before and first != second:
            return None
        merged[key] = second if first == before else first
    return merged
