"""A local mailbox with explicit delivery, acceptance, and completion states."""

from sqlite3 import Row
from uuid import uuid4

from .consent import ConsentService
from .domain import AccessDenied, Clock, Conflict, Memory, Operation, RequestState, SupportRequest, required, timestamp, utc_now
from .memory import MemoryService
from .store import SQLiteStore


class DelegationService:
    def __init__(self, store: SQLiteStore, consent: ConsentService,
                 memory: MemoryService, clock: Clock = utc_now) -> None:
        self.store, self.consent, self.memory, self.clock = store, consent, memory, clock

    def _row(self, request_id: str) -> Row:
        row = self.store.connection.execute("SELECT * FROM requests WHERE id=?", (request_id,)).fetchone()
        if row is None:
            raise AccessDenied("Request unavailable")
        return row

    def _context(self, row: Row, actor: str) -> tuple[Memory, ...]:
        result = []
        for link in self.store.connection.execute(
            "SELECT * FROM request_context WHERE request_id=? ORDER BY memory_id", (row["id"],)):
            memory = self.memory._read(link["memory_id"], actor, row["purpose"])
            # A previously approved handover must not silently change its contents.
            if memory.revision != link["revision"]:
                raise Conflict("Context changed; create and approve a new request")
            self.consent.require(subject=row["subject"], actor=actor, purpose=row["purpose"],
                                 resource_type="memory", resource_id=memory.id, operation=Operation.SHARE)
            result.append(memory)
        return tuple(result)

    def _recipient_access(self, row: Row, *, act: bool = False) -> tuple[Memory, ...]:
        self.consent.require(subject=row["subject"], actor=row["recipient"], purpose=row["purpose"],
                             resource_type="request", resource_id=row["id"], operation=Operation.READ)
        if act:
            self.consent.require(subject=row["subject"], actor=row["recipient"], purpose=row["purpose"],
                                 resource_type="request", resource_id=row["id"], operation=Operation.ACT)
        return self._context(row, row["recipient"])

    def create(self, *, actor: str, subject: str, recipient: str, purpose: str,
               message: str, idempotency_key: str, memory_ids: tuple[str, ...] = ()) -> str:
        """Store the exact message the person can preview before granting access."""
        self.consent.require_owner(actor, subject)
        for label, value in (("subject", subject), ("recipient", recipient), ("purpose", purpose),
                             ("message", message), ("idempotency_key", idempotency_key)):
            required(value, label)
        if recipient == subject:
            raise ValueError("Choose a separate support recipient")
        ids = sorted(set(memory_ids))
        with self.store.transaction() as db:
            prior = db.execute("SELECT * FROM requests WHERE subject=? AND idempotency_key=?",
                               (subject, idempotency_key)).fetchone()
            if prior is not None:
                prior_ids = [r[0] for r in db.execute(
                    "SELECT memory_id FROM request_context WHERE request_id=? ORDER BY memory_id", (prior["id"],))]
                if (prior["recipient"], prior["purpose"], prior["message"], prior_ids) != (recipient, purpose, message, ids):
                    raise Conflict("Idempotency key already used for a different request")
                return prior["id"]
            memories = [self.memory._read(mid, actor, purpose) for mid in ids]
            if any(m.subject != subject for m in memories):
                raise AccessDenied("Context must belong to this person")
            request_id, at = str(uuid4()), timestamp(self.clock())
            db.execute("INSERT INTO requests VALUES (?, ?, ?, ?, ?, 'draft', ?, ?, ?)",
                       (request_id, subject, recipient, purpose, message, idempotency_key, at, at))
            db.executemany("INSERT INTO request_context VALUES (?, ?, ?)",
                           [(request_id, m.id, m.revision) for m in memories])
            self.store.event(subject, actor, request_id, "request.draft", at)
            return request_id

    def _set_state(self, row: Row, actor: str, state: RequestState) -> None:
        at = timestamp(self.clock())
        self.store.connection.execute("UPDATE requests SET state=?, updated_at=? WHERE id=?",
                                      (state.value, at, row["id"]))
        self.store.event(row["subject"], actor, row["id"], f"request.{state.value}", at)

    def queue(self, request_id: str, *, actor: str) -> None:
        with self.store.transaction():
            row = self._row(request_id)
            self.consent.require_owner(actor, row["subject"])
            if row["state"] == "queued":
                self._recipient_access(row, act=True)
                return
            if row["state"] != "draft":
                raise Conflict("Only a draft can be queued")
            self._recipient_access(row, act=True)
            self._set_state(row, actor, RequestState.QUEUED)

    def dispatch(self, request_id: str, *, actor: str) -> RequestState:
        """Deliver to the local mailbox only. No network transport is implied."""
        with self.store.transaction():
            row = self._row(request_id)
            self.consent.require_owner(actor, row["subject"])
            if row["state"] != "queued":
                return RequestState(row["state"])
            if self.store.connection.execute('SELECT 1 FROM delivery_jobs WHERE request_id=?', (request_id,)).fetchone():
                raise Conflict('This request uses the external delivery outbox')
            try:
                self._recipient_access(row, act=True)
            except (AccessDenied, Conflict):
                self._set_state(row, actor, RequestState.BLOCKED)
                return RequestState.BLOCKED
            self._set_state(row, actor, RequestState.DELIVERED)
            return RequestState.DELIVERED

    def read(self, request_id: str, *, actor: str) -> SupportRequest:
        with self.store.transaction():
            row = self._row(request_id)
            if actor == row["subject"]:
                context = self._context(row, actor)
            elif actor == row["recipient"] and row["state"] in ("delivered", "accepted", "completed"):
                context = self._recipient_access(row)
            else:
                raise AccessDenied("Request unavailable")
            return SupportRequest(row["id"], row["subject"], row["recipient"], row["purpose"],
                                  row["message"], RequestState(row["state"]), context,
                                  row["created_at"], row["updated_at"])

    def transition(self, request_id: str, *, actor: str, state: RequestState) -> None:
        state = RequestState(state)
        with self.store.transaction():
            row = self._row(request_id)
            if state == RequestState.CANCELLED:
                self.consent.require_owner(actor, row["subject"])
                if row["state"] == "completed":
                    raise Conflict("A completed request cannot be cancelled")
            else:
                if actor != row["recipient"]:
                    raise AccessDenied("Only the chosen recipient may accept or complete")
                self._recipient_access(row, act=True)
                predecessors = {RequestState.ACCEPTED: "delivered", RequestState.COMPLETED: "accepted"}
                if state not in predecessors or row["state"] not in (predecessors[state], state.value):
                    raise Conflict("Invalid request transition")
            if row["state"] != state.value:
                self._set_state(row, actor, state)

    def history(self, *, actor: str, subject: str) -> list[dict]:
        """Owner-only metadata remains readable even when context is no longer usable."""
        self.consent.require_owner(actor, subject)
        return [dict(row) for row in self.store.connection.execute(
            "SELECT * FROM events WHERE subject=? ORDER BY sequence", (subject,))]
