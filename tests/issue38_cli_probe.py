"""Manual Linux acceptance: quota is read-only; read issues exactly one model prompt."""

import argparse
import asyncio
import secrets
import tempfile
from pathlib import Path
from types import SimpleNamespace

from tests import astrbot_stub  # only supplies the host logger
from agy_provider.config import Settings
from agy_provider.errors import AgyError
from agy_provider.models import select
from agy_provider.quota import QuotaService
from agy_provider.sessions import Runtime, Session
from agy_provider.tools import ToolSnapshot


async def run(args):
    settings = Settings(command=args.command, builtin_read_file="allow_once", enable_tools=True,
                        tool_max_calls=1, request_timeout=60)
    if args.action == "quota":
        service = QuotaService(settings)
        try:
            data = await service.refresh()
            groups = data["groups"]
            code = data["error"]["code"] if data["error"] else None
            print("version", data["cli_version"], "groups", len(groups),
                  "buckets", sum(len(g["buckets"]) for g in groups), "error", code,
                  "cached", bool(service.snapshot()["fetched_at"]))
            return 1 if code else 0
        finally:
            await service.close()

    with tempfile.TemporaryDirectory() as directory:
        runtime = Runtime(settings, Path(directory))
        session = Session()
        snapshot = ToolSnapshot(SimpleNamespace(tools=[SimpleNamespace(
            name="echo", active=True, description="Echo", parameters={"type": "object", "properties": {}})]))
        try:
            options = await runtime.open(session, "", snapshot)
            if not session.broker.read_workspace or not session.client.verified_read:
                print("unsupported; no prompt sent")
                return 1
            await select(session.client, options, args.model, "low")
            marker = secrets.token_hex(8)
            (session.broker.read_workspace / "sample.txt").write_text(marker)
            parts = []
            async for event in session.client.generate("Read sample.txt using read_file. Reply with its contents."):
                if event.kind == "text":
                    parts.append(event.text)
            matched = marker in "".join(parts)
            calls = session.broker.count
            grants = sum(session.broker.read_decisions.values())
            print("verified_read", session.client.verified_read, "terminal", session.client.terminal_reason,
                  "matched", matched, "calls", calls, "grants", grants)
            return 0 if matched and calls == grants == 1 and session.client.terminal_reason == "end_turn" else 1
        finally:
            await session.close()
            await runtime.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("quota", "read"))
    parser.add_argument("--command", default="")
    parser.add_argument("--model", default="")
    arguments = parser.parse_args()
    if arguments.action == "read" and not arguments.model:
        parser.error("read requires --model")
    try:
        raise SystemExit(asyncio.run(run(arguments)))
    except AgyError as exc:
        print("CLI check failed", exc.code)
        raise SystemExit(1)
