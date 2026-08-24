from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class MetaStudioMessageRequest(BaseModel):
    # Huawei may add message metadata (for example, a role) independently of
    # the documented content field.  The callback only consumes content, so
    # ignoring bounded unknown metadata is safer than coupling availability to
    # a vendor-side additive change.
    model_config = ConfigDict(extra="ignore")

    content: str = Field(min_length=1, max_length=4096)

    @field_validator("content")
    @classmethod
    def reject_blank_content(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("content must not be blank")
        return value


class MetaStudioExtendRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    client_id: str | None = Field(default=None, max_length=128)
    city: str | None = Field(default=None, max_length=128)
    extra_json_param: str | None = Field(default=None, max_length=4096)
    question_param: str | None = Field(default=None, max_length=4096)


class MetaStudioLlmRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    # Five-turn mode sends four prior question/answer pairs plus the current
    # question.  Rejecting larger bodies prevents an upstream configuration
    # mistake from becoming an unbounded prompt or persistence write.
    messages: list[MetaStudioMessageRequest] = Field(min_length=1, max_length=9)
    app_id: str = Field(min_length=1, max_length=128)
    user: str = Field(min_length=1, max_length=256)
    session_id: str = Field(min_length=1, max_length=256)
    is_stream: bool = False
    extend_param: MetaStudioExtendRequest | None = None

    @field_validator("extend_param", mode="before")
    @classmethod
    def accept_vendor_extend_param_shape(cls, value: Any) -> Any:
        """Accept the object contract plus the SDK's JSON-string wire shape.

        Huawei documents an object on the callback, while its Web SDK accepts
        ``extendParamStr``.  Some service paths preserve that JSON string.  It
        is parsed only within a tight bound, must decode to an object, and is
        then passed through ``MetaStudioExtendRequest`` so only whitelisted,
        length-bounded fields survive.
        """

        if value is None:
            return None
        if isinstance(value, str):
            if value == "":
                return None
            if len(value) > 4096:
                raise ValueError("extend_param string is too long")
            try:
                decoded = json.loads(value)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ValueError("extend_param must contain a JSON object") from exc
            if not isinstance(decoded, dict):
                raise ValueError("extend_param must contain a JSON object")
            return decoded
        if not isinstance(value, dict):
            raise ValueError("extend_param must be an object")
        return value


class MetaStudioClientSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class MetaStudioClientSessionResponse(BaseModel):
    session_id: UUID
    once_code: str
    robot_id: str
    server_address: str
    expires_at: datetime


class MetaStudioIntentExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    chat_id: str = Field(min_length=1, max_length=256)


class MetaStudioIntentExchangeResponse(BaseModel):
    intent_id: UUID
    type: str
    label: str
    section: str
    prefill: dict[str, Any]
    requires_confirmation: bool = True
