"""Offline regression tests for B01-B04 routing, fallback safety, and controlled delete/disable."""

import ast
import asyncio
import copy
import enum
import json
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from tests import astrbot_stub  # noqa: F401 -- install offline AstrBot stubs

from agy_provider import onboarding as onboarding_module
from agy_provider.config import Settings
from agy_provider.errors import AgyError
from agy_provider.onboarding import Onboarding
from agy_provider.routing import (
    OverrideObservations,
    dashboard_admin,
    enable_provider,
    provider_impact,
    routing_snapshot,
    select_default,
    sync_current_provider_pointer,
)
from agy_provider.telemetry import TelemetryTracker, start_diagnostics, stop_diagnostics

DEFAULT_HOST_MANAGER = (
    Path(__file__).resolve().parents[2] / "evidence" / "repro" / "host" / "host-manager.py"
)


class _ProviderType(enum.Enum):
    CHAT_COMPLETION = "chat_completion"
    TEXT_TO_SPEECH = "text_to_speech"
    SPEECH_TO_TEXT = "speech_to_text"
    DECISION = "decision"


class _Provider:
    def __init__(self, config):
        self.provider_config = config
        self.provider_settings = {}
        self.runtime = None

    def get_model(self):
        return self.provider_config.get("model", "")


class _UnrelatedProvider:
    pass


def _extract_host_manager_methods():
    source_path = os.environ.get("AGY_HOST_MANAGER_SOURCE") or (
        str(DEFAULT_HOST_MANAGER) if DEFAULT_HOST_MANAGER.is_file() else None
    )
    if not source_path:
        return None, None
    source = Path(source_path)
    tree = ast.parse(source.read_text(encoding="utf-8"))
    cls = next(
        n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ProviderManager"
    )
    extracted = {}
    for target_name in ("_resolve_using_provider", "set_provider", "delete_provider"):
        node = next(
            n for n in cls.body
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == target_name
        )
        fn = copy.deepcopy(node)
        fn.decorator_list = []
        extracted[target_name] = fn
    module = ast.Module(
        body=[
            ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0),
            *extracted.values(),
        ],
        type_ignores=[],
    )
    ast.fix_missing_locations(module)
    sp = types.SimpleNamespace(put_async=AsyncMock(), session_put=AsyncMock())
    ns = {
        "copy": copy,
        "json": json,
        "Provider": _Provider,
        "TTSProvider": _UnrelatedProvider,
        "STTProvider": _UnrelatedProvider,
        "DecisionProvider": _UnrelatedProvider,
        "ProviderType": _ProviderType,
        "sp": sp,
        "logger": Mock(),
    }
    exec(compile(module, str(source), "exec"), ns)
    return {name: ns[name] for name in extracted}, source_path


_HOST_METHODS, _HOST_SOURCE_PATH = _extract_host_manager_methods()


class _PersistingConfig(dict):
    def __init__(self, backing_file: Path, initial: dict):
        super().__init__(copy.deepcopy(initial))
        self._backing_file = backing_file
        self.fail_next_save = False

    def save_config(self):
        if self.fail_next_save:
            self.fail_next_save = False
            raise OSError("simulated disk error")
        self._backing_file.write_text(json.dumps(dict(self), ensure_ascii=False), encoding="utf-8")


def _build_manager_class():
    class HostBackedManager:
        def __init__(self, backing_file: Path, initial: dict):
            self.backing_file = backing_file
            self.reload_lock = asyncio.Lock()
            self.resource_lock = asyncio.Lock()
            default_conf = _PersistingConfig(backing_file, initial)
            self.acm = types.SimpleNamespace(
                default_conf=default_conf,
                confs={"default": default_conf},
                get_conf=lambda umo=None: self.acm.confs.get(umo or "default", default_conf),
            )
            self.providers_config = default_conf["provider"]
            self.provider_sources_config = default_conf["provider_sources"]
            self.inst_map = {}
            self.provider_insts = []
            self.curr_provider_inst = None
            self.default_chat_provider_id = (
                default_conf["agent_runner"]["config"]["model"].get("provider_id", "")
                if default_conf["agent_runner"].get("runner_type") == "local"
                else ""
            )
            self._provider_change_hooks = []
            self.fail_reload = False
            self.fail_set_provider = False
            self._rebuild_loaded_instances()

        def _rebuild_loaded_instances(self):
            self.inst_map.clear()
            self.provider_insts.clear()
            for row in self.acm.default_conf["provider"]:
                if row.get("enable"):
                    inst = _Provider(copy.deepcopy(row))
                    self.inst_map[row["id"]] = inst
                    self.provider_insts.append(inst)
            pid = self.acm.default_conf.get("agent_runner", {}).get("config", {}).get("model", {}).get("provider_id")
            self.curr_provider_inst = self.inst_map.get(pid)

        def register_provider_change_hook(self, hook):
            if hook not in self._provider_change_hooks:
                self._provider_change_hooks.append(hook)

        def _notify_provider_changed(self, provider_id, provider_type, umo):
            for hook in list(self._provider_change_hooks):
                hook(provider_id, provider_type, umo)

        def get_merged_provider_config(self, config):
            merged = copy.deepcopy(config)
            sid = merged.get("provider_source_id", "")
            for src in self.provider_sources_config:
                if src.get("id") == sid:
                    for key in ("type", "api_key"):
                        if key in src and key not in merged:
                            merged[key] = copy.deepcopy(src[key])
            return merged

        async def reload(self, provider_config):
            if self.fail_reload:
                self.fail_reload = False
                raise RuntimeError("reload failed")
            pid = provider_config["id"]
            old = self.inst_map.pop(pid, None)
            if old in self.provider_insts:
                self.provider_insts.remove(old)
            if provider_config.get("enable"):
                inst = _Provider(copy.deepcopy(provider_config))
                self.inst_map[pid] = inst
                self.provider_insts.append(inst)

        async def terminate_provider(self, provider_id):
            old = self.inst_map.pop(provider_id, None)
            if old in self.provider_insts:
                self.provider_insts.remove(old)
            if self.curr_provider_inst is old:
                self.curr_provider_inst = None

        async def create_provider(self, new_config):
            async with self.resource_lock:
                self.providers_config.append(copy.deepcopy(new_config))
                self.acm.default_conf.save_config()
                await self.reload(new_config)

        async def _set_provider_impl(self, provider_id, provider_type, umo=None):
            if self.fail_set_provider:
                self.fail_set_provider = False
                raise RuntimeError("set_provider failed")
            if _HOST_METHODS is not None:
                return await _HOST_METHODS["set_provider"](self, provider_id, provider_type, umo)
            if provider_id not in self.inst_map:
                raise ValueError(f"missing {provider_id}")
            if not umo and provider_type == _ProviderType.CHAT_COMPLETION:
                self.curr_provider_inst = self.inst_map[provider_id]
                self._notify_provider_changed(provider_id, provider_type, umo)

        set_provider = _set_provider_impl

        def _resolve_using_provider(self, provider_type, umo, provider_id):
            if _HOST_METHODS is not None:
                return _HOST_METHODS["_resolve_using_provider"](self, provider_type, umo, provider_id)
            config = self.acm.get_conf(umo)
            pid = provider_id or config.get("agent_runner", {}).get("config", {}).get("model", {}).get("provider_id")
            return self.inst_map.get(pid) or (self.provider_insts[0] if self.provider_insts else None)

        async def delete_provider(self, provider_id=None, provider_source_id=None):
            if _HOST_METHODS is not None:
                return await _HOST_METHODS["delete_provider"](self, provider_id, provider_source_id)
            async with self.resource_lock:
                await self.terminate_provider(provider_id)
                self.acm.default_conf["provider"] = [
                    p for p in self.acm.default_conf["provider"] if p.get("id") != provider_id
                ]
                self.acm.default_conf.save_config()
                self.providers_config = self.acm.default_conf["provider"]

    return HostBackedManager


def _install_web_and_entities(saved_modules):
    for mod_name in ("astrbot.api.web", "astrbot.core.provider.entities"):
        if mod_name in sys.modules:
            saved_modules.setdefault(mod_name, sys.modules[mod_name])

    web_mod = types.ModuleType("astrbot.api.web")
    web_mod.request = types.SimpleNamespace(username="admin", content_type="application/json")
    web_mod._raw_body = b"{}"
    web_mod.request.body = AsyncMock(side_effect=lambda: web_mod._raw_body)
    web_mod.request.json = AsyncMock(side_effect=lambda default=None: json.loads(web_mod._raw_body.decode("utf-8")))
    web_mod.json_response = lambda data, status_code=200, headers=None: {
        "status_code": status_code, "headers": dict(headers or {}), "data": copy.deepcopy(data)
    }
    web_mod.error_response = lambda msg, status_code=400, data=None, headers=None: {
        "status_code": status_code, "headers": dict(headers or {}), "data": {"message": msg, **(data or {})}
    }
    sys.modules["astrbot.api.web"] = web_mod

    entities_mod = types.ModuleType("astrbot.core.provider.entities")
    entities_mod.ProviderType = _ProviderType
    sys.modules["astrbot.core.provider.entities"] = entities_mod
    return web_mod


class RoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="agy-routing-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.conf_file = self.root / "cmd_config.json"
        self.saved_modules = {}
        self.web_mod = _install_web_and_entities(self.saved_modules)
        self.Manager = _build_manager_class()
        start_diagnostics(self.root / "diag")
        self.addCleanup(stop_diagnostics)

    async def asyncTearDown(self):
        for name, mod in self.saved_modules.items():
            sys.modules[name] = mod

    def _initial_config(self):
        return {
            "dashboard": {"username": "admin"},
            "provider": [
                {"id": "zhipu_vlm", "type": "openai_chat_completion", "enable": True, "model": "glm-4v"},
                {"id": "acp_chat", "type": "agy_acp", "enable": False, "model": "gemini-3.1-pro-high",
                 "custom_extra_body": {"agy_thought_level": "default", "agy_tools_mode": "chat"}},
                {"id": "acp_tools", "type": "agy_acp", "enable": True, "model": "gemini-3.1-pro-high",
                 "custom_extra_body": {"agy_thought_level": "default", "agy_tools_mode": "tools"}},
                {"id": "acp_disabled", "type": "agy_acp", "enable": False, "model": "gemini-2.5-flash",
                 "custom_extra_body": {"agy_thought_level": "default", "agy_tools_mode": "chat"}},
            ],
            "provider_sources": [{"id": "agy_acp", "type": "agy_acp", "provider_type": "chat_completion", "enable": True}],
            "provider_settings": {},
            "provider_stt_settings": {},
            "agent_runner": {
                "runner_type": "local",
                "config": {
                    "model": {
                        "provider_id": "zhipu_vlm",
                        "fallback_provider_ids": ["acp_tools", "missing_fb", "acp_disabled"],
                    }
                },
            },
        }

    def _make_service(self, manager):
        registered = []
        ctx = types.SimpleNamespace(
            provider_manager=manager,
            registered_web_apis=registered,
            register_web_api=lambda route, handler, methods, desc: registered.append((route, handler)),
        )
        with patch.object(onboarding_module, "plugin_data_root", return_value=self.root):
            service = Onboarding(ctx, Settings())
        service.register()
        return service

    @unittest.skipUnless(_HOST_METHODS is not None, "Captured 4.29.4 host-manager.py unavailable")
    async def test_b01_use_default_persists_real_4294_resolver_and_survives_rebuild(self):
        manager = self.Manager(self.conf_file, self._initial_config())
        service = self._make_service(manager)

        # Before: resolves to zhipu_vlm via official 4.29.4 _resolve_using_provider
        self.assertIs(manager._resolve_using_provider(_ProviderType.CHAT_COMPLETION, None, None), manager.inst_map["zhipu_vlm"])

        # Enable + set default on previously disabled acp_chat
        await enable_provider(manager, "acp_chat", expected=copy.deepcopy(manager.providers_config[1]), use_default=True)
        self.assertTrue(manager.providers_config[1]["enable"])
        self.assertEqual(manager.acm.default_conf["agent_runner"]["config"]["model"]["provider_id"], "acp_chat")
        self.assertEqual(manager.default_chat_provider_id, "acp_chat")
        self.assertIs(manager.curr_provider_inst, manager.inst_map["acp_chat"])
        self.assertIs(manager._resolve_using_provider(_ProviderType.CHAT_COMPLETION, None, None), manager.inst_map["acp_chat"])

        # Simulate restart by rebuilding Manager solely from persisted disk JSON
        persisted = json.loads(self.conf_file.read_text(encoding="utf-8"))
        rebuilt = self.Manager(self.conf_file, persisted)
        resolved_after_restart = rebuilt._resolve_using_provider(_ProviderType.CHAT_COMPLETION, None, None)
        self.assertIs(resolved_after_restart, rebuilt.inst_map["acp_chat"])
        snap = routing_snapshot(rebuilt)
        self.assertEqual(snap["configured_primary_id"], "acp_chat")
        self.assertEqual(snap["resolved_primary_id"], "acp_chat")
        self.assertIs(snap["is_acp"], True)
        self.assertEqual(snap["resolution_reason"], "configured_primary")

        # Also verify onboarding POST provider-default switches cleanly to acp_tools
        self.web_mod._raw_body = json.dumps({"csrf": service.csrf, "provider_id": "acp_tools", "confirm": True}).encode("utf-8")
        # Recreate manager with rebuilt state so hooks match
        service2 = self._make_service(rebuilt)
        self.web_mod._raw_body = json.dumps({"csrf": service2.csrf, "provider_id": "acp_tools", "confirm": True}).encode("utf-8")
        resp = await service2.handle("provider-default")
        self.assertEqual(resp["status_code"], 200)
        await service2.job
        self.assertTrue(service2.result["applied"])
        self.assertEqual(rebuilt.acm.default_conf["agent_runner"]["config"]["model"]["provider_id"], "acp_tools")
        self.assertIs(rebuilt._resolve_using_provider(_ProviderType.CHAT_COMPLETION, None, None), rebuilt.inst_map["acp_tools"])

    async def test_b02_use_default_false_and_failures_roll_back_cleanly(self):
        initial = self._initial_config()
        manager = self.Manager(self.conf_file, initial)
        service = self._make_service(manager)

        # 1. apply with use_default=False creates new ACP provider without changing route or fallback list
        await service._save_provider("gemini-2.5-pro", "high", False, tools_mode="chat")
        self.assertFalse(service.result["default_selected"])
        self.assertEqual(manager.acm.default_conf["agent_runner"]["config"]["model"]["provider_id"], "zhipu_vlm")
        self.assertEqual(manager.acm.default_conf["agent_runner"]["config"]["model"]["fallback_provider_ids"], ["acp_tools", "missing_fb", "acp_disabled"])
        self.assertIs(manager.curr_provider_inst, manager.inst_map["zhipu_vlm"])

        # 2. If save fails during select_default, previous provider_id and curr_provider_inst roll back
        manager.acm.default_conf.fail_next_save = True
        with self.assertRaises(AgyError) as caught:
            await select_default(manager, "acp_tools")
        self.assertEqual(caught.exception.code, "HOST")
        self.assertEqual(manager.acm.default_conf["agent_runner"]["config"]["model"]["provider_id"], "zhipu_vlm")
        self.assertIs(manager.curr_provider_inst, manager.inst_map["zhipu_vlm"])

        # 3. If previous provider_id did NOT exist at all, failure pops provider_id rather than leaving empty/stale
        del manager.acm.default_conf["agent_runner"]["config"]["model"]["provider_id"]
        manager.fail_set_provider = True
        with self.assertRaises(AgyError):
            await select_default(manager, "acp_tools")
        self.assertNotIn("provider_id", manager.acm.default_conf["agent_runner"]["config"]["model"])

        # Restore primary, test enable_provider reload/select rollback preserves disabled state
        manager.acm.default_conf["agent_runner"]["config"]["model"]["provider_id"] = "zhipu_vlm"
        manager.fail_reload = True
        with self.assertRaises(AgyError) as caught_reload:
            await enable_provider(manager, "acp_chat", expected=copy.deepcopy(manager.providers_config[1]), use_default=True)
        self.assertEqual(caught_reload.exception.code, "HOST")
        self.assertFalse(manager.providers_config[1]["enable"])
        self.assertEqual(manager.acm.default_conf["agent_runner"]["config"]["model"]["provider_id"], "zhipu_vlm")

        # 4. Non-local runner fails with ROUTE_MISMATCH; missing _resolve_using_provider fails closed
        manager.acm.default_conf["agent_runner"]["runner_type"] = "dify"
        with self.assertRaises(AgyError) as caught_runner:
            await select_default(manager, "acp_tools")
        self.assertEqual(caught_runner.exception.code, "ROUTE_MISMATCH")

        manager.acm.default_conf["agent_runner"]["runner_type"] = "local"
        with patch.object(manager, "_resolve_using_provider", return_value=manager.inst_map["zhipu_vlm"]):
            with self.assertRaises(AgyError) as caught_mismatch:
                await select_default(manager, "acp_tools")
        self.assertEqual(caught_mismatch.exception.code, "ROUTE_MISMATCH")
        self.assertEqual(manager.acm.default_conf["agent_runner"]["config"]["model"]["provider_id"], "zhipu_vlm")

        # 5. Session override via hook keeps global route intact & is counted under observed_session_overrides
        manager._notify_provider_changed("acp_chat", _ProviderType.CHAT_COMPLETION, "qq:session:42")
        self.assertEqual(manager.acm.default_conf["agent_runner"]["config"]["model"]["provider_id"], "zhipu_vlm")
        # Duplicate UMO updates replace rather than double-count
        manager._notify_provider_changed("acp_tools", _ProviderType.CHAT_COMPLETION, "qq:session:42")
        imp_chat = provider_impact(manager, "acp_chat", service.overrides)
        imp_tools = provider_impact(manager, "acp_tools", service.overrides)
        self.assertEqual(imp_chat["references"]["observed_session_overrides"], 0)
        self.assertEqual(imp_tools["references"]["observed_session_overrides"], 1)

    async def test_b03_controlled_delete_disable_impact_and_dangling_detection(self):
        cfg = self._initial_config()
        # Add another profile referencing acp_disabled as auxiliary TTS/custom field
        cfg["provider_settings"]["extra_acp_provider_id"] = "acp_chat"
        manager = self.Manager(self.conf_file, cfg)
        manager.acm.confs["profile_b"] = {
            "agent_runner": {"runner_type": "local", "config": {"model": {"provider_id": "acp_tools", "custom_helper_provider_ids": ["acp_chat"]}}},
        }
        service = self._make_service(manager)

        # Non-ACP rejected across all provider-* gates
        for action in ("provider-impact", "provider-default", "provider-delete", "provider-toggle"):
            payload = {"csrf": service.csrf, "provider_id": "zhipu_vlm"}
            if action != "provider-impact":
                payload["confirm"] = True
            if action == "provider-toggle":
                payload["enabled"] = True
            self.web_mod._raw_body = json.dumps(payload).encode("utf-8")
            resp = await service.handle(action)
            if action == "provider-impact":
                self.assertEqual(resp["status_code"], 400)
            else:
                self.assertEqual(resp["status_code"], 200)
                await service.job
                self.assertEqual(service.action_error, "CONFIG")

        # 无引用 ACP 未确认 force_confirm 时仍受阻，但预览标明可确认放行且无需迁移
        unreferenced_id = "acp_unref"
        manager.providers_config.append({
            "id": unreferenced_id, "type": "agy_acp", "enable": True, "model": "gemini-3.1-pro-high",
            "custom_extra_body": {"agy_thought_level": "default", "agy_tools_mode": "chat"},
        })
        manager._rebuild_loaded_instances()
        imp_unref = provider_impact(manager, unreferenced_id, service.overrides)
        self.assertTrue(imp_unref["can_delete"])
        self.assertTrue(imp_unref["can_disable"])
        self.assertFalse(imp_unref["requires_migration"])
        self.assertEqual(imp_unref["block_reason"], "incomplete_scan")
        self.assertEqual(imp_unref["session_scan"], "unknown")
        self.assertEqual(imp_unref["profiles_scanned"], 2)

        imp_chat = provider_impact(manager, "acp_chat", service.overrides)
        self.assertEqual(imp_chat["block_reason"], "referenced")
        self.assertEqual(imp_chat["references"]["auxiliary"], 2)

        # 未携带 force_confirm 的直接删除/停用继续返回 REFERENCE_BLOCKED，不修改旁系实例
        for action, extra in (("provider-delete", {}), ("provider-toggle", {"enabled": False})):
            self.web_mod._raw_body = json.dumps({"csrf": service.csrf, "provider_id": unreferenced_id, "confirm": True, **extra}).encode("utf-8")
            resp = await service.handle(action)
            self.assertEqual(resp["status_code"], 200)
            await service.job
            self.assertEqual(service.action_error, "REFERENCE_BLOCKED")
            self.assertFalse(service.result["applied"])
            self.assertIn(unreferenced_id, manager.inst_map)

        # 携带 force_confirm=True 后允许停用与删除无默认引用实例
        self.web_mod._raw_body = json.dumps({
            "csrf": service.csrf, "provider_id": unreferenced_id,
            "confirm": True, "enabled": False, "force_confirm": True,
        }).encode("utf-8")
        resp_dis = await service.handle("provider-toggle")
        self.assertEqual(resp_dis["status_code"], 200)
        await service.job
        self.assertTrue(service.result["applied"])
        self.assertNotIn(unreferenced_id, manager.inst_map)

        self.web_mod._raw_body = json.dumps({
            "csrf": service.csrf, "provider_id": unreferenced_id,
            "confirm": True, "force_confirm": True,
        }).encode("utf-8")
        resp_del = await service.handle("provider-delete")
        self.assertEqual(resp_del["status_code"], 200)
        await service.job
        self.assertTrue(service.result["applied"])
        self.assertFalse(any(r.get("id") == unreferenced_id for r in manager.providers_config))

        # Controlled enable succeeds cleanly on disabled ACP
        self.web_mod._raw_body = json.dumps({"csrf": service.csrf, "provider_id": "acp_disabled", "confirm": True, "enabled": True}).encode("utf-8")
        resp = await service.handle("provider-toggle")
        self.assertEqual(resp["status_code"], 200)
        await service.job
        self.assertTrue(service.result["applied"])
        self.assertIn("acp_disabled", manager.inst_map)

        # 设为默认后，未提供迁移目标时阻止停用/删除；提供 migrate_default_to 后原子迁移并下线
        await select_default(manager, "acp_tools")
        imp_primary = provider_impact(manager, "acp_tools", service.overrides)
        self.assertFalse(imp_primary["can_delete"])
        self.assertTrue(imp_primary["requires_migration"])
        self.assertTrue(any(c["id"] == "acp_disabled" for c in imp_primary["replacement_candidates"]))

        self.web_mod._raw_body = json.dumps({
            "csrf": service.csrf, "provider_id": "acp_tools",
            "confirm": True, "enabled": False, "force_confirm": True,
        }).encode("utf-8")
        await service.handle("provider-toggle")
        await service.job
        self.assertEqual(service.action_error, "REFERENCE_BLOCKED")
        self.assertIn("acp_tools", manager.inst_map)

        self.web_mod._raw_body = json.dumps({
            "csrf": service.csrf, "provider_id": "acp_tools",
            "confirm": True, "enabled": False, "force_confirm": True,
            "migrate_default_to": "acp_disabled",
        }).encode("utf-8")
        await service.handle("provider-toggle")
        await service.job
        self.assertTrue(service.result["applied"])
        self.assertNotIn("acp_tools", manager.inst_map)
        self.assertEqual(manager.acm.default_conf["agent_runner"]["config"]["model"]["provider_id"], "acp_disabled")
        self.assertEqual(routing_snapshot(manager)["resolution_reason"], "configured_primary")

        # 验证 sync_current_provider_pointer 修正重载后漂移的内存指针
        manager.curr_provider_inst = manager.inst_map["zhipu_vlm"]
        self.assertTrue(sync_current_provider_pointer(manager))
        self.assertIs(manager.curr_provider_inst, manager.inst_map["acp_disabled"])
        await select_default(manager, "acp_disabled")

        # Missing confirm or extra field rejected with 400
        self.web_mod._raw_body = json.dumps({"csrf": service.csrf, "provider_id": "acp_disabled", "confirm": False, "enabled": True}).encode("utf-8")
        self.assertEqual((await service.handle("provider-toggle"))["status_code"], 400)
        self.web_mod._raw_body = json.dumps({"csrf": service.csrf, "provider_id": "acp_disabled", "confirm": True, "extra": 1}).encode("utf-8")
        self.assertEqual((await service.handle("provider-default"))["status_code"], 400)

        # Dangling detection: after native delete_provider removes primary without clearing agent_runner,
        # routing_snapshot detects primary_exists=False and implicit_first_provider without fabricating primary.
        await manager.delete_provider(provider_id="acp_disabled")
        dangling_snap = routing_snapshot(manager)
        self.assertEqual(dangling_snap["configured_primary_id"], "acp_disabled")
        self.assertIs(dangling_snap["primary_exists"], False)
        self.assertEqual(dangling_snap["resolution_reason"], "implicit_first_provider")

    async def test_b04_routing_snapshot_states_fallback_order_and_service_observation(self):
        manager = self.Manager(self.conf_file, self._initial_config())

        # 1. explicit_fallback_ids preserve exact order & list invalid fallbacks
        snap = routing_snapshot(manager)
        self.assertEqual(snap["scope"], "global")
        self.assertEqual(snap["configured_primary_id"], "zhipu_vlm")
        self.assertIs(snap["primary_exists"], True)
        self.assertIs(snap["primary_enabled"], True)
        self.assertEqual(snap["resolved_primary_id"], "zhipu_vlm")
        self.assertIs(snap["is_acp"], False)
        self.assertEqual(snap["resolution_reason"], "configured_primary")
        self.assertEqual(snap["explicit_fallback_ids"], ["acp_tools", "missing_fb", "acp_disabled"])
        self.assertEqual(snap["invalid_fallback_ids"], ["missing_fb", "acp_disabled"])
        self.assertIsNone(snap["last_observed_provider_id"])
        self.assertEqual(snap["last_observed_scope"], "unknown")

        # 2. Missing primary + no loaded instances -> missing_primary
        manager.inst_map.clear()
        manager.provider_insts.clear()
        snap_missing = routing_snapshot(manager)
        self.assertEqual(snap_missing["resolution_reason"], "missing_primary")
        self.assertIsNone(snap_missing["resolved_primary_id"])

        # 3. Implicit first provider when primary is disabled/absent
        manager._rebuild_loaded_instances()
        manager.acm.default_conf["agent_runner"]["config"]["model"]["provider_id"] = "acp_disabled"
        snap_implicit = routing_snapshot(manager)
        self.assertIs(snap_implicit["primary_exists"], True)
        self.assertIs(snap_implicit["primary_enabled"], False)
        self.assertEqual(snap_implicit["resolution_reason"], "implicit_first_provider")
        self.assertEqual(snap_implicit["resolved_primary_id"], "zhipu_vlm")

        # 4. Non-local runner -> non_local_runner
        manager.acm.default_conf["agent_runner"]["runner_type"] = "coze"
        self.assertEqual(routing_snapshot(manager)["resolution_reason"], "non_local_runner")

        # 5. Missing/corrupt runner config -> unknown
        manager.acm.default_conf["agent_runner"] = {}
        self.assertEqual(routing_snapshot(manager)["resolution_reason"], "unknown")

        # 6. Only successful sent turn sets service observation; error/not_sent must not overwrite
        tracker = TelemetryTracker(cost_log_enabled=False)
        err_meter = tracker.start_turn(provider="acp_err", session_key_raw="s", mode="chat", model="m", effort="low")
        err_meter.request_sent = True
        err_meter.finish(status="error", error_code="UPSTREAM")
        self.assertIsNone(routing_snapshot(manager)["last_observed_provider_id"])

        ok_meter = tracker.start_turn(provider="acp_tools", session_key_raw="s", mode="tools", model="m", effort="low")
        ok_meter.request_sent = True
        ok_meter.finish(status="ok")
        obs_snap = routing_snapshot(manager)
        self.assertEqual(obs_snap["last_observed_provider_id"], "acp_tools")
        self.assertEqual(obs_snap["last_observed_scope"], "plugin_only")
        self.assertIsNotNone(obs_snap["last_observed_at"])

    def test_dashboard_admin_fails_closed(self):
        manager = types.SimpleNamespace(acm=types.SimpleNamespace(default_conf={"dashboard": {"username": "admin"}}))
        self.assertTrue(dashboard_admin(manager, "admin"))
        for bad in ("", None, "guest", "api_key:admin", "api_key:123"):
            self.assertFalse(dashboard_admin(manager, bad))
        broken = types.SimpleNamespace(acm=types.SimpleNamespace(default_conf={}))
        self.assertFalse(dashboard_admin(broken, "admin"))


if __name__ == "__main__":
    unittest.main()
