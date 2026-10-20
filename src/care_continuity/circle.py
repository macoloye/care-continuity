"""Membership records relationships; grants still control every disclosure."""

from .consent import ConsentService
from .domain import AccessDenied, Clock, required, timestamp, utc_now
from .store import SQLiteStore


class CircleService:
    def __init__(self, store: SQLiteStore, clock: Clock = utc_now) -> None:
        self.store, self.clock = store, clock

    def add(self, *, actor: str, subject: str, member: str, role: str) -> None:
        ConsentService.require_owner(actor, subject)
        required(member, "member")
        if member == subject or role not in ("supporter", "worker", "coordinator"):
            raise ValueError("Choose a separate member and a supported role")
        at = timestamp(self.clock())
        with self.store.transaction() as db:
            db.execute("""INSERT INTO care_circle VALUES (?, ?, ?, ?, NULL)
                       ON CONFLICT(subject, member) DO UPDATE SET
                       role=excluded.role, added_at=excluded.added_at, removed_at=NULL""",
                       (subject, member, role, at))
            self.store.event(subject, actor, member, "circle.added", at)

    def require_member(self, subject: str, member: str) -> None:
        row = self.store.connection.execute(
            "SELECT 1 FROM care_circle WHERE subject=? AND member=? AND removed_at IS NULL",
            (subject, member)).fetchone()
        if row is None:
            raise AccessDenied("Choose an active care-circle member")

    def remove(self, *, actor: str, subject: str, member: str) -> None:
        ConsentService.require_owner(actor, subject)
        with self.store.transaction() as db:
            self.require_member(subject, member)
            at = timestamp(self.clock())
            db.execute("UPDATE care_circle SET removed_at=? WHERE subject=? AND member=?", (at, subject, member))
            # Revoke all purposes and resources, not just the currently displayed grant.
            db.execute("UPDATE grants SET revoked_at=? WHERE subject=? AND recipient=? AND revoked_at IS NULL",
                       (at, subject, member))
            rows = db.execute("""SELECT id FROM requests WHERE subject=? AND recipient=?
                               AND state NOT IN ('completed', 'cancelled')""", (subject, member)).fetchall()
            for row in rows:
                db.execute("UPDATE requests SET state='cancelled', updated_at=? WHERE id=?", (at, row["id"]))
                self.store.event(subject, actor, row["id"], "request.cancelled", at)
            self.store.event(subject, actor, member, "circle.removed", at)

    def list_members(self, *, actor: str, subject: str) -> list[dict]:
        ConsentService.require_owner(actor, subject)
        return [dict(row) for row in self.store.connection.execute(
            "SELECT * FROM care_circle WHERE subject=? ORDER BY member", (subject,))]
