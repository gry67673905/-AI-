from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    CITIZEN = "CITIZEN"
    STAFF = "STAFF"
    ADMIN = "ADMIN"


class ApplicantType(StrEnum):
    INDIVIDUAL = "INDIVIDUAL"
    ENTERPRISE = "ENTERPRISE"


class ServiceStatus(StrEnum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ApplicationStatus(StrEnum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    NEEDS_SUPPLEMENT = "NEEDS_SUPPLEMENT"
    REJECTED = "REJECTED"
    AWAITING_PAYMENT = "AWAITING_PAYMENT"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"
    DISCARDED = "DISCARDED"


class ReviewTaskStatus(StrEnum):
    PENDING = "PENDING"
    CLAIMED = "CLAIMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class HandoffStatus(StrEnum):
    QUEUED = "QUEUED"
    CLAIMED = "CLAIMED"
    IN_PROGRESS = "IN_PROGRESS"
    RESOLVED = "RESOLVED"
    CANCELLED = "CANCELLED"


class PaymentStatus(StrEnum):
    CREATED = "CREATED"
    PENDING = "PENDING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class AppointmentStatus(StrEnum):
    BOOKED = "BOOKED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"


class VerificationStatus(StrEnum):
    CREATED = "CREATED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class DeliveryStatus(StrEnum):
    CREATED = "CREATED"
    ACCEPTED = "ACCEPTED"
    DISPATCHED = "DISPATCHED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class KnowledgeStatus(StrEnum):
    DRAFT = "DRAFT"
    INDEXING = "INDEXING"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    ARCHIVED = "ARCHIVED"
    INDEX_FAILED = "INDEX_FAILED"


class DigitalHumanIntentStatus(StrEnum):
    ACTIVE = "ACTIVE"
    CONSUMED = "CONSUMED"


class EligibilityOutcome(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    NEEDS_INFORMATION = "NEEDS_INFORMATION"


class MaterialTemplateMode(StrEnum):
    SOURCE_EDITABLE = "SOURCE_EDITABLE"
    VISUAL_RECONSTRUCT = "VISUAL_RECONSTRUCT"
    NOT_GENERATABLE = "NOT_GENERATABLE"


class MaterialDocumentStatus(StrEnum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    READY = "READY"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class MaterialDocumentScope(StrEnum):
    APPLICATION = "APPLICATION"
    CONSULTATION = "CONSULTATION"


class ConsultationMaterialIntentStatus(StrEnum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
