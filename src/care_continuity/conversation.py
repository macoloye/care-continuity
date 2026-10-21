"""Session-bound, ephemeral model suggestions; no model-directed actions."""

from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Mapping

from .consent import ConsentService
from .circle import CircleService
from .delegation import DelegationService
from .domain import AccessDenied, Clock, Conflict, Memory, Operation, timestamp, utc_now
from .memory import MemoryService
from .sessions import SessionService
from .store import SQLiteStore


PURPOSE = 'draft-support-request'


@dataclass(frozen=True)
class DraftContext:
    purpose: str
    memories: tuple[Memory, ...]


@dataclass(frozen=True)
class RequestSuggestion:
    """Untrusted text for review, not a saved or approved request."""
    message: str
    dependencies: tuple[tuple[str, int], ...]
    provider: str


class ConversationService:
    """Host-configured adapters receive context only, never sessions or service handles.

    Adapters return exactly {'kind': 'request_draft', 'message': str}. They are
    trusted host code; their output is untrusted. No prompts or results are cached.
    """

    def __init__(self, store: SQLiteStore, *,
                 adapters: Mapping[str, Callable[[DraftContext], object]],
                 clock: Clock = utc_now) -> None:
        self.store, self.clock = store, clock
        self.adapters = dict(adapters)
        self.sessions = SessionService(store, clock)
        self.consent = ConsentService(store, clock)
        self.memory = MemoryService(store, self.consent, clock)

    def _context(self, token: str, provider: str, selections: tuple[tuple[str, int], ...],
                 *, require_grants: bool) -> DraftContext:
        actor = self.sessions.resolve(token)
        if provider not in self.adapters or provider == actor:
            raise AccessDenied('Model provider unavailable')
        if not selections or len(selections) > 20 or len({key for key, _ in selections}) != len(selections):
            raise ValueError('Select between one and twenty distinct memories')
        memories = []
        for key, revision in selections:
            item = self.memory.read(key, actor=actor, purpose=PURPOSE)
            self.consent.require_owner(actor, item.subject)
            if type(revision) is not int or item.revision != revision:
                raise Conflict('Selected memory changed; review it again')
            if require_grants:
                for operation in (Operation.READ, Operation.SHARE):
                    self.consent.require(subject=actor, actor=provider, purpose=PURPOSE,
                                         resource_type='memory', resource_id=key, operation=operation)
            memories.append(item)
        return DraftContext(PURPOSE, tuple(memories))

    def authorize(self, token: str, *, provider: str, selections: tuple[tuple[str, int], ...],
                  expires_at: datetime) -> None:
        """Call only after showing exact memories, provider, purpose and expiry."""
        selections = tuple(selections)
        with self.store.transaction():
            context = self._context(token, provider, selections, require_grants=False)
            actor = context.memories[0].subject
            for item in context.memories:
                for operation in (Operation.READ, Operation.SHARE):
                    existing = self.store.connection.execute(
                        """SELECT 1 FROM grants WHERE subject=? AND recipient=? AND purpose=?
                        AND resource_type='memory' AND resource_id=? AND operation=?
                        AND expires_at=? AND expires_at>? AND revoked_at IS NULL""",
                        (actor, provider, PURPOSE, item.id, operation.value,
                         timestamp(expires_at), timestamp(self.clock())),
                    ).fetchone()
                    if existing:
                        continue
                    self.consent.grant(actor=actor, subject=actor, recipient=provider, purpose=PURPOSE,
                                       resource_type='memory', resource_id=item.id,
                                       operation=operation, expires_at=expires_at)

    def suggest(self, token: str, *, provider: str,
                selections: tuple[tuple[str, int], ...]) -> RequestSuggestion:
        """One adapter call outside transactions; revalidate before returning text."""
        if self.store.connection.in_transaction:
            raise Conflict('Run generation outside an application transaction')
        selections = tuple(selections)
        with self.store.transaction():
            context = self._context(token, provider, selections, require_grants=True)
        failed = False
        try:
            output = self.adapters[provider](context)
        except Exception:
            failed = True
        # Raise outside the exception handler so private provider errors are not chained.
        if failed:
            raise ValueError('The model could not produce a suggestion')
        with self.store.transaction():
            self._context(token, provider, selections, require_grants=True)
            if (type(output) is not dict or set(output) != {'kind', 'message'}
                    or output['kind'] != 'request_draft' or type(output['message']) is not str
                    or not output['message'].strip() or len(output['message']) > 4000):
                raise ValueError('The model returned an invalid suggestion')
            return RequestSuggestion(output['message'], selections, provider)

    def save_draft(self, token: str, suggestion: RequestSuggestion, *,
                   reviewed_message: str, recipient: str, purpose: str,
                   idempotency_key: str) -> str:
        """Save explicitly reviewed text with every source dependency, without sharing.

        The host must retain the original suggestion's dependencies and provider;
        never reconstruct them from model output or editable client form fields.
        The person chooses recipient/purpose and reviews the message and all context.
        """
        if type(reviewed_message) is not str or not reviewed_message.strip() or len(reviewed_message) > 4000:
            raise ValueError('Review a nonblank message of at most 4000 characters')
        with self.store.transaction():
            context = self._context(token, suggestion.provider, tuple(suggestion.dependencies),
                                    require_grants=True)
            actor = context.memories[0].subject
            CircleService(self.store, self.clock).require_member(actor, recipient)
            return DelegationService(self.store, self.consent, self.memory, self.clock).create(
                actor=actor, subject=actor, recipient=recipient, purpose=purpose,
                message=reviewed_message, idempotency_key=idempotency_key,
                memory_ids=tuple(item.id for item in context.memories))
