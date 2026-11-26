"""Local calendar-day aggregates. Store no turn, provider or conversation IDs."""

import os
import sqlite3
import stat
from datetime import date, datetime, timedelta


COLUMNS = ("requests", "success", "failed", "input_tokens", "cached_tokens",
           "output_tokens", "total_tokens", "usage_unknown_turns")


def _sum(*values):
    known = [n for n in values if n is not None]
    return sum(known) if known else None


class DailyUsage:
    def __init__(self, root):
        self.db = None
        self.write_failed = False
        try:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if root.is_symlink():
                raise OSError
            path = root / "daily-usage-v1.sqlite3"
            fd = os.open(path, os.O_CREAT | os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0), 0o600)
            try:
                info = os.fstat(fd)
                if path.is_symlink() or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                    raise OSError
            finally:
                os.close(fd)
            self.db = sqlite3.connect(path, timeout=0.05)
            self.db.execute("CREATE TABLE IF NOT EXISTS daily (day TEXT, model TEXT, "
                            + ", ".join(f"{col} INTEGER" for col in COLUMNS)
                            + ", PRIMARY KEY(day, model))")
        except (OSError, sqlite3.Error):
            self.close()

    def close(self):
        if self.db is not None:
            self.db.close()
            self.db = None

    def record(self, record):
        if self.db is None:
            return
        day = datetime.fromisoformat(record["recorded_at"]).astimezone().date()
        model = (record.get("negotiated_model") or record.get("model") or "")[:256]
        success = int(record.get("status") == "ok")
        other, cached, output = (record.get(k) for k in ("input_other", "input_cached", "output"))
        total_input = _sum(other, cached)
        values = (1, success, 1-success, total_input, cached, output, _sum(total_input, output),
                  int(record.get("usage_status") == "unavailable"))
        # NULL + NULL stays NULL. A mix of missing and known counts sums only the known fields.
        updates = ", ".join(f"{c}=COALESCE({c}+excluded.{c},{c},excluded.{c})" for c in COLUMNS)
        try:
            with self.db:
                self.db.execute("DELETE FROM daily WHERE day < ?", ((day-timedelta(days=364)).isoformat(),))
                self.db.execute(f"INSERT INTO daily VALUES (?,?,?,?,?,?,?,?,?,?) "
                                f"ON CONFLICT(day,model) DO UPDATE SET {updates}",
                                (day.isoformat(), model, *values))
        except (OverflowError, sqlite3.Error, UnicodeError):
            self.write_failed = True

    def snapshot(self, days=90):
        if self.db is None or self.write_failed:
            raise OSError("每日统计存储不可用。")
        if days not in (30, 90, 365):
            raise ValueError("区间无效。")
        end = date.today()
        start = end - timedelta(days=days-1)
        rows, models = {}, set()
        for day, model, *values in self.db.execute(
                "SELECT * FROM daily WHERE day BETWEEN ? AND ? ORDER BY day, model",
                (start.isoformat(), end.isoformat())):
            row = rows.setdefault(day, {"date": day, "by_model": {}})
            row["by_model"][model] = dict(zip(COLUMNS, values))
            models.add(model)
            for key, value in zip(COLUMNS, values):
                row[key] = _sum(row.get(key), value)
        return {"schema_version": 1, "timezone": "host_local",
                "range": {"days": days, "start": start.isoformat(), "end": end.isoformat()},
                "models": sorted(models), "days": list(rows.values())}
