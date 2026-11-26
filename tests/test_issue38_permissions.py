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

from agy_provider.builtin_tools import BuiltinDenied, read_target, supports_read
from agy_provider.errors import AgyError
from agy_provider.config import Settings
from agy_provider.process import make_home
from agy_provider.tools import ToolBroker, ToolSnapshot
from agy_provider.transport import AcpClient
from tests.test_tools_mode import _load_provider_module, _tool


@unittest.skipUnless(sys.platform == "linux", "Scoped builtin reads are verified only on Linux")
class ReadPermissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.workspace = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.file = self.workspace / "sample_read.txt"
        self.file.write_text("test")
        self.file.chmod(0o600)
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

    def test_make_home_gives_read_target_a_canonical_workspace_under_aliased_root(self):
        data = self.workspace / "data"
        data.mkdir()
        alias = self.workspace / "alias"
        alias.symlink_to(data, target_is_directory=True)
        workspace = make_home(alias, "", tools_mode=True, read_allowed=True) / "workspace"
        self.assertEqual(workspace, workspace.resolve(strict=True))
        self.assertIn("request read_file", (workspace / "AGENTS.md").read_text())
        sample = workspace / "sample.txt"
        sample.write_text("test")
        sample.chmod(0o600)
        args = {"Path": str(sample)}
        call = {"kind": "read", "args": args, "rawInput": args, "locations": [{"path": str(sample)}]}
        self.assertEqual(read_target(call, workspace), str(sample))
        self.assertIsNone(read_target(call, alias / workspace.parent.name / "workspace"))

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
        for name in ("search_web", "run_command", "edit_file", "write_file", "browser",
                     "execute_url", "read_url", "schedule", "invoke_subagent"):
            with self.assertRaises(BuiltinDenied):
                self.broker.observe({"toolCallId": "x", "name": name})
        self.assertTrue(supports_read("1.5.18"))
        self.assertTrue(supports_read("agy 1.5.17"))
        self.assertFalse(supports_read("1.5.16"))
        self.assertFalse(supports_read("1.5.19"))
        self.assertEqual(self.broker.count, 0)


class SearchPermissionTests(unittest.IsolatedAsyncioTestCase):
    def make_broker(self, **changes):
        config = {"enable_tools": True, "builtin_search_web": "allow", "tool_max_calls": 1, **changes}
        broker = ToolBroker(ToolSnapshot(SimpleNamespace(tools=[_tool("echo")])), Settings(**config))
        broker.turn_active = True
        return broker

    def search(self, ident="search-1", **changes):
        args = {"query": "synthetic search"}
        return {"toolCallId": ident, "sessionUpdate": "tool_call", "name": "search_web",
                "kind": "search", "status": "in_progress", "rawInput": args, "args": args, **changes}

    async def test_search_requires_opt_in_and_only_recognizes_exact_builtin(self):
        for broker in (self.make_broker(builtin_search_web="deny"), self.make_broker(enable_tools=False)):
            with self.assertRaises(BuiltinDenied):
                broker.observe(self.search())
            self.assertEqual(broker.count, 0)
        broker = self.make_broker()
        for changes in ({"name": "browser"}, {"name": "read_url"}, {"name": "execute_url"},
                        {"name": "write_file"}, {"name": "run_command"}, {"name": "read_file"},
                        {"kind": "other"}, {"status": "pending"}, {"rawInput": {"query": []}}):
            with self.assertRaises(BuiltinDenied):
                broker.observe(self.search(**changes))
        self.assertEqual(broker.count, 0)
        with self.assertRaisesRegex(AgyError, "CONFIG"):
            Settings.from_dict({"builtin_search_web": True})

    async def test_search_updates_count_once_and_never_get_permission(self):
        broker = self.make_broker()
        client = AcpClient(broker.settings)
        client.tool_broker = broker
        client.session_id = broker.session_id = "session"
        client.active = True
        client.prompt_deadline = asyncio.get_running_loop().time() + 10
        client._write = AsyncMock()
        call = self.search()
        client._on_update({"sessionId": "other", "update": call})
        self.assertEqual(broker.count, 0)
        client._on_update({"sessionId": "session", "update": call})
        await client._reject_request({"id": 1, "method": "session/request_permission", "params": {
            "sessionId": "session", "toolCall": call,
            "options": [{"kind": "allow_once", "optionId": "allow"}],
        }})
        self.assertEqual(client._write.call_args.args[0]["result"], {"outcome": {"outcome": "cancelled"}})
        complete = {"toolCallId": "search-1", "sessionUpdate": "tool_call_update", "status": "completed"}
        client._on_update({"sessionId": "session", "update": complete})
        self.assertEqual(broker.count, 1)
        with self.assertRaises(BuiltinDenied):
            broker.observe(complete)
        broker.search_calls.clear()
        broker.count = 0
        with self.assertRaises(BuiltinDenied):
            broker.observe(call)

    async def test_search_update_cannot_change_its_arguments(self):
        broker = self.make_broker(tool_max_calls=4)
        broker.observe(self.search())
        update = {"toolCallId": "search-1", "sessionUpdate": "tool_call_update", "status": "in_progress",
                  "rawInput": {"query": "synthetic search"}, "args": {"query": "synthetic search"}}
        broker.observe(update)
        for key in ("rawInput", "args"):
            with self.subTest(key), self.assertRaises(BuiltinDenied) as caught:
                broker.observe({**update, key: {"query": "other"}})
            self.assertIn("搜索请求可能已经发出", str(caught.exception))

    async def test_tools_disabled_search_notice_admits_the_search_may_already_have_run(self):
        for broker in (self.make_broker(builtin_search_web="deny"), self.make_broker(tool_max_calls=0)):
            with self.assertRaises(BuiltinDenied) as caught:
                broker.observe(self.search())
            self.assertIn("搜索请求可能已经发出", caught.exception.user_notice)
        with self.assertRaises(BuiltinDenied) as caught:
            self.make_broker(builtin_read_file="allow_once").observe(
                {"toolCallId": "read-1", "sessionUpdate": "tool_call", "name": "read_file"}
            )
        self.assertIsNone(caught.exception.user_notice)

    async def test_search_and_mcp_share_observed_budget_in_both_orders(self):
        mcp = {"toolCallId": "echo-1", "sessionUpdate": "tool_call", "name": "mcp_astrbot_echo"}
        broker = self.make_broker()
        broker.observe(mcp)
        with self.assertRaisesRegex(BuiltinDenied, "TOOL_BUDGET"):
            broker.observe(self.search())
        self.assertEqual(broker.count, 1)
        broker = self.make_broker()
        broker.observe(self.search())
        with self.assertRaisesRegex(AgyError, "TOOL_BUDGET"):
            broker.observe(mcp)
        with self.assertRaisesRegex(BuiltinDenied, "TOOL_BUDGET"):
            broker.observe(self.search("search-2"))
        self.assertEqual(broker.count, 2)

    def test_search_switch_changes_only_tool_mode_guardrails(self):
        from agy_provider.process import _guardrails

        self.assertIn("web search or browser", _guardrails(True))
        enabled = _guardrails(True, search_allowed=True)
        self.assertIn("may use the built-in search_web", enabled)
        self.assertIn("Never use built-in shell, write or browser", enabled)
        self.assertIn("Do not use read_url or execute_url", enabled)
        self.assertIn("Do not use built-in file tools", enabled)
        self.assertEqual(_guardrails(False, search_allowed=True), _guardrails(False))


class DenialDeliveryTests(unittest.IsolatedAsyncioTestCase):
    def launch_provider(self, **settings):
        import importlib
        from agy_provider.process import LaunchInfo

        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        self.enterContext(patch.dict(sys.modules, _load_provider_module(root)))
        sys.modules.pop("agy_provider.provider", None)
        mod = importlib.import_module("agy_provider.provider")
        self.addCleanup(sys.modules.pop, "agy_provider.provider", None)
        mod.configure(Settings(enable_tools=True, auth_bridge=False, **settings))
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
        return provider, scenario, log, args

    async def test_provider_finishes_denial_without_replay_then_accepts_next_message(self):
        provider, scenario, log, args = self.launch_provider()
        scenario.write_text("builtin-denied")
        responses = [r async for r in provider.text_chat_stream(**args)]
        self.assertTrue(responses[0].is_chunk)
        # Post-observation abort: the notice must admit the search may already have run.
        self.assertIn("搜索请求可能已经发出", responses[-1].completion_text)
        self.assertNotIn("受限", responses[-1].completion_text)
        self.assertFalse(responses[-1].is_chunk)
        self.assertEqual(provider.runtime.telemetry.history[-1]["error_code"], "TOOL_PERMISSION")
        scenario.write_text("echo")
        self.assertEqual((await provider.text_chat(**args)).completion_text, "reply:1")
        scenario.write_text("partial-builtin-denied")
        with self.assertRaises(AgyError) as caught:
            await provider.text_chat(**args)
        self.assertTrue(caught.exception.no_retry and caught.exception.no_fallback)
        self.assertEqual(sum(json.loads(line)["event"] == "prompt" for line in log.read_text().splitlines()), 3)

    async def test_provider_charges_observed_search_and_aborts_without_replay(self):
        provider, scenario, log, args = self.launch_provider(builtin_search_web="allow", tool_max_calls=1)
        scenario.write_text("builtin-search")
        response = await provider.text_chat(**args)
        self.assertEqual(response.completion_text, "fake answer")
        self.assertEqual(provider.runtime.telemetry.history[-1]["tool_calls"], 1)

        scenario.write_text("builtin-search-over-budget")
        with self.assertRaisesRegex(AgyError, "TOOL_BUDGET") as caught:
            await provider.text_chat(**args)
        self.assertTrue(caught.exception.no_retry and caught.exception.no_fallback)
        events = [json.loads(line)["event"] for line in log.read_text().splitlines()]
        self.assertEqual(events.count("prompt"), 2)
        self.assertEqual(provider.runtime.telemetry.history[-1]["tool_calls"], 2)
