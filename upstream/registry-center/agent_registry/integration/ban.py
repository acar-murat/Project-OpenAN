# Copyright (c) 2026 Huawei Technologies Co., Ltd.
# All Rights Reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""
Authentication failure ban tracking (minimal anomaly detection).

Counts consecutive authentication failures per credential (falling back to
source IP when no credential was presented). Reaching the threshold
temporarily bans the key for a cooldown period. In-memory only — bans reset
on restart, consistent with the main port's rate limiter storage.
"""

import threading
import time

from loguru import logger


class BanTracker:
    """In-memory failure counter with temporary bans."""

    def __init__(self, threshold: int = 5, cooldown_seconds: int = 300,
                 clock=time.monotonic, on_lift=None):
        self.threshold = max(1, int(threshold))
        self.cooldown_seconds = max(1, int(cooldown_seconds))
        self._clock = clock
        self.on_lift = on_lift  # optional callback(key) fired when a ban expires
        self._failures = {}
        self._banned_until = {}
        self._lock = threading.Lock()

    def is_banned(self, key: str) -> bool:
        if not key:
            return False
        with self._lock:
            until = self._banned_until.get(key)
            if until is None:
                return False
            if self._clock() < until:
                return True
            # Cooldown elapsed: lift the ban and clear the counter
            del self._banned_until[key]
            self._failures.pop(key, None)
        if self.on_lift:
            try:
                self.on_lift(key)
            except Exception as e:  # pragma: no cover - audit must not break auth
                logger.debug(f"Ban-lift audit callback failed: {e}")
        return False

    def remaining_seconds(self, key: str) -> int:
        with self._lock:
            until = self._banned_until.get(key)
            if until is None:
                return 0
            return max(0, int(until - self._clock()))

    def record_failure(self, key: str) -> bool:
        """Count a failure. Returns True when this failure triggered a ban."""
        if not key:
            return False
        with self._lock:
            if key in self._banned_until:
                return False  # already banned; no counting during cooldown
            count = self._failures.get(key, 0) + 1
            if count >= self.threshold:
                self._banned_until[key] = self._clock() + self.cooldown_seconds
                self._failures.pop(key, None)
                return True
            self._failures[key] = count
            return False

    def record_success(self, key: str) -> None:
        if not key:
            return
        with self._lock:
            self._failures.pop(key, None)
