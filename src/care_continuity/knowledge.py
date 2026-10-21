"""Knowledge submissions with private evidence and an independent editorial gate."""

from datetime import datetime
from uuid import uuid4

from .domain import AccessDenied, Clock, Conflict, KnowledgeCard, required, timestamp, utc_now
from .store import SQLiteStore
from .qualifications import QualificationService


class KnowledgeService:
    def __init__(self, store: SQLiteStore, *, reviewers: frozenset[str] = frozenset(),
                 clock: Clock = utc_now) -> None:
        self.store, self.reviewers, self.clock = store, reviewers, clock

    def submit(self, *, contributor: str, title: str, body: str, kind: str,
               source: str, audience: str, setting: str, language: str,
               limitations: str, publication_rights: str,
               publication_authorized: bool = False) -> str:
        """Record explicit publication permission and its evidence; never import memory."""
        if publication_authorized is not True:
            raise AccessDenied("Separate publication authorization is required")
        if kind not in ("experience", "procedure", "guidance"):
            raise ValueError("Unknown knowledge kind")
        for label, value in (("contributor", contributor), ("title", title), ("body", body),
                             ("source", source), ("audience", audience), ("setting", setting),
                             ("language", language), ("limitations", limitations),
                             ("publication_rights", publication_rights)):
            required(value, label)
        card_id, at = str(uuid4()), timestamp(self.clock())
        with self.store.transaction() as db:
            db.execute("""INSERT INTO knowledge
                (id, title, body, kind, source, contributor, audience, setting, language,
                 limitations, submitted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (card_id, title, body, kind, source, contributor, audience, setting,
                 language, limitations, at))
            db.execute("INSERT INTO knowledge_publication_rights VALUES (?, ?, ?, ?)",
                       (card_id, contributor, publication_rights, at))
            self.store.event(contributor, contributor, card_id, "knowledge.submitted", at)
        return card_id

    def submissions(self, *, actor: str) -> tuple[KnowledgeCard, ...]:
        """Reviewers inspect all submissions; contributors inspect only their own."""
        with self.store.transaction() as db:
            rows = db.execute("""SELECT * FROM knowledge WHERE contributor=? OR ?
                ORDER BY submitted_at, id""", (actor, actor in self.reviewers)).fetchall()
            return tuple(KnowledgeCard(**dict(row)) for row in rows)

    def evidence(self, card_id: str, *, actor: str) -> dict:
        """Publication rights and review notes are private editorial records."""
        with self.store.transaction() as db:
            row = db.execute("SELECT contributor FROM knowledge WHERE id=?", (card_id,)).fetchone()
            if row is None or (row["contributor"] != actor and actor not in self.reviewers):
                raise AccessDenied("Card unavailable")
            rights = db.execute("SELECT * FROM knowledge_publication_rights WHERE card_id=?",
                                (card_id,)).fetchone()
            reviews = db.execute("""SELECT * FROM knowledge_reviews WHERE card_id=?
                ORDER BY reviewed_at, id""", (card_id,)).fetchall()
            return {"publication_rights": dict(rights) if rights else None,
                    "reviews": [dict(review) for review in reviews]}

    def review(self, card_id: str, *, actor: str, review_due: datetime,
               privacy_checked: bool, scope_checked: bool, evidence: str, qualification_id: str | None = None) -> None:
        if actor not in self.reviewers:
            raise AccessDenied("Reviewer authority required")
        if privacy_checked is not True or scope_checked is not True:
            raise ValueError("Privacy and scope review are required")
        required(evidence, "review evidence")
        due, at = timestamp(review_due), timestamp(self.clock())
        if due <= at:
            raise ValueError("Review due date must be in the future")
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM knowledge WHERE id=?", (card_id,)).fetchone()
            if row is None:
                raise AccessDenied("Card unavailable")
            if row["contributor"] == actor:
                raise AccessDenied("A separate reviewer is required")
            if row["status"] == "withdrawn":
                raise Conflict("Withdrawn cards cannot be republished; submit a new card")
            if row["kind"] == "guidance":
                raise Conflict("Professional guidance publication is not implemented; qualified review is required")
            if row["qualification_id"] is not None and qualification_id is None:
                raise Conflict("Renew this card with a current qualification; qualification evidence cannot be dropped")
            if qualification_id is not None:
                QualificationService(self.store, clock=self.clock).require(
                    qualification_id, reviewer=actor, kind=row["kind"], setting=row["setting"],
                    language=row["language"], review_due=review_due)
            rights = db.execute("SELECT 1 FROM knowledge_publication_rights WHERE card_id=?",
                                (card_id,)).fetchone()
            if not rights or any(not row[field].strip() for field in
                                 ("audience", "setting", "language", "limitations")):
                raise Conflict("Legacy cards require a new submission with metadata and publication rights")
            db.execute("INSERT INTO knowledge_reviews VALUES (?, ?, ?, ?, ?, ?, ?)",
                       (str(uuid4()), card_id, actor, evidence, at, due, qualification_id))
            db.execute("""UPDATE knowledge SET reviewer=?, review_due=?, status='reviewed',
                published_at=COALESCE(published_at, ?), qualification_id=? WHERE id=?""",
                (actor, due, at, qualification_id, card_id))
            self.store.event(row["contributor"], actor, card_id, "knowledge.reviewed", at)

    def withdraw(self, card_id: str, *, actor: str) -> None:
        """Either the contributor or an authorized reviewer may withdraw a card."""
        with self.store.transaction() as db:
            row = db.execute("SELECT * FROM knowledge WHERE id=?", (card_id,)).fetchone()
            if row is None or (row["contributor"] != actor and actor not in self.reviewers):
                raise AccessDenied("Card unavailable")
            if row["status"] != "withdrawn":
                db.execute("UPDATE knowledge SET status='withdrawn' WHERE id=?", (card_id,))
                self.store.event(row["contributor"], actor, card_id, "knowledge.withdrawn", timestamp(self.clock()))

    def search(self, query: str = "") -> tuple[KnowledgeCard, ...]:
        """Public catalogue only; audience describes applicability, not access control."""
        with self.store.transaction() as db:
            rows = db.execute("""SELECT * FROM knowledge WHERE status='reviewed'
                AND kind IN ('experience', 'procedure') AND published_at IS NOT NULL
                AND review_due > ? AND (qualification_id IS NULL OR EXISTS (
                    SELECT 1 FROM reviewer_qualifications q WHERE q.id=knowledge.qualification_id
                    AND q.revoked_at IS NULL AND q.expires_at > ?)) ORDER BY title, id""",
                (timestamp(self.clock()), timestamp(self.clock()))).fetchall()
            needle = query.casefold()
            return tuple(KnowledgeCard(**dict(row)) for row in rows
                         if needle in (row["title"] + " " + row["body"]).casefold())
