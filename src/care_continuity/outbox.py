"""Durable outbound jobs. Network calls happen outside SQLite transactions."""

from datetime import timedelta
from enum import Enum
from typing import Callable
from uuid import uuid4

from .consent import ConsentService
from .delegation import DelegationService
from .domain import AccessDenied, Clock, Conflict, Operation, RequestState, SupportRequest, required, timestamp, utc_now
from .memory import MemoryService
from .store import SQLiteStore


class DeliveryResult(str, Enum):
    RECEIVED = "received"  # Provider receipt, never human acceptance.
    NOT_SENT = "not_sent"  # Adapter guarantees no disclosure occurred; safe to retry.
    UNKNOWN = "unknown"    # May have sent; never automatically resend.


class OutboxService:
    """Privileged worker API; adapters receive an authorized payload and stable job ID.

    Adapters must enforce provider idempotency using that ID. Exceptions and expired
    leases are ambiguous outcomes, not permission to retry. Transport errors are not stored.
    """

    def __init__(self, store: SQLiteStore, clock: Clock = utc_now) -> None:
        self.store, self.clock = store, clock
        self.consent = ConsentService(store, clock)
        self.requests = DelegationService(store, self.consent, MemoryService(store, self.consent, clock), clock)

    def _authorized(self, request_id: str, provider: str) -> SupportRequest:
        row = self.requests._row(request_id)
        if row['state'] != 'queued':
            raise Conflict('Only a queued request can be sent')
        context = self.requests._recipient_access(row, act=True)
        # The transport provider is itself a separate disclosure recipient.
        for operation in (Operation.READ, Operation.SHARE):
            self.consent.require(subject=row['subject'], actor=provider, purpose=row['purpose'],
                                 resource_type='request', resource_id=request_id, operation=operation)
        for memory in context:
            for operation in (Operation.READ, Operation.SHARE):
                self.consent.require(subject=row['subject'], actor=provider, purpose=row['purpose'],
                                     resource_type='memory', resource_id=memory.id, operation=operation)
        return SupportRequest(row['id'], row['subject'], row['recipient'], row['purpose'], row['message'],
                              RequestState.QUEUED, context, row['created_at'], row['updated_at'])

    def enqueue(self, request_id: str, *, actor: str, provider: str) -> str:
        required(provider, 'provider')
        with self.store.transaction() as db:
            row = self.requests._row(request_id)
            self.consent.require_owner(actor, row['subject'])
            if provider in (row['subject'], row['recipient']):
                raise ValueError('Use a distinct transport provider identity')
            previous = db.execute('SELECT * FROM delivery_jobs WHERE request_id=?', (request_id,)).fetchone()
            if previous:
                if previous['provider'] != provider:
                    raise Conflict('This request already has a delivery provider')
                return previous['id']
            self._authorized(request_id, provider)
            job_id, at = str(uuid4()), timestamp(self.clock())
            db.execute("""INSERT INTO delivery_jobs
                (id,request_id,provider,state,attempts,available_at) VALUES (?,?,?,'pending',0,?)""",
                (job_id, request_id, provider, at))
            self.store.event(row['subject'], actor, job_id, 'delivery.queued', at)
            return job_id

    def jobs(self, *, actor: str) -> list[dict]:
        with self.store.transaction() as db:
            return [dict(row) for row in db.execute("""SELECT j.id,j.request_id,j.provider,j.state,j.attempts,
                j.available_at,j.lease_until,r.state AS request_state,r.recipient
                FROM delivery_jobs j JOIN requests r ON r.id=j.request_id
                WHERE r.subject=? ORDER BY j.available_at,j.id""", (actor,))]

    def run_one(self, *, provider: str,
                send: Callable[[str, SupportRequest], DeliveryResult]) -> str | None:
        """Send at most one job; a receipt moves queued to delivered, never accepted."""
        if self.store.connection.in_transaction:
            raise Conflict('Run the worker outside an application transaction')
        with self.store.transaction() as db:
            at = timestamp(self.clock())
            # A crashed worker may have transmitted. Never steal and resend its job.
            expired = db.execute("SELECT id,attempts FROM delivery_jobs WHERE state='sending' AND lease_until<=?",
                                 (at,)).fetchall()
            for job in expired:
                db.execute("UPDATE delivery_jobs SET state='unknown' WHERE id=?", (job['id'],))
                db.execute("UPDATE delivery_attempts SET outcome='unknown',finished_at=? WHERE job_id=? AND number=?",
                           (at, job['id'], job['attempts']))
            job = db.execute("""SELECT * FROM delivery_jobs WHERE provider=? AND state='pending'
                AND available_at<=? ORDER BY available_at,id LIMIT 1""", (provider, at)).fetchone()
            if job is None:
                return None
            try:
                payload = self._authorized(job['request_id'], provider)
            except (AccessDenied, Conflict):
                db.execute("UPDATE delivery_jobs SET state='blocked' WHERE id=?", (job['id'],))
                row = self.requests._row(job['request_id'])
                if row['state'] == 'queued':
                    self.requests._set_state(row, row['subject'], RequestState.BLOCKED)
                return job['id']
            lease = str(uuid4())
            attempt = job['attempts'] + 1
            db.execute("""UPDATE delivery_jobs SET state='sending',attempts=?,lease_token=?,lease_until=? WHERE id=?""",
                       (attempt, lease, timestamp(self.clock() + timedelta(minutes=5)), job['id']))
            db.execute("INSERT INTO delivery_attempts VALUES (?, ?, ?, NULL, 'sending')", (job['id'], attempt, at))
        try:
            outcome = DeliveryResult(send(job['id'], payload))
        except Exception:
            # Provider exceptions can contain care text. Do not log or persist them.
            outcome = DeliveryResult.UNKNOWN
        with self.store.transaction() as db:
            current = db.execute('SELECT * FROM delivery_jobs WHERE id=?', (job['id'],)).fetchone()
            if current['state'] != 'sending' or current['lease_token'] != lease:
                return job['id']
            at = timestamp(self.clock())
            state = ('received' if outcome == DeliveryResult.RECEIVED else
                     'pending' if outcome == DeliveryResult.NOT_SENT and attempt < 3 else
                     'failed' if outcome == DeliveryResult.NOT_SENT else 'unknown')
            db.execute("""UPDATE delivery_jobs SET state=?,available_at=?,lease_until=NULL,lease_token=NULL WHERE id=?""",
                       (state, timestamp(self.clock() + timedelta(minutes=1)), job['id']))
            db.execute('UPDATE delivery_attempts SET outcome=?,finished_at=? WHERE job_id=? AND number=?',
                       (outcome.value, at, job['id'], attempt))
            row = self.requests._row(job['request_id'])
            if outcome == DeliveryResult.RECEIVED and row['state'] == 'queued':
                try:
                    self._authorized(job['request_id'], provider)
                except (AccessDenied, Conflict):
                    self.requests._set_state(row, row['subject'], RequestState.BLOCKED)
                else:
                    self.requests._set_state(row, row['subject'], RequestState.DELIVERED)
            self.store.event(row['subject'], provider, job['id'], 'delivery.' + state, at)
        return job['id']

    def reconcile(self, job_id: str, *, provider: str,
                  lookup: Callable[[str], DeliveryResult]) -> str:
        """Resolve an unknown outcome through a trusted provider's receipt lookup.

        Lookup receives only the stable job ID. NOT_SENT must mean the original
        operation is definitively closed without delivery, not merely absent from
        an eventually consistent receipt index. No payload is sent by this method.
        """
        if self.store.connection.in_transaction:
            raise Conflict('Run receipt lookup outside an application transaction')
        with self.store.transaction() as db:
            job = db.execute('SELECT * FROM delivery_jobs WHERE id=? AND provider=?',
                             (job_id, provider)).fetchone()
            if job is None:
                raise AccessDenied('Delivery job unavailable')
            if job['state'] != 'unknown':
                return job['state']
            attempt = job['attempts']
        try:
            result = DeliveryResult(lookup(job_id))
        except Exception:
            result = DeliveryResult.UNKNOWN
        with self.store.transaction() as db:
            current = db.execute('SELECT * FROM delivery_jobs WHERE id=?', (job_id,)).fetchone()
            # Another reconciliation or a later attempt wins over a stale lookup.
            if current['state'] != 'unknown' or current['attempts'] != attempt:
                return current['state']
            if result == DeliveryResult.UNKNOWN:
                return 'unknown'
            row = self.requests._row(job['request_id'])
            authorized = False
            if row['state'] == 'queued':
                try:
                    self._authorized(job['request_id'], provider)
                    authorized = True
                except (AccessDenied, Conflict):
                    self.requests._set_state(row, row['subject'], RequestState.BLOCKED)
            if result == DeliveryResult.RECEIVED:
                state = 'received'
                if authorized:
                    self.requests._set_state(row, row['subject'], RequestState.DELIVERED)
            else:
                state = 'blocked' if not authorized else 'pending' if attempt < 3 else 'failed'
            at = timestamp(self.clock())
            db.execute("""UPDATE delivery_jobs SET state=?,available_at=?,lease_until=NULL,
                lease_token=NULL WHERE id=?""", (state, timestamp(self.clock() + timedelta(minutes=1)), job_id))
            # Preserve the attempt's original unknown outcome and record the later resolution.
            self.store.event(row['subject'], provider, job_id, 'delivery.reconciled.' + result.value, at)
            return state
