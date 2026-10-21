"""Private qualification attestations recorded by host-authorized verifiers."""

from datetime import datetime
from uuid import uuid4

from .domain import AccessDenied, Clock, Conflict, required, timestamp, utc_now
from .store import SQLiteStore


class QualificationService:
    """Records external checks; does not verify credentials with an issuing authority."""

    def __init__(self, store: SQLiteStore, *, verifiers: frozenset[str] = frozenset(),
                 clock: Clock = utc_now) -> None:
        self.store, self.verifiers, self.clock = store, verifiers, clock

    def record(self, *, actor: str, reviewer: str, kind: str, setting: str, language: str,
               evidence: str, expires_at: datetime, idempotency_key: str) -> str:
        """Record one exact scope after an independent external credential check."""
        with self.store.transaction() as db:
            if actor not in self.verifiers or actor == reviewer:
                raise AccessDenied("An independent qualification verifier is required")
            for label, value in (("reviewer", reviewer), ("setting", setting), ("language", language),
                                 ("evidence", evidence), ("idempotency_key", idempotency_key)):
                required(value, label)
            if kind not in ("experience", "procedure", "guidance"):
                raise ValueError("Unknown knowledge kind")
            expiry = timestamp(expires_at)
            previous = db.execute("SELECT * FROM reviewer_qualifications WHERE verifier=? AND idempotency_key=?",
                                  (actor, idempotency_key)).fetchone()
            fields = dict(reviewer=reviewer, kind=kind, setting=setting, language=language,
                          evidence=evidence, expires_at=expiry)
            if previous:
                if any(previous[key] != value for key, value in fields.items()):
                    raise Conflict("This qualification key was already used for different evidence")
                return previous["id"]
            at = timestamp(self.clock())
            if expiry <= at:
                raise ValueError("Qualification expiry must be in the future")
            record_id = str(uuid4())
            db.execute("""INSERT INTO reviewer_qualifications
                (id, reviewer, verifier, kind, setting, language, evidence, verified_at, expires_at, idempotency_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (record_id, reviewer, actor, kind, setting, language, evidence, at, expiry, idempotency_key))
            self.store.event(reviewer, actor, record_id, "qualification.recorded", at)
            return record_id

    def list_records(self, *, actor: str, reviewer: str) -> list[dict]:
        with self.store.transaction() as db:
            if actor != reviewer and actor not in self.verifiers:
                raise AccessDenied("Qualification records unavailable")
            at = timestamp(self.clock())
            return [dict(row, active=row["revoked_at"] is None and row["expires_at"] > at)
                    for row in db.execute("SELECT * FROM reviewer_qualifications WHERE reviewer=? ORDER BY verified_at, id",
                                          (reviewer,))]

    def revoke(self, qualification_id: str, *, actor: str) -> None:
        with self.store.transaction() as db:
            if actor not in self.verifiers:
                raise AccessDenied("Qualification verifier authority required")
            row = db.execute("SELECT * FROM reviewer_qualifications WHERE id=?", (qualification_id,)).fetchone()
            if row is None:
                raise AccessDenied("Qualification unavailable")
            if row["revoked_at"] is None:
                at = timestamp(self.clock())
                db.execute("UPDATE reviewer_qualifications SET revoked_at=? WHERE id=?", (at, qualification_id))
                self.store.event(row["reviewer"], actor, qualification_id, "qualification.revoked", at)

    def require(self, qualification_id: str, *, reviewer: str, kind: str, setting: str,
                language: str, review_due: datetime) -> None:
        """Check exact scope and coverage of the full review interval in a transaction."""
        with self.store.transaction() as db:
            row = db.execute("""SELECT * FROM reviewer_qualifications WHERE id=? AND reviewer=?
                AND kind=? AND setting=? AND language=? AND revoked_at IS NULL AND expires_at > ?""",
                (qualification_id, reviewer, kind, setting, language, timestamp(self.clock()))).fetchone()
            if row is None or row["expires_at"] < timestamp(review_due):
                raise AccessDenied("A current qualification covering this scope and review interval is required")
