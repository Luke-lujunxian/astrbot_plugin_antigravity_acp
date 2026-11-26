"""Exercise the shipped command bodies without importing a running AstrBot."""

import ast
import asyncio
import sys
import sqlite3
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from tests import astrbot_stub  # noqa: F401 -- install the offline host logger

from agy_provider.admin_commands import admin_command, HELP, quota_text, usage_text
from agy_provider.config import Settings
from agy_provider.errors import AgyError
from agy_provider.onboarding import next_step
from agy_provider.telemetry import format_cost_report


class CommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        path = Path(__file__).resolve().parents[1] / "main.py"
        tree = ast.parse(path.read_text(encoding="utf-8"))
        plugin = next(node for node in tree.body if isinstance(node, ast.ClassDef))
        commands = [
            node
            for node in plugin.body
            if isinstance(node, ast.AsyncFunctionDef)
            and node.name in {"setup", "use", "doctor", "cost", "help", "models", "status", "quota", "usage"}
        ]
        for node in commands:
            node.decorator_list = [d for d in node.decorator_list if isinstance(d, ast.Name) and d.id == "admin_command"]
        self.snapshots = []
        namespace = {
            "AstrMessageEvent": object, "admin_command": admin_command, "HELP": HELP,
            "sqlite3": sqlite3, "daily_snapshot": lambda days: {"days": [], "range": {"days": days}},
            "quota_text": quota_text, "usage_text": usage_text, "PLUGIN_VERSION": "test",
            "AgyError": AgyError,
            "Settings": Settings,
            "next_step": next_step,
            "format_cost_report": format_cost_report,
            "instance_cost_snapshots": lambda: list(self.snapshots),
            "asyncio": asyncio,
            "json": __import__("json"),
        }
        exec(
            compile(ast.Module(body=commands, type_ignores=[]), str(path), "exec"),
            namespace,
        )
        self.commands = namespace
        self.manager = types.SimpleNamespace(set_provider=AsyncMock())
        service = types.SimpleNamespace(
            _available=lambda: None,
            busy=False,
            login=types.SimpleNamespace(busy=False),
            report={"status": "passed"},
            settings=Settings(),
            providers=lambda: [
                {"id": "enabled", "model": "gemini-test", "enabled": True, "tools_mode": "chat"},
                {"id": "disabled", "model": "gemini-test", "enabled": False, "tools_mode": "inherit"},
            ],
        )
        self.plugin = types.SimpleNamespace(
            setup_service=service,
            config={},
            stopping=False,
            context=types.SimpleNamespace(provider_manager=self.manager),
            doctor_lock=asyncio.Lock(),
        )
        self.event = types.SimpleNamespace(
            is_admin=lambda: True, send=AsyncMock(), stop_event=Mock(), should_call_llm=Mock(),
            plain_result=lambda text: text,
            unified_msg_origin="target-session",
        )
        entities = types.ModuleType("astrbot.core.provider.entities")
        entities.ProviderType = types.SimpleNamespace(CHAT_COMPLETION="chat_completion")
        module_patch = patch.dict(
            sys.modules, {"astrbot.core.provider.entities": entities}
        )
        module_patch.start()
        self.addCleanup(module_patch.stop)

    async def collect(self, name, *args):
        return [
            item async for item in self.commands[name](self.plugin, self.event, *args)
        ]

    async def test_all_commands_deny_non_admin_direct_invocation(self):
        self.event.is_admin = lambda: False
        for name in ("setup", "use", "doctor", "cost", "help", "models", "status", "quota", "usage"):
            self.assertEqual(await self.collect(name), [])
            self.event.send.assert_awaited_with("AGY [FORBIDDEN] 仅管理员可使用此指令。")
            self.event.stop_event.assert_called_once()
            self.event.stop_event.reset_mock()
            self.event.should_call_llm.assert_called_with(True)
        self.manager.set_provider.assert_not_awaited()

    async def test_new_commands_and_usage_parameters(self):
        help_text = (await self.collect("help"))[0]
        for command in ("setup", "use", "cost", "doctor", "help", "models", "status", "quota", "usage"):
            self.assertIn("/agy " + command, help_text)
        self.assertIn("已加载 0", (await self.collect("status"))[0])
        self.assertIn("disabled · gemini-test · 停用", (await self.collect("models"))[0])
        self.assertIn("没有本地", (await self.collect("usage", "30"))[0])
        self.assertIn("用法", (await self.collect("usage", "31"))[0])
        quota = AsyncMock(return_value={"groups": [], "fetched_at": None, "error": {"message": "登录失效"}})
        self.plugin.setup_service.quota = types.SimpleNamespace(refresh=quota)
        self.assertIn("登录失效", (await self.collect("quota"))[0])
        quota.assert_awaited_once_with()

    async def test_usage_heatmap_keeps_unknown_days_separate(self):
        today = {"date": "2026-11-26", "requests": 2, "success": 1, "failed": 1, "input_tokens": 0,
                 "output_tokens": 0, "total_tokens": 0, "usage_unknown_turns": 1}
        days = [dict(today, date="2026-11-24", usage_unknown_turns=0), today]
        self.commands["daily_snapshot"] = lambda span: {"range": {"days": span, "end": today["date"]}, "days": days}
        text = (await self.collect("usage"))[0]
        self.assertIn("·0·?", text)

    async def test_use_only_changes_target_session(self):
        result = await self.collect("use", "enabled")
        self.manager.set_provider.assert_awaited_once_with(
            "enabled", "chat_completion", "target-session"
        )
        self.assertIn("已切换", result[0])

    async def test_disabled_non_agy_and_unknown_provider_denied(self):
        for provider_id in ("disabled", "other-provider", "", "unknown"):
            result = await self.collect("use", provider_id)
            self.assertIn("CONFIG", result[0])
        self.manager.set_provider.assert_not_awaited()

    async def test_stopping_plugin_rejects_commands(self):
        self.plugin.stopping = True
        for name in ("setup", "use", "doctor", "cost"):
            self.assertTrue(await self.collect(name))
        self.manager.set_provider.assert_not_awaited()

    async def test_cost_command_readonly_and_formats_instance_stats(self):
        self.snapshots.append(
            {
                "provider_id": "agy_chat",
                "model": "gemini-test",
                "tools_mode": "chat",
                "effective_mode": "chat",
                "pool": {"active_sessions": 1, "live_processes": 1, "max_sessions": 16},
                "summary": {
                    "total_turns": 2,
                    "request_sent_turns": 2,
                    "short_circuited_turns": 0,
                    "reused_turns": 1,
                    "reuse_rate": 0.5,
                    "candidate_turns": 1,
                    "candidate_reuse_rate": 1.0,
                    "reported_usage_turns": 2,
                    "unavailable_usage_turns": 0,
                    "unavailable_ratio": 0.0,
                    "missing_cache_field_turns": 0,
                    "total_input_other": 100,
                    "total_input_cached": 800,
                    "total_input": 900,
                    "total_output": 50,
                    "cache_token_ratio": 800 / 900,
                    "median_input_other": 50,
                    "median_total_input": 450,
                    "failed_reported_turns": 0,
                    "failed_input_other": 0,
                    "failed_input_cached": 0,
                    "failed_output": 0,
                    "rebuild_reasons": [("cold_start", 1)],
                    "evictions": {},
                },
            }
        )
        output = (await self.collect("cost"))[0]
        self.assertIn("只读，未发送模型请求", output)
        self.assertIn("agy_chat", output)
        self.assertIn("reuse=strict", output)
        self.assertIn("50.0%", output)

    async def test_setup_explains_native_entry_without_login_material(self):
        result = (await self.collect("setup"))[0]
        self.assertIn("首次设置", result)
        self.assertIn("enabled", result)
        self.assertNotIn("accounts.google.com", result)
