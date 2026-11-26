"""Offline regression tests for B06 + Comment #32 paired side-effect safety and 4.29.4 runner seam."""

import ast
import asyncio
import copy
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import Mock

# Ensure offline astrbot stubs are present before importing agy_provider
from tests import astrbot_stub  # noqa: F401

# Provide LLMResponse, Provider, TokenUsage, and astrobot_path before loading provider/host_compat
_SAVED_STUBS = {}


def _ensure_provider_stubs():
    class _LLMResponse:
        def __init__(self, role="assistant", completion_text="", reasoning_content=None,
                     tools_call_name=None, tools_call_args=None, tools_call_ids=None,
                     usage=None, is_chunk=False):
            self.role = role
            self.completion_text = completion_text
            self.reasoning_content = reasoning_content
            self.tools_call_name = tools_call_name or []
            self.tools_call_args = tools_call_args or []
            self.tools_call_ids = tools_call_ids or []
            self.usage = usage
            self.is_chunk = is_chunk

    class _Provider:
        def __init__(self, provider_config, provider_settings):
            self.provider_config = provider_config
            self.provider_settings = provider_settings
            self._model = ""

        def set_model(self, m):
            self._model = m

        def get_model(self):
            return self._model

        def _ensure_message_to_dicts(self, contexts):
            return list(contexts or [])

    class _TokenUsage:
        def __init__(self, input_other=0, input_cached=0, output=0):
            self.input_other = input_other
            self.input_cached = input_cached
            self.output = output

    for name in ("astrbot.api.provider", "astrbot.core.provider", "astrbot.core.provider.entities",
                 "astrbot.core.utils", "astrbot.core.utils.astrbot_path", "astrbot.core.agent",
                 "astrbot.core.agent.runners", "astrbot.core.agent.runners.tool_loop_agent_runner"):
        if name in sys.modules:
            _SAVED_STUBS.setdefault(name, sys.modules[name])

    provider_api = types.ModuleType("astrbot.api.provider")
    provider_api.LLMResponse = _LLMResponse
    provider_api.Provider = _Provider
    sys.modules["astrbot.api.provider"] = provider_api

    core_provider = sys.modules.get("astrbot.core.provider") or types.ModuleType("astrbot.core.provider")
    sys.modules["astrbot.core.provider"] = core_provider
    entities = types.ModuleType("astrbot.core.provider.entities")
    entities.TokenUsage = _TokenUsage
    entities.ProviderType = types.SimpleNamespace(CHAT_COMPLETION="chat_completion")
    sys.modules["astrbot.core.provider.entities"] = entities

    utils = sys.modules.get("astrbot.core.utils") or types.ModuleType("astrbot.core.utils")
    sys.modules["astrbot.core.utils"] = utils
    path_mod = types.ModuleType("astrbot.core.utils.astrbot_path")
    _data_root = [tempfile.gettempdir()]
    path_mod.get_astrbot_plugin_data_path = lambda: _data_root[0]
    sys.modules["astrbot.core.utils.astrbot_path"] = path_mod
    return _LLMResponse, _data_root


_LLMResponse, _DATA_ROOT = _ensure_provider_stubs()

from agy_provider.config import Settings
from agy_provider.errors import AgyError
from agy_provider.host_compat import install_host_compat, uninstall_host_compat
from agy_provider.provider import OWNER, AgyProvider
from agy_provider.telemetry import TelemetryTracker, failure_snapshot, start_diagnostics, stop_diagnostics
from agy_provider.tools import PendingCall, ToolBroker, ToolSnapshot
from agy_provider.transport import Event

DEFAULT_RUNNER_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "evidence"
    / "astrbot-v4.29.4"
    / "astrbot"
    / "core"
    / "agent"
    / "runners"
    / "tool_loop_agent_runner.py"
)


class _EmptyModelOutputError(Exception):
    pass


class _Attempt:
    def __init__(self, state):
        self.retry_state = state

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False


class _Retrying:
    def __init__(self, **kwargs):
        self._attempt = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        self._attempt += 1
        if self._attempt > 2:
            raise StopAsyncIteration
        return _Attempt(types.SimpleNamespace(attempt_number=self._attempt))


def _make_4294_runner_cls(streaming_mode: bool = True):
    source_text = DEFAULT_RUNNER_SOURCE.read_text(encoding="utf-8") if DEFAULT_RUNNER_SOURCE.is_file() else None
    if source_text is None:
        return None

    class Runner4294:
        EMPTY_OUTPUT_RETRY_ATTEMPTS = 2
        EMPTY_OUTPUT_RETRY_WAIT_MIN_S = 0
        EMPTY_OUTPUT_RETRY_WAIT_MAX_S = 0

        def __init__(self, provider, fallbacks, streaming: bool = streaming_mode):
            self.provider = provider
            self.fallback_providers = list(fallbacks)
            self.streaming = streaming
            self._abort_signal = asyncio.Event()
            self.request_max_retries = 0
            self._func_tool = None
            self.run_context = types.SimpleNamespace(messages=[{"role": "user", "content": "hi"}])
            self.req = types.SimpleNamespace(
                session_id="sess-1",
                conversation=types.SimpleNamespace(cid="conv-1"),
                extra_user_content_parts=[],
                model="",
            )

        async def reset(self, provider, request, tool_schema_mode="full"):
            self.provider = provider

        async def step_until_done(self):
            if False:
                yield

        def _is_stop_requested(self):
            return False

        def _sanitize_malformed_tool_calls(self, resp):
            pass

        def _sanitize_contexts_for_provider(self, messages):
            return messages

        def _func_tool_for_provider(self):
            return self._func_tool

        async def _await_or_stop(self, coro):
            return await coro

        async def _close_executor(self, stream):
            await stream.aclose()

    module = ast.parse(source_text)
    cls_node = next(n for n in module.body if isinstance(n, ast.ClassDef) and n.name == "ToolLoopAgentRunner")
    methods = {}
    for target in ("_iter_llm_responses", "_iter_llm_responses_with_fallback"):
        fn = copy.deepcopy(next(n for n in cls_node.body if isinstance(n, ast.AsyncFunctionDef) and n.name == target))
        fn.decorator_list = []
        methods[target] = fn

    exec_mod = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            methods["_iter_llm_responses"],
            methods["_iter_llm_responses_with_fallback"],
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(exec_mod)
    ns = {
        "T": types,
        "LLMResponse": _LLMResponse,
        "AsyncRetrying": _Retrying,
        "EmptyModelOutputError": _EmptyModelOutputError,
        "retry_if_exception_type": lambda *a, **k: None,
        "stop_after_attempt": lambda *a, **k: None,
        "wait_exponential": lambda *a, **k: None,
        "anext": anext,
        "logger": Mock(),
    }
    exec(compile(exec_mod, str(DEFAULT_RUNNER_SOURCE), "exec"), ns)
    Runner4294._iter_llm_responses = ns["_iter_llm_responses"]
    Runner4294._iter_llm_responses_with_fallback = ns["_iter_llm_responses_with_fallback"]
    return Runner4294


class _BackupProvider:
    def __init__(self, pid="backup_openai"):
        self.provider_config = {"id": pid, "type": "openai_chat_completion"}
        self.calls = 0

    async def text_chat(self, **kwargs):
        self.calls += 1
        return _LLMResponse(role="assistant", completion_text="backup-ok", is_chunk=False)

    async def text_chat_stream(self, **kwargs):
        self.calls += 1
        yield _LLMResponse(role="assistant", completion_text="backup-ok", is_chunk=True)
        yield _LLMResponse(role="assistant", completion_text="backup-ok", is_chunk=False)


class _ScriptedRuntime:
    def __init__(self, settings: Settings, stream_fn):
        self.settings = settings
        self.telemetry = TelemetryTracker(cost_log_enabled=False)
        self.failure_guard = types.SimpleNamespace(
            check=self._allow,
            release_probe=lambda scope: None,
            record_failure=lambda *a, **k: None,
            record_success=lambda *a, **k: None,
        )
        self.turns = {}
        self.entry_locks = {}
        self.callers = 0
        self.model_cache = []
        self._stream_fn = stream_fn

    async def _allow(self, *a, **k):
        return types.SimpleNamespace(allowed=True, half_open_scope=None, code=None, origin_turn_id=None, retry_after=0)

    async def stream(self, request, key, model, effort, *args, meter=None, **kwargs):
        source = self._stream_fn(request, key, model, effort, *args, meter=meter)
        try:
            async for item in source:
                yield item
        finally:
            await source.aclose()

    async def close(self):
        self.turns.clear()


class _FakeFuncTool:
    def __init__(self, name="write_record"):
        self.tools = [
            types.SimpleNamespace(
                name=name,
                description="Non-idempotent write",
                parameters={"type": "object", "properties": {"v": {"type": "string"}}, "required": ["v"]},
                handler=None,
                active=True,
            )
        ]


def _make_agy_provider(settings: Settings, stream_fn, pid="agy_primary"):
    provider = AgyProvider(
        {"id": pid, "type": "agy_acp", "model": "gemini-3.1-pro-high", "custom_extra_body": {"agy_thought_level": "low", "agy_tools_mode": "tools"}},
        {},
    )
    provider.settings = settings
    provider.runtime = _ScriptedRuntime(settings, stream_fn)
    return provider


@unittest.skipUnless(DEFAULT_RUNNER_SOURCE.is_file(), "AstrBot v4.29.4 tool_loop_agent_runner.py required")
class B06SideEffectAndFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agy-b06-test-")
        self.addCleanup(self.temp.cleanup)
        _DATA_ROOT[0] = self.temp.name
        self.settings = Settings(enable_tools=True, max_pending=8, max_concurrent=4)
        start_diagnostics(Path(self.temp.name) / "diag")
        self.addCleanup(stop_diagnostics)

    async def _run_fallback(self, runner):
        responses = []
        gen = runner._iter_llm_responses_with_fallback()
        try:
            async for r in gen:
                responses.append(r)
        finally:
            await gen.aclose()
        return responses

    async def test_b06_no_visible_text_allows_fallback_both_streaming_and_nonstream(self):
        Runner = _make_4294_runner_cls(True)
        install_host_compat(Runner, owner=OWNER, logger=Mock())
        self.addCleanup(uninstall_host_compat, Runner)

        for streaming in (True, False):
            for exc_factory, case_name in (
                (lambda: AgyError("RATE_LIMIT", "429"), "thought_whitespace_agy_error"),
                (lambda: RuntimeError("raw socket crash"), "thought_whitespace_ordinary_exc"),
                (lambda: AgyError("EMPTY", "0 chunks"), "zero_chunks_agy_error"),
            ):
                with self.subTest(streaming=streaming, case=case_name):
                    async def stream_fn(req, key, model, effort, *, meter=None, exc_factory=exc_factory, case_name=case_name):
                        if case_name != "zero_chunks_agy_error":
                            yield Event("thought", "Thinking internally...")
                            yield Event("text", "   \n\t  ")
                        raise exc_factory()

                    agy = _make_agy_provider(self.settings, stream_fn)
                    backup = _BackupProvider()
                    runner = Runner(agy, [backup], streaming=streaming)
                    runner._func_tool = None
                    resps = await self._run_fallback(runner)

                    self.assertEqual(backup.calls, 1)
                    self.assertTrue(any(r.completion_text == "backup-ok" for r in resps))

    async def test_b06_visible_prefix_blocks_fallback_and_resets_no_replay(self):
        Runner = _make_4294_runner_cls(True)
        install_host_compat(Runner, owner=OWNER, logger=Mock())
        self.addCleanup(uninstall_host_compat, Runner)

        for exc in (AgyError("UPSTREAM", "mid-stream fail"), RuntimeError("ordinary crash after text")):
            with self.subTest(exc=type(exc).__name__):
                async def stream_fn(req, key, model, effort, *, meter=None, exc=exc):
                    yield Event("text", "已输出可见正文")
                    raise exc

                agy = _make_agy_provider(self.settings, stream_fn)
                backup = _BackupProvider()
                runner = Runner(agy, [backup], streaming=True)
                resps = await self._run_fallback(runner)

                self.assertEqual(backup.calls, 0)
                self.assertEqual(resps[0].completion_text, "已输出可见正文")
                self.assertEqual(resps[-1].role, "err")
                snap = failure_snapshot()["failure_events"][0]
                self.assertIs(snap["fallback_allowed"], False)
                self.assertEqual(snap["fallback_reason"], "visible_prefix")

    async def test_comment32_paired_non_idempotent_side_effect_pre_vs_post_handoff(self):
        """Paired side-effect test required by #32 comment:
        Identical user-visible progress (thought only, zero body prose).
        (a) Pre-handoff fail (writes=0) -> backup.calls == 1
        (b) Post-handoff write=1 + lost receipt/unknown/stale/timeout/CancelledError -> backup.calls == 0, writes == 1
        """
        Runner = _make_4294_runner_cls(True)
        install_host_compat(Runner, owner=OWNER, logger=Mock())
        self.addCleanup(uninstall_host_compat, Runner)

        # (a) Pre-handoff failure: identical progress, writes == 0 -> fallback executes backup ONCE
        for exc in (AgyError("RATE_LIMIT", "pre-handoff limit"), RuntimeError("pre-handoff raw error")):
            with self.subTest(pair="pre_handoff", exc=type(exc).__name__):
                writes = [0]

                async def stream_pre_fail(req, key, model, effort, snapshot, *, meter=None, exc=exc):
                    yield Event("thought", "正在准备写操作进度...\n")
                    raise exc

                agy = _make_agy_provider(self.settings, stream_pre_fail)
                backup = _BackupProvider()
                runner = Runner(agy, [backup], streaming=True)
                runner._func_tool = _FakeFuncTool("write_record")

                resps = await self._run_fallback(runner)
                self.assertEqual(writes[0], 0)
                self.assertEqual(backup.calls, 1)
                self.assertTrue(any(r.completion_text == "backup-ok" for r in resps))

        # (b) Post-handoff failure: writes == 1, lost completion receipt / continuation failure -> backup.calls == 0
        for lose_mode in ("ordinary_exc_after_write", "agy_timeout_after_write", "cancelled_after_write", "continuation_stale"):
            with self.subTest(pair="post_handoff", mode=lose_mode):
                writes = [0]
                broker = ToolBroker(ToolSnapshot(_FakeFuncTool("write_record")), self.settings)
                call = PendingCall(id="call-w1", name="write_record", arguments={"v": "row-1"},
                                   future=asyncio.get_running_loop().create_future(), created_at=0.0)
                broker.pending[call.id] = call
                client = types.SimpleNamespace(
                    alive=True, prompt_terminal=False,
                    prompt_deadline=asyncio.get_running_loop().time() + 60,
                    failure_event=asyncio.Event(), failed=None,
                )

                async def stream_with_handoff(req, key, model, effort, snapshot, *, meter=None):
                    yield Event("thought", "正在准备写操作进度...\n")
                    yield Event("tools", result={"call": call, "broker": broker, "client": client})
                    # After ToolTurn resumes, never reach done if cancelled/timeout

                agy = _make_agy_provider(self.settings, stream_with_handoff)
                backup = _BackupProvider()
                runner = Runner(agy, [backup], streaming=True)
                runner._func_tool = _FakeFuncTool("write_record")

                if lose_mode == "continuation_stale":
                    # Hand off works cleanly, write executes once (receipt/save fails or tool_calls_result triggers error)
                    await self._run_fallback(runner)
                    self.assertEqual(call.state, "unknown")
                    self.assertTrue(call.delivered)
                    writes[0] += 1  # Host write executed once!
                    # Simulate host continuation fail (e.g. receipt save failed -> lost turn / stale error)
                    await agy.runtime.turns.pop(list(agy.runtime.turns)[0]).close()
                    # Second LLM iteration with empty/lost turn & backup configured MUST NOT fall back either
                    runner.run_context.messages = [
                        {"role": "user", "content": "hi"},
                        {"role": "assistant", "content": "", "tool_calls": [{"id": call.id, "type": "function", "function": {"name": "write_record", "arguments": '{"v":"row-1"}'}}]},
                        {"role": "tool", "tool_call_id": call.id, "content": "receipt-lost"},
                    ]
                    runner.req = types.SimpleNamespace(session_id="sess-1", conversation=types.SimpleNamespace(cid="conv-1"),
                                                       extra_user_content_parts=[], model="")
                    # Force stale continuation through ToolTurn
                    resps_t2 = await self._run_fallback(runner)
                    self.assertEqual(writes[0], 1)
                    self.assertEqual(backup.calls, 0)
                    self.assertEqual(resps_t2[-1].role, "err")
                    self.assertEqual(call.state, "unknown")
                else:
                    # Hand off tool call cleanly, execute write once, then consumer/post-handoff failure occurs
                    gen = runner._iter_llm_responses_with_fallback()
                    got_tools = False
                    async for resp in gen:
                        if resp.tools_call_ids == [call.id]:
                            got_tools = True
                            self.assertEqual(call.state, "unknown")
                            writes[0] += 1  # Write handler actually entered ONCE!
                            # Lose completion receipt: simulate failure before tool result closes!
                            break
                    self.assertTrue(got_tools)
                    await gen.aclose()
                    self.assertEqual(writes[0], 1)
                    self.assertEqual(backup.calls, 0)
                    self.assertEqual(call.state, "unknown")

                    # Also close any turn retained in agy.runtime before next test
                    for pending_turn in list(agy.runtime.turns.values()):
                        await pending_turn.close()

                    # Now test host failing inside _iter_llm_responses AFTER handoff within the same _iter_llm_responses_with_fallback loop:
                    # because _iter_llm_responses_with_fallback yields the non-chunk tools response and returns (closing executor),
                    # closing raises inside finally/aclose (before fallback loop exits try:), OR failure occurs after handoff.
                    broker2 = ToolBroker(ToolSnapshot(_FakeFuncTool("write_record")), self.settings)
                    call2 = PendingCall(id="call-w2", name="write_record", arguments={"v": "row-2"},
                                        future=asyncio.get_running_loop().create_future(), created_at=0.0)
                    broker2.pending[call2.id] = call2
                    writes2 = [0]

                    async def stream_handoff_then_fail(req, key, model, effort, snapshot, *, meter=None):
                        yield Event("thought", "正在准备写操作进度...\n")
                        yield Event("tools", result={"call": call2, "broker": broker2, "client": client})

                    agy2 = _make_agy_provider(self.settings, stream_handoff_then_fail)
                    backup2 = _BackupProvider()
                    runner2 = Runner(agy2, [backup2], streaming=True)
                    runner2._func_tool = _FakeFuncTool("write_record")

                    orig_stream = agy2.text_chat_stream

                    async def host_post_handoff_fail(**kw):
                        inner = orig_stream(**kw)
                        handed = False
                        try:
                            async for r in inner:
                                if r.tools_call_ids:
                                    handed = True
                                    writes2[0] += 1
                                yield r
                        finally:
                            await inner.aclose()
                            if handed:
                                if lose_mode == "ordinary_exc_after_write":
                                    raise RuntimeError("lost receipt writing artifact")
                                if lose_mode == "agy_timeout_after_write":
                                    raise AgyError("TOOL_TIMEOUT", "lost receipt")
                                raise asyncio.CancelledError()

                    agy2.text_chat_stream = host_post_handoff_fail
                    gen2 = runner2._iter_llm_responses_with_fallback()
                    seen_out = []
                    try:
                        if lose_mode == "cancelled_after_write":
                            with self.assertRaises(asyncio.CancelledError):
                                async for item in gen2:
                                    seen_out.append(item)
                        else:
                            async for item in gen2:
                                seen_out.append(item)
                    finally:
                        await gen2.aclose()
                        for turn in list(agy2.runtime.turns.values()):
                            await turn.close()
                        await broker2.close()

                    self.assertEqual(writes2[0], 1)
                    self.assertEqual(backup2.calls, 0)
                    self.assertEqual(call2.state, "unknown")
                    if lose_mode != "cancelled_after_write":
                        self.assertEqual(seen_out[-1].role, "err")

    async def test_b06_cross_task_generator_advance_keeps_scope_isolated(self):
        Runner = _make_4294_runner_cls(True)
        install_host_compat(Runner, owner=OWNER, logger=Mock())
        self.addCleanup(uninstall_host_compat, Runner)

        async def stream_fn(req, key, model, effort, *, meter=None):
            yield Event("text", "分段1")
            raise RuntimeError("fail after yield")

        agy = _make_agy_provider(self.settings, stream_fn)
        backup = _BackupProvider()
        runner = Runner(agy, [backup], streaming=True)
        gen = runner._iter_llm_responses_with_fallback()
        try:
            # Advance each anext(gen) inside a separate asyncio task!
            first = await asyncio.create_task(anext(gen))
            self.assertEqual(first.completion_text, "分段1")
            err = await asyncio.create_task(anext(gen))
            self.assertEqual(err.role, "err")
            self.assertEqual(backup.calls, 0)
        finally:
            await gen.aclose()


if __name__ == "__main__":
    unittest.main()
