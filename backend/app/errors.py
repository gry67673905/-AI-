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

