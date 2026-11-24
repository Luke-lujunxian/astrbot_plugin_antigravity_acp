"""Offline regression tests for B09 (bounded private failure journal) and B10 (zero-generation read-only routes)."""

import asyncio
import copy
import json
import os
import stat
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from tests import astrbot_stub  # noqa: F401 -- install offline AstrBot stubs

from agy_provider import models as models_module  # noqa: F401
from agy_provider import onboarding as onboarding_module
from agy_provider import probe as probe_module  # noqa: F401
from agy_provider import process as process_module  # noqa: F401
from agy_provider import telemetry as telemetry_module
from agy_provider.config import Settings
from agy_provider.errors import AgyError
from agy_provider.failure_events import FailureJournal, MAX_BYTES, MAX_EVENTS, TTL
from agy_provider.monitoring import Monitoring
from agy_provider.onboarding import Onboarding
from agy_provider.telemetry import (
    MONITOR_ERROR_CODES,
    TelemetryTracker,
    failure_snapshot,
    last_service_observation,
    provider_tag,
    start_diagnostics,
    stop_diagnostics,
)


class _FakeConfig(dict):
    def __init__(self, manager):
        super().__init__(
            provider=[],
            provider_sources=[],
            dashboard={"username": "admin"},
            agent_runner={
                "runner_type": "local",
                "config": {"model": {"provider_id": "acp-1", "fallback_provider_ids": []}},
            },
        )
        self._manager = manager

    def save_config(self):
        self._manager.saved = copy.deepcopy(dict(self))


class _FakeManager:
    def __init__(self):
        self.reload_lock = asyncio.Lock()
        self.resource_lock = asyncio.Lock()
        default_conf = _FakeConfig(self)
        self.acm = types.SimpleNamespace(
            default_conf=default_conf,
            confs={"default": default_conf},
            get_conf=lambda umo=None: default_conf,
        )
        self.providers_config = default_conf["provider"]
        self.provider_sources_config = default_conf["provider_sources"]
        self.inst_map = {}
        self.provider_insts = []
        self.curr_provider_inst = None
        self.saved = None

    def get_merged_provider_config(self, config):
        return copy.deepcopy(config)

    def _resolve_using_provider(self, provider_type, umo, provider_id):
        pid = provider_id or self.acm.default_conf["agent_runner"]["config"]["model"].get("provider_id")
        return self.inst_map.get(pid) or (self.provider_insts[0] if self.provider_insts else None)

    async def set_provider(self, provider_id, provider_type, umo=None):
        self.curr_provider_inst = self.inst_map[provider_id]


def _install_web_and_entities_stubs(saved_modules):
    if "astrbot.api.web" in sys.modules:
        saved_modules.setdefault("astrbot.api.web", sys.modules["astrbot.api.web"])
    if "astrbot.core.provider.entities" in sys.modules:
        saved_modules.setdefault("astrbot.core.provider.entities", sys.modules["astrbot.core.provider.entities"])

    web_mod = types.ModuleType("astrbot.api.web")
    web_mod.request = types.SimpleNamespace(username="admin", content_type="application/json")
    web_mod._raw_body = b"{}"

    async def _body():
        return web_mod._raw_body

    async def _json(default=None):
        try:
            return json.loads(web_mod._raw_body.decode("utf-8"))
        except Exception:
            return default

    web_mod.request.body = _body
    web_mod.request.json = _json

    def _json_response(data, status_code=200, headers=None):
        return {"status_code": status_code, "headers": dict(headers or {}), "data": copy.deepcopy(data)}

    def _error_response(message, status_code=400, headers=None):
        return {"status_code": status_code, "headers": dict(headers or {}), "data": {"message": message}}

    web_mod.json_response = _json_response
    web_mod.error_response = _error_response
    sys.modules["astrbot.api.web"] = web_mod

    entities = sys.modules.get("astrbot.core.provider.entities")
    if entities is None:
        entities = types.ModuleType("astrbot.core.provider.entities")
        sys.modules["astrbot.core.provider.entities"] = entities
    entities.ProviderType = types.SimpleNamespace(CHAT_COMPLETION="chat_completion")
    return web_mod


def _make_context(manager, data_dir):
    registered = []

    def register_web_api(route, handler, methods, desc):
        registered.append((route, handler, methods, desc))

    return types.SimpleNamespace(
        provider_manager=manager,
        registered_web_apis=registered,
        register_web_api=register_web_api,
    )


class FailureEventsAndReadOnlyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agy-failure-events-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "journal-root"
        self.saved_modules = {}
        self.addCleanup(stop_diagnostics)

    async def asyncTearDown(self):
        stop_diagnostics()
        for name, mod in self.saved_modules.items():
            sys.modules[name] = mod

    async def test_b09_cost_log_disabled_still_persists_failures_not_ok_and_tracks_service(self):
        if sys.platform == "win32":
            self.skipTest("POSIX 权限位断言不适用于 Windows（journal 0o600/0o700 与 mkdir chmod 语义不同）")
        start_diagnostics(self.root)
        tracker = TelemetryTracker(cost_log_enabled=False)

        ok_meter = tracker.start_turn(
            provider="acp-ok",
            session_key_raw="qq:group:998877",
            mode="chat",
            model="gemini-3.1-pro-high",
            effort="low",
        )
        ok_meter.request_sent = True
        ok_meter.finish(status="ok")
        self.assertEqual(failure_snapshot()["failure_events"], [])
        self.assertFalse((self.root / "failure-events-v1.json").exists())
        obs = last_service_observation()
        self.assertEqual(obs["last_observed_provider_id"], "acp-ok")
        self.assertEqual(obs["last_observed_scope"], "plugin_only")
        self.assertIsNotNone(obs["last_observed_at"])

        fail_meter = tracker.start_turn(
            provider="acp-fail",
            session_key_raw="qq:group:998877",
            mode="tools",
            model="gemini-3.1-pro-high",
            effort="medium",
        )
        fail_meter.request_sent = True
        fail_meter.tool_handed_off = True
        fail_meter.logical_request_tag = tracker.opaque_tag("req-123")
        fail_meter.finish(status="error", error_code="TOOL_TIMEOUT")

        self.assertEqual(list(tracker.emitted_lines), [])
        snap = failure_snapshot()
        self.assertEqual(snap["failure_retention"]["storage_state"], "available")
        self.assertEqual(len(snap["failure_events"]), 1)
        evt = snap["failure_events"][0]
        self.assertEqual(evt["status"], "error")
        self.assertEqual(evt["error_code"], "TOOL_TIMEOUT")
        self.assertEqual(evt["provider_tag"], provider_tag("acp-fail"))
        self.assertIs(evt["tool_handed_off"], True)
        self.assertIs(evt["fallback_allowed"], False)
        self.assertEqual(evt["fallback_reason"], "tool_handoff")

        file_path = self.root / "failure-events-v1.json"
        self.assertTrue(file_path.exists())
        self.assertEqual(stat.S_IMODE(file_path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(self.root.stat().st_mode), 0o700)

    async def test_b09_ttl_count_bytes_limits_and_restart_salt_persistence(self):
        fake_now = [1_700_000_000.0]
        with patch("agy_provider.failure_events.time.time", side_effect=lambda: fake_now[0]):
            journal = FailureJournal(self.root, MONITOR_ERROR_CODES)
            self.addCleanup(journal.close)
            first_tag = journal.provider_tag("acp-main")
            journal.append({
                "provider": "acp-main",
                "status": "error",
                "error_code": "UPSTREAM",
                "mode": "chat",
                "elapsed_ms": 12,
                "fallback_allowed": True,
                "fallback_reason": "no_visible_prefix",
            })
            # Advance to just inside TTL: still visible
            fake_now[0] += TTL - 10
            self.assertEqual(len(journal.snapshot()["failure_events"]), 1)

            # Reopen across simulated restart: salt & tag remain identical
            journal.close()
            restarted = FailureJournal(self.root, MONITOR_ERROR_CODES)
            self.addCleanup(restarted.close)
            self.assertEqual(restarted.provider_tag("acp-main"), first_tag)
            self.assertEqual(len(restarted.snapshot()["failure_events"]), 1)

            # Past TTL: expired automatically
            fake_now[0] += 20
            self.assertEqual(restarted.snapshot()["failure_events"], [])

            # Exceed MAX_EVENTS (128) with compact events (< 64KiB total when provider_tag=None): hits 128-event cap
            for idx in range(MAX_EVENTS + 15):
                fake_now[0] += 0.01
                restarted.append({
                    "provider": None,
                    "status": "error",
                    "error_code": "STOP",
                    "mode": "chat",
                    "elapsed_ms": idx % 10,
                })
            snap = restarted.snapshot()
            self.assertEqual(len(snap["failure_events"]), MAX_EVENTS)
            self.assertEqual(snap["failure_events"][0]["elapsed_ms"], (MAX_EVENTS + 14) % 10)
            self.assertLessEqual((self.root / "failure-events-v1.json").stat().st_size, MAX_BYTES)

            # Rich events with all optional fields populated hit MAX_BYTES (64KiB) before 128 rows
            for idx in range(MAX_EVENTS):
                fake_now[0] += 0.01
                restarted.append({
                    "provider": "acp-main",
                    "status": "error",
                    "error_code": "TOOL_TIMEOUT",
                    "mode": "tools",
                    "elapsed_ms": idx,
                    "fallback_allowed": False,
                    "fallback_reason": "tool_handoff",
                    "stop_reason": "error",
                    "turn_id": f"{idx:016x}",
                    "origin_turn_id": f"{idx + 1000:016x}",
                    "logical_request_tag": f"{idx + 2000:016x}",
                    "attempt": 1,
                    "cli_retry_attempt": 2,
                    "chunk_seen": False,
                    "body_seen": False,
                    "body_streamed": False,
                    "tool_handed_off": True,
                    "tool_result_supplied": True,
                    "body_bytes": 0,
                    "thought_bytes": 12,
                    "permission_denial_count": 0,
                    "filtered_notice_count": 1,
                })
            byte_snap = restarted.snapshot()
            self.assertLess(len(byte_snap["failure_events"]), MAX_EVENTS)
            self.assertGreater(len(byte_snap["failure_events"]), 50)
            self.assertLessEqual((self.root / "failure-events-v1.json").stat().st_size, MAX_BYTES)
            restarted.close()

            # Pre-existing oversized snapshot (>64KiB) fails closed and resets cleanly
            (self.root / "failure-events-v1.json").write_bytes(b"{" + b"x" * MAX_BYTES + b"}")
            reset_journal = FailureJournal(self.root, MONITOR_ERROR_CODES)
            self.addCleanup(reset_journal.close)
            self.assertEqual(reset_journal.snapshot()["failure_events"], [])
            self.assertLessEqual((self.root / "failure-events-v1.json").stat().st_size, MAX_BYTES)

    async def test_b09_malformed_future_symlink_unwritable_and_sentinel_non_leakage(self):
        # 1. Malformed + extra keys + future timestamp + sentinel secrets
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        now = 1_700_000_000.0
        bad_payload = {
            "salt": "00" * 32,
            "extra_unexpected_key": "must_reset",
            "events": [
                {"time": now + 3600, "status": "error", "error_code": "UPSTREAM"},  # future ts
                {"time": now - 10, "status": "error", "error_code": "NOT_IN_VOCAB", "elapsed_ms": True,
                 "turn_id": "invalid_short", "provider_tag": "NOT_HEX", "raw_umo": "qq:999"},
                {"time": now - 5, "status": "cancelled", "error_code": "CANCELLED", "elapsed_ms": 50},
            ],
        }
        (self.root / "failure-events-v1.json").write_text(json.dumps(bad_payload), encoding="utf-8")
        with patch("agy_provider.failure_events.time.time", return_value=now):
            journal = FailureJournal(self.root, MONITOR_ERROR_CODES)
            self.addCleanup(journal.close)
            events = journal.snapshot()["failure_events"]
            self.assertEqual(len(events), 2)
            # First appended row in snapshot is newest (-5) then (-10)
            sanitized_old = events[1]
            self.assertEqual(sanitized_old["error_code"], "UNKNOWN")
            self.assertIsNone(sanitized_old["elapsed_ms"])
            self.assertIsNone(sanitized_old["turn_id"])
            self.assertIsNone(sanitized_old["provider_tag"])
            self.assertNotIn("raw_umo", sanitized_old)

            # Inject sensitive fields directly to append(): verify none persist
            sentinels = [
                "qq:group:999888777",
                "SECRET_USER_MESSAGE",
                "SECRET_TOOL_PARAM",
                "ya29.SECRET_OAUTH_TOKEN",
                "https://oauth.example/cb?code=AUTH_CODE_XYZ",
                "http://user:pass@example.invalid:8080",
            ]
            journal.append({
                "provider": "acp-main",
                "status": "short_circuited",
                "error_code": "QUOTA",
                "mode": "chat",
                "raw_umo": sentinels[0],
                "prompt": sentinels[1],
                "tool_args": sentinels[2],
                "oauth": sentinels[3],
                "auth_url": sentinels[4],
                "proxy": sentinels[5],
            })
            on_disk = (self.root / "failure-events-v1.json").read_text(encoding="utf-8")
            snap_json = json.dumps(journal.snapshot(), ensure_ascii=False)
            for s in sentinels:
                self.assertNotIn(s, on_disk)
                self.assertNotIn(s, snap_json)
            journal.close()

            # Corrupt JSON resets safely
            (self.root / "failure-events-v1.json").write_text("{corrupt", encoding="utf-8")
            repaired = FailureJournal(self.root, MONITOR_ERROR_CODES)
            self.addCleanup(repaired.close)
            self.assertEqual(repaired.snapshot()["failure_events"], [])
            self.assertEqual(repaired.snapshot()["failure_retention"]["storage_state"], "available")
            repaired.close()

        # 2. Symlink root & symlink target fail closed without following symlink
        victim = Path(self.temp.name) / "victim.json"
        victim.write_text("KEEP_ME", encoding="utf-8")
        sym_root = Path(self.temp.name) / "sym-root"
        sym_root.symlink_to(self.root)
        sym_journal = FailureJournal(sym_root, MONITOR_ERROR_CODES)
        self.addCleanup(sym_journal.close)
        self.assertEqual(sym_journal.snapshot()["failure_retention"]["storage_state"], "unavailable")

        file_sym_dir = Path(self.temp.name) / "file-sym-dir"
        file_sym_dir.mkdir(mode=0o700)
        (file_sym_dir / "failure-events-v1.json").symlink_to(victim)
        file_sym_journal = FailureJournal(file_sym_dir, MONITOR_ERROR_CODES)
        self.addCleanup(file_sym_journal.close)
        self.assertEqual(file_sym_journal.snapshot()["failure_retention"]["storage_state"], "unavailable")
        self.assertEqual(victim.read_text(encoding="utf-8"), "KEEP_ME")

        # 3. Unwritable root (path collision with regular file) degrades cleanly
        blocked_root = Path(self.temp.name) / "regular-file-as-root"
        blocked_root.write_text("not a dir", encoding="utf-8")
        blocked_journal = FailureJournal(blocked_root, MONITOR_ERROR_CODES)
        self.addCleanup(blocked_journal.close)
        self.assertEqual(blocked_journal.snapshot()["failure_retention"]["storage_state"], "unavailable")
        blocked_journal.append({"provider": "acp-main", "status": "error", "error_code": "UPSTREAM"})
        self.assertEqual(blocked_journal.snapshot()["failure_retention"]["storage_state"], "unavailable")

    def _install_stub_scope(self):
        """Install AstrBot module stubs (mirrors tests/test_main_init.py) and re-import agy_provider."""
        import importlib
        import importlib.util

        # astrbot.api / astrbot.api.web already stubbed by module-level import / _install_web_and_entities_stubs
        api_mod = sys.modules.get("astrbot.api") or types.ModuleType("astrbot.api")
        sys.modules["astrbot.api"] = api_mod

        def fake_command_group(*a, **kw):
            def decorator(fn):
                fn.command = lambda *ca, **ckw: (lambda f: f)
                return fn

            return decorator

        filter_obj = types.SimpleNamespace(
            command_group=fake_command_group,
            permission_type=lambda *a, **kw: (lambda fn: fn),
            PermissionType=types.SimpleNamespace(ADMIN="admin"),
        )
        event_mod = types.ModuleType("astrbot.api.event")
        event_mod.AstrMessageEvent = object
        event_mod.filter = filter_obj
        star_mod = types.ModuleType("astrbot.api.star")
        star_mod.Context = object
        star_mod.Star = object
        star_mod.register = lambda *a, **kw: (lambda cls: cls)
        provider_api_mod = types.ModuleType("astrbot.api.provider")
        provider_api_mod.LLMResponse = object
        provider_api_mod.Provider = object
        core_mod = types.ModuleType("astrbot.core")
        core_provider_mod = sys.modules.get("astrbot.core.provider") or types.ModuleType("astrbot.core.provider")
        core_provider_mod.register = lambda *a, **kw: None
        entities_mod = sys.modules.get("astrbot.core.provider.entities") or types.ModuleType("astrbot.core.provider.entities")
        if not hasattr(entities_mod, "TokenUsage"):
            entities_mod.TokenUsage = dict
        if not hasattr(entities_mod, "ProviderType"):
            entities_mod.ProviderType = types.SimpleNamespace(CHAT_COMPLETION="chat_completion")
        utils_mod = types.ModuleType("astrbot.core.utils")
        path_mod = types.ModuleType("astrbot.core.utils.astrbot_path")
        path_mod.get_astrbot_plugin_data_path = lambda: str(self.root)
        agent_mod = types.ModuleType("astrbot.core.agent")
        runners_mod = types.ModuleType("astrbot.core.agent.runners")
        loop_mod = types.ModuleType("astrbot.core.agent.runners.tool_loop_agent_runner")
        loop_mod.ToolLoopAgentRunner = object

        repo_root = Path(__file__).resolve().parents[1]
        pkg_name = "agy_failure_events_test_pkg"
        pkg_mod = types.ModuleType(pkg_name)
        pkg_mod.__path__ = [str(repo_root)]

        stubs = {
            "astrbot.api.event": event_mod,
            "astrbot.api.star": star_mod,
            "astrbot.api.provider": provider_api_mod,
            "astrbot.core": core_mod,
            "astrbot.core.provider": core_provider_mod,
            "astrbot.core.provider.entities": entities_mod,
            "astrbot.core.utils": utils_mod,
            "astrbot.core.utils.astrbot_path": path_mod,
            "astrbot.core.agent": agent_mod,
            "astrbot.core.agent.runners": runners_mod,
            "astrbot.core.agent.runners.tool_loop_agent_runner": loop_mod,
            pkg_name: pkg_mod,
        }
        for name, mod in stubs.items():
            self.saved_modules.setdefault(name, sys.modules.get(name))
            sys.modules[name] = mod

        # Re-import agy_provider submodules cleanly inside the patched sys.modules scope.
        for name in list(sys.modules):
            if name == "agy_provider" or name.startswith("agy_provider."):
                self.saved_modules.setdefault(name, sys.modules.get(name))
                sys.modules.pop(name, None)

        agy_pkg = importlib.import_module("agy_provider")
        sys.modules[f"{pkg_name}.agy_provider"] = agy_pkg
        for sub in ("config", "errors", "host_compat", "onboarding", "provider", "routing", "paths", "monitoring", "_version"):
            sys.modules[f"{pkg_name}.agy_provider.{sub}"] = importlib.import_module(
                f"agy_provider.{sub}"
            )

        spec = importlib.util.spec_from_file_location(
            f"{pkg_name}.main", repo_root / "main.py"
        )
        main_mod = importlib.util.module_from_spec(spec)
        sys.modules[f"{pkg_name}.main"] = main_mod
        spec.loader.exec_module(main_mod)
        return main_mod

    async def test_b10_zero_generation_read_only_routes_auth_and_doctor(self):
        web_mod = _install_web_and_entities_stubs(self.saved_modules)
        self._install_stub_scope()
        start_diagnostics(self.root)

        manager = _FakeManager()
        manager.providers_config.append({"id": "acp-1", "type": "agy_acp", "enable": True, "model": "gemini-3.1-pro-high"})
        runtime = types.SimpleNamespace(
            sessions={},
            model_cache=[],
            telemetry=TelemetryTracker(cost_log_enabled=False),
            pool_stats=lambda: {"size": 0, "max_size": 4},
        )
        inst = types.SimpleNamespace(
            provider_config=copy.deepcopy(manager.providers_config[0]),
            runtime=runtime,
            get_model=lambda: "gemini-3.1-pro-high",
        )
        manager.inst_map["acp-1"] = inst
        manager.provider_insts.append(inst)
        manager.curr_provider_inst = inst

        ctx = _make_context(manager, self.root)
        with patch.object(onboarding_module, "plugin_data_root", return_value=self.root):
            onboarding = Onboarding(ctx, Settings())
        monitoring = Monitoring(ctx)

        with (
            patch("agy_provider.process.asyncio.create_subprocess_exec", side_effect=AssertionError("must not spawn CLI")),
            patch("agy_provider.process.discover", side_effect=AssertionError("must not discover CLI")),
            patch("agy_provider.models.catalog", side_effect=AssertionError("must not probe models")),
            patch("agy_provider.probe.probe", side_effect=AssertionError("must not probe CLI")),
            patch("agy_provider.transport.AcpClient.generate", side_effect=AssertionError("must not prompt ACP")),
            patch("agy_provider.provider.AgyProvider.text_chat", side_effect=AssertionError("must not call text_chat")),
            patch("agy_provider.provider.AgyProvider.text_chat_stream", side_effect=AssertionError("must not call text_chat_stream")),
            patch.object(onboarding, "start_check", side_effect=AssertionError("GET/impact must not start check")),
        ):
            # Auth checks: 401 anonymous, 403 non-admin & api_key
            web_mod.request.username = ""
            self.assertEqual((await monitoring.handle())["status_code"], 401)
            self.assertEqual((await onboarding.handle("status"))["status_code"], 401)
            for bad_user in ("guest", "api_key:admin"):
                web_mod.request.username = bad_user
                self.assertEqual((await monitoring.handle())["status_code"], 403)
                self.assertEqual((await onboarding.handle("provider-impact"))["status_code"], 403)

            # Valid admin GET routes & provider-impact
            web_mod.request.username = "admin"
            mon_1 = await monitoring.handle()
            self.assertEqual(mon_1["status_code"], 200)
            self.assertEqual(mon_1["headers"]["Cache-Control"], "no-store")
            self.assertEqual(mon_1["headers"]["Referrer-Policy"], "no-referrer")
            self.assertEqual(mon_1["data"]["schema_version"], 2)
            self.assertEqual(mon_1["data"]["routing"]["resolved_primary_id"], "acp-1")
            self.assertEqual(mon_1["data"]["failure_events"], [])

            st = await onboarding.handle("status")
            self.assertEqual(st["status_code"], 200)
            self.assertEqual(st["headers"]["Cache-Control"], "no-store")
            self.assertEqual(st["data"]["routing"]["resolved_primary_id"], "acp-1")

            web_mod._raw_body = json.dumps({"csrf": onboarding.csrf, "provider_id": "acp-1"}).encode("utf-8")
            imp = await onboarding.handle("provider-impact")
            self.assertEqual(imp["status_code"], 200)
            self.assertIs(imp["data"]["impact"]["can_delete"], False)
            self.assertIs(imp["data"]["impact"]["can_disable"], False)

            # Subsequent runtime failure + route change updates monitor/status without restarting/probing
            meter = runtime.telemetry.start_turn(
                provider="acp-1", session_key_raw="qq:1", mode="chat", model="gemini-3.1-pro-high", effort="low"
            )
            meter.request_sent = True
            meter.finish(status="error", error_code="RATE_LIMIT")
            manager.acm.default_conf["agent_runner"]["config"]["model"]["provider_id"] = "missing-id"

            mon_2 = await monitoring.handle()
            self.assertEqual(mon_2["data"]["schema_version"], 2)
            self.assertEqual(mon_2["data"]["routing"]["configured_primary_id"], "missing-id")
            self.assertEqual(mon_2["data"]["routing"]["resolution_reason"], "implicit_first_provider")
            self.assertEqual(len(mon_2["data"]["failure_events"]), 1)
            self.assertEqual(mon_2["data"]["failure_events"][0]["error_code"], "RATE_LIMIT")

        # /agy doctor runs preflight check ONLY (no model prompt / text_chat generation) and includes routing
        # main already loaded via _install_stub_scope at test start (agy_provider.* re-imported under stubs)
        main_module = sys.modules["agy_failure_events_test_pkg.main"]

        plugin = main_module.AgyProviderPlugin.__new__(main_module.AgyProviderPlugin)
        plugin.context = ctx
        plugin.stopping = False
        plugin.doctor_lock = asyncio.Lock()
        plugin.doctor_task = None
        plugin.setup_service = onboarding

        async def _fake_preflight():
            onboarding.report = {
                "status": "ready",
                "error_code": None,
                "models": ["gemini-3.1-pro-high"],
                "efforts": ["low", "high"],
                "selected_model": "gemini-3.1-pro-high",
            }

        def _start_preflight():
            onboarding.job = asyncio.create_task(_fake_preflight())

        replies = []
        event = types.SimpleNamespace(
            is_admin=lambda: True,
            plain_result=lambda text: text,
        )
        with (
            patch.object(onboarding, "start_check", side_effect=_start_preflight),
            patch("agy_provider.transport.AcpClient.generate", side_effect=AssertionError("doctor must never prompt")),
            patch("agy_provider.provider.AgyProvider.text_chat", side_effect=AssertionError("doctor must not generate")),
            patch("agy_provider.provider.AgyProvider.text_chat_stream", side_effect=AssertionError("doctor must not stream generate")),
        ):
            async for item in plugin.doctor(event):
                replies.append(item)

        self.assertEqual(len(replies), 1)
        doctor_text = replies[0]
        self.assertIn('"routing"', doctor_text)
        self.assertNotIn('"models"', doctor_text)
        self.assertNotIn('"efforts"', doctor_text)
        self.assertNotIn('"selected_model"', doctor_text)


if __name__ == "__main__":
    unittest.main()
