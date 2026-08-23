from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import PurePath
from typing import Any, Awaitable, Callable
from uuid import UUID, uuid4

from app.application.dtos import (
    ChatCommand,
    ChatExecutionContext,
    ChatResult,
    KnowledgeSearchResult,
    Principal,
    SourceData,
    ToolCallData,
)
from app.application.ports import (
    BusinessRepositoryPort,
    ChatModelPort,
    ChatPersistencePort,
    DeliveryProviderPort,
    GovernmentToolRetrievalPort,
    KnowledgeRetrievalPort,
    KnowledgeParserPort,
    ObjectStorePort,
    PaymentProviderPort,
    PublicRetrievalCachePort,
    SecurityPort,
    SmsProviderPort,
    TokenValidationError,
    VectorIndexPort,
    VerificationProviderPort,
)
from app.domain.enums import (
    ApplicantType,
    AppointmentStatus,
    ApplicationStatus,
    DeliveryStatus,
    Role,
    ServiceStatus,
)
from app.domain.policies import (
    AssignmentPolicy,
    DomainRuleViolation,
    EligibilityEvaluator,
    FormValidationService,
    GroundedAnswerPolicy,
    JsonRuleEvaluator,
    MaterialRuleEngine,
    ReviewDecisionPolicy,
    ServiceMatcher,
)
from app.errors import (
    AuthenticationRequired,
    BusinessValidationError,
    ConflictError,
    DependencyUnavailable,
    LLMUnavailable,
    PermissionDenied,
)
class AuthCoordinator:
    def __init__(
        self,
        repository: BusinessRepositoryPort,
        security: SecurityPort,
        sms: SmsProviderPort,
        refresh_days: int,
        demo_code: str,
    ) -> None:
        self.repository = repository
        self.security = security
        self.sms = sms
        self.refresh_days = refresh_days
        self.demo_code = demo_code

    async def request_code(self, destination: str, purpose: str) -> dict[str, object]:
        return await self.sms.send_code(destination, purpose)

    async def register(
        self, username: str, password: str, display_name: str,
        applicant_type: ApplicantType, verification_code: str,
    ) -> dict[str, Any]:
        if verification_code != self.demo_code:
            raise BusinessValidationError("演示验证码不正确")
        record = await self.repository.create_account(
            username, self.security.hash_password(password), display_name, applicant_type,
        )
        return await self._issue(record)

    async def login(self, username: str, password: str) -> dict[str, Any]:
        record = await self.repository.get_account_by_username(username)
        if record is None or not self.security.verify_password(password, record.password_hash):
            raise AuthenticationRequired("用户名或密码错误")
        if not record.active:
            raise PermissionDenied("账号已冻结")
        return await self._issue(record)

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        record = await self.repository.consume_refresh_token(refresh_token)
        if record is None or not record.active:
            raise AuthenticationRequired("刷新令牌无效或已过期")
        return await self._issue(record)

    async def logout(self, refresh_token: str) -> dict[str, str]:
        await self.repository.revoke_refresh_token(refresh_token)
        return {"status": "ok"}

    async def authenticate(self, token: str) -> Principal:
        try:
            claims = self.security.decode_access_token(token)
            account_id = UUID(str(claims["sub"]))
        except (TokenValidationError, ValueError, KeyError) as exc:
            raise AuthenticationRequired("访问令牌无效或已过期") from exc
        record = await self.repository.get_account_record(account_id)
        if record is None or not record.active or int(claims["ver"]) != record.token_version:
            raise AuthenticationRequired("访问令牌已失效")
        return Principal(
            account_id=record.id, username=record.username, display_name=record.display_name,
            role=Role(record.role), applicant_type=ApplicantType(record.applicant_type) if record.applicant_type else None,
            token_version=record.token_version, department_id=record.department_id,
        )

    async def me(self, principal: Principal) -> dict[str, Any]:
        return await self.repository.get_account_view(principal.account_id)

    async def _issue(self, record: Any) -> dict[str, Any]:
        principal = Principal(
            account_id=record.id, username=record.username, display_name=record.display_name,
            role=Role(record.role), applicant_type=ApplicantType(record.applicant_type) if record.applicant_type else None,
            token_version=record.token_version, department_id=record.department_id,
        )
        access, expires = self.security.issue_access_token(principal)
        refresh = self.security.new_refresh_token()
        await self.repository.save_refresh_token_if_current(
            record.id,
            record.token_version,
            refresh,
            datetime.now(timezone.utc) + timedelta(days=self.refresh_days),
        )
        user = await self.repository.get_account_view(record.id)
        return {
            "access_token": access, "refresh_token": refresh, "token_type": "bearer",
            "expires_in": max(1, int((expires - datetime.now(timezone.utc)).total_seconds())),
            "user": user,
        }


class IdempotencyCoordinator:
    def __init__(self, repository: BusinessRepositoryPort) -> None:
        self.repository = repository
        self._locks_guard = asyncio.Lock()
        self._locks: dict[tuple[UUID, str, str], tuple[asyncio.Lock, int]] = {}

    async def _retain_lock(self, lock_key: tuple[UUID, str, str]) -> asyncio.Lock:
        async with self._locks_guard:
            lock, users = self._locks.get(lock_key, (asyncio.Lock(), 0))
            self._locks[lock_key] = (lock, users + 1)
            return lock

    async def _release_lock(self, lock_key: tuple[UUID, str, str]) -> None:
        async with self._locks_guard:
            current = self._locks.get(lock_key)
            if current is None:
                return
            lock, users = current
            if users <= 1:
                self._locks.pop(lock_key, None)
            else:
                self._locks[lock_key] = (lock, users - 1)

    async def execute(
        self, actor_id: UUID, scope: str, key: str, payload: Any,
        operation: Callable[[], Awaitable[dict[str, Any]]],
    ) -> dict[str, Any]:
        if not key or len(key) > 128:
            raise BusinessValidationError("必须提供有效的 Idempotency-Key")
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
        digest = hashlib.sha256(encoded.encode("utf-8")).hexdigest()
        lock_key = (actor_id, scope, key)
        lock = await self._retain_lock(lock_key)
        try:
            async with lock:
                # Recheck after acquiring the per-key lock. This prevents two
                # concurrent requests in the local single-worker deployment from
                # both executing the side effect before the database unique key
                # can arbitrate the idempotency record.
                transactional = getattr(
                    self.repository, "execute_idempotent", None
                )
                if callable(transactional):
                    return await transactional(
                        actor_id, scope, key, digest, operation
                    )
                existing = await self.repository.get_idempotent(actor_id, scope, key, digest)
                if existing is not None:
                    return existing
                result = await operation()
                return await self.repository.store_idempotent(actor_id, scope, key, digest, result)
        finally:
            await self._release_lock(lock_key)


class CatalogCoordinator:
    def __init__(self, repository: BusinessRepositoryPort) -> None:
        self.repository = repository
        self.eligibility = EligibilityEvaluator()
        self.materials = MaterialRuleEngine()

    async def search(self, query: str | None = None) -> dict[str, Any]:
        items = await self.repository.list_services(query)
        return {"items": items, "total": len(items)}

    async def details(self, service_id: UUID) -> dict[str, Any]:
        return await self.repository.get_service_bundle(service_id)

    async def evaluate_eligibility(self, service_id: UUID, answers: dict[str, Any]) -> dict[str, Any]:
        bundle = await self.repository.get_service_bundle(service_id)
        rules = [(item["rule"], item["failure_message"]) for item in bundle["eligibility_rules"]]
        result = self.eligibility.evaluate(rules, answers)
        return {
            "service_id": service_id, "outcome": result.outcome,
            "reasons": list(result.reasons), "missing_fields": list(result.missing_fields),
            "disclaimer": result.disclaimer, "demo_data": True,
        }

    async def evaluate_materials(self, service_id: UUID, answers: dict[str, Any]) -> dict[str, Any]:
        _, entities = await self.repository.get_material_entities(service_id)
        decisions = self.materials.classify(entities, answers)
        items = [{"code": item.code, "name": item.name, "category": item.category, "trigger_reason": item.reason} for item in decisions]
        return {"items": items, "total": len(items), "demo_data": True}


class ConsultationCoordinator:
    """Coordinates the complete grounded chat use case through application ports."""

    def __init__(
        self,
        repository: BusinessRepositoryPort,
        persistence: ChatPersistencePort,
        cache: PublicRetrievalCachePort,
        government_tools: GovernmentToolRetrievalPort,
        knowledge: KnowledgeRetrievalPort,
        model: ChatModelPort,
        security: SecurityPort,
    ) -> None:
        self.repository = repository
        self.persistence = persistence
        self.cache = cache
        self.government_tools = government_tools
        self.knowledge = knowledge
        self.model = model
        self.security = security
        self.matcher = ServiceMatcher()
        self.grounding = GroundedAnswerPolicy()

    @staticmethod
    def _deduplicate(values: list[str]) -> list[str]:
        return list(dict.fromkeys(values))

    @staticmethod
    def _suggested_actions(context: ChatExecutionContext) -> list[dict[str, Any]]:
        action_type = "SELECT_SERVICE" if context.clarification_required else "VIEW_SERVICE"
        return [
            {
                "type": action_type,
                "service_id": str(item["id"]),
                "label": item["title"],
            }
            for item in context.candidates
        ]

    def _local_catalog_source(self, context: ChatExecutionContext) -> SourceData | None:
        """Build a source from allowlisted public catalogue fields only."""
        service = context.public_service
        if service is None:
            return None

        title = self.security.redact_public_text(str(service.get("title", "")).strip())
        service_id = str(service.get("id", "")).strip()
        if not title or not service_id:
            return None

        public_parts = [f"事项名称：{title}"]
        code = self.security.redact_public_text(str(service.get("code", "")).strip())
        summary = self.security.redact_public_text(
            str(service.get("summary", "")).strip()
        )
        if code:
            public_parts.append(f"事项编码：{code}")
        if summary:
            public_parts.append(f"事项简介：{summary}")
        public_parts.append("数据性质：本地公开演示事项目录")
        return SourceData(
            kind="local_catalog",
            title=f"{title}（本地演示事项）",
            reference=f"local-catalog://services/{service_id}",
            excerpt="；".join(public_parts),
        )

    @staticmethod
    def _effective_sources(sources: list[SourceData]) -> list[SourceData]:
        return [
            source
            for source in sources
            if source.title.strip()
            and source.reference.strip()
            and source.excerpt.strip()
        ]

    async def _search_knowledge(self, query: str) -> KnowledgeSearchResult:
        search_with_warnings = getattr(
            self.knowledge, "search_with_warnings", None
        )
        if callable(search_with_warnings):
            return await search_with_warnings(query)
        return KnowledgeSearchResult(sources=await self.knowledge.search(query))

    async def _save_answer(
        self,
        session_id: UUID,
        request_id: UUID,
        answer: str,
        sources: list[SourceData],
        tool_calls: list[ToolCallData],
        cache_hit: bool,
        warnings: list[str],
    ) -> None:
        await self.persistence.save_assistant_result(
            session_id,
            request_id,
            answer,
            sources,
            tool_calls,
            cache_hit,
            warnings,
        )

    async def candidate_services(self, question: str) -> dict[str, Any]:
        services = await self.repository.list_services(question)
        items, ambiguous = self.matcher.match(question, services)
        return {
            "items": items,
            "total": len(items),
            "clarification_required": ambiguous,
            "notice": "候选来自公开演示事项目录；存在歧义时不会默认选择第一项。",
        }

    async def list(self, principal: Principal) -> dict[str, Any]:
        if principal.role is not Role.CITIZEN:
            raise PermissionDenied("咨询历史仅向群众账号开放")
        items = await self.repository.list_consultations(principal.account_id)
        return {"items": items, "total": len(items)}

    async def feedback(
        self, principal: Principal, session_id: UUID, rating: int,
        comment: str | None,
    ) -> dict[str, Any]:
        if principal.role is not Role.CITIZEN:
            raise PermissionDenied("咨询反馈仅向群众账号开放")
        return await self.repository.create_feedback(
            principal.account_id, session_id, rating, comment
        )

    async def prepare_chat_context(
        self,
        question: str,
        service_id: UUID | None,
        application_id: UUID | None,
        principal: Principal | None,
    ) -> ChatExecutionContext:
        candidate_result = await self.candidate_services(question)
        candidates = candidate_result["items"]
        clarification_required = bool(candidate_result["clarification_required"])
        public_service: dict[str, Any] | None = None
        private_case: dict[str, Any] | None = None

        if application_id is not None:
            if principal is None:
                raise AuthenticationRequired("查询办件状态必须登录")
            application = await self.repository.get_application_case_authorized(
                application_id,
                principal.account_id,
                principal.role,
                principal.department_id,
            )
            if service_id is not None and application["service_id"] != service_id:
                raise ConflictError("service_id 与 application_id 对应事项不一致")
            service_id = application["service_id"]
            public_service = {
                "id": application["service_id"],
                "external_item_id": application["external_item_id"],
                "code": application["service_code"],
                "title": application["service_title"],
                "summary": application["service_summary"],
                "demo_data": True,
            }
            candidates = [public_service]
            clarification_required = False
            private_case = {
                "application_id": str(application_id),
                "service_title": application["service_title"],
                "status": application["status"],
            }

        elif service_id is not None:
            bundle = await self.repository.get_service_bundle(service_id)
            public_service = {
                "id": bundle["id"],
                "external_item_id": bundle["external_item_id"],
                "code": bundle["code"],
                "title": bundle["title"],
                "summary": bundle["summary"],
                "demo_data": True,
            }
            candidates = [public_service]
            clarification_required = False

        return ChatExecutionContext(
            owner_account_id=principal.account_id if principal is not None else None,
            external_item_id=(public_service or {}).get("external_item_id"),
            public_service=public_service,
            private_case=private_case,
            candidates=candidates,
            clarification_required=clarification_required,
        )

    async def chat(
        self,
        payload: ChatCommand,
        principal: Principal | None = None,
        execution_context: ChatExecutionContext | None = None,
    ) -> ChatResult:
        """Run one bounded chat turn without exposing private case data to retrieval."""
        request_id = uuid4()
        session_id = payload.session_id or uuid4()
        context = execution_context or await self.prepare_chat_context(
            payload.message,
            payload.service_id,
            payload.application_id,
            principal,
        )
        safe_public_question = self.security.redact_public_text(payload.message)
        await self.persistence.save_user_message(
            session_id,
            request_id,
            payload.message,
            context.owner_account_id,
        )

        if context.private_case is not None:
            status_labels = {
                "DRAFT": "草稿",
                "SUBMITTED": "已提交",
                "IN_REVIEW": "审核中",
                "NEEDS_SUPPLEMENT": "待补正",
                "REJECTED": "已驳回",
                "AWAITING_PAYMENT": "待模拟缴费",
                "PROCESSING": "办理中",
                "COMPLETED": "已完成",
                "WITHDRAWN": "已撤回",
                "DISCARDED": "已丢弃",
            }
            status = str(context.private_case["status"])
            title = str(context.private_case["service_title"])
            answer = (
                f"你查询的“{title}”演示办件当前状态为："
                f"{status_labels.get(status, status)}。该状态来自本地授权数据库查询，"
                "未发送给大模型；办理结果仅用于联调演示。"
            )
            warnings = ["private_case_local_only: 办件状态未进入公共缓存或大模型"]
            await self._save_answer(
                session_id, request_id, answer, [], [], False, warnings
            )
            return ChatResult(
                request_id=request_id,
                session_id=session_id,
                answer=answer,
                sources=[],
                tool_calls=[],
                cache_hit=False,
                warnings=warnings,
                candidate_services=context.candidates,
                suggested_actions=self._suggested_actions(context),
                clarification_required=False,
            )

        if context.clarification_required and context.candidates:
            names = "、".join(item["title"] for item in context.candidates)
            answer = (
                f"找到多个可能的演示事项：{names}。请先选择其中一个事项，"
                "我再查询对应材料、流程和窗口；不会默认替你选择第一项。"
            )
            warnings = ["clarification_required: 请选择具体事项后继续"]
            await self._save_answer(
                session_id, request_id, answer, [], [], False, warnings
            )
            return ChatResult(
                request_id=request_id,
                session_id=session_id,
                answer=answer,
                sources=[],
                tool_calls=[],
                cache_hit=False,
                warnings=warnings,
                candidate_services=context.candidates,
                suggested_actions=self._suggested_actions(context),
                clarification_required=True,
            )

        warnings: list[str] = []
        cache_hit = False
        sources: list[SourceData] = []
        tool_calls: list[ToolCallData] = []
        unmapped_public_service = bool(
            context.public_service is not None and context.external_item_id is None
        )
        public_context_id: str | int | None = context.external_item_id
        if unmapped_public_service:
            public_context_id = f"local:{context.public_service['id']}"
            warnings.append(
                "mcp_unmapped: 该本地事项尚未映射外部演示目录，已跳过政务工具检索"
            )

        try:
            cached = await self.cache.get(payload.message, public_context_id)
        except Exception:
            cached = None
            warnings.append("redis_unavailable: 缓存服务暂不可用，已绕过缓存")

        if cached is not None:
            cache_hit = True
            sources, tool_calls = cached
        else:
            retrieval_query = safe_public_question
            if context.public_service:
                retrieval_query = self.security.redact_public_text(
                    f"{context.public_service['title']} "
                    f"{context.public_service.get('code', '')}"
                ).strip()
            if unmapped_public_service:
                mcp_result: object = ([], [], [])
                (knowledge_result,) = await asyncio.gather(
                    self._search_knowledge(retrieval_query),
                    return_exceptions=True,
                )
            else:
                mcp_result, knowledge_result = await asyncio.gather(
                    self.government_tools.retrieve(
                        retrieval_query,
                        context.external_item_id,
                        context.public_service is None,
                    ),
                    self._search_knowledge(retrieval_query),
                    return_exceptions=True,
                )
            if isinstance(mcp_result, BaseException):
                warnings.append("mcp_unavailable: 政务工具服务暂不可用")
            else:
                mcp_sources, tool_calls, mcp_warnings = mcp_result
                sources.extend(mcp_sources)
                warnings.extend(mcp_warnings)
            if isinstance(knowledge_result, BaseException):
                warnings.append("milvus_unavailable: 知识检索服务暂不可用")
            else:
                sources.extend(knowledge_result.sources)
                warnings.extend(knowledge_result.warnings)

            if not warnings:
                try:
                    await self.cache.set(
                        payload.message, sources, tool_calls, public_context_id
                    )
                except Exception:
                    warnings.append("redis_unavailable: 缓存服务暂不可用，已绕过缓存")

        local_catalog_source = self._local_catalog_source(context)
        if local_catalog_source is not None and all(
            source.reference != local_catalog_source.reference for source in sources
        ):
            sources.append(local_catalog_source)
        sources = self._effective_sources(sources)
        if any(source.reference.startswith("ragdb://") for source in sources):
            warnings.append(
                "rag_group_demo_unverified: 组内演示语料、时效待核验，请以官方最新要求为准"
            )

        if not self.grounding.may_answer(len(sources)):
            answer = (
                "当前没有检索到可核验的公开演示事项或知识依据，"
                "暂不调用大模型生成办理结论。请补充具体事项名称或稍后重试。"
            )
            warnings.append(
                "grounding_unavailable: 未检索到可核验的公开依据，已跳过大模型"
            )
            warnings = self._deduplicate(warnings)
            await self._save_answer(
                session_id,
                request_id,
                answer,
                sources,
                tool_calls,
                cache_hit,
                warnings,
            )
            return ChatResult(
                request_id=request_id,
                session_id=session_id,
                answer=answer,
                sources=sources,
                tool_calls=tool_calls,
                cache_hit=cache_hit,
                warnings=warnings,
                candidate_services=context.candidates,
                suggested_actions=self._suggested_actions(context),
                clarification_required=False,
            )

        try:
            model_question = safe_public_question
            if context.public_service:
                model_question += (
                    f"\n已选择公开演示事项：{context.public_service['title']}"
                )
                if context.external_item_id is not None:
                    model_question += f"（外部演示事项ID {context.external_item_id}）"
            answer = await self.model.answer(
                model_question, sources, tool_calls, request_id=request_id
            )
        except LLMUnavailable:
            raise
        except Exception as exc:
            raise LLMUnavailable(request_id) from exc

        warnings = self._deduplicate(warnings)
        await self._save_answer(
            session_id,
            request_id,
            answer,
            sources,
            tool_calls,
            cache_hit,
            warnings,
        )
        return ChatResult(
            request_id=request_id,
            session_id=session_id,
            answer=answer,
            sources=sources,
            tool_calls=tool_calls,
            cache_hit=cache_hit,
            warnings=warnings,
            candidate_services=context.candidates,
            suggested_actions=self._suggested_actions(context),
            clarification_required=False,
        )


class ApplicationCoordinator:
    _allowed_types = {"application/pdf", "image/jpeg", "image/png"}

    def __init__(
        self, repository: BusinessRepositoryPort, object_store: ObjectStorePort,
        idempotency: IdempotencyCoordinator, max_material_bytes: int,
    ) -> None:
        self.repository = repository
        self.object_store = object_store
        self.idempotency = idempotency
        self.max_material_bytes = max_material_bytes
        self.form_validator = FormValidationService()
        self.material_engine = MaterialRuleEngine()
        self.eligibility = EligibilityEvaluator()

    async def create_draft(self, principal: Principal, service_id: UUID, data: dict[str, Any]) -> dict[str, Any]:
        self._citizen(principal)
        return await self.repository.create_application(principal.account_id, service_id, data)

    async def list(self, principal: Principal) -> dict[str, Any]:
        items = await self.repository.list_applications(principal.account_id, principal.role, principal.department_id)
        return {"items": items, "total": len(items)}

    async def get(self, principal: Principal, application_id: UUID) -> dict[str, Any]:
        return await self.repository.get_application_view_authorized(
            application_id, principal.account_id, principal.role, principal.department_id
        )

    async def update_form(self, principal: Principal, application_id: UUID, data: dict[str, Any], version: int) -> dict[str, Any]:
        self._citizen(principal)
        return await self.repository.update_application_form(application_id, principal.account_id, data, version)

    async def upload_material(
        self, principal: Principal, application_id: UUID, requirement_code: str,
        filename: str, content_type: str, content: bytes,
    ) -> dict[str, Any]:
        self._citizen(principal)
        if content_type not in self._allowed_types:
            raise BusinessValidationError("材料仅支持 PDF/JPEG/PNG")
        if not content or len(content) > self.max_material_bytes:
            raise BusinessValidationError("材料必须非空且不超过 10MB")
        signatures = {
            "application/pdf": content.startswith(b"%PDF-"),
            "image/jpeg": content.startswith(b"\xff\xd8\xff"),
            "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        }
        if not signatures[content_type]:
            raise BusinessValidationError("材料内容与声明的文件类型不一致")
        await self.repository.preflight_material_upload(
            application_id, principal.account_id, requirement_code, content_type
        )
        safe_name = PurePath(filename).name[:255]
        digest = hashlib.sha256(content).hexdigest()
        object_key = f"applications/{application_id}/{uuid4().hex}"
        await self.object_store.put_bytes(self.object_store.materials_bucket, object_key, content, content_type)
        try:
            return await self.repository.add_material(
                application_id, principal.account_id, requirement_code, safe_name,
                object_key, content_type, len(content), digest,
            )
        except Exception:
            await self.object_store.delete(self.object_store.materials_bucket, object_key)
            raise

    async def download_material(
        self, principal: Principal, application_id: UUID, material_id: UUID
    ) -> tuple[bytes, dict[str, Any]]:
        metadata = await self.repository.get_material_authorized(
            application_id,
            material_id,
            principal.account_id,
            principal.role,
            principal.department_id,
        )
        content = await self.object_store.get_bytes(
            self.object_store.materials_bucket, metadata["object_key"]
        )
        if len(content) != metadata["size_bytes"] or hashlib.sha256(content).hexdigest() != metadata["sha256"]:
            raise ConflictError("材料完整性校验失败", "material_integrity_failed")
        return content, metadata

    async def timeline(
        self, principal: Principal, application_id: UUID
    ) -> dict[str, Any]:
        items = await self.repository.list_timeline(
            application_id,
            principal.account_id,
            principal.role,
            principal.department_id,
        )
        return {"items": items, "total": len(items)}

    async def submit(self, principal: Principal, application_id: UUID, version: int, key: str) -> dict[str, Any]:
        self._citizen(principal)

        async def operation() -> dict[str, Any]:
            app, config, uploaded, requirements, verification_passed = await self.repository.application_submission_context(application_id, principal.account_id)
            errors = self.form_validator.validate(config["form_schema"], app.form_data)
            eligibility_facts = dict(app.form_data)
            if verification_passed:
                verification = dict(eligibility_facts.get("verification", {}))
                verification["demo_identity_passed"] = True
                eligibility_facts["verification"] = verification
            eligibility = self.eligibility.evaluate(config["eligibility_rules"], eligibility_facts)
            decisions = self.material_engine.classify(requirements, app.form_data)
            missing = [item.code for item in decisions if item.category in {"REQUIRED", "CONDITIONAL_REQUIRED"} and item.code not in uploaded]
            undecidable = [item.code for item in decisions if item.category == "NEEDS_INFORMATION"]
            if errors or missing or undecidable:
                raise BusinessValidationError("表单或材料不完整", {"fields": errors, "missing_materials": missing, "undecidable_materials": undecidable})
            if eligibility.outcome != "ELIGIBLE":
                raise BusinessValidationError("资格预检尚未通过", {"outcome": eligibility.outcome, "reasons": list(eligibility.reasons), "missing_fields": list(eligibility.missing_fields), "disclaimer": eligibility.disclaimer})
            if config["requires_verification"] and not verification_passed:
                raise BusinessValidationError("请先完成本地模拟身份核验")
            if config["requires_appointment"] and not config["appointment_booked"]:
                raise BusinessValidationError("请先预约演示窗口和时段")
            return await self.repository.submit_application(application_id, principal.account_id, version)

        return await self.idempotency.execute(principal.account_id, f"application.submit:{application_id}", key, {"version": version}, operation)

    async def withdraw(self, principal: Principal, application_id: UUID, version: int, comment: str | None, key: str) -> dict[str, Any]:
        self._citizen(principal)
        return await self.idempotency.execute(
            principal.account_id, f"application.withdraw:{application_id}", key,
            {"version": version, "comment": comment},
            lambda: self.repository.transition_application(application_id, principal.account_id, principal.role, ApplicationStatus.WITHDRAWN, version, comment),
        )

    async def discard(self, principal: Principal, application_id: UUID, version: int, key: str) -> dict[str, Any]:
        self._citizen(principal)
        return await self.idempotency.execute(
            principal.account_id, f"application.discard:{application_id}", key, {"version": version},
            lambda: self.repository.transition_application(application_id, principal.account_id, principal.role, ApplicationStatus.DISCARDED, version),
        )

    @staticmethod
    def _citizen(principal: Principal) -> None:
        if principal.role is not Role.CITIZEN:
            raise PermissionDenied("该功能仅向个人或企业群众账号开放")


class ReviewCoordinator:
    def __init__(self, repository: BusinessRepositoryPort, idempotency: IdempotencyCoordinator) -> None:
        self.repository = repository
        self.idempotency = idempotency
        self.assignment_policy = AssignmentPolicy()
        self.decision_policy = ReviewDecisionPolicy()

    async def tasks(self, principal: Principal) -> dict[str, Any]:
        self._staff(principal)
        items = await self.repository.list_staff_tasks(principal.account_id, principal.department_id)
        return {"items": items, "total": len(items)}

    async def claim(self, principal: Principal, task_id: UUID, key: str) -> dict[str, Any]:
        self._staff(principal)
        task_department = await self.repository.get_review_task_department(task_id)
        if not self.assignment_policy.can_claim(
            principal.role,
            str(principal.department_id) if principal.department_id else None,
            str(task_department),
        ):
            raise PermissionDenied("只能认领所属部门审核任务")
        return await self.idempotency.execute(principal.account_id, f"review.claim:{task_id}", key, {}, lambda: self.repository.claim_task(task_id, principal.account_id, principal.department_id))

    async def decide(
        self, principal: Principal, application_id: UUID, action: str,
        version: int, comment: str | None, require_payment: bool, key: str,
    ) -> dict[str, Any]:
        self._staff(principal)
        task_department = await self.repository.get_application_review_department(
            application_id
        )
        try:
            self.decision_policy.require_staff(
                principal.role,
                str(principal.department_id) if principal.department_id else None,
                str(task_department),
            )
        except DomainRuleViolation as exc:
            raise PermissionDenied("只能审核所属部门任务") from exc
        if action == "approve":
            require_payment = require_payment or await self.repository.application_requires_payment(application_id)
        targets = {
            "supplement": ApplicationStatus.NEEDS_SUPPLEMENT,
            "reject": ApplicationStatus.REJECTED,
            "approve": ApplicationStatus.AWAITING_PAYMENT if require_payment else ApplicationStatus.PROCESSING,
            "complete": ApplicationStatus.COMPLETED,
        }
        target = targets[action]
        return await self.idempotency.execute(
            principal.account_id, f"review.{action}:{application_id}", key,
            {"version": version, "comment": comment, "require_payment": require_payment},
            lambda: self.repository.transition_application(application_id, principal.account_id, principal.role, target, version, comment, require_assignee=True),
        )

    @staticmethod
    def _staff(principal: Principal) -> None:
        if principal.role is not Role.STAFF:
            raise PermissionDenied("该功能仅向工作人员开放")


class HandoffCoordinator:
    def __init__(
        self, repository: BusinessRepositoryPort,
        idempotency: IdempotencyCoordinator,
    ) -> None:
        self.repository = repository
        self.idempotency = idempotency

    async def create(self, principal: Principal, session_id: UUID, subject: str, department_id: UUID | None) -> dict[str, Any]:
        if principal.role is not Role.CITIZEN: raise PermissionDenied()
        return await self.repository.create_handoff(principal.account_id, session_id, subject, department_id)

    async def list(self, principal: Principal) -> dict[str, Any]:
        items = await self.repository.list_handoffs(principal.account_id, principal.role, principal.department_id)
        return {"items": items, "total": len(items)}

    async def add_message(
        self, principal: Principal, ticket_id: UUID, content: str
    ) -> dict[str, Any]:
        if principal.role not in {Role.CITIZEN, Role.STAFF}:
            raise PermissionDenied("当前角色不能发送人工咨询消息")
        return await self.repository.add_handoff_message(
            principal.account_id,
            principal.role,
            principal.department_id,
            ticket_id,
            content,
        )

    async def messages(
        self, principal: Principal, ticket_id: UUID
    ) -> dict[str, Any]:
        if principal.role not in {Role.CITIZEN, Role.STAFF}:
            raise PermissionDenied("当前角色不能查看人工咨询消息")
        items = await self.repository.list_handoff_messages(
            principal.account_id,
            principal.role,
            principal.department_id,
            ticket_id,
        )
        return {"items": items, "total": len(items)}

    async def resolve(self, principal: Principal, ticket_id: UUID) -> dict[str, Any]:
        if principal.role is not Role.STAFF:
            raise PermissionDenied("该功能仅向工作人员开放")
        return await self.repository.resolve_handoff(
            principal.account_id, principal.department_id, ticket_id
        )

    async def cancel(
        self, principal: Principal, ticket_id: UUID, key: str
    ) -> dict[str, Any]:
        if principal.role is not Role.CITIZEN:
            raise PermissionDenied("仅发起咨询的群众可以取消转人工")
        return await self.idempotency.execute(
            principal.account_id,
            f"handoff.cancel:{ticket_id}",
            key,
            {},
            lambda: self.repository.cancel_handoff(
                principal.account_id, ticket_id
            ),
        )


class AppointmentCoordinator:
    def __init__(self, repository: BusinessRepositoryPort, idempotency: IdempotencyCoordinator) -> None:
        self.repository = repository; self.idempotency = idempotency

    async def create(self, principal: Principal, service_id: UUID, window_id: UUID, slot_start: datetime, key: str) -> dict[str, Any]:
        self._citizen(principal)
        return await self.idempotency.execute(principal.account_id, "appointment.create", key, {"service_id": service_id, "window_id": window_id, "slot_start": slot_start}, lambda: self.repository.create_appointment(principal.account_id, service_id, window_id, slot_start))

    async def list(self, principal: Principal) -> dict[str, Any]:
        self._citizen(principal)
        items = await self.repository.list_appointments(principal.account_id)
        return {"items": items, "total": len(items)}

    async def cancel(
        self, principal: Principal, appointment_id: UUID, key: str
    ) -> dict[str, Any]:
        self._citizen(principal)
        return await self.idempotency.execute(
            principal.account_id,
            f"appointment.cancel:{appointment_id}",
            key,
            {},
            lambda: self.repository.cancel_appointment(
                principal.account_id, appointment_id
            ),
        )

    async def advance(
        self,
        principal: Principal,
        appointment_id: UUID,
        target: AppointmentStatus,
        key: str,
    ) -> dict[str, Any]:
        if principal.role not in {Role.STAFF, Role.ADMIN}:
            raise PermissionDenied("该功能仅向工作人员或管理员开放")
        return await self.idempotency.execute(
            principal.account_id,
            f"appointment.advance:{appointment_id}",
            key,
            {"status": target.value},
            lambda: self.repository.advance_appointment(
                principal.account_id,
                principal.role,
                principal.department_id,
                appointment_id,
                target,
            ),
        )

    @staticmethod
    def _citizen(principal: Principal) -> None:
        if principal.role is not Role.CITIZEN:
            raise PermissionDenied("预约功能仅向群众账号开放")


class PaymentCoordinator:
    def __init__(self, repository: BusinessRepositoryPort, provider: PaymentProviderPort, idempotency: IdempotencyCoordinator) -> None:
        self.repository = repository; self.provider = provider; self.idempotency = idempotency

    async def create(self, principal: Principal, application_id: UUID, key: str) -> dict[str, Any]:
        self._citizen(principal)
        return await self.idempotency.execute(principal.account_id, f"payment.create:{application_id}", key, {}, lambda: self.repository.create_payment(principal.account_id, application_id))

    async def pay(self, principal: Principal, payment_id: UUID, outcome: str, key: str) -> dict[str, Any]:
        self._citizen(principal)
        async def operation() -> dict[str, Any]:
            pending = await self.repository.mark_payment_pending(
                payment_id, principal.account_id
            )
            if pending["status"] == "SUCCEEDED":
                return pending
            provider = await self.provider.pay(outcome)
            return await self.repository.update_payment(payment_id, principal.account_id, outcome, str(provider["provider_reference"]))
        return await self.idempotency.execute(principal.account_id, f"payment.pay:{payment_id}", key, {"outcome": outcome}, operation)

    async def cancel(
        self, principal: Principal, payment_id: UUID, key: str
    ) -> dict[str, Any]:
        self._citizen(principal)
        return await self.idempotency.execute(
            principal.account_id,
            f"payment.cancel:{payment_id}",
            key,
            {},
            lambda: self.repository.cancel_payment(
                payment_id, principal.account_id
            ),
        )

    @staticmethod
    def _citizen(principal: Principal) -> None:
        if principal.role is not Role.CITIZEN:
            raise PermissionDenied("模拟缴费仅向群众账号开放")


class VerificationCoordinator:
    def __init__(
        self, repository: BusinessRepositoryPort,
        provider: VerificationProviderPort,
        idempotency: IdempotencyCoordinator,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.idempotency = idempotency

    async def create(
        self, principal: Principal, application_id: UUID, key: str
    ) -> dict[str, Any]:
        self._citizen(principal)
        return await self.idempotency.execute(
            principal.account_id,
            f"verification.create:{application_id}",
            key,
            {"application_id": application_id},
            lambda: self.repository.create_verification(
                principal.account_id,
                application_id,
                datetime.now(timezone.utc) + timedelta(minutes=10),
            ),
        )

    async def complete(
        self, principal: Principal, verification_id: UUID,
        outcome: str, key: str,
    ) -> dict[str, Any]:
        self._citizen(principal)

        async def operation() -> dict[str, Any]:
            await self.provider.verify(outcome)
            return await self.repository.complete_verification(
                principal.account_id, verification_id, outcome
            )

        return await self.idempotency.execute(
            principal.account_id,
            f"verification.complete:{verification_id}",
            key,
            {"outcome": outcome},
            operation,
        )

    @staticmethod
    def _citizen(principal: Principal) -> None:
        if principal.role is not Role.CITIZEN:
            raise PermissionDenied("模拟身份核验仅向群众账号开放")


class DeliveryCoordinator:
    def __init__(
        self, repository: BusinessRepositoryPort,
        provider: DeliveryProviderPort,
        security: SecurityPort,
        idempotency: IdempotencyCoordinator,
    ) -> None:
        self.repository = repository
        self.provider = provider
        self.security = security
        self.idempotency = idempotency

    async def create(
        self, principal: Principal, application_id: UUID,
        recipient: str, address: str, key: str,
    ) -> dict[str, Any]:
        if principal.role is not Role.CITIZEN:
            raise PermissionDenied("模拟邮寄仅向群众账号开放")

        async def operation() -> dict[str, Any]:
            existing = await self.repository.preflight_delivery(
                principal.account_id, application_id
            )
            if existing is not None:
                return existing
            provider = await self.provider.create()
            return await self.repository.create_delivery(
                principal.account_id,
                application_id,
                self.security.mask_personal_text(recipient),
                self.security.mask_personal_text(address),
                str(provider["provider_reference"]),
            )

        return await self.idempotency.execute(
            principal.account_id,
            f"delivery.create:{application_id}",
            key,
            {"recipient": recipient, "address": address},
            operation,
        )

    async def advance(
        self, principal: Principal, delivery_id: UUID,
        target: DeliveryStatus, key: str,
    ) -> dict[str, Any]:
        if principal.role not in {Role.STAFF, Role.ADMIN}:
            raise PermissionDenied("该功能仅向工作人员或管理员开放")
        return await self.idempotency.execute(
            principal.account_id,
            f"delivery.advance:{delivery_id}",
            key,
            {"status": target.value},
            lambda: self.repository.advance_delivery(
                principal.account_id,
                principal.role,
                principal.department_id,
                delivery_id,
                target,
            ),
        )

    async def cancel(
        self, principal: Principal, delivery_id: UUID, key: str
    ) -> dict[str, Any]:
        if principal.role is not Role.CITIZEN:
            raise PermissionDenied("仅办件申请人可以取消模拟邮寄")
        return await self.idempotency.execute(
            principal.account_id,
            f"delivery.cancel:{delivery_id}",
            key,
            {},
            lambda: self.repository.cancel_delivery(
                principal.account_id, delivery_id
            ),
        )


class KnowledgeIndexCoordinator:
    _allowed_extensions = {".pdf", ".docx", ".txt", ".md", ".markdown"}
    max_knowledge_bytes = 20 * 1024 * 1024

    def __init__(
        self, repository: BusinessRepositoryPort, object_store: ObjectStorePort,
        milvus: VectorIndexPort, parser: KnowledgeParserPort,
        idempotency: IdempotencyCoordinator,
        cache: PublicRetrievalCachePort | None = None,
    ) -> None:
        self.repository = repository
        self.object_store = object_store
        self.milvus = milvus
        self.parser = parser
        self.idempotency = idempotency
        self.cache = cache

    async def upload(self, principal: Principal, filename: str, content_type: str, content: bytes, title: str, source: str) -> dict[str, Any]:
        if principal.role is not Role.ADMIN: raise PermissionDenied()
        extension = PurePath(filename).suffix.lower()
        if extension not in self._allowed_extensions:
            raise BusinessValidationError("知识资料仅支持 PDF/DOCX/TXT/Markdown")
        if not content or len(content) > self.max_knowledge_bytes:
            raise BusinessValidationError("知识文件必须非空且不超过 20MB")
        try:
            text = (
                await asyncio.to_thread(self.parser.extract, extension, content)
            ).strip()
        except Exception as exc:
            # Parser exceptions may contain archive member names or local paths.
            # Expose one stable validation error without reflecting internals.
            raise BusinessValidationError("知识文件格式无效或无法解析") from exc
        if not text: raise BusinessValidationError("知识资料未提取到文本")
        document_id = "admin-" + hashlib.sha256(content).hexdigest()[:32]
        # A duplicate concurrent upload must never delete the canonical object
        # retained by the winning transaction, so every attempt owns a unique
        # temporary key until PostgreSQL selects the canonical one.
        object_key = (
            f"knowledge/{document_id}/{uuid4().hex}-"
            f"{PurePath(filename).name[:150]}"
        )
        await self.object_store.put_bytes(self.object_store.knowledge_bucket, object_key, content, content_type)
        chunks = self._chunks(text)
        try:
            job_id, rows, object_retained, job_status = await self.repository.create_knowledge_records(
                principal.account_id, document_id, title, source, text, object_key, chunks
            )
        except Exception:
            await self.object_store.delete(self.object_store.knowledge_bucket, object_key)
            raise
        if not object_retained:
            try:
                await self.object_store.delete(
                    self.object_store.knowledge_bucket, object_key
                )
            except Exception:
                # Failure to remove a redundant, upload-owned object must not
                # invalidate the canonical document or its index job.
                pass
        if job_status == "ACTIVE" or (
            not object_retained and job_status == "INDEXING"
        ):
            return {
                "document_id": document_id,
                "job_id": job_id,
                "status": job_status,
                "chunks": len(rows),
                "demo_data": True,
                "reused": True,
            }
        try:
            await self.milvus.index_chunks(rows)
        except Exception as exc:
            await self.repository.finish_knowledge_job(job_id, False, type(exc).__name__)
            await self._delete_failed_vectors(rows)
            raise ConflictError(
                "知识已保存，但向量索引失败，可稍后重试",
                "knowledge_index_failed",
                {"job_id": str(job_id)},
            ) from exc
        await self.repository.finish_knowledge_job(job_id, True)
        try:
            await self.milvus.activate_chunks(rows)
        except Exception as exc:
            await self.repository.finish_knowledge_job(
                job_id, False, type(exc).__name__
            )
            await self._delete_failed_vectors(rows)
            raise ConflictError(
                "知识已保存，但向量发布失败，可稍后重试",
                "knowledge_index_failed",
                {"job_id": str(job_id)},
            ) from exc
        await self._invalidate_public_cache()
        return {"document_id": document_id, "job_id": job_id, "status": "ACTIVE", "chunks": len(chunks), "demo_data": True}

    async def retry(
        self, principal: Principal, job_id: UUID, key: str
    ) -> dict[str, Any]:
        if principal.role is not Role.ADMIN:
            raise PermissionDenied("该功能仅向管理员开放")

        result = await self.idempotency.execute(
            principal.account_id,
            f"knowledge.retry:{job_id}",
            key,
            {},
            lambda: self._retry(principal, job_id),
        )
        if result.get("_index_failed"):
            # _retry returns a marker instead of raising inside the database
            # UoW so attempts, last_error and audit metadata are committed.
            raise ConflictError(
                "知识索引重试失败，可稍后再次重试",
                "knowledge_index_failed",
                {"job_id": str(job_id)},
            )
        return result

    async def _retry(self, principal: Principal, job_id: UUID) -> dict[str, Any]:
        chunks = await self.repository.prepare_knowledge_retry(
            principal.account_id, job_id
        )
        try:
            await self.milvus.index_chunks(chunks)
        except Exception as exc:
            await self.repository.finish_knowledge_job(
                job_id, False, type(exc).__name__
            )
            await self._delete_failed_vectors(chunks)
            return {
                "job_id": job_id,
                "status": "INDEX_FAILED",
                "chunks": len(chunks),
                "demo_data": True,
                "_index_failed": True,
            }
        await self.repository.finish_knowledge_job(job_id, True)
        try:
            await self.milvus.activate_chunks(chunks)
        except Exception as exc:
            await self.repository.finish_knowledge_job(
                job_id, False, type(exc).__name__
            )
            await self._delete_failed_vectors(chunks)
            return {
                "job_id": job_id,
                "status": "INDEX_FAILED",
                "chunks": len(chunks),
                "demo_data": True,
                "_index_failed": True,
            }
        await self._invalidate_public_cache()
        return {
            "job_id": job_id,
            "status": "ACTIVE",
            "chunks": len(chunks),
            "demo_data": True,
        }

    async def archive(
        self, principal: Principal, job_id: UUID, key: str
    ) -> dict[str, Any]:
        if principal.role is not Role.ADMIN:
            raise PermissionDenied("该功能仅向管理员开放")
        async def operation() -> dict[str, Any]:
            result = await self.repository.archive_knowledge(
                principal.account_id, job_id
            )
            chunk_ids = [str(item) for item in result.pop("_chunk_ids", [])]
            if chunk_ids:
                try:
                    await self.milvus.delete_chunks(chunk_ids)
                except Exception as exc:
                    raise DependencyUnavailable("milvus") from exc
            await self._invalidate_public_cache()
            return result

        return await self.idempotency.execute(
            principal.account_id,
            f"knowledge.archive:{job_id}",
            key,
            {},
            operation,
        )

    async def _delete_failed_vectors(
        self, chunks: list[dict[str, Any]]
    ) -> None:
        try:
            await self.milvus.delete_chunks(
                [str(item["id"]) for item in chunks if item.get("id")]
            )
        except Exception:
            # Staged vectors carry INDEXING and are excluded by the Milvus
            # search filter even if best-effort physical cleanup is delayed.
            pass

    async def _invalidate_public_cache(self) -> None:
        if self.cache is None:
            return
        try:
            await self.cache.invalidate_public()
        except Exception:
            # Redis is optional for business writes; stale public retrieval is
            # bounded by TTL and vectors still enforce ACTIVE at query time.
            pass

    @staticmethod
    def _chunks(text: str, size: int = 800, overlap: int = 100) -> list[str]:
        compact = "\n".join(line.strip() for line in text.splitlines() if line.strip())
        if len(compact) <= size: return [compact]
        return [compact[start:start + size] for start in range(0, len(compact), size - overlap) if compact[start:start + size]]


class AdminCoordinator:
    def __init__(
        self, repository: BusinessRepositoryPort,
        security: SecurityPort,
        idempotency: IdempotencyCoordinator,
    ) -> None:
        self.repository = repository
        self.security = security
        self.idempotency = idempotency
        self.rule_evaluator = JsonRuleEvaluator()

    @staticmethod
    def require(principal: Principal) -> None:
        if principal.role is not Role.ADMIN: raise PermissionDenied("该功能仅向管理员开放")

    def validate_rules(self, values: dict[str, Any]) -> None:
        try:
            FormValidationService.validate_schema(values.get("form_schema", {}))
            for item in values.get("eligibility_rules", []):
                self.rule_evaluator.validate(item.get("rule", item))
            for item in values.get("materials", []):
                if item.get("condition") is not None:
                    self.rule_evaluator.validate(item["condition"])
        except DomainRuleViolation as exc:
            raise BusinessValidationError(
                "事项规则结构无效", {"reason": str(exc)}
            ) from exc

    async def departments(self, principal: Principal) -> dict[str, Any]:
        self.require(principal)
        items = await self.repository.list_departments()
        return {"items": items, "total": len(items)}

    async def create_department(
        self, principal: Principal, code: str, name: str
    ) -> dict[str, Any]:
        self.require(principal)
        return await self.repository.create_department(
            principal.account_id, code, name
        )

    async def windows(
        self, principal: Principal, department_id: UUID | None
    ) -> dict[str, Any]:
        self.require(principal)
        items = await self.repository.list_windows(department_id)
        return {"items": items, "total": len(items)}

    async def create_window(
        self, principal: Principal, values: dict[str, Any]
    ) -> dict[str, Any]:
        self.require(principal)
        return await self.repository.create_window(principal.account_id, values)

    async def create_staff(
        self, principal: Principal, username: str, password: str,
        display_name: str, department_id: UUID, window_id: UUID | None,
    ) -> dict[str, Any]:
        self.require(principal)
        return await self.repository.create_staff_account(
            principal.account_id,
            username,
            self.security.hash_password(password),
            display_name,
            department_id,
            window_id,
        )

    async def accounts(self, principal: Principal) -> dict[str, Any]:
        self.require(principal)
        items = await self.repository.list_accounts()
        return {"items": items, "total": len(items)}

    async def set_account_status(
        self, principal: Principal, account_id: UUID, active: bool
    ) -> dict[str, Any]:
        self.require(principal)
        return await self.repository.set_account_active(
            principal.account_id, account_id, active
        )

    async def services(
        self, principal: Principal, query: str | None
    ) -> dict[str, Any]:
        self.require(principal)
        items = await self.repository.list_services(query, include_all=True)
        return {"items": items, "total": len(items)}

    async def create_service(
        self, principal: Principal, values: dict[str, Any]
    ) -> dict[str, Any]:
        self.require(principal)
        self.validate_rules(values)
        return await self.repository.create_service(principal.account_id, values)

    async def create_version(
        self, principal: Principal, service_id: UUID, values: dict[str, Any]
    ) -> dict[str, Any]:
        self.require(principal)
        self.validate_rules(values)
        return await self.repository.create_service_version(
            principal.account_id, service_id, values
        )

    async def lifecycle(
        self, principal: Principal, service_id: UUID, target: ServiceStatus,
        version_id: UUID | None, key: str,
    ) -> dict[str, Any]:
        self.require(principal)
        return await self.idempotency.execute(
            principal.account_id,
            f"service.lifecycle:{service_id}",
            key,
            {"target_status": target.value, "version_id": version_id},
            lambda: self.repository.transition_service(
                principal.account_id, service_id, target, version_id
            ),
        )

    async def audits(
        self, principal: Principal, limit: int
    ) -> dict[str, Any]:
        self.require(principal)
        items = await self.repository.list_audits(limit)
        return {"items": items, "total": len(items)}

    async def metrics(self, principal: Principal) -> dict[str, Any]:
        self.require(principal)
        return {**await self.repository.metrics(), "demo_data": True}
