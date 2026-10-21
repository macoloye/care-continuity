"""Shared value types. No model provider or interface dependencies."""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Callable


Clock = Callable[[], datetime]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Use a timezone-aware datetime")
    return value.astimezone(timezone.utc).isoformat()


def required(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must not be empty")
    return value


class AccessDenied(PermissionError):
    """Missing, revoked, or expired authority; does not reveal record contents."""


class Conflict(ValueError):
    """A stale revision, duplicate key, or invalid lifecycle transition."""


class Operation(str, Enum):
    READ = "read"
    SHARE = "share"
    ACT = "act"


class MemoryKind(str, Enum):
    PREFERENCE = "preference"
    OBSERVATION = "observation"
    INTERPRETATION = "interpretation"


class RequestState(str, Enum):
    DRAFT = "draft"
    QUEUED = "queued"
    DELIVERED = "delivered"
    ACCEPTED = "accepted"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class Memory:
    id: str
    subject: str
    kind: MemoryKind
    text: str
    source: str
    confirmed: bool
    revision: int
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class SupportRequest:
    id: str
    subject: str
    recipient: str
    purpose: str
    message: str
    state: RequestState
    context: tuple[Memory, ...]
    created_at: str
    updated_at: str


@dataclass(frozen=True)
class KnowledgeCard:
    id: str
    title: str
    body: str
    kind: str
    source: str
    contributor: str
    reviewer: str | None
    review_due: str | None
    status: str
    audience: str
    setting: str
    language: str
    limitations: str
    submitted_at: str | None
    published_at: str | None
    qualification_id: str | None
