import asyncio
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from agy_provider.builtin_tools import BuiltinDenied, supports_read
from agy_provider.errors import AgyError
from agy_provider.config import Settings
from agy_provider.tools import ToolBroker, ToolSnapshot
from agy_provider.transport import AcpClient
from tests.test_tools_mode import _load_provider_module, _tool


@unittest.skipUnless(sys.platform == "linux", "Scoped builtin reads are verified only on Linux")
class ReadPermissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.workspace = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.file = self.workspace / "sample_read.txt"
        self.file.write_text("test")
        settings = Settings(builtin_read_file="allow_once", enable_tools=True, tool_max_calls=1)
        self.broker = ToolBroker(ToolSnapshot(SimpleNamespace(tools=[_tool("read_file")])), settings)
        self.client = AcpClient(settings)
        self.client.verified_read = True
        self.client.tool_broker = self.broker
        self.client.proc = SimpleNamespace(returncode=None)
        self.client.active = self.broker.turn_active = True
        self.client.session_id = self.broker.session_id = "sess_redacted_1"
        self.broker.read_workspace = self.workspace
        self.client._write = AsyncMock()
        frames = Path(__file__).parent / "fixtures/issue38/read_file.json"
        self.frames = json.loads(frames.read_text().replace("/isolated/workspace", str(self.workspace)))

    def observe(self):
        self.client.prompt_deadline = asyncio.get_running_loop().time() + 10
        for frame in self.frames[:2]:
            self.client._on_update(frame["params"])

    async def authorize(self, request=None):
        await self.client._reject_request(request or self.frames[2])
        return self.client._write.call_args.args[0]["result"]["outcome"]["outcome"]

    async def test_real_frames_charge_before_io_and_share_mcp_budget(self):
        self.observe()
        self.assertEqual(await self.authorize(), "selected")
        self.assertEqual(self.broker.count, 1)
        self.assertEqual(await self.authorize(), "cancelled")
        self.client._on_update(self.frames[-1]["params"])
        with self.assertRaisesRegex(AgyError, "TOOL_BUDGET"):
            await self.broker.dispatch({"method": "tools/call", "id": 2, "params": {"name": "read_file",
                "_meta": {"antigravity.google/conversation_id": self.client.session_id,
                          "antigravity.google/root_conversation_id": self.client.session_id}}})
        self.broker.read_calls.clear()
        with self.assertRaises(BuiltinDenied):
            self.observe()

    async def test_running_peer_version_must_be_verified(self):
        self.observe()
        self.client.verified_read = False
        self.assertEqual(await self.authorize(), "cancelled")
        self.assertEqual(self.broker.count, 0)

    async def test_budget_used_by_mcp_denies_builtin(self):
        self.observe()
        self.broker.count = self.broker.settings.tool_max_calls
        self.assertEqual(await self.authorize(), "cancelled")
        self.assertEqual(self.broker.count, 1)

    async def test_cross_session_and_terminal_cannot_grant(self):
        self.observe()
        req = copy.deepcopy(self.frames[2])
        req["params"]["sessionId"] = "other"
        self.assertEqual(await self.authorize(req), "cancelled")
        self.client.prompt_terminal = True
        self.assertEqual(await self.authorize(), "cancelled")
        self.assertEqual(self.broker.count, 0)

    async def test_path_and_permission_must_agree_and_denial_is_final(self):
        self.observe()
        req = copy.deepcopy(self.frames[2])
        req["params"]["toolCall"]["rawInput"]["Path"] += ".txt"
        self.assertEqual(await self.authorize(req), "cancelled")
        self.assertEqual(await self.authorize(), "cancelled")
        self.assertEqual(self.broker.count, 0)

    async def test_replaced_with_link_between_observation_and_permission(self):
        self.observe()
        self.file.unlink()
        self.file.symlink_to(self.workspace / "private")
        self.assertEqual(await self.authorize(), "cancelled")
        self.assertEqual(self.broker.count, 0)

    async def test_denies_escape_hardlink_and_unverified_tools(self):
        other = Path(self.enterContext(tempfile.TemporaryDirectory())) / "sample_read.txt"
        other.write_text("outside")
        call = self.frames[0]["params"]["update"]
        wrong_path = dict(call, args={"Path": str(other)}, rawInput={"Path": str(other)},
                          locations=[{"path": str(other)}])
        with self.assertRaises(BuiltinDenied):
            self.broker.observe(wrong_path)
        os.link(self.file, self.workspace / "alias")
        with self.assertRaises(BuiltinDenied):
            self.observe()
        for name in ("search_web", "run_command", "write_file", "browser", "execute_url", "read_url"):
            with self.assertRaises(BuiltinDenied):
                self.broker.observe({"toolCallId": "x", "name": name})
        self.assertFalse(supports_read("1.5.18"))
        self.assertTrue(supports_read("agy 1.5.17"))
        self.assertEqual(self.broker.count, 0)


class DenialDeliveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_provider_finishes_denial_without_replay_then_accepts_next_message(self):
        import importlib
        from agy_provider.process import LaunchInfo

        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(sys.modules, _load_provider_module(root)))
        sys.modules.pop("agy_provider.provider", None)
        mod = importlib.import_module("agy_provider.provider")
        self.addCleanup(sys.modules.pop, "agy_provider.provider", None)
        mod.configure(Settings(enable_tools=True, auth_bridge=False))
        self.addCleanup(mod.configure, Settings())
        provider = mod.AgyProvider({"id": "tools", "model": "gemini-test"}, {})
        self.addAsyncCleanup(provider.terminate)
        self.enterContext(patch("agy_provider.sessions.discover", AsyncMock(return_value=LaunchInfo("fake", "1.5.17", False))))
        self.enterContext(patch("agy_provider.sessions.launch_args", return_value=[
            sys.executable, str(Path(__file__).with_name("fake_cli.py")), "echo"]))
        scenario = root / "scenario"
        log = root / "fixture.jsonl"
        self.enterContext(patch.dict(os.environ, {"AGY_SCENARIO_FILE": str(scenario), "AGY_TEST_LOG": str(log)}))
        args = dict(prompt="sample", session_id="local", func_tool=SimpleNamespace(tools=[_tool("echo")]),
                    abort_signal=asyncio.Event())
        scenario.write_text("builtin-denied")
        responses = [r async for r in provider.text_chat_stream(**args)]
        self.assertTrue(responses[0].is_chunk)
        self.assertIn("受限", responses[-1].completion_text)
        self.assertFalse(responses[-1].is_chunk)
        self.assertEqual(provider.runtime.telemetry.history[-1]["error_code"], "TOOL_PERMISSION")
        scenario.write_text("echo")
        self.assertEqual((await provider.text_chat(**args)).completion_text, "reply:1")
        scenario.write_text("partial-builtin-denied")
        with self.assertRaises(AgyError) as caught:
            await provider.text_chat(**args)
        self.assertTrue(caught.exception.no_retry and caught.exception.no_fallback)
        self.assertEqual(sum(json.loads(line)["event"] == "prompt" for line in log.read_text().splitlines()), 3)
