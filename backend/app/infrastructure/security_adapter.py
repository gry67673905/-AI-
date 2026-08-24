from __future__ import annotations

import jwt

from app.application.dtos import Principal
from app.application.ports import TokenValidationError
from app.security import (
    TokenCodec,
    hash_password,
    mask_personal_text,
    new_refresh_token,
    redact_pii_text,
    redact_sensitive,
    verify_password,
)


class LocalSecurityAdapter:
    def __init__(self, signing_key: str, access_minutes: int) -> None:
        self._codec = TokenCodec(signing_key, access_minutes)

    @staticmethod
    def hash_password(password: str) -> str:
        return hash_password(password)

    @staticmethod
    def verify_password(password: str, encoded: str) -> bool:
        return verify_password(password, encoded)

    def issue_access_token(self, principal: Principal):
        return self._codec.issue_access_token(principal)

    def decode_access_token(self, token: str):
        try:
            return self._codec.decode_access_token(token)
        except jwt.InvalidTokenError as exc:
            raise TokenValidationError("访问令牌无效") from exc

    @staticmethod
    def new_refresh_token() -> str:
        return new_refresh_token()

    @staticmethod
    def mask_personal_text(value: str) -> str:
        return mask_personal_text(value)

    @staticmethod
    def redact_public_text(value: str) -> str:
        redacted = redact_sensitive(value)
        return redacted if isinstance(redacted, str) else redact_pii_text(str(redacted))
