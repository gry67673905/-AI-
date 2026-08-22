from __future__ import annotations

from uuid import UUID


class ServiceError(Exception):
    def __init__(self, code: str, message: str, status_code: int, request_id: UUID | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.request_id = request_id


class DatabaseUnavailable(ServiceError):
    def __init__(self, request_id: UUID | None = None):
        super().__init__("database_unavailable", "数据库暂不可用，请稍后重试", 503, request_id)


class LLMUnavailable(ServiceError):
    def __init__(self, request_id: UUID | None = None):
        super().__init__("llm_unavailable", "智能问答服务暂不可用，请稍后重试", 502, request_id)


class AuthenticationRequired(ServiceError):
    def __init__(self, message: str = "请先登录"):
        super().__init__("authentication_required", message, 401)


class PermissionDenied(ServiceError):
    def __init__(self, message: str = "无权执行此操作"):
        super().__init__("permission_denied", message, 403)


class ResourceNotFound(ServiceError):
    def __init__(self, resource: str = "资源"):
        super().__init__("not_found", f"{resource}不存在", 404)


class ConflictError(ServiceError):
    def __init__(
        self, message: str, code: str = "conflict", detail: object | None = None
    ):
        super().__init__(code, message, 409)
        self.detail = detail


class BusinessValidationError(ServiceError):
    def __init__(self, message: str, detail: object | None = None):
        super().__init__("business_validation_failed", message, 422)
        self.detail = detail


class DependencyUnavailable(ServiceError):
    def __init__(self, dependency: str):
        super().__init__(f"{dependency}_unavailable", f"{dependency} 暂不可用", 503)
