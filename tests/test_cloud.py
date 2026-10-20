from __future__ import annotations

import base64
import copy
import hashlib
import tempfile
import unittest
import uuid
import shutil
from pathlib import Path

from project_map.cloud.api import CloudError, normalize_endpoint
from project_map.cloud.assets import Assets
from project_map.cloud.credentials import load_token, save_token
from project_map.cloud.engine import Engine
from project_map.cloud.merge import FIELDS, merge_document, payload
from project_map.file_io import read_json, write_json
from project_map.locations import AppPaths
from project_map.migration import merge_inner_data

PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+aWQAAAABJRU5ErkJggg==")


class MemoryApi:
    def __init__(self):
        self.documents = {}
        self.revisions = {}
        self.operations = {}
        self.images = {}
        self.sequence = 0
        self.fail_after_commit = False

    def write(self, identifier, document):
        self.sequence += 1
        revision = self.documents.get(identifier, {}).get("revision", 0) + 1
        value = {**payload(document), "id": identifier, "revision": revision, "sequence": self.sequence}
        self.documents[identifier] = value
        self.revisions[identifier, revision] = payload(value)
        return copy.deepcopy(value)

    def request(self, route, body=None):
        if route.startswith("api/changes"):
            since = int(route.rsplit("=", 1)[1])
            docs = sorted((value for value in self.documents.values() if value["sequence"] > since), key=lambda value: value["sequence"])
            return {"documents": copy.deepcopy(docs), "cursor": docs[-1]["sequence"] if docs else since, "has_more": False}
        if route == "api/media":
            data = base64.b64decode(body["data"])
            if hashlib.sha256(data).hexdigest() != body["id"]:
                raise ValueError("图片校验失败")
            self.images[body["id"]] = data
            return {"id": body["id"]}
        if route.startswith("api/media/"):
            return {"mime": "image/png", "data": base64.b64encode(self.images[route.rsplit("/", 1)[1]]).decode()}
        if route == "api/sync":
            operation = body["op_id"]
            if operation in self.operations:
                return copy.deepcopy(self.operations[operation])
            identifier = body["id"]
            previous = self.documents.get(identifier)
            merged = body["document"]
            if previous and previous["revision"] != body["base_revision"]:
                base = self.revisions.get((identifier, body["base_revision"]))
                merged = merge_document(base, body["document"], previous) if base else None
            if merged is None:
                conflict = {**body["document"], "title": body["document"]["title"] + " · 冲突副本", "deleted": False}
                result = {"status": "conflict", "document": copy.deepcopy(previous), "conflict": self.write(str(uuid.uuid4()), conflict)}
            else:
                result = {"status": "saved", "document": self.write(identifier, merged)}
            self.operations[operation] = result
            if self.fail_after_commit:
                self.fail_after_commit = False
                raise CloudError("模拟响应丢失")
            return copy.deepcopy(result)
        raise ValueError(route)


class CloudTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.paths = AppPaths(root, root / "Markdown", root / "Media", root / "Data", root / "Backups")
        self.paths.ensure()
        self.engine = Engine(self.paths, "http://127.0.0.1:18770/")
        self.api = MemoryApi()
        self.path = self.paths.markdown / "演示.md"
        self.path.write_text("第一行\n第二行\n第三行\n", encoding="utf-8")

    def tearDown(self):
        self.temporary.cleanup()

    def item(self, content=None, path=None, external=False):
        path = path or self.path
        return {"path": str(path), "external": external, "document": {**FIELDS, "title": path.stem, "content": content if content is not None else path.read_text(encoding="utf-8")}}

    def upload(self, items=None, external=False):
        result = self.engine.cycle(self.api, items or [self.item()], "桌面测试", external)
        self.engine.acknowledge(list(result["applications"]))
        return result

    def test_upload_and_idempotent_retry_after_response_lost(self):
        self.api.fail_after_commit = True
        with self.assertRaises(CloudError):
            self.upload()
        state = self.engine.load()
        operation = next(iter(state["documents"].values()))["pending"]["op_id"]
        result = self.upload()
        self.assertEqual(len(self.api.operations), 1)
        self.assertIn(operation, self.api.operations)
        self.assertEqual(next(iter(result["applications"].values()))["remote"]["content"], self.path.read_text(encoding="utf-8"))

    def test_separate_line_edits_merge_and_same_line_conflict_is_retained(self):
        self.upload()
        identifier = next(iter(self.api.documents))
        self.api.write(identifier, {**self.api.documents[identifier], "content": "手机第一行\n第二行\n第三行\n"})
        result = self.upload([self.item("第一行\n第二行\n电脑第三行\n")])
        merged = result["applications"][identifier]["remote"]["content"]
        self.assertEqual(merged, "手机第一行\n第二行\n电脑第三行\n")
        self.api.write(identifier, {**self.api.documents[identifier], "content": "手机改同一行\n第二行\n电脑第三行\n"})
        result = self.upload([self.item("电脑改同一行\n第二行\n电脑第三行\n")])
        self.assertEqual(len(self.api.documents), 2)
        self.assertEqual(len(result["applications"]), 2)

    def test_images_upload_before_document_and_download_to_selected_cache(self):
        source = self.paths.media / "图片.png"
        source.write_bytes(PNG)
        self.upload([self.item("![示例](Media/图片.png)")])
        digest = hashlib.sha256(PNG).hexdigest()
        self.assertIn(digest, self.api.images)
        content = next(iter(self.api.documents.values()))["content"]
        self.assertIn("Media/" + digest + ".png", content)
        another = self.paths.root / "另一图片目录"
        Assets(another).download(self.api, content)
        self.assertEqual((another / (digest + ".png")).read_bytes(), PNG)
        self.assertEqual(source.read_bytes(), PNG)

    def test_missing_image_does_not_upload_broken_markdown(self):
        result = self.upload([self.item("![缺失](Media/不存在.png)")])
        self.assertIn("图片未找到", result["errors"][0])
        self.assertFalse(self.api.documents)

    def test_missing_image_issues_are_complete_persisted_and_do_not_block_other_projects(self):
        result = self.upload([self.item("![缺失](Media/不存在.png)"), self.item("文字继续同步", self.paths.markdown / "正常.md")])
        self.assertEqual(len(result["issues"]), 1)
        issue = result["issues"][0]
        self.assertEqual(issue["path"], str(self.path.resolve()))
        self.assertEqual(issue["kind"], "missing_image")
        self.assertEqual(issue["source"], "Media/不存在.png")
        self.assertEqual(self.engine.load()["issues"], result["issues"])
        self.assertEqual(len(self.api.documents), 1)
        self.assertEqual(next(iter(self.api.documents.values()))["title"], "正常")

    def test_pending_application_does_not_erase_previous_warning(self):
        items = [self.item("![缺失](Media/不存在.png)"), self.item("文字", self.paths.markdown / "正常.md")]
        first = self.engine.cycle(self.api, items, "桌面测试")
        second = self.engine.cycle(self.api, items, "桌面测试")
        self.assertEqual(first["issues"], second["issues"])
        self.assertEqual(first["errors"], second["errors"])

    def test_recovered_missing_image_clears_issue_and_uploads_document(self):
        item = self.item("![缺失](Media/暂缺.png)")
        self.upload([item])
        (self.paths.media / "暂缺.png").write_bytes(PNG)
        result = self.upload([item])
        self.assertEqual(result["issues"], [])
        self.assertEqual(self.engine.load()["issues"], [])
        self.assertEqual(len(self.api.documents), 1)

    def test_remote_change_to_locally_blocked_document_is_deferred_until_recovery(self):
        self.upload()
        identifier = next(iter(self.api.documents))
        remote = {**self.api.documents[identifier], "description": "手机补充属性"}
        self.api.write(identifier, remote)
        result = self.upload([self.item("![缺失](Media/暂缺.png)")])
        self.assertFalse(result["applications"])
        self.assertEqual(len(result["issues"]), 1)
        self.assertIn("deferred", self.engine.load()["documents"][identifier])
        (self.paths.media / "暂缺.png").write_bytes(PNG)
        result = self.upload([self.item("![缺失](Media/暂缺.png)")])
        self.assertEqual(result["issues"], [])
        self.assertIn(identifier, result["applications"])
        self.assertEqual(result["applications"][identifier]["remote"]["description"], "手机补充属性")

    def test_old_absolute_image_uses_relocated_cache_without_rewriting_source(self):
        cached = self.paths.media / "旧图.png"
        cached.write_bytes(PNG)
        previous = self.paths.root / "不存在的Typora目录" / cached.name
        content = f"![旧图]({previous})"
        converted, images = self.engine.assets.cloud_content(content, self.path)
        self.assertTrue(images)
        self.assertNotIn(str(previous), converted)
        self.assertFalse(previous.exists())
        self.assertEqual(self.engine.assets.resolve(previous.as_uri(), self.path), cached.resolve())

    def test_different_same_name_images_are_not_silently_substituted(self):
        cached = self.paths.media / "旧图.png"
        cached.write_bytes(PNG)
        extra = self.paths.root / "额外图片"
        extra.mkdir()
        (extra / cached.name).write_bytes(PNG + b"different")
        assets = Assets(self.paths.media, [extra])
        previous = self.paths.root / "已失效" / cached.name
        self.assertIsNone(assets.resolve(str(previous), self.path))
        (extra / cached.name).write_bytes(PNG)
        self.assertIsNotNone(assets.resolve(str(previous), self.path))
        previous.parent.mkdir()
        previous.write_bytes(PNG + b"original")
        self.assertEqual(assets.resolve(str(previous), self.path), previous)

    def test_image_uri_preserves_encoded_hash_spaces_and_unicode(self):
        cached = self.paths.media / "图片 #1.png"
        cached.write_bytes(PNG)
        self.assertEqual(self.engine.assets.resolve(cached.as_uri(), self.path), cached)

    def test_external_project_sibling_media_resolves_without_setting_extra_directory(self):
        external = self.paths.root / "外部目录"
        external.mkdir()
        (external / "Media").mkdir()
        image = external / "Media" / "本地.png"
        image.write_bytes(PNG)
        document = external / "项目.md"
        self.assertEqual(self.engine.assets.resolve("Media/本地.png", document), image)

    def test_image_examples_in_code_are_not_treated_as_missing_files(self):
        content = '```md\n![代码示例](Media/不存在.png)\n```\n`![行内示例](Media/也不存在.png)`'
        result = self.upload([self.item(content)])
        self.assertEqual(result["errors"], [])
        self.assertEqual(next(iter(self.api.documents.values()))["content"], content)

    def test_external_links_are_opt_in_and_not_deleted_when_scope_changes(self):
        external = self.paths.root / "外部.md"
        external.write_text("外部", encoding="utf-8")
        self.upload([self.item(), self.item(path=external, external=True)])
        self.assertEqual(len(self.api.documents), 1)
        self.upload([self.item(), self.item(path=external, external=True)], external=True)
        self.assertEqual(len(self.api.documents), 2)
        self.upload([self.item(), self.item(path=external, external=True)])
        self.assertFalse(any(value["deleted"] for value in self.api.documents.values()))

    def test_paused_external_scope_replays_remote_change_when_enabled_again(self):
        external = self.paths.root / "外部.md"
        external.write_text("外部", encoding="utf-8")
        items = [self.item(), self.item(path=external, external=True)]
        self.upload(items, external=True)
        identifier = next(key for key, value in self.api.documents.items() if value["title"] == "外部")
        self.api.write(identifier, {**self.api.documents[identifier], "content": "手机改了外部"})
        self.upload(items)
        result = self.upload(items, external=True)
        self.assertEqual(result["applications"][identifier]["remote"]["content"], "手机改了外部")

    def test_missing_external_link_is_not_treated_as_user_deletion(self):
        external = self.paths.root / "暂时断开的外部.md"
        external.write_text("外部", encoding="utf-8")
        items = [self.item(), self.item(path=external, external=True)]
        self.upload(items, external=True)
        external.unlink()
        self.upload([self.item(), {"path": str(external), "external": True, "document": None}], external=True)
        self.assertFalse(any(value["deleted"] for value in self.api.documents.values()))

    def test_moving_whole_project_preserves_cloud_identity_and_pending_paths(self):
        self.upload()
        moved = self.paths.root / "迁移后的程序"
        shutil.copytree(self.paths.markdown, moved / "Markdown")
        shutil.copytree(self.paths.data, moved / "Data")
        paths = AppPaths(moved, moved / "Markdown", moved / "Media", moved / "Data", moved / "Backups")
        paths.ensure()
        engine = Engine(paths, self.engine.endpoint)
        result = engine.cycle(self.api, [self.item(path=paths.markdown / self.path.name)], "迁移验证")
        self.assertEqual(len(self.api.documents), 1)
        self.assertTrue(all(Path(path).parent == paths.markdown for path in result["bindings"].values()))

    def test_local_removal_becomes_cloud_tombstone(self):
        self.upload()
        self.path.unlink()
        result = self.engine.cycle(self.api, [], "桌面测试")
        self.assertTrue(next(iter(result["applications"].values()))["remote"]["deleted"])

    def test_durable_incoming_application_is_replayed_before_more_uploads(self):
        result = self.engine.cycle(self.api, [self.item()], "桌面测试")
        again = self.engine.cycle(self.api, [self.item("继续编辑")], "桌面测试")
        self.assertEqual(result["applications"], again["applications"])
        self.assertEqual(result["bindings"], again["bindings"])
        self.assertEqual(len(self.api.operations), 1)

    def test_download_same_titles_uses_distinct_files(self):
        for content in ("甲", "乙"):
            self.api.write(str(uuid.uuid4()), {**FIELDS, "title": "同名", "content": content})
        result = self.engine.cycle(self.api, [], "桌面测试")
        paths = [value["path"] for value in result["applications"].values()]
        self.assertEqual(len(set(paths)), 2)

    def test_endpoint_validation_and_protected_shared_account(self):
        for endpoint in ("http://example.com/", "https://user:password@example.com/", "https://example.com/?password=x"):
            with self.assertRaises(ValueError):
                normalize_endpoint(endpoint)
        self.assertEqual(normalize_endpoint("https://example.com/test"), "https://example.com/test/")
        path = self.paths.data / "account.json"
        save_token(path, "https://example.com/", "测试登录令牌", "owner")
        self.assertEqual(load_token(path, "https://example.com/"), "测试登录令牌")
        self.assertEqual(load_token(path, "https://other.example.com/"), "")
        self.assertNotIn("测试登录令牌", path.read_text(encoding="utf-8"))


class MigrationTests(unittest.TestCase):
    def test_inner_precedence_metadata_link_dedup_and_full_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for base in (root, root / "dist"):
                for name in ("Markdown", "Media", "Data"):
                    (base / name).mkdir(parents=True)
            (root / "Markdown" / "同名.md").write_text("外层旧版", encoding="utf-8")
            (root / "dist" / "Markdown" / "同名.md").write_text("内层常用版", encoding="utf-8")
            (root / "Markdown" / "仅外层.md").write_text("保留", encoding="utf-8")
            (root / "Media" / "仅外层.png").write_bytes(PNG)
            (root / "dist" / "Media" / "仅内层.png").write_bytes(PNG)
            write_json(root / "Data" / "projects.json", {"同名.md": {"group": "旧组"}})
            write_json(root / "dist" / "Data" / "projects.json", {"同名.md": {"group": "常用组"}, "external:old": {"source_path": str(root / "Markdown" / "仅外层.md"), "pinned": True}})
            result = merge_inner_data(root, root / "Backups" / "迁移")
            self.assertEqual((root / "Markdown" / "同名.md").read_text(encoding="utf-8"), "内层常用版")
            self.assertEqual((root / "Backups" / "迁移" / "外层原始" / "Markdown" / "同名.md").read_text(encoding="utf-8"), "外层旧版")
            meta = read_json(root / "Data" / "projects.json")
            self.assertEqual(meta["同名.md"]["group"], "常用组")
            self.assertTrue(meta["仅外层.md"]["pinned"])
            self.assertNotIn("source_path", meta["仅外层.md"])
            self.assertEqual(result["markdown_total"], 2)
            self.assertEqual(result["media_total"], 2)
            with self.assertRaises(ValueError):
                merge_inner_data(root, root / "Backups" / "迁移")

    def test_paths_are_shared_and_library_metadata_is_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            defaults = (root, root / "Markdown", root / "Media", root / "Data", root / "Backups")
            paths = AppPaths.load(*defaults)
            selected = paths.with_sources(root / "另一个大纲目录", root / "另一个图片目录")
            selected.save()
            self.assertEqual(AppPaths.load(*defaults), selected)
            self.assertNotEqual(selected.projects, paths.projects)
            with self.assertRaises(ValueError):
                paths.with_sources(root / "相同", root / "相同")
