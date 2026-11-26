"""On-demand official CLI /usage. Keep only projected quota fields in memory."""

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import stat
import time
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .errors import AgyError
from .process import build_child_env, capture, cli_version, resolve_binary, spawn, stop_process

MESSAGES = {
    "AUTH": "请在环境与认证页完成官方 CLI 登录。",
    "TIMEOUT": "额度查询超时。",
    "NOT_INSTALLED": "未找到配置的 AGY CLI。",
    "UNSUPPORTED": "此 CLI 未确认支持无生成的额度查询。",
    "QUOTA_FORMAT": "CLI 返回的额度格式无法识别。",
    "QUOTA_FAILED": "官方 CLI 未能完成额度查询。",
    "ENV_CHANGED": "登录环境已变化，请重新查询。",
}


def _label(value):
    if not isinstance(value, str) or not re.fullmatch(r"[\w ()+.,/–-]{1,200}", value):
        raise ValueError
    return value


def _groups(raw):
    try:
        payload = json.loads(raw)
        if not isinstance(payload, dict) or not isinstance(payload.get("status"), str):
            raise ValueError
        if payload["status"].lower() not in {"success", "complete"}:
            if "authenticat" in str(payload.get("error", "")).lower():
                raise AgyError("AUTH", MESSAGES["AUTH"])
            raise AgyError("QUOTA_FAILED", MESSAGES["QUOTA_FAILED"])
        command = payload["command"]
        if command["name"] != "usage" or ("num_turns" in payload and (type(payload["num_turns"]) is not int or payload["num_turns"] != 0)):
            raise ValueError
        groups = command["data"]["groups"]
        if not isinstance(groups, list):
            raise ValueError
        projected = []
        for group in groups:
            models = []
            description = group.get("description")
            prefix = "Models within this group:"
            if isinstance(description, str) and description.startswith(prefix):
                models = [_label(name.strip()) for name in description[len(prefix):].split(",") if name.strip()]
            buckets = []
            if not isinstance(group["buckets"], list):
                raise ValueError
            for row in group["buckets"]:
                fraction = row["remaining_fraction"]
                if type(fraction) not in (int, float) or not 0 <= fraction <= 1:
                    raise ValueError
                stamp = row.get("reset_time")
                if stamp is not None:
                    parsed = datetime.fromisoformat(stamp)
                    if parsed.tzinfo is None:
                        raise ValueError
                    utc = parsed.astimezone(timezone.utc)
                    stamp = None if fraction == 1 and utc == datetime(1970, 1, 1, tzinfo=timezone.utc) else utc.isoformat()
                buckets.append({"id": _label(row["id"]), "name": _label(row["name"]),
                                "window": _label(row["window"]), "remaining_fraction": fraction,
                                "reset_time": stamp})
            projected.append({"name": _label(group["name"]), "models_shared": models, "buckets": buckets})
        return projected
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        raise AgyError("QUOTA_FORMAT", MESSAGES["QUOTA_FORMAT"]) from None


async def _usage(binary, env, cwd):
    proc = await spawn([binary, "-p", "/usage", "--output-format", "json"], cwd, env=env)
    async def stdout():
        buf = bytearray()
        while chunk := await proc.stdout.read(8192):
            if len(buf) + len(chunk) > 256 * 1024:
                raise AgyError("QUOTA_FORMAT", MESSAGES["QUOTA_FORMAT"])
            buf.extend(chunk)
        return buf

    async def stderr():
        tail = b""
        while chunk := await proc.stderr.read(4096):
            window = tail + chunk.lower()
            if any(marker in window for marker in (b"accounts.google.com/", b"oauth2/auth",
                    b"authentication failed", b"authorization code", b"sign in to continue")):
                raise AgyError("AUTH", MESSAGES["AUTH"])
            if b"unknown flag" in window or b"unknown command" in window:
                raise AgyError("UNSUPPORTED", MESSAGES["UNSUPPORTED"])
            tail = window[-64:]

    tasks = [asyncio.create_task(stdout()), asyncio.create_task(stderr())]
    try:
        proc.stdin.close()
        out, _ = await asyncio.gather(*tasks)
        rc = await proc.wait()
        if rc != 0:
            if b"authentication failed" in out.lower():
                raise AgyError("AUTH", MESSAGES["AUTH"])
            raise AgyError("QUOTA_FAILED", MESSAGES["QUOTA_FAILED"])
        return _groups(out)
    finally:
        try:
            await stop_process(proc)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def _environment():
    # Metadata changes (including atomic replacement) invalidate even warm data.
    home = Path.home()
    try:
        info = (home / ".gemini/antigravity-cli/antigravity-oauth-token").lstat()
        stamp = (info.st_dev, info.st_ino, info.st_mtime_ns, info.st_ctime_ns, info.st_size)
        observable = stat.S_ISREG(info.st_mode)
    except OSError:
        stamp, observable = None, False
    return (str(home), os.environ.get("XDG_CONFIG_HOME"), os.environ.get("XDG_DATA_HOME"),
            os.environ.get("DBUS_SESSION_BUS_ADDRESS"), stamp), observable


class QuotaService:
    def __init__(self, settings):
        self.settings = settings
        self.secret = secrets.token_bytes(32)
        self.key = None
        self.task = None
        self.closed = False
        self.generation = 0
        self.invalidate()

    def invalidate(self):
        self.generation += 1
        self.data = {}
        self.updated = None
        self.error = None

    def _sync(self):
        key, observable = _environment()
        if self.key != key:
            self.key = key
            self.invalidate()
        return observable

    def snapshot(self):
        self._sync()
        env_id = hmac.new(self.secret, repr(self.key).encode(), hashlib.sha256).hexdigest()[:16]
        return {"schema_version": 1, "source": "official_cli", "login_env": env_id,
                "cli_version": None, "capability": "unknown", "groups": [], "fetched_at": None,
                **self.data, "stale": bool(self.error or (
                    self.updated is not None and time.monotonic() - self.updated >= 60)), "error": self.error}

    async def refresh(self, *, force=False):
        if self.closed:
            raise AgyError("CLOSED", "插件已停用。")
        data = self.snapshot()
        generation = self.generation
        if self.task is None or self.task.done():
            if not force and data["fetched_at"] and not data["stale"]:
                return data
            self.task_generation = generation
            self.task = asyncio.create_task(self._refresh(generation))
            self.task.add_done_callback(self._finished)
        same_environment = generation == self.task_generation
        try:
            result = await asyncio.shield(self.task)
        except asyncio.CancelledError:
            if not self.closed or asyncio.current_task().cancelling():
                raise
            raise AgyError("CLOSED", "插件已停用。") from None
        if self.closed:
            raise AgyError("CLOSED", "插件已停用。")
        return result if same_environment else await self.refresh(force=force)

    def _finished(self, task):
        if self.task is task:
            self.task = None

    async def _refresh(self, generation):
        version = code = None
        try:
            async with asyncio.timeout(30):
                binary = resolve_binary(self.settings)
                env = build_child_env(self.settings)
                banner = await capture([binary, "--version"], 30, env=env)
                version = cli_version(banner)
                # Older clients may treat an unknown slash command as a prompt.
                if not version or tuple(map(int, version.split("."))) < (1, 5, 17):
                    raise AgyError("UNSUPPORTED", MESSAGES["UNSUPPORTED"])
                with tempfile.TemporaryDirectory(prefix="agy-usage-") as directory:
                    groups = await _usage(binary, env, Path(directory))
        except TimeoutError:
            code = "TIMEOUT"
        except AgyError as exc:
            code = "NOT_INSTALLED" if exc.code == "COMMAND_NOT_FOUND" else exc.code
            if code not in MESSAGES:
                code = "QUOTA_FAILED"
        except (OSError, ValueError):
            code = "QUOTA_FAILED"
        observable = self._sync()
        if generation != self.generation:
            return {**self.snapshot(), "stale": True, "groups": [], "fetched_at": None,
                    "error": {"code": "ENV_CHANGED", "message": MESSAGES["ENV_CHANGED"]}}
        if code == "AUTH":
            self.invalidate()
        self.data["cli_version"] = version
        if code:
            self.error = {"code": code, "message": MESSAGES[code]}
            if code == "UNSUPPORTED":
                self.data["capability"] = "unsupported"
        else:
            self.error = None
            self.updated = time.monotonic()
            self.data.update(groups=groups, capability="supported", fetched_at=datetime.now(timezone.utc).isoformat())
        result = self.snapshot()
        if not observable:
            self.invalidate()
        return result

    async def close(self):
        self.closed = True
        self.invalidate()
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
