from __future__ import annotations

import copy
import hashlib
import re
import threading
import uuid
from pathlib import Path

from ..file_io import read_json, write_json
from ..locations import path_identity
from .assets import Assets, MissingImage
from .merge import FIELDS, payload
from .api import CloudError


def safe_name(title):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", title).strip(" .")[:100] or "未命名项目"
    if text.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        text = "_" + text
    return text


class Engine:
    def __init__(self, paths, endpoint, search_dirs=()):
        self.paths = paths
        self.endpoint = endpoint
        key = hashlib.sha256(endpoint.encode()).hexdigest()[:16]
        self.state_path = paths.data / "cloud" / (paths.library_id + "-" + key + ".json")
        self.assets = Assets(paths.media, [paths.root / "Media", *search_dirs])
        self.cancel = threading.Event()

    def load(self):
        state = read_json(self.state_path, {"documents": {}, "applications": {}, "uploaded": [], "cursor": 0})
        old_root = Path(state.get("root", self.paths.root))
        if path_identity(old_root) != path_identity(self.paths.root):
            for collection in (state["documents"].values(), state["applications"].values(), state.get("issues", [])):
                for value in collection:
                    path = Path(value["path"])
                    if path.is_relative_to(old_root):
                        value["path"] = str(self.paths.root / path.relative_to(old_root))
                    pending = value.get("pending")
                    if pending:
                        for digest, image_path in list(pending.get("images", {}).items()):
                            path = Path(image_path)
                            if path.is_relative_to(old_root):
                                pending["images"][digest] = str(self.paths.root / path.relative_to(old_root))
        state["root"] = str(self.paths.root)
        return state

    def save(self, state):
        write_json(self.state_path, state)

    def acknowledge(self, identifiers):
        state = self.load()
        for identifier in identifiers:
            state["applications"].pop(identifier, None)
        self.save(state)

    def unused_path(self, title, identifier, documents):
        reserved = {path_identity(value["path"]) for value in documents.values()}
        stem = safe_name(title)
        candidate = self.paths.markdown / (stem + ".md")
        count = 0
        while candidate.exists() or path_identity(candidate) in reserved:
            count += 1
            candidate = self.paths.markdown / f"{stem} · {identifier[:8]}{('-' + str(count)) if count > 1 else ''}.md"
        return candidate

    def queue_remote(self, state, api, remote, expected, path):
        self.assets.download(api, remote["content"])
        identifier = remote["id"]
        old = state["documents"].get(identifier, {})
        state["documents"][identifier] = {
            "path": str(path), "revision": remote["revision"], "base": payload(remote),
            "external": old.get("external", path.parent.resolve() != self.paths.markdown.resolve()), "pending": None,
        }
        state["applications"][identifier] = {"path": str(path), "expected": payload(expected), "remote": payload(remote)}
        self.save(state)

    def cycle(self, api, items, device_id, include_external=False):
        state = self.load()
        if state["applications"]:
            return self.result(state)
        if self.cancel.is_set():
            return self.result(state)
        by_path = {path_identity(value["path"]): key for key, value in state["documents"].items()}
        snapshots = {}
        active_identifier = None
        issues = []
        all_paths = {path_identity(item["path"]) for item in items}
        try:
            for item in items:
                if item.get("document") is None:
                    continue
                if item.get("external") and not include_external:
                    continue
                path = Path(item["path"])
                local = payload(item["document"])
                try:
                    local["content"], images = self.assets.cloud_content(local["content"], path)
                    if len(local["content"].encode("utf-8")) > 2 * 1024 * 1024:
                        raise ValueError("单份大纲超过云端 2 MB 限制")
                except (ValueError, OSError) as error:
                    issues.append({"path": str(path.resolve()), "message": str(error),
                                   "kind": "missing_image" if isinstance(error, MissingImage) else "document",
                                   "source": error.source if isinstance(error, MissingImage) else ""})
                    continue
                key = by_path.get(path_identity(path))
                if key is None:
                    key = item.get("cloud_id") if item.get("cloud_endpoint") == self.endpoint else None
                    key = key or str(uuid.uuid4())
                    if key in state["documents"]:
                        key = str(uuid.uuid4())
                    state["documents"][key] = {"path": str(path), "revision": 0, "base": dict(FIELDS), "external": bool(item.get("external")), "pending": None}
                snapshots[key] = (local, images)
                if item.get("active"):
                    active_identifier = key
            state["issues"] = issues
            for identifier, entry in list(state["documents"].items()):
                if self.cancel.is_set():
                    break
                if entry.get("external") and not include_external:
                    continue
                current = snapshots.get(identifier)
                if current is None:
                    if path_identity(entry["path"]) in all_paths:
                        continue
                    current = ({**entry["base"], "deleted": True}, {})
                local, images = current
                deferred = entry.get("deferred")
                if deferred and current[0] == entry["base"] and identifier in snapshots:
                    self.queue_remote(state, api, deferred, entry["base"], Path(entry["path"]))
                    continue
                if local == entry["base"] and not entry.get("pending"):
                    continue
                if not entry.get("pending"):
                    entry["pending"] = {
                        "id": identifier, "op_id": str(uuid.uuid4()), "base_revision": entry["revision"],
                        "document": copy.deepcopy(local), "images": {digest: str(path) for digest, path in images.items()},
                    }
                    self.save(state)
                pending = entry["pending"]
                self.assets.upload(api, {digest: Path(path) for digest, path in pending["images"].items()}, state["uploaded"])
                self.save(state)
                request = {key: value for key, value in pending.items() if key != "images"}
                try:
                    marker = {"_active_editor": True} if identifier == active_identifier else {}
                    response = api.request("api/sync", {**request, "device_id": device_id, **marker})
                except CloudError as error:
                    if error.status != 423:
                        raise
                    issues.append({"path": entry["path"], "message": str(error), "kind": "busy", "source": ""})
                    continue
                original = response["document"]
                self.queue_remote(state, api, original, pending["document"], Path(entry["path"]))
                if response["status"] == "conflict":
                    conflict = response["conflict"]
                    path = self.unused_path(conflict["title"], conflict["id"], state["documents"])
                    self.queue_remote(state, api, conflict, conflict, path)
                    state["applications"][conflict["id"]]["related_path"] = entry["path"]
                    self.save(state)
            if not self.cancel.is_set():
                while True:
                    page = api.request("api/changes?since=" + str(state["cursor"]))
                    for remote in page["documents"]:
                        identifier = remote["id"]
                        entry = state["documents"].get(identifier)
                        if entry and remote["revision"] <= entry["revision"]:
                            continue
                        if entry and entry.get("external") and not include_external:
                            entry["deferred"] = remote
                            continue
                        if entry:
                            if identifier not in snapshots and path_identity(entry["path"]) in all_paths:
                                entry["deferred"] = remote
                                continue
                            current = snapshots.get(identifier, (entry["base"], {}))[0]
                            if current != entry["base"] or entry.get("pending"):
                                entry["deferred"] = remote
                                continue
                            path, expected = Path(entry["path"]), current
                        else:
                            if remote.get("deleted"):
                                continue
                            path = self.unused_path(remote["title"], identifier, state["documents"])
                            expected = remote
                        self.queue_remote(state, api, remote, expected, path)
                    state["cursor"] = page["cursor"]
                    self.save(state)
                    if not page["has_more"] or self.cancel.is_set():
                        break
        finally:
            self.save(state)
        return self.result(state)

    @staticmethod
    def result(state):
        issues = copy.deepcopy(state.get("issues", []))
        return {"applications": copy.deepcopy(state["applications"]),
                "bindings": {key: value["path"] for key, value in state["documents"].items()},
                "issues": issues, "errors": [Path(issue["path"]).name + "：" + issue["message"] for issue in issues]}
