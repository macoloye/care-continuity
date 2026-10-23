"""Session-bound entry points for future text and voice interfaces.

Every operation derives its actor from a bearer session. The outer transaction
keeps session validation, membership checks, and service work in one snapshot.
"""

from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime
from typing import Iterator

from .circle import CircleService
from .consent import ConsentService
from .delegation import DelegationService
from .domain import AccessDenied, Clock, Conflict, KnowledgeCard, Memory, Operation, RequestState, SupportRequest, required, timestamp, utc_now
from .memory import MemoryService
from .knowledge import KnowledgeService
from .qualifications import QualificationService
from .outbox import OutboxService
from .sessions import SessionService
from .store import SQLiteStore


class CareApplication:
    def __init__(self, store: SQLiteStore, clock: Clock = utc_now, *,
                 reviewers: frozenset[str] = frozenset(),
                 qualification_verifiers: frozenset[str] = frozenset(),
                 delivery_providers: frozenset[str] = frozenset()) -> None:
        self.store, self.clock = store, clock
        self._delivery_providers = frozenset(delivery_providers)
        self._sessions = SessionService(store, clock)
        self._consent = ConsentService(store, clock)
        self._memory = MemoryService(store, self._consent, clock)
        self._requests = DelegationService(store, self._consent, self._memory, clock)
        self._circle = CircleService(store, clock)
        self._knowledge = KnowledgeService(store, reviewers=reviewers, clock=clock)
        self._qualifications = QualificationService(store, verifiers=qualification_verifiers, clock=clock)

    @contextmanager
    def _actor(self, token: str) -> Iterator[str]:
        with self.store.transaction():
            yield self._sessions.resolve(token)

    def logout(self, token: str) -> None:
        self._sessions.revoke(token)

    def remember(self, token: str, *, text: str, confirmed: bool = False) -> Memory:
        with self._actor(token) as actor:
            return self._memory.remember(actor=actor, subject=actor, source=actor, text=text, confirmed=confirmed)

    def revise(self, token: str, memory_id: str, *, text: str, expected_revision: int) -> Memory:
        with self._actor(token) as actor:
            return self._memory.revise(memory_id, actor=actor, text=text, expected_revision=expected_revision)

    def forget(self, token: str, memory_id: str) -> None:
        with self._actor(token) as actor:
            self._memory.forget(memory_id, actor=actor)

    def memories(self, token: str, *, subject: str, purpose: str) -> tuple[Memory, ...]:
        with self._actor(token) as actor:
            return self._memory.summary(subject=subject, actor=actor, purpose=purpose)

    def observe(self, token: str, *, subject: str, text: str) -> Memory:
        """A circle member records an observation about the person for review."""
        with self._actor(token) as actor:
            return self._memory.observe(actor=actor, subject=subject, text=text)

    def pending_observations(self, token: str) -> tuple[Memory, ...]:
        """Owner-only review inbox for unconfirmed observations."""
        with self._actor(token) as actor:
            return self._memory.observations_pending(subject=actor, actor=actor)

    def accept_observation(self, token: str, memory_id: str) -> Memory:
        with self._actor(token) as actor:
            return self._memory.observation_accept(memory_id, actor=actor)

    def dismiss_observation(self, token: str, memory_id: str) -> None:
        with self._actor(token) as actor:
            self._memory.observation_dismiss(memory_id, actor=actor)

    def withdraw_observation(self, token: str, memory_id: str) -> None:
        with self._actor(token) as actor:
            self._memory.observation_withdraw(memory_id, actor=actor)

    def my_observations(self, token: str) -> list[dict]:
        """A contributor's own submissions with their review status."""
        with self._actor(token) as actor:
            return self._memory.observations_by(actor=actor)

    def circle_subjects(self, token: str) -> list[str]:
        """People whose care circle currently includes the actor."""
        with self._actor(token) as actor:
            return [row["subject"] for row in self.store.connection.execute(
                """SELECT subject FROM care_circle WHERE member=? AND removed_at IS NULL
                   ORDER BY subject""", (actor,))]

    def add_member(self, token: str, *, member: str, role: str) -> None:
        with self._actor(token) as actor:
            self._circle.add(actor=actor, subject=actor, member=member, role=role)

    def remove_member(self, token: str, *, member: str) -> None:
        with self._actor(token) as actor:
            self._circle.remove(actor=actor, subject=actor, member=member)

    def members(self, token: str) -> list[dict]:
        with self._actor(token) as actor:
            return self._circle.list_members(actor=actor, subject=actor)

    def grant(self, token: str, *, recipient: str, purpose: str, resource_type: str,
              resource_id: str, operation: Operation, expires_at: datetime) -> str:
        with self._actor(token) as actor:
            self._circle.require_member(actor, recipient)
            return self._consent.grant(actor=actor, subject=actor, recipient=recipient, purpose=purpose,
                                       resource_type=resource_type, resource_id=resource_id,
                                       operation=operation, expires_at=expires_at)

    def revoke(self, token: str, grant_id: str) -> None:
        with self._actor(token) as actor:
            self._consent.revoke(actor=actor, grant_id=grant_id)

    def sharing(self, token: str) -> list[dict]:
        with self._actor(token) as actor:
            now = timestamp(self.clock())
            return [dict(grant, active=grant["revoked_at"] is None and grant["expires_at"] > now)
                    for grant in self._consent.list_grants(actor=actor, subject=actor)]

    def create_request(self, token: str, *, recipient: str, purpose: str, message: str,
                       idempotency_key: str, memory_ids: tuple[str, ...] = ()) -> str:
        with self._actor(token) as actor:
            self._circle.require_member(actor, recipient)
            return self._requests.create(actor=actor, subject=actor, recipient=recipient, purpose=purpose,
                                          message=message, idempotency_key=idempotency_key, memory_ids=memory_ids)

    def read_request(self, token: str, request_id: str) -> SupportRequest:
        with self._actor(token) as actor:
            return self._requests.read(request_id, actor=actor)

    def queue(self, token: str, request_id: str) -> None:
        with self._actor(token) as actor:
            self._requests.queue(request_id, actor=actor)

    def approve_request(self, token: str, request_id: str, *, expires_at: datetime) -> RequestState:
        """Approve an immutable draft and deliver locally in one transaction.

        Interfaces must first show the exact draft, context, recipient, purpose,
        and expiry. A changed context fails before any grants are created.
        """
        with self._actor(token) as actor:
            row = self._requests._row(request_id)
            self._consent.require_owner(actor, row["subject"])
            if row["state"] != "draft":
                raise Conflict("This draft has already been handled; check its current status")
            request = self._requests.read(request_id, actor=actor)
            self._circle.require_member(actor, request.recipient)
            scopes = [("request", request_id, Operation.READ), ("request", request_id, Operation.ACT)]
            for memory in request.context:
                scopes.extend((("memory", memory.id, Operation.READ), ("memory", memory.id, Operation.SHARE)))
            for resource_type, resource_id, operation in scopes:
                self._consent.grant(actor=actor, subject=actor, recipient=request.recipient,
                                    purpose=request.purpose, resource_type=resource_type,
                                    resource_id=resource_id, operation=operation, expires_at=expires_at)
            self._requests.queue(request_id, actor=actor)
            return self._requests.dispatch(request_id, actor=actor)

    def dispatch(self, token: str, request_id: str) -> RequestState:
        with self._actor(token) as actor:
            return self._requests.dispatch(request_id, actor=actor)

    def transition(self, token: str, request_id: str, *, state: RequestState) -> None:
        with self._actor(token) as actor:
            self._requests.transition(request_id, actor=actor, state=state)

    def inbox(self, token: str) -> tuple[SupportRequest, ...]:
        with self._actor(token) as actor:
            rows = self.store.connection.execute(
                "SELECT id FROM requests WHERE recipient=? ORDER BY created_at, id", (actor,)).fetchall()
            result = []
            for row in rows:
                try:
                    result.append(self._requests.read(row["id"], actor=actor))
                except (AccessDenied, Conflict):
                    # Do not reveal hidden, revoked, or stale request metadata.
                    continue
            return tuple(result)

    def plan_followup(self, token: str, request_id: str, *, due_at: datetime, alternative: str) -> None:
        required(alternative, "alternative")
        with self._actor(token) as actor:
            row = self._requests._row(request_id)
            self._consent.require_owner(actor, row["subject"])
            if row["state"] not in ("draft", "queued", "delivered"):
                raise Conflict("Follow-up is only available before acceptance")
            at, due = timestamp(self.clock()), timestamp(due_at)
            if due <= at:
                raise ValueError("Choose a future follow-up time")
            self.store.connection.execute("""INSERT INTO followups(request_id, due_at, alternative, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(request_id) DO UPDATE SET due_at=excluded.due_at,
                alternative=excluded.alternative, updated_at=excluded.updated_at,
                resolved_at=NULL, resolution=NULL""",
                (request_id, due, alternative, at))
            self.store.event(actor, actor, request_id, "request.followup_planned", at)

    def resolve_followup(self, token: str, request_id: str, *, note: str) -> None:
        """Record how the person handled an unanswered request; no reminder is sent."""
        required(note, "note")
        with self._actor(token) as actor:
            row = self._requests._row(request_id)
            self._consent.require_owner(actor, row["subject"])
            if row["state"] not in ("draft", "queued", "delivered"):
                raise Conflict("Follow-up is only available before acceptance")
            followup = self.store.connection.execute(
                "SELECT * FROM followups WHERE request_id=?", (request_id,)).fetchone()
            if followup is None:
                raise Conflict("Plan a follow-up before recording its outcome")
            if followup["resolved_at"] is not None:
                raise Conflict("This follow-up has already been resolved")
            at = timestamp(self.clock())
            self.store.connection.execute(
                """UPDATE followups SET resolved_at=?, resolution=?, updated_at=?
                   WHERE request_id=? AND resolved_at IS NULL""", (at, note, at, request_id))
            self.store.event(actor, actor, request_id, "request.followup_resolved", at)

    def _owner_requests(self, actor: str) -> list[dict]:
        rows = self.store.connection.execute(
            """SELECT r.id, r.recipient, r.purpose, r.state, r.created_at, r.updated_at,
               f.due_at, f.alternative, f.resolved_at, f.resolution
               FROM requests r LEFT JOIN followups f ON f.request_id=r.id
               WHERE r.subject=? ORDER BY r.created_at, r.id""", (actor,)).fetchall()
        result = []
        now = timestamp(self.clock())
        for row in rows:
            item = dict(row)
            item["needs_followup"] = bool(row["due_at"] and row["due_at"] <= now
                                           and row["state"] in ("draft", "queued", "delivered")
                                           and row["resolved_at"] is None)
            try:
                request = self._requests.read(row["id"], actor=actor)
                item.update(content_available=True, message=request.message,
                            context=[asdict(memory) for memory in request.context])
            except (AccessDenied, Conflict):
                item.update(content_available=False, message=None, context=[])
            result.append(item)
        return result

    def requests(self, token: str) -> list[dict]:
        """Owner view includes metadata even when old context cannot be read."""
        with self._actor(token) as actor:
            return self._owner_requests(actor)

    def export(self, token: str) -> dict:
        """Return a consistent JSON-compatible account export; never session secrets."""
        with self._actor(token) as actor:
            memories = self._memory.summary(subject=actor, actor=actor, purpose="export")
            return {
                "format_version": 1, "subject": actor, "exported_at": timestamp(self.clock()),
                "memories": [dict(asdict(memory), history=self._memory.history(memory.id, actor=actor))
                             for memory in memories],
                "sharing": self.sharing(token),
                "care_circle": self._circle.list_members(actor=actor, subject=actor),
                "requests": self._owner_requests(actor),
                "events": self._requests.history(actor=actor, subject=actor),
            }

    def submit_knowledge(self, token: str, *, title: str, body: str, kind: str,
                         source: str, audience: str, setting: str, language: str,
                         limitations: str, publication_rights: str,
                         publication_authorized: bool = False) -> str:
        with self._actor(token) as actor:
            return self._knowledge.submit(
                contributor=actor, title=title, body=body, kind=kind, source=source,
                audience=audience, setting=setting, language=language, limitations=limitations,
                publication_rights=publication_rights, publication_authorized=publication_authorized)

    def knowledge_submissions(self, token: str) -> tuple[KnowledgeCard, ...]:
        with self._actor(token) as actor:
            return self._knowledge.submissions(actor=actor)

    def knowledge_evidence(self, token: str, card_id: str) -> dict:
        with self._actor(token) as actor:
            return self._knowledge.evidence(card_id, actor=actor)

    def review_knowledge(self, token: str, card_id: str, *, review_due: datetime,
                         privacy_checked: bool, scope_checked: bool, evidence: str,
                         qualification_id: str | None = None) -> None:
        with self._actor(token) as actor:
            self._knowledge.review(card_id, actor=actor, review_due=review_due,
                                   privacy_checked=privacy_checked, scope_checked=scope_checked,
                                   evidence=evidence, qualification_id=qualification_id)

    def withdraw_knowledge(self, token: str, card_id: str) -> None:
        with self._actor(token) as actor:
            self._knowledge.withdraw(card_id, actor=actor)

    def search_knowledge(self, token: str, query: str = "") -> tuple[KnowledgeCard, ...]:
        with self._actor(token):
            return self._knowledge.search(query)

    def record_qualification(self, token: str, *, reviewer: str, kind: str, setting: str,
                             language: str, evidence: str, expires_at: datetime,
                             idempotency_key: str) -> str:
        with self._actor(token) as actor:
            return self._qualifications.record(actor=actor, reviewer=reviewer, kind=kind,
                setting=setting, language=language, evidence=evidence, expires_at=expires_at,
                idempotency_key=idempotency_key)

    def qualifications(self, token: str, *, reviewer: str) -> list[dict]:
        with self._actor(token) as actor:
            return self._qualifications.list_records(actor=actor, reviewer=reviewer)

    def revoke_qualification(self, token: str, qualification_id: str) -> None:
        with self._actor(token) as actor:
            self._qualifications.revoke(qualification_id, actor=actor)

    def enqueue_delivery(self, token: str, request_id: str, *, provider: str) -> str:
        """Queue external delivery after explicit recipient and provider grants."""
        with self._actor(token) as actor:
            return OutboxService(self.store, self.clock).enqueue(request_id, actor=actor, provider=provider)

    def approve_external_request(self, token: str, request_id: str, *, provider: str,
                                 expires_at: datetime) -> str:
        """Approve the exact preview and queue external delivery atomically.

        The host configures provider identities. Before calling, show the person
        the message, all pinned context, supporter, purpose, provider and expiry.
        This creates a pending job; only a separate worker may contact a provider.
        Like local approval, repeated approval conflicts rather than renewing grants.
        """
        with self._actor(token) as actor:
            if provider not in self._delivery_providers:
                raise AccessDenied('Choose a configured delivery provider')
            request = self._requests.read(request_id, actor=actor)
            self._consent.require_owner(actor, request.subject)
            if request.state != RequestState.DRAFT:
                raise Conflict('This draft has already been handled; check its current status')
            self._circle.require_member(actor, request.recipient)
            self.authorize_delivery_provider(token, request_id, provider=provider, expires_at=expires_at)
            scopes = [('request', request_id, Operation.READ), ('request', request_id, Operation.ACT)]
            for memory in request.context:
                scopes.extend((('memory', memory.id, Operation.READ), ('memory', memory.id, Operation.SHARE)))
            for resource_type, resource_id, operation in scopes:
                self._consent.grant(actor=actor, subject=actor, recipient=request.recipient,
                                    purpose=request.purpose, resource_type=resource_type,
                                    resource_id=resource_id, operation=operation, expires_at=expires_at)
            self._requests.queue(request_id, actor=actor)
            return OutboxService(self.store, self.clock).enqueue(request_id, actor=actor, provider=provider)

    def deliveries(self, token: str) -> list[dict]:
        with self._actor(token) as actor:
            return OutboxService(self.store, self.clock).jobs(actor=actor)

    def authorize_delivery_provider(self, token: str, request_id: str, *, provider: str,
                                    expires_at: datetime) -> None:
        """Approve disclosure of the previewed request and context to this provider.

        This does not grant provider action authority or care-circle membership.
        """
        required(provider, "provider")
        with self._actor(token) as actor:
            row = self._requests._row(request_id)
            self._consent.require_owner(actor, row["subject"])
            if row["state"] not in ("draft", "queued"):
                raise Conflict("Provider consent requires an unfinished delivery draft")
            if provider in (actor, row["recipient"]):
                raise ValueError("Use a distinct transport provider identity")
            request = self._requests.read(request_id, actor=actor)
            resources = [("request", request_id)] + [("memory", memory.id) for memory in request.context]
            for resource_type, resource_id in resources:
                for operation in (Operation.READ, Operation.SHARE):
                    existing = self.store.connection.execute("""SELECT 1 FROM grants WHERE subject=?
                        AND recipient=? AND purpose=? AND resource_type=? AND resource_id=? AND operation=?
                        AND expires_at=? AND expires_at>? AND revoked_at IS NULL""",
                        (actor, provider, request.purpose, resource_type, resource_id, operation.value,
                         timestamp(expires_at), timestamp(self.clock()))).fetchone()
                    if existing:
                        continue
                    self._consent.grant(actor=actor, subject=actor, recipient=provider, purpose=request.purpose,
                        resource_type=resource_type, resource_id=resource_id, operation=operation, expires_at=expires_at)
