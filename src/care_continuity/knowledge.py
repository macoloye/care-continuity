"""Public knowledge cards with an explicit editorial gate."""

from datetime import datetime
from uuid import uuid4

from .domain import AccessDenied, Clock, Conflict, KnowledgeCard, required, timestamp, utc_now
from .store import SQLiteStore


class KnowledgeService:
    def __init__(self, store: SQLiteStore, *, reviewers: frozenset[str] = frozenset(),
                 clock: Clock = utc_now) -> None:
        self.store, self.reviewers, self.clock = store, reviewers, clock

    def submit(self, *, contributor: str, title: str, body: str, kind: str,
               source: str, publication_authorized: bool = False) -> str:
        """Accept a separately authorized submission, never import personal memory."""
        if not publication_authorized:
            raise AccessDenied("Separate publication authorization is required")
        if kind not in ("experience", "procedure", "guidance"):
            raise ValueError("Unknown knowledge kind")
        for label, value in (("contributor", contributor), ("title", title), ("body", body), ("source", source)):
            required(value, label)
        card_id = str(uuid4())
        with self.store.transaction() as db:
            db.execute("INSERT INTO knowledge(id, title, body, kind, source, contributor) VALUES (?, ?, ?, ?, ?, ?)",
                       (card_id, title, body, kind, source, contributor))
        return card_id

    def review(self, card_id: str, *, actor: str, review_due: datetime,
               privacy_checked: bool, scope_checked: bool) -> None:
        if actor not in self.reviewers:
            raise AccessDenied("Reviewer authority required")
        if not privacy_checked or not scope_checked:
            raise ValueError("Privacy and scope review are required")
        due = timestamp(review_due)
        if due <= timestamp(self.clock()):
            raise ValueError("Review due date must be in the future")
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM knowledge WHERE id=?", (card_id,)).fetchone()
            if row is None:
                raise AccessDenied("Card unavailable")
            if row["contributor"] == actor:
                raise AccessDenied("A separate reviewer is required")
            if row["kind"] == "guidance":
                raise Conflict("Professional guidance publication is not implemented; qualified review is required")
            db.execute("UPDATE knowledge SET reviewer=?, review_due=?, status='reviewed' WHERE id=?",
                       (actor, due, card_id))

    def withdraw(self, card_id: str, *, actor: str) -> None:
        if actor not in self.reviewers:
            raise AccessDenied("Reviewer authority required")
        with self.store.transaction() as db:
            result = db.execute("UPDATE knowledge SET status='withdrawn' WHERE id=?", (card_id,))
            if result.rowcount != 1:
                raise AccessDenied("Card unavailable")

    def search(self, query: str = "") -> tuple[KnowledgeCard, ...]:
        """Literal substring search; expired and withdrawn cards are excluded."""
        rows = self.store.connection.execute(
            "SELECT * FROM knowledge WHERE status='reviewed' AND review_due > ? ORDER BY title, id",
            (timestamp(self.clock()),)).fetchall()
        needle = query.casefold()
        return tuple(KnowledgeCard(**dict(row)) for row in rows
                     if needle in (row["title"] + " " + row["body"]).casefold())
