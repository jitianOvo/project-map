export const fields = {
  content: "",
  title: "新项目",
  group: "默认项目",
  description: "",
  priority: "",
  pinned: false,
  order: 0,
  deleted: false,
  project_path: "",
};
export const clone = (value) => JSON.parse(JSON.stringify(value));
export const uuid = () =>
  crypto.randomUUID
    ? crypto.randomUUID()
    : "10000000-1000-4000-8000-100000000000".replace(/[018]/g, (c) =>
        (
          +c ^
          (crypto.getRandomValues(new Uint8Array(1))[0] & (15 >> (+c / 4)))
        ).toString(16),
      );
export const payload = (doc) =>
  Object.fromEntries(
    Object.keys(fields).map((key) => [key, doc[key] ?? fields[key]]),
  );
export function normalize(value) {
  const result = payload(value);
  for (const [key, limit] of [
    ["content", 2097152],
    ["title", 200],
    ["group", 200],
    ["description", 4000],
    ["priority", 20],
    ["project_path", 2000],
  ]) {
    if (typeof result[key] !== "string") throw new Error(key + " 必须是文字");
    if (
      (key === "content"
        ? new TextEncoder().encode(result[key]).length
        : result[key].length) > limit
    )
      throw new Error(key === "content" ? "单个大纲最多 2 MB" : key + " 过长");
  }
  if (
    !["", "urgent", "high", "normal"].includes(result.priority) ||
    typeof result.pinned !== "boolean" ||
    typeof result.deleted !== "boolean" ||
    !Number.isSafeInteger(result.order)
  )
    throw new Error("项目状态无效");
  result.title = result.title.trim() || "未命名项目";
  result.group = result.group.trim() || "默认项目";
  return result;
}
export const equal = (a, b) => JSON.stringify(a) === JSON.stringify(b);
export function textMerge(base, local, remote) {
  if (local === remote || remote === base) return local;
  if (local === base) return remote;
  const before = base.split("\n");
  function range(value) {
    const lines = value.split("\n");
    let start = 0,
      tail = 0;
    while (
      start < before.length &&
      start < lines.length &&
      before[start] === lines[start]
    )
      start++;
    while (
      tail < before.length - start &&
      tail < lines.length - start &&
      before[before.length - 1 - tail] === lines[lines.length - 1 - tail]
    )
      tail++;
    return {
      start,
      end: before.length - tail,
      lines: lines.slice(start, lines.length - tail),
    };
  }
  const a = range(local),
    b = range(remote);
  if (
    Math.max(a.start, b.start) < Math.min(a.end, b.end) ||
    (a.start === a.end && b.start <= a.start && a.start < b.end) ||
    (b.start === b.end && a.start <= b.start && b.start < a.end) ||
    (a.start === a.end && a.start === b.start && b.start === b.end)
  )
    return null;
  for (const edit of [a, b].sort((x, y) => y.start - x.start || y.end - x.end))
    before.splice(edit.start, edit.end - edit.start, ...edit.lines);
  return before.join("\n");
}
export function documentMerge(base, local, remote) {
  if (
    ((local.deleted !== base.deleted && !equal(remote, base)) ||
      (remote.deleted !== base.deleted && !equal(local, base))) &&
    !equal(local, remote)
  )
    return null;
  const content = textMerge(base.content, local.content, remote.content);
  if (content === null) return null;
  const merged = { content };
  for (const key of Object.keys(fields).filter((key) => key !== "content")) {
    if (
      local[key] !== base[key] &&
      remote[key] !== base[key] &&
      local[key] !== remote[key]
    )
      return null;
    merged[key] = local[key] === base[key] ? remote[key] : local[key];
  }
  return merged;
}
export function accepted(entry, pending, response) {
  const remote =
    response.status === "conflict" ? response.conflict : response.document;
  const base = payload(remote);
  const next =
    entry.generation === pending.generation
      ? base
      : documentMerge(pending.document, payload(entry), base);
  if (next === null) return { conflict: true, remote, local: payload(entry) };
  return {
    entry: {
      ...entry,
      ...remote,
      ...next,
      base,
      dirty: !equal(next, base),
      pending: null,
      generation: entry.generation,
    },
  };
}
