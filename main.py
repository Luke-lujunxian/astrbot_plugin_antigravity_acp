"""Register only while the plugin is enabled; own no global CLI credentials."""

import asyncio
import sqlite3
from copy import deepcopy

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register
from astrbot.core.provider import register as registry

from .agy_provider._version import PLUGIN_VERSION
from .agy_provider.admin_commands import (
    HELP,
    admin_command,
    doctor_text,
    models_text,
    quota_text,
    setup_text,
    status_text,
    usage_text,
    use_text,
)
from .agy_provider.config import Settings
from .agy_provider.errors import AgyError
from .agy_provider.host_compat import install_host_compat, uninstall_host_compat
from .agy_provider.onboarding import Onboarding, ensure_provider_source, next_step
from .agy_provider.monitoring import Monitoring
from .agy_provider.routing import (
    compute_acp_modalities,
    routing_snapshot,
    sync_current_provider_pointer,
)
from .agy_provider.paths import cleanup_stale_dirs, plugin_data_root
from .agy_provider.provider import (
    DEFAULT_CONFIG,
    OWNER,
    PROVIDER_TYPE,
    AgyProvider,
    active_instances,
    configure,
    instance_cost_snapshots,
    terminate_all,
)
from .agy_provider.telemetry import daily_snapshot, format_cost_report, start_diagnostics, stop_diagnostics

RESTORE_IDS = "_sl251_agy_provider_restore_ids"


class BareAgyCommand(filter.CustomFilter):
    def filter(self, event, cfg):
        return event.is_at_or_wake_command and event.message_str.strip() == "agy"


class AgySubcommands(BareAgyCommand):
    def filter(self, event, cfg):
        return not super().filter(event, cfg)


def unregister_owned_adapter() -> None:
    meta = registry.provider_cls_map.get(PROVIDER_TYPE)
    if meta is None:
        return
    if getattr(meta.cls_type, "agy_plugin_owner", None) != OWNER:
        raise RuntimeError("agy_acp 已被其他插件注册，请先解决 provider 名称冲突。")
    registry.provider_cls_map.pop(PROVIDER_TYPE)
    registry.provider_registry[:] = [
        item for item in registry.provider_registry if item is not meta
    ]


@register(
    "astrbot_plugin_antigravity_acp",
    "sl251",
    "通过本机 AGY ACP 使用 Gemini 模型",
    PLUGIN_VERSION,
    "https://github.com/sl251/astrbot_plugin_antigravity_acp",
)
class AgyProviderPlugin(Star):
    def __init__(self, context: Context, config=None):
        super().__init__(context)
        self.config = config if config is not None else {}
        self.registered = False
        self.doctor_lock = asyncio.Lock()
        self.doctor_task = None
        self.cleanup_task = None
        self.stopping = False
        self.setup_service = None
        self.monitor_service = None

    # AstrBot checks group custom filters before it generates the bare command tree.
    @filter.custom_filter(AgySubcommands)
    @filter.command_group("agy")
    async def agy(self, event: AstrMessageEvent):
        pass

    @filter.custom_filter(BareAgyCommand)
    @admin_command
    async def agy_root(self, event: AstrMessageEvent):
        yield event.plain_result(HELP)

    @agy.command("setup")
    @admin_command
    async def setup(self, event: AstrMessageEvent):
        if self.stopping or self.setup_service is None:
            yield event.plain_result("AGY 插件尚未就绪，请启用后重试。")
            return
        service = self.setup_service
        busy = service.busy or service.login.busy
        yield event.plain_result(setup_text(busy, next_step(service.report), service.providers()))

    @agy.command("use")
    @admin_command
    async def use(self, event: AstrMessageEvent, provider_id: str = ""):
        service = self.setup_service
        if self.stopping or service is None:
            yield event.plain_result("AGY 插件尚未就绪。")
            return
        try:
            service._available()
            allowed = {row["id"]: row for row in service.providers() if row["enabled"]}
            if provider_id not in allowed:
                raise AgyError("CONFIG", "请指定已启用的模型实例 ID（可用 /agy models 查看）。")
            from astrbot.core.provider.entities import ProviderType

            await self.context.provider_manager.set_provider(
                provider_id, ProviderType.CHAT_COMPLETION, event.unified_msg_origin
            )
            yield event.plain_result(use_text(provider_id, allowed[provider_id]))
        except AgyError as exc:
            yield event.plain_result(str(exc))
        except Exception:
            yield event.plain_result("AGY 模型切换失败，请检查模型是否已启用，或重新运行首次设置。")

    @agy.command("cost")
    @admin_command
    async def cost(self, event: AstrMessageEvent):
        if self.stopping:
            yield event.plain_result("AGY [CLOSED] 插件正在停用，无法读取成本统计。")
            return
        settings = (
            self.setup_service.settings
            if self.setup_service is not None
            else Settings.from_dict(self.config)
        )
        settings_summary = {
            "session_reuse_mode": settings.session_reuse_mode,
            "history_bytes": settings.history_bytes,
            "enable_tools": settings.enable_tools,
            "cost_log_enabled": settings.cost_log_enabled,
            "empty_dedupe_ttl": settings.empty_dedupe_ttl,
            "quota_cooldown": settings.quota_cooldown,
        }
        yield event.plain_result(
            format_cost_report(instance_cost_snapshots(), settings_summary)
        )

    @agy.command("doctor")
    @admin_command
    async def doctor(self, event: AstrMessageEvent):
        if self.stopping:
            yield event.plain_result("AGY [CLOSED] 插件正在停用，请启用后再自检。")
            return
        if self.doctor_lock.locked():
            yield event.plain_result("AGY [BUSY] 自检正在运行，请稍后再试。")
            return
        async with self.doctor_lock:
            try:
                if self.setup_service is None:
                    raise AgyError("CLOSED", "首次设置服务尚未就绪。")
                self.setup_service.start_check()
            except AgyError as exc:
                yield event.plain_result(str(exc))
                return
            self.doctor_task = self.setup_service.job
            try:
                await asyncio.shield(self.doctor_task)
                report = {
                    key: value for key, value in self.setup_service.report.items()
                    if key not in {"models", "efforts", "selected_model"}
                }
                report["routing"] = routing_snapshot(self.context.provider_manager)
            finally:
                self.doctor_task = None
        yield event.plain_result(doctor_text(report, next_step(report)))

    @agy.command("help")
    @admin_command
    async def help(self, event: AstrMessageEvent):
        yield event.plain_result(HELP)

    @agy.command("quota")
    @admin_command
    async def quota(self, event: AstrMessageEvent):
        service = self.setup_service
        if self.stopping or service is None:
            yield event.plain_result("AGY 插件尚未就绪。")
        elif service.login.busy:
            yield event.plain_result("登录中，请稍后查询额度。")
        else:
            try:
                message = quota_text(await service.quota.refresh())
            except AgyError as exc:
                if exc.code != "CLOSED":
                    raise
                message = str(exc)
            yield event.plain_result(message)

    @agy.command("status")
    @admin_command
    async def status(self, event: AstrMessageEvent):
        if self.stopping or self.setup_service is None:
            yield event.plain_result("AGY 插件尚未就绪。")
            return
        yield event.plain_result(status_text(PLUGIN_VERSION, instance_cost_snapshots()))

    @agy.command("models")
    @admin_command
    async def models(self, event: AstrMessageEvent):
        if self.stopping or self.setup_service is None:
            yield event.plain_result("AGY 插件尚未就绪。")
            return
        yield event.plain_result(models_text(self.setup_service.providers()))

    @agy.command("usage")
    @admin_command
    async def usage(self, event: AstrMessageEvent, days: str = "90"):
        if self.stopping:
            yield event.plain_result("AGY 插件正在停用。")
            return
        if days not in ("30", "90", "365"):
            yield event.plain_result("用法：/agy usage [30|90|365]")
            return
        try:
            message = usage_text(daily_snapshot(int(days)))
        except (OSError, sqlite3.Error):
            message = "每日统计存储不可用。"
        yield event.plain_result(message)

    async def initialize(self):
        repairs = {}
        settings = Settings.from_dict(self.config, on_repair=repairs.__setitem__)
        if repairs:
            self.config.update(repairs)
            for key, value in repairs.items():
                logger.warning("AGY 配置 %s 无效或与其他预算冲突，已恢复为 %s。", key, value)
            try:
                if hasattr(self.config, "save_config"):
                    self.config.save_config()
            except Exception:
                logger.warning("AGY 修正配置写盘失败；本次使用修正值，请在插件配置页重新保存。")
        configure(settings)
        unregister_owned_adapter()
        template = deepcopy(DEFAULT_CONFIG)
        template["modalities"] = compute_acp_modalities(settings, "inherit")
        registry.register_provider_adapter(
            PROVIDER_TYPE,
            "本机官方 AGY CLI / ACP Gemini 模型（支持 custom_extra_body.agy_tools_mode=inherit|chat|tools）",
            default_config_tmpl=template,
            provider_display_name="AGY Gemini (ACP)",
        )(AgyProvider)
        self.registered = True
        try:
            install_host_compat(owner=OWNER, logger=logger)
        except Exception:
            unregister_owned_adapter()
            self.registered = False
            raise
        manager = self.context.provider_manager
        if any(manager.get_merged_provider_config(config).get("type") == PROVIDER_TYPE
               for config in manager.providers_config):
            try:
                await ensure_provider_source(manager)
            except Exception:
                logger.warning("AGY 模型来源关联保存失败；已有模型仍可使用，请在插件面板重新保存模型。")
        data_root = plugin_data_root()
        start_diagnostics(data_root)
        # Startup: ProviderManager.initialize follows plugin initialization.
        # Hot reload / re-enable: restore only instances this plugin removed.
        restore_ids = getattr(manager, RESTORE_IDS, set())
        for config in list(manager.providers_config):
            if config.get("id") in restore_ids and config.get("enable"):
                merged = manager.get_merged_provider_config(config)
                if merged.get("type") == PROVIDER_TYPE:
                    try:
                        await manager.reload(config)
                    except Exception:
                        logger.error("AGY provider 重载失败，请在模型设置重新启用。")
        setattr(manager, RESTORE_IDS, set())
        sync_current_provider_pointer(manager)
        logger.info(
            "已注册 agy_acp。打开插件详情 → 首次设置，或发送 /agy setup 开始引导。"
        )
        self.stopping = False
        self.setup_service = Onboarding(self.context, settings, self.config)
        if warning := self.setup_service.command_scope_warning():
            logger.warning(warning)
        self.setup_service.register()
        self.monitor_service = Monitoring(self.context, self.setup_service.quota)
        self.monitor_service.register()
        active_names = {inst.runtime.root.name for inst in active_instances()}
        self.cleanup_task = asyncio.create_task(
            asyncio.to_thread(cleanup_stale_dirs, data_root, active_names=active_names),
            name="agy:stale-cleanup",
        )
        if settings.setup_auto_check:
            self.setup_service.start_check()

    async def terminate(self):
        self.stopping = True
        if self.cleanup_task:
            self.cleanup_task.cancel()
            await asyncio.gather(self.cleanup_task, return_exceptions=True)
            self.cleanup_task = None
        if self.monitor_service:
            await self.monitor_service.close()
        if self.setup_service:
            await self.setup_service.close()
        if self.doctor_task:
            self.doctor_task.cancel()
            await asyncio.gather(self.doctor_task, return_exceptions=True)
        if not self.registered:
            return
        try:
            manager = self.context.provider_manager
            restore_ids = set(getattr(manager, RESTORE_IDS, set()))
            async with manager.reload_lock:
                for provider_id, provider in list(manager.inst_map.items()):
                    if getattr(provider, "agy_plugin_owner", None) == OWNER:
                        restore_ids.add(provider_id)
                        await manager.terminate_provider(provider_id)
            setattr(manager, RESTORE_IDS, restore_ids)
            await terminate_all()
        finally:
            stop_diagnostics()
            uninstall_host_compat()
            unregister_owned_adapter()
            self.registered = False
