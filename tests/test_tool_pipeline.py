import asyncio
import copy
import importlib
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from tests import astrbot_stub  # noqa: F401
from tests.test_host_replay import Response, runner_type
from tests.test_tools_mode import _load_provider_module
from agy_provider.config import Settings
from agy_provider.errors import AgyError
from agy_provider.host_compat import install_host_compat, uninstall_host_compat
from agy_provider.messages import ConversationInput, normalize
from agy_provider.process import LaunchInfo
from agy_provider.sessions import Runtime, decide_reuse
from agy_provider.tools import ToolSnapshot
from agy_provider.tool_turn import ToolTurn
from agy_provider.transport import PermissionDenial


class ToolPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mcp-pipeline-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.settings = Settings(auth_bridge=False, enable_tools=True, request_timeout=5,
                                 tool_approval_timeout=2, tool_execution_timeout=2)
        self.snapshot = ToolSnapshot(SimpleNamespace(tools=[SimpleNamespace(
            name="echo", active=True, description="echo", parameters={
                "type": "object", "properties": {"value": {"type": "string"}}})]))
        self.enterContext(patch("agy_provider.sessions.discover", AsyncMock(return_value=LaunchInfo("fake", "1.5.9", False))))
        self.enterContext(patch("agy_provider.sessions.launch_args", return_value=[sys.executable, str(Path(__file__).with_name("fake_tool_cli.py"))]))

    async def max_steps_runner(self, *, builtins=False):
        stubs = _load_provider_module(self.root)
        stubs["astrbot.core.provider.entities"].LLMResponse = Response
        self.enterContext(patch.dict(sys.modules, stubs))
        sys.modules.pop("agy_provider.provider", None)
        self.addCleanup(sys.modules.pop, "agy_provider.provider", None)
        module = importlib.import_module("agy_provider.provider")
        module.configure(replace(self.settings, builtin_search_web="allow" if builtins else "deny"))
        self.addCleanup(module.configure, Settings())
        provider = module.AgyProvider({"id": "p", "model": "gemini-test"}, {})
        self.addAsyncCleanup(provider.terminate)

        def launch(info, home, *, use_default_agent, customizations_mode):
            fixtures = Path(__file__).parent
            if use_default_agent:
                return [sys.executable, str(fixtures / "fake_tool_cli.py")]
            return [sys.executable, str(fixtures / "fake_cli.py"), "echo"]

        log = self.root / "cli.jsonl"
        self.enterContext(patch.dict(os.environ, {"AGY_TEST_LOG": str(log)}))
        launches = self.enterContext(patch("agy_provider.sessions.launch_args", side_effect=launch))

        class Runner(runner_type()):
            MAX_STEPS_REACHED_PROMPT = "Step budget exhausted. Summarize the results."

            async def _iter_llm_responses(self, **kwargs):
                if self.provider is not provider:
                    self.provider.calls += 1
                    yield Response(role="assistant", completion_text="fallback")
                    return
                async for response in provider.text_chat_stream(
                    contexts=self.run_context.messages,
                    session_id="max-steps",
                    func_tool=self.req.func_tool,
                    abort_signal=self._abort_signal,
                ):
                    yield response

        install_host_compat(Runner, owner=module.OWNER, logger=Mock())
        self.addCleanup(uninstall_host_compat, Runner)
        runner = Runner()
        toolset = SimpleNamespace(tools=[SimpleNamespace(
            name="echo", active=True, description="echo",
            parameters={"type": "object", "properties": {"value": {"type": "string"}}},
        )])
        runner.req = SimpleNamespace(func_tool=toolset)
        runner.provider = provider
        fallback = SimpleNamespace(calls=0)
        runner.fallback_providers = [fallback]
        runner._abort_signal = asyncio.Event()
        runner._step_budget_max = runner._step_budget_used = 12
        runner.run_context = SimpleNamespace(messages=[{"role": "user", "content": "echo"}])
        initial = await self.run_step(runner)
        call = initial[-1]
        runner.run_context.messages.extend(self.exchange(
            call.tools_call_ids[0], call.tools_call_args[0], "completed tool result",
        ))
        runner.req.func_tool = None
        runner._step_budget_used += 1
        runner.run_context.messages.append({
            "role": "user", "content": runner.MAX_STEPS_REACHED_PROMPT,
        })
        return runner, provider, fallback, launches, log

    @staticmethod
    async def run_step(runner):
        return [response async for response in runner._iter_llm_responses_with_fallback()]

    @staticmethod
    def exchange(call_id, arguments, result):
        return [
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": call_id, "function": {"name": "echo", "arguments": arguments},
            }]},
            {"role": "tool", "tool_call_id": call_id, "content": result},
        ]

    @staticmethod
    def prompts(log):
        events = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
        return [event for event in events if event["event"] == "prompt"]

    async def test_max_steps_retires_pending_tool_prompt_and_summarizes_without_tools(self):
        runner, provider, fallback, launches, log = await self.max_steps_runner(builtins=True)
        old_turn = next(iter(provider.runtime.turns.values()))
        call = old_turn.waiting["call"]
        summary = await self.run_step(runner)
        self.assertEqual(summary[-1].completion_text, "reply:1")
        self.assertFalse(getattr(summary[-1], "tools_call_ids", None))
        self.assertEqual(fallback.calls, 0)
        self.assertFalse(provider.runtime.turns)
        self.assertTrue(old_turn.finished)
        self.assertEqual(provider.runtime.tool_outcomes[call.id], "unknown")
        self.assertEqual([c.kwargs["use_default_agent"] for c in launches.call_args_list], [True, False])
        self.assertIsNone(next(iter(provider.runtime.sessions.values())).broker)
        prompts = self.prompts(log)
        self.assertEqual(len(prompts), 1)
        self.assertIn("completed tool result", "".join(prompts[0]["texts"]))

    async def test_max_steps_late_tool_result_rebuilds_without_fallback_or_tools(self):
        runner, provider, fallback, launches, log = await self.max_steps_runner()
        # Exercise the no-retained-turn branch independently of the first fix.
        await next(iter(provider.runtime.turns.values())).close()
        first = await self.run_step(runner)
        self.assertEqual(first[-1].completion_text, "reply:1")
        runner.run_context.messages.extend(self.exchange("late-result", {}, "late tool result"))

        signal = runner._abort_signal
        runner._abort_signal = asyncio.Event()
        foreign = await self.run_step(runner)
        self.assertIn("[TOOL_STALE]", foreign[-1].completion_text)
        runner._abort_signal = signal

        summary = await self.run_step(runner)
        self.assertEqual(summary[-1].completion_text, "reply:1")
        self.assertFalse(getattr(summary[-1], "tools_call_ids", None))
        repeated = await self.run_step(runner)
        self.assertIn("[TOOL_STALE]", repeated[-1].completion_text)
        self.assertEqual(fallback.calls, 0)
        self.assertFalse(provider.runtime.turns)
        self.assertEqual([c.kwargs["use_default_agent"] for c in launches.call_args_list], [True, False, False])
        self.assertIsNone(next(iter(provider.runtime.sessions.values())).broker)
        prompts = self.prompts(log)
        self.assertEqual(len(prompts), 2)
        self.assertIn("late tool result", "".join(prompts[-1]["texts"]))

    async def test_max_steps_rejects_results_without_a_matching_live_summary(self):
        runner, provider, fallback, launches, log = await self.max_steps_runner()
        old = next(iter(provider.runtime.turns.values()))
        forced_history = list(runner.run_context.messages)
        runner.run_context.messages.pop()
        pending = await self.run_step(runner)
        self.assertIn("[TOOL_STALE]", pending[-1].completion_text)
        self.assertFalse(old.finished)
        await old.close()
        stale = await self.run_step(runner)
        self.assertIn("[TOOL_STALE]", stale[-1].completion_text)

        runner.run_context.messages = forced_history
        first = await self.run_step(runner)
        self.assertEqual(first[-1].completion_text, "reply:1")
        runner.run_context.messages.extend(self.exchange("late-result", {}, "late tool result"))
        runner.run_context.messages[0] = {"role": "user", "content": "changed question"}
        rewritten = await self.run_step(runner)
        self.assertIn("[TOOL_STALE]", rewritten[-1].completion_text)
        runner.run_context.messages[0] = {"role": "user", "content": "echo"}
        await next(iter(provider.runtime.sessions.values())).close()
        expired = await self.run_step(runner)
        self.assertIn("[TOOL_STALE]", expired[-1].completion_text)
        self.assertEqual(fallback.calls, 0)
        self.assertEqual(launches.call_count, 2)
        self.assertEqual(len(self.prompts(log)), 1)

    async def test_max_steps_generation_failure_after_tool_results_does_not_replay(self):
        runner, provider, fallback, launches, log = await self.max_steps_runner()
        first = await self.run_step(runner)
        self.assertEqual(first[-1].completion_text, "reply:1")
        runner.run_context.messages.extend(self.exchange("late-result", {}, "late tool result"))
        scenario = self.root / "scenario"
        scenario.write_text("empty", encoding="utf-8")
        with patch.dict(os.environ, {"AGY_SCENARIO_FILE": str(scenario)}):
            failed = await self.run_step(runner)
        self.assertEqual(failed[-1].role, "err")
        self.assertIn("[EMPTY]", failed[-1].completion_text)
        self.assertEqual(fallback.calls, 0)
        self.assertEqual(launches.call_count, 3)
        self.assertEqual(len(self.prompts(log)), 2)
        self.assertFalse(provider.runtime.turns)

    async def test_max_steps_failure_after_trimmed_tool_history_does_not_replay(self):
        runner, provider, fallback, launches, log = await self.max_steps_runner()
        # The prior handoff still blocks replay when host compaction omits it.
        del runner.run_context.messages[1:-1]
        scenario = self.root / "scenario"
        scenario.write_text("empty", encoding="utf-8")
        with patch.dict(os.environ, {"AGY_SCENARIO_FILE": str(scenario)}):
            failed = await self.run_step(runner)
        self.assertEqual(failed[-1].role, "err")
        self.assertIn("[EMPTY]", failed[-1].completion_text)
        self.assertEqual(fallback.calls, 0)
        self.assertEqual(launches.call_count, 2)
        self.assertEqual(len(self.prompts(log)), 1)
        self.assertFalse(provider.runtime.turns)

    def turn(self, approver=None, *, request=None, settings=None):
        runtime = Runtime(settings or self.settings, self.root)
        self.addAsyncCleanup(runtime.close)
        if request is None:
            request = ConversationInput(system="", messages=[{"role": "user", "content": "echo"}])
        meter = runtime.telemetry.start_turn(provider="p", session_key_raw="id", mode="tools", model="gemini-test", effort="default")
        signal = asyncio.Event()
        turn = ToolTurn(runtime, request, "id", "gemini-test", "default", self.snapshot, signal,
                        approver=approver, meter=meter)
        self.addAsyncCleanup(turn.close)
        return runtime, turn, request, signal

    async def test_tool_exchange_preserves_the_persisted_user_hash(self):
        settings = replace(self.settings, context_compaction_min_peak=200000)
        request = normalize(
            [{"role": "user", "content": [
                {"type": "text", "text": "echo"},
                {"type": "text", "text": "temporary", "_no_save": True},
            ]}],
            None, None, None, settings.history_bytes, tools=True,
        )
        runtime, turn, _, signal = self.turn(request=request, settings=settings)
        async with asyncio.timeout(5):
            events = [event async for event in turn.events()]
            call = next(event.result["call"] for event in events if event.kind == "tools")
            exchange = [
                {"role": "assistant", "content": "", "tool_calls": [{
                    "id": call.id, "type": "function",
                    "function": {"name": call.name, "arguments": call.arguments},
                }]},
                {"role": "tool", "tool_call_id": call.id, "content": "echo result"},
            ]
            continuation = normalize(
                [*request.messages, *exchange], None, None, None, settings.history_bytes,
                tools=True, continuation=True,
            )
            turn.accept(continuation, "gemini-test", "default", self.snapshot, signal, None)
            final = [event async for event in turn.events()]
        self.assertEqual(final[-1].text, "echo result")

        replay = normalize(
            [
                {"role": "user", "content": "echo"},
                *exchange,
                {"role": "assistant", "content": final[-1].text},
                {"role": "user", "content": "next"},
            ],
            None, None, None, settings.history_bytes, tools=True,
        )
        session = runtime.sessions["id"]
        decision = decide_reuse(session, replay, "gemini-test", "default", self.snapshot)
        self.assertTrue(decision.reuse)
        self.assertEqual(decision.history_relation, "exact")
        self.assertEqual(session.sent_window.hashes[0], request.hashes[0])
        self.assertNotEqual(session.host_expected[0], request.hashes[0])
        self.assertEqual(session.sent_window.hashes[1:], session.host_expected[1:])

    async def test_real_relay_handoff_approval_result_compaction_and_permission_denial(self):
        approver = AsyncMock(return_value=True)
        runtime, turn, request, signal = self.turn(approver)
        async with asyncio.timeout(5):
            events = [event async for event in turn.events()]
            tool = next(event for event in events if event.kind == "tools")
            call = tool.result["call"]
            client = tool.result["client"]
            self.assertTrue(client.context_usage.suspected_compaction)
            self.assertTrue(client.alive, "Must not retire before host side effect/result")
            self.assertEqual(client.permission_errors, [PermissionDenial(
                "session/request_permission", "run_command", "native-call-1"
            )])
            approver.assert_awaited_once_with("echo", {"value": "中文 🦊"}, call.id)
            continuation = ConversationInput(system="", messages=copy.deepcopy(request.messages) + [
                {"role": "assistant", "content": "", "tool_calls": [{"id": call.id, "type": "function", "function": {
                    "name": "echo", "arguments": '{"value":"中文 🦊"}'}}]},
                {"role": "tool", "tool_call_id": call.id, "content": "宿主执行一次 🦊"}])
            # Constructor does not normalize the wire argument representation.
            from agy_provider.messages import canonical_calls
            continuation.messages[-2]["tool_calls"] = canonical_calls(continuation.messages[-2]["tool_calls"])
            turn.accept(continuation, "gemini-test", "default", self.snapshot, signal, approver)
            final = [event async for event in turn.events()]
        self.assertEqual(final[-1].text, "宿主执行一次 🦊")
        self.assertEqual(len(runtime.telemetry.history), 1)
        self.assertEqual(runtime.telemetry.history[-1]["tool_calls"], 1)
        self.assertTrue(runtime.telemetry.history[-1]["upstream_compaction_detected"])
        self.assertNotIn("id", runtime.sessions)
        self.assertFalse(client.alive)

    async def test_rejected_approval_never_hands_tool_to_executor(self):
        approver = AsyncMock(return_value=False)
        runtime, turn, _, _ = self.turn(approver)
        async with asyncio.timeout(5):
            events = [event async for event in turn.events()]
        self.assertFalse(any(event.kind == "tools" for event in events))
        self.assertEqual(events[-1].text, "TOOL_APPROVAL_DENIED")
        self.assertEqual(approver.await_count, 1)

    async def test_cancel_after_handoff_records_unknown_and_cleans_process(self):
        runtime, turn, _, signal = self.turn()
        async with asyncio.timeout(5):
            events = [event async for event in turn.events()]
            client = events[-1].result["client"]
            broker = events[-1].result["broker"]
            call = events[-1].result["call"]
            signal.set()
            await turn.task
        self.assertFalse(client.alive)
        self.assertEqual(broker.audit[call.id], "unknown")
        self.assertFalse(broker.tasks)

    async def test_provider_marks_partial_output_failure_non_replayable(self):
        with patch.dict(sys.modules, _load_provider_module(self.root)):
            sys.modules.pop("agy_provider.provider", None)
            provider_module = importlib.import_module("agy_provider.provider")
            provider_module.configure(Settings(auth_bridge=False))
            provider = provider_module.AgyProvider({"id": "p", "model": "gemini-test"}, {"auth_bridge": False})
            try:
                with patch("agy_provider.sessions.launch_args", return_value=[sys.executable, str(Path(__file__).with_name("fake_cli.py")), "partial-fatal"]):
                    chunks = []
                    with self.assertRaises(AgyError) as caught:
                        async for response in provider.text_chat_stream(prompt="hi", session_id="p"):
                            chunks.append(response)
                    self.assertTrue(caught.exception.no_fallback and caught.exception.no_retry)
                    self.assertEqual(caught.exception.code, "QUOTA")
                    self.assertTrue(chunks)
            finally:
                await provider.terminate()
                sys.modules.pop("agy_provider.provider", None)

    async def test_broker_close_does_not_deadlock_with_long_execution_timeout(self):
        # 复现 Python 3.12+ Server.wait_closed() 在活跃连接未取消时的死锁风险
        long_settings = Settings(
            auth_bridge=False,
            enable_tools=True,
            request_timeout=30,
            tool_approval_timeout=30,
            tool_execution_timeout=60,
        )
        runtime = Runtime(long_settings, self.root / "long-close")
        self.addAsyncCleanup(runtime.close)
        request = ConversationInput(system="", messages=[{"role": "user", "content": "echo"}])
        signal = asyncio.Event()
        turn = ToolTurn(runtime, request, "id", "gemini-test", "default", self.snapshot, signal)
        self.addAsyncCleanup(turn.close)
        events = [event async for event in turn.events()]
        call = events[-1].result["call"]
        broker = events[-1].result["broker"]
        client = events[-1].result["client"]
        # 必须在 1.5s 内干净关闭，而不是卡满 60s tool_execution_timeout
        async with asyncio.timeout(1.5):
            await turn.close()
        self.assertFalse(client.alive)
        self.assertEqual(broker.audit[call.id], "unknown")

    async def test_concurrent_same_session_requests_do_not_kill_active_tool_turn(self):
        toolset = SimpleNamespace(tools=[SimpleNamespace(
            name="echo", active=True, description="echo",
            parameters={"type": "object", "properties": {"value": {"type": "string"}}},
        )])

        class FakeToolResult:
            def __init__(self, call_id, args_json, content):
                self._msgs = [
                    {
                        "role": "assistant",
                        "content": "",
                        "tool_calls": [{
                            "id": call_id,
                            "type": "function",
                            "function": {"name": "echo", "arguments": args_json},
                        }],
                    },
                    {"role": "tool", "tool_call_id": call_id, "content": content},
                ]

            def to_openai_messages(self):
                return list(self._msgs)

        with patch.dict(sys.modules, _load_provider_module(self.root)):
            sys.modules.pop("agy_provider.provider", None)
            pm = importlib.import_module("agy_provider.provider")
            pm.configure(Settings(
                auth_bridge=False,
                enable_tools=True,
                queue_timeout=1,
                request_timeout=10,
                tool_approval_timeout=5,
                tool_execution_timeout=5,
            ))
            provider = pm.AgyProvider({"id": "p", "model": "gemini-test"}, {"auth_bridge": False})
            try:
                sig1 = asyncio.Event()
                out1 = [
                    r async for r in provider.text_chat_stream(
                        prompt="echo", session_id="shared-group", func_tool=toolset, abort_signal=sig1
                    )
                ]
                call_id = out1[-1].tools_call_ids[0]
                self.assertEqual(len(provider.runtime.turns), 1)
                active_turn = next(iter(provider.runtime.turns.values()))

                # 1) 同会话外部请求预检失败（如不支持的音频），不得关闭或污染 Runner 1 的工具轮
                sig_bad = asyncio.Event()
                with self.assertRaises(AgyError) as bad_exc:
                    async for _ in provider.text_chat_stream(
                        prompt="hi", audio_urls=["a.mp3"], session_id="shared-group", abort_signal=sig_bad
                    ):
                        pass
                self.assertEqual(bad_exc.exception.code, "UNSUPPORTED")
                self.assertFalse(active_turn.finished)
                self.assertFalse(active_turn.meter.finished)
                self.assertEqual(len(provider.runtime.turns), 1)

                # 2) 同会话外部新消息等待超时（queue_timeout=1s），仅外部请求报 BUSY，原工具轮仍存活
                sig2 = asyncio.Event()
                with self.assertRaises(AgyError) as busy_exc:
                    async for _ in provider.text_chat_stream(
                        prompt="并发打断", session_id="shared-group", func_tool=toolset, abort_signal=sig2
                    ):
                        pass
                self.assertEqual(busy_exc.exception.code, "BUSY")
                self.assertFalse(active_turn.finished)
                self.assertEqual(len(provider.runtime.turns), 1)

                # 3) Runner 1 随后回填工具结果，并验证排队等待的 Runner 3 能接力完成
                pm.configure(Settings(
                    auth_bridge=False,
                    enable_tools=True,
                    queue_timeout=5,
                    request_timeout=10,
                    tool_approval_timeout=5,
                    tool_execution_timeout=5,
                ))
                provider.settings = pm._settings

                async def queued_chat():
                    # 纯聊天接力请求（tool_choice="none"）等待工具轮释放后完成
                    with patch(
                        "agy_provider.sessions.launch_args",
                        return_value=[sys.executable, str(Path(__file__).with_name("fake_cli.py")), "generate"],
                    ):
                        res = await provider.text_chat(
                            prompt="后续消息",
                            session_id="shared-group",
                            tool_choice="none",
                            abort_signal=asyncio.Event(),
                        )
                        return res.completion_text

                queued_task = asyncio.create_task(queued_chat())
                await asyncio.sleep(0.05)
                cont_res = await provider.text_chat(
                    contexts=[{"role": "user", "content": "echo"}],
                    tool_calls_result=FakeToolResult(call_id, '{"value":"中文 🦊"}', "宿主执行一次 🦊"),
                    session_id="shared-group",
                    func_tool=toolset,
                    abort_signal=sig1,
                )
                self.assertEqual(cont_res.completion_text, "宿主执行一次 🦊")
                self.assertEqual(await asyncio.wait_for(queued_task, 5), "fake answer")
            finally:
                await provider.terminate()
                sys.modules.pop("agy_provider.provider", None)
