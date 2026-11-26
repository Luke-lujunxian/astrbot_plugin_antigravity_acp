import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from tests import astrbot_stub  # noqa: F401
from agy_provider import turn_history
from agy_provider.telemetry import TelemetryTracker, daily_snapshot, start_diagnostics, stop_diagnostics


class TurnHistoryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.tag = turn_history.instance_tag("private-provider", "a" * 32)

    async def test_real_time_window_record_caps_and_duplicate_sample(self):
        with (
            patch.object(turn_history, "MAX_STORED_TURNS", 5),
            patch.object(turn_history, "MAX_HISTORY_TURNS", 3),
        ):
            store = turn_history.TurnHistory(self.root)
            self.addCleanup(store.close)
            now = time.time()
            for index in range(6):
                store.record(self.tag, str(index), now - 20 + index, {"output": index})
            store.record(self.tag, "5", now - 15, {"output": 99})
            self.assertEqual([row["output"] for _, row in store.load(self.tag, now)], [3, 4, 5])
            for index in range(4):
                store.record("other", str(index), now - 6 + index, {"output": index})
            self.assertEqual([row["output"] for _, row in store.load(self.tag, now)], [4, 5])
            self.assertEqual(store.db.execute("SELECT count(*) FROM turns").fetchone()[0], 5)
            self.assertLessEqual(store.db.execute("PRAGMA max_page_count").fetchone()[0]
                                 * store.db.execute("PRAGMA page_size").fetchone()[0],
                                 turn_history.MAX_DB_BYTES)
            self.assertEqual(store.load(self.tag, now - 60), [])
            self.assertEqual(store.load(self.tag, now + 86400), [])
            store.record("expired", "one", now - 86401, {})
            self.assertEqual(store.db.execute("SELECT count(*) FROM turns WHERE instance = 'expired'").fetchone()[0], 0)
            for index in range(3):
                store.record(self.tag, f"future-{index}", now + index + 1, {"output": 10})
            store.record(self.tag, "after-clock-rollback", now - 1, {"output": 11})
            self.assertEqual([row["output"] for _, row in store.load(self.tag, now)], [11])

    async def test_allowlist_and_process_exit_durability(self):
        result = subprocess.run(
            [sys.executable, "-c", """
import os
import sys
from pathlib import Path
from tests import astrbot_stub
from agy_provider.telemetry import TelemetryTracker, start_diagnostics

start_diagnostics(Path(sys.argv[1]))
class TrackerWithPrivateFields(TelemetryTracker):
    def record_turn(self, record):
        super().record_turn({
            **record, "prompt": "PRIVATE_CANARY", "tool_arguments": {"value": "PRIVATE_CANARY"},
            "native_session_tag": "PRIVATE_CANARY", "context_used": 123,
        })

tracker = TrackerWithPrivateFields()
tracker.restore_history(sys.argv[2])
meter = tracker.start_turn(provider="private-provider", session_key_raw="RAW_SESSION_PRIVATE",
                           model="gemini-valid", mode="chat", effort="default")
meter.finish(status="ok")
meter.finish(status="ok")
os._exit(0)
""", str(self.root), self.tag],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        store = turn_history.TurnHistory(self.root)
        self.addCleanup(store.close)
        rows = store.load(self.tag, time.time())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1]["model"], "gemini-valid")
        self.assertTrue(rows[0][1]["stable_identity"])
        self.assertNotIn("context_used", rows[0][1])
        raw = store.path.read_bytes()
        for value in (b"PRIVATE_CANARY", b"RAW_SESSION_PRIVATE", b"private-provider", b"session_key"):
            self.assertNotIn(value, raw)

        start_diagnostics(self.root)
        self.addCleanup(stop_diagnostics)
        tracker = TelemetryTracker()
        tracker.restore_history(self.tag)
        self.assertEqual(tracker.monitor_summary()["total_turns"], 1)
        self.assertEqual(tracker.safe_recent_turns()[0]["context_used"], None)

    async def test_lock_falls_back_to_memory_and_preserves_daily_usage(self):
        start_diagnostics(self.root)
        self.addCleanup(stop_diagnostics)
        tracker = TelemetryTracker()
        tracker.restore_history(self.tag)
        path = self.root / "turn-history-v1.sqlite3"
        with sqlite3.connect(path) as blocker:
            blocker.execute("BEGIN IMMEDIATE")
            meter = tracker.start_turn(provider="p", session_key_raw=None, model="m", mode="chat", effort="default")
            meter.finish(status="ok")
        blocker.close()
        self.assertEqual(tracker.history_storage, "memory_only")
        self.assertEqual(tracker.monitor_summary()["total_turns"], 1)
        self.assertEqual(daily_snapshot()["days"][0]["requests"], 1)

    async def test_corrupt_or_newer_schema_is_preserved_and_oversized_file_refused(self):
        path = self.root / "turn-history-v1.sqlite3"
        path.write_bytes(b"invalid database bytes")
        self.assertIsNone(turn_history.TurnHistory(self.root).db)
        self.assertEqual(path.read_bytes(), b"invalid database bytes")
        path.unlink()
        with sqlite3.connect(path) as newer:
            newer.execute("PRAGMA user_version = 2")
        newer.close()
        if os.name == "posix":
            path.chmod(0o600)
        self.assertIsNone(turn_history.TurnHistory(self.root).db)
        with sqlite3.connect(path) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0], 2)
        db.close()
        with path.open("r+b") as stream:
            stream.truncate(turn_history.MAX_DB_BYTES + 1)
        self.assertIsNone(turn_history.TurnHistory(self.root).db)
        self.assertEqual(path.stat().st_size, turn_history.MAX_DB_BYTES + 1)

    async def test_rejects_linked_database_and_sidecar(self):
        target = self.root / "other-file"
        target.write_bytes(b"untouched")
        path = self.root / "turn-history-v1.sqlite3"
        try:
            os.link(target, path)
        except OSError as exc:
            self.skipTest(f"Hardlinks unavailable: {exc.strerror}")
        self.assertIsNone(turn_history.TurnHistory(self.root).db)
        path.unlink()
        os.link(target, self.root / "turn-history-v1.sqlite3-journal")
        self.assertIsNone(turn_history.TurnHistory(self.root).db)
        self.assertEqual(target.read_bytes(), b"untouched")
