from __future__ import annotations

import hashlib
import hmac
import re
from datetime import datetime
from uuid import UUID
from zoneinfo import ZoneInfo

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.errors import DependencyUnavailable, TooManyRequests


_CONSUME_SCRIPT = """
local global_count = tonumber(redis.call('GET', KEYS[1]) or '0')
local subject_count = tonumber(redis.call('GET', KEYS[2]) or '0')
local global_limit = tonumber(ARGV[1])
local subject_limit = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
if global_count >= global_limit then
  return {0, 1, global_count, subject_count}
end
if subject_count >= subject_limit then
  return {0, 2, global_count, subject_count}
end
global_count = redis.call('INCR', KEYS[1])
subject_count = redis.call('INCR', KEYS[2])
if global_count == 1 then redis.call('EXPIRE', KEYS[1], ttl) end
if subject_count == 1 then redis.call('EXPIRE', KEYS[2], ttl) end
return {1, 0, global_count, subject_count}
"""


class ChatQuota:
    """Atomic, privacy-preserving daily limits for the public demo chat."""

    def __init__(
        self,
        redis_url: str,
        hmac_key: str,
        *,
        enabled: bool,
        anonymous_daily: int,
        authenticated_daily: int,
        global_daily: int,
        exempt_subject_hashes: set[str] | frozenset[str] | None = None,
        key_namespace: str = "chat",
        dependency_name: str = "chat_quota",
        subject_message: str = "今日智能问答额度已用完，请明日再试",
        global_message: str = "今日演示系统智能问答总额度已用完，请明日再试",
    ) -> None:
        if not re.fullmatch(r"[a-z0-9-]{1,48}", key_namespace):
            raise ValueError("invalid quota key namespace")
        exemptions = frozenset(exempt_subject_hashes or ())
        if any(not re.fullmatch(r"[0-9a-f]{64}", value) for value in exemptions):
            raise ValueError("invalid quota exemption subject")
        self.enabled = enabled
        self.hmac_key = hmac_key.encode("utf-8")
        self.anonymous_daily = anonymous_daily
        self.authenticated_daily = authenticated_daily
        self.global_daily = global_daily
        self.exempt_subject_hashes = exemptions
        self.key_namespace = key_namespace
        self.dependency_name = dependency_name
        self.subject_message = subject_message
        self.global_message = global_message
        self.client = Redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=3,
        )

    def _subject(self, account_id: UUID | None, client_ip: str) -> str:
        raw = f"account:{account_id}" if account_id else f"ip:{client_ip or 'unknown'}"
        return hmac.new(self.hmac_key, raw.encode("utf-8"), hashlib.sha256).hexdigest()

    async def consume(self, account_id: UUID | None, client_ip: str) -> None:
        if not self.enabled:
            return
        today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
        subject = self._subject(account_id, client_ip)
        if subject in self.exempt_subject_hashes:
            return
        subject_limit = (
            self.authenticated_daily if account_id else self.anonymous_daily
        )
        try:
            result = await self.client.eval(
                _CONSUME_SCRIPT,
                2,
                f"smart-gov:quota:{self.key_namespace}:{today}:global",
                f"smart-gov:quota:{self.key_namespace}:{today}:subject:{subject}",
                self.global_daily,
                subject_limit,
                172800,
            )
        except RedisError as exc:
            # Quota enforcement protects a public paid endpoint. Fail closed
            # with a structured dependency response instead of bypassing it.
            raise DependencyUnavailable(self.dependency_name) from exc
        if not result or int(result[0]) != 1:
            reason = int(result[1]) if result and len(result) > 1 else 0
            if reason == 1:
                raise TooManyRequests(self.global_message)
            raise TooManyRequests(self.subject_message)

    async def close(self) -> None:
        await self.client.aclose()
