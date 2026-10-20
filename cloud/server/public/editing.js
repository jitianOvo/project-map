export function lineRange(text, start, end = start) {
  const first = start === 0 ? 0 : text.lastIndexOf("\n", start - 1) + 1;
  const adjusted = end > start && text[end - 1] === "\n" ? end - 1 : end;
  const found = text.indexOf("\n", adjusted);
  return [first, found < 0 ? text.length : found];
}
export function wrap(text, start, end, left, right = left) {
  if (start === end) [start, end] = lineRange(text, start, end);
  const selected = text.slice(start, end);
  let replacement;
  if (
    selected.startsWith(left) &&
    selected.endsWith(right) &&
    selected.length >= left.length + right.length
  ) {
    replacement = selected.slice(left.length, selected.length - right.length);
    return {
      start,
      end,
      replacement,
      selection: [start, start + replacement.length],
    };
  }
  if (
    text.slice(0, start).endsWith(left) &&
    text.slice(end).startsWith(right)
  ) {
    return {
      start: start - left.length,
      end: end + right.length,
      replacement: selected,
      selection: [start - left.length, end - left.length],
    };
  }
  replacement = left + (selected || "文本") + right;
  return {
    start,
    end,
    replacement,
    selection: [start + left.length, start + replacement.length - right.length],
  };
}
export function indent(text, start, end, remove = false) {
  const [first, last] = lineRange(text, start, end),
    lines = text.slice(first, last).split("\n");
  const nonstandard = /^([\t ]*)(\d+)\.(?=\S|$)(.*)$/;
  const correct = !remove && lines.some((line) => nonstandard.test(line));
  const replacement = lines
    .map((line) =>
      remove
        ? line.replace(/^(\t| {1,4})/, "")
        : correct
          ? line.replace(nonstandard, "$1$2. $3")
          : "\t" + line,
    )
    .join("\n");
  return {
    start: first,
    end: last,
    replacement,
    selection: [first, first + replacement.length],
  };
}
export function heading(text, start, end, level) {
  const [first, last] = lineRange(text, start, end);
  const replacement = text
    .slice(first, last)
    .split("\n")
    .map((line) => {
      const match = line.match(/^(\s*)(#{1,6})\s+(.*)$/);
      return match
        ? match[1] +
            (match[2].length === level ? "" : "#".repeat(level) + " ") +
            match[3]
        : "#".repeat(level) + " " + line;
    })
    .join("\n");
  return {
    start: first,
    end: last,
    replacement,
    selection: [first, first + replacement.length],
  };
}
export function numberedEnter(text, start, end, insert = false) {
  if (start !== end) return null;
  const [first, last] = lineRange(text, start),
    line = text.slice(first, start),
    match = line.match(/^([\t ]*)(\d+)\. (.*)$/);
  if (!match) return null;
  if (!match[3].trim())
    return {
      start: first,
      end: start,
      replacement: "",
      selection: [first, first],
    };
  const next = Number(match[2]) + 1,
    prefix = "\n" + match[1] + next + ". ";
  if (!insert)
    return {
      start,
      end,
      replacement: prefix,
      selection: [start + prefix.length, start + prefix.length],
    };
  const after = text.slice(last),
    lines = after.split("\n");
  let expected = next;
  for (let i = 1; i < lines.length; i++) {
    const number = lines[i].match(/^([\t ]*)(\d+)\. (.*)$/);
    if (!number || number[1] !== match[1] || Number(number[2]) !== expected)
      break;
    lines[i] = number[1] + (expected + 1) + ". " + number[3];
    expected++;
  }
  return {
    start,
    end: text.length,
    replacement: prefix + text.slice(start, last) + lines.join("\n"),
    selection: [start + prefix.length, start + prefix.length],
  };
}
export function insertVersion(text, start, end, sub = false) {
  const matches = [
    ...text.slice(0, start).matchAll(/^(#{1,6})\s+[Vv](\d+(?:\.\d+)*)\b.*$/gm),
  ];
  const closest = matches.at(-1);
  let level = closest?.[1] || "#",
    parts = closest ? closest[2].split(".").map(Number) : [0];
  if (sub) {
    const major = matches.filter((match) => match[1] === "#").at(-1);
    const root = major?.[2].split(".")[0] || "1";
    const child = matches
      .filter((match) => match[1] === "##" && match[2].startsWith(root + "."))
      .at(-1);
    level = "##";
    parts = [Number(root), child ? Number(child[2].split(".").at(-1)) + 1 : 1];
  } else parts[parts.length - 1]++;
  const marker = parts.join("."),
    prefix = start && text[start - 1] !== "\n" ? "\n\n" : "",
    inserted = prefix + level + " V" + marker + "\n\n";
  const series = parts.slice(0, -1).join(".");
  const after = text
    .slice(end)
    .replace(
      /^(#{1,6})\s+([Vv])(\d+(?:\.\d+)*)(.*)$/gm,
      (all, h, v, n, tail) => {
        const values = n.split(".").map(Number);
        if (
          h !== level ||
          values.length !== parts.length ||
          values.slice(0, -1).join(".") !== series ||
          values.at(-1) < parts.at(-1)
        )
          return all;
        values[values.length - 1]++;
        return h + " " + v + values.join(".") + tail;
      },
    );
  return {
    start,
    end: text.length,
    replacement: inserted + after,
    selection: [start + inserted.length, start + inserted.length],
  };
}
export function removeVersion(text, start, end) {
  const [first, last] = lineRange(text, start, end),
    line = text.slice(first, last),
    match = line.match(/^(#{1,6})\s+[Vv](\d+(?:\.\d+)*)\b/);
  if (!match) return null;
  const parts = match[2].split(".").map(Number),
    series = parts.slice(0, -1).join(".");
  let after = text.slice(last + (text[last] === "\n" ? 1 : 0));
  after = after.replace(
    /^(#{1,6})\s+([Vv])(\d+(?:\.\d+)*)(.*)$/gm,
    (all, h, v, n, tail) => {
      const values = n.split(".").map(Number);
      if (
        h !== match[1] ||
        values.length !== parts.length ||
        values.slice(0, -1).join(".") !== series ||
        values.at(-1) <= parts.at(-1)
      )
        return all;
      values[values.length - 1]--;
      return h + " " + v + values.join(".") + tail;
    },
  );
  return {
    start: first,
    end: text.length,
    replacement: after,
    selection: [first, first],
  };
}
