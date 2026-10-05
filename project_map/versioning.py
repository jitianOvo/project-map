from __future__ import annotations

import re
from dataclasses import dataclass


VERSION = re.compile(r"^([ \t]{0,3})(#{1,6})[ \t]+([Vv])(\d+(?:\.\d+)*)(?=[ \t]|$)(.*)$")
HEADING = re.compile(r"^[ \t]{0,3}(#{1,6})(?:[ \t]+|$)")
FENCE = re.compile(r"^[ \t]{0,3}(`{3,}|~{3,})")


@dataclass(frozen=True)
class VersionHeading:
    line: int
    level: int
    letter: str
    numbers: tuple[int, ...]


def markdown_content_lines(lines):
    fence = None
    for index, line in enumerate(lines):
        marker = FENCE.match(line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            continue
        if fence is None:
            yield index, line


def version_headings(lines):
    return [
        VersionHeading(index, len(match[2]), match[3], tuple(map(int, match[4].split("."))))
        for index, line in markdown_content_lines(lines)
        if (match := VERSION.match(line))
    ]


def change_number(line, number):
    match = VERSION.match(line)
    return line[:match.start(4)] + ".".join(map(str, number)) + line[match.end(4):]


def shift_following(lines, start, template, threshold, delta):
    valid = {heading.line: heading for heading in version_headings(lines)}
    parent_change = None
    for index, content in markdown_content_lines(lines):
        if index < start:
            continue
        heading = HEADING.match(content)
        if heading and len(heading[1]) < template.level and index not in valid:
            break
        version = valid.get(index)
        if version is None:
            continue
        if version.level < template.level:
            break
        if version.level == template.level:
            parent_change = None
            if version.numbers[:-1] != template.numbers[:-1]:
                break
            if version.numbers[-1] >= threshold:
                number = (*version.numbers[:-1], max(1, version.numbers[-1] + delta))
                lines[index] = change_number(lines[index], number)
                parent_change = (version.numbers, number)
        elif parent_change:
            old, new = parent_change
            if len(version.numbers) > len(old) and version.numbers[:len(old)] == old:
                lines[index] = change_number(lines[index], (*new, *version.numbers[len(old):]))


def insert_version(text, line, child=False):
    lines = text.split("\n")
    line = max(0, min(line, len(lines) - 1))
    # 在非空行后插入，保留已有正文和标题。
    insertion = line + 1 if lines[line].strip() else line
    preceding = [heading for heading in version_headings(lines) if heading.line < insertion]
    nearest = preceding[-1] if preceding else None
    if child and nearest:
        if nearest.level == 1:
            numbers, level, letter = (nearest.numbers[0], 1), 2, "v"
        else:
            numbers = (*nearest.numbers[:-1], nearest.numbers[-1] + 1)
            level, letter = nearest.level, nearest.letter
    elif child:
        numbers, level, letter = (1, 1), 2, "v"
    elif nearest:
        numbers = (*nearest.numbers[:-1], nearest.numbers[-1] + 1)
        level, letter = nearest.level, nearest.letter
    else:
        numbers, level, letter = (1,), 1, "V"
    template = VersionHeading(insertion, level, letter, numbers)
    shift_following(lines, insertion, template, numbers[-1], 1)
    header = "#" * level + " " + letter + ".".join(map(str, numbers))
    lines[insertion:insertion] = [header, ""]
    return "\n".join(lines), insertion + 1


def remove_versions(text, first, last):
    lines = text.split("\n")
    headings = version_headings(lines)
    selected = [heading for heading in headings if first <= heading.line <= last]
    if not selected:
        selected = [heading for heading in headings if heading.line <= first][-1:]
    for heading in reversed(selected):
        shift_following(lines, heading.line + 1, heading, heading.numbers[-1] + 1, -1)
        # 只删除版本标题，标题尾部的说明和段落正文保留。
        match = VERSION.match(lines[heading.line])
        lines[heading.line] = match[5].strip()
    return "\n".join(lines), bool(selected)
