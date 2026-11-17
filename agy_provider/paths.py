"""Shared authorized session data root and Windows filesystem paths."""

import os
import re
import shutil
import time
from pathlib import Path

_NAMESPACE_RE = re.compile(r"^[0-9a-f]{16}$")


def windows_long_path(path: Path) -> Path:
    """在 Windows 上转换为扩展长度绝对路径，且不解析符号链接。"""
    if os.name != "nt":
        return path
    value = os.fspath(path)
    if value.startswith(("\\\\?\\", "\\\\.\\")):
        return path
    # 添加前缀前先规范化相对路径、分隔符和点号组件：Win32 对扩展路径会跳过该规范化。
    value = os.path.abspath(value)
    if value.startswith("\\\\"):
        return Path("\\\\?\\UNC\\" + value[2:])
    return Path("\\\\?\\" + value)


def plugin_data_root(base: Path | None = None) -> Path:
    if base is None:
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path
        except ImportError:
            # 独立 CLI 模式：从 AstrBot 工作目录推导，或由调用方显式传入。
            base = Path.cwd() / "data" / "plugin_data"
        else:
            base = Path(get_astrbot_plugin_data_path())
    return base / "astrbot_plugin_antigravity_acp"


def remove_tree_robust(path: Path) -> None:
    """在线程中删除隔离目录；在 Windows 上对短暂的子进程句柄释放延迟做有界重试。"""
    target = windows_long_path(path)
    attempts = 6 if os.name == "nt" else 1
    for idx in range(attempts):
        if not target.exists():
            return
        if idx < attempts - 1:
            try:
                shutil.rmtree(target)
                return
            except OSError:
                time.sleep(0.03 * (idx + 1))
        else:
            shutil.rmtree(target, ignore_errors=True)


def cleanup_stale_dirs(
    root: Path,
    *,
    active_names: set[str] | frozenset[str] = frozenset(),
    min_age_seconds: float = 3600.0,
    now: float | None = None,
) -> int:
    """清理插件隔离数据根下因异常退出遗留的陈旧临时目录，绝不触碰外部或活跃目录。"""
    root = windows_long_path(root)
    if not root.exists():
        return 0
    current = time.time() if now is None else now
    removed = 0
    try:
        entries = list(os.scandir(root))
    except OSError:
        return 0
    for entry in entries:
        try:
            if not entry.is_dir(follow_symlinks=False):
                continue
            name = entry.name
            if name.startswith(("preflight-", "login-")):
                if name not in active_names and current - entry.stat(follow_symlinks=False).st_mtime >= min_age_seconds:
                    shutil.rmtree(entry.path, ignore_errors=True)
                    removed += 1
            elif _NAMESPACE_RE.fullmatch(name):
                try:
                    sub_entries = list(os.scandir(entry.path))
                except OSError:
                    continue
                for sub in sub_entries:
                    try:
                        if (
                            sub.is_dir(follow_symlinks=False)
                            and sub.name.startswith("runtime-")
                            and sub.name not in active_names
                            and current - sub.stat(follow_symlinks=False).st_mtime >= min_age_seconds
                        ):
                            shutil.rmtree(sub.path, ignore_errors=True)
                            removed += 1
                    except OSError:
                        continue
                try:
                    os.rmdir(entry.path)
                except OSError:
                    pass
        except OSError:
            continue
    return removed
