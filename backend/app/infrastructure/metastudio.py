from __future__ import annotations

import hashlib
import hmac
import json
import math
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

import httpx
from pydantic import SecretStr
from redis.asyncio import Redis

from app.application.ports import MetaStudioSessionPort
from app.errors import DependencyUnavailable


_HEX_TIMESTAMP = re.compile(r"^[0-9a-fA-F]{1,32}$")
_HEX_SIGNATURE = re.compile(r"^[0-9a-fA-F]{64}$")
_APP_ID = re.compile(r"^[0-9a-f]{32}$")
_APP_KEY = re.compile(r"^[0-9a-f]{32}$")


def secret_value(value: SecretStr | None, file_path: str | None) -> str | None:
    """Read a mounted single-line secret without ever logging its value."""

    if file_path:
        try:
            raw = Path(file_path).read_text(encoding="utf-8")
        except OSError:
            return None
        resolved = raw.strip()
        if "\n" in resolved or "\r" in resolved:
            return None
        return resolved or None
    if value is None:
        return None
    resolved = value.get_secret_value().strip()
    if "\n" in resolved or "\r" in resolved:
        return None
    return resolved or None


class RedisMetaStudioSessionAdapter(MetaStudioSessionPort):
    def __init__(self, redis_url: str, prefix: str = "metastudio:v1") -> None:
        self._redis = Redis.from_url(redis_url, decode_responses=True)
        self._prefix = prefix

    async def put(
        self, session_id: Any, values: dict[str, Any], ttl_seconds: int
    ) -> None:
        await self._redis.set(
            f"{self._prefix}:sessions:{session_id}",
            json.dumps(values, ensure_ascii=False, separators=(",", ":"), default=str),
            ex=ttl_seconds,
        )

    async def get(self, session_id: Any) -> dict[str, Any] | None:
        raw = await self._redis.get(f"{self._prefix}:sessions:{session_id}")
        if raw is None:
            return None
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None

    async def claim_replay(self, replay_key: str, ttl_seconds: int) -> bool:
        claimed = await self._redis.set(
            f"{self._prefix}:replay:{replay_key}", "1", ex=ttl_seconds, nx=True
        )
        return bool(claimed)

    async def close(self) -> None:
        await self._redis.aclose()


class MetaStudioCallbackAuthenticator:
    """Validate Huawei's callback HMAC and atomically reject replay."""

    def __init__(
        self,
        *,
        enabled: bool,
        app_id: str | None,
        app_key: str | None,
        callback_url: str,
        replay_window_seconds: int,
        sessions: MetaStudioSessionPort,
    ) -> None:
        self._enabled = enabled
        self._app_id = app_id or ""
        self._app_key = app_key or ""
        self._callback_url = callback_url
        self._replay_window_seconds = replay_window_seconds
        self._sessions = sessions

    async def verify(
        self,
        supplied_secret: str,
        time_stamp: str,
        request_app_id: str,
        *,
        now_ms: int | None = None,
    ) -> bool:
        if (
            not self._enabled
            or not _APP_ID.fullmatch(self._app_id)
            or not _APP_KEY.fullmatch(self._app_key)
        ):
            return False
        if not _HEX_SIGNATURE.fullmatch(supplied_secret):
            return False
        if not _HEX_TIMESTAMP.fullmatch(time_stamp):
            return False
        if not _APP_ID.fullmatch(request_app_id) or not hmac.compare_digest(
            request_app_id, self._app_id
        ):
            return False
        timestamp_ms = int(time_stamp, 16)
        current_ms = now_ms if now_ms is not None else int(datetime.now(timezone.utc).timestamp() * 1000)
        if abs(current_ms - timestamp_ms) > self._replay_window_seconds * 1000:
            return False
        expected = hmac.new(
            self._app_key.encode("utf-8"),
            f"{self._callback_url}{timestamp_ms}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(supplied_secret.lower(), expected):
            return False
        # Canonicalize equivalent hexadecimal spellings (for example `1a`
        # and `01a`) so they cannot bypass replay detection. A timestamp may
        # be up to one window in the future, so retain the claim until that
        # timestamp's complete acceptance window has elapsed.
        replay_key = hashlib.sha256(
            f"{self._app_id}:{timestamp_ms}:{expected}".encode("ascii")
        ).hexdigest()
        replay_ttl = max(
            1,
            math.ceil(
                (timestamp_ms + self._replay_window_seconds * 1000 - current_ms)
                / 1000
            ),
        )
        try:
            return await self._sessions.claim_replay(
                replay_key, replay_ttl
            )
        except Exception as exc:
            # HMAC verification without replay storage is not safe enough for
            # an internet-facing callback, so Redis degradation fails closed.
            raise DependencyUnavailable("metastudio_replay") from exc


class HuaweiMetaStudioOnceCodeAdapter:
    """Server-side AK/SK adapter for the five-minute one-time auth code API."""

    _allowed_host = "metastudio.cn-north-4.myhuaweicloud.com"
    _allowed_endpoint = "https://metastudio.cn-north-4.myhuaweicloud.com"

    def __init__(
        self,
        *,
        enabled: bool,
        endpoint: str,
        project_id: str | None,
        access_key: str | None,
        secret_key: str | None,
        timeout_seconds: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._enabled = enabled
        self._endpoint = endpoint.rstrip("/")
        self._project_id = project_id or ""
        self._access_key = access_key or ""
        self._secret_key = secret_key or ""
        self._client = client or httpx.AsyncClient(
            timeout=timeout_seconds, trust_env=False
        )
        self._owns_client = client is None

    def _configuration_valid(self) -> bool:
        parsed = urlsplit(self._endpoint)
        return bool(
            self._enabled
            and self._project_id
            and self._access_key
            and self._secret_key
            and self._endpoint == self._allowed_endpoint
            and parsed.scheme == "https"
            and parsed.hostname == self._allowed_host
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
        )

    async def create_once_code(self, app_user_id: str) -> str:
        if not self._configuration_valid():
            raise DependencyUnavailable("metastudio")
        url = (
            f"{self._endpoint}/v1/{quote(self._project_id, safe='')}"
            "/digital-human-chat/once-code"
        )
        headers = self._signed_headers(url, app_user_id)
        try:
            response = await self._client.post(url, content=b"", headers=headers)
            response.raise_for_status()
            payload = response.json()
            once_code = payload.get("once_code") if isinstance(payload, dict) else None
            if not isinstance(once_code, str) or not 1 <= len(once_code) <= 4096:
                raise ValueError("invalid once-code response")
            return once_code
        except DependencyUnavailable:
            raise
        except Exception as exc:
            raise DependencyUnavailable("metastudio") from exc

    def _signed_headers(
        self, url: str, app_user_id: str, sdk_date: str | None = None
    ) -> dict[str, str]:
        if not app_user_id.isascii() or not 1 <= len(app_user_id) <= 128:
            raise DependencyUnavailable("metastudio")
        parsed = urlsplit(url)
        sdk_date = sdk_date or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        canonical_values = {
            "host": parsed.netloc,
            "x-app-userid": app_user_id,
            "x-project-id": self._project_id,
            "x-sdk-date": sdk_date,
        }
        signed_headers = ";".join(sorted(canonical_values))
        canonical_headers = "".join(
            f"{name}:{canonical_values[name].strip()}\n"
            for name in sorted(canonical_values)
        )
        canonical_uri = quote(parsed.path or "/", safe="/-_.~")
        # Huawei's official signer canonicalizes a non-root resource path with
        # a trailing slash even though the transmitted request URI is unchanged.
        if not canonical_uri.endswith("/"):
            canonical_uri += "/"
        payload_hash = hashlib.sha256(b"").hexdigest()
        canonical_request = "\n".join(
            (
                "POST",
                canonical_uri,
                "",
                canonical_headers,
                signed_headers,
                payload_hash,
            )
        )
        algorithm = "SDK-HMAC-SHA256"
        string_to_sign = "\n".join(
            (
                algorithm,
                sdk_date,
                hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
            )
        )
        signature = hmac.new(
            self._secret_key.encode("utf-8"),
            string_to_sign.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        authorization = (
            f"{algorithm} Access={self._access_key}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        return {
            "Authorization": authorization,
            "Host": parsed.netloc,
            "X-App-UserId": app_user_id,
            "X-Project-Id": self._project_id,
            "X-Sdk-Date": sdk_date,
        }

    async def close(self) -> None:
        if self._owns_client:
            await self._client.aclose()
