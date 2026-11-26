"""Dashboard-admin snapshots; GET never starts a CLI or queries remote quota."""

import sqlite3
from datetime import datetime, timezone

from .onboarding import PLUGIN_NAME
from .routing import dashboard_admin, routing_snapshot
from .telemetry import daily_snapshot, failure_snapshot


class Monitoring:
    def __init__(self, context, quota=None):
        self.context = context
        self.quota = quota
        self.closed = False
        self.routes = []

    def register(self):
        for resource in ("status", "quota", "daily/30", "daily/90", "daily/365"):
            async def handler(resource=resource):
                return await self.handle(resource)

            route = f"/{PLUGIN_NAME}/monitor/{resource}"
            self.context.register_web_api(route, handler, ["GET"], "AGY 运行概览")
            self.routes.append((route, handler))

    async def handle(self, resource="status"):
        from astrbot.api.web import error_response, json_response, request
        from .provider import instance_monitor_snapshots

        headers = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}
        # AstrBot authenticates the dashboard session before dispatch. Its
        # dashboard has one configured admin username, not a chat-platform ID.
        # Check that identity again; unknown host auth configuration fails closed.
        username = request.username
        if not username:
            return error_response("请先登录 AstrBot 管理面板。", status_code=401, headers=headers)
        manager = self.context.provider_manager
        if not dashboard_admin(manager, username):
            return error_response("仅 AstrBot 面板管理员可查看运行概览。", status_code=403, headers=headers)
        if self.closed:
            return error_response("插件已停用。", status_code=503, headers=headers)
        try:
            if resource == "quota":
                if self.quota is None:
                    return error_response("额度服务尚未就绪。", status_code=503, headers=headers)
                return json_response(self.quota.snapshot(), headers=headers)
            if resource.startswith("daily/"):
                try:
                    payload = daily_snapshot(int(resource.split("/")[1]))
                except (OSError, sqlite3.Error):
                    return error_response("每日统计存储不可用。", status_code=503, headers=headers)
                return json_response(payload, headers=headers)
            # No await within collection: all runtime/telemetry mutations run
            # on the same event loop, so these fields share one consistent view.
            payload = {
                "schema_version": 2,
                "routing": routing_snapshot(manager),
                **failure_snapshot(),
                "sampled_at": datetime.now(timezone.utc).isoformat(),
                "window": {"hours": 24, "max_turns_per_instance": 100},
                "instances": instance_monitor_snapshots(manager),
            }
            return json_response(payload, headers=headers)
        except Exception:
            return error_response("暂时无法读取监控数据。", status_code=500, headers=headers)

    async def close(self):
        self.closed = True
        registered = self.context.registered_web_apis
        registered[:] = [row for row in registered if not any(
            row[0] == route and row[1] is handler for route, handler in self.routes
        )]
        self.routes.clear()
