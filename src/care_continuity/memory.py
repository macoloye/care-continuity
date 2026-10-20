"""Attributed memories, optimistic corrections, and reference-based summaries."""

from sqlite3 import Row
from uuid import uuid4

from .consent import ConsentService
from .domain import AccessDenied, Clock, Conflict, Memory, MemoryKind, Operation, required, timestamp, utc_now
from .store import SQLiteStore


class MemoryService:
    def __init__(self, store: SQLiteStore, consent: ConsentService, clock: Clock = utc_now) -> None:
        self.store, self.consent, self.clock = store, consent, clock

    @staticmethod
    def _record(row: Row) -> Memory:
        return Memory(row["id"], row["subject"], MemoryKind(row["kind"]), row["text"],
                      row["source"], bool(row["confirmed"]), row["revision"],
                      row["created_at"], row["updated_at"])

    def _read(self, memory_id: str, actor: str, purpose: str) -> Memory:
        row = self.store.connection.execute(
            "SELECT * FROM memories WHERE id=? AND deleted=0", (memory_id,)).fetchone()
        if row is None:
            raise AccessDenied("Memory unavailable")
        self.consent.require(subject=row["subject"], actor=actor, purpose=purpose,
                             resource_type="memory", resource_id=memory_id, operation=Operation.READ)
        return self._record(row)

    def remember(self, *, actor: str, subject: str, text: str, source: str,
                 kind: MemoryKind = MemoryKind.PREFERENCE, confirmed: bool = False) -> Memory:
        """The person approves storage; source identifies whose account is recorded."""
        self.consent.require_owner(actor, subject)
        required(subject, "subject")
        required(text, "text")
        required(source, "source")
        kind = MemoryKind(kind)
        if kind == MemoryKind.PREFERENCE and source != subject:
            raise ValueError("A preference must be attributed to the person")
        memory_id, at = str(uuid4()), timestamp(self.clock())
        with self.store.transaction() as db:
            db.execute("INSERT INTO memories VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, 0)",
                       (memory_id, subject, kind.value, text, source, bool(confirmed), at, at))
            db.execute("INSERT INTO memory_history VALUES (?, 1, ?, ?, ?, ?)",
                       (memory_id, text, source, bool(confirmed), at))
            self.store.event(subject, actor, memory_id, "memory.created", at)
            return self._read(memory_id, actor, "manage")

    def read(self, memory_id: str, *, actor: str, purpose: str) -> Memory:
        with self.store.transaction():
            return self._read(memory_id, actor, purpose)

    def revise(self, memory_id: str, *, actor: str, text: str,
               expected_revision: int, confirmed: bool = True) -> Memory:
        required(text, "text")
        with self.store.transaction() as db:
            current = self._read(memory_id, actor, "manage")
            self.consent.require_owner(actor, current.subject)
            if current.revision != expected_revision:
                raise Conflict("Memory changed; read the current revision first")
            revision, at = current.revision + 1, timestamp(self.clock())
            db.execute("UPDATE memories SET text=?, confirmed=?, revision=?, updated_at=? WHERE id=?",
                       (text, bool(confirmed), revision, at, memory_id))
            db.execute("INSERT INTO memory_history VALUES (?, ?, ?, ?, ?, ?)",
                       (memory_id, revision, text, current.source, bool(confirmed), at))
            self.store.event(current.subject, actor, memory_id, "memory.revised", at)
            return self._read(memory_id, actor, "manage")

    def summary(self, *, subject: str, actor: str, purpose: str) -> tuple[Memory, ...]:
        """Resolve current records on every call; never persist a copied summary."""
        with self.store.transaction() as db:
            rows = db.execute("SELECT * FROM memories WHERE subject=? AND deleted=0 ORDER BY created_at, id",
                              (subject,)).fetchall()
            return tuple(self._record(row) for row in rows if self.consent.allows(
                subject=subject, actor=actor, purpose=purpose, resource_type="memory",
                resource_id=row["id"], operation=Operation.READ))

    def history(self, memory_id: str, *, actor: str) -> list[dict]:
        with self.store.transaction() as db:
            memory = self._read(memory_id, actor, "manage")
            self.consent.require_owner(actor, memory.subject)
            return [dict(row) for row in db.execute(
                "SELECT * FROM memory_history WHERE memory_id=? ORDER BY revision", (memory_id,))]

    def forget(self, memory_id: str, *, actor: str) -> None:
        with self.store.transaction() as db:
            memory = self._read(memory_id, actor, "manage")
            self.consent.require_owner(actor, memory.subject)
            at = timestamp(self.clock())
            db.execute("DELETE FROM memory_history WHERE memory_id=?", (memory_id,))
            db.execute("UPDATE memories SET text='', source='', confirmed=0, deleted=1, updated_at=? WHERE id=?",
                       (at, memory_id))
            db.execute("UPDATE grants SET revoked_at=? WHERE resource_type='memory' AND resource_id=? AND revoked_at IS NULL",
                       (at, memory_id))
            # Linked drafts might quote the forgotten item. Redact them conservatively.
            db.execute("""UPDATE requests SET message='', updated_at=?,
                       state=CASE WHEN state='completed' THEN state ELSE 'cancelled' END
                       WHERE id IN (SELECT request_id FROM request_context WHERE memory_id=?)""",
                       (at, memory_id))
            db.execute("""UPDATE followups SET alternative='', updated_at=? WHERE request_id IN
                       (SELECT request_id FROM request_context WHERE memory_id=?)""", (at, memory_id))
            self.store.event(memory.subject, actor, memory_id, "memory.forgotten", at)
