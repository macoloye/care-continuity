"""People directory and relationship setup for the trusted local adapter.

Administration here manages directory records only: the service offers no
method that reads care data or creates grants. Care-circle membership remains
a contribution boundary, and only the person's own sharing decisions disclose
anything.
"""

import re

from .circle import CircleService
from .domain import AccessDenied, Clock, Conflict, required, timestamp, utc_now
from .store import SQLiteStore

KINDS = ("person", "carer")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")


class DirectoryService:
    """The setup surface behind the local profile chooser and admin console.

    ``operator`` names the setup actor recorded in audit events; the local
    adapter passes its fixed setup identity, never a client-supplied actor.
    """

    def __init__(self, store: SQLiteStore, circle: CircleService, clock: Clock = utc_now) -> None:
        self.store, self.circle, self.clock = store, circle, clock

    def ensure_person(self, *, person_id: str, name: str, kind: str) -> None:
        """Idempotent local seed used at startup; audits only a first creation."""
        at = timestamp(self.clock())
        with self.store.transaction() as db:
            cursor = db.execute("INSERT INTO people VALUES (?, ?, ?, ?) ON CONFLICT(id) DO NOTHING",
                                (person_id, name, kind, at))
            if cursor.rowcount:
                self.store.event(person_id, "local-setup", person_id, "person.created", at)

    def create_person(self, *, operator: str, person_id: str, name: str, kind: str) -> dict:
        """Add a person to the local directory; creates no records and no access."""
        required(person_id, "person_id")
        required(name, "name")
        if not _ID.match(person_id):
            raise ValueError("Use 1–32 lowercase letters, digits or hyphens as the profile id")
        name = name.strip()
        if len(name) > 60:
            raise ValueError("Keep the display name under 60 characters")
        if kind == "reviewer":
            raise ValueError("Reviewer authority is configured by the host, not added here")
        if kind not in KINDS:
            raise ValueError("Choose a person receiving support or a carer")
        at = timestamp(self.clock())
        with self.store.transaction() as db:
            if db.execute("SELECT 1 FROM people WHERE id=?", (person_id,)).fetchone():
                raise Conflict("This profile id is already in use")
            db.execute("INSERT INTO people VALUES (?, ?, ?, ?)", (person_id, name, kind, at))
            self.store.event(person_id, operator, person_id, "person.created", at)
        return {"id": person_id, "name": name, "kind": kind, "created_at": at}

    def people(self) -> list[dict]:
        return [dict(row) for row in self.store.connection.execute(
            "SELECT * FROM people ORDER BY created_at, id")]

    def names(self) -> dict[str, str]:
        return {person["id"]: person["name"] for person in self.people()}

    def reviewers(self) -> frozenset[str]:
        """Host-configured editorial identities; setup cannot create them."""
        return frozenset(person["id"] for person in self.people() if person["kind"] == "reviewer")

    def require_person(self, person_id: str) -> dict:
        row = self.store.connection.execute("SELECT * FROM people WHERE id=?", (person_id,)).fetchone()
        if row is None:
            raise AccessDenied("Profile unavailable")
        return dict(row)

    def relationships(self) -> list[dict]:
        return [dict(row) for row in self.store.connection.execute(
            "SELECT * FROM care_circle ORDER BY subject, member")]

    def set_relationship(self, *, operator: str, subject: str, member: str, role: str) -> None:
        """Record or change who belongs to a person's care circle."""
        with self.store.transaction():
            self.require_person(subject)
            self.require_person(member)
            self.circle.set_membership(operator=operator, subject=subject, member=member, role=role)

    def end_relationship(self, *, operator: str, subject: str, member: str) -> None:
        """End a relationship with the person's own revocations, audited to the operator."""
        with self.store.transaction():
            self.require_person(subject)
            self.require_person(member)
            self.circle.end_membership(operator=operator, subject=subject, member=member)
