"""受固定权限协议证据约束的 CLI 原生工具统一注册表与参数校验。"""

import os
import re
import stat
import sys
from dataclasses import dataclass
from pathlib import Path

from .errors import AgyError
from .process import cli_version

VERIFIED_READ_VERSIONS = frozenset({"1.5.17", "1.5.18"})
SEARCH_ABORTED_NOTICE = "检测到 CLI 联网搜索，已中止本轮；该搜索请求可能已经发出。"
NON_SEARCH_ABORTED_NOTICE = "检测到 CLI 尝试调用未授权的内置工具，已中止本轮。"

_READ_INT_BOUNDS = {
    "StartLine": (1, 10_000_000),
    "EndLine": (1, 10_000_000),
    "ByteOffset": (0, 100_000_000),
}
_READ_ALL_ARGS = frozenset({"Path", *_READ_INT_BOUNDS})


@dataclass(frozen=True)
class BuiltinToolSpec:
    """CLI 原生工具的能力、授权方式、预算与风险等级定义。"""

    id: str
    purpose: str
    risk: str
    auth_mode: str = "denied"  # pre_permission | post_observation | denied
    budgeted: bool = False
    choices: tuple[str, ...] = ("deny",)
    platforms: tuple[str, ...] = ()
    verified_versions: frozenset[str] = frozenset()
    ui_visible: bool = True
    limitation: str = ""


BUILTIN_SPECS: dict[str, BuiltinToolSpec] = {
    "read_file": BuiltinToolSpec(
        id="read_file",
        purpose="读取隔离工作区顶层文本文件",
        risk="high",
        auth_mode="pre_permission",
        budgeted=True,
        choices=("deny", "allow_once"),
        platforms=("linux",),
        verified_versions=VERIFIED_READ_VERSIONS,
    ),
    "search_web": BuiltinToolSpec(
        id="search_web",
        purpose="联网搜索",
        risk="network",
        auth_mode="post_observation",
        budgeted=True,
        choices=("deny", "allow"),
        limitation=(
            "CLI 自动执行搜索，无法在执行前审批。关闭时由模型护栏和事后中止限制，"
            "发现时搜索请求可能已发出。开启后按通知计入预算，超预算时中止本轮。"
        ),
    ),
    "edit_file": BuiltinToolSpec("edit_file", "编辑文件", "high"),
    "write_file": BuiltinToolSpec("write_file", "写入文件", "high"),
    "run_command": BuiltinToolSpec("run_command", "执行终端命令", "high"),
    "read_url": BuiltinToolSpec("read_url", "读取网页", "network"),
    "execute_url": BuiltinToolSpec("execute_url", "执行网页操作", "high"),
    "browser": BuiltinToolSpec("browser", "操作浏览器", "high"),
    # CLI 1.5.18 声明或历史引擎存在的其余内置工具：统一在后台拒止，不向面板铺陈内部调度项
    "ask_question": BuiltinToolSpec("ask_question", "发起交互提问", "internal", ui_visible=False),
    "update_steps": BuiltinToolSpec("update_steps", "更新内部步骤", "internal", ui_visible=False),
    "manage_task": BuiltinToolSpec("manage_task", "管理后台任务", "internal", ui_visible=False),
    "schedule": BuiltinToolSpec("schedule", "创建定时任务", "high", ui_visible=False),
    "define_subagent": BuiltinToolSpec("define_subagent", "定义子代理", "high", ui_visible=False),
    "invoke_subagent": BuiltinToolSpec("invoke_subagent", "启动子代理", "high", ui_visible=False),
    "manage_subagents": BuiltinToolSpec("manage_subagents", "管理子代理", "high", ui_visible=False),
    "send_message": BuiltinToolSpec("send_message", "发送代理消息", "internal", ui_visible=False),
    "run_workflow": BuiltinToolSpec("run_workflow", "执行工作流脚本", "high", ui_visible=False),
    "swarm": BuiltinToolSpec("swarm", "协同代理蜂群", "high", ui_visible=False),
    "read_url_content": BuiltinToolSpec("read_url_content", "读取网页正文", "network", ui_visible=False),
    "list_dir": BuiltinToolSpec("list_dir", "浏览目录", "high", ui_visible=False),
    "list_directory": BuiltinToolSpec("list_directory", "浏览目录", "high", ui_visible=False),
    "find_by_name": BuiltinToolSpec("find_by_name", "按名查找文件", "high", ui_visible=False),
    "find_file": BuiltinToolSpec("find_file", "查找文件", "high", ui_visible=False),
    "grep_search": BuiltinToolSpec("grep_search", "检索文件内容", "high", ui_visible=False),
    "search_directory": BuiltinToolSpec("search_directory", "检索目录内容", "high", ui_visible=False),
    "view_file": BuiltinToolSpec("view_file", "查看文件", "high", ui_visible=False),
    "write_to_file": BuiltinToolSpec("write_to_file", "写入文件", "high", ui_visible=False),
    "replace_file_content": BuiltinToolSpec("replace_file_content", "替换文件内容", "high", ui_visible=False),
    "multi_replace_file_content": BuiltinToolSpec(
        "multi_replace_file_content", "批量替换文件内容", "high", ui_visible=False
    ),
}

BUILTINS = {
    name: (spec.purpose, spec.risk)
    for name, spec in BUILTIN_SPECS.items()
    if spec.ui_visible
}
KNOWN_BUILTIN_NAMES = frozenset(BUILTIN_SPECS)


class BuiltinDenied(AgyError):
    def __init__(self, code="TOOL_PERMISSION", message="当前工具策略禁止此次 CLI 内置工具调用。", user_notice=None):
        # user_notice 仅在 CLI 先于插件拦截前执行（或需明确告知非搜索拒止）时替换通用聊天提示
        super().__init__(code, message, no_retry=True, no_fallback=True)
        self.user_notice = user_notice


def is_known_builtin(name: object) -> bool:
    """判断工具名是否属于已登记的 CLI 内置工具或历史候选名称。"""
    return isinstance(name, str) and name in KNOWN_BUILTIN_NAMES


def builtin_notice(raw_name: object) -> str:
    """按具体内置工具返回诚实的拒止提示文案，避免非搜索工具误报搜索提示。"""
    return SEARCH_ABORTED_NOTICE if raw_name == "search_web" else NON_SEARCH_ABORTED_NOTICE


def supports_read(version):
    """仅对已实测验证 사전 session/request_permission 协议的 Linux CLI 版本开放。"""
    return sys.platform == "linux" and cli_version(version) in VERIFIED_READ_VERSIONS


def builtin_tools_configured(settings) -> bool:
    """判断总闸开启后是否存在可脱离宿主 MCP 独立激活的原生工具。"""
    if not getattr(settings, "enable_tools", False):
        return False
    if getattr(settings, "builtin_search_web", "deny") == "allow":
        return True
    if getattr(settings, "builtin_read_file", "deny") == "allow_once" and sys.platform == "linux":
        return True
    return False


def tool_policy(settings, saved_read, supported, saved_search="deny"):
    """生成面板与接口使用的工具权限策略快照。"""
    rows = [dict(id="astrbot_mcp", source="mcp", purpose="宿主提供的工具", risk="host",
                 capability="supported", choices=[], policy="allow_once", effective=settings.enable_tools,
                 reload_required=False)]
    for spec in BUILTIN_SPECS.values():
        if not spec.ui_visible:
            continue
        row = dict(id=spec.id, source="builtin", purpose=spec.purpose, risk=spec.risk,
                   capability="unsupported", choices=["deny"], policy="deny", effective=False,
                   reload_required=False)
        if spec.id == "read_file":
            row.update(capability="supported" if supported else "unverified", policy=saved_read,
                       reload_required=saved_read != settings.builtin_read_file)
            if supported:
                row.update(choices=list(spec.choices), effective=(
                    settings.enable_tools and settings.builtin_read_file == "allow_once"))
        elif spec.id == "search_web":
            row.update(capability="experimental", choices=list(spec.choices), policy=saved_search,
                       effective=settings.enable_tools and settings.builtin_search_web == "allow",
                       reload_required=saved_search != settings.builtin_search_web,
                       pre_execution_approval=False, enforcement="post_observation",
                       limitation=spec.limitation)
        rows.append(row)
    return {"enable_tools": settings.enable_tools,
            "reload_required": any(row["reload_required"] for row in rows), "tools": rows}


def _valid_read_args(args: object) -> bool:
    """校验 read_file 参数结构及可选按行/字节偏移分页参数。"""
    if not isinstance(args, dict) or "Path" not in args or not (set(args) <= _READ_ALL_ARGS):
        return False
    for key, (low, high) in _READ_INT_BOUNDS.items():
        if key in args:
            val = args[key]
            if type(val) is not int or not low <= val <= high:
                return False
    if "StartLine" in args and "EndLine" in args and args["EndLine"] < args["StartLine"]:
        return False
    return True


def read_args_digest(args: object):
    """生成只读调用参数规范摘要，防止更新帧或审批请求篡改行范围/偏移量。"""
    if not isinstance(args, dict):
        return None
    return tuple(sorted(args.items()))


def read_target(call, workspace):
    """仅校验元数据；CLI 仅可在私有会话工作区执行受限顶层文本读取。"""
    args = call.get("rawInput")
    if (workspace is None or call.get("kind") != "read" or not _valid_read_args(args)
            or call.get("args") != args):
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
