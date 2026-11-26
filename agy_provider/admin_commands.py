"""Chat authorization runs after command matching, before reading plugin state."""

from datetime import date, timedelta
from functools import wraps

HELP = """AGY 管理员指令
/agy setup　设置入口
/agy use <提供商 ID>　切换当前会话模型
/agy cost　近期成本与复用
/agy doctor　无生成自检
/agy quota　查询账号额度
/agy status　查看运行状态
/agy models　查看已配置模型
/agy usage [30|90|365]　查看本地每日用量
/agy help　显示此帮助"""


def admin_command(handler):
    @wraps(handler)
    async def checked(plugin, event, *args, **kwargs):
        # In 4.29.4 ProcessStage requires "not event.call_llm" to dispatch.
        event.should_call_llm(True)
        if not event.is_admin():
            try:
                await event.send(event.plain_result("AGY [FORBIDDEN] 仅管理员可使用此指令。"))
            finally:
                event.stop_event()
            return
        async for result in handler(plugin, event, *args, **kwargs):
            yield result
    return checked


def quota_text(data):
    lines = ["AGY 账号额度"]
    if data["error"]:
        lines.append(data["error"]["message"])
    if data["fetched_at"]:
        lines.append(("过期数据 · " if data["stale"] else "采集于 ") + data["fetched_at"])
    for group in data["groups"]:
        lines.append(group["name"])
        for bucket in group["buckets"]:
            reset = bucket["reset_time"] or "不适用"
            lines.append(f"  {bucket['window']} 剩余 {bucket['remaining_fraction']:.1%}，重置 {reset}")
    return "\n".join(lines)


def usage_text(data):
    days = data["days"]
    if not days:
        return "所选区间没有本地用量记录。"
    def known(key):
        counts = [day[key] for day in days if day[key] is not None]
        return sum(counts) if counts else "未知"
    lines = [f"AGY 插件本地用量 · 近 {data['range']['days']} 天",
             f"{len(days)} 个有记录日，{known('requests')} 轮（成功 {known('success')}，失败 {known('failed')}）",
             f"已知输入 {known('input_tokens')}，输出 {known('output_tokens')}，合计 {known('total_tokens')} Token",
             f"缺少用量的轮次 {known('usage_unknown_turns')}"]
    end = date.fromisoformat(data["range"]["end"])
    indexed = {row["date"]: row for row in days}
    cells = []
    for offset in range(27, -1, -1):
        key = (end - timedelta(days=offset)).isoformat()
        row = indexed.get(key)
        if row is None:
            cell = "·"
        elif row["total_tokens"] is None or (row["usage_unknown_turns"] and row["total_tokens"] == 0):
            cell = "?"
        elif row["total_tokens"] == 0:
            cell = "0"
        elif row["total_tokens"] < 1000:
            cell = "░"
        elif row["total_tokens"] < 10000:
            cell = "▒"
        else:
            cell = "▓"
        cells.append(cell)
    lines.extend(["近 28 日本地 Token，左早右晚", "".join(cells),
                  "· 无记录　? 用量未知　0 已知零　░ <1千　▒ <1万　▓ ≥1万", "近 7 个有记录日："])
    for day in days[-7:]:
        count = day["total_tokens"]
        detail = f"已知 {count} Token" if count is not None else "Token 未知"
        if day["usage_unknown_turns"] and count is not None:
            detail += "（部分轮次未知）"
        lines.append(f"{day['date']}　{day['requests']} 轮　{detail}")
    return "\n".join(lines)
