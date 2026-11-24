"""A single bounded private journal, shared by all providers on the host event loop."""

import asyncio
import hmac
import json
import math
import os
import re
import secrets
import stat
import time
from datetime import datetime, timezone

TTL = 7 * 86400
MAX_EVENTS = 128
MAX_BYTES = 65536
FAILURES = {"error", "cancelled", "short_circuited"}
FALLBACK_REASONS = {"tool_handoff", "tool_continuation", "visible_prefix", "no_visible_prefix"}
STOP_REASONS = {"end_turn", "max_tokens", "cancelled", "error", "failed", "failure",
                "agent_error", "execution_error", "internal_error"}


def _choice(value, choices):
    return value if isinstance(value, str) and value in choices else None


def event_fields(record):
    fields = {}
    for key in ("turn_id", "origin_turn_id", "logical_request_tag"):
        value = record.get(key)
        fields[key] = value if isinstance(value, str) and re.fullmatch("[0-9a-f]{16}", value) else None
    for key in ("elapsed_ms", "attempt", "cli_retry_attempt", "body_bytes", "thought_bytes", "permission_denial_count",
                "filtered_notice_count"):
        value = record.get(key)
        fields[key] = value if type(value) is int and 0 <= value < 2**53 else None
    for key in ("chunk_seen", "body_seen", "body_streamed", "tool_handed_off", "tool_result_supplied", "fallback_allowed"):
        value = record.get(key)
        fields[key] = value if type(value) is bool else None
    fields["fallback_reason"] = _choice(record.get("fallback_reason"), FALLBACK_REASONS)
    fields["stop_reason"] = _choice(record.get("stop_reason"), STOP_REASONS)
    return fields


class FailureJournal:
    def __init__(self, root, codes):
        self.path = root / "failure-events-v1.json"
        self.temp = root / "failure-events-v1.tmp"
        self.codes = codes
        self.rows = []
        self.salt = secrets.token_bytes(32)
        self.storage_state = "available"
        self.timer = None
        try:
            root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if root.is_symlink():
                raise OSError
            self.temp.unlink(missing_ok=True)
            self._load()
        except (ValueError, TypeError, OverflowError, RecursionError):
            self.rows.clear()
            self._save()
        except OSError:
            self.storage_state = "unavailable"
        self._schedule()

    def provider_tag(self, provider_id):
        if not isinstance(provider_id, str) or not provider_id:
            return None
        return hmac.digest(self.salt, provider_id.encode("utf-8", "surrogatepass"), "sha256").hex()[:32]

    def _safe_event(self, record, stamp):
        if not isinstance(record, dict) or not _choice(record.get("status"), FAILURES):
            return None
        if type(stamp) not in (float, int) or not math.isfinite(stamp) or not time.time() - TTL < stamp <= time.time():
            return None
        return {
            **event_fields(record), "time": stamp,
            "provider_tag": record["provider_tag"] if isinstance(record.get("provider_tag"), str)
            and re.fullmatch("[0-9a-f]{32}", record["provider_tag"]) else None,
            "status": record["status"], "error_code": _choice(record.get("error_code"), self.codes) or "UNKNOWN",
            "mode": _choice(record.get("mode"), {"tools", "chat"}),
        }

    def _load(self):
        try:
            before = self.path.lstat()
        except FileNotFoundError:
            return
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise OSError
        if before.st_size > MAX_BYTES:
            raise ValueError
        fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(fd)
            if not os.path.samestat(info, before) or info.st_nlink != 1:
                raise ValueError
            data = stream.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError
        payload = json.loads(data)
        if not isinstance(payload, dict) or not isinstance(payload.get("salt"), str) or not re.fullmatch(
            "[0-9a-f]{64}", payload["salt"]
        ):
            raise ValueError
        self.salt = bytes.fromhex(payload["salt"])
        rows = payload.get("events")
        if not isinstance(rows, list):
            raise ValueError
        for row in rows[-MAX_EVENTS:]:
            if isinstance(row, dict):
                event = self._safe_event(row, row.get("time"))
                if event is not None:
                    self.rows.append(event)
        if rows != self.rows or set(payload) != {"events", "salt"}:
            self._save()

    def _save(self):
        # Fixed staging name bounds crash residue. Never follow an existing
        # file or link for writing. Replace the committed snapshot atomically.
        try:
            if self.path.parent.is_symlink():
                raise OSError
            while True:
                payload = json.dumps({"salt": self.salt.hex(), "events": self.rows},
                                     separators=(",", ":")).encode()
                if len(payload) <= MAX_BYTES:
                    break
                self.rows.pop(0)
            fd = os.open(self.temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(payload)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(self.temp, self.path)
            finally:
                self.temp.unlink(missing_ok=True)
            self.storage_state = "available"
        except OSError:
            self.storage_state = "unavailable"

    def append(self, record):
        now = time.time()
        event = self._safe_event({**record, "provider_tag": self.provider_tag(record.get("provider"))}, now)
        if event is None:
            return
        self.rows = [r for r in self.rows if r["time"] > now - TTL][1-MAX_EVENTS:]
        self.rows.append(event)
        self._save()
        self._schedule()

    def _schedule(self):
        self.close()
        if self.rows:
            delay = max(1, min(r["time"] for r in self.rows) + TTL - time.time())
            self.timer = asyncio.get_running_loop().call_later(delay, self._expire)

    def _expire(self):
        self.rows = [r for r in self.rows if r["time"] > time.time() - TTL]
        self._save()
        self._schedule()

    def snapshot(self):
        rows = []
        for record in reversed(self.rows):
            if record["time"] > time.time() - TTL:
                row = dict(record)
                row["recorded_at"] = datetime.fromtimestamp(row.pop("time"), timezone.utc).isoformat()
                rows.append(row)
        return {"failure_events": rows, "failure_retention": {
            "ttl_seconds": TTL, "max_events": MAX_EVENTS, "max_bytes": MAX_BYTES,
            "storage_state": self.storage_state,
        }}

    def close(self):
        if self.timer is not None:
            self.timer.cancel()
            self.timer = None
