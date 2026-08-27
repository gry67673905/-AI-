from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Awaitable, Callable
from uuid import UUID, uuid4

from app.application.dtos import (
    DocumentContextData,
    DocumentFrameData,
    Principal,
    VisualContextData,
    VisionFrameData,
    VisionTicketClaimsData,
)
from app.application.ports import (
    VisionAnalyzerPort,
    VisionFastAnalyzerPort,
    VisionFrameStorePort,
    VisionTicketPort,
)
from app.errors import DependencyUnavailable


@dataclass(frozen=True, slots=True)
class VisionSessionBundle:
    vision_session_id: UUID
    vision_token: str
    vision_expires_at: datetime


class DocumentAnalysisError(ValueError):
    """A fixed, client-safe reason that a document photo can be retaken."""

    _ALLOWED = {"document_unreadable", "analysis_unavailable"}

    def __init__(self, code: str) -> None:
        if code not in self._ALLOWED:
            code = "analysis_unavailable"
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class _SlowVisionJob:
    sanitized_question: str
    frames: tuple[VisionFrameData, ...] = ()
    vision_session_id: UUID | None = None
    wait_deadline: float | None = None


class VisionCoordinator:
    """Own the short-lived, non-persistent camera data plane."""

    _DOCUMENT_JOB_LIMIT = 256
    _DOCUMENT_CONTEXT_LIMIT = 256

    def __init__(
        self,
        tickets: VisionTicketPort,
        frames: VisionFrameStorePort,
        analyzer: VisionAnalyzerPort,
        *,
        enabled: bool,
        ticket_ttl_seconds: int,
        authorize_client_session: Callable[[Principal, UUID], Awaitable[None]],
        turn_close_wait_ms: int = 2000,
        fast_analyzer: VisionFastAnalyzerPort | None = None,
        fast_max_concurrency: int = 2,
        late_memory_ttl_seconds: int = 120,
    ) -> None:
        self.tickets = tickets
        self.frames = frames
        self.analyzer = analyzer
        self.fast_analyzer = fast_analyzer
        self._enabled = enabled
        self._ticket_ttl_seconds = ticket_ttl_seconds
        self._authorize_client_session = authorize_client_session
        if not 100 <= turn_close_wait_ms <= 5000:
            raise ValueError("vision turn-close wait must be 100..5000 ms")
        if not 5 <= late_memory_ttl_seconds <= 600:
            raise ValueError("vision late-memory TTL must be 5..600 seconds")
        if not 1 <= fast_max_concurrency <= 32:
            raise ValueError("fast vision concurrency must be 1..32")
        self._turn_close_wait_seconds = turn_close_wait_ms / 1000
        self._late_memory_ttl_seconds = late_memory_ttl_seconds
        self._fast_slots = asyncio.Semaphore(fast_max_concurrency)
        self._fast_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._slow_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._slow_pending: dict[UUID, _SlowVisionJob] = {}
        self._scene_discard_tasks: dict[UUID, asyncio.Task[None]] = {}
        self._document_slots = asyncio.Semaphore(fast_max_concurrency)
        self._document_lock = asyncio.Lock()
        self._document_contexts: dict[
            UUID, tuple[float, DocumentContextData]
        ] = {}
        self._document_jobs: dict[
            tuple[UUID, int], tuple[float, str, bool]
        ] = {}
        self._document_current_chats: dict[UUID, tuple[float, str]] = {}
        # Client sessions can replace an expired/invalidated WSS generation
        # before the old socket's ``finally`` block runs.  Keep the generation
        # observed at successful registration so that late cleanup from the
        # old socket cannot erase the replacement's chat binding or document
        # context.
        self._active_vision_sessions: dict[UUID, UUID] = {}

    def _require_enabled(self) -> None:
        if not self._enabled:
            raise DependencyUnavailable("metastudio_vision")

    async def create_session(
        self, principal: Principal, client_session_id: UUID
    ) -> VisionSessionBundle:
        self._require_enabled()
        await self._authorize_client_session(principal, client_session_id)
        vision_session_id = uuid4()
        claims = VisionTicketClaimsData(
            vision_session_id=vision_session_id,
            client_session_id=client_session_id,
            account_id=principal.account_id,
            role=principal.role,
            token_version=principal.token_version,
        )
        try:
            token = await self.tickets.issue(claims, self._ticket_ttl_seconds)
        except DependencyUnavailable:
            raise
        except Exception as exc:
            raise DependencyUnavailable("vision_ticket") from exc
        expires_at = datetime.now(timezone.utc) + timedelta(
            seconds=self._ticket_ttl_seconds
        )
        return VisionSessionBundle(
            vision_session_id=vision_session_id,
            vision_token=token,
            vision_expires_at=expires_at,
        )

    async def consume_ticket(self, token: str) -> VisionTicketClaimsData | None:
        self._require_enabled()
        if not token or len(token) > 256 or not token.isascii():
            return None
        try:
            return await self.tickets.consume(token)
        except DependencyUnavailable:
            raise
        except Exception as exc:
            raise DependencyUnavailable("vision_ticket") from exc

    async def start_turn(
        self, claims: VisionTicketClaimsData, turn_sequence: int
    ) -> bool:
        self._require_enabled()
        return await self.frames.start_turn(
            claims.client_session_id,
            claims.vision_session_id,
            turn_sequence,
        )

    async def end_turn(
        self, claims: VisionTicketClaimsData, turn_sequence: int
    ) -> bool:
        self._require_enabled()
        return await self.frames.end_turn(
            claims.client_session_id,
            claims.vision_session_id,
            turn_sequence,
        )

    async def ingest(
        self, claims: VisionTicketClaimsData, frame: VisionFrameData
    ) -> str:
        self._require_enabled()
        if (
            frame.vision_session_id != claims.vision_session_id
            or frame.client_session_id != claims.client_session_id
        ):
            return "session_mismatch"
        result = await self.frames.put(frame)
        if result == "accepted" and self.fast_analyzer is not None:
            self._schedule_fast(frame)
        return result

    def _schedule_fast(self, frame: VisionFrameData) -> None:
        """Keep one latest-wins fast inference task per client session."""

        previous = self._fast_tasks.get(frame.client_session_id)
        if previous is not None and not previous.done():
            previous.cancel()
        task = asyncio.create_task(
            self._run_fast(frame),
            name=f"vision-fast-{frame.client_session_id}",
        )
        self._fast_tasks[frame.client_session_id] = task
        task.add_done_callback(
            lambda completed, session_id=frame.client_session_id: self._forget_task(
                self._fast_tasks, session_id, completed
            )
        )

    @staticmethod
    def _forget_task(
        tasks: dict[UUID, asyncio.Task[None]],
        session_id: UUID,
        completed: asyncio.Task[None],
    ) -> None:
        if tasks.get(session_id) is completed:
            tasks.pop(session_id, None)

    async def _run_fast(self, frame: VisionFrameData) -> None:
        try:
            if self.fast_analyzer is None:
                return
            # Per-session latest-wins prevents stale frames accumulating;
            # this global cap also bounds inference across all live sessions.
            async with self._fast_slots:
                events = await self.fast_analyzer.analyze_frame(frame)
            await self.frames.append_events(frame, events)
        except asyncio.CancelledError:
            raise
        except Exception:
            # A detector/tracker/OCR failure is an absent optional fact. It
            # never invokes the slow model and never changes the chat path.
            return

    async def cleanup_expired(self) -> None:
        """Enforce the raw-frame TTL even while a WSS connection is idle."""

        await self.frames.cleanup_expired()
        now = asyncio.get_running_loop().time()
        async with self._document_lock:
            expired = [
                session_id
                for session_id, (expires_at, _) in self._document_contexts.items()
                if expires_at <= now
            ]
            for session_id in expired:
                self._document_contexts.pop(session_id, None)
            expired_jobs = [
                key
                for key, (expires_at, _, _) in self._document_jobs.items()
                if expires_at <= now
            ]
            for key in expired_jobs:
                self._document_jobs.pop(key, None)
            expired_chats = [
                session_id
                for session_id, (expires_at, _) in self._document_current_chats.items()
                if expires_at <= now
            ]
            for session_id in expired_chats:
                self._document_current_chats.pop(session_id, None)

    @staticmethod
    def _chat_binding(chat_id: str) -> str:
        value = chat_id.strip()
        if not value or len(value) > 256 or not value.isascii():
            return ""
        return hashlib.sha256(value.encode("ascii")).hexdigest()

    async def note_chat(self, client_session_id: UUID, chat_id: str) -> None:
        binding = self._chat_binding(chat_id)
        if not binding:
            return
        expires_at = (
            asyncio.get_running_loop().time() + self._late_memory_ttl_seconds
        )
        async with self._document_lock:
            self._document_current_chats[client_session_id] = (
                expires_at,
                binding,
            )

    async def clear_document_context(self, client_session_id: UUID) -> None:
        async with self._document_lock:
            self._document_contexts.pop(client_session_id, None)

    async def start_document(
        self, claims: VisionTicketClaimsData, document_sequence: int
    ) -> bool:
        """Clear old OCR and bind one capture to the current provider chat."""

        self._require_enabled()
        key = (claims.vision_session_id, document_sequence)
        now = asyncio.get_running_loop().time()
        async with self._document_lock:
            self._document_contexts.pop(claims.client_session_id, None)
            for job_key, (expires_at, _, _) in tuple(self._document_jobs.items()):
                if expires_at <= now:
                    self._document_jobs.pop(job_key, None)
            current = self._document_current_chats.get(claims.client_session_id)
            if current is None or current[0] <= now:
                self._document_current_chats.pop(claims.client_session_id, None)
                return False
            if key in self._document_jobs or len(self._document_jobs) >= self._DOCUMENT_JOB_LIMIT:
                return False
            self._document_jobs[key] = (
                now + self._late_memory_ttl_seconds,
                current[1],
                False,
            )
            return True

    async def analyze_document(
        self, claims: VisionTicketClaimsData, frame: DocumentFrameData
    ) -> DocumentContextData:
        """Analyze exactly one document photo and retain only bounded text.

        The caller owns the frame bytes and drops them as soon as this method
        returns. There is no retry or alternate-model path.
        """

        self._require_enabled()
        if (
            frame.vision_session_id != claims.vision_session_id
            or frame.client_session_id != claims.client_session_id
        ):
            raise DocumentAnalysisError("analysis_unavailable")
        loop = asyncio.get_running_loop()
        job_key = (claims.vision_session_id, frame.document_sequence)
        async with self._document_lock:
            now = loop.time()
            for key, (expires_at, _, _) in tuple(self._document_jobs.items()):
                if expires_at <= now:
                    self._document_jobs.pop(key, None)
            job = self._document_jobs.get(job_key)
            if job is None or job[2]:
                raise DocumentAnalysisError("analysis_unavailable")
            self._document_jobs[job_key] = (job[0], job[1], True)
            chat_binding = job[1]
        try:
            async with self._document_slots:
                context = await self.analyzer.analyze_document(frame)
        except DocumentAnalysisError:
            raise
        except Exception as exc:
            raise DocumentAnalysisError("analysis_unavailable") from exc
        if not context.summary and not context.visible_text and not context.key_fields:
            raise DocumentAnalysisError("document_unreadable")
        context = replace(context, chat_binding=chat_binding)
        expires_at = loop.time() + self._late_memory_ttl_seconds
        async with self._document_lock:
            previous = self._document_contexts.get(claims.client_session_id)
            if (
                previous is None
                or previous[1].document_sequence <= context.document_sequence
            ):
                if (
                    claims.client_session_id not in self._document_contexts
                    and len(self._document_contexts) >= self._DOCUMENT_CONTEXT_LIMIT
                ):
                    raise DocumentAnalysisError("analysis_unavailable")
                self._document_contexts[claims.client_session_id] = (
                    expires_at,
                    context,
                )
        return context

    async def get_document_context(
        self, client_session_id: UUID, chat_id: str
    ) -> DocumentContextData | None:
        """Read the latest document repeatedly until replacement or TTL expiry."""

        now = asyncio.get_running_loop().time()
        async with self._document_lock:
            item = self._document_contexts.get(client_session_id)
            if item is not None and item[0] <= now:
                self._document_contexts.pop(client_session_id, None)
                item = None
        if item is None:
            return None
        binding = self._chat_binding(chat_id)
        if not binding or item[1].chat_binding != binding:
            return None
        return item[1]

    async def discard_latest_scene_turn(self, client_session_id: UUID) -> None:
        """Erase ordinary scene frames without scheduling a scene VLM call."""

        # A late summary from a previous scene is also irrelevant while the
        # user is entering the explicit document-capture flow.
        for _ in range(2):
            if await self.frames.pop_late_context(client_session_id) is None:
                break
        snapshot = None
        # The store capacity is much smaller than this hard bound. Drain every
        # already sealed turn, not just the FIFO head, so an earlier backlog
        # cannot trigger paid scene analysis after document capture.
        for _ in range(16):
            snapshot = await self.frames.pop_latest_turn(client_session_id)
            if snapshot.status != "ready":
                break
        if (
            snapshot is None
            or snapshot.status != "active"
            or snapshot.vision_session_id is None
        ):
            return
        previous = self._scene_discard_tasks.get(client_session_id)
        if previous is not None and not previous.done():
            previous.cancel()
        task = asyncio.create_task(
            self._wait_and_discard_scene_turn(
                client_session_id,
                snapshot.vision_session_id,
                snapshot.turn_sequence,
            ),
            name=f"vision-discard-{client_session_id}",
        )
        self._scene_discard_tasks[client_session_id] = task
        task.add_done_callback(
            lambda completed, session_id=client_session_id: self._forget_task(
                self._scene_discard_tasks, session_id, completed
            )
        )

    async def _wait_and_discard_scene_turn(
        self,
        client_session_id: UUID,
        vision_session_id: UUID,
        turn_sequence: int | None,
    ) -> None:
        deadline = (
            asyncio.get_running_loop().time() + self._turn_close_wait_seconds
        )
        try:
            while asyncio.get_running_loop().time() < deadline:
                snapshot = await self.frames.pop_latest_turn(
                    client_session_id, vision_session_id
                )
                if snapshot.status == "ready":
                    # The generation and observed turn are fixed, so this can
                    # never consume a later socket generation.
                    if turn_sequence is None or snapshot.turn_sequence == turn_sequence:
                        return
                    return
                if snapshot.status == "absent":
                    return
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise

    async def register_session(self, claims: VisionTicketClaimsData) -> bool:
        self._require_enabled()
        # Serialize the frame-store registration and generation publication
        # with document cleanup.  This closes the small window in which a
        # stale socket could otherwise clear client-scoped state after the
        # replacement had registered in the frame store but before its
        # generation was visible here.
        async with self._document_lock:
            registered = await self.frames.register_session(
                claims.client_session_id, claims.vision_session_id
            )
            if registered:
                self._active_vision_sessions[claims.client_session_id] = (
                    claims.vision_session_id
                )
            return registered

    async def analyze_latest_turn(
        self, client_session_id: UUID, sanitized_question: str
    ) -> VisualContextData | None:
        if not self._enabled:
            return None
        if self.fast_analyzer is not None:
            return await self._analyze_nonblocking(
                client_session_id, sanitized_question
            )
        return await self._analyze_legacy(client_session_id, sanitized_question)

    async def _analyze_nonblocking(
        self, client_session_id: UUID, sanitized_question: str
    ) -> VisualContextData | None:
        """Return immediately; slow VLM work may only enrich a later turn."""

        late = await self.frames.pop_late_context(client_session_id)
        snapshot = await self.frames.pop_latest_turn(client_session_id)
        if snapshot.status == "ready" and snapshot.vision_session_id is not None:
            current = await self.frames.timeline_context(
                client_session_id,
                snapshot.vision_session_id,
                snapshot.turn_sequence or 1,
                len(snapshot.frames),
            )
            if snapshot.frames:
                self._schedule_slow(
                    client_session_id,
                    sanitized_question,
                    snapshot.frames,
                )
            return self._merge_contexts(current, self._as_late_memory(late))
        if snapshot.status in {"idle", "active"} and snapshot.vision_session_id is not None:
            self._schedule_slow_wait(
                client_session_id,
                snapshot.vision_session_id,
                sanitized_question,
            )
        # Missing, active, empty, or failed visual state is deliberately
        # represented as no visual context. The ordinary answer proceeds once;
        # there is no visual-triggered fallback/degraded model invocation.
        return self._as_late_memory(late)

    def _enqueue_slow_job(
        self, client_session_id: UUID, job: _SlowVisionJob
    ) -> None:
        """Keep one paid request in flight and one latest pending job.

        Once a slow provider request may have consumed quota or emitted HTTP,
        a newer callback must not cancel it. New work replaces only the single
        pending slot, bounding retained JPEGs while preserving useful late
        summaries from requests that have already started.
        """

        current = self._slow_tasks.get(client_session_id)
        if current is not None and not current.done():
            self._slow_pending[client_session_id] = job
            return
        task = asyncio.create_task(
            self._slow_worker(client_session_id, job),
            name=f"vision-slow-{client_session_id}",
        )
        self._slow_tasks[client_session_id] = task
        task.add_done_callback(
            lambda completed, session_id=client_session_id: self._forget_task(
                self._slow_tasks, session_id, completed
            )
        )

    async def _slow_worker(
        self, client_session_id: UUID, first: _SlowVisionJob
    ) -> None:
        job: _SlowVisionJob | None = first
        while job is not None:
            try:
                if job.frames:
                    await self._run_slow(job.sanitized_question, job.frames)
                elif job.vision_session_id is not None:
                    await self._wait_for_sealed_turn(
                        client_session_id,
                        job.vision_session_id,
                        job.sanitized_question,
                        job.wait_deadline,
                    )
            except asyncio.CancelledError:
                raise
            except Exception:
                # Store/watcher failures are optional vision failures too.
                # Keep the worker healthy so the single pending job can still
                # run; never surface a task exception into normal answering.
                pass
            job = self._slow_pending.pop(client_session_id, None)

    def _schedule_slow(
        self,
        client_session_id: UUID,
        sanitized_question: str,
        frames: tuple[VisionFrameData, ...],
    ) -> None:
        self._enqueue_slow_job(
            client_session_id,
            _SlowVisionJob(
                sanitized_question=sanitized_question,
                frames=frames,
            ),
        )

    def _schedule_slow_wait(
        self,
        client_session_id: UUID,
        vision_session_id: UUID,
        sanitized_question: str,
    ) -> None:
        self._enqueue_slow_job(
            client_session_id,
            _SlowVisionJob(
                sanitized_question=sanitized_question,
                vision_session_id=vision_session_id,
                # A watcher queued behind an in-flight paid request must not
                # start a fresh wait window later and steal a future turn.
                wait_deadline=(
                    asyncio.get_running_loop().time()
                    + self._turn_close_wait_seconds
                ),
            ),
        )

    async def _wait_for_sealed_turn(
        self,
        client_session_id: UUID,
        vision_session_id: UUID,
        sanitized_question: str,
        deadline: float | None = None,
    ) -> None:
        loop = asyncio.get_running_loop()
        effective_deadline = deadline or (
            loop.time() + self._turn_close_wait_seconds
        )
        while loop.time() < effective_deadline:
            snapshot = await self.frames.pop_latest_turn(
                client_session_id, vision_session_id
            )
            if snapshot.status == "ready":
                if snapshot.frames:
                    await self._run_slow(sanitized_question, snapshot.frames)
                return
            if snapshot.status == "absent":
                return
            await asyncio.sleep(
                min(0.05, max(0.0, effective_deadline - loop.time()))
            )

    async def _run_slow(
        self, sanitized_question: str, frames: tuple[VisionFrameData, ...]
    ) -> None:
        try:
            context = await self.analyzer.analyze(sanitized_question, frames)
            # Zero-confidence/no-fact mock results are not conversational
            # memory. Real normalized summaries are offered exactly once to a
            # subsequent turn and expire quickly.
            if context.available and (
                context.confidence > 0
                or context.people
                or context.objects
                or context.visible_text
                or context.query_hints
            ):
                await self.frames.remember_late_context(
                    context, self._late_memory_ttl_seconds
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            return

    @staticmethod
    def _as_late_memory(
        context: VisualContextData | None,
    ) -> VisualContextData | None:
        if context is None or not context.available:
            return None
        scene = context.scene.strip()
        return VisualContextData(
            client_session_id=context.client_session_id,
            turn_sequence=context.turn_sequence,
            frame_count=context.frame_count,
            scene=("上一轮画面摘要：" + scene) if scene else "上一轮画面有可用摘要",
            available=True,
            people=context.people,
            objects=context.objects,
            visible_text=context.visible_text,
            # Late camera text may inform the answer but must not initiate a
            # fresh retrieval or action on the following spoken question.
            query_hints=(),
            confidence=context.confidence,
            mode=context.mode,
        )

    @staticmethod
    def _merge_contexts(
        current: VisualContextData | None,
        late: VisualContextData | None,
    ) -> VisualContextData | None:
        if current is None:
            return late
        if late is None:
            return current

        def merge(left: tuple[str, ...], right: tuple[str, ...]) -> tuple[str, ...]:
            return tuple(dict.fromkeys((*left, *right)))[:8]

        return VisualContextData(
            client_session_id=current.client_session_id,
            turn_sequence=current.turn_sequence,
            frame_count=current.frame_count,
            scene="；".join(value for value in (current.scene, late.scene) if value),
            available=True,
            people=merge(current.people, late.people),
            objects=merge(current.objects, late.objects),
            visible_text=merge(current.visible_text, late.visible_text),
            query_hints=current.query_hints,
            confidence=max(current.confidence, late.confidence),
            mode=current.mode,
        )

    async def _analyze_legacy(
        self, client_session_id: UUID, sanitized_question: str
    ) -> VisualContextData | None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + self._turn_close_wait_seconds
        expected_vision_session_id: UUID | None = None
        while True:
            snapshot = await self.frames.pop_latest_turn(
                client_session_id, expected_vision_session_id
            )
            if snapshot.status not in {"idle", "active"}:
                break
            if snapshot.vision_session_id is None:
                return self._unavailable_context(
                    client_session_id, snapshot.turn_sequence or 1
                )
            if expected_vision_session_id is None:
                expected_vision_session_id = snapshot.vision_session_id
            elif snapshot.vision_session_id != expected_vision_session_id:
                return self._unavailable_context(
                    client_session_id, snapshot.turn_sequence or 1
                )
            remaining = deadline - loop.time()
            if remaining <= 0:
                turn_sequence = snapshot.turn_sequence or 1
                # The callback has irrevocably fallen back to voice-only. Tear
                # down precisely the socket generation it observed so a late
                # turn.start cannot become an orphan and be paired with the
                # next ASR question.
                await self.frames.invalidate_session(
                    client_session_id, expected_vision_session_id
                )
                return self._unavailable_context(
                    client_session_id, turn_sequence
                )
            await asyncio.sleep(min(0.05, remaining))
        if snapshot.status == "absent":
            if expected_vision_session_id is not None:
                return self._unavailable_context(client_session_id, 1)
            return None
        frames = snapshot.frames
        if not frames:
            return self._unavailable_context(
                client_session_id, snapshot.turn_sequence or 1
            )
        # The store no longer retains these frames. The analyzer receives one
        # bounded tuple exactly once for the final ASR question, and the tuple
        # falls out of scope immediately after the call.
        try:
            return await self.analyzer.analyze(sanitized_question, frames)
        except Exception:
            return self._unavailable_context(
                client_session_id, snapshot.turn_sequence or frames[-1].turn_sequence
            )

    async def close(self) -> None:
        tasks = [
            *self._fast_tasks.values(),
            *self._slow_tasks.values(),
            *self._scene_discard_tasks.values(),
        ]
        self._fast_tasks.clear()
        self._slow_tasks.clear()
        self._slow_pending.clear()
        self._scene_discard_tasks.clear()
        async with self._document_lock:
            self._document_contexts.clear()
            self._document_jobs.clear()
            self._document_current_chats.clear()
            self._active_vision_sessions.clear()
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def discard_session(
        self, claims: VisionTicketClaimsData, *, mark_unavailable: bool = False
    ) -> None:
        await self.frames.discard_session(
            claims.client_session_id,
            claims.vision_session_id,
            mark_unavailable=mark_unavailable,
        )
        async with self._document_lock:
            if (
                self._active_vision_sessions.get(claims.client_session_id)
                == claims.vision_session_id
            ):
                self._document_contexts.pop(claims.client_session_id, None)
                self._document_current_chats.pop(claims.client_session_id, None)
                self._active_vision_sessions.pop(claims.client_session_id, None)
            for key in tuple(self._document_jobs):
                if key[0] == claims.vision_session_id:
                    self._document_jobs.pop(key, None)

    @staticmethod
    def _unavailable_context(
        client_session_id: UUID, turn_sequence: int
    ) -> VisualContextData:
        return VisualContextData(
            client_session_id=client_session_id,
            turn_sequence=turn_sequence,
            frame_count=0,
            scene="",
            available=False,
            confidence=0.0,
            mode="mock",
        )
