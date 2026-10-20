from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from pathlib import Path


WORK_ROOT = Path(r"D:\桌面\Work")
MAIN_PROJECT = WORK_ROOT / "项目航图"
CLOUD_PROJECT = WORK_ROOT / "项目航图-云端"
PRESERVED_EVIDENCE = Path("adb-lease-qa") / "result.json"

FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
FILE_ATTRIBUTE_REPARSE_POINT = 0x0400
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF


class SHFileOperation(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", ctypes.c_void_p),
        ("pTo", ctypes.c_void_p),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def is_reparse_point(path: Path) -> bool:
    get_attributes = ctypes.windll.kernel32.GetFileAttributesW
    get_attributes.argtypes = [wintypes.LPCWSTR]
    get_attributes.restype = wintypes.DWORD
    attributes = get_attributes(str(path))
    return (
        attributes != INVALID_FILE_ATTRIBUTES
        and bool(attributes & FILE_ATTRIBUTE_REPARSE_POINT)
    )


def tree_has_reparse_point(path: Path) -> bool:
    if is_reparse_point(path):
        return True
    if not path.is_dir():
        return False
    for current, directories, files in os.walk(path, followlinks=False):
        parent = Path(current)
        for name in directories + files:
            if is_reparse_point(parent / name):
                return True
    return False


def size_of(path: Path) -> tuple[int, int]:
    if is_reparse_point(path):
        return 0, 0
    if path.is_file():
        return 1, path.stat().st_size
    count = 0
    total = 0
    for current, directories, files in os.walk(path, followlinks=False):
        parent = Path(current)
        directories[:] = [name for name in directories if not is_reparse_point(parent / name)]
        for name in files:
            file_path = parent / name
            if is_reparse_point(file_path):
                continue
            try:
                total += file_path.stat().st_size
                count += 1
            except OSError:
                pass
    return count, total


def is_inside(path: Path, root: Path) -> bool:
    resolved_path = path.resolve(strict=True)
    resolved_root = root.resolve(strict=True)
    return resolved_path != resolved_root and resolved_root in resolved_path.parents


def add_target(targets: dict[Path, Path], target: Path, root: Path) -> None:
    if not target.exists():
        return
    if is_reparse_point(target):
        raise ValueError(f"清理目标是链接或联接目录：{target}")
    if not is_inside(target, root):
        raise ValueError(f"清理目标越出项目目录：{target}")
    targets[target] = root


def add_python_caches(
    targets: dict[Path, Path], project: Path, source_dirs: tuple[str, ...]
) -> None:
    root_cache = project / "__pycache__"
    add_target(targets, root_cache, project)
    for relative in source_dirs:
        scope = project / relative
        if not scope.is_dir():
            continue
        for current, directories, _ in os.walk(scope, topdown=True, followlinks=False):
            parent = Path(current)
            directories[:] = [
                name for name in directories if not is_reparse_point(parent / name)
            ]
            cache_dirs = [name for name in directories if name == "__pycache__"]
            for name in cache_dirs:
                add_target(targets, parent / name, project)
            directories[:] = [name for name in directories if name != "__pycache__"]


def collect_targets() -> dict[Path, Path]:
    targets: dict[Path, Path] = {}

    add_target(targets, MAIN_PROJECT / ".cache", MAIN_PROJECT)
    add_target(targets, MAIN_PROJECT / "build", MAIN_PROJECT)
    add_target(targets, MAIN_PROJECT / ".pytest_cache", MAIN_PROJECT)
    add_python_caches(targets, MAIN_PROJECT, ("project_map", "scripts", "tests"))

    cloud_cache = CLOUD_PROJECT / ".cache"
    if cloud_cache.is_dir():
        for child in cloud_cache.iterdir():
            if child.name != PRESERVED_EVIDENCE.parts[0]:
                add_target(targets, child, CLOUD_PROJECT)
        evidence_dir = cloud_cache / PRESERVED_EVIDENCE.parts[0]
        if evidence_dir.is_dir():
            for child in evidence_dir.iterdir():
                if child.name != PRESERVED_EVIDENCE.name:
                    add_target(targets, child, CLOUD_PROJECT)

    add_target(targets, CLOUD_PROJECT / ".pytest_cache", CLOUD_PROJECT)
    add_python_caches(
        targets, CLOUD_PROJECT, ("scripts", "server", "tests", "windows")
    )
    return targets


def recycle(path: Path) -> None:
    source_buffer = ctypes.create_unicode_buffer(f"{path}\0\0")
    operation = SHFileOperation()
    operation.wFunc = FO_DELETE
    operation.pFrom = ctypes.cast(source_buffer, ctypes.c_void_p)
    operation.fFlags = (
        FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI
    )
    shell32 = ctypes.windll.shell32
    shell32.SHFileOperationW.argtypes = [ctypes.POINTER(SHFileOperation)]
    shell32.SHFileOperationW.restype = ctypes.c_int
    result = shell32.SHFileOperationW(ctypes.byref(operation))
    if result != 0:
        raise OSError(f"Windows 回收站接口返回错误 {result}")
    if operation.fAnyOperationsAborted:
        raise OSError("Windows 中止了回收操作")


def recycle_recursively(path: Path, root: Path) -> list[tuple[Path, str]]:
    if not path.exists():
        return []
    if not is_inside(path, root):
        return [(path, "目标路径不在允许的项目目录内")]
    if is_reparse_point(path):
        return [(path, "目标是链接或联接目录，已跳过")]

    try:
        recycle(path)
        return []
    except OSError as error:
        if not path.is_dir():
            return [(path, str(error))]

    try:
        children = sorted(path.iterdir(), key=lambda item: item.name.casefold())
    except OSError as error:
        return [(path, str(error))]

    failures: list[tuple[Path, str]] = []
    for child in children:
        failures.extend(recycle_recursively(child, root))

    if not failures:
        try:
            path.rmdir()
        except OSError as error:
            failures.append((path, str(error)))
    return failures


def main() -> int:
    if os.name != "nt":
        print("此脚本只能在 Windows 上运行。")
        return 2

    for project in (MAIN_PROJECT, CLOUD_PROJECT):
        if not project.is_dir():
            print(f"找不到项目目录：{project}")
            return 2

    targets = collect_targets()
    if not targets:
        print("没有发现待清理的缓存。")
        input("按回车退出。")
        return 0

    total_files = 0
    total_bytes = 0
    print("以下项目将移入 Windows 回收站：")
    for target in sorted(targets, key=lambda item: str(item).lower()):
        files, byte_count = size_of(target)
        total_files += files
        total_bytes += byte_count
        print(f"  {target}  ({files} 个文件，{byte_count / 1024 / 1024:.1f} MiB)")

    evidence = CLOUD_PROJECT / ".cache" / PRESERVED_EVIDENCE
    if evidence.is_file():
        print(f"保留交接测试结果：{evidence}")
    print(f"预计回收：{total_files} 个文件，{total_bytes / 1024 / 1024:.1f} MiB")
    if input("确认清理请输入“清理”：").strip() != "清理":
        print("已取消，没有更改文件。")
        input("按回车退出。")
        return 0

    failures: list[tuple[Path, str]] = []
    for target, root in sorted(
        targets.items(), key=lambda pair: len(pair[0].parts), reverse=True
    ):
        if not target.exists():
            continue
        if not is_inside(target, root):
            failures.append((target, "目标路径不在允许的项目目录内"))
            continue
        if tree_has_reparse_point(target):
            failures.append((target, "目标内含符号链接或目录联接，已跳过"))
            continue

        target_failures = recycle_recursively(target, root)
        if target_failures:
            failures.extend(target_failures)
            for failed_path, reason in target_failures:
                print(f"清理失败：{failed_path}；{reason}")
        else:
            print(f"已清理并移入回收站：{target}")

    if failures:
        print(f"完成时有 {len(failures)} 项未清理；失败项仍保留在原位置。")
        print("请按上方完整路径检查文件占用和访问权限；管理员权限未必能解决。")
        result = 1
    else:
        print("清理完成；项目已进入回收站，可恢复。")
        result = 0
    input("按回车退出。")
    return result


if __name__ == "__main__":
    raise SystemExit(main())
