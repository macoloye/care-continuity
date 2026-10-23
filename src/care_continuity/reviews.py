"""Bounded, process-local review handles; never put authoritative context in forms."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from secrets import token_urlsafe

from .conversation import PURPOSE, ConversationService, RequestSuggestion
from .domain import AccessDenied, Conflict, Operation, timestamp
from .sessions import SessionService


@dataclass
class Review:
    session_hash: str
    actor: str
    selections: tuple[tuple[str, int], ...]
    provider: str
    expires: datetime
    permission_expires: datetime
    suggestion: RequestSuggestion | None = None


class SuggestionReviews:
    def __init__(self, service: ConversationService) -> None:
        self.service = service
        self.entries: dict[str, Review] = {}

    def _check(self, review: Review) -> None:
        service = self.service
        now = service.clock()
        if review.provider not in service.adapters:
            raise AccessDenied("Provider unavailable")
        session = service.store.connection.execute(
            'SELECT actor FROM sessions WHERE token_hash=? AND revoked_at IS NULL AND expires_at>?',
            (review.session_hash, timestamp(now))).fetchone()
        if not session or session['actor'] != review.actor or review.expires <= now:
            raise AccessDenied('Review expired; start a new suggestion')
        for key, revision in review.selections:
            memory = service.memory.read(key, actor=review.actor, purpose='manage')
            service.consent.require_owner(review.actor, memory.subject)
            if memory.revision != revision:
                raise Conflict('Source changed; start a new suggestion')
            if review.suggestion is not None:
                for operation in (Operation.READ, Operation.SHARE):
                    service.consent.require(subject=review.actor, actor=review.provider,
                        purpose=PURPOSE, resource_type='memory', resource_id=key, operation=operation)

    def prune(self) -> None:
        with self.service.store.transaction():
            for key, review in list(self.entries.items()):
                try:
                    self._check(review)
                except (AccessDenied, Conflict):
                    self.entries.pop(key, None)

    def create(self, token: str, *, selections: tuple[tuple[str, int], ...],
               provider: str, hours: int) -> str:
        self.prune()
        if hours not in (1, 24, 168):
            raise ValueError('Choose one hour, one day or seven days')
        if len(self.entries) >= 128:
            raise Conflict('Too many open reviews; discard one or wait for it to expire')
        with self.service.store.transaction():
            context = self.service._context(token, provider, selections, require_grants=False)
            handle = token_urlsafe(32)
            now = self.service.clock()
            self.entries[handle] = Review(SessionService._digest(token), context.memories[0].subject,
                selections, provider, now + timedelta(minutes=15), now + timedelta(hours=hours))
            return handle

    def get(self, token: str, handle: str) -> Review:
        self.prune()
        review = self.entries.get(handle)
        if review is None or review.session_hash != SessionService._digest(token):
            raise AccessDenied('Review unavailable or expired; start a new suggestion')
        return review

    def generate(self, token: str, handle: str) -> Review:
        review = self.get(token, handle)
        if review.suggestion is None:
            self.service.authorize(token, provider=review.provider, selections=review.selections,
                                   expires_at=review.permission_expires)
            review.suggestion = self.service.suggest(token, provider=review.provider, selections=review.selections)
        return self.get(token, handle)

    def discard(self, token: str, handle: str) -> None:
        self.get(token, handle)
        self.entries.pop(handle)
