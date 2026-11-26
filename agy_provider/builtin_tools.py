"""CLI capabilities with evidence for the pinned permission protocol."""

import os
import re
import stat
import sys
from pathlib import Path

from .errors import AgyError
from .process import cli_version

BUILTINS = {
    "read_file": ("读取隔离工作区顶层文本文件", "high"),
    "search_web": ("联网搜索", "network"),
    "run_command": ("执行终端命令", "high"),
    "write_file": ("写入文件", "high"),
    "browser": ("操作浏览器", "high"),
    "read_url": ("读取网页", "network"),
    "execute_url": ("执行网页操作", "high"),
}


class BuiltinDenied(AgyError):
    def __init__(self, code="TOOL_PERMISSION"):
        super().__init__(code, "当前工具策略禁止此次 CLI 内置工具调用。",
                         no_retry=True, no_fallback=True)


def supports_read(version):
    return sys.platform == "linux" and cli_version(version) == "1.5.17"


def tool_policy(settings, saved, supported):
    rows = [dict(id="astrbot_mcp", source="mcp", purpose="宿主提供的工具", risk="host",
                 capability="supported", choices=[], policy="allow_once", effective=settings.enable_tools)]
    for name, (purpose, risk) in BUILTINS.items():
        read = name == "read_file"
        capability = ("supported" if supported else "unverified") if read else "unsupported"
        rows.append(dict(id=name, source="builtin", purpose=purpose, risk=risk,
                         capability=capability, choices=["deny", "allow_once"] if read and supported else ["deny"],
                         policy=saved if read else "deny", effective=bool(
                             read and supported and settings.enable_tools and settings.builtin_read_file == "allow_once")))
    return {"enable_tools": settings.enable_tools, "reload_required": saved != settings.builtin_read_file,
            "tools": rows}


def read_target(call, workspace):
    """Check metadata only. CLI owns the read in its private session workspace."""
    args = call.get("rawInput")
    if (workspace is None or call.get("kind") != "read" or not isinstance(args, dict)
            or set(args) != {"Path"} or call.get("args") != args):
        return None
    raw = args["Path"]
    if not isinstance(raw, str) or len(raw) > 4096:
        return None
    path = Path(raw)
    if (path.parent != workspace or str(path) != raw
            or not re.fullmatch(r"[a-zA-Z0-9_-][a-zA-Z0-9_.-]{0,120}\.txt", path.name)
            or call.get("locations") != [{"path": raw}]):
        return None
    try:
        info = path.lstat()
        parent = workspace.lstat()
        if (workspace.resolve(strict=True) == workspace and stat.S_ISDIR(parent.st_mode)
                and parent.st_uid == os.getuid() and not parent.st_mode & 0o077
                and stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and info.st_uid == os.getuid() and not info.st_mode & 0o022):
            return raw
    except (OSError, RuntimeError, ValueError):
        pass
    return None
