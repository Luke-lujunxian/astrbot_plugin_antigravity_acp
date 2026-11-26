import os
import tempfile
import time
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from tests import astrbot_stub
from agy_provider.daily_usage import DailyUsage
from agy_provider.telemetry import TelemetryTracker, daily_snapshot, start_diagnostics, stop_diagnostics


class DailyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = self.enterContext(tempfile.TemporaryDirectory())
        self.root = Path(self.temp)
        self.store = DailyUsage(self.root)
        self.addCleanup(self.store.close)

    def record(self, day, model, other, cached, output, status="ok", usage="reported"):
        self.store.record({"recorded_at": day, "model": model, "input_other": other,
                           "input_cached": cached, "output": output, "status": status,
                           "usage_status": usage, "session_key": "CANARY_PRIVATE"})

    def test_sparse_dates_known_zero_unknown_and_reopen(self):
        end = date.today()
        d1, d2 = end - timedelta(days=5), end - timedelta(days=2)
        self.record(d1.isoformat(), "one", None, None, None, "error", "unavailable")
        self.record(d2.isoformat(), "two", 0, 0, 0, "short_circuited", "not_sent")
        self.record(end.isoformat(), "one", 5, None, 1)
        self.record(end.isoformat(), "two", 10, 3, 4)
        self.record(end.isoformat(), "two", None, None, None, "cancelled", "unavailable")
        self.store.close()
        reopened = DailyUsage(self.root)
        self.addCleanup(reopened.close)
        for span in (30, 90, 365):
            result = reopened.snapshot(span)
            self.assertEqual(result["range"]["start"], (end-timedelta(days=span-1)).isoformat())
            self.assertEqual(result["models"], ["one", "two"])
            older, zero, today = result["days"]
            self.assertIsNone(older["total_tokens"])
            self.assertEqual(zero["total_tokens"], 0)
            self.assertEqual((today["requests"], today["success"], today["failed"]), (3, 2, 1))
            self.assertEqual((today["total_tokens"], today["input_tokens"], today["cached_tokens"]), (23, 18, 3))
            self.assertIsNone(today["by_model"]["one"]["cached_tokens"])
            self.assertEqual(today["usage_unknown_turns"], 1)
        self.assertNotIn(b"CANARY_PRIVATE", (self.root / "daily-usage-v1.sqlite3").read_bytes())

    @unittest.skipUnless(hasattr(time, "tzset"), "POSIX timezone override")
    def test_host_local_day_boundaries(self):
        self.addCleanup(time.tzset)
        with patch.dict(os.environ, {"TZ": "Asia/Shanghai"}):
            time.tzset()
            today = date.today()
            stamp = (today - timedelta(days=1)).isoformat() + "T16:10:00+00:00"
            self.record(stamp, "one", 1, 0, 1)
            self.assertEqual(self.store.snapshot()["days"][0]["date"], today.isoformat())

    async def test_telemetry_sink_once_across_restart_without_cost_log(self):
        start_diagnostics(self.root)
        self.addCleanup(stop_diagnostics)
        tracker = TelemetryTracker()
        meter = tracker.start_turn(provider="p", session_key_raw="private", mode="chat", model="m", effort="low")
        meter.request_sent = True
        meter.finish(status="error", error_code="TIMEOUT")
        meter.finish(status="ok")
        start_diagnostics(self.root)
        self.assertEqual(daily_snapshot()["days"][0]["requests"], 1)
        self.assertEqual(daily_snapshot()["days"][0]["usage_unknown_turns"], 1)
