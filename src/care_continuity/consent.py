"""Explicit, recipient-specific grants; no role-based or family defaults."""

from datetime import datetime
from uuid import uuid4

from .domain import AccessDenied, Clock, Operation, required, timestamp, utc_now
from .store import SQLiteStore


class ConsentService:
    def __init__(self, store: SQLiteStore, clock: Clock = utc_now) -> None:
        self.store, self.clock = store, clock

    @staticmethod
    def require_owner(actor: str, subject: str) -> None:
        if actor != subject:
            raise AccessDenied("Only the person may change this record")

    def allows(self, *, subject: str, actor: str, purpose: str,
               resource_type: str, resource_id: str, operation: Operation) -> bool:
        if actor == subject:
            return True
        if self.store.connection.execute(
            "SELECT 1 FROM care_circle WHERE subject=? AND member=? AND removed_at IS NOT NULL",
            (subject, actor),
        ).fetchone():
            return False
        row = self.store.connection.execute(
            """SELECT 1 FROM grants WHERE subject=? AND recipient=? AND purpose=?
            AND resource_type=? AND resource_id=? AND operation=?
            AND revoked_at IS NULL AND expires_at > ? LIMIT 1""",
            (subject, actor, purpose, resource_type, resource_id,
             Operation(operation).value, timestamp(self.clock())),
        ).fetchone()
        return row is not None

    def require(self, *, subject: str, actor: str, purpose: str,
                resource_type: str, resource_id: str, operation: Operation) -> None:
        if not self.allows(subject=subject, actor=actor, purpose=purpose,
                           resource_type=resource_type, resource_id=resource_id, operation=operation):
            raise AccessDenied("No current permission for this use")

    def grant(self, *, actor: str, subject: str, recipient: str, purpose: str,
              resource_type: str, resource_id: str, operation: Operation,
              expires_at: datetime) -> str:
        self.require_owner(actor, subject)
        required(recipient, "recipient")
        required(purpose, "purpose")
        operation = Operation(operation)
        tables = {"memory": "memories", "request": "requests"}
        if resource_type not in tables:
            raise ValueError("Unknown resource type")
        if resource_type == "memory" and operation == Operation.ACT:
            raise ValueError("Memory does not support action permission")
        at, expiry = timestamp(self.clock()), timestamp(expires_at)
        if expiry <= at:
            raise ValueError("Permission must expire in the future")
        grant_id = str(uuid4())
        with self.store.transaction() as db:
            if db.execute("SELECT 1 FROM care_circle WHERE subject=? AND member=? AND removed_at IS NOT NULL",
                          (subject, recipient)).fetchone():
                raise AccessDenied("Recipient has left this care circle")
            row = db.execute(f"SELECT * FROM {tables[resource_type]} WHERE id=?", (resource_id,)).fetchone()
            if row is None or row["subject"] != subject or (resource_type == "memory" and row["deleted"]):
                raise AccessDenied("Resource unavailable")
            db.execute("INSERT INTO grants VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)",
                       (grant_id, subject, recipient, purpose, resource_type, resource_id,
                        operation.value, expiry, at))
            self.store.event(subject, actor, grant_id, "consent.granted", at)
        return grant_id

    def revoke(self, *, actor: str, grant_id: str) -> None:
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM grants WHERE id=?", (grant_id,)).fetchone()
            if row is None:
                raise AccessDenied("Permission unavailable")
            self.require_owner(actor, row["subject"])
            if row["revoked_at"] is None:
                at = timestamp(self.clock())
                db.execute("UPDATE grants SET revoked_at=? WHERE id=?", (at, grant_id))
                self.store.event(row["subject"], actor, grant_id, "consent.revoked", at)

    def list_grants(self, *, actor: str, subject: str) -> list[dict]:
        self.require_owner(actor, subject)
        return [dict(row) for row in self.store.connection.execute(
            "SELECT * FROM grants WHERE subject=? ORDER BY created_at, id", (subject,))]
