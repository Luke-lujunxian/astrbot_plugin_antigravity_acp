"""Bounded local storage for projected, settled turn statistics."""

import asyncio
import hmac
import json
import os
import re
import sqlite3
import stat
import time
from contextlib import suppress

from astrbot.api import logger

HISTORY_ID = "agy_history_id"
HISTORY_TTL_SECONDS = 86400
MAX_HISTORY_TURNS = 100
MAX_STORED_TURNS = 2000
MAX_DB_BYTES = 8 * 1024 * 1024
_SCHEMA_VERSION = 1


def valid_history_id(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{32}", value) is not None


def instance_tag(provider_id, history_id):
    if not isinstance(provider_id, str) or not provider_id or not valid_history_id(history_id):
        return None
    return hmac.digest(bytes.fromhex(history_id), provider_id.encode("utf-8", "surrogatepass"),
                       "sha256").hex()[:32]


def _private_path(info, *, directory=False):
    kind = stat.S_ISDIR if directory else stat.S_ISREG
    if not kind(info.st_mode) or getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
        return False
    if not directory and info.st_nlink != 1:
        return False
    if os.name == "posix":
        return info.st_uid == os.getuid() and not info.st_mode & (0o022 if directory else 0o077)
    return True


class TurnHistory:
    def __init__(self, root):
        self.db = self.timer = None
        self.path = root / "turn-history-v1.sqlite3"
        try:
            root.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not _private_path(root.lstat(), directory=True):
                raise OSError
            with suppress(FileNotFoundError):
                if not _private_path(self.path.lstat()):
                    raise OSError
            fd = os.open(self.path, os.O_CREAT | os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                         | getattr(os, "O_NONBLOCK", 0), 0o600)
            try:
                info = os.fstat(fd)
                if (not _private_path(info) or not os.path.samestat(info, self.path.lstat())
                        or info.st_size > MAX_DB_BYTES):
                    raise OSError
            finally:
                os.close(fd)

            self._check_sidecars()
            self.db = sqlite3.connect(self.path, timeout=0.01)
            self.db.execute("PRAGMA trusted_schema = OFF")
            if self.db.execute("PRAGMA user_version").fetchone()[0] not in (0, _SCHEMA_VERSION):
                raise sqlite3.OperationalError("Unsupported turn history schema")
            if self.db.execute("PRAGMA journal_mode = DELETE").fetchone()[0] != "delete":
                raise sqlite3.OperationalError
            self.db.execute("PRAGMA synchronous = FULL")
            self.db.execute("PRAGMA secure_delete = ON")
            page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
            page_limit = MAX_DB_BYTES // page_size
            if self.db.execute(f"PRAGMA max_page_count = {page_limit}").fetchone()[0] > page_limit:
                raise sqlite3.OperationalError
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                self._migrate()
                self._prune(time.time())
            self._schedule_expiry()
        except (OSError, sqlite3.Error):
            self._degrade()

    def _check_sidecars(self):
        for suffix in ("-journal", "-wal", "-shm"):
            with suppress(FileNotFoundError):
                if not _private_path(self.path.with_name(self.path.name + suffix).lstat()):
                    raise OSError

    def _migrate(self):
        version, = self.db.execute("PRAGMA user_version").fetchone()
        if version == 0:
            self.db.execute(
                "CREATE TABLE turns (id INTEGER PRIMARY KEY, instance TEXT NOT NULL, "
                "sample TEXT NOT NULL, stamp REAL NOT NULL, stats TEXT NOT NULL, UNIQUE(instance, sample))")
            self.db.execute("CREATE INDEX turns_instance_stamp ON turns(instance, stamp, id)")
            self.db.execute("CREATE INDEX turns_stamp ON turns(stamp, id)")
            self.db.execute(f"PRAGMA user_version = {_SCHEMA_VERSION}")
        elif version != _SCHEMA_VERSION:
            raise sqlite3.OperationalError("Unsupported turn history schema")

    def _prune(self, now):
        self.db.execute("DELETE FROM turns WHERE stamp <= ?", (now - HISTORY_TTL_SECONDS,))
        # Settlement order keeps new samples even if the wall clock moves back.
        self.db.execute("DELETE FROM turns WHERE id IN (SELECT id FROM turns ORDER BY id DESC "
                        "LIMIT -1 OFFSET ?)", (MAX_STORED_TURNS,))

    def _schedule_expiry(self):
        if self.timer is not None:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        oldest = self.db.execute("SELECT MIN(stamp) FROM turns").fetchone()[0]
        if type(oldest) in (int, float):
            delay = min(3600, max(1, oldest + HISTORY_TTL_SECONDS - time.time()))
            self.timer = loop.call_later(delay, self._expire)

    def _expire(self):
        self.timer = None
        try:
            self._check_sidecars()
            with self.db:
                self._prune(time.time())
            self._schedule_expiry()
        except (OSError, sqlite3.Error):
            self._degrade()

    def record(self, instance, sample, stamp, stats):
        if self.db is None:
            return
        try:
            self._check_sidecars()
            payload = json.dumps(stats, ensure_ascii=True, separators=(",", ":"), allow_nan=False)
            with self.db:
                self.db.execute("INSERT INTO turns(instance, sample, stamp, stats) VALUES (?,?,?,?) "
                                "ON CONFLICT(instance, sample) DO NOTHING", (instance, sample, stamp, payload))
                self.db.execute("DELETE FROM turns WHERE id IN (SELECT id FROM turns WHERE instance = ? "
                                "ORDER BY id DESC LIMIT -1 OFFSET ?)", (instance, MAX_HISTORY_TURNS))
                self._prune(time.time())
            self._schedule_expiry()
        except (OSError, OverflowError, ValueError, sqlite3.Error):
            self._degrade()

    def load(self, instance, now):
        if self.db is None:
            return []
        try:
            self._check_sidecars()
            rows = self.db.execute("SELECT stamp, stats FROM turns WHERE instance = ? AND stamp > ? AND stamp <= ? "
                                   "ORDER BY stamp DESC, id DESC LIMIT ?",
                                   (instance, now - HISTORY_TTL_SECONDS, now, MAX_HISTORY_TURNS))
            return [(stamp, json.loads(payload)) for stamp, payload in reversed(rows.fetchall())]
        except (OSError, ValueError, RecursionError, sqlite3.Error):
            self._degrade()
            return []

    def _degrade(self):
        self.close()
        logger.warning("AGY 请求明细存储不可用，当前仅保留内存统计。")

    def close(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
        if self.db is not None:
            with suppress(sqlite3.Error):
                self.db.close()
            self.db = None
