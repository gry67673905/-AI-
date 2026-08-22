from __future__ import annotations

import re
import hashlib
import secrets
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.domain.enums import ApplicantType, Role
from app.application.dtos import Principal


_SENSITIVE_KEYS = re.compile(
    r"(?:authorization|api[-_]?key|token|password|passwd|secret|credential)", re.IGNORECASE
)
_BEARER = re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]+")
_API_KEY = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_CN_ID = re.compile(r"(?<![0-9A-Za-z])\d{17}[0-9Xx](?![0-9A-Za-z])")
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])")


def redact_sensitive(value: Any) -> Any:
    """Return a JSON-safe copy with secrets removed from keys and free text."""

    if isinstance(value, Mapping):
        return {
            str(key): "[REDACTED]" if _SENSITIVE_KEYS.search(str(key)) else redact_sensitive(item)
            for key, item in value.items()
        }
    if isinstance(value, str):
        secret_safe = _API_KEY.sub(
            "[REDACTED]", _BEARER.sub("Bearer [REDACTED]", value)
        )
        return redact_pii_text(secret_safe)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [redact_sensitive(item) for item in value]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return redact_sensitive(str(value))


def redact_pii_text(value: str) -> str:
    redacted = _CN_ID.sub("[REDACTED_ID]", value)
    redacted = _PHONE.sub("[REDACTED_PHONE]", redacted)
    return _EMAIL.sub("[REDACTED_EMAIL]", redacted)


_password_hasher = PasswordHasher(time_cost=3, memory_cost=65536, parallelism=2)


def hash_password(password: str) -> str:
    return _password_hasher.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return _password_hasher.verify(encoded, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def new_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class TokenCodec:
    def __init__(self, signing_key: str, access_minutes: int) -> None:
        self._signing_key = signing_key
        self._access_minutes = access_minutes

    def issue_access_token(self, principal: Principal) -> tuple[str, datetime]:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=self._access_minutes)
        payload = {
            "sub": str(principal.account_id),
            "usr": principal.username,
            "role": principal.role.value,
            "applicant_type": principal.applicant_type.value if principal.applicant_type else None,
            "ver": principal.token_version,
            "iat": now,
            "exp": expires,
            "typ": "access",
        }
        return jwt.encode(payload, self._signing_key, algorithm="HS256"), expires

    def decode_access_token(self, token: str) -> dict[str, Any]:
        payload = jwt.decode(
            token,
            self._signing_key,
            algorithms=["HS256"],
            options={"require": ["sub", "exp", "iat", "typ", "ver"]},
        )
        if payload.get("typ") != "access":
            raise jwt.InvalidTokenError("wrong token type")
        return payload


def mask_personal_text(value: str) -> str:
    """Mask names, phone-like identifiers and addresses before API/audit output."""
    stripped = value.strip()
    if len(stripped) <= 2:
        return stripped[:1] + "*" if stripped else ""
    if len(stripped) <= 6:
        return stripped[0] + "*" * (len(stripped) - 2) + stripped[-1]
    return stripped[:2] + "*" * (len(stripped) - 4) + stripped[-2:]
