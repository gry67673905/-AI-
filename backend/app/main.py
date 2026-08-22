from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Header, Request, Response
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.errors import AuthenticationRequired, DatabaseUnavailable, ServiceError
from app.domain.policies import DomainRuleViolation
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ErrorBody,
    ErrorResponse,
    ReadinessResponse,
)
from app.services import AppServices
from app.boundaries.chat_mapping import to_chat_command, to_chat_response
from app.boundaries.http import build_business_router


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
                detail=getattr(exc, "detail", None),
            )
        )
        return JSONResponse(status_code=exc.status_code, content=body.model_dump(mode="json"))

    @application.exception_handler(SQLAlchemyError)
    async def database_error_handler(_: Request, __: SQLAlchemyError) -> JSONResponse:
        exc = DatabaseUnavailable()
        body = ErrorResponse(
            error=ErrorBody(
                code=exc.code,
                message=exc.message,
                request_id=exc.request_id,
            )
        )
        return JSONResponse(
            status_code=exc.status_code,
            content=body.model_dump(mode="json"),
        )

    @application.exception_handler(DomainRuleViolation)
    async def domain_rule_error_handler(
        _: Request, exc: DomainRuleViolation
    ) -> JSONResponse:
        validation = ServiceError(
            "business_validation_failed",
            "业务规则结构或数据类型无效",
            422,
        )
        body = ErrorResponse(
            error=ErrorBody(
                code=validation.code,
                message=validation.message,
                detail={"reason": str(exc)},
            )
        )
        return JSONResponse(
            status_code=validation.status_code,
            content=body.model_dump(mode="json"),
        )

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
    async def chat(
        payload: ChatRequest,
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> ChatResponse:
        services = request.app.state.services
        principal = None
        business = services.business
        if authorization:
            scheme, _, token = authorization.partition(" ")
            if scheme.lower() != "bearer" or not token:
                raise AuthenticationRequired("Authorization 格式无效")
            principal = await business.auth.authenticate(token)
        if payload.application_id is not None and principal is None:
            raise AuthenticationRequired("查询办件状态必须登录")
        result = await business.consultations.chat(
            to_chat_command(payload), principal
        )
        return to_chat_response(result)

    application.include_router(build_business_router())

    return application


app = create_app()
