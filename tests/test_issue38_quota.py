import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from agy_provider.config import Settings
from agy_provider.errors import AgyError
from agy_provider import quota
from agy_provider.process import spawn

SAMPLE = Path(__file__).parent / "fixtures/issue38/quota_usage_sample.json"


class QuotaTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = quota.QuotaService(Settings())
        self.addAsyncCleanup(self.service.close)
        self.environment = self.enterContext(patch.object(quota, "_environment", return_value=(("test",), True)))
        self.enterContext(patch.object(quota, "resolve_binary", return_value="agy"))
        self.version = self.enterContext(patch.object(quota, "capture", AsyncMock(return_value="1.5.17")))
        self.groups = quota._groups(SAMPLE.read_bytes())
        self.query = self.enterContext(patch.object(quota, "_usage", AsyncMock(return_value=self.groups)))

    def test_sample_and_rejected_shapes(self):
        self.assertEqual(len(self.groups[0]["models_shared"]), 8)
        self.assertEqual(self.groups[0]["buckets"][0]["window"], "weekly")
        self.assertIsNone(self.groups[1]["buckets"][1]["reset_time"])
        for value in [None, 2, -1, True, "0.1", float("nan")]:
            data = json.loads(SAMPLE.read_bytes())
            data["command"]["data"]["groups"][0]["buckets"][0]["remaining_fraction"] = value
            with self.assertRaisesRegex(AgyError, "QUOTA_FORMAT"):
                quota._groups(json.dumps(data))
        with self.assertRaisesRegex(AgyError, "QUOTA_FORMAT"):
            quota._groups(b"not json")

    async def test_cold_get_manual_refresh_cache_failure_and_login_switch(self):
        self.assertIsNone(self.service.snapshot()["fetched_at"])
        self.query.assert_not_awaited()
        result = await self.service.refresh()
        await self.service.refresh()
        self.query.assert_awaited_once()
        self.assertFalse(result["stale"])
        self.service.updated -= 61
        self.assertTrue(self.service.snapshot()["stale"])
        self.query.side_effect = AgyError("UPSTREAM", "PRIVATE_ERROR")
        failed = await self.service.refresh()
        self.assertEqual(failed["groups"], self.groups)
        self.assertTrue(failed["stale"])
        self.assertNotIn("PRIVATE_ERROR", str(failed))
        self.environment.return_value = (("replaced",), True)
        self.assertEqual(self.service.snapshot()["groups"], [])
        self.assertNotEqual(self.service.snapshot()["login_env"], result["login_env"])
        self.query.side_effect = None
        await self.service.refresh()
        self.query.side_effect = AgyError("AUTH", "PRIVATE_URL")
        logged_out = await self.service.refresh(force=True)
        self.assertEqual(logged_out["groups"], [])
        self.assertEqual(logged_out["error"]["code"], "AUTH")

    async def test_coalesces_refresh_and_cancellation_is_per_waiter(self):
        started, release = asyncio.Event(), asyncio.Event()
        async def query(*args):
            started.set()
            await release.wait()
            return self.groups
        self.query.side_effect = query
        a = asyncio.create_task(self.service.refresh())
        await started.wait()
        b = asyncio.create_task(self.service.refresh(force=True))
        a.cancel()
        await asyncio.gather(a, return_exceptions=True)
        release.set()
        self.assertEqual((await b)["groups"], self.groups)
        self.query.assert_awaited_once()

    async def test_close_reports_closed_to_active_refresh_waiter(self):
        started = asyncio.Event()

        async def query(*args):
            started.set()
            await asyncio.Event().wait()

        self.query.side_effect = query
        waiter = asyncio.create_task(self.service.refresh())
        await started.wait()
        await self.service.close()
        with self.assertRaisesRegex(AgyError, "CLOSED"):
            await waiter

    async def test_account_change_inflight_and_unobservable_keyring(self):
        async def switch(*_):
            self.environment.return_value = (("new",), True)
            return self.groups
        self.query.side_effect = switch
        result = await self.service.refresh()
        self.assertEqual(result["groups"], [])
        self.assertEqual(result["error"]["code"], "ENV_CHANGED")
        self.environment.return_value = (("keyring",), False)
        self.query.side_effect = None
        self.assertEqual((await self.service.refresh())["groups"], self.groups)
        self.assertEqual(self.service.snapshot()["groups"], [])

    async def test_unknown_old_cli_does_not_run_slash_command(self):
        self.version.return_value = "1.5.2"
        data = await self.service.refresh()
        self.assertEqual(data["capability"], "unsupported")
        self.query.assert_not_awaited()


class QuotaChildTests(unittest.IsolatedAsyncioTestCase):
    async def child(self, script):
        with tempfile.TemporaryDirectory() as tmp:
            proc = None
            async def launch(argv, cwd, env):
                nonlocal proc
                self.assertEqual(argv, ["agy", "-p", "/usage", "--output-format", "json"])
                proc = await spawn([sys.executable, "-c", script], cwd, env=env)
                return proc
            with patch.object(quota, "spawn", launch):
                try:
                    return await quota._usage("agy", {}, Path(tmp))
                finally:
                    self.assertIsNotNone(proc.returncode)

    async def test_stdin_closed_and_bounded_stdout(self):
        script = "import sys; assert sys.stdin.read() == ''; print(" + repr(SAMPLE.read_text()) + ")"
        self.assertEqual(len(await self.child(script)), 2)
        with self.assertRaisesRegex(AgyError, "QUOTA_FORMAT"):
            await self.child("print('x' * 300000)")

    async def test_login_and_timeout_reap_child_without_echoing_stderr(self):
        with self.assertRaises(AgyError) as caught:
            await self.child("import sys,time; print('authorization code private_marker', file=sys.stderr); time.sleep(10)")
        self.assertEqual(caught.exception.code, "AUTH")
        self.assertNotIn("private_marker", str(caught.exception))
        with self.assertRaises(TimeoutError):
            async with asyncio.timeout(0.3):
                await self.child("import time; time.sleep(10)")
