from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.chat import handle_chat
from app.config import get_settings
from app.errors import ServiceError
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ErrorBody,
    ErrorResponse,
    ReadinessResponse,
)
from app.services import AppServices


def create_app(services_override: Any | None = None) -> FastAPI:
    settings = get_settings()
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    @asynccontextmanager
    async def lifespan(application: FastAPI):
        services = services_override or AppServices(settings)
        application.state.services = services
        if hasattr(services, "startup"):
            await services.startup()
        try:
            yield
        finally:
            if hasattr(services, "shutdown"):
                await services.shutdown()

    application = FastAPI(
        title="智慧政务助手 API",
        version="0.1.0",
        lifespan=lifespan,
    )

    @application.exception_handler(ServiceError)
    async def service_error_handler(_: Request, exc: ServiceError) -> JSONResponse:
        body = ErrorResponse(
            error=ErrorBody(
                code=exc.code,
                message=exc.message,
                request_id=exc.request_id,
            )
        )
        return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))

    @application.get("/health/live")
    async def live() -> dict[str, str]:
        return {"status": "ok", "service": settings.app_name}

    @application.get("/health/ready", response_model=ReadinessResponse)
    async def ready(request: Request, response: Response) -> ReadinessResponse:
        checks = await request.app.state.services.readiness()
        is_ready = all(check.status == "ok" for check in checks.values())
        if not is_ready:
            response.status_code = 503
        return ReadinessResponse(status="ready" if is_ready else "not_ready", checks=checks)

    @application.post(
        "/api/v1/chat",
        response_model=ChatResponse,
        responses={
            502: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
        },
    )
    async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
        return await handle_chat(payload, request.app.state.services)

    return application


app = create_app()

