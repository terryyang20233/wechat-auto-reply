from __future__ import annotations

import threading
import time
from collections import deque


class SendGuard:
    """Keep sending sparse and human-paced to reduce account-risk signals."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_sent_at = 0.0
        self._hour_stamps: deque[float] = deque()

    def check(self, min_interval: float, max_per_hour: int) -> str | None:
        now = time.monotonic()
        with self._lock:
            gap = now - self._last_sent_at
            if self._last_sent_at and gap < min_interval:
                wait = int(min_interval - gap) + 1
                return f"发送过快，请再等 {wait} 秒。这是为了降低微信风控风险。"
            while self._hour_stamps and now - self._hour_stamps[0] > 3600:
                self._hour_stamps.popleft()
            if len(self._hour_stamps) >= max_per_hour:
                return f"过去一小时已发送 {max_per_hour} 条，已达上限。请稍后再试。"
        return None

    def mark_sent(self) -> None:
        now = time.monotonic()
        with self._lock:
            self._last_sent_at = now
            self._hour_stamps.append(now)
