"""全局本地 runner 路由与面板受限 ACP 管理操作。"""

from copy import deepcopy
import hashlib
import hmac
import secrets
from collections import OrderedDict

from .errors import AgyError

VALID_THOUGHT_LEVELS = ("default", "low", "medium", "high")
VALID_TOOLS_MODES = ("inherit", "chat", "tools")
PROVIDER_TYPE = "agy_acp"
DEFAULT_CONFIG = {
    "id": PROVIDER_TYPE,
    "type": PROVIDER_TYPE,
    "provider": PROVIDER_TYPE,
    "provider_type": "chat_completion",
    "enable": False,
    "key": [""],
    "model": "",
    "modalities": ["text"],
    "custom_extra_body": {
        "agy_thought_level": "default",
        "agy_tools_mode": "inherit",
    },
}


def compute_acp_modalities(settings, tools_mode: str) -> list[str]:
    """根据全局总闸与实例模式统一计算宿主 modalities，绝不包含 audio。"""
    modalities = ["text"]
    if getattr(settings, "enable_tools", False) and tools_mode in {"inherit", "tools"}:
        modalities.append("tool_use")
    if getattr(settings, "enable_images", False):
        modalities.append("image")
    return modalities


def inspect_acp_provider(
    manager,
    config: dict,
    settings,
    *,
    route: dict | None = None,
    source_ids: set[str] | None = None,
) -> dict:
    """按合并后的配置计算 ACP 实例状态与漂移诊断。"""
    merged = manager.get_merged_provider_config(config)
    provider_id = config.get("id")
    model = str(
        merged.get("model")
        or (merged.get("model_config") or {}).get("model")
        or ""
    )
    enabled = bool(merged.get("enable"))
    extra = merged.get("custom_extra_body")
    extra_dict = extra if isinstance(extra, dict) else {}
    raw_effort = extra_dict.get("agy_thought_level", "default")
    raw_mode = extra_dict.get("agy_tools_mode", "inherit")

    errors: list[str] = []
    if not isinstance(raw_effort, str) or raw_effort not in VALID_THOUGHT_LEVELS:
        errors.append("INVALID_THOUGHT_LEVEL")
        thought_level = "invalid"
        effective_thought = settings.thought_level
    else:
        thought_level = raw_effort
        effective_thought = (
            settings.thought_level if thought_level == "default" else thought_level
        )

    if not isinstance(raw_mode, str) or raw_mode not in VALID_TOOLS_MODES:
        errors.append("INVALID_TOOLS_MODE")
        tools_mode = "invalid"
        effective_tools = False
        safe_mode = "inherit"
    else:
        tools_mode = raw_mode
        effective_tools = bool(settings.enable_tools and tools_mode != "chat")
        safe_mode = tools_mode

    raw_modalities = merged.get("modalities")
    modalities = (
        [item for item in raw_modalities if isinstance(item, str)]
        if isinstance(raw_modalities, list)
        else []
    )
    if "audio" in modalities:
        errors.append("UNSUPPORTED_AUDIO_MODALITY")
    expected_modalities = compute_acp_modalities(settings, safe_mode)
    if set(modalities) != set(expected_modalities) or len(modalities) != len(expected_modalities):
        errors.append("MODALITIES_DRIFT")

    if source_ids is not None and merged.get("provider_source_id") not in source_ids:
        errors.append("MISSING_SOURCE")

    inst_map = getattr(manager, "inst_map", {}) or {}
    provider_insts = getattr(manager, "provider_insts", []) or []
    loaded = inst_map.get(provider_id)
    runtime_active = loaded is not None and loaded in provider_insts
    if runtime_active:
        loaded_cfg = getattr(loaded, "provider_config", {}) or {}
        loaded_extra = loaded_cfg.get("custom_extra_body")
        loaded_extra = loaded_extra if isinstance(loaded_extra, dict) else {}
        if (
            loaded_cfg.get("model") != merged.get("model")
            or list(loaded_cfg.get("modalities") or []) != modalities
            or loaded_extra.get("agy_thought_level", "default") != extra_dict.get("agy_thought_level", "default")
            or loaded_extra.get("agy_tools_mode", "inherit") != extra_dict.get("agy_tools_mode", "inherit")
        ):
            errors.append("RUNTIME_CONFIG_DRIFT")

    route_info = route or {}
    primary_id = route_info.get("configured_primary_id")
    fallbacks = route_info.get("explicit_fallback_ids") or []
    return {
        "id": provider_id,
        "model": model,
        "enabled": enabled,
        "thought_level": thought_level,
        "effective_thought": effective_thought,
        "tools_mode": tools_mode,
        "effective_tools": effective_tools,
        "modalities": modalities,
        "expected_modalities": expected_modalities,
        "is_default": bool(primary_id and provider_id == primary_id),
        "in_fallback": provider_id in fallbacks,
        "runtime_active": runtime_active,
        "provider_source_id": merged.get("provider_source_id"),
        "config_drifted": bool(errors),
        "config_errors": errors,
    }


def _merged_enabled(manager, row: dict | None) -> bool:
    if row is None:
        return False
    return bool(manager.get_merged_provider_config(row).get("enable"))


def sync_current_provider_pointer(manager) -> bool:
    """插件热重载后，将内存指针 curr_provider_inst 对齐到当前配置主模型。"""
    try:
        runner = manager.acm.default_conf.get("agent_runner", {})
        if runner.get("runner_type") != "local":
            return False
        primary_id = runner.get("config", {}).get("model", {}).get("provider_id")
        if not isinstance(primary_id, str) or not primary_id:
            return False
        inst = (getattr(manager, "inst_map", None) or {}).get(primary_id)
        insts = getattr(manager, "provider_insts", None) or []
        if inst is None or inst not in insts:
            return False
        manager.curr_provider_inst = inst
        if hasattr(manager, "default_chat_provider_id"):
            manager.default_chat_provider_id = primary_id
        return True
    except (AttributeError, KeyError, TypeError):
        return False


def dashboard_admin(manager, username):
    try:
        admin = manager.acm.default_conf["dashboard"]["username"]
    except (AttributeError, KeyError, TypeError):
        return False
    return (isinstance(username, str) and bool(username)
            and not username.startswith("api_key:") and username == admin)


def _row(manager, provider_id):
    matches = [row for row in manager.acm.default_conf["provider"]
               if isinstance(row, dict) and row.get("id") == provider_id]
    return matches[0] if len(matches) == 1 else None


def _acp_row(manager, provider_id):
    row = _row(manager, provider_id)
    if row is None or manager.get_merged_provider_config(row).get("type") != "agy_acp":
        raise AgyError("CONFIG", "请选择现有的唯一 ACP 实例 ID。")
    return row


def _resolve(manager):
    from astrbot.core.provider.entities import ProviderType

    return manager._resolve_using_provider(ProviderType.CHAT_COMPLETION, None, None)


def routing_snapshot(manager):
    from .telemetry import last_service_observation

    result = {
        "scope": "global", "configured_primary_id": None, "primary_exists": None,
        "primary_enabled": None, "resolved_primary_id": None, "is_acp": None,
        "resolution_reason": "unknown", "explicit_fallback_ids": [], "invalid_fallback_ids": [],
        "non_default_profile_overrides": 0,
        **last_service_observation(),
    }
    try:
        runner = manager.acm.default_conf["agent_runner"]
        if not runner.get("runner_type"):
            return result
        if runner["runner_type"] != "local":
            result["resolution_reason"] = "non_local_runner"
            return result
        model = runner["config"]["model"]
        primary = model.get("provider_id") or None
        fallbacks = model.get("fallback_provider_ids", [])
        if (primary is not None and not isinstance(primary, str)
                or not isinstance(fallbacks, list) or not all(isinstance(i, str) for i in fallbacks)):
            return result
        row = _row(manager, primary) if primary else None
        result.update(configured_primary_id=primary, primary_exists=row is not None,
                      primary_enabled=_merged_enabled(manager, row) if row is not None else None,
                      explicit_fallback_ids=list(fallbacks))
        for fid in fallbacks:
            cfg = _row(manager, fid)
            if not cfg or not _merged_enabled(manager, cfg) or manager.inst_map.get(fid) not in manager.provider_insts:
                result["invalid_fallback_ids"].append(fid)
        profiles = getattr(manager.acm, "confs", {})
        if isinstance(profiles, dict):
            overrides = 0
            for prof in profiles.values():
                if not isinstance(prof, dict) or prof is manager.acm.default_conf:
                    continue
                prof_runner = prof.get("agent_runner", {})
                if prof_runner.get("runner_type") == "local":
                    prof_pid = prof_runner.get("config", {}).get("model", {}).get("provider_id") or None
                    if prof_pid != primary:
                        overrides += 1
            result["non_default_profile_overrides"] = overrides
        inst = _resolve(manager)
        if inst is None:
            result["resolution_reason"] = "missing_primary"
        else:
            actual = inst.provider_config["id"]
            actual_row = _row(manager, actual)
            adapter_type = inst.provider_config.get("type")
            if not adapter_type and actual_row is not None:
                adapter_type = manager.get_merged_provider_config(actual_row).get("type")
            result.update(resolved_primary_id=actual,
                          resolution_reason="configured_primary" if primary == actual else "implicit_first_provider",
                          is_acp=adapter_type == "agy_acp" if adapter_type else None)
    except (AttributeError, KeyError, TypeError, ValueError, ImportError):
        pass
    return result


async def _select_locked(manager, provider_id, *, acp_only=True):
    from astrbot.core.provider.entities import ProviderType

    config = manager.acm.default_conf
    row = _acp_row(manager, provider_id) if acp_only else _row(manager, provider_id)
    if row is None:
        raise AgyError("CONFIG", "目标实例不存在或 ID 不唯一。")
    runner = config["agent_runner"]
    if runner.get("runner_type") != "local":
        raise AgyError("ROUTE_MISMATCH", "当前全局 runner 无法选择本地聊天模型。")
    model = runner["config"]["model"]
    target = manager.inst_map.get(provider_id)
    is_acp = manager.get_merged_provider_config(row).get("type") == "agy_acp"
    if (not _merged_enabled(manager, row) or target is None or target not in manager.provider_insts
            or target.provider_config.get("id") != provider_id
            or (acp_only and not is_acp)
            or (acp_only and target.provider_config.get("type", "agy_acp") != "agy_acp")):
        raise AgyError("ROUTE_MISMATCH", "目标 ACP 实例尚未启用并加载。" if acp_only else "目标替代实例尚未启用并加载。")
    previous = model.get("provider_id")
    had_previous = "provider_id" in model
    previous_inst = manager.curr_provider_inst

    def verify():
        live = manager.acm.get_conf(None)["agent_runner"]
        if (live.get("runner_type") != "local"
                or live["config"]["model"].get("provider_id") != provider_id
                or _resolve(manager) is not target):
            raise AgyError("ROUTE_MISMATCH", "全局主 ID 或宿主解析结果未匹配目标实例。")

    try:
        model["provider_id"] = provider_id
        config.save_config()
        verify()
        await manager.set_provider(provider_id, ProviderType.CHAT_COMPLETION)
        if manager.curr_provider_inst is not target:
            raise AgyError("HOST", "宿主未同步全局聊天模型偏好。")
        verify()
    except BaseException:
        if had_previous:
            model["provider_id"] = previous
        else:
            model.pop("provider_id", None)
        try:
            config.save_config()
        finally:
            if manager.curr_provider_inst is not previous_inst:
                if previous_inst is None:
                    manager.curr_provider_inst = None
                else:
                    await manager.set_provider(previous_inst.provider_config["id"], ProviderType.CHAT_COMPLETION)
        raise
    if hasattr(manager, "default_chat_provider_id"):
        manager.default_chat_provider_id = provider_id


async def select_default(manager, provider_id):
    try:
        async with manager.resource_lock:
            await _select_locked(manager, provider_id)
    except AgyError:
        raise
    except Exception:
        raise AgyError("HOST", "宿主保存或回读失败，请核对全局主模型和实例状态。") from None


class OverrideObservations:
    """Bounded counts from native change notifications; old preferences remain unknown."""

    def __init__(self):
        self.secret = secrets.token_bytes(32)
        self.rows = OrderedDict()

    def changed(self, provider_id, provider_type, umo):
        if isinstance(umo, str) and umo and getattr(provider_type, "value", "") == "chat_completion":
            tag = hmac.digest(self.secret, umo.encode(), hashlib.sha256)
            self.rows[tag] = provider_id
            self.rows.move_to_end(tag)
            if len(self.rows) > 1024:
                self.rows.popitem(last=False)


def _aux_refs(config, target):
    count = 0
    if isinstance(config, list):
        return sum(_aux_refs(item, target) for item in config if isinstance(item, (list, dict)))
    if isinstance(config, dict):
        for key, value in config.items():
            if key in {"provider_id", "fallback_provider_ids"} or key.endswith(("_provider_id", "_provider_ids")):
                count += int(value == target or isinstance(value, list) and target in value)
            elif isinstance(value, (list, dict)):
                count += _aux_refs(value, target)
    return count


def _replacement_candidates(manager, exclude_id: str) -> list[dict]:
    """列出可接替全局默认的已启用且已加载聊天模型。"""
    candidates = []
    inst_map = getattr(manager, "inst_map", {}) or {}
    insts = getattr(manager, "provider_insts", []) or []
    for row in list(manager.acm.default_conf.get("provider", [])):
        if not isinstance(row, dict):
            continue
        pid = row.get("id")
        if not pid or pid == exclude_id:
            continue
        merged = manager.get_merged_provider_config(row)
        if merged.get("provider_type", "chat_completion") != "chat_completion":
            continue
        if not merged.get("enable"):
            continue
        loaded = inst_map.get(pid)
        if loaded is None or loaded not in insts:
            continue
        extra = merged.get("custom_extra_body") if isinstance(merged.get("custom_extra_body"), dict) else {}
        candidates.append({
            "id": pid,
            "model": str(merged.get("model") or (merged.get("model_config") or {}).get("model") or pid),
            "is_acp": merged.get("type") == "agy_acp",
            "thought_level": extra.get("agy_thought_level", "default") if merged.get("type") == "agy_acp" else None,
            "tools_mode": extra.get("agy_tools_mode", "inherit") if merged.get("type") == "agy_acp" else None,
        })
    return candidates


def provider_impact(manager, provider_id, observations):
    row = _acp_row(manager, provider_id)
    conf = manager.acm.default_conf
    profiles = getattr(manager.acm, "confs", {})
    configs = [conf]
    if isinstance(profiles, dict):
        configs.extend(c for c in profiles.values() if isinstance(c, dict) and c is not conf)
    hits = {"primary": 0, "fallback": 0, "auxiliary": 0}
    for config in configs:
        runner = config.get("agent_runner", {}).get("config", {})
        model = runner.get("model", {})
        primary = int(model.get("provider_id") == provider_id)
        fallback = int(provider_id in (model.get("fallback_provider_ids") or []))
        hits["primary"] += primary
        hits["fallback"] += fallback
        hits["auxiliary"] += _aux_refs(runner, provider_id) - primary - fallback
        for key, section in config.items():
            if key.startswith("provider_") and key.endswith("_settings") or key == "provider_settings":
                hits["auxiliary"] += _aux_refs(section, provider_id)
    hits["observed_session_overrides"] = sum(v == provider_id for v in observations.rows.values())
    route = routing_snapshot(manager)
    hits["global_resolved"] = (route["resolved_primary_id"] == provider_id
                               if route["resolution_reason"] not in {"unknown", "non_local_runner"} else None)
    requires_migration = bool(hits["primary"] or hits["global_resolved"])
    if requires_migration:
        block_reason = "requires_migration"
    elif any(hits.values()):
        block_reason = "referenced"
    else:
        block_reason = "incomplete_scan"
    return {
        "provider_id": provider_id, "enabled": _merged_enabled(manager, row),
        "references": hits, "profiles_scanned": len(configs),
        "non_default_profile_overrides": route.get("non_default_profile_overrides", 0),
        "session_scan": "unknown", "auxiliary_scan": "known_config_fields",
        "requires_migration": requires_migration,
        "replacement_candidates": _replacement_candidates(manager, provider_id),
        "can_delete": not requires_migration, "can_disable": not requires_migration,
        "can_confirm_offboard": True,
        "block_reason": block_reason,
    }


async def enable_provider(manager, provider_id, *, expected=None, use_default=False, modalities=None):
    """在单把宿主锁内完成 ACP 实例启用与可选的默认路由切换。"""
    try:
        async with manager.resource_lock:
            config = manager.acm.default_conf
            row = _acp_row(manager, provider_id)
            if expected is not None and row != expected:
                raise AgyError("ROUTE_MISMATCH", "实例配置已变化，请刷新并重新选择。")
            old = deepcopy(row)
            loaded = manager.inst_map.get(provider_id)
            if loaded is not None and loaded.provider_config.get("type", "agy_acp") != "agy_acp":
                raise AgyError("ROUTE_MISMATCH", "已加载实例与 ACP 配置不匹配。")
            sync_mod = modalities is not None and row.get("modalities") != list(modalities)
            reload_needed = not _merged_enabled(manager, row) or loaded not in manager.provider_insts or sync_mod
            previous_inst = manager.curr_provider_inst
            try:
                if reload_needed:
                    row["enable"] = True
                    if modalities is not None:
                        row["modalities"] = list(modalities)
                    config.save_config()
                    await manager.reload(row)
                    if manager.inst_map.get(provider_id) not in manager.provider_insts:
                        raise AgyError("HOST", "宿主没有加载目标实例。")
                elif expected is not None:
                    # 之前原生创建未落盘时，显式重新保存一次配置。
                    config.save_config()
                if use_default:
                    await _select_locked(manager, provider_id)
            except BaseException:
                if reload_needed:
                    row.clear()
                    row.update(old)
                    config.save_config()
                    if loaded is None:
                        async with manager.reload_lock:
                            await manager.terminate_provider(provider_id)
                    else:
                        await manager.reload(row)
                    if previous_inst is None or previous_inst in manager.provider_insts:
                        manager.curr_provider_inst = previous_inst
                raise
    except AgyError:
        raise
    except Exception:
        raise AgyError("HOST", "宿主保存或加载失败，请核对实例和路由。") from None


async def _prepare_offboard_locked(manager, provider_id, migrate_default_to, force_confirm, observations):
    """下线或删除前的引用迁移与校验，返回回滚状态。"""
    impact = provider_impact(manager, provider_id, observations)
    is_primary = impact["requires_migration"]
    config = manager.acm.default_conf
    runner = config.get("agent_runner", {})
    model_cfg = runner.get("config", {}).get("model", {}) if runner.get("runner_type") == "local" else {}
    had_primary = "provider_id" in model_cfg
    prev_primary = model_cfg.get("provider_id")
    had_fallbacks = "fallback_provider_ids" in model_cfg
    prev_fallbacks = deepcopy(model_cfg.get("fallback_provider_ids"))
    prev_inst = manager.curr_provider_inst
    prev_default_attr = getattr(manager, "default_chat_provider_id", None)

    if is_primary:
        if isinstance(migrate_default_to, str) and migrate_default_to:
            if migrate_default_to == provider_id:
                raise AgyError("CONFIG", "不能将默认模型迁移到正在停用或删除的实例。")
            await _select_locked(manager, migrate_default_to, acp_only=False)
        elif migrate_default_to == "" and force_confirm:
            if isinstance(model_cfg, dict):
                model_cfg.pop("provider_id", None)
                if hasattr(manager, "default_chat_provider_id"):
                    manager.default_chat_provider_id = ""
        else:
            raise AgyError("REFERENCE_BLOCKED", "该实例为全局默认模型，请先选择替代默认模型。")

    refs = impact["references"]
    if (refs["fallback"] or refs["auxiliary"] or refs["observed_session_overrides"]) and not force_confirm:
        raise AgyError("REFERENCE_BLOCKED", "实例仍存在备用链、辅助配置或会话引用，请先确认影响。")
    if not force_confirm and not is_primary:
        raise AgyError("REFERENCE_BLOCKED", "请查看影响预览并确认操作。")

    if force_confirm and isinstance(model_cfg.get("fallback_provider_ids"), list):
        model_cfg["fallback_provider_ids"] = [
            fid for fid in model_cfg["fallback_provider_ids"] if fid != provider_id
        ]

    async def rollback_route():
        if isinstance(model_cfg, dict):
            if had_primary:
                model_cfg["provider_id"] = prev_primary
            else:
                model_cfg.pop("provider_id", None)
            if had_fallbacks:
                model_cfg["fallback_provider_ids"] = prev_fallbacks
            else:
                model_cfg.pop("fallback_provider_ids", None)
        if hasattr(manager, "default_chat_provider_id") and prev_default_attr is not None:
            manager.default_chat_provider_id = prev_default_attr
        if manager.curr_provider_inst is not prev_inst:
            if prev_inst is None:
                manager.curr_provider_inst = None
            else:
                from astrbot.core.provider.entities import ProviderType

                prev_id = prev_inst.provider_config.get("id")
                if prev_id in manager.inst_map:
                    await manager.set_provider(prev_id, ProviderType.CHAT_COMPLETION)

    return rollback_route


async def disable_provider(
    manager,
    provider_id: str,
    *,
    migrate_default_to: str | None = None,
    force_confirm: bool = False,
    observations=None,
):
    """受控停用 ACP 实例：必要时在同一锁内先迁移默认模型与清理备用引用。"""
    obs = observations if observations is not None else OverrideObservations()
    try:
        async with manager.resource_lock:
            config = manager.acm.default_conf
            row = _acp_row(manager, provider_id)
            old = deepcopy(row)
            rollback_route = await _prepare_offboard_locked(
                manager, provider_id, migrate_default_to, force_confirm, obs
            )
            try:
                row["enable"] = False
                config.save_config()
                await manager.reload(row)
            except BaseException:
                row.clear()
                row.update(old)
                await rollback_route()
                config.save_config()
                await manager.reload(row)
                raise
    except AgyError:
        raise
    except Exception:
        raise AgyError("HOST", "停用实例失败，请核对宿主配置和默认路由。") from None


async def delete_acp_provider(
    manager,
    provider_id: str,
    *,
    migrate_default_to: str | None = None,
    force_confirm: bool = False,
    observations=None,
):
    """受控删除 ACP 实例：在同一锁内先迁移默认模型并清理配置。"""
    obs = observations if observations is not None else OverrideObservations()
    try:
        async with manager.resource_lock:
            config = manager.acm.default_conf
            row = _acp_row(manager, provider_id)
            providers = config["provider"]
            idx = providers.index(row)
            old_row = deepcopy(row)
            rollback_route = await _prepare_offboard_locked(
                manager, provider_id, migrate_default_to, force_confirm, obs
            )
            try:
                providers.pop(idx)
                config.save_config()
                await manager.terminate_provider(provider_id)
                manager.providers_config = providers
            except BaseException:
                if row not in providers:
                    providers.insert(idx, old_row)
                await rollback_route()
                config.save_config()
                manager.providers_config = providers
                if _merged_enabled(manager, old_row):
                    await manager.reload(old_row)
                raise
    except AgyError:
        raise
    except Exception:
        raise AgyError("HOST", "删除实例失败，请核对宿主配置和默认路由。") from None


async def update_acp_provider(
    manager,
    provider_id: str,
    *,
    model: str,
    effort: str,
    tools_mode: str,
    settings,
    source_id: str | None = None,
) -> bool:
    """就地编辑 ACP 实例：严格保留原 provider_id，并重算 modalities 后热重载。"""
    if not isinstance(model, str) or not model.strip() or len(model) > 1024:
        raise AgyError("CONFIG", "模型 ID 无效。")
    if effort not in VALID_THOUGHT_LEVELS:
        raise AgyError("CONFIG", "思考强度应为 default/low/medium/high。")
    if tools_mode not in VALID_TOOLS_MODES:
        raise AgyError("CONFIG", "工具模式应为 inherit/chat/tools。")
    try:
        async with manager.resource_lock:
            config = manager.acm.default_conf
            row = _acp_row(manager, provider_id)
            old = deepcopy(row)
            merged = manager.get_merged_provider_config(row)
            old_model = str(merged.get("model") or (merged.get("model_config") or {}).get("model") or "")
            model_changed = old_model != model
            extra = deepcopy(row.get("custom_extra_body") if isinstance(row.get("custom_extra_body"), dict) else {})
            extra["agy_thought_level"] = effort
            extra["agy_tools_mode"] = tools_mode
            try:
                row["model"] = model
                row["custom_extra_body"] = extra
                row["modalities"] = compute_acp_modalities(settings, tools_mode)
                if source_id:
                    sources = config.get("provider_sources") or []
                    source_ids = {s.get("id") for s in sources if isinstance(s, dict) and s.get("id")}
                    if row.get("provider_source_id") not in source_ids:
                        row["provider_source_id"] = source_id
                config.save_config()
                await manager.reload(row)
                manager.providers_config = config["provider"]
            except BaseException:
                row.clear()
                row.update(old)
                config.save_config()
                await manager.reload(row)
                raise
            return model_changed
    except AgyError:
        raise
    except Exception:
        raise AgyError("HOST", "更新实例配置失败，请核对宿主配置。") from None


async def repair_acp_providers(
    manager,
    settings,
    *,
    provider_id: str | None = None,
    source_id: str | None = None,
) -> list[str]:
    """一键修复失真配置：清理无效思考/模式/audio 模态，重新对齐全局开关并绑定来源。"""
    repaired_ids: list[str] = []
    try:
        async with manager.resource_lock:
            config = manager.acm.default_conf
            providers = config.get("provider", [])
            sources = config.get("provider_sources") or []
            source_ids = {s.get("id") for s in sources if isinstance(s, dict) and s.get("id")}
            if provider_id is not None:
                targets = [_acp_row(manager, provider_id)]
            else:
                targets = [
                    row for row in providers
                    if isinstance(row, dict)
                    and manager.get_merged_provider_config(row).get("type") == "agy_acp"
                ]
            snapshots: list[tuple[dict, dict]] = []
            for row in targets:
                merged = manager.get_merged_provider_config(row)
                extra = deepcopy(row.get("custom_extra_body") if isinstance(row.get("custom_extra_body"), dict) else {})
                merged_extra = merged.get("custom_extra_body") if isinstance(merged.get("custom_extra_body"), dict) else {}
                raw_effort = extra.get("agy_thought_level", merged_extra.get("agy_thought_level", "default"))
                raw_mode = extra.get("agy_tools_mode", merged_extra.get("agy_tools_mode", "inherit"))
                effort = raw_effort if isinstance(raw_effort, str) and raw_effort in VALID_THOUGHT_LEVELS else "default"
                tools_mode = raw_mode if isinstance(raw_mode, str) and raw_mode in VALID_TOOLS_MODES else "inherit"
                expected_mods = compute_acp_modalities(settings, tools_mode)
                needs_source = bool(source_id and row.get("provider_source_id") not in source_ids)
                loaded = (getattr(manager, "inst_map", None) or {}).get(row.get("id"))
                runtime_drifted = False
                if loaded is not None:
                    lcfg = getattr(loaded, "provider_config", {}) or {}
                    lextra = lcfg.get("custom_extra_body") if isinstance(lcfg.get("custom_extra_body"), dict) else {}
                    runtime_drifted = (
                        list(lcfg.get("modalities") or []) != expected_mods
                        or lextra.get("agy_thought_level", "default") != effort
                        or lextra.get("agy_tools_mode", "inherit") != tools_mode
                    )
                if (
                    extra.get("agy_thought_level") != effort
                    or extra.get("agy_tools_mode") != tools_mode
                    or list(row.get("modalities") or []) != expected_mods
                    or needs_source
                    or runtime_drifted
                ):
                    snapshots.append((row, deepcopy(row)))
                    extra["agy_thought_level"] = effort
                    extra["agy_tools_mode"] = tools_mode
                    row["custom_extra_body"] = extra
                    row["modalities"] = expected_mods
                    if needs_source:
                        row["provider_source_id"] = source_id
                    repaired_ids.append(row["id"])
            if not snapshots:
                return []
            try:
                config.save_config()
                for row, _ in snapshots:
                    await manager.reload(row)
                manager.providers_config = providers
            except BaseException:
                for row, old in snapshots:
                    row.clear()
                    row.update(old)
                config.save_config()
                for row, _ in snapshots:
                    await manager.reload(row)
                raise
            return repaired_ids
    except AgyError:
        raise
    except Exception:
        raise AgyError("HOST", "同步修复配置失败，请核对宿主配置。") from None
