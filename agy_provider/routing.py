"""Global local-runner routing and the dashboard's restricted ACP operations."""

import hashlib
import hmac
import secrets
from collections import OrderedDict

from .errors import AgyError


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
                      primary_enabled=bool(row.get("enable")) if row is not None else None,
                      explicit_fallback_ids=list(fallbacks))
        for fid in fallbacks:
            cfg = _row(manager, fid)
            if not cfg or not cfg.get("enable") or manager.inst_map.get(fid) not in manager.provider_insts:
                result["invalid_fallback_ids"].append(fid)
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


async def _select_locked(manager, provider_id):
    from astrbot.core.provider.entities import ProviderType

    config = manager.acm.default_conf
    row = _acp_row(manager, provider_id)
    runner = config["agent_runner"]
    if runner.get("runner_type") != "local":
        raise AgyError("ROUTE_MISMATCH", "当前全局 runner 无法选择本地聊天模型。")
    model = runner["config"]["model"]
    target = manager.inst_map.get(provider_id)
    if (not row.get("enable") or target is None or target not in manager.provider_insts
            or target.provider_config.get("id") != provider_id
            or target.provider_config.get("type", "agy_acp") != "agy_acp"):
        raise AgyError("ROUTE_MISMATCH", "目标 ACP 实例尚未启用并加载。")
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
    return {
        "provider_id": provider_id, "enabled": bool(row.get("enable")),
        "references": hits, "profiles_scanned": len(configs),
        "session_scan": "unknown", "auxiliary_scan": "known_config_fields",
        "can_delete": False, "can_disable": False,
        "block_reason": "referenced" if any(hits.values()) else "incomplete_scan",
    }


async def enable_provider(manager, provider_id, *, expected=None, use_default=False):
    """Check the selected row and perform any enable/selection under one host lock."""
    try:
        async with manager.resource_lock:
            config = manager.acm.default_conf
            row = _acp_row(manager, provider_id)
            if expected is not None and row != expected:
                raise AgyError("ROUTE_MISMATCH", "实例配置已变化，请刷新并重新选择。")
            old = dict(row)
            loaded = manager.inst_map.get(provider_id)
            if loaded is not None and loaded.provider_config.get("type", "agy_acp") != "agy_acp":
                raise AgyError("ROUTE_MISMATCH", "已加载实例与 ACP 配置不匹配。")
            reload_needed = not row.get("enable") or loaded not in manager.provider_insts
            previous_inst = manager.curr_provider_inst
            try:
                if reload_needed:
                    row["enable"] = True
                    config.save_config()
                    await manager.reload(row)
                    if manager.inst_map.get(provider_id) not in manager.provider_insts:
                        raise AgyError("HOST", "宿主没有加载目标实例。")
                elif expected is not None:
                    # A previous native create may have loaded the row before a failed save.
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
