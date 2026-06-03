from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Callable

from fastapi import Request


@dataclass(frozen=True)
class RateLimitRule:
    limit: int
    window_seconds: int


@dataclass(frozen=True)
class RateLimitExceeded(Exception):
    retry_after: int


@dataclass
class LoginFailureState:
    count: int = 0
    first_at: float = 0
    cooldown_until: float = 0


class RateLimiter:
    def __init__(self, now: Callable[[], float] | None = None):
        self._now = now or time.time
        self._events: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._login_failures: dict[str, LoginFailureState] = {}
        self._lock = threading.RLock()
        self.rules: dict[str, RateLimitRule] = {
            "public_light": RateLimitRule(limit=120, window_seconds=60),
            "auth_login": RateLimitRule(limit=20, window_seconds=60),
            "collect": RateLimitRule(limit=30, window_seconds=60),
            "import_json": RateLimitRule(limit=10, window_seconds=60),
            "media": RateLimitRule(limit=120, window_seconds=60),
        }
        self.login_failure_limit = 5
        self.login_failure_window_seconds = 300
        self.login_cooldown_seconds = 60

    def set_rule(self, name: str, limit: int, window_seconds: int) -> None:
        self.rules[name] = RateLimitRule(limit=limit, window_seconds=window_seconds)

    def client_key(self, request: Request) -> str:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",", 1)[0].strip() or "unknown"
        if request.client is not None:
            return request.client.host or "unknown"
        return "unknown"

    def session_key(self, request: Request) -> str:
        user = getattr(request.state, "user", "")
        if user:
            return f"user:{user}"
        return f"ip:{self.client_key(request)}"

    def check(self, rule_name: str, key: str) -> None:
        rule = self.rules.get(rule_name)
        if rule is None or rule.limit <= 0 or rule.window_seconds <= 0:
            return

        now = self._now()
        bucket = (rule_name, key)
        with self._lock:
            events = self._events[bucket]
            while events and now - events[0] >= rule.window_seconds:
                events.popleft()
            if len(events) >= rule.limit:
                retry_after = max(1, int(rule.window_seconds - (now - events[0])))
                raise RateLimitExceeded(retry_after)
            events.append(now)

    def check_login_allowed(self, key: str) -> None:
        now = self._now()
        with self._lock:
            state = self._login_failures.get(key)
            if state is None:
                return
            if state.cooldown_until > now:
                raise RateLimitExceeded(max(1, int(state.cooldown_until - now)))

    def record_login_failure(self, key: str) -> None:
        now = self._now()
        with self._lock:
            state = self._login_failures.setdefault(key, LoginFailureState(first_at=now))
            if now - state.first_at >= self.login_failure_window_seconds:
                state.count = 0
                state.first_at = now
                state.cooldown_until = 0
            state.count += 1
            if state.count >= self.login_failure_limit:
                state.cooldown_until = now + self.login_cooldown_seconds
                state.count = 0
                state.first_at = now
                raise RateLimitExceeded(self.login_cooldown_seconds)

    def record_login_success(self, key: str) -> None:
        with self._lock:
            self._login_failures.pop(key, None)
