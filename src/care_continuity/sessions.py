"""Revocable bearer sessions issued by a trusted identity adapter."""

from datetime import timedelta
from hashlib import sha256
from secrets import token_urlsafe

from .domain import AccessDenied, Clock, required, timestamp, utc_now
from .store import SQLiteStore


class SessionService:
    """Issuance is privileged: call only after verifying the person's identity."""

    def __init__(self, store: SQLiteStore, clock: Clock = utc_now) -> None:
        self.store, self.clock = store, clock

    @staticmethod
    def _digest(token: str) -> str:
        if not isinstance(token, str) or not token or len(token) > 256:
            raise AccessDenied("Session unavailable")
        return sha256(token.encode("utf-8")).hexdigest()

    def issue(self, verified_actor: str, *, lifetime: timedelta = timedelta(hours=8)) -> str:
        required(verified_actor, "verified_actor")
        if not timedelta(0) < lifetime <= timedelta(days=1):
            raise ValueError("Session lifetime must be positive and at most one day")
        token, now = token_urlsafe(32), self.clock()
        with self.store.transaction() as db:
            db.execute("INSERT INTO sessions VALUES (?, ?, ?, ?, NULL)",
                       (self._digest(token), verified_actor, timestamp(now), timestamp(now + lifetime)))
        return token

    def resolve(self, token: str) -> str:
        row = self.store.connection.execute(
            "SELECT actor FROM sessions WHERE token_hash=? AND revoked_at IS NULL AND expires_at > ?",
            (self._digest(token), timestamp(self.clock())),
        ).fetchone()
        if row is None:
            raise AccessDenied("Session unavailable")
        return row["actor"]

    def revoke(self, token: str) -> None:
        """Logout is idempotent, including for an expired session."""
        with self.store.transaction() as db:
            db.execute("UPDATE sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                       (timestamp(self.clock()), self._digest(token)))
