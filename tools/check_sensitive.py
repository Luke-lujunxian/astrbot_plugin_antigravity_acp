#!/usr/bin/env python3
"""轻量敏感信息扫描（防再发生，issue #18 P1）。

扫描邮箱、中国大陆手机号、凭据与认证元数据模式，用于 CI 与提交前检查。
用法：
  python3 tools/check_sensitive.py            # 扫描整个仓库
  python3 tools/check_sensitive.py --staged   # 仅扫描 Git 暂存区变更文件（适合 pre-commit）
  python3 tools/check_sensitive.py 文件/目录  # 指定路径
返回码：0 = 无命中；1 = 命中敏感模式（CI 失败）。
白名单只放通用占位符，不放真实账号；命中检查点请先人工确认。
"""
import re
import subprocess
import sys
from pathlib import Path

EXCLUDE_DIRS = {
    ".git", "__pycache__", "node_modules", ".pytest_cache", ".ruff_cache",
    ".venv", "data", "cache", ".hermes", "scratch",
}
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".zip", ".db",
                   ".pyc", ".lock", ".woff", ".woff2", ".icns", ".ico"}
# 通用占位符域名/示例值，不视为泄露
ALLOW_TOKENS = {
    "example.com", "example.org", "example.net", "example.cn",
    "your@email.com", "user@example.com", "noreply@github.com",
    "users.noreply.github.com", "placeholder", "REDACTED", "«EMAIL»",
}
# Python 装饰器（@unittest.skipUnless 等）易被邮箱正则误判
DECORATOR_RX = re.compile(
    r"@(?:unittest|pytest|asyncio|dataclass|classmethod|staticmethod|property|"
    r"register|app|router|skip|wraps|contextmanager|abstractmethod)\b")
# 扫描器自身含正则字符串，跳过
SELF_PATH = "tools/check_sensitive.py"
# 保持与 issue #18 一致的脱敏占位
REDACTED_MARKERS = {"已从公开记录中移除"}

PATTERNS = [
    # 邮箱：排除已在 ALLOW_TOKENS 中出现的完整匹配
    ("email", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+")),
    # 中国大陆手机号
    ("phone", re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")),
    # GitHub / OpenAI / Google API key 及 Google OAuth 令牌形态
    ("secret", re.compile(
        r"(?:\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
        r"sk-[A-Za-z0-9]{20,}|AIza[A-Za-z0-9_\-]{20,}|xox[baprs]-[A-Za-z0-9\-]{10,}|"
        r"ya29\.[A-Za-z0-9_\-]{20,})\b|(?<![A-Za-z0-9])1//[0-9A-Za-z_\-]{20,})")),
    # 内嵌账密的代理或 HTTP URL
    ("url_cred", re.compile(
        r"(?:https?|socks5h?)://[^/\s:@'\"<>]+:[^/\s@'\"<>]+@[A-Za-z0-9.\-\[\]]+")),
    # 认证元数据关键字（账号标识伴随的字段名）
    ("auth_meta", re.compile(
        r"(authMethod\s*[=:]\s*\S+|quotaProject\s*[=:]\s*\S+|applyAuthResult|"
        r"access_token\s*[=:]\s*\S+|refresh_token\s*[=:]\s*\S+|"
        r"client_secret\s*[=:]\s*\S+|password\s*[=:]\s*['\"]?\S+)", re.I)),
]

URL_CRED_PLACEHOLDERS = ("fake", "example", "placeholder", "redacted", "user:pass@")


def scan(path: Path):
    hits = []
    explicit_file = path.is_file()
    if explicit_file:
        files = [path]
    else:
        files = [p for p in path.rglob("*") if p.is_file()]
    for f in files:
        rel = f.as_posix()
        if rel.endswith(SELF_PATH):
            continue
        if not explicit_file:
            # 递归发现时按目录名排除；显式指定的文件始终扫描
            parts = set(rel.split("/"))
            if parts & EXCLUDE_DIRS:
                continue
        if f.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            if DECORATOR_RX.search(line):
                # 该行是装饰器，跳过邮箱匹配（其余规则仍生效）
                line_for_email = DECORATOR_RX.sub("", line)
            else:
                line_for_email = line
            for kind, rx in PATTERNS:
                src = line_for_email if kind == "email" else line
                for m in rx.finditer(src):
                    hit = m.group(0)
                    if kind == "email":
                        if hit in ALLOW_TOKENS:
                            continue
                        # scheme://user:pass@host 交由 url_cred 规则归类与白名单判定
                        if m.start() > 0 and src[m.start() - 1] == ":" and "://" in src[: m.start()]:
                            continue
                    if kind == "url_cred" and any(
                        token in hit.lower() for token in URL_CRED_PLACEHOLDERS
                    ):
                        continue
                    if any(mark in line for mark in REDACTED_MARKERS):
                        continue
                    # 摘要化展示，避免在 CI 日志粘贴原文
                    digest = hit if hit in ALLOW_TOKENS else f"{hit[:6]}…{hit[-4:]}"
                    hits.append(f"{rel}:{lineno} [{kind}] {digest}")
    return hits


def staged_files() -> list[Path]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    if result.returncode != 0:
        print("无法读取 Git 暂存区文件列表。", file=sys.stderr)
        sys.exit(2)
    return [Path(line) for line in result.stdout.splitlines() if line.strip()]


def main():
    args = sys.argv[1:]
    if "--staged" in args:
        extra = [a for a in args if a != "--staged"]
        if extra:
            print("--staged 不能与显式路径同时指定。", file=sys.stderr)
            return 2
        roots = staged_files()
        if not roots:
            print("敏感扫描通过：暂存区无待检文件")
            return 0
    else:
        roots = [Path(a) for a in args] or [Path(".")]
    total = []
    for r in roots:
        total.extend(scan(r))
    if total:
        for h in sorted(set(total)):
            print(f"SENSITIVE: {h}", file=sys.stderr)
        print(f"命中 {len(set(total))} 处，请人工核实并脱敏", file=sys.stderr)
        return 1
    print("敏感扫描通过：无命中")
    return 0


if __name__ == "__main__":
    sys.exit(main())