"""Backward-compatible typed facade for the application chat coordinator."""

from __future__ import annotations

from typing import Protocol

from app.application.dtos import (
    ChatCommand,
    ChatExecutionContext,
    ChatResult,
    Principal,
)
from app.boundaries.chat_mapping import to_chat_command, to_chat_response
from app.schemas import ChatRequest, ChatResponse


class ChatCoordinatorPort(Protocol):
    async def chat(
        self,
        payload: ChatCommand,
        principal: Principal | None = None,
        execution_context: ChatExecutionContext | None = None,
    ) -> ChatResult: ...


async def handle_chat(
    payload: ChatRequest,
    coordinator: ChatCoordinatorPort,
    execution_context: ChatExecutionContext | None = None,
    principal: Principal | None = None,
) -> ChatResponse:
    """Delegate legacy callers to the typed application use case."""
    result = await coordinator.chat(
        to_chat_command(payload), principal, execution_context
    )
    return to_chat_response(result)
